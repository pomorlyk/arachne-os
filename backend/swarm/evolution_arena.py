from __future__ import annotations

import asyncio
import copy
import hashlib
import ast
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import uuid
from typing import Any

from config import ArachneSettings
from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from core.llm_gateway import LLMGateway
from core.particles import ParticleEngine
from core.schemas import (
    ArenaReport as BaseArenaReport,
    ArenaSampleResult,
    ExtractedBallCandidate,
)
from swarm.pulse_bus import PulseBus
from swarm.scoring_engine import ScoringEngine

class ArenaReport(BaseArenaReport):
    source_hash: str = ""
    candidate_status: str = "REJECTED"
    validation_status: str = "UNVALIDATED"
    evidence_provenance: dict[str, Any] = {}


ALLOWED_STDLIB_MODULES = frozenset(
    {
        "math",
        "json",
        "re",
        "datetime",
        "decimal",
        "collections",
        "statistics",
    }
)

FORBIDDEN_BUILTIN_CALLS = frozenset(
    {
        "eval",
        "exec",
        "open",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "dir",
        "breakpoint",
        "input",
        "memoryview",
        "help",
    }
)

_CURRENCY_CLEAN_RE = re.compile(r"[¥￥$元RMBrmb,\s]")


class SandboxSecurityViolation(Exception):
    def __init__(self, violations: list[str]) -> None:
        self.violations = violations
        super().__init__("; ".join(violations))


def sandbox_ast_guard(source_code: str) -> list[str]:
    """
    第一层安全防线：AST 静态语法树白名单审查。
    1. 仅放行 ALLOWED_STDLIB_MODULES 中的纯计算标准库；
    2. 严禁调用 eval/exec/open/__import__/getattr 等危险内置函数；
    3. 严禁访问任何以 '__' 开头的双下划线魔术属性（彻底阻断 Python 对象原型链逃逸）；
    4. 强制要求定义顶层函数 execute_skill(payload)。
    """
    violations: list[str] = []
    try:
        tree = ast.parse(source_code)
    except SyntaxError as exc:
        raise SandboxSecurityViolation([f"Python 语法解析失败: {exc}"]) from exc

    has_entry_fn = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "execute_skill":
            has_entry_fn = True

        elif isinstance(node, ast.Import):
            for alias in node.names:
                root_mod = alias.name.split(".")[0]
                if root_mod not in ALLOWED_STDLIB_MODULES:
                    violations.append(f"禁止导入非白名单模块: '{alias.name}'")

        elif isinstance(node, ast.ImportFrom):
            root_mod = (node.module or "").split(".")[0]
            if root_mod not in ALLOWED_STDLIB_MODULES:
                violations.append(f"禁止从非白名单模块导入: '{node.module}'")

        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr.endswith("__"):
                violations.append(f"禁止访问双下划线魔术属性: '{node.attr}'（防沙箱逃逸拦截）")

        elif isinstance(node, ast.Name):
            if node.id.startswith("__") and node.id.endswith("__"):
                violations.append(f"禁止引用双下划线内置标识符: '{node.id}'")

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_BUILTIN_CALLS:
                violations.append(f"禁止调用高危内置函数: '{node.func.id}()'")
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in FORBIDDEN_BUILTIN_CALLS
            ):
                violations.append(f"禁止调用高危属性方法: '.{node.func.attr}()'")

    if not has_entry_fn:
        violations.append(
            "缺失强制标准入口函数定义: def execute_skill(payload: dict) -> dict"
        )

    if violations:
        raise SandboxSecurityViolation(violations)
    return []


def _has_meaningful_expected_output(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_meaningful_expected_output(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_meaningful_expected_output(item) for item in value)
    return isinstance(value, (bool, int, float, Decimal))


class NormalizedResultComparator:
    """
    结构化与数值归一化比对器（解决历史手工流水带货币符号/单位导致格式误杀问题）。
    例如标准答案 "18.00元" / "¥18" 与函数输出 {"status": "ok", "result": 18.0} 精确等价判定。
    """

    @staticmethod
    def _extract_core_value(val: Any) -> Any:
        if isinstance(val, dict):
            if "result" in val:
                return NormalizedResultComparator._extract_core_value(val["result"])
            for k in ("fee", "shipping_fee", "amount", "value", "total"):
                if k in val:
                    return val[k]
        return val

    @staticmethod
    def _try_decimal(val: Any) -> Decimal | None:
        if isinstance(val, bool):
            return None
        if isinstance(val, (int, float, Decimal)):
            try:
                return Decimal(str(val))
            except InvalidOperation:
                return None
        if isinstance(val, str):
            stripped = _CURRENCY_CLEAN_RE.sub("", val.strip())
            if not stripped:
                return None
            try:
                return Decimal(stripped)
            except InvalidOperation:
                return None
        return None

    @classmethod
    def is_equivalent(
        cls, expected: Any, actual_envelope: Any, tolerance: Decimal = Decimal("0.01")
    ) -> bool:
        def finite(value: Any) -> bool:
            if isinstance(value, (float, Decimal)):
                return Decimal(str(value)).is_finite()
            if isinstance(value, dict):
                return all(finite(v) for v in value.values())
            if isinstance(value, (list, tuple)):
                return all(finite(v) for v in value)
            return True

        if not finite(expected) or not finite(actual_envelope):
            return False
        if isinstance(expected, dict):
            if not expected:
                return actual_envelope == {} and isinstance(actual_envelope, dict)
            return isinstance(actual_envelope, dict) and all(
                key in actual_envelope
                and cls.is_equivalent(value, actual_envelope[key], tolerance)
                for key, value in expected.items()
            )
        if isinstance(expected, (list, tuple)):
            return (
                isinstance(actual_envelope, (list, tuple))
                and len(expected) == len(actual_envelope)
                and all(
                    cls.is_equivalent(e, a, tolerance)
                    for e, a in zip(expected, actual_envelope)
                )
            )
        core_exp = cls._extract_core_value(expected)
        core_act = cls._extract_core_value(actual_envelope)

        dec_exp = cls._try_decimal(core_exp)
        dec_act = cls._try_decimal(core_act)
        if dec_exp is not None and dec_act is not None:
            return (
                dec_exp.is_finite()
                and dec_act.is_finite()
                and abs(dec_exp - dec_act) <= tolerance
            )

        return str(core_exp).strip() == str(core_act).strip()


_SUBPROCESS_RUNNER_HARNESS = """
import importlib.util
import json
import os
import sys
import tracemalloc

script_path = sys.argv[1]
max_mem_mb = int(sys.argv[2]) if len(sys.argv) > 2 else 256
cpu_limit_sec = int(sys.argv[3]) if len(sys.argv) > 3 else 4
max_mem_bytes = max(32, max_mem_mb) * 1024 * 1024

sys.setrecursionlimit(200)

try:
    import resource

    try:
        soft_cpu, hard_cpu = resource.getrlimit(resource.RLIMIT_CPU)
        new_cpu = cpu_limit_sec if hard_cpu == resource.RLIM_INFINITY else min(cpu_limit_sec, hard_cpu)
        resource.setrlimit(resource.RLIMIT_CPU, (new_cpu, new_cpu))
    except (ValueError, OSError, AttributeError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    except (ValueError, OSError, AttributeError):
        pass
    try:
        soft_nf, hard_nf = resource.getrlimit(resource.RLIMIT_NOFILE)
        cap_nf = 64 if hard_nf == resource.RLIM_INFINITY else min(64, hard_nf)
        if cap_nf >= 16:
            resource.setrlimit(resource.RLIMIT_NOFILE, (cap_nf, cap_nf))
    except (ValueError, OSError, AttributeError):
        pass
    for r_name in ("RLIMIT_AS", "RLIMIT_DATA"):
        r_const = getattr(resource, r_name, None)
        if r_const is not None:
            try:
                _s, _h = resource.getrlimit(r_const)
                lim = max_mem_bytes if _h == resource.RLIM_INFINITY else min(max_mem_bytes, _h)
                resource.setrlimit(r_const, (lim, lim))
            except (ValueError, OSError, AttributeError):
                pass
except Exception:
    pass

cases = json.loads(sys.stdin.read())

spec = importlib.util.spec_from_file_location("candidate_skill", script_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

outputs = []
tracemalloc.start()
for payload in cases:
    try:
        res = mod.execute_skill(payload)
        _, peak_bytes = tracemalloc.get_traced_memory()
        if peak_bytes > max_mem_bytes:
            raise MemoryError(
                f"Sandbox memory limit exceeded: {peak_bytes // (1024 * 1024)}MB > {max_mem_mb}MB"
            )
        outputs.append({
            "ok": True,
            "output": res,
            "env_keys_leaked": [k for k in os.environ.keys() if "API_KEY" in k or "SECRET" in k],
        })
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        outputs.append({"ok": False, "output": None, "error": f"{type(exc).__name__}: {exc}", "env_keys_leaked": []})

sys.stdout.write(json.dumps(outputs, ensure_ascii=False))
"""


def run_skill_in_isolated_subprocess(
    script_path: Path,
    sandbox_dir: Path,
    input_payloads: list[dict[str, Any]],
    timeout_seconds: float = 3.0,
    max_memory_mb: int = 256,
    max_output_bytes: int = 65536,
) -> list[dict[str, Any]]:
    """
    第二层安全防线：使用 python -I 隔离模式 + 净空环境变量 + OS 资源配额 (rlimit / killpg / 输出上限)
    在 sandbox_workspace 子进程执行，彻底隔绝宿主机 .env 密钥并拦截死循环/内存炸弹/输出泛洪。
    """
    clean_env = {
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    cpu_cap = max(1, int(timeout_seconds) + 1)
    cmd = [
        sys.executable,
        "-I",
        "-c",
        _SUBPROCESS_RUNNER_HARNESS,
        str(script_path.resolve()),
        str(max_memory_mb),
        str(cpu_cap),
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(sandbox_dir.resolve()),
        env=clean_env,
        start_new_session=True,
    )
    in_bytes = json.dumps(input_payloads, ensure_ascii=False).encode("utf-8")
    try:
        stdout_bytes, stderr_bytes = proc.communicate(
            input=in_bytes, timeout=timeout_seconds
        )
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=1.0)
        except Exception:
            pass
        raise TimeoutError(
            f"Sandbox subprocess exceeded timeout ({timeout_seconds}s) and process group was killed"
        ) from exc

    if len(stdout_bytes) > max_output_bytes:
        raise RuntimeError(
            f"Sandbox stdout ({len(stdout_bytes)} bytes) exceeded max_output_bytes ({max_output_bytes})"
        )
    if proc.returncode != 0:
        err_text = stderr_bytes.decode("utf-8", errors="replace").strip()[:500]
        raise RuntimeError(
            f"Sandbox subprocess exited with code {proc.returncode}: {err_text}"
        )
    out_text = stdout_bytes.decode("utf-8", errors="replace")
    return list(json.loads(out_text))


class EvolutionArena:
    """
    达尔文自我进化中心 (ArtisanAgent + Shadow Arena)：
    口述痛点 -> 生成标准 Python 工具脚本 -> AST 白名单静态审查 -> 净室子进程历史黄金集回放 ->
    成功率 100% 且归一化吻合率 >= 98% 时自动晋升 ACTIVE 技能球并发放反向创新绩效加分！
    """

    def __init__(
        self,
        settings: ArachneSettings,
        vault: BlackBoxVault,
        particles: ParticleEngine,
        containers: ContainerRegistry,
        llm_gateway: LLMGateway,
        scoring: ScoringEngine,
        pulse_bus: PulseBus,
    ) -> None:
        self._settings = settings
        self._vault = vault
        self._particles = particles
        self._containers = containers
        self._llm = llm_gateway
        self._scoring = scoring
        self._pulse = pulse_bus
        self._reports: list[ArenaReport] = []
        self._candidates: dict[str, dict[str, Any]] = {}
        self._publication_lock = asyncio.Lock()

        self._sandbox_dir = Path(settings.sandbox_workspace_dir)
        self._sandbox_dir.mkdir(parents=True, exist_ok=True)

    def list_reports(self) -> list[ArenaReport]:
        return list(reversed(self._reports))

    def export_state(self) -> dict[str, Any]:
        return copy.deepcopy(
            {
                "reports": [r.model_dump() for r in self._reports],
                "candidates": self._candidates,
            }
        )

    def restore_state(self, payload: dict[str, Any]) -> None:
        self._reports = [
            ArenaReport.model_validate(r) for r in payload.get("reports", [])
        ]
        self._candidates = copy.deepcopy(payload.get("candidates", {}))
        for report in self._reports:
            candidate = self._candidates.get(report.proposal_id)
            if not candidate or not re.fullmatch(r"PROP_[A-F0-9]+", report.proposal_id):
                continue
            code = report.generated_code
            if hashlib.sha256(code.encode()).hexdigest() != candidate.get(
                "source_hash"
            ):
                continue
            path = self._sandbox_dir / f"skill_{report.proposal_id.lower()}.py"
            ball = self._particles.get_ball(candidate.get("ball_id", ""))
            # Active source belongs to the capability snapshot: it can have a newer validated revision.
            if ball and ball.status == "ACTIVE":
                current = (
                    self._sandbox_dir
                    / Path(ball.executable_code_path or path.name).name
                )
                if current.exists():
                    ball.executable_code_path = current.name
                    continue
            path.write_text(code, encoding="utf-8")
            if ball:
                ball.executable_code_path = path.name

    def register_candidate(
        self,
        *,
        proposal_id: str,
        ball_id: str,
        source_hash: str,
        source_code: str,
        proposer_id: str,
        target_slot_id: str,
    ) -> ArenaReport:
        """Register an unmounted composed candidate for the existing independent review workflow."""
        if not re.fullmatch(r"PROP_[A-F0-9]+", proposal_id):
            raise ValueError(
                "Candidate proposal ID must use PROP_<uppercase hexadecimal>"
            )
        if hashlib.sha256(source_code.encode()).hexdigest() != source_hash:
            raise ValueError("Candidate source hash does not match source")
        sandbox_ast_guard(source_code)
        self._containers.get_profile(proposer_id)
        self._containers.get_slot(target_slot_id)
        ball = self._particles.get_ball(ball_id)
        if ball is None or ball.ball_type != "SKILL" or ball.status != "CANDIDATE":
            raise ValueError(
                "Independent registration requires an existing CANDIDATE skill"
            )
        if target_slot_id not in ball.owner_slot_ids:
            raise ValueError("Candidate target slot is not a declared owner")
        existing = self._candidates.get(proposal_id)
        if existing is not None:
            expected = {
                "ball_id": ball_id,
                "source_hash": source_hash,
                "proposer_id": proposer_id,
                "target_slot_id": target_slot_id,
            }
            if any(existing.get(key) != value for key, value in expected.items()):
                raise ValueError("Proposal ID already belongs to a different candidate")
            report = next(
                (
                    report
                    for report in self._reports
                    if report.proposal_id == proposal_id
                ),
                None,
            )
            if report is None:
                raise ValueError("Candidate registry is missing its review report")
            return report
        path = self._sandbox_dir / f"skill_{proposal_id.lower()}.py"
        path.write_text(source_code, encoding="utf-8")
        ball.executable_code_path = path.name
        self._candidates[proposal_id] = {
            "ball_id": ball_id,
            "source_hash": source_hash,
            "proposer_id": proposer_id,
            "target_slot_id": target_slot_id,
            "benchmark_source": "SYNTHETIC_COLD_START",
        }
        report = ArenaReport(
            proposal_id=proposal_id,
            proposer_id=proposer_id,
            skill_title=ball.title,
            domain_tags=list(ball.domain_tags),
            generated_code=source_code,
            ast_passed=True,
            benchmark_source="SYNTHETIC_COLD_START",
            total_samples=0,
            success_rate=0.0,
            match_rate=0.0,
            promoted=False,
            minted_ball_id=ball_id,
            source_hash=source_hash,
            candidate_status="CANDIDATE",
            validation_status="INDEPENDENT_REVIEW_REQUIRED",
            evidence_provenance={
                "source": "COMPOSED_CANDIDATE",
                "source_hash": source_hash,
                "independent_business_validation": False,
            },
        )
        self._reports.append(report)
        return report

    async def publish_candidate(
        self,
        proposal_id: str,
        reviewer_id: str,
        *,
        approved_source_hash: str,
        independent_samples: list[dict[str, Any]],
    ) -> dict[str, Any]:
        async with self._publication_lock:
            return await self._publish_candidate(
                proposal_id, reviewer_id, approved_source_hash, independent_samples
            )

    async def _publish_candidate(
        self,
        proposal_id: str,
        reviewer_id: str,
        approved_source_hash: str,
        independent_samples: list[dict[str, Any]],
    ) -> dict[str, Any]:
        candidate = self._candidates.get(proposal_id)
        report = next((r for r in self._reports if r.proposal_id == proposal_id), None)
        if candidate is None or report is None:
            raise ValueError("Unknown candidate proposal")
        reviewer = self._containers.get_profile(reviewer_id)
        if (
            reviewer.role_view not in ("leader", "manager", "boss")
            or reviewer_id == report.proposer_id
        ):
            raise PermissionError(
                "Publication requires an independent management reviewer"
            )
        if approved_source_hash != candidate["source_hash"]:
            raise ValueError("Reviewed source hash does not match candidate")
        path = self._sandbox_dir / f"skill_{proposal_id.lower()}.py"
        code = path.read_text(encoding="utf-8")
        if hashlib.sha256(code.encode()).hexdigest() != approved_source_hash:
            raise ValueError("Candidate code changed after review")
        if report.promoted:
            return {
                "status": "ACTIVE",
                "report": report.model_dump(),
                "mounted_ball": self._particles.get_ball(
                    candidate["ball_id"]
                ).model_dump(),
                "idempotent": True,
            }
        if len(independent_samples) < 3 or len(independent_samples) > 100:
            raise ValueError(
                "At least three independent known expected samples are required (maximum 100)"
            )
        for sample in independent_samples:
            if (
                not isinstance(sample, dict)
                or not isinstance(sample.get("input_payload"), dict)
                or "expected_output" not in sample
                or sample["expected_output"] is None
            ):
                raise ValueError(
                    "Each independent sample needs input_payload and known expected_output"
                )
            if not _has_meaningful_expected_output(sample["expected_output"]):
                raise ValueError(
                    "Each independent sample needs a meaningful known expected output"
                )
            json.dumps(sample, allow_nan=False)
        keys = [
            json.dumps(b["input_payload"], sort_keys=True, allow_nan=False)
            for b in independent_samples
        ]
        prior_keys = {
            json.dumps(b.input_payload, sort_keys=True, allow_nan=False)
            for b in report.sample_results
        }
        if len(set(keys)) < 3 or not (set(keys) - prior_keys):
            raise ValueError(
                "Review requires distinct samples including an input outside the synthetic benchmark"
            )
        sandbox_ast_guard(code)
        outputs = await asyncio.to_thread(
            run_skill_in_isolated_subprocess,
            script_path=path,
            sandbox_dir=self._sandbox_dir,
            input_payloads=[b["input_payload"] for b in independent_samples],
            timeout_seconds=self._settings.sandbox_timeout_seconds,
            max_memory_mb=self._settings.sandbox_max_memory_mb,
            max_output_bytes=self._settings.sandbox_max_output_bytes,
        )
        evidence = []
        for idx, sample in enumerate(independent_samples):
            out = outputs[idx] if idx < len(outputs) else {}
            evidence.append(
                {
                    **sample,
                    "actual_output": out.get("output"),
                    "matched": bool(out.get("ok"))
                    and NormalizedResultComparator.is_equivalent(
                        sample["expected_output"], out.get("output")
                    ),
                }
            )
        valid = all(x["matched"] for x in evidence)
        if hashlib.sha256(path.read_bytes()).hexdigest() != approved_source_hash:
            raise ValueError("Candidate code changed during validation")
        validation = {
            "source": "INDEPENDENT_MANAGEMENT_REVIEW",
            "reviewer_id": reviewer_id,
            "source_hash": approved_source_hash,
            "samples": evidence,
            "passed": valid,
        }
        candidate["review_validation"] = validation
        self._vault.append_event(
            event_kind="ARENA_CANDIDATE_REVIEWED",
            subtree_root_id="root",
            actor_slot_id=reviewer.slot_id,
            payload={"proposal_id": proposal_id, **validation},
        )
        if not valid:
            return {
                "status": "VALIDATION_FAILED",
                "report": report.model_dump(),
                "mounted_ball": None,
                "validation": validation,
            }
        ball = self._particles.get_ball(candidate["ball_id"])
        if ball is None or ball.status != "CANDIDATE":
            raise ValueError(
                "Candidate capability is no longer available for publication"
            )
        publication_slot_id = (
            candidate.get("target_slot_id")
            or self._containers.get_profile(report.proposer_id).slot_id
        )
        self._containers.get_slot(publication_slot_id)
        ball.status = "ACTIVE"
        self._particles.register_ball(ball, record_to_vault=True)
        self._containers.attach_ball_to_slot(publication_slot_id, ball.ball_id)
        report.promoted = True
        report.candidate_status = "ACTIVE"
        report.validation_status = "INDEPENDENTLY_REVIEWED"
        report.evidence_provenance["publication_review"] = validation
        return {
            "status": "ACTIVE",
            "report": report.model_dump(),
            "mounted_ball": ball.model_dump(),
            "validation": validation,
        }

    def _resolve_benchmarks(
        self, domain_tags: list[str], generated_code: str, natural_instruction: str
    ) -> tuple[str, list[dict[str, Any]]]:
        # Synthetic expectations are computed from the declared rule, never from candidate code.
        if "运费" in domain_tags or "运费" in natural_instruction:
            number = r"(\d+(?:\.\d+)?)"
            weight_match = re.search(
                r"(?:首重|超过)\s*" + number + r"\s*(?:公斤|千克|kg)",
                natural_instruction,
            )
            base_match = re.search(
                r"首重[^元]{0,30}?" + number + r"\s*元", natural_instruction
            )
            extra_match = re.search(
                r"每(?:公斤|千克|kg)[^元]{0,12}?" + number + r"\s*元",
                natural_instruction,
            )
            free_match = re.search(r"满\s*" + number + r"\s*元", natural_instruction)
            if not all((weight_match, base_match, extra_match)):
                return "SYNTHETIC_COLD_START", []
            base_weight = Decimal(weight_match.group(1))
            base_fee = Decimal(base_match.group(1))
            extra_fee = Decimal(extra_match.group(1))
            free_threshold = Decimal(free_match.group(1)) if free_match else None
            history = self._vault.list_golden_benchmarks("运费")
            standard = (base_weight, base_fee, extra_fee, free_threshold) == (
                Decimal("3"),
                Decimal("10"),
                Decimal("4"),
                Decimal("500"),
            )
            if len(history) >= 5 and standard:
                return "VAULT_HISTORICAL", history
            weights = [
                Decimal("0"),
                max(Decimal("0"), base_weight - Decimal("0.01")),
                base_weight,
                base_weight + Decimal("0.01"),
                base_weight + 1,
                base_weight + Decimal("2.5"),
            ]
            inputs = [
                {"weight_kg": float(weight), "order_amount": 0} for weight in weights
            ]
            if free_threshold is not None:
                inputs.extend(
                    {"weight_kg": float(base_weight + 1), "order_amount": float(amount)}
                    for amount in (
                        max(Decimal("0"), free_threshold - Decimal("0.01")),
                        free_threshold,
                        free_threshold + 1,
                    )
                )
            samples = []
            for payload in inputs:
                weight = Decimal(str(payload["weight_kg"]))
                extra_units = max(Decimal("0"), weight - base_weight).to_integral_value(
                    rounding="ROUND_CEILING"
                )
                expected = base_fee + extra_units * extra_fee
                if weight <= 0:
                    expected = Decimal("0")
                if (
                    free_threshold is not None
                    and Decimal(str(payload["order_amount"])) >= free_threshold
                ):
                    expected = Decimal("0")
                samples.append(
                    {
                        "input_payload": payload,
                        "expected_output": float(expected.quantize(Decimal("0.01"))),
                    }
                )
            return "SYNTHETIC_COLD_START", samples

        if "折扣" in natural_instruction or "折" in natural_instruction:
            threshold = re.search(
                r"满\s*(\d+)\s*(?:件|台|把|套|片|款|块|盒|箱|单|批|个)",
                natural_instruction,
            )
            discount = re.search(r"(\d(?:\.\d)?)\s*折", natural_instruction)
            if threshold is None or discount is None:
                return "SYNTHETIC_COLD_START", []
            quantity_threshold = int(threshold.group(1))
            discount_factor = Decimal(discount.group(1)) / Decimal("10")
            samples = []
            for quantity, unit_price in [
                (5, 100),
                (max(0, quantity_threshold - 1), 200),
                (quantity_threshold, 200),
                (quantity_threshold + 10, 1280),
                (1, 399),
                (50, 500),
            ]:
                expected = Decimal(quantity) * Decimal(unit_price)
                if quantity >= quantity_threshold:
                    expected *= discount_factor
                samples.append(
                    {
                        "input_payload": {
                            "quantity": quantity,
                            "unit_price": unit_price,
                        },
                        "expected_output": float(expected.quantize(Decimal("0.01"))),
                    }
                )
            return "SYNTHETIC_COLD_START", samples

        rate_match = re.search(r"(\d+(?:\.\d+)?)\s*%", natural_instruction)
        if rate_match is None:
            return "SYNTHETIC_COLD_START", []
        rate = Decimal(rate_match.group(1)) / Decimal("100")
        samples = [
            {
                "input_payload": {"amount": amount},
                "expected_output": float(
                    (Decimal(str(amount)) * rate).quantize(Decimal("0.01"))
                ),
            }
            for amount in (0, 100, 350.5, 1000, 5280, 12800)
        ]
        return "SYNTHETIC_COLD_START", samples

    async def propose_and_evaluate(
        self,
        proposer_id: str,
        natural_instruction: str,
        override_code_for_security_test: str | None = None,
    ) -> ArenaReport:
        proposal_id = f"PROP_{uuid.uuid4().hex[:8].upper()}"
        profile = self._containers.get_profile(proposer_id)

        if override_code_for_security_test is not None:
            skill_title = "待检候选脚本"
            domain_tags = ["安全测试"]
            code = override_code_for_security_test
        else:
            skill_title, domain_tags, code = await self._llm.synthesize_artisan_skill(
                natural_instruction
            )

        # Step 1: 静态 AST 安全门禁审查
        try:
            sandbox_ast_guard(code)
        except SandboxSecurityViolation as sec_exc:
            failed_report = ArenaReport(
                proposal_id=proposal_id,
                proposer_id=proposer_id,
                skill_title=skill_title,
                domain_tags=domain_tags,
                generated_code=code,
                ast_passed=False,
                ast_violations=sec_exc.violations,
                benchmark_source="SYNTHETIC_COLD_START",
                total_samples=0,
                success_rate=0.0,
                match_rate=0.0,
                promoted=False,
            )
            self._reports.append(failed_report)
            self._vault.append_event(
                event_kind="ARENA_AST_BLOCKED",
                subtree_root_id="root",
                actor_slot_id=profile.slot_id,
                payload={
                    "proposal_id": proposal_id,
                    "proposer_id": proposer_id,
                    "violations": sec_exc.violations,
                },
            )
            await self._pulse.publish(
                event_type="ARENA_RESULT",
                node_id=self._containers.resolve_node_id_for_slot(profile.slot_id),
                subtree_root_id="root",
                severity="CRITICAL",
                summary=f"🛡️ AST 沙箱门禁拦截恶意/违规代码 [{proposal_id}]：{'；'.join(sec_exc.violations)}",
                payload={"proposal_id": proposal_id, "violations": sec_exc.violations},
            )
            return failed_report

        # Step 2: 落盘至隔离沙箱目录并在 python -I 净室子进程中回放基准集
        script_file = self._sandbox_dir / f"skill_{proposal_id.lower()}.py"
        script_file.write_text(code, encoding="utf-8")

        bench_source, benchmarks = self._resolve_benchmarks(
            domain_tags, code, natural_instruction
        )
        inputs = [dict(b["input_payload"]) for b in benchmarks]

        try:
            exec_outputs = await asyncio.to_thread(
                run_skill_in_isolated_subprocess,
                script_path=script_file,
                sandbox_dir=self._sandbox_dir,
                input_payloads=inputs,
                timeout_seconds=self._settings.sandbox_timeout_seconds,
                max_memory_mb=self._settings.sandbox_max_memory_mb,
                max_output_bytes=self._settings.sandbox_max_output_bytes,
            )
        except (subprocess.TimeoutExpired, TimeoutError, RuntimeError) as sb_exc:
            blocked_report = ArenaReport(
                proposal_id=proposal_id,
                proposer_id=proposer_id,
                skill_title=skill_title,
                domain_tags=domain_tags,
                generated_code=code,
                ast_passed=True,
                ast_violations=[f"SANDBOX_RUNTIME_BLOCKED: {sb_exc}"],
                benchmark_source=bench_source,  # type: ignore[arg-type]
                total_samples=len(benchmarks),
                success_rate=0.0,
                match_rate=0.0,
                promoted=False,
            )
            self._reports.append(blocked_report)
            self._vault.append_event(
                event_kind="ARENA_SANDBOX_BLOCKED",
                subtree_root_id="root",
                actor_slot_id=profile.slot_id,
                payload={
                    "proposal_id": proposal_id,
                    "proposer_id": proposer_id,
                    "reason": str(sb_exc),
                },
            )
            await self._pulse.publish(
                event_type="ARENA_RESULT",
                node_id=self._containers.resolve_node_id_for_slot(profile.slot_id),
                subtree_root_id="root",
                severity="CRITICAL",
                summary=f"🛑 沙箱运行时资源熔断拦截 [{proposal_id}]：{sb_exc}",
                payload={"proposal_id": proposal_id, "reason": str(sb_exc)},
            )
            return blocked_report

        sample_results: list[ArenaSampleResult] = []
        ok_count = 0
        match_count = 0
        for idx, bench in enumerate(benchmarks, start=1):
            run_item = (
                exec_outputs[idx - 1]
                if idx <= len(exec_outputs)
                else {"ok": False, "error": "Missing subprocess receipt"}
            )
            executed_ok = bool(run_item.get("ok", False))
            actual_out = run_item.get("output")
            expected_out = bench["expected_output"]
            matched = False
            if executed_ok:
                ok_count += 1
                matched = NormalizedResultComparator.is_equivalent(
                    expected_out, actual_out
                )
                if matched:
                    match_count += 1

            sample_results.append(
                ArenaSampleResult(
                    sample_index=idx,
                    input_payload=bench["input_payload"],
                    expected_output=expected_out,
                    actual_output=actual_out,
                    executed_ok=executed_ok,
                    matched=matched,
                    error_detail=str(run_item.get("error", "")),
                )
            )

        total = len(benchmarks)
        success_rate = round(ok_count / total, 4) if total > 0 else 0.0
        match_rate = round(match_count / total, 4) if total > 0 else 0.0

        passed = (
            total > 0
            and success_rate == 1.0
            and match_rate >= self._settings.arena_min_match_rate
        )

        promoted = passed and bench_source == "VAULT_HISTORICAL"
        minted_ball_id: str | None = None
        bonus_awarded = 0.0
        source_hash = hashlib.sha256(code.encode()).hexdigest()
        if passed:
            mgmt_slots = [
                s.slot_id
                for s in self._containers.list_slots()
                if s.slot_id != profile.slot_id
                and (
                    s.slot_id == "SLOT_BOSS"
                    or any(
                        p.slot_id == s.slot_id
                        and p.role_view in ("leader", "manager", "boss")
                        for p in self._containers.list_profiles()
                    )
                )
            ]
            owner_slots = [profile.slot_id] + mgmt_slots[:3]
            minted = self._particles.mint_from_candidate(
                candidate=ExtractedBallCandidate(
                    ball_type="SKILL",
                    title=skill_title,
                    domain_tags=domain_tags,
                    sensitivity_level=2,
                    content=f"员工 {profile.name} 提案；基准来源 {bench_source}，业务发布状态 {'ACTIVE' if promoted else 'CANDIDATE_PENDING_REVIEW'}。",
                ),
                owner_slot_ids=owner_slots,
                status="ACTIVE" if promoted else "CANDIDATE",
                executable_code_path=str(script_file.name),
            )
            minted_ball_id = minted.ball_id
            self._candidates[proposal_id] = {
                "ball_id": minted.ball_id,
                "source_hash": source_hash,
                "proposer_id": proposer_id,
                "benchmark_source": bench_source,
            }
            if promoted:
                self._containers.attach_ball_to_slot(profile.slot_id, minted.ball_id)
                bonus_awarded = 24.0
                await self._scoring.award_evolution_architect_bonus(
                    user_id=proposer_id,
                    skill_title=skill_title,
                    bonus_points=bonus_awarded,
                )

        if promoted:
            candidate_status = "ACTIVE"
            validation_status = "HISTORICAL_VALIDATED"
        elif passed:
            candidate_status = "CANDIDATE"
            validation_status = "SYNTHETIC_ONLY"
        else:
            candidate_status = "REJECTED"
            validation_status = "FAILED"

        report = ArenaReport(
            proposal_id=proposal_id,
            proposer_id=proposer_id,
            skill_title=skill_title,
            domain_tags=domain_tags,
            generated_code=code,
            ast_passed=True,
            ast_violations=[],
            benchmark_source=bench_source,  # type: ignore[arg-type]
            total_samples=total,
            success_rate=success_rate,
            match_rate=match_rate,
            promoted=promoted,
            minted_ball_id=minted_ball_id,
            innovation_bonus_awarded=bonus_awarded,
            sample_results=sample_results,
            source_hash=source_hash,
            candidate_status=candidate_status,
            validation_status=validation_status,
            evidence_provenance={
                "benchmark_source": bench_source,
                "independent_business_validation": bench_source == "VAULT_HISTORICAL",
                "source_hash": source_hash,
            },
        )
        self._reports.append(report)

        self._vault.append_event(
            event_kind="ARENA_EVALUATED",
            subtree_root_id="root",
            actor_slot_id=profile.slot_id,
            payload={
                "proposal_id": proposal_id,
                "skill_title": skill_title,
                "benchmark_source": bench_source,
                "total_samples": total,
                "success_rate": success_rate,
                "match_rate": match_rate,
                "promoted": promoted,
                "minted_ball_id": minted_ball_id,
            },
        )
        await self._pulse.publish(
            event_type="ARENA_RESULT",
            node_id=self._containers.resolve_node_id_for_slot(profile.slot_id),
            subtree_root_id="root",
            severity="SUCCESS" if promoted else "WARNING",
            summary=(
                f"⚔️ 影子擂台战报《{skill_title}》：{total} 组样本成功率 {success_rate * 100:.0f}%、"
                f"吻合度 {match_rate * 100:.1f}% → {'已通过历史业务基准并晋升 ACTIVE' if promoted else '合成基准通过，候选待独立审批' if passed else '未达标拦截'}"
            ),
            payload={
                "proposal_id": proposal_id,
                "promoted": promoted,
                "minted_ball_id": minted_ball_id,
                "match_rate": match_rate,
            },
        )
        return report

from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path

import pytest

from config import load_settings
from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from core.llm_gateway import LLMGateway
from core.particles import ParticleEngine
from database import HotStateStore
from seed_demo.commerce_dept_seed import seed_commerce_department
from swarm.board_of_directors import BoardOfDirectors
from swarm.evolution_arena import (
    EvolutionArena,
    NormalizedResultComparator,
    SandboxSecurityViolation,
    run_skill_in_isolated_subprocess,
    sandbox_ast_guard,
)
from swarm.pulse_bus import PulseBus
from swarm.scoring_engine import ScoringEngine


async def _build_m4_fixture(
    tmp_path: Path,
) -> tuple[EvolutionArena, BoardOfDirectors, ScoringEngine, ContainerRegistry, HotStateStore, BlackBoxVault]:
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=tmp_path / "sandbox",
    )
    vault = BlackBoxVault(settings.vault_storage_dir)
    particles = ParticleEngine(vault)
    containers = ContainerRegistry()
    hot_store = HotStateStore(f"sqlite+aiosqlite:///{(tmp_path / 'hot.db').as_posix()}")
    await hot_store.init_db()
    await seed_commerce_department(vault, particles, containers, hot_store)

    pulse = PulseBus()
    llm = LLMGateway(settings)
    scoring = ScoringEngine(vault, containers, pulse)
    arena = EvolutionArena(
        settings, vault, particles, containers, llm, scoring, pulse
    )
    board = BoardOfDirectors(
        settings, vault, hot_store, particles, containers, llm, scoring, pulse
    )
    return arena, board, scoring, containers, hot_store, vault


def test_g_patch_2_and_3_ast_escape_blocking_and_subprocess_secret_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # G-Patch-2: 四类沙箱逃逸恶意载荷必须 100% 在静态 AST 层拦截
    malicious_snippets = [
        "import os\ndef execute_skill(payload: dict) -> dict:\n    return {'result': os.getcwd()}",
        "def execute_skill(payload: dict) -> dict:\n    return {'result': __import__('os').listdir('.')}",
        "def execute_skill(payload: dict) -> dict:\n    return {'result': ().__class__.__bases__[0].__subclasses__()}",
        "def execute_skill(payload: dict) -> dict:\n    return {'result': open('/etc/passwd').read()}",
    ]
    for bad_code in malicious_snippets:
        with pytest.raises(SandboxSecurityViolation):
            sandbox_ast_guard(bad_code)

    # G-Patch-3: 验证宿主进程哪怕含有敏感 LLM_API_KEY，净室子进程中也 100% 零泄露
    monkeypatch.setenv("LLM_API_KEY", "sk-top-secret-host-key")
    assert os.environ.get("LLM_API_KEY") == "sk-top-secret-host-key"

    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    safe_script = sandbox_dir / "safe_calc.py"
    safe_script.write_text(
        "def execute_skill(payload: dict) -> dict:\n    return {'status': 'ok', 'result': payload['x'] * 2}\n",
        encoding="utf-8",
    )
    res = run_skill_in_isolated_subprocess(safe_script, sandbox_dir, [{"x": 21}])
    assert res[0]["ok"] is True
    assert res[0]["output"]["result"] == 42
    assert res[0]["env_keys_leaked"] == []


def test_g_patch_4_normalized_result_comparator() -> None:
    assert NormalizedResultComparator.is_equivalent(
        "18.00元", {"status": "ok", "result": 18}
    )
    assert NormalizedResultComparator.is_equivalent(
        "¥30.00", {"status": "ok", "result": Decimal("30.0")}
    )
    assert not NormalizedResultComparator.is_equivalent(
        "18.00元", {"status": "ok", "result": 19.0}
    )


@pytest.mark.asyncio
async def test_gate_4_and_6_artisan_freight_arena_promotion_and_board_transition(
    tmp_path: Path,
) -> None:
    arena, board, scoring, containers, hot_store, vault = await _build_m4_fixture(
        tmp_path
    )

    chen_before = containers.get_profile("emp_chen").management_view.performance_score

    # 关卡 4：小陈口述阶梯运费规则 -> 工匠现场写 Python 代码 -> 跑过 12 条 Vault 历史黄金样本 -> 晋升 ACTIVE + 绩效暴涨
    report = await arena.propose_and_evaluate(
        proposer_id="emp_chen",
        natural_instruction="每次算阶梯运费太麻烦：首重10元，超过3公斤每公斤加4元，满500元免运费，帮我做成自动工具",
    )
    assert report.ast_passed is True
    assert report.benchmark_source == "VAULT_HISTORICAL"
    assert report.total_samples == 12
    assert report.success_rate == 1.0
    assert report.match_rate == 1.0
    assert report.promoted is True
    assert report.minted_ball_id is not None

    chen_after = containers.get_profile("emp_chen").management_view.performance_score
    assert chen_after > chen_before + 15.0

    # 验证安全红线官一票否决机制 (VETO)
    vetoed_res = await board.convene(
        agenda="风险状况下强推自动化测试",
        target_slot_id="SLOT_FOLLOWUP_01",
        force_security_veto=True,
    )
    assert vetoed_res.vetoed is True
    assert vetoed_res.recommended_action == "REJECTED_BY_VETO"
    with pytest.raises(PermissionError):
        await board.apply_boss_decision(vetoed_res.resolution_id, approve=True)

    # 关卡 6：正常召开自适应董事会（3名铁三角 + 2名动态业务域董事并发盲评）-> 老板批准进入师徒反转期
    good_res = await board.convene(
        agenda="审议【商务跟单专员一号位】启动师徒反转接管",
        target_slot_id="SLOT_FOLLOWUP_01",
    )
    assert good_res.vetoed is False
    assert len(good_res.votes) >= 5
    assert good_res.recommended_action == "MAINTAIN_HUMAN"
    with pytest.raises(ValueError):
        await board.apply_boss_decision(good_res.resolution_id, approve=True)

    # Independent human-reviewed examples are required before transition eligibility.
    for weight, amount in ((1, 100), (6, 320), (9, 499), (12, 800)):
        reviewed = f"订单金额{amount}元，重量{weight}公斤，运费已人工核对"
        await scoring.on_shadow_trial_completed(
            "emp_chen", "SLOT_FOLLOWUP_01",
            ai_draft_text=reviewed, human_final_text=reviewed,
        )
    good_res = await board.convene(
        agenda="根据已审核影子样本审议岗位试运行", target_slot_id="SLOT_FOLLOWUP_01",
    )
    assert good_res.recommended_action == "APPROVE_HYBRID_TRANSITION"

    weights_before = scoring.calibrator.snapshot()["automation_aggressiveness"]
    decision_out = await board.apply_boss_decision(good_res.resolution_id, approve=True)
    assert decision_out["updated_slot"].occupant_type == "HYBRID_TRANSITION"
    assert (
        decision_out["preference_weights"]["automation_aggressiveness"] > weights_before
    )
    assert vault.verify_chain_integrity().intact is True
    await hot_store.close()


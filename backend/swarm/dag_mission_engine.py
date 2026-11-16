from __future__ import annotations

import asyncio
import copy
import math
import json
from pathlib import Path
import re
import time
import uuid
from typing import Any, Optional

from core.llm_gateway import sanitize_l1_text
from core.schemas import CapabilityBall, UnitSlot, utc_now_iso
from core.topology_resolver import (
    resolve_active_authority_ball,
    resolve_active_redline_and_floor,
    resolve_blackbox_user_and_slot,
    resolve_executive_slots,
    resolve_frontline_user_and_slot,
    resolve_leader_user_and_slot,
    resolve_primary_catalog_item,
    resolve_slot_by_role_keywords,
)
from swarm.evolution_arena import run_skill_in_isolated_subprocess, sandbox_ast_guard

EnterpriseState = Any


def _build_dynamic_presets(state: Optional[EnterpriseState]) -> list[dict[str, Any]]:
    """Bind synthetic scenario templates to the selected enterprise topology; quantities remain hypothetical."""
    if state is not None and getattr(state, "containers", None) is not None and getattr(state, "particles", None) is not None:
        containers = state.containers
        particles = state.particles
        if not containers.list_slots():
            return []
        fl_uid, fl_slot = resolve_frontline_user_and_slot(containers)
        ld_uid, ld_slot = resolve_leader_user_and_slot(containers)
        _bb_uid, bb_slot = resolve_blackbox_user_and_slot(containers)
        boss_slots, mgr_slots = resolve_executive_slots(containers)
        boss_slot = boss_slots[0] if boss_slots else containers.list_slots()[-1].slot_id
        mgr_slot = mgr_slots[0] if mgr_slots else ld_slot
        wms_slot = resolve_slot_by_role_keywords(containers, ["仓", "物流", "排产", "交付"])
        proc_slot = resolve_slot_by_role_keywords(containers, ["采购", "产研", "工程", "供应"])
        legal_slot = resolve_slot_by_role_keywords(containers, ["法务", "合规", "审计"], ("finance_tool", "leader"))
        hr_slot = resolve_slot_by_role_keywords(containers, ["人事", "HR", "进化"], ("manager", "leader"))

        def _dept(sid: str, fallback: str) -> str:
            try:
                return str(containers.get_slot(sid).department or fallback)
            except Exception:
                return fallback

        def _occ(sid: str, fallback: str) -> str:
            try:
                return str(containers.get_slot(sid).occupant_id or fallback)
            except Exception:
                return fallback

        floor_rl, floor_price, _ = resolve_active_redline_and_floor(particles)
        auth_ball = resolve_active_authority_ball(particles)
        primary_item = resolve_primary_catalog_item(particles)
        all_rl = particles.list_redline_balls()
        legal_rl = next((b.ball_id for b in all_rl if "LEGAL" in b.ball_id or "法务" in b.title), floor_rl)
        bom_rl = next((b.ball_id for b in all_rl if "BOM" in b.ball_id or "隐私" in b.title or "PII" in b.ball_id), floor_rl)
    else:
        fl_uid, ld_uid, fl_slot, ld_slot, bb_slot, boss_slot, mgr_slot = (
            "role_frontline",
            "role_leader",
            "SLOT_FRONTLINE",
            "SLOT_LEADER",
            "SLOT_BLACKBOX",
            "SLOT_BOSS",
            "SLOT_MANAGER",
        )
        wms_slot, proc_slot, legal_slot, hr_slot = fl_slot, fl_slot, bb_slot, mgr_slot
        _dept = lambda _sid, fb: fb  # noqa: E731
        _occ = lambda _sid, fb: fb  # noqa: E731
        floor_rl, floor_price, auth_ball, primary_item = "REDLINE_FLOOR_GUARD", 500.0, "AUTH_GATE_GUARD", "核心主营产品"
        legal_rl, bom_rl = floor_rl, floor_rl

    lock_price = int(round(floor_price * 0.9833))
    presets = [
        {
            "preset_id": "preset_global_steel_lock",
            "mission_title": f"战略大客户 200 单位大宗紧急锁价（{lock_price}元/单位）+ 45 天账期特批 + 跨区调拨协同",
            "title": f"战略大客户 200 单位大宗紧急锁价（{lock_price}元/单位）+ 45 天账期特批 + 跨区调拨协同",
            "category": "CROSS_DEPT_PRICE_AND_CREDIT_GAMING",
            "difficulty": "EXTREME",
            "initiator_account_id": fl_uid,
            "max_debate_rounds": 3,
            "auto_execute_skills": True,
            "involved_departments": [
                _dept(fl_slot, "一线业务部"),
                _dept(wms_slot, "供应链物流部"),
                _dept(bb_slot, "财税风控部"),
                _dept(boss_slot, "顶层治理董事会"),
            ],
            "target_slots": [fl_slot, wms_slot, bb_slot, boss_slot],
            "expected_redlines": [floor_rl],
            "mission_brief": (
                f"重点大客户紧急采购 200 单位【{primary_item}】配套特种标品，"
                f"一线业务工位申请按 {lock_price} 元/单位紧急锁价（低于底价 {int(round(floor_price))} 元/单位红线 {floor_rl}），"
                "并要求特批 45 天远期账期。当前主节点实时可用现货仅 140 单位，缺口 60 单位需由兄弟节点紧急跨区调拨，"
                "同时需调用净室沙箱核算跨区阶梯运费、45 天账期贴现资金成本与锁价毛利缺口，"
                f"由业务、交付、财务与董事会围绕 {int(round(floor_price))} 元底价红线展开多轮博弈并达成可执行联合决议。"
            ),
            "brief": (
                f"战略大客户紧急采购 200 单位【{primary_item}】，申请按 {lock_price} 元紧急锁价（逼近/低于底价红线 {floor_rl}），"
                "并要求特批 45 天账期，需跨部门展开多轮博弈与沙箱精算。"
            ),
            "tags": ["大客户锁价", f"{lock_price}元/单位", "45天账期", "跨区调拨", "底价红线博弈"],
        },
        {
            "preset_id": "preset_supply_chain_shortage",
            "mission_title": "核心原料/产能突发断供 48 小时应急跨区调配与客户违约金最小化会战",
            "title": "核心原料/产能突发断供 48 小时应急跨区调配与客户违约金最小化会战",
            "category": "SUPPLY_CHAIN_CRISIS_RESPONSE",
            "difficulty": "HIGH",
            "initiator_account_id": _occ(proc_slot, fl_uid),
            "max_debate_rounds": 3,
            "auto_execute_skills": True,
            "involved_departments": [
                _dept(proc_slot, "供应链采购部"),
                _dept(wms_slot, "仓储交付部"),
                _dept(legal_slot, "合规风控部"),
                _dept(ld_slot, "业务主管部"),
            ],
            "target_slots": [proc_slot, wms_slot, legal_slot, ld_slot],
            "expected_redlines": list(dict.fromkeys([legal_rl, bom_rl])),
            "mission_brief": (
                f"核心上游模组突发产线故障断供 48 小时，导致 120 批【{primary_item}】面临逾期交付。"
                "下游签约客户发函要求签署补充协议：承诺逾期每日按合同总额 25% 支付惩罚性违约金并承担无限连带责任"
                f"（直接触碰法务红线球 {legal_rl} 与成本底价红线 {bom_rl}）。"
                "需采购、交付、法务与业务主管联合执行安全库存重算、48 小时跨区现货拆单调配与违约金最小化抗辩。"
            ),
            "brief": (
                "核心上游突发断供 48 小时，客户要求承诺超额 25% 违约金与无限连带责任，"
                "需跨部门联合跨区调配并压降违约赔付敞口。"
            ),
            "tags": ["供应链断供", "48小时应急", "跨区调配", "违约金最小化", "法务红线"],
        },
        {
            "preset_id": "preset_annual_margin_defense",
            "mission_title": "大促季全渠道阶梯返利核算与毛利红线保卫战",
            "title": "大促季全渠道阶梯返利核算与毛利红线保卫战",
            "category": "OMNICHANNEL_MARGIN_DEFENSE",
            "difficulty": "HIGH",
            "initiator_account_id": fl_uid,
            "max_debate_rounds": 3,
            "auto_execute_skills": True,
            "involved_departments": [
                _dept(fl_slot, "一线业务部"),
                _dept(wms_slot, "物流交付部"),
                _dept(mgr_slot, "经营管理部"),
                _dept(boss_slot, "顶层治理董事会"),
            ],
            "target_slots": [fl_slot, wms_slot, mgr_slot, boss_slot],
            "expected_redlines": [floor_rl],
            "mission_brief": (
                f"季度大促冲刺阶段，区域大客户提报 160 批【{primary_item}】团购锁单，"
                f"申请在 8.5 折集采底线基础上再叠加 8% 阶梯返利与干线补贴（折算净结算价逼近底价 {int(round(floor_price))} 元红线）。"
                "需调用沙箱技能球精确核算批量折后总价、首重续重物流费用及净毛利率，展开多部门毛利红线保卫战。"
            ),
            "brief": (
                f"全渠道大促阶梯返利叠加补贴逼近底价 {int(round(floor_price))} 元红线，"
                "需跨部门调用沙箱算子精算净毛利并合成阶梯返利替代方案。"
            ),
            "tags": ["全渠道大促", "阶梯返利", "毛利保卫战", "沙箱精算"],
        },
        {
            "preset_id": "preset_compliance_audit_sweep",
            "mission_title": "全集团越权操作与高危权限球租借合规联审行动",
            "title": "全集团越权操作与高危权限球租借合规联审行动",
            "category": "COMPLIANCE_AND_PRIVILEGE_SWEEP",
            "difficulty": "EXTREME",
            "initiator_account_id": _occ(hr_slot, ld_uid),
            "max_debate_rounds": 2,
            "auto_execute_skills": True,
            "involved_departments": [
                _dept(hr_slot, "经营进化部"),
                _dept(legal_slot, "合规黑盒部"),
                _dept(ld_slot, "业务督导部"),
                _dept(boss_slot, "顶层治理董事会"),
            ],
            "target_slots": [hr_slot, legal_slot, ld_slot, boss_slot],
            "expected_redlines": list(dict.fromkeys([bom_rl, floor_rl])),
            "mission_brief": (
                "集团黑匣子监控发现多起一线工位越界刺探【核心成本底价】、【导出全量客户明文隐私】"
                f"以及超时借用高危权限球（{auth_ball}）未及时归还的风险信号。"
                "现由进化治理岗、法务合规黑盒、业务督导与顶层董事会启动全集团越权操作清查与权限球 TTL 租借合规联审。"
            ),
            "brief": (
                "全集团越权刺探底价、敏感隐私合规与高危权限球 TTL 租借跨部门合规联审行动。"
            ),
            "tags": ["合规联审", "越权清查", "权限球租借", "隐私红线"],
        },
    ]

    for preset in presets:
        preset["evidence_source"] = "SYNTHETIC_SCENARIO"
        preset["business_facts_verified"] = False
        preset["mission_brief"] = "【合成推演样例：以下数量、现货、账期等为假设，须核验后执行】" + preset["mission_brief"]
        preset["brief"] = "【推演样例】" + preset["brief"]
    return presets


MISSION_PRESETS: list[dict[str, Any]] = _build_dynamic_presets(None)


class DAGMissionEngine:
    """
    Pillar 1：多智能体跨部门 DAG 协同作战与博弈辩论引擎 (Multi-Agent DAG & Adversarial Debate Engine)
    - 动态 DAG 拓扑规划（绑定真实 UnitSlot、部门与挂载的四类权能球）
    - 逐节点 Agent 深度推理（支持真实 DeepSeek/OpenAI API 调用 + 高保真确定性混合推演兜底）
    - 洁净室 python -I 技能球真实子进程执行与上下文注入
    - 跨部门红线冲突自动触发多轮对抗博弈辩论 (Round 1 提案 -> Round 2 红线精算质询 -> Round 3 折中合成)
    - 双工位/三工位专项对抗辩论 (run_adversarial_debate) 与 WORM 黑匣子审计落盘
    """

    def __init__(
        self,
        state: Optional[EnterpriseState] = None,
        runtime: Optional[EnterpriseState] = None,
    ) -> None:
        self._state = state if state is not None else runtime
        self._mission_history: list[dict[str, Any]] = []
        self._debate_history: list[dict[str, Any]] = []

    def bind_state(self, state: EnterpriseState) -> None:
        self._state = state

    def get_mission_presets(self) -> list[dict[str, Any]]:
        return _build_dynamic_presets(self._state)

    def get_history(self) -> dict[str, Any]:
        combined = sorted(
            [*self._mission_history, *self._debate_history],
            key=lambda x: str(x.get("created_at", "")),
            reverse=True,
        )
        return {
            "missions": list(self._mission_history),
            "debates": list(self._debate_history),
            "history": combined,
            "total_missions": len(self._mission_history),
            "total_debates": len(self._debate_history),
            "count": len(combined),
        }

    # ==========================================================================
    # 内部辅助：状态解析、部门映射、LLM 调用与洁净室技能脚本物化执行
    # ==========================================================================

    def _is_llm_live(self) -> bool:
        if self._state is None or getattr(self._state, "llm_gateway", None) is None:
            return False
        gw = self._state.llm_gateway
        return bool(
            getattr(gw, "is_live", False) or getattr(gw, "is_live_mode", False)
        )

    async def _call_llm_json(
        self, system_prompt: str, user_prompt: str
    ) -> Optional[dict[str, Any]]:
        if not self._is_llm_live():
            return None
        gw = self._state.llm_gateway
        try:
            if hasattr(gw, "_call_openai_compatible") and callable(
                gw._call_openai_compatible
            ):
                raw = await gw._call_openai_compatible(
                    system_prompt=system_prompt, user_prompt=user_prompt
                )
                if isinstance(raw, dict):
                    return raw
                if isinstance(raw, str):
                    return json.loads(raw)
            client = getattr(gw, "_client", None)
            if client is not None:
                model_name = getattr(
                    gw._settings, "llm_model_l3_reasoner", "deepseek-chat"
                )
                resp = await client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
                if hasattr(gw, "_telemetry") and isinstance(gw._telemetry, dict):
                    gw._telemetry["l3_reasoner_calls"] = (
                        int(gw._telemetry.get("l3_reasoner_calls", 0)) + 1
                    )
                    gw._telemetry["live_api_hits"] = (
                        int(gw._telemetry.get("live_api_hits", 0)) + 1
                    )
                content = resp.choices[0].message.content or "{}"
                return json.loads(content)
        except Exception:
            if hasattr(gw, "_telemetry") and isinstance(gw._telemetry, dict):
                gw._telemetry["deterministic_engine_hits"] = (
                    int(gw._telemetry.get("deterministic_engine_hits", 0)) + 1
                )
        return None

    def _resolve_slot_department(self, slot: UnitSlot) -> str:
        if getattr(slot, "department", None):
            return str(slot.department)
        if self._state is not None and getattr(self._state, "custody", None) is not None:
            for item in self._state.custody.list_directory():
                if item.get("user_id") == slot.occupant_id and item.get("department"):
                    return str(item["department"])
        return "核心业务协同部"

    def _resolve_occupant_name(self, slot: UnitSlot) -> str:
        if self._state is not None and getattr(self._state, "containers", None):
            try:
                prof = self._state.containers.get_profile(slot.occupant_id)
                return f"{prof.name}（{prof.title}）"
            except Exception:
                pass
        return slot.occupant_id or slot.slot_name

    def _get_slot_mounted_balls(self, slot_id: str) -> list[CapabilityBall]:
        if self._state is None:
            return []
        containers = self._state.containers
        particles = self._state.particles
        try:
            eff_ids = containers.get_effective_ball_ids(slot_id)
        except Exception:
            eff_ids = set()
        balls: list[CapabilityBall] = []
        seen: set[str] = set()
        for b in particles.list_all_balls():
            if b.status != "ACTIVE":
                continue
            if b.ball_id in eff_ids:
                if b.ball_id not in seen:
                    balls.append(b)
                    seen.add(b.ball_id)
        return balls

    def export_state(self) -> dict[str, Any]:
        return copy.deepcopy(
            {"missions": self._mission_history, "debates": self._debate_history}
        )

    def restore_state(self, payload: dict[str, Any]) -> None:
        self._mission_history = copy.deepcopy(payload.get("missions", []))
        self._debate_history = copy.deepcopy(payload.get("debates", []))

    def _extract_mission_metrics(
        self, brief: str, supplied: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        # Missing business facts remain missing. Brief values are assertions, not verified inventory.
        patterns = {
            "quantity": r"(-?\d+(?:\.\d+)?)\s*(?:吨|把|张|套|件|单位|批)",
            "floor_price": r"底价\s*[¥￥]?(-?\d+(?:\.\d+)?)",
            "unit_price": r"按\s*(-?\d+(?:\.\d+)?)\s*元",
            "payment_days": r"(-?\d+)\s*天(?:远期)?账期",
            "available_stock": r"现货(?:仅)?\s*(-?\d+(?:\.\d+)?)\s*(?:吨|把|张|套|件|单位|批)",
            "indemnity_pct": r"(-?\d+(?:\.\d+)?)\s*%\s*(?:索赔|违约金|支付)",
        }
        metrics = {
            key: float(m.group(1))
            for key, pattern in patterns.items()
            if (m := re.search(pattern, brief))
        }
        price = re.search(
            r"(-?\d+(?:\.\d+)?)\s*元\s*/\s*(?:吨|把|张|套|件|单位)", brief
        )
        if price:
            metrics["unit_price"] = float(price.group(1))
        facts_to_validate = {**metrics, **(supplied or {})}
        for key, value in facts_to_validate.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"Invalid nonnegative finite metric: {key}")
            metrics[key] = value
        if "quantity" in metrics and "unit_price" in metrics:
            amount = metrics["quantity"] * metrics["unit_price"]
            if not math.isfinite(amount):
                raise ValueError("Derived order amount must be finite")
            metrics["order_amount"] = round(amount, 2)
            metrics["amount"] = metrics["order_amount"]
        if "quantity" in metrics and "available_stock" in metrics:
            metrics["transfer_qty"] = max(
                0, metrics["quantity"] - metrics["available_stock"]
            )
        return metrics

    def _ensure_executable_skill_script(
        self, ball: CapabilityBall, sandbox_dir: Path
    ) -> Path:
        # A title is not an implementation. Never synthesize a replacement and label it execution.
        if not ball.executable_code_path:
            raise FileNotFoundError(
                f"Skill {ball.ball_id} has no executable implementation"
            )
        candidate = Path(ball.executable_code_path)
        if not candidate.is_absolute():
            candidate = sandbox_dir / candidate
        sandbox_ast_guard(candidate.read_text(encoding="utf-8"))
        return candidate

    # ==========================================================================
    # Step 1 ~ Step 4: 多智能体跨部门 DAG 协同规划、执行与多轮红线博弈
    # ==========================================================================

    def _plan_dag_topology(
        self,
        mission_brief: str,
        initiator_account_id: Optional[str],
    ) -> list[dict[str, Any]]:
        if self._state is None:
            raise RuntimeError(
                "DAGMissionEngine requires an initialized EnterpriseState"
            )

        containers = self._state.containers
        all_slots = containers.list_slots()
        if not all_slots:
            raise ValueError("Selected enterprise has no configured posts")
        slot_by_id = {s.slot_id: s for s in all_slots}

        _, default_fl_slot = resolve_frontline_user_and_slot(containers)
        _, default_ld_slot = resolve_leader_user_and_slot(containers)
        _, default_bb_slot = resolve_blackbox_user_and_slot(containers)
        boss_slots, _ = resolve_executive_slots(containers)

        # 确定业务发起工位 (Node 1)
        initiator_slot_id = default_fl_slot
        if initiator_account_id:
            try:
                prof = containers.get_profile(initiator_account_id)
                initiator_slot_id = prof.slot_id
            except (KeyError, ValueError) as exc:
                raise ValueError(
                    "Initiator is not a member of the selected enterprise"
                ) from exc
        if initiator_slot_id not in slot_by_id:
            if "断供" in mission_brief:
                initiator_slot_id = resolve_slot_by_role_keywords(
                    containers, ["采购", "产研", "供应", "工程"]
                )
            elif "越权" in mission_brief:
                initiator_slot_id = resolve_slot_by_role_keywords(
                    containers, ["人事", "HR", "进化", "治理"], ("manager", "leader")
                )
            else:
                initiator_slot_id = all_slots[0].slot_id

        # 确定跨仓/供应链工位 (Node 2)
        supply_candidates = [
            s.slot_id
            for s in all_slots
            if s.slot_id != initiator_slot_id
            and any(
                k in (s.slot_name + s.department)
                for k in ("仓", "物流", "供应链", "采购", "交付", "调度")
            )
        ]
        supply_slot_id = (
            supply_candidates[0]
            if supply_candidates
            else all_slots[min(1, len(all_slots) - 1)].slot_id
        )

        # 确定财务/法务/风控审核工位 (Node 3)
        if (
            "违约金" in mission_brief
            or "法务" in mission_brief
            or "连带责任" in mission_brief
        ):
            risk_slot_id = resolve_slot_by_role_keywords(
                containers, ["法务", "合规", "审计"], ("finance_tool", "leader")
            )
        elif "账期" in mission_brief or "锁价" in mission_brief:
            risk_slot_id = default_bb_slot
        else:
            risk_slot_id = default_ld_slot
        if risk_slot_id not in slot_by_id:
            risk_slot_id = all_slots[min(2, len(all_slots) - 1)].slot_id

        # 确定总裁办/高管红线裁决工位 (Node 4)
        arbiter_slot_id = boss_slots[0] if boss_slots else all_slots[-1].slot_id

        # 确保黑盒工位也可见相关风控/红线上下文以便审计
        raw_plan = [
            {
                "node_id": "DAG_STEP_01",
                "step_index": 1,
                "stage_name": "一线业务诉求提报与订单要素建模",
                "slot_id": initiator_slot_id,
                "depends_on": [],
            },
            {
                "node_id": "DAG_STEP_02",
                "step_index": 2,
                "stage_name": "多仓现货水位核验与跨区调拨配载精算",
                "slot_id": supply_slot_id,
                "depends_on": ["DAG_STEP_01"],
            },
            {
                "node_id": "DAG_STEP_03",
                "step_index": 3,
                "stage_name": "财税账期贴现测算与合规高压线初审",
                "slot_id": risk_slot_id,
                "depends_on": ["DAG_STEP_01"],
            },
            {
                "node_id": "DAG_STEP_04",
                "step_index": 4,
                "stage_name": "总裁办底价红线守护与跨部门联合裁决",
                "slot_id": arbiter_slot_id,
                "depends_on": ["DAG_STEP_02", "DAG_STEP_03"],
            },
        ]

        dag_nodes: list[dict[str, Any]] = []
        for item in raw_plan:
            slot = containers.get_slot(item["slot_id"])
            mounted = self._get_slot_mounted_balls(slot.slot_id)
            dag_nodes.append(
                {
                    "node_id": item["node_id"],
                    "step_index": item["step_index"],
                    "stage_name": item["stage_name"],
                    "title": item["stage_name"],
                    "slot_id": slot.slot_id,
                    "slot_title": slot.slot_name,
                    "slot_name": slot.slot_name,
                    "occupant_id": slot.occupant_id,
                    "occupant_name": self._resolve_occupant_name(slot),
                    "department": self._resolve_slot_department(slot),
                    "depends_on": list(item["depends_on"]),
                    "mounted_balls": [
                        {
                            "ball_id": b.ball_id,
                            "ball_type": b.ball_type,
                            "title": b.title,
                            "sensitivity_level": b.sensitivity_level,
                            "domain_tags": list(b.domain_tags),
                            "executable_code_path": b.executable_code_path,
                        }
                        for b in mounted
                    ],
                    "_ball_objects": mounted,
                }
            )
        return dag_nodes

    async def execute_dag_mission(
        self,
        mission_title: str = "跨部门联合特战队行动",
        mission_brief: str = "",
        initiator_account_id: Optional[str] = None,
        max_debate_rounds: int = 2,
        auto_execute_skills: bool = True,
        preset_id: Optional[str] = None,
        metrics: Optional[dict[str, Any]] = None,
        requirements: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        if self._state is None:
            raise RuntimeError(
                "DAGMissionEngine requires an initialized EnterpriseState"
            )
        t0 = time.perf_counter()
        preset = next(
            (p for p in self.get_mission_presets() if p["preset_id"] == preset_id), None
        )
        if preset_id and preset is None:
            raise ValueError("Unknown mission preset")
        if preset and not mission_brief.strip():
            mission_brief = preset["mission_brief"]
            mission_title = preset["mission_title"]
        mission_id = f"MSN_{uuid.uuid4().hex[:8].upper()}"
        facts = self._extract_mission_metrics(mission_brief, metrics)
        policy_floor_id, policy_floor, _ = resolve_active_redline_and_floor(
            self._state.particles
        )
        policy_ball = self._state.particles.get_ball(policy_floor_id)
        if (
            policy_ball is not None
            and policy_ball.status == "ACTIVE"
            and policy_floor > 0
        ):
            # The current policy controls the threshold, never a caller-supplied lower number.
            facts["floor_price"] = policy_floor
        required = list(requirements or [])
        if any(not isinstance(k, str) or not k.strip() for k in required):
            raise ValueError("Requirements must be metric field names")
        missing = [k for k in required if k not in facts]
        if not mission_brief.strip():
            missing.append("mission_brief")
        nodes = self._plan_dag_topology(mission_brief, initiator_account_id)
        rehydrated_node_ids = []
        if getattr(self._state, "spider", None) is not None:
            rehydrated_node_ids = await self._state.spider.rehydrate_slot_nodes(
                [n["slot_id"] for n in nodes], reason="dag_mission_dispatch"
            )
        sandbox_dir = Path(self._state.settings.sandbox_workspace_dir)
        executions = []
        failed = False
        triggered = []
        for ball in self._state.particles.list_redline_balls():
            if ball.status == "ACTIVE" and any(
                k and k in mission_brief for k in ball.redline_keywords
            ):
                triggered.append(ball.ball_id)
        price_conflict = (
            all(k in facts for k in ("unit_price", "floor_price"))
            and facts["unit_price"] < facts["floor_price"]
        )
        if (
            price_conflict
            and policy_ball is not None
            and policy_floor_id not in triggered
        ):
            triggered.append(policy_floor_id)
        conflict = price_conflict or "无限连带责任" in mission_brief
        attempts = responses = 0
        for node in nodes:
            balls = node.pop("_ball_objects", [])
            runs = []
            if auto_execute_skills and not missing:
                for ball in balls:
                    if ball.ball_type != "SKILL" or ball.status != "ACTIVE":
                        continue
                    record = {
                        "execution_id": f"SKEX_{uuid.uuid4().hex[:8].upper()}",
                        "node_id": node["node_id"],
                        "slot_id": node["slot_id"],
                        "ball_id": ball.ball_id,
                        "ball_title": ball.title,
                        "isolation_mode": "python -I",
                        "input_payload": dict(facts),
                    }
                    try:
                        path = self._ensure_executable_skill_script(ball, sandbox_dir)
                        output = await asyncio.to_thread(
                            run_skill_in_isolated_subprocess,
                            script_path=path,
                            sandbox_dir=sandbox_dir,
                            input_payloads=[facts],
                            timeout_seconds=float(
                                self._state.settings.sandbox_timeout_seconds
                            ),
                        )
                        item = (
                            output[0]
                            if output
                            else {"ok": False, "error": "Missing subprocess receipt"}
                        )
                        record.update(
                            script_path=path.name,
                            sandbox_output=item.get("output"),
                            executed_ok=bool(item.get("ok")),
                            error=item.get("error", ""),
                            env_keys_leaked=item.get("env_keys_leaked", []),
                        )
                        if isinstance(item.get("output"), dict) and item["output"].get(
                            "status"
                        ) in ("error", "failed", "rejected"):
                            record["executed_ok"] = False
                    except Exception as exc:
                        record.update(
                            executed_ok=False, sandbox_output=None, error=str(exc)
                        )
                    runs.append(record)
                    executions.append(record)
            failed |= any(not r["executed_ok"] for r in runs)
            if any(not r["executed_ok"] for r in runs):
                node_status = "FAILED"
            elif conflict:
                node_status = "BLOCKED"
            else:
                node_status = "PLAN_READY"
            summary = (
                "基于本岗位实际挂载能力完成方案分析；业务动作仍需真实审批与执行回执。"
            )
            if self._is_llm_live():
                attempts += 1
                out = await self._call_llm_json(
                    "Return JSON with status, reasoning_summary, veto. Planning never authorizes business execution.",
                    json.dumps(
                        {
                            "brief": mission_brief,
                            "facts": facts,
                            "mounted_balls": [b.model_dump() for b in balls],
                            "tool_receipts": runs,
                        },
                        ensure_ascii=False,
                    ),
                )
                if out:
                    responses += 1
                    summary = str(out.get("reasoning_summary", summary))
                    if out.get("veto") or out.get("status") in (
                        "BLOCKED",
                        "CONFLICT_DETECTED",
                        "REDLINE_GUARDED",
                    ):
                        node_status = "BLOCKED" if node_status != "FAILED" else "FAILED"
                    elif out.get("status") == "FAILED":
                        node_status = "FAILED"
                        failed = True
            node.update(
                status=node_status,
                reasoning_summary=summary,
                output_summary=summary,
                risk_assessment="待核验审批、执行与业务事实",
                quantitative_metrics=dict(facts),
                executed_skill_ids=[r["ball_id"] for r in runs],
                triggered_redline_ids=triggered,
                handoff_to_downstream=sanitize_l1_text(summary).clean_text,
            )
        transcript, debate_calls, _ = await self._run_mission_redline_debate(
            mission_title=mission_title,
            mission_brief=mission_brief,
            dag_nodes=nodes,
            metrics=facts,
            skill_executions=executions,
            triggered_redlines=[self._state.particles.get_ball(b) for b in triggered],
            max_debate_rounds=max_debate_rounds,
        )
        attempts += sum(bool(turn.get("llm_attempted")) for turn in transcript)
        responses += debate_calls
        debate_veto = any(
            turn.get("veto") or turn.get("status") in ("BLOCKED", "VETO", "REJECTED")
            for turn in transcript
        )
        veto = conflict or debate_veto or any(n["status"] == "BLOCKED" for n in nodes)
        approval_needed = any(
            term in mission_brief
            for term in ("特批", "折扣", "赔偿", "返利", "账期", "合同", "任免")
        )
        if failed:
            status = "FAILED"
            summary = "工具失败，任务不能完成。"
            next_action = "REPAIR_FAILED_TOOLS"
        elif veto:
            status = "BLOCKED"
            summary = "存在否决或红线冲突，需修订方案。"
            next_action = "REVISE_BLOCKED_PLAN"
        elif missing or approval_needed:
            status = "PENDING_APPROVAL"
            summary = "方案已记录；尚无实际业务完成证据。"
            next_action = "SUBMIT_FOR_HUMAN_APPROVAL"
        else:
            status = "PLAN_READY"
            summary = "方案已记录；尚无实际业务完成证据。"
            next_action = "EXECUTE_THROUGH_AUTHORIZED_BUSINESS_WORKFLOW"
        resolution = {
            "resolution_id": f"RES_{uuid.uuid4().hex[:8].upper()}",
            "final_status": status,
            "decision": status,
            "summary": summary,
            "approved_conditions": [],
            "triggered_redline_ball_ids": triggered,
            "executed_skill_ball_ids": list(
                dict.fromkeys(r["ball_id"] for r in executions)
            ),
            "requires_temp_ball_lease": False,
            "recommended_lease_grant": None,
            "financial_impact_estimate": {
                "gross_order_amount": facts.get("order_amount")
            },
        }
        telemetry = {
            "llm_calls": responses,
            "llm_attempts": attempts,
            "llm_responses": responses,
            "estimated_tokens": 0,
            "total_latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "mode": "LIVE_CLOUD_HYBRID" if attempts else "DETERMINISTIC_SWARM",
        }
        event = self._state.vault.append_event(
            event_kind="DAG_MISSION_EVALUATED",
            subtree_root_id="root",
            actor_slot_id=nodes[0]["slot_id"],
            payload={
                "mission_id": mission_id,
                "status": status,
                "skill_execution_count": len(executions),
                "token_telemetry": telemetry,
            },
        )
        result = {
            "record_type": "DAG_MISSION",
            "mission_id": mission_id,
            "mission_title": mission_title,
            "mission_brief": mission_brief,
            "initiator_account_id": initiator_account_id,
            "status": status,
            "dag_nodes": nodes,
            "rehydrated_node_ids": rehydrated_node_ids,
            "debate_transcript": transcript,
            "skill_executions": executions,
            "consensus_resolution": resolution,
            "token_telemetry": telemetry,
            "worm_event": event.model_dump(),
            "created_at": utc_now_iso(),
            "execution_evidence": {
                "business_execution_completed": False,
                "ticket_ids": [],
                "card_receipts": [],
                "source": "CURRENT_ENTERPRISE",
                "business_facts_verified": False,
                "metrics_validation": "STRUCTURAL_ONLY",
                "metrics_source": "SYNTHETIC_PRESET_ASSERTIONS"
                if preset
                else "CALLER_ASSERTIONS",
                "policy_floor_source": policy_floor_id
                if policy_ball is not None and policy_floor > 0
                else None,
                "validated_requirements": [k for k in required if k in facts],
                "missing_requirements": missing,
            },
            "continuation": {
                "status": status,
                "required_action": next_action,
                "business_effects_applied": False,
            },
        }
        self._mission_history.insert(0, result)
        if hasattr(self._state, "sync_persistence"):
            await self._state.sync_persistence()
        return result

    async def _run_mission_redline_debate(
        self,
        mission_title: str,
        mission_brief: str,
        dag_nodes: list[dict[str, Any]],
        metrics: dict[str, Any],
        skill_executions: list[dict[str, Any]],
        triggered_redlines: list[CapabilityBall],
        max_debate_rounds: int,
    ) -> tuple[list[dict[str, Any]], int, int]:
        transcript = []
        responses = 0
        blocked = any(node["status"] == "BLOCKED" for node in dag_nodes)
        failed_tools = [r["ball_id"] for r in skill_executions if not r["executed_ok"]]
        redline_ids = [b.ball_id for b in triggered_redlines if b is not None]
        for index in range(max(1, min(6, int(max_debate_rounds)))):
            stance = ("PROPOSE", "CHALLENGE", "SYNTHESIZE")[min(index, 2)]
            if index == 0:
                speaker = dag_nodes[0]
                text = "提报当前任务与已提供事实，申请跨岗位核验。"
            elif index == 1:
                speaker = dag_nodes[min(2, len(dag_nodes) - 1)]
                text = f"核验实际工具回执；失败能力 {failed_tools}，触发策略 {redline_ids}。"
            else:
                speaker = dag_nodes[-1]
                text = "合并各方证据，保留未决约束，提交独立审批与后续执行流程。"
            turn = {
                "round": index + 1,
                "round_number": index + 1,
                "stance": stance,
                "slot_id": speaker["slot_id"],
                "slot_title": speaker["slot_title"],
                "argument": text,
                "concession_or_demand": "补齐可核验事实、审批和业务执行回执。",
                "cited_redline_ids": redline_ids,
                "cited_ball_ids": [b["ball_id"] for b in speaker["mounted_balls"]],
                "veto": blocked or bool(failed_tools),
                "llm_attempted": False,
                "evidence_source": "CURRENT_ENTERPRISE_RULES_AND_TOOL_RECEIPTS",
            }
            if self._is_llm_live():
                turn["llm_attempted"] = True
                parsed = await self._call_llm_json(
                    "Return JSON argument, concession_or_demand, veto. Cite supplied real evidence. You discuss a plan and cannot grant approvals, leases, rebates, or execution authority.",
                    json.dumps(
                        {
                            "title": mission_title,
                            "brief": mission_brief,
                            "stance": stance,
                            "facts": metrics,
                            "nodes": dag_nodes,
                            "tool_receipts": skill_executions,
                            "prior_turns": transcript,
                        },
                        ensure_ascii=False,
                    ),
                )
                if parsed:
                    responses += 1
                    turn["argument"] = str(parsed.get("argument", text))
                    turn["concession_or_demand"] = str(
                        parsed.get("concession_or_demand", turn["concession_or_demand"])
                    )
                    turn["veto"] = (
                        turn["veto"]
                        or bool(parsed.get("veto"))
                        or parsed.get("status") in ("BLOCKED", "VETO", "REJECTED")
                    )
            transcript.append(turn)
        return transcript, responses, 0

    async def run_adversarial_debate(
        self,
        topic: str,
        proposer_slot_id: Optional[str] = None,
        reviewer_slot_id: Optional[str] = None,
        arbiter_slot_id: Optional[str] = None,
        rounds: int = 3,
    ) -> dict[str, Any]:
        if self._state is None:
            raise RuntimeError(
                "DAGMissionEngine requires an initialized EnterpriseState"
            )
        containers = self._state.containers
        _, frontline = resolve_frontline_user_and_slot(containers)
        _, leader = resolve_leader_user_and_slot(containers)
        slots = [
            containers.get_slot(s)
            for s in (
                proposer_slot_id or frontline,
                reviewer_slot_id or leader,
                arbiter_slot_id or leader,
            )
        ]
        transcripts = []
        veto = False
        attempts = responses = 0
        for idx in range(max(1, min(int(rounds), 6))):
            cited = [
                b.ball_id
                for slot in slots
                for b in self._get_slot_mounted_balls(slot.slot_id)
            ]
            turn = {
                "round": idx + 1,
                "proposer_slot_id": slots[0].slot_id,
                "reviewer_slot_id": slots[1].slot_id,
                "arbiter_slot_id": slots[2].slot_id,
                "proposer_cited_balls": [
                    b.ball_id for b in self._get_slot_mounted_balls(slots[0].slot_id)
                ],
                "reviewer_cited_balls": [
                    b.ball_id for b in self._get_slot_mounted_balls(slots[1].slot_id)
                ],
                "cited_ball_ids": list(dict.fromkeys(cited)),
                "proposer_argument": topic,
                "reviewer_rebuttal": "请提交可核验业务事实、红线符合性与审批证据。",
                "arbiter_comment": "讨论仅形成待审批方案，不授予执行权。",
                "veto": False,
            }
            if self._is_llm_live():
                attempts += 1
                parsed = await self._call_llm_json(
                    "Return JSON proposer_argument, reviewer_rebuttal, arbiter_comment, veto. No execution authority.",
                    json.dumps({"topic": topic, "evidence": cited}, ensure_ascii=False),
                )
                if parsed:
                    responses += 1
                    for key in (
                        "proposer_argument",
                        "reviewer_rebuttal",
                        "arbiter_comment",
                    ):
                        turn[key] = str(parsed.get(key, turn[key]))
                    turn["veto"] = bool(parsed.get("veto"))
            veto |= turn["veto"]
            turn["content"] = "\n".join(
                turn[k]
                for k in ("proposer_argument", "reviewer_rebuttal", "arbiter_comment")
            )
            transcripts.append(turn)
        status = "BLOCKED" if veto else "PENDING_APPROVAL"
        verdict = {
            "verdict_id": f"VRD_{uuid.uuid4().hex[:8].upper()}",
            "arbiter_slot_id": slots[2].slot_id,
            "decision": status,
            "ruling": status,
            "verdict": status,
            "summary": "讨论结果需经过独立人工审批及真实业务执行。",
            "rationale": "无实际审批凭证或业务执行回执，不能宣称完成或批准。",
            "mandatory_guardrails": ["核验业务事实", "独立人工审批", "收集执行回执"],
            "cited_ball_ids": list(
                dict.fromkeys(b for turn in transcripts for b in turn["cited_ball_ids"])
            ),
            "authorized_lease": None,
        }
        record = {
            "record_type": "ADVERSARIAL_DEBATE",
            "debate_id": f"DBT_{uuid.uuid4().hex[:8].upper()}",
            "topic": topic,
            "status": status,
            "rounds": transcripts,
            "final_verdict": verdict,
            "token_telemetry": {
                "llm_calls": responses,
                "llm_attempts": attempts,
                "llm_responses": responses,
                "estimated_tokens": 0,
                "mode": "LIVE_CLOUD_HYBRID" if attempts else "DETERMINISTIC_SWARM",
            },
            "created_at": utc_now_iso(),
        }
        event = self._state.vault.append_event(
            event_kind="ADVERSARIAL_DEBATE_EVALUATED",
            subtree_root_id="root",
            actor_slot_id=slots[2].slot_id,
            payload={
                "debate_id": record["debate_id"],
                "status": status,
                "token_telemetry": record["token_telemetry"],
            },
        )
        record["worm_event"] = event.model_dump()
        record["evidence_provenance"] = {
            "source": "CURRENT_ENTERPRISE_MOUNTED_CAPABILITIES",
            "business_execution_completed": False,
        }
        self._debate_history.insert(0, record)
        if hasattr(self._state, "sync_persistence"):
            await self._state.sync_persistence()
        return record

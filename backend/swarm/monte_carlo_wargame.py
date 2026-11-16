from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import random
import time
import uuid
from typing import Any, Optional

from core.schemas import CapabilityBall, utc_now_iso
from core.topology_resolver import (
    resolve_active_authority_ball,
    resolve_active_redline_and_floor,
    resolve_blackbox_user_and_slot,
    resolve_frontline_user_and_slot,
    resolve_leader_user_and_slot,
    resolve_slot_by_role_keywords,
)
from swarm.evolution_arena import run_skill_in_isolated_subprocess, sandbox_ast_guard

EnterpriseState = Any


BLACK_SWAN_SCENARIOS: list[dict[str, Any]] = [
    {
        "scenario_id": "swan_raw_material_surge",
        "title": "上游特种钢/锂电原材料 72 小时暴涨 38% + 核心大客户要求按原锁定低价履约",
        "scenario_title": "上游特种钢/锂电原材料 72 小时暴涨 38% + 核心大客户要求按原锁定低价履约",
        "category": "COMMODITY_PRICE_SHOCK",
        "severity": "EXTREME",
        "default_horizon_days": 30,
        "default_monte_carlo_paths": 25,
        "involved_departments": [
            "产研供应链采购部",
            "商务跟单部",
            "财税法务双黑盒部",
            "顶层治理董事会",
        ],
        "involved_slots": [
            "ROLE_PROCURE",
            "ROLE_FRONTLINE",
            "ROLE_BLACKBOX",
            "SLOT_BOSS",
        ],
        "shock_parameters": {
            "raw_material_surge_pct": 38.0,
            "shock_window_hours": 72,
            "locked_order_revenue_cny": 3200000.0,
            "baseline_gross_margin_pct": 24.5,
            "unhedged_margin_drop_pct": -14.8,
            "default_penalty_rate_pct": 15.0,
            "base_stockout_prob": 0.42,
        },
        "description": (
            "受国际矿山罢工与出口配额骤降影响，上游特种原材料与核心模组在 72 小时内现货暴涨 38%。"
            "与此同时，已签署框架意向的 3 家跨国大客户要求按原锁定低价（¥500/单位基准）强制履约排产，"
            "若直接按原价交货将导致单批毛利率击穿 -14.8% 严重穿仓；若单方面毁约停发则面临大额违约索赔。"
        ),
        "brief": (
            "上游特种钢/锂电原材料 72 小时暴涨 38%，核心大客户要求按原锁定低价履约，面临毛利穿仓与违约金双杀风险。"
        ),
        "exposed_vulnerability": "缺乏原材料指数联动调价熔断红线（Cost-Pass-Through Redline）与动态阶梯止损对冲算子。",
    },
    {
        "scenario_id": "swan_port_customs_freeze",
        "title": "主干线港口/边境突发封关 14 天 + 冷链/重卡滞港费按日累进暴增",
        "scenario_title": "主干线港口/边境突发封关 14 天 + 冷链/重卡滞港费按日累进暴增",
        "category": "LOGISTICS_BORDER_FREEZE",
        "severity": "CRITICAL",
        "default_horizon_days": 30,
        "default_monte_carlo_paths": 25,
        "involved_departments": [
            "智能仓储物流部",
            "商务跟单部",
            "财税法务双黑盒部",
            "经营管理与进化部",
        ],
        "involved_slots": [
            "SLOT_WMS_01",
            "SLOT_LOGISTICS_01",
            "SLOT_LEGAL_BOX",
            "SLOT_DEPT_MGR",
        ],
        "shock_parameters": {
            "freeze_days": 14,
            "daily_demurrage_base_cny": 18500.0,
            "progressive_multiplier": 1.18,
            "locked_order_revenue_cny": 2600000.0,
            "baseline_gross_margin_pct": 22.0,
            "unhedged_margin_drop_pct": -11.2,
            "base_stockout_prob": 0.55,
        },
        "description": (
            "主干线海运枢纽港及跨境陆运口岸突发极端天气与系统升级联动封关 14 天，"
            "在途 42 个重卡/冷链标准柜滞留口岸，滞港费与插电柜租按日累进暴增（日均复合递增 18%），"
            "同时华南与华东分仓安全库存跌破红线，下游订单大面积面临断供与延迟交付违约。"
        ),
        "brief": (
            "主干线港口/边境突发封关 14 天，重卡/冷链滞港费按日累进暴增，多仓安全库存告急。"
        ),
        "exposed_vulnerability": "缺乏口岸滞期费单柜封顶熔断红线与替代走廊跨仓分流经济性精算技能球。",
    },
    {
        "scenario_id": "swan_key_account_default",
        "title": "TOP1 经销商资金链断裂逾期 450 万 + 申请债转货与二次账期展期",
        "scenario_title": "TOP1 经销商资金链断裂逾期 450 万 + 申请债转货与二次账期展期",
        "category": "KEY_ACCOUNT_CREDIT_DEFAULT",
        "severity": "EXTREME",
        "default_horizon_days": 30,
        "default_monte_carlo_paths": 25,
        "involved_departments": [
            "财税法务双黑盒部",
            "商务跟单部",
            "智能仓储物流部",
            "顶层治理董事会",
        ],
        "involved_slots": [
            "ROLE_BLACKBOX",
            "ROLE_LEGAL",
            "ROLE_LEADER",
            "SLOT_BOSS",
        ],
        "shock_parameters": {
            "overdue_receivables_cny": 4500000.0,
            "extension_days_requested": 90,
            "locked_order_revenue_cny": 4500000.0,
            "baseline_gross_margin_pct": 25.0,
            "unhedged_margin_drop_pct": -18.5,
            "base_stockout_prob": 0.18,
        },
        "description": (
            "集团年度销量占比 22% 的 TOP1 核心总代经销商突发下游暴雷、资金链断裂，"
            "已到期 450 万元应收账款全面逾期，并向商务部申请【以异地积压库存债转货抵扣 60% 欠款 + 剩余 40% 二次展期 90 天 + 继续赊销发新货】。"
            "若盲目批准二次展期将引发集团经营性现金流枯竭与坏账穿仓。"
        ),
        "brief": (
            "TOP1 经销商资金链断裂逾期 450 万，申请折价债转货与二次账期展期 90 天。"
        ),
        "exposed_vulnerability": "缺乏逾期授信一键停发熔断红线与债转货公允残值折扣精算技能球。",
    },
    {
        "scenario_id": "swan_regulatory_tax_audit",
        "title": "行业税务与反商业贿赂突击合规审查 + 历史越权拆单全面追溯",
        "scenario_title": "行业税务与反商业贿赂突击合规审查 + 历史越权拆单全面追溯",
        "category": "REGULATORY_COMPLIANCE_SWEEP",
        "severity": "CRITICAL",
        "default_horizon_days": 30,
        "default_monte_carlo_paths": 25,
        "involved_departments": [
            "财税法务双黑盒部",
            "经营管理与进化部",
            "商务跟单部",
            "顶层治理董事会",
        ],
        "involved_slots": [
            "ROLE_LEGAL",
            "ROLE_BLACKBOX",
            "ROLE_HR",
            "SLOT_BOSS",
        ],
        "shock_parameters": {
            "audit_lookback_months": 12,
            "flagged_split_orders": 36,
            "locked_order_revenue_cny": 2800000.0,
            "baseline_gross_margin_pct": 23.0,
            "unhedged_margin_drop_pct": -9.5,
            "base_stockout_prob": 0.12,
        },
        "description": (
            "监管部门启动行业金税四期数电专票交叉稽核与反商业贿赂突击合规审查，"
            "重点追溯过去 12 个月内一线销售为规避 8.5 折高压线审批而实施的【化整为零拆单】、"
            "【无前置入网订单提前开票】及【超比例渠道返点】，须在 72 小时内完成 WORM 账本自查与制度补丁固化。"
        ),
        "brief": (
            "行业税务与反商业贿赂突击合规审查，全面追溯历史越权拆单与超标返利。"
        ),
        "exposed_vulnerability": "缺乏同一税号24小时累计拆单合并拦截红线与返利合规税盾精算技能球。",
    },
]


class MonteCarloWargameEngine:
    """
    Pillar 5：多智能体蒙特卡洛经营沙盘推演与极端黑天鹅压力测试引擎
    (Monte Carlo Enterprise War-Gaming & Black-Swan Simulator)
    """

    def __init__(
        self,
        state: Optional[EnterpriseState] = None,
        runtime: Optional[EnterpriseState] = None,
    ) -> None:
        self._state = state if state is not None else runtime
        self._history: list[dict[str, Any]] = []

    def bind_state(self, state: EnterpriseState) -> None:
        self._state = state

    def get_black_swan_scenarios(self) -> list[dict[str, Any]]:
        return copy.deepcopy(BLACK_SWAN_SCENARIOS)

    def get_history(self) -> dict[str, Any]:
        clone = getattr(self._state, "simulation_runtime", None)
        if clone is not None:
            return clone.wargame_engine.get_history()
        return {
            "count": len(self._history),
            "simulations": list(self._history),
            "history": list(self._history),
        }

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
                return json.loads(resp.choices[0].message.content or "{}")
        except Exception:
            if hasattr(gw, "_telemetry") and isinstance(gw._telemetry, dict):
                gw._telemetry["deterministic_engine_hits"] = (
                    int(gw._telemetry.get("deterministic_engine_hits", 0)) + 1
                )
        return None

    def _resolve_scenario(
        self,
        scenario_id_or_custom: str,
        custom_title: Optional[str] = None,
        custom_description: Optional[str] = None,
        shock_parameters: Optional[dict[str, float]] = None,
    ) -> dict[str, Any]:
        clean_key = (scenario_id_or_custom or "").strip()
        selected: Optional[dict[str, Any]] = None
        for sc in BLACK_SWAN_SCENARIOS:
            if sc["scenario_id"] == clean_key or sc["title"] == clean_key:
                selected = copy.deepcopy(sc)
                break

        if custom_description and (selected is None or custom_description.strip() != selected["description"].strip()):
            selected = None
        if selected is None:
            if not shock_parameters:
                raise ValueError("Custom scenarios require structured shock_parameters; descriptions are not quantified shocks")
            required = {"locked_order_revenue_cny", "baseline_gross_margin_pct", "unhedged_margin_drop_pct", "base_stockout_prob"}
            if not required.issubset(shock_parameters):
                raise ValueError(f"shock_parameters requires: {', '.join(sorted(required))}")
            params = {key: float(value) for key, value in shock_parameters.items()}
            if not all(math.isfinite(value) for value in params.values()):
                raise ValueError("shock_parameters must be finite")
            if params["locked_order_revenue_cny"] <= 0 or not 0 <= params["base_stockout_prob"] <= 1:
                raise ValueError("shock_parameters requires positive revenue and stockout probability in [0,1]")
            if not -100 <= params["unhedged_margin_drop_pct"] <= 0 or not 0 <= params["baseline_gross_margin_pct"] <= 100:
                raise ValueError("shock_parameters margin percentages outside valid range")
            title = custom_title or clean_key[:80] or "自定义结构化冲击"
            desc = custom_description or clean_key
            selected = {
                "scenario_id": f"swan_custom_{hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:12]}",
                "title": title, "scenario_title": title, "description": desc, "brief": desc[:120],
                "category": "CUSTOM_STRUCTURED_SHOCK", "severity": "CUSTOM",
                "shock_parameters": params,
                "involved_departments": ["业务", "供应链", "财务", "治理"],
                "involved_slots": ["ROLE_FRONTLINE", "ROLE_PROCURE", "ROLE_BLACKBOX", "SLOT_BOSS"],
                "exposed_vulnerability": "用户定义的结构化风险参数；政策建议尚未经过业务执行评估。",
            }
        elif shock_parameters:
            raise ValueError("shock_parameters may only be supplied for custom scenarios")

        if self._state is not None and getattr(self._state, "containers", None) is not None:
            containers = self._state.containers
            _, fl_slot = resolve_frontline_user_and_slot(containers)
            _, ld_slot = resolve_leader_user_and_slot(containers)
            _, bb_slot = resolve_blackbox_user_and_slot(containers)
            boss_slots, mgr_slots = ([s.slot_id for s in containers.list_slots() if s.slot_id == "SLOT_BOSS"], [])
            role_map = {
                "ROLE_FRONTLINE": fl_slot,
                "ROLE_LEADER": ld_slot,
                "ROLE_BLACKBOX": bb_slot,
                "ROLE_PROCURE": resolve_slot_by_role_keywords(containers, ["采购", "产研", "供应", "工程"]),
                "ROLE_WMS": resolve_slot_by_role_keywords(containers, ["仓", "物流", "调度"]),
                "ROLE_LOGISTICS": resolve_slot_by_role_keywords(containers, ["物流", "交付", "履约"]),
                "ROLE_LEGAL": resolve_slot_by_role_keywords(containers, ["法务", "合规", "风控", "审计"], ("finance_tool", "leader")),
                "ROLE_HR": resolve_slot_by_role_keywords(containers, ["人事", "HR", "进化", "治理"], ("manager", "leader")),
                "ROLE_MANAGER": (mgr_slots[0] if mgr_slots else resolve_slot_by_role_keywords(containers, ["管理", "经理"], ("manager",))),
                "SLOT_BOSS": boss_slots[0] if boss_slots else containers.list_slots()[-1].slot_id,
            }
            resolved_slots: list[str] = []
            for token in selected.get("involved_slots", []):
                mapped = role_map.get(token, token)
                if mapped not in resolved_slots:
                    resolved_slots.append(mapped)
            selected["involved_slots"] = resolved_slots
        return selected

    def _simulate_monte_carlo_paths(
        self,
        scenario: dict[str, Any],
        horizon_days: int,
        num_paths: int,
        auto_forge_defensive_balls: bool,
    ) -> dict[str, Any]:
        seed_bytes = hashlib.sha256(
            f"{scenario['scenario_id']}::{horizon_days}::{num_paths}".encode("utf-8")
        ).digest()
        seed = int.from_bytes(seed_bytes[:8], "big")
        rng = random.Random(seed)

        shock = scenario.get("shock_parameters", {})
        base_rev = float(shock.get("locked_order_revenue_cny", 3200000.0))
        base_margin_pct = float(shock.get("baseline_gross_margin_pct", 24.0))
        unhedged_drop_pct = float(shock.get("unhedged_margin_drop_pct", -14.0))
        base_stockout = float(shock.get("base_stockout_prob", 0.38))
        horizon_factor = max(0.5, min(2.2, horizon_days / 30.0))

        cashflow_impacts: list[float] = []
        drawdowns: list[float] = []
        margin_deltas: list[float] = []
        collection_rates: list[float] = []
        penalty_exposures: list[float] = []
        stockout_probs: list[float] = []
        redline_hits = 0
        survived_count = 0
        unmitigated_survived = 0
        sample_paths: list[dict[str, Any]] = []

        for path_idx in range(1, num_paths + 1):
            # 随机冲击强度因子 (正态+肥尾偏态)
            shock_z = abs(rng.gauss(1.0, 0.28)) + (0.35 if rng.random() < 0.15 else 0.0)
            raw_margin_shock = unhedged_drop_pct * shock_z * math.sqrt(horizon_factor)

            # 无防御球干预时的净现金流冲击与回款率
            raw_collection = max(0.42, min(0.95, 0.82 - 0.18 * shock_z))
            raw_penalty = round(base_rev * 0.085 * shock_z * horizon_factor, 2)
            unmitigated_cf = round(
                base_rev * (raw_margin_shock / 100.0)
                - raw_penalty
                - base_rev * (1.0 - raw_collection) * 0.35,
                2,
            )
            raw_path_survived = unmitigated_cf >= -base_rev * 0.18 and raw_collection >= 0.72
            unmitigated_survived += int(raw_path_survived)

            # Candidate generation does not execute a defense. Both arms use
            # the same sampled baseline and the same survival rule.
            effective_margin_delta = round(raw_margin_shock, 2)
            effective_collection = raw_collection
            effective_penalty = raw_penalty
            effective_stockout = round(max(0.03, min(0.95, base_stockout * shock_z)), 4)
            net_cf_impact = unmitigated_cf
            peak_drawdown = round(
                abs(min(0.0, net_cf_impact)) * (1.15 + 0.1 * rng.random()), 2
            )

            # 判断该路径是否触碰红线阈值
            breached = bool(
                raw_margin_shock <= -11.5
                or shock_z >= 1.12
                or effective_stockout >= 0.30
            )
            if breached:
                redline_hits += 1

            path_survived = raw_path_survived
            if path_survived:
                survived_count += 1

            cashflow_impacts.append(net_cf_impact)
            drawdowns.append(peak_drawdown)
            margin_deltas.append(effective_margin_delta)
            collection_rates.append(effective_collection)
            penalty_exposures.append(effective_penalty)
            stockout_probs.append(effective_stockout)

            if len(sample_paths) < 12:
                sample_paths.append(
                    {
                        "path_id": f"MC_PATH_{path_idx:02d}",
                        "shock_multiplier": round(shock_z, 3),
                        "gross_margin_delta_pct": effective_margin_delta,
                        "cashflow_collection_rate": effective_collection,
                        "penalty_exposure_cny": effective_penalty,
                        "stockout_probability": effective_stockout,
                        "net_cashflow_impact_cny": net_cf_impact,
                        "unmitigated_cashflow_impact_cny": unmitigated_cf,
                        "max_drawdown_cny": peak_drawdown,
                        "redline_triggered": breached,
                        "survived": path_survived,
                    }
                )

        sorted_cf = sorted(cashflow_impacts)
        n = len(sorted_cf)
        p10_idx = max(0, min(n - 1, int(math.floor(n * 0.10))))
        p50_idx = max(0, min(n - 1, int(math.floor(n * 0.50))))
        p90_idx = max(0, min(n - 1, int(math.floor(n * 0.90))))

        p10_cf = round(sorted_cf[p10_idx], 2)
        p50_cf = round(sorted_cf[p50_idx], 2)
        p90_cf = round(sorted_cf[p90_idx], 2)
        worst_drawdown = round(max(drawdowns), 2)
        max_drawdown_pct = round((worst_drawdown / base_rev) * 100.0, 2)
        redline_rate = round(redline_hits / n, 4)

        survival_score = round(100.0 * survived_count / n, 1)
        unmitigated_score = round(100.0 * unmitigated_survived / n, 1)

        return {
            "random_seed": seed,
            "comparison_method": "PAIRED_IDENTICAL_SHOCKS_AND_SURVIVAL_CRITERION",
            "survival_criterion": "cashflow >= -0.18 * revenue AND collection_rate >= 0.72",
            "defense_effect_status": "NOT_MEASURED",
            "paths_simulated": n,
            "total_paths": n,
            "horizon_days": horizon_days,
            "baseline_revenue_cny": base_rev,
            "baseline_gross_margin_pct": base_margin_pct,
            "p10_net_cashflow_impact": p10_cf,
            "p50_net_cashflow_impact": p50_cf,
            "p90_net_cashflow_impact": p90_cf,
            "p10_cashflow_cny": p10_cf,
            "p50_cashflow_cny": p50_cf,
            "p90_cashflow_cny": p90_cf,
            "max_drawdown": worst_drawdown,
            "max_drawdown_cny": worst_drawdown,
            "max_drawdown_pct": max_drawdown_pct,
            "redline_trigger_rate": redline_rate,
            "redline_breach_probability": redline_rate,
            "gross_margin_volatility_pct": round(
                sum(abs(m) for m in margin_deltas) / n, 2
            ),
            "cashflow_collection_rate_mean": round(
                sum(collection_rates) / n, 4
            ),
            "penalty_exposure_mean_cny": round(
                sum(penalty_exposures) / n, 2
            ),
            "stockout_probability_mean": round(sum(stockout_probs) / n, 4),
            "survival_score": survival_score,
            "unmitigated_survival_score": unmitigated_score,
            "resilience_gain_points": round(survival_score - unmitigated_score, 1),
            "sample_paths": sample_paths,
        }

    def _build_timeline_stages(
        self,
        scenario: dict[str, Any],
        horizon_days: int,
        mc_metrics: dict[str, Any],
        forged_balls: list[dict[str, Any]],
        llm_stage_overrides: Optional[list[dict[str, Any]]] = None,
    ) -> list[dict[str, Any]]:
        forged_ids = [b["ball_id"] for b in forged_balls]
        d1 = max(3, horizon_days // 10)
        d2 = max(7, horizon_days // 4)
        d3 = max(15, horizon_days // 2)

        floor_redline_id = "REDLINE_FLOOR_GUARD"
        legal_redline_id = "REDLINE_LEGAL_GUARD"
        auth_ball_id = "AUTH_GATE_GUARD"
        if self._state is not None and getattr(self._state, "particles", None) is not None:
            particles = self._state.particles
            floor_redline_id, _, _ = resolve_active_redline_and_floor(particles)
            all_rl = particles.list_redline_balls()
            legal_rl = next(
                (b.ball_id for b in all_rl if "LEGAL" in b.ball_id or "法务" in b.title or "违约" in b.title),
                floor_redline_id,
            )
            legal_redline_id = legal_rl
            auth_ball_id = resolve_active_authority_ball(particles)

        actions = [
            ("冲击监测与风险识别", "建议审查现有成本和授信敞口，核验触发条件后提交人工审批；尚未执行风险熔断。"),
            ("跨部门应对方案", "建议仓储与法务评估替代履约路线及合同抗辩依据；未模拟实际供应和合同履约效果。"),
            ("现金流保护方案", "建议财务评估首付调整、调价和成本分摊的可行性；尚无已执行回款改善证据。"),
            ("治理复盘与候选防御", "将生成的防御资产提交治理审查；自动锻造不代表政策获批或生存率得到改善。"),
        ]
        boundaries = [0, min(d1, horizon_days), min(d2, horizon_days), min(d3, horizon_days), horizon_days]
        default_stages = []
        for idx, (title, action) in enumerate(actions):
            default_stages.append({
                "stage_index": idx + 1, "stage_id": f"WARGAME_STAGE_{idx + 1:02d}",
                "time_window": f"Day {min(boundaries[idx] + 1, horizon_days)}~{boundaries[idx + 1]}",
                "week_label": f"阶段 {idx + 1}", "stage_title": title, "title": title,
                "lead_department": scenario["involved_departments"][idx],
                "lead_slot_id": scenario["involved_slots"][idx % len(scenario["involved_slots"])],
                "participating_slots": scenario["involved_slots"], "shock_event": scenario["brief"],
                "defensive_action": action, "cited_ball_ids": forged_ids,
                "cashflow_impact_delta": 0.0, "risk_mitigation_pct": 0.0,
                "status": "PROPOSED", "effect_evaluated": False,
            })

        if llm_stage_overrides and isinstance(llm_stage_overrides, list):
            for idx, ov in enumerate(llm_stage_overrides[: len(default_stages)]):
                if isinstance(ov, dict) and ov.get("defensive_action"):
                    default_stages[idx]["defensive_action"] = str(
                        ov["defensive_action"]
                    )
                    if ov.get("stage_title"):
                        default_stages[idx]["stage_title"] = str(ov["stage_title"])
                        default_stages[idx]["title"] = str(ov["stage_title"])

        return default_stages

    def _forge_and_mount_defensive_balls(
        self,
        scenario: dict[str, Any],
        mc_metrics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if self._state is None:
            return []

        particles = self._state.particles
        containers = self._state.containers
        sandbox_dir = Path(self._state.settings.sandbox_workspace_dir)
        sandbox_dir.mkdir(parents=True, exist_ok=True)

        short_tag = uuid.uuid4().hex[:6].upper()
        sc_id = scenario["scenario_id"]

        # 1. 铸造并挂载 1 颗应急防御 REDLINE 球
        redline_ball_id = f"BALL_REDLINE_WARGAME_{short_tag}"
        if "raw_material" in sc_id:
            rl_title = "黑天鹅原材料暴涨38%锁价熔断与成本联动传导红线"
            rl_keywords = ["强制原低价排产", "拒绝成本联动调价", "亏本锁价直发"]
            rl_tags = ["底价", "黑天鹅防御", "供应链", "红线熔断"]
        elif "port" in sc_id or "customs" in sc_id:
            rl_title = "口岸封关滞港费单柜封顶与不可抗力免责红线"
            rl_keywords = ["全额承担无限滞港费", "放弃不可抗力抗辩", "超时滞箱费免审"]
            rl_tags = ["物流", "黑天鹅防御", "法务", "红线熔断"]
        elif "default" in sc_id or "account" in sc_id:
            rl_title = "逾期经销商停发熔断与债转货公允折价红线"
            rl_keywords = ["逾期继续赊销发货", "债转货100%原值抵扣", "无抵押二次展期"]
            rl_tags = ["财税", "黑天鹅防御", "大客户", "红线熔断"]
        else:
            rl_title = "反商业贿赂与同税号24h拆单规避审批拦截红线"
            rl_keywords = ["化整为零拆单", "无合同预支返点", "绕过高压线拆单"]
            rl_tags = ["合规", "黑天鹅防御", "风控审批", "红线熔断"]

        target_slots = [
            s
            for s in scenario.get("involved_slots", [])
            if s in {sl.slot_id for sl in containers.list_slots()}
        ]
        if "SLOT_BOSS" not in target_slots:
            target_slots.append("SLOT_BOSS")

        redline_ball = CapabilityBall(
            ball_id=redline_ball_id,
            ball_type="REDLINE",
            title=rl_title,
            domain_tags=rl_tags,
            sensitivity_level=5,
            owner_slot_ids=target_slots,
            content=(
                f"【蒙特卡洛沙盘自动锻造防御红线 · 源自 {scenario['title'][:20]}】"
                f"当冲击导致毛利回撤或逾期敞口触及 P10 极值（¥{mc_metrics['p10_net_cashflow_impact']:,.2f}）时，"
                "强制熔断常规低折放行通道，严禁未经成本传导对冲或足额抵押直接履约！"
            ),
            redline_keywords=rl_keywords,
            status="CANDIDATE",
        )

        # 2. 铸造并挂载 1 颗应急止损精算 Python SKILL 球（真实落盘并通过 python -I 净室子进程校验）
        skill_ball_id = f"BALL_SKILL_WARGAME_{short_tag}"
        script_filename = f"skill_{skill_ball_id.lower()}.py"
        script_path = sandbox_dir / script_filename

        skill_code = '''from decimal import Decimal, ROUND_HALF_UP


def execute_skill(payload: dict) -> dict:
    """
    蒙特卡洛黑天鹅应急止损与动态对冲精算算子 (Cleanroom Verified)
    输入:
      - order_amount / revenue_cny: 订单基准金额
      - cost_surge_pct: 原材料/滞港/坏账冲击百分比 (默认 38.0)
      - pass_through_ratio: 向买方传导分摊比例 (默认 0.55)
      - down_payment_ratio: 强制上调后的首付款比例 (默认 0.55)
    输出:
      - status: "ok"
      - result: 经止损对冲后的净保护毛利额
    """
    rev = Decimal(str(payload.get("order_amount", payload.get("revenue_cny", 100000))))
    surge_pct = Decimal(str(payload.get("cost_surge_pct", 38.0))) / Decimal("100")
    pass_ratio = Decimal(str(payload.get("pass_through_ratio", 0.55)))
    dp_ratio = Decimal(str(payload.get("down_payment_ratio", 0.55)))
    base_margin_rate = Decimal(str(payload.get("base_margin_rate", 0.24)))

    raw_shock_loss = (rev * surge_pct * Decimal("0.60")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    hedged_recovery = (raw_shock_loss * pass_ratio + rev * dp_ratio * Decimal("0.03")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    protected_margin = (rev * base_margin_rate - raw_shock_loss + hedged_recovery).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    required_surcharge_pct = (surge_pct * pass_ratio * Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    return {
        "status": "ok",
        "result": float(protected_margin),
        "raw_shock_loss_cny": float(raw_shock_loss),
        "hedged_recovery_cny": float(hedged_recovery),
        "protected_net_margin_cny": float(protected_margin),
        "required_surcharge_pct": float(required_surcharge_pct),
    }
'''
        sandbox_ast_guard(skill_code)
        script_path.write_text(skill_code, encoding="utf-8")

        verification_inputs = [
            {
                "order_amount": 3200000.0,
                "cost_surge_pct": 38.0,
                "pass_through_ratio": 0.55,
                "down_payment_ratio": 0.55,
            },
            {
                "order_amount": 500000.0,
                "cost_surge_pct": 25.0,
                "pass_through_ratio": 0.50,
                "down_payment_ratio": 0.60,
            },
        ]
        verify_runs = run_skill_in_isolated_subprocess(
            script_path=script_path,
            sandbox_dir=sandbox_dir,
            input_payloads=verification_inputs,
            timeout_seconds=float(
                getattr(self._state.settings, "sandbox_timeout_seconds", 3.0)
            ),
        )

        if not verify_runs or not all(r.get("ok", False) for r in verify_runs):
            raise RuntimeError("Wargame candidate skill sandbox validation failed")

        skill_ball = CapabilityBall(
            ball_id=skill_ball_id,
            ball_type="SKILL",
            title=f"黑天鹅应急止损与动态调价对冲精算器 ({scenario['scenario_id']})",
            domain_tags=["黑天鹅防御", "止损精算", "报价", "风控审批"],
            sensitivity_level=3,
            owner_slot_ids=target_slots,
            content=(
                f"针对《{scenario['title']}》自动合成并通过 python -I 净室沙箱校验的应急止损精算算子，"
                "支持实时测算原材料暴涨/滞港费传导分摊比例、首付上调贴现回收额与保护毛利底线。"
            ),
            executable_code_path=script_filename,
            status="CANDIDATE",
        )
        particles.register_ball(redline_ball, record_to_vault=True)
        particles.register_ball(skill_ball, record_to_vault=True)

        return [
            {
                **redline_ball.model_dump(),
                "mounted_to_slots": [], "proposed_target_slots": target_slots,
                "forged_role": "EMERGENCY_DEFENSIVE_REDLINE",
            },
            {
                **skill_ball.model_dump(),
                "mounted_to_slots": [], "proposed_target_slots": target_slots,
                "forged_role": "EMERGENCY_STOPLOSS_SKILL",
                "generated_code": skill_code,
                "sandbox_verification": {
                    "verification_scope": "EXECUTION_ONLY",
                    "business_effect_evaluated": False,
                    "isolation_mode": "python -I",
                    "script_path": script_filename,
                    "all_passed": all(r.get("ok", False) for r in verify_runs),
                    "sample_outputs": verify_runs,
                },
            },
        ]

    async def run_wargame_simulation(
        self,
        scenario_id_or_custom: str = "swan_raw_material_surge",
        horizon_days: int = 30,
        monte_carlo_paths: int = 20,
        auto_forge_defensive_balls: bool = True,
        custom_title: Optional[str] = None,
        custom_description: Optional[str] = None,
        shock_parameters: Optional[dict[str, float]] = None,
    ) -> dict[str, Any]:
        if self._state is not None and hasattr(self._state, "settings") and not getattr(self._state, "simulation_scope", None):
            from core.simulation_workspace import get_simulation_runtime
            clone = await get_simulation_runtime(self._state)
            return await clone.wargame_engine.run_wargame_simulation(
                scenario_id_or_custom, horizon_days, monte_carlo_paths, auto_forge_defensive_balls,
                custom_title, custom_description, shock_parameters)
        t0 = time.perf_counter()
        if self._state is None:
            raise RuntimeError(
                "MonteCarloWargameEngine requires an initialized EnterpriseState"
            )

        num_paths = max(5, min(100, int(monte_carlo_paths or 20)))
        days = max(7, min(180, int(horizon_days or 30)))
        scenario = self._resolve_scenario(
            scenario_id_or_custom=scenario_id_or_custom,
            custom_title=custom_title,
            custom_description=custom_description,
            shock_parameters=shock_parameters,
        )

        # 1. 运行蒙特卡洛多路径随机冲击模拟
        mc_metrics = self._simulate_monte_carlo_paths(
            scenario=scenario,
            horizon_days=days,
            num_paths=num_paths,
            auto_forge_defensive_balls=auto_forge_defensive_balls,
        )

        # 2. 若启用 auto_forge_defensive_balls，当场铸造并挂载 1 颗 REDLINE 球 + 1 颗 SKILL 球（含 python -I 实弹校验）
        forged_balls: list[dict[str, Any]] = []
        if auto_forge_defensive_balls:
            forged_balls = self._forge_and_mount_defensive_balls(
                scenario=scenario,
                mc_metrics=mc_metrics,
            )

        # 3. 结合大模型（Live 模式）或高拟真确定性引擎推演各阶段跨部门应对时间线
        llm_calls = 0
        estimated_tokens = 0
        llm_stage_overrides: Optional[list[dict[str, Any]]] = None
        executive_commentary = (
            f"针对《{scenario['title']}》完成 {days} 天 × {num_paths} 条蒙特卡洛路径压力测试："
            f"P10 极端尾部净现金流冲击为 ¥{mc_metrics['p10_net_cashflow_impact']:,.2f}，"
            f"P50 中位净现金流影响为 ¥{mc_metrics['p50_net_cashflow_impact']:,.2f}，"
            f"红线触发率 {mc_metrics['redline_trigger_rate']*100:.1f}%。"
            f"模型生存率评分为 {mc_metrics['survival_score']} / 100；候选防御尚未执行，缓释效果未测量。"
        )

        if self._is_llm_live():
            sys_prompt = (
                "你是 Arachne-OS 的首席风险官与蒙特卡洛经营沙盘推演引擎。\n"
                "请针对输入的黑天鹅剧本与蒙特卡洛统计分布，推演 4 个阶段的跨部门联防应对策略及总结评语。\n"
                '输出严格 JSON: {"executive_commentary": "...", "timeline_stages": [{"stage_title": "...", "defensive_action": "..."}]}'
            )
            usr_prompt = json.dumps(
                {
                    "scenario": scenario["title"],
                    "description": scenario["description"],
                    "horizon_days": days,
                    "monte_carlo_summary": {
                        "p10_net_cashflow_impact": mc_metrics["p10_net_cashflow_impact"],
                        "p50_net_cashflow_impact": mc_metrics["p50_net_cashflow_impact"],
                        "p90_net_cashflow_impact": mc_metrics["p90_net_cashflow_impact"],
                        "max_drawdown": mc_metrics["max_drawdown"],
                        "redline_trigger_rate": mc_metrics["redline_trigger_rate"],
                        "survival_score": mc_metrics["survival_score"],
                    },
                },
                ensure_ascii=False,
            )
            llm_calls += 1
            estimated_tokens += max(420, (len(sys_prompt) + len(usr_prompt)) // 2)
            parsed = await self._call_llm_json(sys_prompt, usr_prompt)
            if parsed:
                if parsed.get("executive_commentary"):
                    executive_commentary = str(parsed["executive_commentary"])
                if isinstance(parsed.get("timeline_stages"), list):
                    llm_stage_overrides = parsed["timeline_stages"]

        timeline_stages = self._build_timeline_stages(
            scenario=scenario,
            horizon_days=days,
            mc_metrics=mc_metrics,
            forged_balls=forged_balls,
            llm_stage_overrides=llm_stage_overrides,
        )

        wargame_id = f"WG_{uuid.uuid4().hex[:8].upper()}"
        total_latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        token_telemetry = {
            "llm_calls": llm_calls,
            "actual_tokens": 0 if llm_calls == 0 else None,
            "estimated_tokens": estimated_tokens,
            "token_measurement": "NO_MODEL_CALLS" if llm_calls == 0 else "ESTIMATE_ONLY",
            "total_latency_ms": total_latency_ms,
            "mode": "LIVE_CLOUD_HYBRID" if self._is_llm_live() else "DETERMINISTIC_SWARM",
        }

        worm_rec = self._state.vault.append_event(
            event_kind="WARGAME_SIMULATION_COMPLETED",
            subtree_root_id="root",
            actor_slot_id="SLOT_BOSS",
            payload={
                "wargame_id": wargame_id,
                "scenario_id": scenario["scenario_id"],
                "scenario_title": scenario["title"],
                "horizon_days": days,
                "monte_carlo_paths": num_paths,
                "survival_score": mc_metrics["survival_score"],
                "p10_net_cashflow_impact": mc_metrics["p10_net_cashflow_impact"],
                "p50_net_cashflow_impact": mc_metrics["p50_net_cashflow_impact"],
                "p90_net_cashflow_impact": mc_metrics["p90_net_cashflow_impact"],
                "forged_ball_ids": [b["ball_id"] for b in forged_balls],
            },
        )

        report = {
            "scope": getattr(self._state, "simulation_scope", {}),
            "run_id": getattr(self._state, "simulation_scope", {}).get("run_id"),
            "wargame_id": wargame_id,
            "simulation_id": wargame_id,
            "scenario_id": scenario["scenario_id"],
            "scenario_title": scenario["title"],
            "scenario_description": scenario["description"],
            "evaluation_kind": "MODEL_BASELINE_ONLY",
            "defense_effect_status": "NOT_MEASURED",
            "exposed_vulnerability": scenario.get("exposed_vulnerability", ""),
            "horizon_days": days,
            "monte_carlo_paths": num_paths,
            "auto_forge_defensive_balls": auto_forge_defensive_balls,
            "timeline_stages": timeline_stages,
            "monte_carlo_metrics": mc_metrics,
            "forged_defensive_balls": forged_balls,
            "defensive_redline_ball": (
                next((b for b in forged_balls if b["ball_type"] == "REDLINE"), None)
            ),
            "defensive_skill_ball": (
                next((b for b in forged_balls if b["ball_type"] == "SKILL"), None)
            ),
            "executive_commentary": executive_commentary,
            "token_telemetry": token_telemetry,
            "worm_event": worm_rec.model_dump(),
            "created_at": utc_now_iso(),
        }
        self._history.insert(0, report)
        if getattr(self._state, "simulation_scope", None):
            from core.simulation_workspace import persist_simulation_runtime
            await persist_simulation_runtime(self._state)
        return report

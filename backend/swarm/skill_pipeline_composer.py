from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Optional
import uuid

from core.schemas import CapabilityBall, utc_now_iso
from core.topology_resolver import (
    resolve_active_authority_ball,
    resolve_frontline_user_and_slot,
    resolve_leader_user_and_slot,
    resolve_slot_by_role_keywords,
)
from swarm.evolution_arena import run_skill_in_isolated_subprocess, sandbox_ast_guard


class DualSyncAsyncDict(dict):
    """
    兼容同步直接调用与 `await` 异步调用的字典包装器：
    - 同步调用时本身即为标准 `dict`（支持索引、序列化、isinstance(x, dict)）；
    - 异步 `await` 调用时通过 `__await__` 返回自身字典副本。
    """

    def __await__(self):
        async def _coro() -> dict[str, Any]:
            return dict(self)

        return _coro().__await__()


PIPELINE_PRESETS: list[dict[str, Any]] = [
    {
        "preset_id": "pipe_end_to_end_order_profit",
        "pipeline_title": "【报价折扣算子 -> 阶梯运费算子 -> 税费与净毛利联立核算】全链路利润复合技能链",
        "title": "【报价折扣算子 -> 阶梯运费算子 -> 税费与净毛利联立核算】全链路利润复合技能链",
        "domain_mode": "ORDER_PROFIT",
        "target_slot_id": None,
        "source_skill_ball_ids": [
            "BALL_DATA_BULK_DISCOUNT_MATRIX",
            "BALL_DATA_SHIPPING_RULE_DOC",
            "BALL_SKILL_ORDER_CHECKLIST",
        ],
        "pipeline_instruction": (
            "Stage 1 根据订购数量与单价执行 B2B 阶梯折扣算子核算折后营收；"
            "Stage 2 根据总重量与折后金额执行首重3kg内10元、续重每kg加4元、满500元免邮的阶梯运费算子；"
            "Stage 3 联立出厂拿货成本、增值税附加税费与运费核算最终净毛利额及毛利率红线合规性。"
        ),
        "stages_preview": [
            "Stage 1: B2B 批量阶梯报价与折扣核算算子",
            "Stage 2: 首重/续重/满额免邮阶梯运费核算算子",
            "Stage 3: 综合税负、出厂成本与净毛利红线联立求解器",
        ],
        "default_test_payload": {
            "sku": "SKU-STD-01",
            "quantity": 50,
            "unit_price": 1280.0,
            "cost_unit_price": 760.0,
            "weight_kg": 18.5,
        },
    },
    {
        "preset_id": "pipe_supply_chain_replenish",
        "pipeline_title": "【安全库存水位核算 -> 紧急补货批量折扣 -> 跨境/干线物流总成本】供应链补货复合技能链",
        "title": "【安全库存水位核算 -> 紧急补货批量折扣 -> 跨境/干线物流总成本】供应链补货复合技能链",
        "domain_mode": "SUPPLY_REPLENISH",
        "target_slot_id": None,
        "source_skill_ball_ids": [
            "BALL_DATA_WMS_SAFETY_STOCK",
            "BALL_SKILL_WMS_WAVE_LOCK",
            "BALL_SKILL_QA_AQL_INSPECT",
        ],
        "pipeline_instruction": (
            "Stage 1 根据日均销量与备货周期天数计算安全库存水位 (日均*周期*1.5) 及紧急补货缺口量；"
            "Stage 2 根据补货量匹配认证代工厂阶梯集采折扣与加急排产保供费；"
            "Stage 3 联立核算干线/跨境物流运费、8.5%保税清关与质检杂费，输出到岸总成本与单件到岸成本。"
        ),
        "stages_preview": [
            "Stage 1: 安全库存水位与缺口补货量精算算子",
            "Stage 2: 供应商集采阶梯折扣与加急排产费算子",
            "Stage 3: 干线/跨境物流与到岸总成本联立求解器",
        ],
        "default_test_payload": {
            "daily_sales": 18.0,
            "lead_time_days": 7,
            "current_stock": 60,
            "supplier_unit_price": 500.0,
            "unit_weight_kg": 6.5,
        },
    },
    {
        "preset_id": "pipe_contract_rebate_settlement",
        "pipeline_title": "【季度阶梯返利精算 -> 逾期违约金抵扣 -> 最终应结返利净额】经销商返利清算复合技能链",
        "title": "【季度阶梯返利精算 -> 逾期违约金抵扣 -> 最终应结返利净额】经销商返利清算复合技能链",
        "domain_mode": "CONTRACT_REBATE",
        "target_slot_id": None,
        "source_skill_ball_ids": [
            "BALL_DATA_CATALOG_2026",
            "BALL_DATA_BULK_DISCOUNT_MATRIX",
            "AUTH_GATE_GUARD",
        ],
        "pipeline_instruction": (
            "Stage 1 根据经销商季度累计提货量或 GMV 核算阶梯返利档位 (3% / 6% / 9.5%) 与应计返利总额；"
            "Stage 2 根据实际回款天数与合同账期计算逾期万分之五日息违约金 (20%封顶保护)；"
            "Stage 3 联立执行返利与逾期违约金交叉抵扣，输出最终应结返利净额及实际应收结算款。"
        ),
        "stages_preview": [
            "Stage 1: 经销商季度阶梯返利档位与总额精算算子",
            "Stage 2: 账期逾期万分之五日息违约金精算算子（含20%封顶）",
            "Stage 3: 返利违约金交叉抵扣与最终应结净额求解器",
        ],
        "default_test_payload": {
            "quarterly_gmv": 600000.0,
            "quantity": 60,
            "unit_price": 10000.0,
            "overdue_days": 20,
        },
    },
]


def get_pipeline_presets(state: Any = None) -> list[dict[str, Any]]:
    presets = []
    containers = getattr(state, "containers", None) if state is not None else None
    particles = getattr(state, "particles", None) if state is not None else None
    fl_slot = resolve_frontline_user_and_slot(containers)[1] if containers else "SLOT_FRONTLINE"
    ld_slot = resolve_leader_user_and_slot(containers)[1] if containers else "SLOT_LEADER"
    wms_slot = resolve_slot_by_role_keywords(containers, ["仓", "物流", "供应链", "采购"]) if containers else fl_slot
    auth_ball = resolve_active_authority_ball(particles) if particles else "AUTH_GATE_GUARD"

    for item in PIPELINE_PRESETS:
        copy = {**item, "source_skill_ball_ids": list(item["source_skill_ball_ids"]),
                "implementation": "PRESET_TEMPLATE", "validation_status": "UNVALIDATED"}
        mode = copy.get("domain_mode")
        if copy.get("target_slot_id") is None:
            if mode == "SUPPLY_REPLENISH":
                copy["target_slot_id"] = wms_slot
            elif mode == "CONTRACT_REBATE":
                copy["target_slot_id"] = ld_slot
            else:
                copy["target_slot_id"] = fl_slot
        copy["source_skill_ball_ids"] = [
            auth_ball if bid == "AUTH_GATE_GUARD" else bid
            for bid in copy["source_skill_ball_ids"]
        ]
        presets.append(copy)
    return presets


class SkillPipelineComposer:
    """
    预设模板候选技能与显式沙箱预览。
    源球仅为引用；生产启用必须通过 Arena 的独立语义审查。
    """

    def __init__(self, state: Any = None, runtime: Any = None) -> None:
        self._state = state or runtime
        self._composed_pipelines: list[dict[str, Any]] = []
        self._execution_history: list[dict[str, Any]] = []
        if self._state is not None:
            self.bind_state(self._state)

    def bind_state(self, state: Any) -> None:
        self._state = state
        if hasattr(state, "particles") and not hasattr(state, "ball_registry"):
            setattr(state, "ball_registry", state.particles._balls)

    @property
    def sandbox_dir(self) -> Path:
        if self._state is not None and hasattr(self._state, "settings"):
            sb = Path(self._state.settings.sandbox_workspace_dir)
        else:
            sb = Path("/tmp/arachne_sandbox_workspace")
        sb.mkdir(parents=True, exist_ok=True)
        return sb

    def get_pipeline_presets(self) -> list[dict[str, Any]]:
        return get_pipeline_presets(self._state)

    def _detect_domain_mode(
        self,
        pipeline_title: str,
        pipeline_instruction: str,
        source_ids: list[str],
        preset_id: Optional[str] = None,
    ) -> str:
        if preset_id:
            for p in PIPELINE_PRESETS:
                if p["preset_id"] == preset_id:
                    return str(p["domain_mode"])
        raise ValueError("An explicit supported preset is required; arbitrary source composition is unavailable")

    def _collect_source_balls_info(
        self, source_skill_ball_ids: list[str]
    ) -> list[dict[str, Any]]:
        info_list: list[dict[str, Any]] = []
        particles = getattr(self._state, "particles", None) if self._state else None

        for bid in source_skill_ball_ids:
            ball: Optional[CapabilityBall] = (
                particles.get_ball(bid) if particles is not None else None
            )
            if ball is None or ball.status != "ACTIVE":
                raise ValueError(f"Source ball must exist and be ACTIVE: {bid}")
            if ball.ball_type not in ("DATA", "SKILL", "AUTHORITY"):
                raise ValueError(f"Unsupported source ball type: {bid}")
            info_list.append({
                "ball_id": ball.ball_id,
                "title": ball.title,
                "ball_type": ball.ball_type,
                "status": ball.status,
                "domain_tags": list(ball.domain_tags),
                "executable_code_path": ball.executable_code_path,
                "content_hash": hashlib.sha256(ball.model_dump_json().encode()).hexdigest(),
                "used_as": "REFERENCE_ONLY",
                "code_executed": False,
            })
        return info_list

    def _generate_composite_pipeline_code(
        self,
        domain_mode: str,
        pipeline_title: str,
        source_balls: list[dict[str, Any]],
    ) -> str:
        s1_id = source_balls[0]["ball_id"] if len(source_balls) > 0 else "STAGE_1_BALL"
        s2_id = source_balls[1]["ball_id"] if len(source_balls) > 1 else "STAGE_2_BALL"
        s3_id = source_balls[2]["ball_id"] if len(source_balls) > 2 else "STAGE_3_BALL"

        # 严格符合 sandbox_ast_guard：仅导入 math，严禁任何双下划线属性与禁止内置函数
        return f'''import math

PIPELINE_DOMAIN_MODE = {json.dumps(domain_mode)}
PIPELINE_TITLE = {json.dumps(pipeline_title, ensure_ascii=False)}
STAGE_SOURCE_BALLS = [None, None, None]
SOURCE_REFERENCE_BALLS = [{json.dumps(s1_id)}, {json.dumps(s2_id)}, {json.dumps(s3_id)}]


def _number(payload, key, default, alias=None):
    if key in payload:
        raw = payload[key]
    elif alias is not None and alias in payload:
        raw = payload[alias]
    else:
        raw = default
    if isinstance(raw, bool) or raw is None:
        raise ValueError("Invalid numeric input: " + key)
    value = float(raw)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Numeric input must be finite and nonnegative: " + key)
    return value


def _run_order_profit_pipeline(payload: dict) -> dict:
    quantity = _number(payload, "quantity", 50.0, "qty")
    unit_price = _number(payload, "unit_price", 1280.0, "price")
    cost_unit_price = _number(payload, "cost_unit_price", round(unit_price * 0.60, 2))
    weight_kg = _number(payload, "weight_kg", round(quantity * 0.35, 2))

    # Stage 1: 报价与阶梯批量折扣算子
    explicit_disc = payload.get("discount_rate")
    if "discount_rate" in payload:
        raw_d = _number(payload, "discount_rate", 1.0)
        if raw_d > 10.0:
            raise ValueError("discount_rate exceeds 10")
        discount_rate = round(raw_d / 10.0, 4) if raw_d > 1.0 else raw_d
    else:
        if quantity >= 100:
            discount_rate = 0.85
        elif quantity >= 50:
            discount_rate = 0.90
        elif quantity >= 10:
            discount_rate = 0.95
        else:
            discount_rate = 1.0

    gross_catalog_amount = round(unit_price * quantity, 2)
    discounted_amount = round(gross_catalog_amount * discount_rate, 2)
    discount_saved = round(gross_catalog_amount - discounted_amount, 2)
    stage_1 = {{
        "stage_index": 1,
        "stage_id": "stage_1_quote_discount",
        "stage_name": "B2B 阶梯报价折扣核算算子",
        "source_ball_id": STAGE_SOURCE_BALLS[0],
        "inputs": {{"quantity": quantity, "unit_price": unit_price}},
        "outputs": {{
            "gross_catalog_amount": gross_catalog_amount,
            "discount_rate": discount_rate,
            "discounted_amount": discounted_amount,
            "discount_saved": discount_saved,
        }},
    }}

    # Stage 2: 阶梯运费算子（首重3kg内10元，超3kg每kg向上取整加4元，折后满500元免邮）
    if discounted_amount >= 500.0 or quantity == 0:
        shipping_fee = 0.0
        extra_kg = 0
        free_shipping = True
    else:
        extra_kg = max(0, int(math.ceil(weight_kg - 3.0))) if weight_kg > 3.0 else 0
        shipping_fee = round(10.0 + 4.0 * extra_kg, 2)
        free_shipping = False

    stage_2 = {{
        "stage_index": 2,
        "stage_id": "stage_2_tiered_shipping",
        "stage_name": "首重续重满额免邮阶梯运费算子",
        "source_ball_id": STAGE_SOURCE_BALLS[1],
        "inputs": {{"weight_kg": weight_kg, "discounted_amount": discounted_amount}},
        "outputs": {{
            "shipping_fee": shipping_fee,
            "billable_extra_kg": extra_kg,
            "free_shipping_applied": free_shipping,
        }},
    }}

    # Stage 3: 税费、出厂拿货成本与净毛利联立求解
    tax_rate = _number(payload, "tax_rate", 0.065)
    if tax_rate > 1.0:
        raise ValueError("tax_rate exceeds 1")
    tax_amount = round(discounted_amount * tax_rate, 2)
    total_cogs = round(cost_unit_price * quantity, 2)
    net_profit = round(discounted_amount - total_cogs - shipping_fee - tax_amount, 2)
    net_margin_rate = (
        round(net_profit / discounted_amount, 4) if discounted_amount > 0 else 0.0
    )
    margin_redline_passed = bool(net_margin_rate >= 0.12 and net_profit > 0)

    stage_3 = {{
        "stage_index": 3,
        "stage_id": "stage_3_tax_and_net_profit",
        "stage_name": "税费成本与净毛利红线联立求解器",
        "source_ball_id": STAGE_SOURCE_BALLS[2],
        "inputs": {{
            "discounted_amount": discounted_amount,
            "shipping_fee": shipping_fee,
            "cost_unit_price": cost_unit_price,
            "tax_rate": tax_rate,
        }},
        "outputs": {{
            "total_cogs": total_cogs,
            "tax_amount": tax_amount,
            "net_profit": net_profit,
            "net_margin_rate": net_margin_rate,
            "margin_redline_passed": margin_redline_passed,
        }},
    }}

    final_output = {{
        "result": net_profit,
        "discounted_amount": discounted_amount,
        "discount_rate": discount_rate,
        "shipping_fee": shipping_fee,
        "tax_amount": tax_amount,
        "total_cogs": total_cogs,
        "net_profit": net_profit,
        "net_margin_rate": net_margin_rate,
        "margin_redline_passed": margin_redline_passed,
    }}
    return {{
        "status": "ok",
        "pipeline_mode": "ORDER_PROFIT",
        "result": net_profit,
        "stage_breakdown": [stage_1, stage_2, stage_3],
        "final_output": final_output,
        "discounted_amount": discounted_amount,
        "shipping_fee": shipping_fee,
        "net_profit": net_profit,
        "net_margin_rate": net_margin_rate,
    }}


def _run_supply_replenish_pipeline(payload: dict) -> dict:
    daily_sales = _number(payload, "daily_sales", 18.0)
    lead_time_days = _number(payload, "lead_time_days", 7.0)
    current_stock = _number(payload, "current_stock", 60.0)
    supplier_unit_price = _number(payload, "supplier_unit_price", 500.0)
    unit_weight_kg = _number(payload, "unit_weight_kg", 6.5)

    # Stage 1: 安全库存水位与缺口核算
    safety_stock = round(daily_sales * lead_time_days * 1.5, 2)
    target_stock = round(safety_stock * 1.25, 2)
    raw_gap = max(0.0, target_stock - current_stock)
    replenish_qty = int(max(20, math.ceil(raw_gap))) if raw_gap > 0 else 0
    urgent_flag = bool(current_stock < safety_stock)

    stage_1 = {{
        "stage_index": 1,
        "stage_id": "stage_1_safety_stock_gap",
        "stage_name": "安全库存水位与缺口补货量精算算子",
        "source_ball_id": STAGE_SOURCE_BALLS[0],
        "inputs": {{
            "daily_sales": daily_sales,
            "lead_time_days": lead_time_days,
            "current_stock": current_stock,
        }},
        "outputs": {{
            "safety_stock": safety_stock,
            "target_stock": target_stock,
            "replenish_qty": replenish_qty,
            "urgent_replenish_triggered": urgent_flag,
        }},
    }}

    # Stage 2: 紧急补货批量折扣与排产费核算
    if replenish_qty >= 100:
        supplier_discount = 0.88
    elif replenish_qty >= 50:
        supplier_discount = 0.92
    else:
        supplier_discount = 0.96

    discounted_goods_cost = round(
        replenish_qty * supplier_unit_price * supplier_discount, 2
    )
    expedite_fee = round(discounted_goods_cost * 0.02, 2) if urgent_flag else 0.0
    procurement_subtotal = round(discounted_goods_cost + expedite_fee, 2)

    stage_2 = {{
        "stage_index": 2,
        "stage_id": "stage_2_supplier_bulk_pricing",
        "stage_name": "供应商批量阶梯集采与加急排产费算子",
        "source_ball_id": STAGE_SOURCE_BALLS[1],
        "inputs": {{
            "replenish_qty": replenish_qty,
            "supplier_unit_price": supplier_unit_price,
        }},
        "outputs": {{
            "supplier_discount": supplier_discount,
            "discounted_goods_cost": discounted_goods_cost,
            "expedite_fee": expedite_fee,
            "procurement_subtotal": procurement_subtotal,
        }},
    }}

    # Stage 3: 干线/跨境物流与到岸总成本联立核算
    total_weight_kg = round(replenish_qty * unit_weight_kg, 2)
    trunk_freight = round(10.0 + max(0.0, total_weight_kg - 3.0) * 1.8, 2)
    customs_and_qa_fee = round(procurement_subtotal * 0.085, 2)
    total_landed_cost = round(
        procurement_subtotal + trunk_freight + customs_and_qa_fee, 2
    )
    landed_unit_cost = round(total_landed_cost / max(1, replenish_qty), 2)
    requires_leader_approval = bool(total_landed_cost > 100000.0)

    stage_3 = {{
        "stage_index": 3,
        "stage_id": "stage_3_trunk_logistics_landed_cost",
        "stage_name": "跨境干线物流与到岸总成本求解器",
        "source_ball_id": STAGE_SOURCE_BALLS[2],
        "inputs": {{
            "procurement_subtotal": procurement_subtotal,
            "total_weight_kg": total_weight_kg,
        }},
        "outputs": {{
            "trunk_freight": trunk_freight,
            "customs_and_qa_fee": customs_and_qa_fee,
            "total_landed_cost": total_landed_cost,
            "landed_unit_cost": landed_unit_cost,
            "requires_leader_approval": requires_leader_approval,
        }},
    }}

    final_output = {{
        "result": total_landed_cost,
        "safety_stock": safety_stock,
        "replenish_qty": replenish_qty,
        "procurement_subtotal": procurement_subtotal,
        "trunk_freight": trunk_freight,
        "customs_and_qa_fee": customs_and_qa_fee,
        "total_landed_cost": total_landed_cost,
        "landed_unit_cost": landed_unit_cost,
        "requires_leader_approval": requires_leader_approval,
    }}
    return {{
        "status": "ok",
        "pipeline_mode": "SUPPLY_REPLENISH",
        "result": total_landed_cost,
        "stage_breakdown": [stage_1, stage_2, stage_3],
        "final_output": final_output,
        "safety_stock": safety_stock,
        "replenish_qty": replenish_qty,
        "total_landed_cost": total_landed_cost,
    }}


def _run_contract_rebate_pipeline(payload: dict) -> dict:
    quantity = _number(payload, "quantity", 60.0)
    unit_price = _number(payload, "unit_price", 10000.0)
    gross_gmv = _number(payload, "quarterly_gmv", round(quantity * unit_price, 2))
    overdue_days = int(_number(payload, "overdue_days", 0))

    # Stage 1: 季度阶梯返利精算
    if quantity >= 100 or gross_gmv >= 1000000.0:
        rebate_rate = 0.095
        rebate_tier = "GOLD_9.5%"
    elif quantity >= 50 or gross_gmv >= 500000.0:
        rebate_rate = 0.06
        rebate_tier = "SILVER_6.0%"
    elif quantity >= 20 or gross_gmv >= 200000.0:
        rebate_rate = 0.03
        rebate_tier = "BRONZE_3.0%"
    else:
        rebate_rate = 0.0
        rebate_tier = "STANDARD_0%"

    gross_rebate_amount = round(gross_gmv * rebate_rate, 2)
    stage_1 = {{
        "stage_index": 1,
        "stage_id": "stage_1_quarterly_tiered_rebate",
        "stage_name": "经销商季度阶梯返利精算算子",
        "source_ball_id": STAGE_SOURCE_BALLS[0],
        "inputs": {{"gross_gmv": gross_gmv, "quantity": quantity}},
        "outputs": {{
            "rebate_tier": rebate_tier,
            "rebate_rate": rebate_rate,
            "gross_rebate_amount": gross_rebate_amount,
        }},
    }}

    # Stage 2: 逾期违约金日息核算（万分之五/日，20%封顶）
    daily_rate = 0.0005
    raw_penalty = round(gross_gmv * daily_rate * max(0, overdue_days), 2)
    penalty_cap = round(gross_gmv * 0.20, 2)
    overdue_penalty_amount = min(raw_penalty, penalty_cap)
    cap_triggered = bool(raw_penalty > penalty_cap)

    stage_2 = {{
        "stage_index": 2,
        "stage_id": "stage_2_overdue_penalty_offset",
        "stage_name": "逾期日息违约金与20%封顶精算算子",
        "source_ball_id": STAGE_SOURCE_BALLS[1],
        "inputs": {{"gross_gmv": gross_gmv, "overdue_days": overdue_days}},
        "outputs": {{
            "daily_penalty_rate": daily_rate,
            "raw_penalty": raw_penalty,
            "overdue_penalty_amount": overdue_penalty_amount,
            "penalty_cap_triggered": cap_triggered,
        }},
    }}

    # Stage 3: 返利与违约金抵扣决算
    net_rebate_payable = round(gross_rebate_amount - overdue_penalty_amount, 2)
    final_settlement_amount = round(
        gross_gmv - gross_rebate_amount + overdue_penalty_amount, 2
    )
    clawback_required = bool(net_rebate_payable < 0)

    stage_3 = {{
        "stage_index": 3,
        "stage_id": "stage_3_net_rebate_settlement",
        "stage_name": "返利违约金交叉抵扣与应结净额求解器",
        "source_ball_id": STAGE_SOURCE_BALLS[2],
        "inputs": {{
            "gross_rebate_amount": gross_rebate_amount,
            "overdue_penalty_amount": overdue_penalty_amount,
        }},
        "outputs": {{
            "net_rebate_payable": net_rebate_payable,
            "final_settlement_amount": final_settlement_amount,
            "clawback_required": clawback_required,
        }},
    }}

    final_output = {{
        "result": net_rebate_payable,
        "gross_gmv": gross_gmv,
        "rebate_rate": rebate_rate,
        "gross_rebate_amount": gross_rebate_amount,
        "overdue_penalty_amount": overdue_penalty_amount,
        "net_rebate_payable": net_rebate_payable,
        "final_settlement_amount": final_settlement_amount,
        "clawback_required": clawback_required,
    }}
    return {{
        "status": "ok",
        "pipeline_mode": "CONTRACT_REBATE",
        "result": net_rebate_payable,
        "stage_breakdown": [stage_1, stage_2, stage_3],
        "final_output": final_output,
        "gross_rebate_amount": gross_rebate_amount,
        "overdue_penalty_amount": overdue_penalty_amount,
        "net_rebate_payable": net_rebate_payable,
        "final_settlement_amount": final_settlement_amount,
    }}


def execute_skill(payload: dict) -> dict:
    if "pipeline_mode" in payload and payload["pipeline_mode"] != PIPELINE_DOMAIN_MODE:
        raise ValueError("Preset domain cannot be overridden")
    mode = PIPELINE_DOMAIN_MODE
    if mode == "SUPPLY_REPLENISH":
        return _run_supply_replenish_pipeline(payload)
    if mode == "CONTRACT_REBATE":
        return _run_contract_rebate_pipeline(payload)
    return _run_order_profit_pipeline(payload)
'''

    def _resolve_target_slot_id(
        self, target_slot_id: Optional[str], domain_mode: str = "ORDER_PROFIT"
    ) -> str:
        if self._state is None or not hasattr(self._state, "containers"):
            return target_slot_id or "SLOT_FRONTLINE"
        containers = self._state.containers
        if target_slot_id:
            try:
                return containers.get_slot(target_slot_id).slot_id
            except KeyError as exc:
                raise ValueError(f"Unknown target slot: {target_slot_id}") from exc
        if domain_mode == "SUPPLY_REPLENISH":
            return resolve_slot_by_role_keywords(containers, ["仓", "物流", "供应链", "采购"])
        if domain_mode == "CONTRACT_REBATE":
            return resolve_leader_user_and_slot(containers)[1]
        _, fl_slot = resolve_frontline_user_and_slot(containers)
        return fl_slot

    def compose_and_verify_pipeline(
        self,
        pipeline_title: str = "",
        source_skill_ball_ids: Optional[list[str]] = None,
        pipeline_instruction: str = "",
        target_slot_id: Optional[str] = None,
        test_payload: Optional[dict[str, Any]] = None,
        preset_id: Optional[str] = None,
        proposer_id: Optional[str] = None,
    ) -> DualSyncAsyncDict:
        presets = self.get_pipeline_presets()
        matched_preset = None
        if preset_id:
            matched_preset = next(
                (p for p in presets if p["preset_id"] == preset_id), None
            )
        elif pipeline_title:
            matched_preset = next(
                (
                    p
                    for p in presets
                    if p["preset_id"] == pipeline_title
                    or p["pipeline_title"] == pipeline_title
                ),
                None,
            )

        if matched_preset is None:
            raise ValueError("An explicit supported preset is required; arbitrary source composition is unavailable")

        if matched_preset is not None:
            pipeline_title = pipeline_title or matched_preset["pipeline_title"]
            if source_skill_ball_ids is None:
                source_skill_ball_ids = list(matched_preset["source_skill_ball_ids"])
            pipeline_instruction = (
                pipeline_instruction or matched_preset["pipeline_instruction"]
            )
            target_slot_id = target_slot_id or matched_preset.get("target_slot_id")
            if test_payload is None:
                test_payload = dict(matched_preset["default_test_payload"])

        clean_title = (
            pipeline_title or "多球联立复合求解技能链 (Master Pipeline)"
        ).strip()
        resolved_source_ids = list(source_skill_ball_ids if source_skill_ball_ids is not None else [])
        if len(resolved_source_ids) != 3 or len(set(resolved_source_ids)) != 3:
            raise ValueError("Exactly three distinct ACTIVE source references are required")
        domain_mode = self._detect_domain_mode(
            clean_title, pipeline_instruction, resolved_source_ids, preset_id=matched_preset["preset_id"]
        )

        default_payload_by_mode = {
            "ORDER_PROFIT": PIPELINE_PRESETS[0]["default_test_payload"],
            "SUPPLY_REPLENISH": PIPELINE_PRESETS[1]["default_test_payload"],
            "CONTRACT_REBATE": PIPELINE_PRESETS[2]["default_test_payload"],
        }
        effective_test_payload = dict(
            test_payload if test_payload is not None else default_payload_by_mode.get(domain_mode, {})
        )

        source_balls_info = self._collect_source_balls_info(resolved_source_ids)
        resolved_slot_id = self._resolve_target_slot_id(target_slot_id, domain_mode=domain_mode)
        arena = getattr(self._state, "arena", None)
        if arena is not None:
            if not proposer_id:
                raise ValueError("A management creator identity is required")
            creator = self._state.containers.get_profile(proposer_id)
            if creator.role_view not in ("manager", "boss"):
                raise ValueError("A management creator identity is required")
        self._validate_payload(effective_test_payload)
        bridge_summary = "Preset template arithmetic; source balls are references and their code is not composed or executed."
        token_telemetry = {"llm_calls": 0, "estimated_tokens": 0, "total_latency_ms": 0, "mode": "PRESET_TEMPLATE"}

        pipeline_id = f"PIPE_{uuid.uuid4().hex[:8].upper()}"
        short_id = pipeline_id.replace("PIPE_", "")
        proposal_id = f"PROP_{short_id}"
        master_ball_id = f"BALL_SKILL_PIPE_{short_id}"

        code = self._generate_composite_pipeline_code(
            domain_mode=domain_mode,
            pipeline_title=clean_title,
            source_balls=source_balls_info,
        )
        sandbox_ast_guard(code)

        script_filename = f"skill_{proposal_id.lower()}.py"
        script_path = self.sandbox_dir / script_filename
        script_path.write_text(code, encoding="utf-8")

        run_results = run_skill_in_isolated_subprocess(
            script_path=script_path,
            sandbox_dir=self.sandbox_dir,
            input_payloads=[effective_test_payload],
            timeout_seconds=3.0,
        )
        passed = bool(run_results and run_results[0].get("ok") is True)
        if not passed:
            raise RuntimeError(
                f"Composite pipeline skill failed cleanroom verification: {run_results}"
            )

        sample_output: dict[str, Any] = run_results[0].get("output") or {}
        sandbox_verification = {
            "passed": False,
            "process_passed": True,
            "semantic_status": "UNVALIDATED",
            "ast_passed": True,
            "isolation_mode": "python -I",
            "script_filename": script_filename,
            "script_path": str(script_path),
            "test_payload": effective_test_payload,
            "sample_output": sample_output,
        }

        merged_tags = ["复合技能链", "多球联立", "报价", "物流", "财税"]
        for sb in source_balls_info:
            for t in sb.get("domain_tags", []):
                if t not in merged_tags:
                    merged_tags.append(t)

        master_ball = CapabilityBall(
            ball_id=master_ball_id,
            ball_type="SKILL",
            title=f"【复合管道·SKILL】{clean_title}",
            domain_tags=merged_tags[:8],
            sensitivity_level=2,
            owner_slot_ids=[resolved_slot_id, "SLOT_BOSS"]
            if resolved_slot_id != "SLOT_BOSS"
            else ["SLOT_BOSS"],
            content=(
                f"Unvalidated {matched_preset['preset_id']} preset template. "
                f"Source references: {', '.join(resolved_source_ids)}. {bridge_summary}"
            ),
            executable_code_path=script_filename,
            status="CANDIDATE",
        )

        worm_event = None
        if self._state is not None:
            particles = getattr(self._state, "particles", None)
            ball_reg = getattr(self._state, "ball_registry", None)
            vault = getattr(self._state, "vault", None)

            if particles is not None:
                particles.register_ball(master_ball, record_to_vault=True)
            if isinstance(ball_reg, dict):
                ball_reg[master_ball.ball_id] = master_ball
            if arena is not None:
                arena.register_candidate(
                    proposal_id=proposal_id, ball_id=master_ball_id,
                    source_hash=hashlib.sha256(code.encode()).hexdigest(),
                    source_code=code, proposer_id=proposer_id,
                    target_slot_id=resolved_slot_id,
                )

            if vault is not None:
                worm_event = vault.append_event(
                    event_kind="SKILL_PIPELINE_COMPOSED",
                    subtree_root_id="root",
                    actor_slot_id=creator.slot_id if arena is not None else resolved_slot_id,
                    payload={
                        "pipeline_id": pipeline_id,
                        "proposer_id": proposer_id,
                        "pipeline_title": clean_title,
                        "master_ball_id": master_ball.ball_id,
                        "source_skill_ball_ids": resolved_source_ids,
                        "target_slot_id": resolved_slot_id,
                        "domain_mode": domain_mode,
                        "sandbox_process_passed": True,
                        "validation_status": "UNVALIDATED",
                        "implementation": "PRESET_TEMPLATE",
                    },
                )

        record = {
            "pipeline_id": pipeline_id,
            "proposal_id": proposal_id,
            "proposer_id": proposer_id,
            "source_hash": hashlib.sha256(code.encode()).hexdigest(),
            "preset_id": matched_preset["preset_id"],
            "candidate_status": "CANDIDATE",
            "validation_status": "UNVALIDATED",
            "promoted": False,
            "evidence_provenance": {
                "implementation": "PRESET_TEMPLATE",
                "source_code_executed": False,
                "independent_business_validation": False,
                "source_references": source_balls_info,
            },
            "pipeline_title": clean_title,
            "domain_mode": domain_mode,
            "master_ball_id": master_ball.ball_id,
            "master_ball": master_ball.model_dump(),
            "created_ball": master_ball.model_dump(),
            "source_skill_ball_ids": resolved_source_ids,
            "source_balls": source_balls_info,
            "pipeline_instruction": pipeline_instruction,
            "bridge_summary": bridge_summary,
            "mounted_to_slot_id": None,
            "target_slot_id": resolved_slot_id,
            "script_filename": script_filename,
            "generated_code": code,
            "stage_breakdown": sample_output.get("stage_breakdown", []),
            "final_output": sample_output.get("final_output", {}),
            "sandbox_verification": sandbox_verification,
            "worm_event": worm_event.model_dump() if worm_event else None,
            "token_telemetry": token_telemetry,
            "created_at": utc_now_iso(),
        }
        self._composed_pipelines.append(record)
        return DualSyncAsyncDict(record)

    def execute_pipeline(
        self,
        pipeline_id: Optional[str] = None,
        ball_id: Optional[str] = None,
        preset_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        sandbox_preview: bool = False,
        proposer_id: Optional[str] = None,
    ) -> DualSyncAsyncDict:
        if sandbox_preview is not True:
            raise ValueError("Explicit sandbox_preview=true is required; this endpoint does not execute business actions")
        target_record = None
        if pipeline_id:
            target_record = next(
                (
                    p
                    for p in self._composed_pipelines
                    if p["pipeline_id"] == pipeline_id
                    or p["master_ball_id"] == pipeline_id
                ),
                None,
            )
            if target_record is None and any(
                pr["preset_id"] == pipeline_id for pr in PIPELINE_PRESETS
            ):
                preset_id = pipeline_id

        if target_record is None and ball_id:
            target_record = next(
                (
                    p
                    for p in self._composed_pipelines
                    if p["master_ball_id"] == ball_id
                ),
                None,
            )

        if target_record is None and preset_id:
            target_record = dict(
                self.compose_and_verify_pipeline(
                    preset_id=preset_id, test_payload=payload, proposer_id=proposer_id
                )
            )

        script_path: Optional[Path] = None
        resolved_ball_id = ball_id or ""
        resolved_pipeline_id = pipeline_id or ""

        if target_record is not None:
            resolved_pipeline_id = target_record["pipeline_id"]
            resolved_ball_id = target_record["master_ball_id"]
            script_path = self.sandbox_dir / target_record["script_filename"]
        else:
            raise KeyError("Unknown composed pipeline; provide a known pipeline_id, ball_id or explicit preset_id")

        effective_payload = dict(
            payload if payload is not None else target_record["sandbox_verification"]["test_payload"]
        )
        self._validate_payload(effective_payload)
        if hashlib.sha256(script_path.read_bytes()).hexdigest() != target_record["source_hash"]:
            raise ValueError("Pipeline source changed since composition")
        run_res = run_skill_in_isolated_subprocess(
            script_path=script_path,
            sandbox_dir=self.sandbox_dir,
            input_payloads=[effective_payload],
            timeout_seconds=3.0,
        )
        ok = bool(run_res and run_res[0].get("ok") is True)
        out_dict: dict[str, Any] = (run_res[0].get("output") or {}) if run_res else {}

        exec_id = f"PEXEC_{uuid.uuid4().hex[:8].upper()}"
        exec_record = {
            "execution_id": exec_id,
            "pipeline_id": resolved_pipeline_id,
            "master_ball_id": resolved_ball_id,
            "ball_id": resolved_ball_id,
            "status": "SANDBOX_ONLY" if ok else "SANDBOX_FAILED",
            "validation_status": "UNVALIDATED",
            "execution_evidence": {
                "business_execution_completed": False,
                "process_passed": ok,
                "implementation": "PRESET_TEMPLATE",
            },
            "ok": ok,
            "input_payload": effective_payload,
            "stage_breakdown": out_dict.get("stage_breakdown", []),
            "final_output": out_dict.get("final_output", out_dict),
            "raw_output": out_dict,
            "executed_at": utc_now_iso(),
        }
        self._execution_history.append(exec_record)

        if self._state is not None and hasattr(self._state, "vault"):
            actor_slot = (self._state.containers.get_profile(proposer_id).slot_id
                          if proposer_id and hasattr(self._state, "containers")
                          else target_record["target_slot_id"])
            self._state.vault.append_event(
                event_kind="SKILL_PIPELINE_EXECUTED",
                subtree_root_id="root",
                actor_slot_id=actor_slot,
                payload={
                    "execution_id": exec_id,
                    "pipeline_id": resolved_pipeline_id,
                    "master_ball_id": resolved_ball_id,
                    "ok": ok,
                },
            )

        return DualSyncAsyncDict(exec_record)

    @staticmethod
    def _validate_payload(payload: dict[str, Any]) -> None:
        json.dumps(payload, allow_nan=False)
        numeric_fields = {
            "quantity", "qty", "unit_price", "price", "cost_unit_price", "weight_kg",
            "discount_rate", "tax_rate", "daily_sales", "lead_time_days", "current_stock",
            "supplier_unit_price", "unit_weight_kg", "quarterly_gmv", "overdue_days",
        }
        for key in numeric_fields.intersection(payload):
            raw = payload[key]
            if raw is None or isinstance(raw, bool):
                raise ValueError(f"Invalid numeric input: {key}")
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid numeric input: {key}") from exc
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Numeric input must be finite and nonnegative: {key}")
        if "tax_rate" in payload and float(payload["tax_rate"]) > 1:
            raise ValueError("tax_rate exceeds 1")
        if "discount_rate" in payload and float(payload["discount_rate"]) > 10:
            raise ValueError("discount_rate exceeds 10")

    def get_history(self) -> dict[str, Any]:
        arena = getattr(self._state, "arena", None)
        if arena is not None:
            reports = {r.proposal_id: r for r in arena.list_reports()}
            for record in self._composed_pipelines:
                review = reports.get(record.get("proposal_id"))
                if review is not None and review.promoted:
                    record.update(candidate_status="ACTIVE", validation_status=review.validation_status,
                                  promoted=True, mounted_to_slot_id=record["target_slot_id"])
                    current_ball = self._state.particles.get_ball(record["master_ball_id"])
                    if current_ball is not None:
                        record["master_ball"] = current_ball.model_dump()
                    record["evidence_provenance"]["publication_review"] = review.evidence_provenance.get("publication_review")
        return {
            "composed_count": len(self._composed_pipelines),
            "execution_count": len(self._execution_history),
            "pipelines": list(reversed(self._composed_pipelines)),
            "composed_pipelines": list(reversed(self._composed_pipelines)),
            "executions": list(reversed(self._execution_history)),
        }

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from openai import OpenAI

from core.auth_custody import ACCOUNT_DIRECTORY, AuthAndCustodyService
from core.schemas import CapabilityBall, UnitSlot
from core.topology_resolver import resolve_frontline_user_and_slot
from swarm.evolution_arena import run_skill_in_isolated_subprocess, sandbox_ast_guard

EnterpriseState = Any

INGESTION_SAMPLES: list[dict[str, Any]] = [
    {
        "sample_id": "sample_csv_steel_ledger",
        "doc_title": "《2026Q4 华东特钢产品阶梯报价、成本底线与实时安全库存台账 (CSV)》",
        "title": "《2026Q4 华东特钢产品阶梯报价、成本底线与实时安全库存台账 (CSV)》",
        "doc_format": "CSV",
        "target_department": "",
        "target_slot_id": None,
        "description": (
            "涵盖 6 大核心特钢 SKU 的规格、公开基准单价、钢厂拿货成本底价、"
            "当前实时库存吨数、安全库存水位、最低毛利红线及大客户阶梯折扣率。"
        ),
        "highlights": [
            "6 行高保真特钢 SKU 台账（304冷轧卷 / 316L无缝管 / 42CrMo合金棒 / H13模具钢等）",
            "自动计算数值列 min/max/mean/sum 与主键、底价、毛利红线敏感列画像",
            "自动编译独立沙箱查表精算 SKILL 球（支持按 SKU、吨数、折扣率自动核验毛利与库存）",
        ],
        "raw_content": (
            "sku,product_name,spec,base_unit_price,cost_floor_price,stock_tons,safety_stock_tons,min_margin_rate,vip_discount_rate\n"
            "ST-304-CR,304冷轧不锈钢卷,2.0mm*1219mm*C,14800,11500,320,120,0.12,0.92\n"
            "ST-316L-PIPE,316L耐蚀无缝钢管,Phi57*3.5mm,26500,20400,145,60,0.14,0.90\n"
            "ST-42CRMO-BAR,42CrMo高强合金圆钢,Phi80mm热轧,6850,5200,540,200,0.15,0.88\n"
            "ST-Q345B-PLATE,Q345B低合金中厚板,20mm*2200mm,4620,3650,820,300,0.11,0.93\n"
            "ST-H13-MOLD,H13电渣重熔热作模具钢,Flat120*400mm,19200,14500,95,40,0.16,0.89\n"
            "ST-GH4169-NI,GH4169航空高温镍基合金板,5.0mm固溶态,168000,128000,28,12,0.18,0.95\n"
        ),
    },
    {
        "sample_id": "sample_json_erp_bom",
        "doc_title": "《新能源PACK产线核心电芯采购BOM与供应商账期权限配置表 (JSON)》",
        "title": "《新能源PACK产线核心电芯采购BOM与供应商账期权限配置表 (JSON)》",
        "doc_format": "JSON",
        "target_department": "产研供应链采购部",
        "target_slot_id": "SLOT_PROCURE_01",
        "description": (
            "结构化 ERP 导出 JSON：包含 100kWh 储能/动力电池 PACK 核心物料清单（BOM）、"
            "AQL 良率红线、各级采购审批金额阈值与供应商返点/账期结算规则。"
        ),
        "highlights": [
            "5 大核心 PACK 物料 BOM（磷酸铁锂电芯、BMS主控板、液冷板、高压接触器、导热结构胶）",
            "内嵌三级采购金额审批门禁（10万自动补货 / 50万主管初审 / 超50万董事会特批）",
            "电芯 AQL 良率红线 (>=99.5%) 与供应商长协底价保密隔离墙",
        ],
        "raw_content": json.dumps(
            {
                "bom_id": "ERP-BOM-PACK-2026Q4",
                "pack_model": "Arachne-Energy-100kWh-LFP",
                "currency": "CNY",
                "bom_items": [
                    {
                        "sku": "CELL-LFP-280AH",
                        "part_name": "280Ah磷酸铁锂储能A品电芯",
                        "category": "核心电芯",
                        "base_unit_price": 420.0,
                        "cost_floor_price": 320.0,
                        "bom_qty_per_pack": 112,
                        "stock_tons": 4800,
                        "safety_stock_tons": 1500,
                        "min_margin_rate": 0.15,
                        "min_yield_rate": 0.996,
                    },
                    {
                        "sku": "BMS-MASTER-V4",
                        "part_name": "三Redundancy高压BMS主控模组",
                        "category": "电子电控",
                        "base_unit_price": 1850.0,
                        "cost_floor_price": 1420.0,
                        "bom_qty_per_pack": 1,
                        "stock_tons": 360,
                        "safety_stock_tons": 120,
                        "min_margin_rate": 0.18,
                        "min_yield_rate": 0.998,
                    },
                    {
                        "sku": "COOL-PLATE-AL",
                        "part_name": "微通道钎焊铝合金液冷板",
                        "category": "热管理组件",
                        "base_unit_price": 680.0,
                        "cost_floor_price": 530.0,
                        "bom_qty_per_pack": 2,
                        "stock_tons": 620,
                        "safety_stock_tons": 200,
                        "min_margin_rate": 0.14,
                        "min_yield_rate": 0.992,
                    },
                    {
                        "sku": "HV-RELAY-1000V",
                        "part_name": "1000V直流充氮高压主接触器",
                        "category": "高压配电",
                        "base_unit_price": 390.0,
                        "cost_floor_price": 295.0,
                        "bom_qty_per_pack": 3,
                        "stock_tons": 950,
                        "safety_stock_tons": 300,
                        "min_margin_rate": 0.16,
                        "min_yield_rate": 0.995,
                    },
                    {
                        "sku": "GLUE-THERM-SI",
                        "part_name": "双组份高导热阻燃有机硅结构胶",
                        "category": "辅材化工",
                        "base_unit_price": 145.0,
                        "cost_floor_price": 108.0,
                        "bom_qty_per_pack": 6,
                        "stock_tons": 1800,
                        "safety_stock_tons": 600,
                        "min_margin_rate": 0.12,
                        "min_yield_rate": 0.990,
                    },
                ],
                "approval_thresholds": {
                    "auto_replenish_max_cny": 100000,
                    "procure_leader_max_cny": 500000,
                    "executive_board_above_cny": 500000,
                    "max_supplier_payment_days": 60,
                },
                "pricing_and_rebate_rules": {
                    "tier_1_qty": 20,
                    "tier_1_rebate_rate": 0.03,
                    "tier_2_qty": 50,
                    "tier_2_rebate_rate": 0.06,
                    "tier_3_qty": 100,
                    "tier_3_rebate_rate": 0.095,
                    "overdue_daily_penalty_rate": 0.0005,
                    "overdue_penalty_cap_rate": 0.20,
                },
                "redline_policies": [
                    "严禁采购循环寿命低于6000次或电芯批次良率低于99.5%的B品拆机电芯",
                    "核心商业绝密：280Ah磷酸铁锂电芯长协拿货底价345元/颗及BMS主控BOM底价1420元/套严禁向外部透出",
                    "严禁未经采购主管与法务黑盒双签私自将供应商预付款比例提高至30%以上",
                ],
                "redline_keywords": [
                    "电芯长协拿货底价",
                    "BMS主控BOM底价",
                    "供应商年度暗返",
                    "B品拆机电芯",
                    "cost_floor_price",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
    },
    {
        "sample_id": "sample_contract_rebate_md",
        "doc_title": "《2026年度核心经销商阶梯返利、账期风控与违约金核算主合同 (CONTRACT_MD)》",
        "title": "《2026年度核心经销商阶梯返利、账期风控与违约金核算主合同 (CONTRACT_MD)》",
        "doc_format": "CONTRACT_MD",
        "target_department": "",
        "target_slot_id": None,
        "description": (
            "标准企业经销商主合同 Markdown 全文：含主力产品基准价与渠道底线价表、"
            "季度阶梯返利公式、逾期付款违约金日息（0.05%/日，20%封顶）精算公式、分级特批权限与严禁窜货红线。"
        ),
        "highlights": [
            "多章节合同结构：价目表 + 阶梯返利公式 + 逾期日息违约金公式 + 特批门禁 + 反窜货红线",
            "自动将合同条款编译为可传入 sku/quantity/discount_rate/overdue_days 的沙箱精算算子",
            "自动提取省级总代底价、年度暗返协议、无限连带责任等法务与商务红线词",
        ],
        "raw_content": (
            "# 2026年度核心经销商阶梯返利、账期风控与违约金核算主合同\n\n"
            "## 第一章：授权标的物、公开基准价与渠道成本底线表\n"
            "| sku | product_name | base_unit_price | cost_floor_price | stock_tons | min_margin_rate |\n"
            "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
            "| MDL-CHAIR-A1 | 旗舰精密工作台Pro | 1280 | 820 | 360 | 0.15 |\n"
            "| MDL-DESK-B2 | 智能工业装配台Max | 2190 | 1450 | 145 | 0.16 |\n"
            "| MDL-ARM-C3 | 双轴精密机械臂Ultra | 399 | 240 | 520 | 0.14 |\n"
            "| MDL-BOOTH-D4 | 恒温精密检测隔离舱 | 16800 | 11800 | 42 | 0.18 |\n\n"
            "## 第二章：季度与年度阶梯返利核算公式\n"
            "1. 常规提货门槛：单笔或单季提货满 20 件（或金额满 200,000 元），享受 3.0% 阶梯返利（`rebate_rate = 0.03`）；\n"
            "2. 核心银牌档位：单笔或单季提货满 50 件（或金额满 500,000 元），享受 6.0% 阶梯返利（`rebate_rate = 0.06`）；\n"
            "3. 战略金牌档位：单笔或单季提货满 100 件（或金额满 1,000,000 元），享受 9.5% 阶梯返利（`rebate_rate = 0.095`）。\n\n"
            "## 第三章：授信账期与逾期违约金日息精算规则\n"
            "1. 标准授信账期为货到签收后 45 个自然日；\n"
            "2. 逾期违约金计算公式：`overdue_penalty = gross_amount * 0.0005 * overdue_days`（即按逾期未付金额每日万分之五计收违约金）；\n"
            "3. 违约金封顶保护：累计逾期违约金最高不超过合同应付总金额的 20%（`max_cap = gross_amount * 0.20`）。\n\n"
            "## 第四章：分级特批权限门禁（Authority Matrix）\n"
            "- 一线业务跟单专员：仅限在折扣率 >= 9.0 折（0.90）、且毛利率不低于 `min_margin_rate` 红线的标准合同内自助锁库排产；\n"
            "- 业务风控组长：拥有 8.5 折 ~ 9.0 折特批权，以及 30 天以内账期展期与 <= 2,000 元履约退换补偿初审权；\n"
            "- 部门总监与董事长：凡涉及低于 8.5 折特批、单笔金额超 500,000 元或减免逾期违约金，须挂起上报高管审批。\n\n"
            "## 第五章：绝密底价隔离与反窜货高压红线（Redline Prohibitions）\n"
            "- 【核心商业绝密】表内所列 `cost_floor_price`（区域总代核算底价：精密工作台 ¥820/台、装配台 ¥1,450/套、检测舱 ¥11,800/套）及年度暗返底价协议，严禁向任何非授权二级分销商或一线人员透出！\n"
            "- 【反窜货与法务红线】严禁经销商跨授权战区低价倾销窜货；严禁任何销售人员在补充协议中签署无限连带责任、十倍赔偿承诺或免除全部违约上限条款。\n"
        ),
    },
]


def get_ingestion_samples() -> list[dict[str, Any]]:
    return [dict(item) for item in INGESTION_SAMPLES]


def _try_float(val: Any) -> Optional[float]:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "").replace("¥", "").replace("￥", "").replace("$", "")
    if s.endswith("%"):
        try:
            return round(float(s[:-1]) / 100.0, 6)
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


class EnterpriseIngestor:
    """
    Pillar 3 核心组件：企业全模态表格/合同深度吞噬器 (Enterprise Ingestor)。
    支持将 CSV 台账、JSON ERP/BOM 配置表与 Markdown 商业合同解析为：
    1. 结构化统计画像 (schema_profile: 行列统计、数值列 min/max/mean/sum、主键列、敏感底价/毛利列)；
    2. 四角权能球组 (DATA + 真实内嵌数据与公式的沙箱 SKILL + AUTHORITY + REDLINE)；
    3. 现场在 `python -I` 洁净室子进程中完成实弹计算验证 (sandbox_verification)，并自动挂载至目标工位容器。
    """

    def __init__(
        self,
        state: Optional[EnterpriseState] = None,
        runtime: Optional[EnterpriseState] = None,
    ) -> None:
        self.state = state or runtime
        if self.state is not None:
            if hasattr(self.state, "particles") and not hasattr(self.state, "ball_registry"):
                setattr(self.state, "ball_registry", self.state.particles._balls)
            if hasattr(self.state, "vault") and hasattr(self.state, "particles") and hasattr(self.state, "containers"):
                auth_svc = getattr(self.state, "auth_custody", None) or getattr(
                    self.state, "auth_custody_manager", None
                )
                if auth_svc is None:
                    auth_svc = AuthAndCustodyService(
                        vault=self.state.vault,
                        particles=self.state.particles,
                        containers=self.state.containers,
                    )
                setattr(self.state, "auth_custody", auth_svc)
                setattr(self.state, "auth_custody_manager", auth_svc)

    def get_ingestion_samples(self) -> list[dict[str, Any]]:
        return get_ingestion_samples()

    def detect_format(self, raw_content: str, doc_format: str = "AUTO") -> str:
        fmt = (doc_format or "AUTO").strip().upper()
        if fmt in ("CSV", "JSON", "CONTRACT_MD"):
            return fmt
        stripped = (raw_content or "").strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                json.loads(stripped)
                return "JSON"
            except Exception:
                pass
        lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
        if len(lines) >= 2 and not lines[0].startswith("#") and not lines[0].startswith("|"):
            comma_c0 = lines[0].count(",")
            comma_c1 = lines[1].count(",")
            if comma_c0 >= 2 and comma_c1 >= 2:
                return "CSV"
        return "CONTRACT_MD"

    def _compute_table_profile(
        self,
        rows: list[dict[str, Any]],
        extra_redlines: Optional[list[str]] = None,
        extra_thresholds: Optional[dict[str, Any]] = None,
        extra_formulas: Optional[list[str]] = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        columns: list[str] = []
        for r in rows:
            for k in r.keys():
                if k and k not in columns:
                    columns.append(str(k).strip())

        pk_candidates = ("sku", "id", "code", "part_no", "model", "型号", "编码", "物料")
        primary_key = columns[0] if columns else "sku"
        for col in columns:
            if any(pk in col.lower() for pk in pk_candidates):
                primary_key = col
                break

        numeric_stats: dict[str, dict[str, Any]] = {}
        for col in columns:
            vals: list[float] = []
            for r in rows:
                fv = _try_float(r.get(col))
                if fv is not None:
                    vals.append(fv)
            if vals:
                numeric_stats[col] = {
                    "min": round(min(vals), 4),
                    "max": round(max(vals), 4),
                    "mean": round(sum(vals) / len(vals), 4),
                    "sum": round(sum(vals), 4),
                    "count": len(vals),
                }

        sensitive_markers = (
            "cost",
            "floor",
            "底价",
            "成本",
            "margin",
            "毛利",
            "discount",
            "折扣",
            "price",
            "单价",
            "stock",
            "库存",
            "yield",
            "良率",
            "rebate",
            "返利",
        )
        sensitive_cols = [
            col
            for col in columns
            if any(mk in col.lower() for mk in sensitive_markers)
        ]

        normalized_records: list[dict[str, Any]] = []
        for idx, r in enumerate(rows):
            sku_val = str(
                r.get(primary_key)
                or r.get("sku")
                or r.get("part_name")
                or r.get("product_name")
                or f"ITEM-{idx + 1:02d}"
            ).strip()
            name_val = str(
                r.get("product_name")
                or r.get("part_name")
                or r.get("name")
                or sku_val
            ).strip()
            base_p = (
                _try_float(r.get("base_unit_price"))
                or _try_float(r.get("standard_unit_price"))
                or _try_float(r.get("unit_price"))
                or _try_float(r.get("price"))
                or 1000.0
            )
            floor_p = (
                _try_float(r.get("cost_floor_price"))
                or _try_float(r.get("supplier_floor_price"))
                or _try_float(r.get("floor_price"))
                or round(base_p * 0.78, 2)
            )
            stock_v = (
                _try_float(r.get("stock_tons"))
                or _try_float(r.get("current_stock_qty"))
                or _try_float(r.get("stock"))
                or 100.0
            )
            safety_v = (
                _try_float(r.get("safety_stock_tons"))
                or _try_float(r.get("safety_stock_qty"))
                or round(stock_v * 0.35, 2)
            )
            margin_v = _try_float(r.get("min_margin_rate")) or 0.12
            vip_disc = _try_float(r.get("vip_discount_rate")) or 0.90
            normalized_records.append(
                {
                    "sku": sku_val,
                    "name": name_val,
                    "base_unit_price": float(base_p),
                    "cost_floor_price": float(floor_p),
                    "stock_tons": float(stock_v),
                    "safety_stock_tons": float(safety_v),
                    "min_margin_rate": float(margin_v),
                    "vip_discount_rate": float(vip_disc),
                }
            )

        redline_kws = list(extra_redlines or [])
        for col in sensitive_cols:
            if any(k in col.lower() for k in ("floor", "cost", "底价", "成本", "margin", "yield")):
                if col not in redline_kws:
                    redline_kws.append(col)
        for base_kw in ("成本底价", "拿货底价", "出厂底价", "最低毛利红线", "cost_floor_price"):
            if base_kw not in redline_kws:
                redline_kws.append(base_kw)

        profile = {
            "row_count": len(rows),
            "column_count": len(columns),
            "columns": columns,
            "primary_key_column": primary_key,
            "numeric_columns": numeric_stats,
            "sensitive_columns": sensitive_cols,
            "approval_thresholds": extra_thresholds
            or {
                "frontline_min_discount": 0.90,
                "leader_min_discount": 0.85,
                "auto_approve_max_amount_cny": 100000.0,
                "board_escalate_amount_cny": 500000.0,
            },
            "extracted_formulas": extra_formulas
            or [
                "effective_unit_price = base_unit_price * discount_rate",
                "actual_margin_rate = (effective_unit_price - cost_floor_price) / effective_unit_price",
                "tiered_rebate: >=20件享3%, >=50件享6%, >=100件享9.5%",
                "overdue_penalty = min(gross_amount * 0.0005 * overdue_days, gross_amount * 0.20)",
            ],
            "redline_keywords_detected": redline_kws[:12],
            "records_preview": normalized_records[:6],
        }
        return profile, normalized_records

    def _parse_csv(self, raw_content: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        reader = csv.DictReader(io.StringIO(raw_content.strip()))
        rows = [
            {str(k).strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
            for row in reader
        ]
        return self._compute_table_profile(rows)

    def _parse_json(self, raw_content: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        data = json.loads(raw_content.strip())
        rows: list[dict[str, Any]] = []
        thresholds: dict[str, Any] = {}
        redlines: list[str] = []
        formulas: list[str] = []

        if isinstance(data, list):
            rows = [r for r in data if isinstance(r, dict)]
        elif isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    rows.extend(v)
                elif isinstance(v, dict) and any(
                    tk in k.lower() for tk in ("approval", "threshold", "authority", "limit")
                ):
                    thresholds.update(v)
                elif isinstance(v, dict) and any(
                    fk in k.lower() for fk in ("pricing", "rebate", "formula", "rule")
                ):
                    formulas.extend(f"{rk}={rv}" for rk, rv in v.items())
                elif isinstance(v, list) and any(rk in k.lower() for rk in ("redline", "secret", "prohibit")):
                    redlines.extend(str(item) for item in v)

        return self._compute_table_profile(
            rows=rows,
            extra_redlines=redlines,
            extra_thresholds=thresholds or None,
            extra_formulas=formulas or None,
        )

    def _parse_contract_md(
        self, raw_content: str, doc_title: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        text = raw_content.strip()
        rows: list[dict[str, Any]] = []

        # 解析 Markdown 表格
        table_lines = [
            ln.strip()
            for ln in text.splitlines()
            if ln.strip().startswith("|") and ln.strip().endswith("|")
        ]
        if len(table_lines) >= 3:
            headers = [c.strip() for c in table_lines[0].strip("|").split("|")]
            for row_line in table_lines[2:]:
                if set(row_line.replace("|", "").replace(":", "").replace("-", "").strip()) == set():
                    continue
                cells = [c.strip() for c in row_line.strip("|").split("|")]
                if len(cells) == len(headers):
                    rows.append(dict(zip(headers, cells)))

        # 若无 Markdown 表格，从文本行提炼默认标的行
        if not rows:
            rows = [
                {
                    "sku": "CONTRACT-STD-01",
                    "product_name": doc_title[:16] or "主合同标准标的物",
                    "base_unit_price": 1280.0,
                    "cost_floor_price": 820.0,
                    "stock_tons": 360.0,
                    "min_margin_rate": 0.15,
                }
            ]

        # 正则提取合同公式、特批阈值與严禁红线
        formulas: list[str] = []
        for m in re.finditer(r"`([^`]+=.+?)`", text):
            formulas.append(m.group(1))
        if not formulas:
            formulas = [
                "rebate_rate: >=20件享3%, >=50件享6%, >=100件享9.5%",
                "overdue_penalty = min(gross_amount * 0.0005 * overdue_days, gross_amount * 0.20)",
            ]

        redlines: list[str] = []
        for kw in (
            "省代出厂核算底价",
            "年度暗返底价",
            "cost_floor_price",
            "无限连带责任",
            "十倍赔偿承诺",
            "免除全部违约上限",
            "跨授权战区低价倾销窜货",
            "拿货底价",
        ):
            if kw in text or kw == "拿货底价":
                redlines.append(kw)

        # 若开启真实大模型，调用 DeepSeek 进行深度语义补充
        llm_gw = getattr(self.state, "llm_gateway", None) if self.state else None
        is_live = bool(
            llm_gw and (getattr(llm_gw, "is_live_mode", False) or getattr(llm_gw, "is_live", False))
        )
        if is_live and self.state is not None:
            try:
                settings = self.state.settings
                client = OpenAI(
                    api_key=settings.llm_api_key,
                    base_url=settings.llm_base_url,
                    timeout=min(12.0, float(settings.llm_timeout_seconds)),
                )
                resp = client.chat.completions.create(
                    model=settings.llm_model_l2_fast,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "请从商业合同文本中提取 JSON：{\"redline_keywords\": [str], \"formulas\": [str]}。"
                            ),
                        },
                        {"role": "user", "content": text[:1500]},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                )
                if hasattr(llm_gw, "_telemetry"):
                    llm_gw._telemetry["l2_fast_calls"] = llm_gw._telemetry.get("l2_fast_calls", 0) + 1
                    llm_gw._telemetry["live_api_hits"] = llm_gw._telemetry.get("live_api_hits", 0) + 1
                parsed_llm = json.loads(resp.choices[0].message.content or "{}")
                for kw in parsed_llm.get("redline_keywords", []):
                    if isinstance(kw, str) and kw.strip() and kw.strip() not in redlines:
                        redlines.append(kw.strip())
                for fm in parsed_llm.get("formulas", []):
                    if isinstance(fm, str) and fm.strip() and fm.strip() not in formulas:
                        formulas.append(fm.strip())
            except Exception:
                pass

        return self._compute_table_profile(
            rows=rows,
            extra_redlines=redlines,
            extra_formulas=formulas,
        )

    def _compile_and_verify_ingested_skill(
        self,
        ball_id: str,
        doc_title: str,
        records: list[dict[str, Any]],
        schema_profile: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        sandbox_dir = (
            Path(self.state.settings.sandbox_workspace_dir)
            if (self.state is not None and hasattr(self.state, "settings"))
            else Path("/tmp/arachne_sandbox_workspace")
        )
        sandbox_dir.mkdir(parents=True, exist_ok=True)

        records_literal = json.dumps(records, ensure_ascii=False, indent=4)
        thresholds_literal = json.dumps(
            schema_profile.get("approval_thresholds", {}), ensure_ascii=False, indent=4
        )

        # 生成符合 sandbox_ast_guard 规范（零双下划线、纯白名单标准库）的可执行沙箱脚本
        code = f'''import math

INGESTED_RECORDS = {records_literal}
APPROVAL_THRESHOLDS = {thresholds_literal}


def execute_skill(payload: dict) -> dict:
    sku_query = str(payload.get("sku") or payload.get("part_no") or payload.get("model") or "").strip()
    quantity = float(payload.get("quantity") or payload.get("qty") or payload.get("tons") or 10.0)
    raw_discount = float(payload.get("discount_rate") or payload.get("discount") or 1.0)
    if raw_discount > 1.0 and raw_discount <= 10.0:
        discount_rate = round(raw_discount / 10.0, 4)
    else:
        discount_rate = raw_discount
    overdue_days = int(payload.get("overdue_days") or 0)

    matched = None
    sku_matched = False
    for row in INGESTED_RECORDS:
        if sku_query and (row.get("sku", "").upper() == sku_query.upper() or sku_query in row.get("name", "")):
            matched = row
            sku_matched = True
            break
    if matched is None and INGESTED_RECORDS:
        matched = INGESTED_RECORDS[0]

    base_price = float(
        payload.get("unit_price")
        if payload.get("unit_price") is not None
        else (matched.get("base_unit_price", 1000.0) if matched else 1000.0)
    )
    cost_floor = float(matched.get("cost_floor_price", round(base_price * 0.78, 2)) if matched else round(base_price * 0.78, 2))
    stock_avail = float(matched.get("stock_tons", 100.0) if matched else 100.0)
    safety_stock = float(matched.get("safety_stock_tons", 30.0) if matched else 30.0)
    min_margin = float(matched.get("min_margin_rate", 0.12) if matched else 0.12)
    resolved_sku = str(matched.get("sku", sku_query or "DEFAULT-SKU") if matched else (sku_query or "DEFAULT-SKU"))

    effective_unit_price = round(base_price * discount_rate, 2)
    gross_amount = round(effective_unit_price * quantity, 2)
    total_cost = round(cost_floor * quantity, 2)
    if effective_unit_price > 0:
        actual_margin_rate = round((effective_unit_price - cost_floor) / effective_unit_price, 4)
    else:
        actual_margin_rate = 0.0

    margin_compliance = bool(actual_margin_rate >= min_margin and effective_unit_price >= cost_floor)
    stock_sufficient = bool(stock_avail >= quantity)
    below_safety_stock_after = bool((stock_avail - quantity) < safety_stock)

    if quantity >= 100 or gross_amount >= 1000000.0:
        rebate_rate = 0.095
    elif quantity >= 50 or gross_amount >= 500000.0:
        rebate_rate = 0.06
    elif quantity >= 20 or gross_amount >= 200000.0:
        rebate_rate = 0.03
    else:
        rebate_rate = 0.0
    rebate_amount = round(gross_amount * rebate_rate, 2)

    daily_penalty_rate = 0.0005
    raw_penalty = round(gross_amount * daily_penalty_rate * max(0, overdue_days), 2)
    penalty_cap = round(gross_amount * 0.20, 2)
    overdue_penalty = min(raw_penalty, penalty_cap)

    net_settlement_amount = round(gross_amount - rebate_amount + overdue_penalty, 2)
    approval_required = bool(
        (not margin_compliance)
        or discount_rate < 0.90
        or gross_amount > 500000.0
        or overdue_days > 45
    )

    return {{
        "status": "ok",
        "result": net_settlement_amount,
        "sku": resolved_sku,
        "sku_matched": sku_matched,
        "quantity": quantity,
        "base_unit_price": base_price,
        "discount_rate": discount_rate,
        "effective_unit_price": effective_unit_price,
        "cost_floor_price": cost_floor,
        "gross_amount": gross_amount,
        "total_cost": total_cost,
        "actual_margin_rate": actual_margin_rate,
        "min_margin_rate": min_margin,
        "margin_compliance": margin_compliance,
        "stock_available": stock_avail,
        "stock_sufficient": stock_sufficient,
        "below_safety_stock_after": below_safety_stock_after,
        "rebate_rate": rebate_rate,
        "rebate_amount": rebate_amount,
        "overdue_days": overdue_days,
        "overdue_penalty": overdue_penalty,
        "net_settlement_amount": net_settlement_amount,
        "approval_required": approval_required,
    }}
'''
        sandbox_ast_guard(code)
        script_filename = f"skill_{ball_id.lower()}.py"
        script_path = sandbox_dir / script_filename
        script_path.write_text(code, encoding="utf-8")

        first_sku = records[0]["sku"] if records else "ST-304-CR"
        verification_inputs = [
            {
                "sku": first_sku,
                "quantity": 25,
                "discount_rate": 0.95,
                "overdue_days": 0,
            },
            {
                "sku": first_sku,
                "quantity": 60,
                "discount_rate": 0.90,
                "overdue_days": 15,
            },
        ]
        run_outputs = run_skill_in_isolated_subprocess(
            script_path=script_path,
            sandbox_dir=sandbox_dir,
            input_payloads=verification_inputs,
            timeout_seconds=3.0,
        )
        passed = bool(run_outputs and all(item.get("ok") is True for item in run_outputs))
        verification_report = {
            "passed": passed,
            "ast_passed": True,
            "isolation_mode": "python -I",
            "script_filename": script_filename,
            "script_path": str(script_path),
            "test_cases_count": len(verification_inputs),
            "sample_outputs": [item.get("output") for item in run_outputs],
            "raw_runs": run_outputs,
        }
        return script_filename, verification_report

    def _resolve_target_slot(
        self, target_slot_id: Optional[str], target_department: str
    ) -> Optional[str]:
        if self.state is None or not hasattr(self.state, "containers"):
            return target_slot_id or "SLOT_BOSS"
        containers = self.state.containers
        if target_slot_id:
            try:
                slot = containers.get_slot(target_slot_id)
                return slot.slot_id
            except KeyError:
                pass

        all_slots: list[UnitSlot] = containers.list_slots()
        if not all_slots:
            return target_slot_id

        dept_clean = (target_department or "").strip()
        if dept_clean:
            for s in all_slots:
                if dept_clean in s.department or s.department in dept_clean:
                    return s.slot_id
            for uid, meta in ACCOUNT_DIRECTORY.items():
                meta_dept = str(meta.get("department", ""))
                if dept_clean in meta_dept or meta_dept in dept_clean:
                    try:
                        prof = containers.get_profile(uid)
                        return prof.slot_id
                    except KeyError:
                        continue

        _, default_sid = resolve_frontline_user_and_slot(containers)
        return default_sid or all_slots[0].slot_id

    def ingest_enterprise_document(
        self,
        doc_title: str = "企业业务数据台账",
        doc_format: str = "AUTO",
        raw_content: str = "",
        target_department: str = "",
        target_slot_id: Optional[str] = None,
        auto_forge_query_skill: bool = True,
        sample_id: Optional[str] = None,
    ) -> dict[str, Any]:
        if sample_id:
            matched_sample = next(
                (s for s in INGESTION_SAMPLES if s["sample_id"] == sample_id), None
            )
            if matched_sample:
                doc_title = (
                    doc_title
                    if doc_title != "企业业务数据台账"
                    else matched_sample["doc_title"]
                )
                doc_format = (
                    doc_format if doc_format != "AUTO" else matched_sample["doc_format"]
                )
                raw_content = raw_content or matched_sample["raw_content"]
                target_department = (
                    target_department or matched_sample["target_department"]
                )
                target_slot_id = target_slot_id or matched_sample["target_slot_id"]

        if not (raw_content or "").strip():
            raise ValueError("吞噬文档内容 raw_content 不能为空")

        clean_title = (doc_title or "企业业务数据台账").strip()
        detected_fmt = self.detect_format(raw_content, doc_format)

        if detected_fmt == "CSV":
            schema_profile, records = self._parse_csv(raw_content)
            domain_tags = ["报价", "库存", "台账", "阶梯核算"]
        elif detected_fmt == "JSON":
            schema_profile, records = self._parse_json(raw_content)
            domain_tags = ["采购", "供应链", "BOM", "库存"]
        else:
            schema_profile, records = self._parse_contract_md(raw_content, clean_title)
            domain_tags = ["报价", "折扣", "合同", "法务"]

        ingestion_id = f"ING_{uuid.uuid4().hex[:8].upper()}"
        short_id = ingestion_id.replace("ING_", "")
        mounted_slot_id = self._resolve_target_slot(target_slot_id, target_department)
        owner_slots = [mounted_slot_id] if mounted_slot_id else ["SLOT_BOSS"]
        if "SLOT_BOSS" not in owner_slots:
            owner_slots_with_boss = [*owner_slots, "SLOT_BOSS"]
        else:
            owner_slots_with_boss = list(owner_slots)

        # REDLINE ownership is derived from actual boss profiles, independently
        # of the requested operational target and any topology fallbacks.
        containers = getattr(self.state, "containers", None) if self.state else None
        boss_slots = (
            [
                p.slot_id
                for p in containers.list_profiles()
                if p.role_view == "boss"
                and containers.get_slot(p.slot_id).occupant_id == p.user_id
            ]
            if containers is not None
            else []
        )

        created_balls: list[CapabilityBall] = []

        # 1. DATA 球
        sku_summary = "；".join(
            f"{r['sku']}({r['name']}): 基准价¥{r['base_unit_price']}, 库存{r['stock_tons']}"
            for r in records[:5]
        )
        data_ball = CapabilityBall(
            ball_id=f"BALL_DATA_ING_{short_id}",
            ball_type="DATA",
            title=f"【全模态吞噬·DATA】{clean_title}",
            domain_tags=domain_tags,
            sensitivity_level=2,
            owner_slot_ids=owner_slots_with_boss,
            content=(
                f"格式：{detected_fmt} | 共 {schema_profile['row_count']} 条核心记录、"
                f"{schema_profile['column_count']} 个字段（主键：{schema_profile['primary_key_column']}）。"
                f"核心条目摘要：{sku_summary}。"
            ),
            status="ACTIVE",
        )
        created_balls.append(data_ball)

        # 2. SKILL 球（真实编译落盘 + python -I 子进程实弹验证）
        sandbox_verification: dict[str, Any] = {
            "passed": False,
            "ast_passed": False,
            "reason": "auto_forge_query_skill is False",
        }
        if auto_forge_query_skill:
            skill_ball_id = f"BALL_SKILL_ING_{short_id}"
            script_filename, sandbox_verification = (
                self._compile_and_verify_ingested_skill(
                    ball_id=skill_ball_id,
                    doc_title=clean_title,
                    records=records,
                    schema_profile=schema_profile,
                )
            )
            skill_ball = CapabilityBall(
                ball_id=skill_ball_id,
                ball_type="SKILL",
                title=f"【全模态吞噬·SKILL】{clean_title}查表与阶梯精算器",
                domain_tags=[*domain_tags, "自动精算"],
                sensitivity_level=2,
                owner_slot_ids=owner_slots_with_boss,
                content=(
                    f"内嵌 {len(records)} 条真实台账记录与合同精算公式的洁净室 Python 算子（{script_filename}）："
                    "支持传入 sku、quantity、unit_price、discount_rate、overdue_days 实时执行查表定价、"
                    "最低毛利红线校验、阶梯返利计提与逾期日息违约金核算。"
                ),
                executable_code_path=script_filename,
                status="ACTIVE",
            )
            created_balls.append(skill_ball)

        # 3. AUTHORITY 权限球
        thresholds_desc = json.dumps(
            schema_profile.get("approval_thresholds", {}), ensure_ascii=False
        )
        auth_ball = CapabilityBall(
            ball_id=f"BALL_AUTH_ING_{short_id}",
            ball_type="AUTHORITY",
            title=f"【全模态吞噬·AUTHORITY】{clean_title}分级审批门禁",
            domain_tags=[*domain_tags, "风控审批"],
            sensitivity_level=3,
            owner_slot_ids=owner_slots_with_boss,
            content=(
                f"基于《{clean_title}》自动提炼的分级授权门禁：{thresholds_desc}。"
                "常规折扣与毛利达标可自助锁库；低于毛利红线或超额采购自动挂起转主管/董事会特批。"
            ),
            status="ACTIVE",
        )
        created_balls.append(auth_ball)

        # 4. REDLINE 红线球
        redline_kws = list(schema_profile.get("redline_keywords_detected", []))
        floor_summary = "、".join(
            f"{r['sku']}底价¥{r['cost_floor_price']}" for r in records[:4]
        )
        redline_ball = CapabilityBall(
            ball_id=f"BALL_REDLINE_ING_{short_id}",
            ball_type="REDLINE",
            title=f"【全模态吞噬·REDLINE】{clean_title}绝密底价与合规红线",
            domain_tags=["底价", "机密成本", "合规", *domain_tags[:1]],
            sensitivity_level=5,
            owner_slot_ids=boss_slots,
            content=(
                f"【核心商业绝密】《{clean_title}》底层成本底价（{floor_summary}）与禁止性条款严禁向外部或无权限工位透出！"
            ),
            redline_keywords=redline_kws,
            status="ACTIVE",
        )
        created_balls.append(redline_ball)

        # 注册进 particles / ball_registry 并挂载到目标工位与账号
        worm_event = None
        if self.state is not None:
            particles = getattr(self.state, "particles", None)
            ball_reg = getattr(self.state, "ball_registry", None)
            containers = getattr(self.state, "containers", None)
            vault = getattr(self.state, "vault", None)

            for b in created_balls:
                if particles is not None:
                    particles.register_ball(b, record_to_vault=True)
                if isinstance(ball_reg, dict):
                    ball_reg[b.ball_id] = b
                mount_slots = (
                    boss_slots if b.ball_type == "REDLINE" else [mounted_slot_id]
                )
                if containers is not None:
                    for mount_slot in mount_slots:
                        if not mount_slot:
                            continue
                        try:
                            containers.attach_ball_to_slot(mount_slot, b.ball_id)
                        except KeyError:
                            pass

            # 同步更新关联账号的 mounted_ball_ids 属性（若存在）
            if containers is not None and mounted_slot_id:
                try:
                    slot_obj = containers.get_slot(mounted_slot_id)
                    prof_obj = containers.get_profile(slot_obj.occupant_id)
                    object.__setattr__(
                        prof_obj, "mounted_ball_ids", list(slot_obj.ball_ids)
                    )
                except Exception:
                    pass

            if vault is not None:
                worm_event = vault.append_event(
                    event_kind="ENTERPRISE_DOCUMENT_INGESTED",
                    subtree_root_id="root",
                    actor_slot_id=mounted_slot_id or "SLOT_BOSS",
                    payload={
                        "ingestion_id": ingestion_id,
                        "doc_title": clean_title,
                        "detected_format": detected_fmt,
                        "row_count": schema_profile["row_count"],
                        "created_ball_ids": [b.ball_id for b in created_balls],
                        "mounted_to_slot_id": mounted_slot_id,
                        "sandbox_passed": sandbox_verification.get("passed", False),
                    },
                )

        summary_text = (
            f"已成功吞噬《{clean_title}》（格式：{detected_fmt}，共 {schema_profile['row_count']} 条记录），"
            f"自动锻造 {len(created_balls)} 颗权能小球，业务球挂载至工位 {mounted_slot_id}；"
            "REDLINE 仅授权并挂载至老板工位。"
        )
        return {
            "ingestion_id": ingestion_id,
            "doc_title": clean_title,
            "detected_format": detected_fmt,
            "schema_profile": schema_profile,
            "created_balls": [b.model_dump() for b in created_balls],
            "mounted_to_slot_id": mounted_slot_id,
            "target_department": target_department,
            "sandbox_verification": sandbox_verification,
            "summary": summary_text,
            "worm_event": worm_event.model_dump() if worm_event else None,
        }

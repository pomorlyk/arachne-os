from __future__ import annotations

from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from core.particles import ParticleEngine
from core.schemas import (
    CapabilityBall,
    DualEmployeeProfile,
    EmployeeViewA,
    ManagementViewB,
    SpiderNode,
    UnitSlot,
)
from database import HotStateStore


async def seed_full_company_expansion(
    vault: BlackBoxVault,
    particles: ParticleEngine,
    containers: ContainerRegistry,
    hot_store: HotStateStore,
) -> None:
    """
    Wave 1：将单一部室扩建为五大核心部门 12 工位真公司全链路沙盘（完全兼容原 5 大种子角色与测试断言）。
    新增部门与工位：
    - 商务跟单部二号位：SLOT_FOLLOWUP_02 (emp_zhou · 小周)
    - 智能仓储与物流部：SLOT_WMS_01 (wms_zhao · 老赵), SLOT_LOGISTICS_01 (log_sun · 小孙)
    - 产研与供应链采购部：SLOT_PROCURE_01 (proc_lin · 林工), SLOT_QA_01 (qa_chen · 陈工)
    - 财税与法务风控黑盒部：SLOT_LEGAL_BOX (leg_liu · 刘律)
    - 经营管理与进化部：SLOT_HR_EVO (hr_su · 苏主管)
    """
    extra_balls = [
        CapabilityBall(
            ball_id="BALL_DATA_WMS_SAFETY_STOCK",
            ball_type="DATA",
            title="张江仓与华南仓安全库存水位及补货公式",
            domain_tags=["仓储", "库存", "供应链"],
            sensitivity_level=2,
            owner_slot_ids=["SLOT_WMS_01", "SLOT_PROCURE_01", "SLOT_DEPT_MGR", "SLOT_BOSS"],
            content=(
                "安全库存水位公式：安全水位 = 日均销量 * 备货周期天数 * 1.5；"
                "当实时可用库存 < 安全水位时，触发向采购部 SLOT_PROCURE_01 自动派发紧急补货单。"
            ),
        ),
        CapabilityBall(
            ball_id="BALL_DATA_BULK_DISCOUNT_MATRIX",
            ball_type="DATA",
            title="大宗B2B阶梯折扣矩阵规范",
            domain_tags=["报价", "折扣", "大客户"],
            sensitivity_level=2,
            owner_slot_ids=["SLOT_FOLLOWUP_01", "SLOT_FOLLOWUP_02", "SLOT_LEADER_01", "SLOT_DEPT_MGR"],
            content=(
                "企业集采阶梯折扣：10件以内无折扣(1.0)；10~49件享 9.5 折；50~99件享 9.0 折；"
                "100件及以上享 8.5 折（低于8.5折须触发基层组长高压线审批）。"
            ),
        ),
        CapabilityBall(
            ball_id="BALL_SKILL_WMS_WAVE_LOCK",
            ball_type="SKILL",
            title="多仓波次拣货与自动锁库 SOP",
            domain_tags=["仓储", "物流", "库存"],
            sensitivity_level=2,
            owner_slot_ids=["SLOT_WMS_01", "SLOT_LOGISTICS_01", "SLOT_FOLLOWUP_01", "SLOT_FOLLOWUP_02"],
            content="大客户订单确认税号与收货仓后，自动锁定对应批次序列号并生成干线物流预约单。",
        ),
        CapabilityBall(
            ball_id="BALL_SKILL_QA_AQL_INSPECT",
            ball_type="SKILL",
            title="出厂批次 AQL 2.5 抽检放行标准",
            domain_tags=["质检", "供应链", "产研"],
            sensitivity_level=2,
            owner_slot_ids=["SLOT_QA_01", "SLOT_PROCURE_01", "SLOT_WMS_01"],
            content="大宗出库前执行气密性与升降电机 5000 次疲劳抽检，合格率 100% 方可签发质检放行码。",
        ),
        CapabilityBall(
            ball_id="BALL_AUTH_WMS_DISPATCH",
            ball_type="AUTHORITY",
            title="跨仓调拨与干线急件加急调度权",
            domain_tags=["仓储", "物流"],
            sensitivity_level=3,
            owner_slot_ids=["SLOT_WMS_01", "SLOT_LOGISTICS_01", "SLOT_DEPT_MGR"],
            content="允许张江仓调度员在单仓缺货时直接发起跨区调拨并指派干线专车。",
        ),
        CapabilityBall(
            ball_id="BALL_AUTH_PROCURE_REPLENISH",
            ball_type="AUTHORITY",
            title="核心零部件 10 万元内自动补货下单权",
            domain_tags=["采购", "供应链"],
            sensitivity_level=3,
            owner_slot_ids=["SLOT_PROCURE_01", "SLOT_BOSS"],
            content="当库存低于安全水位线时，允许采购工程师在授信额度内直接向认证代工厂下达排产单。",
        ),
        CapabilityBall(
            ball_id="BALL_REDLINE_BOM_SUPPLIER_SECRET",
            ball_type="REDLINE",
            title="核心电机供应商底价与BOM返点绝密红线",
            domain_tags=["采购", "机密成本", "底价"],
            sensitivity_level=5,
            owner_slot_ids=["SLOT_BOSS"],
            content="【供应链绝密】双电机升降柱模组代工返点协议与核心芯片BOM成本¥215/套，严禁跨部门查询或外传！",
            redline_keywords=["BOM成本", "供应商返点", "芯片底价", "电机采购底价"],
        ),
        CapabilityBall(
            ball_id="BALL_REDLINE_LEGAL_INDEMNITY",
            ball_type="REDLINE",
            title="无限连带责任与惩罚性违约金法务红线",
            domain_tags=["法务", "合规", "风控审批"],
            sensitivity_level=5,
            owner_slot_ids=["SLOT_LEGAL_BOX", "SLOT_BOSS"],
            content="严禁任何销售或客服在群聊或补充协议中承诺超过合同总额20%的违约赔偿或无限连带责任。",
            redline_keywords=["无限连带责任", "十倍赔偿承诺", "免除全部违约上限"],
        ),
    ]

    for b in extra_balls:
        particles.register_ball(b, record_to_vault=True)

    extra_slots = [
        UnitSlot(
            slot_id="SLOT_FOLLOWUP_02",
            slot_name="华南大客户跟单二号位",
            ball_ids=[
                "BALL_DATA_CATALOG_2026",
                "BALL_DATA_BULK_DISCOUNT_MATRIX",
                "BALL_SKILL_ORDER_CHECKLIST",
                "BALL_AUTH_FOLLOWUP_QUOTE",
            ],
            occupant_type="HUMAN",
            occupant_id="emp_zhou",
            rule_repetition_ratio=91.0,
            shadow_agreement_rate=92.0,
            replaceability_score=91.6,
        ),
        UnitSlot(
            slot_id="SLOT_WMS_01",
            slot_name="张江智能仓调度中心岗",
            ball_ids=[
                "BALL_DATA_CATALOG_2026",
                "BALL_DATA_WMS_SAFETY_STOCK",
                "BALL_SKILL_WMS_WAVE_LOCK",
                "BALL_AUTH_WMS_DISPATCH",
            ],
            occupant_type="HUMAN",
            occupant_id="wms_zhao",
            rule_repetition_ratio=84.0,
            shadow_agreement_rate=88.0,
            replaceability_score=86.4,
        ),
        UnitSlot(
            slot_id="SLOT_LOGISTICS_01",
            slot_name="干线物流与履约追踪岗",
            ball_ids=[
                "BALL_DATA_SHIPPING_RULE_DOC",
                "BALL_SKILL_WMS_WAVE_LOCK",
                "BALL_AUTH_WMS_DISPATCH",
            ],
            occupant_type="HUMAN",
            occupant_id="log_sun",
            rule_repetition_ratio=89.0,
            shadow_agreement_rate=90.0,
            replaceability_score=89.6,
        ),
        UnitSlot(
            slot_id="SLOT_PROCURE_01",
            slot_name="产研供应链核心采购岗",
            ball_ids=[
                "BALL_DATA_WMS_SAFETY_STOCK",
                "BALL_SKILL_QA_AQL_INSPECT",
                "BALL_AUTH_PROCURE_REPLENISH",
            ],
            occupant_type="HUMAN",
            occupant_id="proc_lin",
            rule_repetition_ratio=54.0,
            shadow_agreement_rate=60.0,
            replaceability_score=57.6,
        ),
        UnitSlot(
            slot_id="SLOT_QA_01",
            slot_name="质量工程 AQL 放行岗",
            ball_ids=["BALL_SKILL_QA_AQL_INSPECT"],
            occupant_type="HUMAN",
            occupant_id="qa_chen",
            rule_repetition_ratio=76.0,
            shadow_agreement_rate=82.0,
            replaceability_score=79.6,
        ),
        UnitSlot(
            slot_id="SLOT_LEGAL_BOX",
            slot_name="法务合规合同会签黑盒岗",
            ball_ids=["BALL_REDLINE_LEGAL_INDEMNITY"],
            occupant_type="HUMAN",
            occupant_id="leg_liu",
            rule_repetition_ratio=38.0,
            shadow_agreement_rate=35.0,
            replaceability_score=36.2,
        ),
        UnitSlot(
            slot_id="SLOT_HR_EVO",
            slot_name="组织进化与算力HRBP岗",
            ball_ids=["BALL_DATA_CATALOG_2026", "BALL_REDLINE_PII_COMPLIANCE"],
            occupant_type="HUMAN",
            occupant_id="hr_su",
            rule_repetition_ratio=30.0,
            shadow_agreement_rate=40.0,
            replaceability_score=36.0,
        ),
    ]
    for s in extra_slots:
        containers.register_slot(s)

    extra_profiles = [
        DualEmployeeProfile(
            user_id="emp_zhou",
            name="小周",
            title="华南大客户跟单专员",
            role_view="employee",
            slot_id="SLOT_FOLLOWUP_02",
            employee_view=EmployeeViewA(
                skill_tags=["大宗集采报价", "跨区锁库协同"],
                saved_hours=9.5,
                evolution_contributions=["集采阶梯折扣核验模板"],
                innovation_bonus=10.0,
            ),
            management_view=ManagementViewB(
                avg_latency_ms=340.0,
                rework_rate=0.02,
                boundary_probes=0,
                base_fulfillment_score=89.0,
                performance_score=round(89.0 - 0.35 * 91.6 + 10.0, 2),
            ),
        ),
        DualEmployeeProfile(
            user_id="wms_zhao",
            name="老赵",
            title="张江智能仓调度主管",
            role_view="leader",
            slot_id="SLOT_WMS_01",
            employee_view=EmployeeViewA(
                skill_tags=["波次锁库", "安全水位预警"],
                saved_hours=14.0,
                evolution_contributions=["安全库存自动预警公式"],
                innovation_bonus=18.0,
            ),
            management_view=ManagementViewB(
                avg_latency_ms=280.0,
                rework_rate=0.01,
                boundary_probes=0,
                base_fulfillment_score=92.0,
                performance_score=79.76,
            ),
        ),
        DualEmployeeProfile(
            user_id="log_sun",
            name="小孙",
            title="干线物流调度专员",
            role_view="employee",
            slot_id="SLOT_LOGISTICS_01",
            employee_view=EmployeeViewA(
                skill_tags=["干线配载", "异常签收处理"],
                saved_hours=7.5,
                evolution_contributions=[],
                innovation_bonus=0.0,
            ),
            management_view=ManagementViewB(
                avg_latency_ms=360.0,
                rework_rate=0.02,
                boundary_probes=0,
                base_fulfillment_score=85.0,
                performance_score=53.64,
            ),
        ),
        DualEmployeeProfile(
            user_id="proc_lin",
            name="林工",
            title="供应链核心采购工程师",
            role_view="leader",
            slot_id="SLOT_PROCURE_01",
            employee_view=EmployeeViewA(
                skill_tags=["BOM排产协同", "供应商交期锁定"],
                saved_hours=12.5,
                evolution_contributions=["紧急排产联动协议"],
                innovation_bonus=15.0,
            ),
            management_view=ManagementViewB(
                avg_latency_ms=420.0,
                rework_rate=0.01,
                boundary_probes=0,
                base_fulfillment_score=90.0,
                performance_score=84.84,
            ),
        ),
        DualEmployeeProfile(
            user_id="qa_chen",
            name="陈工",
            title="质量工程 AQL 检验专员",
            role_view="employee",
            slot_id="SLOT_QA_01",
            employee_view=EmployeeViewA(
                skill_tags=["AQL抽检", "疲劳寿命测试"],
                saved_hours=6.0,
                evolution_contributions=[],
                innovation_bonus=0.0,
            ),
            management_view=ManagementViewB(
                avg_latency_ms=310.0,
                rework_rate=0.0,
                boundary_probes=0,
                base_fulfillment_score=91.0,
                performance_score=63.14,
            ),
        ),
        DualEmployeeProfile(
            user_id="leg_liu",
            name="刘律",
            title="法务合规顾问（合同红线黑盒节点）",
            role_view="finance_tool",
            slot_id="SLOT_LEGAL_BOX",
            employee_view=EmployeeViewA(
                skill_tags=["非标条款审查", "违约上限把关"],
                saved_hours=10.0,
                evolution_contributions=["标准赔付免责契约"],
                innovation_bonus=12.0,
            ),
            management_view=ManagementViewB(
                avg_latency_ms=580.0,
                rework_rate=0.0,
                boundary_probes=0,
                base_fulfillment_score=93.0,
                performance_score=92.33,
            ),
        ),
        DualEmployeeProfile(
            user_id="hr_su",
            name="苏主管",
            title="组织进化与算力 HRBP",
            role_view="manager",
            slot_id="SLOT_HR_EVO",
            employee_view=EmployeeViewA(
                skill_tags=["人机师徒反转评估", "工匠奖金核算"],
                saved_hours=16.0,
                evolution_contributions=["双面反推绩效模型"],
                innovation_bonus=20.0,
            ),
            management_view=ManagementViewB(
                avg_latency_ms=390.0,
                rework_rate=0.0,
                boundary_probes=0,
                base_fulfillment_score=92.0,
                performance_score=99.4,
            ),
        ),
    ]
    for p in extra_profiles:
        containers.register_profile(p)

    extra_nodes = [
        SpiderNode(
            node_id="node_aspect_supply",
            label="【智能仓储与供应链域】分面中枢",
            node_type="ASPECT_NODE",
            parent_id="node_board_root",
            subtree_root_id="subtree_supply",
            slot_id="SLOT_DEPT_MGR",
            domain_tags=["仓储", "库存", "供应链", "采购"],
            status="ACTIVE",
            active_load=2,
        ),
        SpiderNode(
            node_id="node_worker_zhou",
            label="华南跟单二号位 (小周 / 集采蜘蛛)",
            node_type="WORKER_SLOT",
            parent_id="node_aspect_quote",
            subtree_root_id="subtree_quote",
            slot_id="SLOT_FOLLOWUP_02",
            domain_tags=["报价", "折扣", "大客户"],
            status="ACTIVE",
            active_load=1,
        ),
        SpiderNode(
            node_id="node_worker_wms",
            label="张江智能仓调度 (老赵 / 锁库蜘蛛)",
            node_type="WORKER_SLOT",
            parent_id="node_aspect_supply",
            subtree_root_id="subtree_supply",
            slot_id="SLOT_WMS_01",
            domain_tags=["仓储", "库存"],
            status="ACTIVE",
            active_load=2,
        ),
        SpiderNode(
            node_id="node_worker_procure",
            label="核心供应链采购 (林工 / 补货蜘蛛)",
            node_type="WORKER_SLOT",
            parent_id="node_aspect_supply",
            subtree_root_id="subtree_supply",
            slot_id="SLOT_PROCURE_01",
            domain_tags=["采购", "供应链"],
            status="ACTIVE",
            active_load=1,
        ),
        SpiderNode(
            node_id="node_worker_logistics",
            label="干线物流配载 (小孙 / 履约蜘蛛)",
            node_type="WORKER_SLOT",
            parent_id="node_aspect_fulfill",
            subtree_root_id="subtree_fulfill",
            slot_id="SLOT_LOGISTICS_01",
            domain_tags=["物流", "运费"],
            status="ACTIVE",
            active_load=1,
        ),
        SpiderNode(
            node_id="node_blackbox_legal",
            label="法务合规会签黑盒 API (刘律)",
            node_type="BLACKBOX_HUMAN",
            parent_id="node_aspect_fulfill",
            subtree_root_id="subtree_fulfill",
            slot_id="SLOT_LEGAL_BOX",
            domain_tags=["法务", "合规"],
            status="DEHYDRATED",
            active_load=0,
        ),
    ]
    for node in extra_nodes:
        await hot_store.upsert_node(node)

    supply_snap = await hot_store.export_subtree_state("subtree_supply")
    vault.seal_snapshot("subtree_supply", "SLOT_DEPT_MGR", supply_snap, scope="LOCAL")

    # 封存阶梯折扣与安全库存黄金测试样本
    discount_cases = [
        ({"quantity": 5, "unit_price": 1000.0}, 5000.0),
        ({"quantity": 10, "unit_price": 1000.0}, 9500.0),
        ({"quantity": 20, "unit_price": 500.0}, "9500.00元"),
        ({"quantity": 50, "unit_price": 200.0}, 9000.0),
        ({"quantity": 100, "unit_price": 100.0}, "¥8500.00"),
        ({"quantity": 120, "unit_price": 100.0}, 10200.0),
    ]
    for idx, (inp, expected) in enumerate(discount_cases, start=1):
        vault.append_event(
            event_kind="GOLDEN_BENCHMARK_SEALED",
            subtree_root_id="subtree_quote",
            actor_slot_id="SLOT_FOLLOWUP_02",
            payload={
                "case_id": f"HIST_DISC_{idx:02d}",
                "domain_tags": ["折扣", "集采"],
                "input_payload": inp,
                "expected_output": expected,
            },
        )

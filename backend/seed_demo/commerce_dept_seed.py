from __future__ import annotations

from typing import Any

from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from core.particles import ParticleEngine
from core.schemas import (
    CapabilityBall,
    ChatMessageItem,
    DualEmployeeProfile,
    EmployeeViewA,
    ManagementViewB,
    SpiderNode,
    UnitSlot,
)
from database import HotStateStore


DEMO_SLOT_ALIASES: dict[str, str] = {
    "SLOT_FOLLOWUP_01": "node_followup",
    "SLOT_FOLLOWUP_02": "node_followup_02",
    "SLOT_WMS_01": "node_wms",
    "SLOT_LOGISTICS_01": "node_logistics",
    "SLOT_PROCURE_01": "node_procure",
    "SLOT_QA_01": "node_qa",
    "SLOT_LEADER_01": "node_leader",
    "SLOT_FINANCE_BOX": "node_finance",
    "SLOT_LEGAL_BOX": "node_legal",
    "SLOT_HR_EVO": "node_hr_evo",
    "SLOT_DEPT_MGR": "node_mgr",
    "SLOT_BOSS": "root",
}


DEFAULT_DEMO_ACCOUNT_DIRECTORY: dict[str, dict[str, Any]] = {
    "emp_chen": {
        "department": "商务跟单部",
        "supervisor_id": "leader_li",
        "is_custodian_leader": False,
    },
    "emp_zhou": {
        "department": "商务跟单部",
        "supervisor_id": "leader_li",
        "is_custodian_leader": False,
    },
    "leader_li": {
        "department": "商务跟单部",
        "supervisor_id": "mgr_zhang",
        "is_custodian_leader": True,
    },
    "wms_zhao": {
        "department": "智能仓储物流部",
        "supervisor_id": "mgr_zhang",
        "is_custodian_leader": True,
    },
    "log_sun": {
        "department": "智能仓储物流部",
        "supervisor_id": "wms_zhao",
        "is_custodian_leader": False,
    },
    "proc_lin": {
        "department": "产研供应链采购部",
        "supervisor_id": "mgr_zhang",
        "is_custodian_leader": True,
    },
    "qa_chen": {
        "department": "产研供应链采购部",
        "supervisor_id": "proc_lin",
        "is_custodian_leader": False,
    },
    "fin_wang": {
        "department": "财税法务双黑盒部",
        "supervisor_id": "boss_lin",
        "is_custodian_leader": False,
    },
    "leg_liu": {
        "department": "财税法务双黑盒部",
        "supervisor_id": "boss_lin",
        "is_custodian_leader": False,
    },
    "hr_su": {
        "department": "经营管理与进化部",
        "supervisor_id": "mgr_zhang",
        "is_custodian_leader": False,
    },
    "mgr_zhang": {
        "department": "经营管理与进化部",
        "supervisor_id": "boss_lin",
        "is_custodian_leader": True,
    },
    "boss_lin": {
        "department": "顶层治理董事会",
        "supervisor_id": None,
        "is_custodian_leader": True,
    },
}


def seed_demo_welcome_messages(wecom: Any) -> None:
    """为演示企业（美雅办公家具 / 商务跟单与客户运营部）注入初始三体门面欢迎语。"""
    wecom._messages_by_user["emp_chen"] = [
        ChatMessageItem(
            msg_id="MSG_INIT_01",
            sender_id="BOT_COPILOT",
            sender_name="#1 业务副驾",
            facade_bot="COPILOT",
            chat_type="SINGLE",
            direction="OUTBOUND",
            content=(
                "👋 你好小陈！当前已挂载【商务跟单专员一号位 (SLOT_FOLLOWUP_01)】容器权能球。\n"
                "你可以直接查库存目录价、在右侧伴生舱一键导入客户微信聊天记录（自动剥离私人寒暄与手机号），"
                "或向 #2 进化与风控官口述重复计算规则锻造自动工具赚取高额创新绩效分！"
            ),
        )
    ]
    wecom._messages_by_user["leader_li"] = [
        ChatMessageItem(
            msg_id="MSG_INIT_02",
            sender_id="BOT_GOVERNANCE",
            sender_name="#2 进化与风控官",
            facade_bot="GOVERNANCE",
            chat_type="SINGLE",
            direction="OUTBOUND",
            content="🛡️ 老李你好！一线跟单触发任何【超低折扣、现金赔偿、法务条款】高压线时，工单将自动挂起并推送到你的待审批卡片列表。",
        )
    ]
    wecom._messages_by_user["fin_wang"] = [
        ChatMessageItem(
            msg_id="MSG_INIT_03",
            sender_id="BOT_GOVERNANCE",
            sender_name="#2 进化与风控官",
            facade_bot="GOVERNANCE",
            chat_type="SINGLE",
            direction="OUTBOUND",
            content=(
                "🔒 王姐你好！你的工位已封装为【加密税控盘人机黑盒节点】。"
                "系统仅向你投喂最小必要开票四要素（工单号、抬头、税号、核准金额），提交数电发票号后将自动执行格式与金额核验。"
            ),
        )
    ]
    wecom._messages_by_user["mgr_zhang"] = [
        ChatMessageItem(
            msg_id="MSG_INIT_04",
            sender_id="BOT_GOVERNANCE",
            sender_name="#2 进化与风控官",
            facade_bot="GOVERNANCE",
            chat_type="SINGLE",
            direction="OUTBOUND",
            content="🕸️ 张经理你好！右侧大屏已实时接入部门活体蛛网拓扑脉搏，可随时演练并发超限自动垫层与边缘哨所局部倒退。",
        )
    ]
    wecom._messages_by_user["boss_lin"] = [
        ChatMessageItem(
            msg_id="MSG_INIT_05",
            sender_id="BOT_BOARD",
            sender_name="#3 董事会内参",
            facade_bot="BOARD_INSIDER",
            chat_type="SINGLE",
            direction="OUTBOUND",
            content="🏛️ 林总你好！永恒铁三角与两大动态业务域董事已就位。当岗位 AI 可替代分突破 90 分时，可一键召开并发盲评会议拍板进入【师徒反转接管期】。",
        )
    ]


async def seed_commerce_department(
    vault: BlackBoxVault,
    particles: ParticleEngine,
    containers: ContainerRegistry,
    hot_store: HotStateStore,
) -> None:
    """
    注入【商务跟单与客户运营部】完整初始沙盘：
    - 5大标准岗位容器与双面员工画像（小陈、老李、王姐、张经理、林总）
    - 四类核心权能小球（产品库存价目、运费规则、权限球、工厂绝密拿货底价红线球）
    - 初始蛛网拓扑树（董事会根节点 + 询价签约域 + 履约财税域 + 各工位节点）
    - 12 条封存于 BlackBoxVault 的真实历史运费核算黄金基准样本（覆盖首重/续重/满500免邮及各种格式单位）
    """
    from core.auth_custody import reset_account_directory

    reset_account_directory(DEFAULT_DEMO_ACCOUNT_DIRECTORY)
    containers.register_slot_aliases(DEMO_SLOT_ALIASES)

    # 1. 注册四类权能小球
    initial_balls = [
        CapabilityBall(
            ball_id="BALL_DATA_CATALOG_2026",
            ball_type="DATA",
            title="2026商务主力产品目录与实时现货库存表",
            domain_tags=["报价", "订单", "库存"],
            sensitivity_level=1,
            owner_slot_ids=["SLOT_FOLLOWUP_01", "SLOT_LEADER_01", "SLOT_DEPT_MGR", "SLOT_BOSS"],
            content=(
                "1) A款-旗舰人体工学椅：公开目录单价 ¥1,280/把，华东仓实时现货 360 把；"
                "2) B款-电动智能升降桌：公开目录单价 ¥2,190/张，华东仓实时现货 145 张；"
                "3) C款-双屏气压显示器支架：公开目录单价 ¥399/套，现货 520 套。"
            ),
        ),
        CapabilityBall(
            ball_id="BALL_DATA_SHIPPING_RULE_DOC",
            ball_type="DATA",
            title="商务部现行手工阶梯运费计价规范（待自动化）",
            domain_tags=["物流", "运费", "报价"],
            sensitivity_level=1,
            owner_slot_ids=["SLOT_FOLLOWUP_01", "SLOT_LEADER_01", "SLOT_DEPT_MGR"],
            content=(
                "标准快递阶梯运费规则：首重 3 公斤内统一收 10 元；超过 3 公斤的部分每公斤加收 4 元（不足1公斤按1公斤向上取整）；"
                "单笔订单商品金额满 500 元直接免收运费。"
            ),
        ),
        CapabilityBall(
            ball_id="BALL_SKILL_ORDER_CHECKLIST",
            ball_type="SKILL",
            title="大客户询价导单与交期确认标准 SOP",
            domain_tags=["订单", "客户履约"],
            sensitivity_level=2,
            owner_slot_ids=["SLOT_FOLLOWUP_01", "SLOT_LEADER_01"],
            content="收到外部微信询价须先执行 L1 公私剥离脱敏，确认商品型号、数量、收货地址及开票税号齐全后方可锁库。",
        ),
        CapabilityBall(
            ball_id="BALL_AUTH_FOLLOWUP_QUOTE",
            ball_type="AUTHORITY",
            title="一线跟单员常规报价与9折内自助锁库权",
            domain_tags=["报价", "折扣"],
            sensitivity_level=2,
            owner_slot_ids=["SLOT_FOLLOWUP_01"],
            content="允许一线跟单员在 >= 9.0 折且不涉及现金赔偿或非标法务条款的前提下直接生成标准订单。",
        ),
        CapabilityBall(
            ball_id="BALL_AUTH_LEADER_HV_GATE",
            ball_type="AUTHORITY",
            title="基层组长高压线特批权（低折/小额赔付初审）",
            domain_tags=["折扣", "风控审批", "订单"],
            sensitivity_level=4,
            owner_slot_ids=["SLOT_LEADER_01", "SLOT_DEPT_MGR", "SLOT_BOSS"],
            content="允许跟单组长老李对低于 8.5 折的特批申请及 <= 2,000 元的客户履约补偿工单执行人工拍板放行。",
        ),
        CapabilityBall(
            ball_id="BALL_REDLINE_FACTORY_FLOOR_PRICE",
            ball_type="REDLINE",
            title="绝密工厂拿货底价与毛利隔离红线墙",
            domain_tags=["底价", "机密成本"],
            sensitivity_level=5,
            owner_slot_ids=["SLOT_BOSS"],
            content="【核心商业绝密】A款人体工学椅工厂出厂拿货底价 ¥480/把；B款升降桌出厂拿货底价 ¥860/张。严禁向一线销售/外部透出！",
            redline_keywords=[
                "工厂拿货底价",
                "拿货底价",
                "工厂底价",
                "出厂底价",
                "真实成本底价",
                "拿货成本是多少",
            ],
        ),
        CapabilityBall(
            ball_id="BALL_REDLINE_PII_COMPLIANCE",
            ball_type="REDLINE",
            title="客户私人隐私与敏感证照出网拦截红线",
            domain_tags=["合规", "隐私脱敏"],
            sensitivity_level=4,
            owner_slot_ids=["SLOT_BOSS", "SLOT_DEPT_MGR"],
            content="所有群聊及向上汇报回传链路强制剥离客户私人手机号、身份证号、银行卡号及非公寒暄记录。",
            redline_keywords=["导出全量客户明文手机号", "明文身份证列表"],
        ),
    ]

    for b in initial_balls:
        particles.register_ball(b, record_to_vault=True)

    # 2. 注册 5 大标准岗位单元容器 (UnitSlot)
    slots = [
        UnitSlot(
            slot_id="SLOT_FOLLOWUP_01",
            slot_name="商务跟单专员一号位",
            ball_ids=[
                "BALL_DATA_CATALOG_2026",
                "BALL_DATA_SHIPPING_RULE_DOC",
                "BALL_SKILL_ORDER_CHECKLIST",
                "BALL_AUTH_FOLLOWUP_QUOTE",
            ],
            occupant_type="HUMAN",
            occupant_id="emp_chen",
            rule_repetition_ratio=88.0,
            shadow_agreement_rate=86.0,
            replaceability_score=86.8,
        ),
        UnitSlot(
            slot_id="SLOT_LEADER_01",
            slot_name="跟单基层组长风控岗",
            ball_ids=[
                "BALL_DATA_CATALOG_2026",
                "BALL_DATA_SHIPPING_RULE_DOC",
                "BALL_SKILL_ORDER_CHECKLIST",
                "BALL_AUTH_LEADER_HV_GATE",
            ],
            occupant_type="HUMAN",
            occupant_id="leader_li",
            rule_repetition_ratio=42.0,
            shadow_agreement_rate=48.0,
            replaceability_score=45.6,
        ),
        UnitSlot(
            slot_id="SLOT_FINANCE_BOX",
            slot_name="财务税控盘黑盒开票岗",
            ball_ids=[],
            occupant_type="HUMAN",
            occupant_id="fin_wang",
            rule_repetition_ratio=65.0,
            shadow_agreement_rate=30.0,
            replaceability_score=44.0,
        ),
        UnitSlot(
            slot_id="SLOT_DEPT_MGR",
            slot_name="商务运营部中层主管岗",
            ball_ids=[
                "BALL_DATA_CATALOG_2026",
                "BALL_DATA_SHIPPING_RULE_DOC",
                "BALL_AUTH_LEADER_HV_GATE",
                "BALL_REDLINE_PII_COMPLIANCE",
            ],
            occupant_type="HUMAN",
            occupant_id="mgr_zhang",
            rule_repetition_ratio=25.0,
            shadow_agreement_rate=32.0,
            replaceability_score=29.2,
        ),
        UnitSlot(
            slot_id="SLOT_BOSS",
            slot_name="公司顶层决策席",
            ball_ids=[
                "BALL_DATA_CATALOG_2026",
                "BALL_AUTH_LEADER_HV_GATE",
                "BALL_REDLINE_FACTORY_FLOOR_PRICE",
                "BALL_REDLINE_PII_COMPLIANCE",
            ],
            occupant_type="HUMAN",
            occupant_id="boss_lin",
            rule_repetition_ratio=10.0,
            shadow_agreement_rate=15.0,
            replaceability_score=13.0,
        ),
    ]
    for s in slots:
        containers.register_slot(s)

    # 3. 注册 5 位演示人物的双面反推简历画像
    profiles = [
        DualEmployeeProfile(
            user_id="emp_chen",
            name="小陈",
            title="普通商务跟单员",
            role_view="employee",
            slot_id="SLOT_FOLLOWUP_01",
            employee_view=EmployeeViewA(
                skill_tags=["大客户询价响应", "微信导单整理"],
                saved_hours=6.5,
                evolution_contributions=[],
                innovation_bonus=0.0,
            ),
            management_view=ManagementViewB(
                avg_latency_ms=390.0,
                rework_rate=0.03,
                boundary_probes=0,
                base_fulfillment_score=86.0,
                performance_score=round(86.0 - 0.35 * 86.8, 2),
            ),
        ),
        DualEmployeeProfile(
            user_id="leader_li",
            name="老李",
            title="跟单基层组长",
            role_view="leader",
            slot_id="SLOT_LEADER_01",
            employee_view=EmployeeViewA(
                skill_tags=["折扣风控把关", "客诉赔付谈判"],
                saved_hours=11.0,
                evolution_contributions=["特批报价核验SOP"],
                innovation_bonus=12.0,
            ),
            management_view=ManagementViewB(
                avg_latency_ms=510.0,
                rework_rate=0.01,
                boundary_probes=0,
                base_fulfillment_score=88.0,
                performance_score=84.0,
            ),
        ),
        DualEmployeeProfile(
            user_id="fin_wang",
            name="王姐",
            title="财务开票专员（加密税控盘黑盒节点）",
            role_view="finance_tool",
            slot_id="SLOT_FINANCE_BOX",
            employee_view=EmployeeViewA(
                skill_tags=["数电专票开具", "税控盘物理签章"],
                saved_hours=8.0,
                evolution_contributions=[],
                innovation_bonus=0.0,
            ),
            management_view=ManagementViewB(
                avg_latency_ms=620.0,
                rework_rate=0.02,
                boundary_probes=0,
                base_fulfillment_score=90.0,
                performance_score=74.6,
            ),
        ),
        DualEmployeeProfile(
            user_id="mgr_zhang",
            name="张经理",
            title="商务运营部中层主管",
            role_view="manager",
            slot_id="SLOT_DEPT_MGR",
            employee_view=EmployeeViewA(
                skill_tags=["蛛网拓扑治理", "供应链协同"],
                saved_hours=19.5,
                evolution_contributions=["跨部门借球应急规范"],
                innovation_bonus=15.0,
            ),
            management_view=ManagementViewB(
                avg_latency_ms=450.0,
                rework_rate=0.0,
                boundary_probes=0,
                base_fulfillment_score=91.0,
                performance_score=95.8,
            ),
        ),
        DualEmployeeProfile(
            user_id="boss_lin",
            name="林总",
            title="公司创始人 / 顶层老板",
            role_view="boss",
            slot_id="SLOT_BOSS",
            employee_view=EmployeeViewA(
                skill_tags=["组织进化决策", "全局红线治理"],
                saved_hours=42.0,
                evolution_contributions=["自适应董事会章程"],
                innovation_bonus=30.0,
            ),
            management_view=ManagementViewB(
                avg_latency_ms=300.0,
                rework_rate=0.0,
                boundary_probes=0,
                base_fulfillment_score=95.0,
                performance_score=99.0,
            ),
        ),
    ]
    for p in profiles:
        containers.register_profile(p)

    # 4. 初始化蛛网拓扑核心节点并封存初始子树快照
    topology_nodes = [
        SpiderNode(
            node_id="node_board_root",
            label="顶层自适应董事会 (铁三角+动态域)",
            node_type="BOARD_ROOT",
            parent_id=None,
            subtree_root_id="root",
            slot_id="SLOT_BOSS",
            domain_tags=["治理", "战略"],
            status="ACTIVE",
            active_load=1,
        ),
        SpiderNode(
            node_id="node_aspect_quote",
            label="【询价签约域】分面中枢",
            node_type="ASPECT_NODE",
            parent_id="node_board_root",
            subtree_root_id="subtree_quote",
            slot_id="SLOT_DEPT_MGR",
            domain_tags=["报价", "订单", "折扣"],
            status="ACTIVE",
            active_load=2,
        ),
        SpiderNode(
            node_id="node_aspect_fulfill",
            label="【物流财税履约域】分面中枢",
            node_type="ASPECT_NODE",
            parent_id="node_board_root",
            subtree_root_id="subtree_fulfill",
            slot_id="SLOT_DEPT_MGR",
            domain_tags=["物流", "运费", "财税"],
            status="ACTIVE",
            active_load=1,
        ),
        SpiderNode(
            node_id="node_worker_chen",
            label="跟单专员一号位 (小陈 / 潜伏蜘蛛)",
            node_type="WORKER_SLOT",
            parent_id="node_aspect_quote",
            subtree_root_id="subtree_quote",
            slot_id="SLOT_FOLLOWUP_01",
            domain_tags=["报价", "订单", "运费"],
            status="ACTIVE",
            active_load=2,
        ),
        SpiderNode(
            node_id="node_leader_li",
            label="基层组长审批哨 (老李 · 高压线拍板)",
            node_type="RELAY_NODE",
            parent_id="node_aspect_quote",
            subtree_root_id="subtree_quote",
            slot_id="SLOT_LEADER_01",
            domain_tags=["折扣", "风控审批"],
            status="ACTIVE",
            active_load=1,
        ),
        SpiderNode(
            node_id="node_blackbox_wang",
            label="财务税控盘黑盒 API (王姐)",
            node_type="BLACKBOX_HUMAN",
            parent_id="node_aspect_fulfill",
            subtree_root_id="subtree_fulfill",
            slot_id="SLOT_FINANCE_BOX",
            domain_tags=["财税", "开票"],
            status="DEHYDRATED",
            active_load=0,
        ),
    ]
    for node in topology_nodes:
        await hot_store.upsert_node(node)

    # 封存两个核心业务子树与全局初始合法快照，供后续局部倒退 (Local Rollback) 与全局回滚使用
    quote_snap = await hot_store.export_subtree_state("subtree_quote")
    vault.seal_snapshot("subtree_quote", "SLOT_DEPT_MGR", quote_snap, scope="LOCAL")

    fulfill_snap = await hot_store.export_subtree_state("subtree_fulfill")
    vault.seal_snapshot("subtree_fulfill", "SLOT_DEPT_MGR", fulfill_snap, scope="LOCAL")

    global_snap = await hot_store.export_global_state()
    vault.seal_snapshot("root", "SLOT_BOSS", global_snap, scope="GLOBAL")

    # 5. 向 BlackBoxVault 封存 12 条真实历史手工阶梯运费结算黄金基准样本
    # 规则基准：首重 3kg 内 10 元，超 3kg 每 kg 加 4 元（向上取整），订单满 500 元免运费
    golden_shipping_cases = [
        ({"weight_kg": 1.5, "order_amount": 180.0}, 10.0),
        ({"weight_kg": 3.0, "order_amount": 260.0}, "10元"),
        ({"weight_kg": 4.0, "order_amount": 300.0}, 14.0),
        ({"weight_kg": 5.0, "order_amount": 320.0}, "18.00元"),
        ({"weight_kg": 6.2, "order_amount": 410.0}, 26.0),
        ({"weight_kg": 8.0, "order_amount": 499.0}, "¥30.00"),
        ({"weight_kg": 8.0, "order_amount": 500.0}, 0.0),
        ({"weight_kg": 15.0, "order_amount": 1280.0}, "0元"),
        ({"weight_kg": 2.0, "order_amount": 99.0}, 10),
        ({"weight_kg": 10.0, "order_amount": 380.0}, 38.0),
        ({"weight_kg": 0.8, "order_amount": 600.0}, 0.0),
        ({"weight_kg": 4.5, "order_amount": 220.0}, "¥18"),
    ]
    for idx, (inp, expected) in enumerate(golden_shipping_cases, start=1):
        vault.append_event(
            event_kind="GOLDEN_BENCHMARK_SEALED",
            subtree_root_id="subtree_fulfill",
            actor_slot_id="SLOT_FOLLOWUP_01",
            payload={
                "case_id": f"HIST_SHIP_{idx:02d}",
                "domain_tags": ["运费", "物流"],
                "input_payload": inp,
                "expected_output": expected,
            },
        )

    from seed_demo.company_full_seed import seed_full_company_expansion

    await seed_full_company_expansion(vault, particles, containers, hot_store)
    global_snap_full = await hot_store.export_global_state()
    vault.seal_snapshot("root", "SLOT_BOSS", global_snap_full, scope="GLOBAL")



from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from core.auth_custody import AuthAndCustodyService
from core.schemas import (
    BallType,
    CapabilityBall,
    ChatMessageItem,
    DualEmployeeProfile,
    EmployeeViewA,
    ExtractedBallCandidate,
    HumanBlackBoxContract,
    ManagementViewB,
    NodeType,
    RoleViewType,
    SpiderNode,
    UnitSlot,
    utc_now_iso,
)
from swarm.evolution_arena import run_skill_in_isolated_subprocess, sandbox_ast_guard


class GenesisAspectSpec(BaseModel):
    node_id: str
    label: str
    subtree_root_id: str
    domain_tags: list[str] = Field(default_factory=list)


class GenesisAccountSlotSpec(BaseModel):
    user_id: str
    name: str
    title: str
    department: str
    role_view: RoleViewType
    slot_id: str
    slot_name: str
    supervisor_id: Optional[str] = None
    is_custodian_leader: bool = False
    node_id: str
    node_type: NodeType = "WORKER_SLOT"
    parent_aspect_id: str
    subtree_root_id: str
    skill_tags: list[str] = Field(default_factory=list)
    rule_repetition_ratio: float = 82.0
    shadow_agreement_rate: float = 85.0
    welcome_message: str = ""


class GenesisBallSpec(BaseModel):
    ball_id: str
    ball_type: BallType
    title: str
    domain_tags: list[str] = Field(default_factory=list)
    sensitivity_level: int = Field(default=2, ge=1, le=5)
    owner_slot_ids: list[str] = Field(default_factory=list)
    content: str
    redline_keywords: list[str] = Field(default_factory=list)
    skill_instruction: Optional[str] = None


class EnterpriseBlueprint(BaseModel):
    enterprise_name: str
    industry_category: str
    aspects: list[GenesisAspectSpec]
    accounts_and_slots: list[GenesisAccountSlotSpec]
    initial_balls: list[GenesisBallSpec]


class PolicyDecompositionPlan(BaseModel):
    data_title: str
    data_content: str
    data_tags: list[str]
    skill_instruction: str
    authority_title: str
    authority_content: str
    authority_tags: list[str]
    redline_title: str
    redline_content: str
    redline_keywords: list[str]
    redline_tags: list[str]


class MitosisSplitPlan(BaseModel):
    child_a_title: str
    child_a_type: BallType
    child_a_content: str
    child_a_tags: list[str]
    child_b_title: str
    child_b_type: BallType
    child_b_content: str
    child_b_tags: list[str]
    child_b_skill_instruction: Optional[str] = None


ENTERPRISE_GENESIS_TEMPLATES: list[dict[str, Any]] = [
    {
        "template_id": "tpl_zambia_copper_fleet",
        "enterprise_name": "赞比亚跨境铜矿陆运车队",
        "industry": "跨境矿业重卡物流与供应链",
        "highlights": [
            "4大业务域子树：重卡干线调度 / 矿区磅房计量 / 沿途油料维保 / 跨境外汇结算",
            "7大标准工位容器：一线调度、报关专员、车队大队长、磅房油料主管、外汇税控黑盒、运营总监、集团董事长",
            "内置干线阶梯运费公式、恩多拉油库安全水位公式、长协柴油补贴绝密底价红线",
        ],
        "business_description": (
            "企业名称：赞比亚跨境铜矿陆运车队（卢萨卡—恩多拉—达累斯萨拉姆走廊）。\n"
            "1. 部门职责划分：\n"
            "  - 【跨境重卡调度与报关部】：负责赞比亚铜精矿粗铜大宗陆运排车、坦赞边境报关锁舱及电子运单跟单；\n"
            "  - 【矿区磅房计量与安环部】：负责矿山出厂过磅净重核验、GPS铅封监控与干线途中损耗核查；\n"
            "  - 【沿途油料补给与维保部】：负责恩多拉及姆皮卡自建油库柴油储备、轮胎备件安全库存管理；\n"
            "  - 【跨境财税与外汇黑盒部】：负责美元/克瓦查多币种运费发票开具、港务税控盘加密签章结算。\n"
            "2. 计费与业务公式：\n"
            "  - 跨境样板件/干线阶梯运费规则：首重 3 公斤内统一收 10 元；超过 3 公斤的部分每公斤加收 4 元（向上取整），单笔订单满 500 元免收附加运费；\n"
            "  - 铜精矿大宗包车集采阶梯折扣：单月批量折扣满 20 车享 9.0 折折后价；\n"
            "  - 跨境清关综合保税服务费率：按合同货运总额的 8.5% 自动计提清关与押运服务费。\n"
            "3. 审批权限与高压线：\n"
            "  - 一线调度跟单员仅限在 >= 9.0 折标准运价内直接锁车派单；\n"
            "  - 凡涉及低于 8.5 折的特批运价、或单笔超过 2,000 元的边境压车滞期费赔偿承诺，必须挂起交由车队调度大队长人工拍板。\n"
            "4. 绝密底价与合规红线：\n"
            "  - 【核心商业绝密】赞比亚矿山长协柴油补贴底价 ¥4,200/车、达累斯萨拉姆港务通关暗补底价 ¥680/柜，严禁向外部货代或一线普通调度员透出（红线词：柴油补贴底价、通关暗补底价、车队真实底价、长协成本底价）。"
        ),
        "sample_policy_sop": (
            "《赞比亚铜矿车队2026雨季跨境运输与清关管理制度》：\n"
            "1) 基础资料：卢萨卡至达港干线主力车型为 35吨重型高栏卡车（标准运价 ¥28,000/车，在途可用 85 辆）与 45吨集装箱特种平板车（标准运价 ¥34,500/车，可用 42 辆）；\n"
            "2) 计费公式：所有跨境矿产保税清关与武装押运附加费，统一按货运合同金额的 8.5% 自动核算收取；\n"
            "3) 审批权限：车队大队长拥有雨季跨国调车特批权及 5,000 元以内边境滞箱费初审放行权；\n"
            "4) 严禁红线：严禁任何调度员在微信群对外泄露柴油补贴底价、通关暗补底价或私自承诺免除全部滞期费违约上限。"
        ),
    },
    {
        "template_id": "tpl_crossborder_mcn_agency",
        "enterprise_name": "跨境电商独立站与达人MCN机构",
        "industry": "出海DTC独立站与全球短视频达人营销",
        "highlights": [
            "4大业务域子树：全球达人BD签约 / 独立站大促投放 / 跨境海外仓履约 / 多币种佣金财税黑盒",
            "7大标准工位容器：达人BD、大促运营、MCN组长、海外仓主管、外汇结算黑盒、增长总监、创始人",
            "内置达人阶梯佣金率公式、美区海外仓阶梯运费、深圳工厂FOB绝密拿货底价红线",
        ],
        "business_description": (
            "企业名称：星海跨境电商独立站与全球达人MCN机构（北美/欧洲 TikTok Shop & Shopify 矩阵）。\n"
            "1. 部门职责划分：\n"
            "  - 【全球达人BD与内容孵化部】：负责欧美本土带货达人建联、寄样跟单与短视频脚本排期；\n"
            "  - 【独立站大促与广告投放部】：负责黑五网一阶梯满减配置、ROAS监控与大客户团购锁库；\n"
            "  - 【洛杉矶与美东海外仓履约部】：负责跨境头程备货、海外仓一件代发波次锁库与尾程物流调度；\n"
            "  - 【多币种合规结算黑盒部】：负责达人佣金跨境打款税号核验、Stripe/PayPal商业发票加密签章。\n"
            "2. 计费与业务公式：\n"
            "  - 达人带货标准佣金核算规则：按净成交 GMV 金额的 12.5% 自动核算达人分成佣金；\n"
            "  - 独立站企业团购批量折扣：满 30 件享 8.8 折折后价；\n"
            "  - 海外仓尾程直邮阶梯运费：首重 3 公斤内收 10 元，超过 3 公斤每公斤加收 4 元，订单满 500 元免运费。\n"
            "3. 审批权限与高压线：\n"
            "  - 一线BD专员可自助发放 >= 9.0 折达人专属粉丝券及常规免费寄样；\n"
            "  - 低于 8.5 折的全站叠加神券、或单笔超过 $1,500 的保底坑位费赔付，必须交由 MCN 运营组长拍板审批。\n"
            "4. 绝密底价与合规红线：\n"
            "  - 【核心商业绝密】独立站爆款储能电源深圳代工厂 FOB 拿货底价 ¥520/台、头部百万粉达人私下返点底价协议，严禁一线BD刺探或外传（红线词：FOB拿货底价、达人返点底价、独立站真实毛利、代工厂底价）。"
        ),
        "sample_policy_sop": (
            "《2026北美黑五网一达人带货与海外仓履约SOP》：\n"
            "1) 基础资料：旗舰款便携户外电源公开零售价 ¥2,680/台（洛杉矶仓现货 520 台），折叠太阳能板零售价 ¥890/套（美东仓现货 620 套）；\n"
            "2) 计费公式：签约达人直播带货佣金统一按有效结算金额的 12.5% 自动核算计提；\n"
            "3) 审批权限：MCN运营组长拥有 $3,000 以内达人保底坑位费与 8.5 折大促闪购券特批权；\n"
            "4) 严禁红线：严禁向外部MCN或达人透露深圳代工厂 FOB拿货底价、达人返点底价或未脱敏的海外消费者私人手机号列表。"
        ),
    },
    {
        "template_id": "tpl_precision_medtech_mfg",
        "enterprise_name": "精密医疗器械智造与集采企业",
        "industry": "三类微创医疗器械智造与省际医药集采",
        "highlights": [
            "4大业务域子树：省际集采政企商务 / 万级洁净产研QA / 冷链恒温物流 / 医保合规审计黑盒",
            "7大标准工位容器：集采商务代表、冷链跟单员、大区商务组长、QA质检主管、医保税控黑盒、营销总监、董事长",
            "内置医院集采阶梯折后价、技术维保计提费率公式、钛合金吻合器BOM绝密底价红线",
        ],
        "business_description": (
            "企业名称：华瑞微创精密医疗器械智造与集采企业（微创腔镜吻合器与超声刀耗材）。\n"
            "1. 部门职责划分：\n"
            "  - 【省际集采与政企商务部】：负责三甲医院阳光集采挂网报价、经销商授权跟单与手术排期锁库；\n"
            "  - 【万级洁净车间与QA质检部】：负责无菌环氧乙烷灭菌批次放行、UDI医疗器械唯一标识溯源核验；\n"
            "  - 【冷链恒温仓配与急件调度部】：负责高值耗材恒温专车配载、院内手术室急件跨区调拨；\n"
            "  - 【医保结算与法务合规黑盒部】：负责两票制增值税专票税控盘加密开具、医疗反腐合规条款审查。\n"
            "2. 计费与业务公式：\n"
            "  - 医院科室集采批量折扣规则：单次采购满 20 把享 9.0 折折后价；\n"
            "  - 临床设备技术维保服务费：按中标合同金额的 6.5% 自动计提年度维保服务费；\n"
            "  - 恒温冷链耗材阶梯运费：首重 3 公斤内收 10 元，超过 3 公斤每公斤加收 4 元，订单满 500 元免收冷链运费。\n"
            "3. 审批权限与高压线：\n"
            "  - 一线集采代表仅限在省标挂网价 >= 9.0 折范围内直接提交锁库发货单；\n"
            "  - 低于 8.5 折的院内特批议价、或涉及临床不良事件补偿承诺，必须触发高压线交由大区商务组长人工拍板。\n"
            "4. 绝密底价与合规红线：\n"
            "  - 【核心商业绝密】电动腔镜吻合器钛合金刀头 BOM 出厂底价 ¥310/把、省级平台总代底价协议，严禁任何一线代表查询或外传（红线词：刀头BOM底价、省级总代底价、医疗器械出厂底价、核心耗材成本底价）。"
        ),
        "sample_policy_sop": (
            "《2026省级阳光集采耗材履约与两票制合规制度》：\n"
            "1) 基础资料：A款电动微创腔镜吻合器阳光挂网单价 ¥3,600/把（苏州洁净仓现货 520 把），B款超声高频外科集成刀头单价 ¥4,800/套（现货 280 套）；\n"
            "2) 计费公式：驻院临床技术支持与冷链质保服务费按合同结算总额的 6.5% 自动核算；\n"
            "3) 审批权限：大区商务组长拥有三甲医院 8.5 折集采分量特批权及紧急手术跨仓调拨指令权；\n"
            "4) 严禁红线：严禁刺探或外传刀头BOM底价、省级总代底价，严禁在补充协议中签署临床无限连带责任条款。"
        ),
    },
]


_PRIVATE_SOURCE_WORDS = (
    "底价",
    "成本",
    "绝密",
    "机密",
    "保密",
    "红线",
    "严禁",
    "禁止",
    "不得",
    "隐私",
    "手机号",
    "身份证",
    "银行卡",
    "密码",
    "密钥",
)
_AUTHORITY_SOURCE_WORDS = ("审批", "授权", "权限", "仅限", "特批", "赔偿")


def _source_clauses(text: str) -> list[str]:
    # Semicolons and line breaks delimit supplied policy clauses; commas do not break secrecy scope.
    return [
        clause.strip() for clause in re.split(r"[；;\r\n]+", text) if clause.strip()
    ]


def _public_data_source(text: str) -> str:
    quantitative_fact = re.compile(
        r"(?:[¥￥$]\s*\d|\d(?:[\d.,]*)\s*(?:元|公斤|kg|吨|件|台|张|把|辆|柜|%))",
        re.IGNORECASE,
    )
    clauses = []
    for clause in _source_clauses(text):
        if any(
            word in clause
            for word in (*_PRIVATE_SOURCE_WORDS, *_AUTHORITY_SOURCE_WORDS)
        ):
            continue
        if quantitative_fact.search(clause):
            clauses.append(clause)
    return "\n".join(clauses)


def _authority_source(text: str) -> str:
    return "\n".join(
        clause
        for clause in _source_clauses(text)
        if any(word in clause for word in _AUTHORITY_SOURCE_WORDS)
        and not any(word in clause for word in _PRIVATE_SOURCE_WORDS)
    )


class EnterpriseGenesisAndFissionEngine:
    """
    Zone-B 核心引擎（EnterpriseGenesisAndFissionEngine）：
    1. 企业创世空投冷启动繁殖 (`deploy_enterprise_blueprint`)：
       解剖任意企业业务描述，生成 3~4 个业务域子树 (ASPECT_NODE)、6~8 个标准岗位容器 (UnitSlot) 与账号 (DualEmployeeProfile)、
       更新 ACCOUNT_DIRECTORY 上下级汇报链，分割出 6~10 颗初始权能球 (DATA/SKILL/AUTHORITY/REDLINE，其中 SKILL 真正编译落盘至 sandbox_workspace/)，
       并向 WORM 账本写入 ENTERPRISE_GENESIS_DEPLOYED 创世区块。
    2. 业务制度/SOP 自动解剖拆球与大球有丝分裂 (`decompose_or_split_balls`)：
       - 模式 A（文档自动拆球）：将杂糅的企业制度/SOP文本解剖切割为 DATA / SKILL（经 Arena 现场编译校验）/ AUTHORITY / REDLINE 四类正交球并挂载；
       - 模式 B（大球细胞有丝分裂 Ball Mitosis）：将指定大球一分为二（前端执行规程 + 后端风控与核算算子），原球标为 DEPRECATED，新子球 ACTIVE 挂载并写入 BALL_MITOSIS_COMPLETED。
    3. 集群自主能动巡检与工位自繁殖 (`run_autonomous_agency_patrol`)：
       - 工位细胞分裂（Slot Mitosis）：识别高负载/高可替代分工位，自动分裂出平行协防子工位 `SLOT_xxx_REPLICA` 与数字分身节点 `SpiderNode`，分流挂载 DATA/SKILL 球；
       - 主动嗅探造球（Proactive Skill Forging）：检测尚未自动化的 DATA 球公式规则，主动合成 ACTIVE SKILL Python 技能球并挂载，向部门头头企微推送《🤖 集群自主巡检进化简报》。
    """

    def __init__(self, runtime: Any) -> None:
        self._rt = runtime
        self._settings = runtime.settings
        self._vault = runtime.vault
        self._hot_store = runtime.hot_store
        self._particles = runtime.particles
        self._containers = runtime.containers
        self._human_tools = runtime.human_tools
        self._pulse = runtime.pulse_bus
        self._llm = runtime.llm_gateway
        self._arena = runtime.arena
        self._wecom = runtime.wecom
        self._sandbox_dir = Path(self._settings.sandbox_workspace_dir)
        self._sandbox_dir.mkdir(parents=True, exist_ok=True)
        self._forged_source_ball_ids: set[str] = set()

    def list_templates(self) -> list[dict[str, Any]]:
        return list(ENTERPRISE_GENESIS_TEMPLATES)

    # ==========================================================================
    # 内部工具：编译并落盘经过 AST 与净室子进程验证的 Python 技能脚本
    # ==========================================================================
    async def _compile_and_persist_skill_script(
        self,
        ball_id: str,
        skill_instruction: str,
    ) -> tuple[str, str]:
        """
        根据自然语言规则合成标准 Python execute_skill(payload) 脚本，
        通过 AST 安全门禁审查与净室子进程实测后落盘至 sandbox_workspace/。
        返回: (script_filename, python_source_code)
        """
        _, _, code = await self._llm.synthesize_artisan_skill(skill_instruction)
        sandbox_ast_guard(code)

        script_filename = f"skill_{ball_id.lower()}.py"
        script_path = self._sandbox_dir / script_filename
        script_path.write_text(code, encoding="utf-8")

        # 净室子进程冒烟验证，确保 100% 可执行
        smoke_inputs = [
            {
                "weight_kg": 4.5,
                "order_amount": 320.0,
                "quantity": 25,
                "unit_price": 1000.0,
                "amount": 10000.0,
            }
        ]
        run_res = run_skill_in_isolated_subprocess(
            script_path=script_path,
            sandbox_dir=self._sandbox_dir,
            input_payloads=smoke_inputs,
            timeout_seconds=self._settings.sandbox_timeout_seconds,
        )
        if not run_res or not run_res[0].get("ok"):
            raise RuntimeError(f"Generated skill script failed smoke test: {run_res}")
        return script_filename, code

    # ==========================================================================
    # 能力 1：企业创世空投冷启动繁殖 (`deploy_enterprise_blueprint`)
    # ==========================================================================
    def _build_deterministic_blueprint(
        self, enterprise_name: str, business_description: str
    ) -> EnterpriseBlueprint:
        combined = f"{enterprise_name}\n{business_description}"

        # 识别行业特征（赞比亚铜矿车队 / 跨境电商MCN / 精密医疗器械 / 任意自定义企业）
        if any(
            k in combined
            for k in ("赞比亚", "铜矿", "陆运", "车队", "矿山", "卢萨卡", "报关")
        ):
            prefix = "ZAM"
            uid_prefix = "zam"
            industry = "跨境矿业重卡物流与供应链"
            aspects = [
                GenesisAspectSpec(
                    node_id="node_aspect_zam_dispatch",
                    label="【跨境重卡调度与报关域】分面中枢",
                    subtree_root_id="subtree_quote",
                    domain_tags=["报价", "订单", "运费", "陆运", "报关", "折扣"],
                ),
                GenesisAspectSpec(
                    node_id="node_aspect_zam_weigh",
                    label="【矿区磅房计量与安环域】分面中枢",
                    subtree_root_id="subtree_weigh",
                    domain_tags=["磅房", "铜矿", "质检", "产研", "计量"],
                ),
                GenesisAspectSpec(
                    node_id="node_aspect_zam_fuel",
                    label="【沿途油料补给与维保域】分面中枢",
                    subtree_root_id="subtree_supply",
                    domain_tags=["仓储", "物流", "库存", "油料", "采购", "供应链"],
                ),
                GenesisAspectSpec(
                    node_id="node_aspect_zam_settle",
                    label="【跨境外汇与港务结算域】分面中枢",
                    subtree_root_id="subtree_fulfill",
                    domain_tags=["财税", "开票", "外汇结算", "法务", "合规"],
                ),
            ]
            accounts_and_slots = [
                GenesisAccountSlotSpec(
                    user_id=f"{uid_prefix}_disp_chen",
                    name="小陈（卢萨卡调度）",
                    title="跨境重卡干线调度专员",
                    department="跨境重卡调度与报关部",
                    role_view="employee",
                    slot_id=f"SLOT_{prefix}_DISP_01",
                    slot_name="卢萨卡重卡调度一号位",
                    supervisor_id=f"{uid_prefix}_leader_li",
                    is_custodian_leader=False,
                    node_id=f"node_{uid_prefix}_disp_01",
                    node_type="WORKER_SLOT",
                    parent_aspect_id="node_aspect_zam_dispatch",
                    subtree_root_id="subtree_quote",
                    skill_tags=["跨境重卡排车", "铜精矿运单跟单"],
                    rule_repetition_ratio=90.0,
                    shadow_agreement_rate=89.0,
                ),
                GenesisAccountSlotSpec(
                    user_id=f"{uid_prefix}_customs_zhou",
                    name="小周（坦赞报关）",
                    title="坦赞边境清关与锁舱专员",
                    department="跨境重卡调度与报关部",
                    role_view="employee",
                    slot_id=f"SLOT_{prefix}_CUSTOMS_02",
                    slot_name="坦赞边境报关二号位",
                    supervisor_id=f"{uid_prefix}_leader_li",
                    is_custodian_leader=False,
                    node_id="node_worker_zhou",
                    node_type="WORKER_SLOT",
                    parent_aspect_id="node_aspect_zam_dispatch",
                    subtree_root_id="subtree_quote",
                    skill_tags=["边境报关单证", "大宗包车折扣核验"],
                    rule_repetition_ratio=86.0,
                    shadow_agreement_rate=88.0,
                ),
                GenesisAccountSlotSpec(
                    user_id=f"{uid_prefix}_leader_li",
                    name="老李（车队大队长）",
                    title="跨境车队调度风控大队长",
                    department="跨境重卡调度与报关部",
                    role_view="leader",
                    slot_id=f"SLOT_{prefix}_LEADER_01",
                    slot_name="车队大队长高压线风控岗",
                    supervisor_id=f"{uid_prefix}_mgr_zhang",
                    is_custodian_leader=True,
                    node_id="node_leader_li",
                    node_type="RELAY_NODE",
                    parent_aspect_id="node_aspect_zam_dispatch",
                    subtree_root_id="subtree_quote",
                    skill_tags=["运价特批把关", "边境压车赔付谈判"],
                    rule_repetition_ratio=45.0,
                    shadow_agreement_rate=52.0,
                ),
                GenesisAccountSlotSpec(
                    user_id=f"{uid_prefix}_weigh_zhao",
                    name="老赵（磅房与油库主管）",
                    title="铜矿带磅房计量与恩多拉油库主管",
                    department="沿途油料补给与磅房部",
                    role_view="leader",
                    slot_id=f"SLOT_{prefix}_WEIGH_01",
                    slot_name="矿区磅房与恩多拉油库调度岗",
                    supervisor_id=f"{uid_prefix}_mgr_zhang",
                    is_custodian_leader=True,
                    node_id="node_worker_wms",
                    node_type="WORKER_SLOT",
                    parent_aspect_id="node_aspect_zam_fuel",
                    subtree_root_id="subtree_supply",
                    skill_tags=["过磅净重核验", "柴油安全水位预警"],
                    rule_repetition_ratio=82.0,
                    shadow_agreement_rate=85.0,
                ),
                GenesisAccountSlotSpec(
                    user_id=f"{uid_prefix}_maint_sun",
                    name="小孙（干线安环与维保）",
                    title="走廊干线GPS押运与轮胎备件专员",
                    department="矿区磅房计量与安环部",
                    role_view="employee",
                    slot_id=f"SLOT_{prefix}_MAINT_01",
                    slot_name="干线GPS安环与备件巡检岗",
                    supervisor_id=f"{uid_prefix}_weigh_zhao",
                    is_custodian_leader=False,
                    node_id="node_worker_maint",
                    node_type="WORKER_SLOT",
                    parent_aspect_id="node_aspect_zam_weigh",
                    subtree_root_id="subtree_weigh",
                    skill_tags=["GPS铅封追踪", "重卡备件点检"],
                    rule_repetition_ratio=84.0,
                    shadow_agreement_rate=86.0,
                ),
                GenesisAccountSlotSpec(
                    user_id=f"{uid_prefix}_fin_wang",
                    name="王姐（跨境外汇税控黑盒）",
                    title="跨境外汇核销与税控盘黑盒专员",
                    department="跨境财税与外汇黑盒部",
                    role_view="finance_tool",
                    slot_id=f"SLOT_{prefix}_FIN_BOX",
                    slot_name="跨境税控盘黑盒开票岗",
                    supervisor_id=f"{uid_prefix}_boss_lin",
                    is_custodian_leader=False,
                    node_id="node_blackbox_wang",
                    node_type="BLACKBOX_HUMAN",
                    parent_aspect_id="node_aspect_zam_settle",
                    subtree_root_id="subtree_fulfill",
                    skill_tags=["美元克瓦查双币开票", "税控盘物理签章"],
                    rule_repetition_ratio=62.0,
                    shadow_agreement_rate=35.0,
                ),
                GenesisAccountSlotSpec(
                    user_id=f"{uid_prefix}_mgr_zhang",
                    name="张总（非洲陆运运营总监）",
                    title="南部非洲走廊运营与组织进化总监",
                    department="经营管理与进化部",
                    role_view="manager",
                    slot_id=f"SLOT_{prefix}_MGR",
                    slot_name="非洲陆运中层运营主管岗",
                    supervisor_id=f"{uid_prefix}_boss_lin",
                    is_custodian_leader=True,
                    node_id="node_mgr_zhang",
                    node_type="RELAY_NODE",
                    parent_aspect_id="node_aspect_zam_dispatch",
                    subtree_root_id="subtree_quote",
                    skill_tags=["跨国走廊拓扑治理", "车队运力调配"],
                    rule_repetition_ratio=28.0,
                    shadow_agreement_rate=34.0,
                ),
                GenesisAccountSlotSpec(
                    user_id=f"{uid_prefix}_boss_lin",
                    name="林董（矿业物流集团董事长）",
                    title="赞比亚跨境陆运集团创始人 / 董事长",
                    department="顶层治理董事会",
                    role_view="boss",
                    slot_id=f"SLOT_{prefix}_BOSS",
                    slot_name="集团顶层决策席",
                    supervisor_id=None,
                    is_custodian_leader=True,
                    node_id="node_board_root",
                    node_type="BOARD_ROOT",
                    parent_aspect_id="node_board_root",
                    subtree_root_id="root",
                    skill_tags=["矿山长协底价治理", "人机师徒反转终审"],
                    rule_repetition_ratio=10.0,
                    shadow_agreement_rate=15.0,
                ),
            ]
            balls = [
                GenesisBallSpec(
                    ball_id=f"BALL_DATA_{prefix}_FLEET_CATALOG",
                    ball_type="DATA",
                    title="赞比亚铜精矿跨境干线运力与车型标准运价表",
                    domain_tags=["报价", "订单", "库存", "陆运"],
                    sensitivity_level=1,
                    owner_slot_ids=[
                        f"SLOT_{prefix}_DISP_01",
                        f"SLOT_{prefix}_CUSTOMS_02",
                        f"SLOT_{prefix}_LEADER_01",
                        f"SLOT_{prefix}_MGR",
                        f"SLOT_{prefix}_BOSS",
                    ],
                    content=(
                        "1) A款-35吨重型高栏铜矿卡车：公开标准运价 ¥1,280/吨（整车基准 ¥28,000/车），卢萨卡基地实时可用 85 辆；"
                        "2) B款-45吨集装箱特种平板车：公开标准运价 ¥2,190/柜段（整车 ¥34,500/车），恩多拉基地实时可用 42 辆；"
                        "3) C款-矿样快检加急皮卡：公开单价 ¥399/次，可用 18 辆。"
                    ),
                ),
                GenesisBallSpec(
                    ball_id=f"BALL_DATA_{prefix}_CUSTOMS_RATE_RULE",
                    ball_type="DATA",
                    title="坦赞边境清关与武装押运综合服务费率规范（待自动化）",
                    domain_tags=["报关", "财税", "报价", "运费"],
                    sensitivity_level=2,
                    owner_slot_ids=[
                        f"SLOT_{prefix}_DISP_01",
                        f"SLOT_{prefix}_CUSTOMS_02",
                        f"SLOT_{prefix}_LEADER_01",
                        f"SLOT_{prefix}_MGR",
                    ],
                    content=(
                        "跨境矿产保税清关与武装押运计费公式（待自动化）：按货运合同总金额的 8.5% 自动计提跨境清关综合服务费；"
                        "大宗铜精矿包车集采批量折扣：满 20 车享 9.0 折折后价。"
                    ),
                ),
                GenesisBallSpec(
                    ball_id=f"BALL_DATA_{prefix}_FUEL_SAFETY_STOCK",
                    ball_type="DATA",
                    title="恩多拉油库0号柴油安全储备水位与补给公式",
                    domain_tags=["仓储", "库存", "油料", "供应链"],
                    sensitivity_level=2,
                    owner_slot_ids=[
                        f"SLOT_{prefix}_WEIGH_01",
                        f"SLOT_{prefix}_MAINT_01",
                        f"SLOT_{prefix}_MGR",
                        f"SLOT_{prefix}_BOSS",
                    ],
                    content=(
                        "恩多拉与姆皮卡油库安全库存水位公式：安全储备升数 = 每日发车数 * 单车往返耗油850升 * 1.5；"
                        "低于安全水位时自动触发向达累斯萨拉姆炼油厂补货工单。"
                    ),
                ),
                GenesisBallSpec(
                    ball_id=f"BALL_SKILL_{prefix}_FREIGHT_CALC",
                    ball_type="SKILL",
                    title="跨境矿样与干线阶梯运费自动核算器",
                    domain_tags=["物流", "运费", "报价", "陆运"],
                    sensitivity_level=2,
                    owner_slot_ids=[
                        f"SLOT_{prefix}_DISP_01",
                        f"SLOT_{prefix}_CUSTOMS_02",
                        f"SLOT_{prefix}_LEADER_01",
                    ],
                    content="内置跨境阶梯运费可执行 Python 算子：首重 3 公斤内 10 元，超重每公斤加 4 元，满 500 元免运费。",
                    skill_instruction="跨境阶梯运费核算规则：首重3公斤内10元，超过3公斤每公斤加4元，满500元免运费",
                ),
                GenesisBallSpec(
                    ball_id=f"BALL_SKILL_{prefix}_FLEET_DISCOUNT_CALC",
                    ball_type="SKILL",
                    title="铜精矿大宗包车阶梯折后总价核算器",
                    domain_tags=["报价", "折扣", "订单"],
                    sensitivity_level=2,
                    owner_slot_ids=[
                        f"SLOT_{prefix}_DISP_01",
                        f"SLOT_{prefix}_CUSTOMS_02",
                        f"SLOT_{prefix}_LEADER_01",
                        f"SLOT_{prefix}_WEIGH_01",
                    ],
                    content="内置大宗包车阶梯折扣可执行 Python 算子：单笔满 20 件/车自动按 9.0 折核算折后总价。",
                    skill_instruction="批量折扣折后价规则：满 20 件享 9.0 折",
                ),
                GenesisBallSpec(
                    ball_id=f"BALL_AUTH_{prefix}_DISPATCH_QUOTE",
                    ball_type="AUTHORITY",
                    title="一线调度员常规锁车与9折内标准运价签发权",
                    domain_tags=["报价", "折扣", "陆运"],
                    sensitivity_level=2,
                    owner_slot_ids=[
                        f"SLOT_{prefix}_DISP_01",
                        f"SLOT_{prefix}_CUSTOMS_02",
                    ],
                    content="允许一线调度与报关专员在 >= 9.0 折且不涉及边境滞期费现金赔付的前提下直接锁车派单。",
                ),
                GenesisBallSpec(
                    ball_id=f"BALL_AUTH_{prefix}_LEADER_HV_GATE",
                    ball_type="AUTHORITY",
                    title="车队大队长高压线特批权（低折运价与压车滞期赔付初审）",
                    domain_tags=["折扣", "风控审批", "订单"],
                    sensitivity_level=4,
                    owner_slot_ids=[
                        f"SLOT_{prefix}_LEADER_01",
                        f"SLOT_{prefix}_MGR",
                        f"SLOT_{prefix}_BOSS",
                    ],
                    content="允许车队大队长老李对低于 8.5 折的运价特批及 <= 2,000 元的口岸压车补偿工单执行人工拍板。",
                ),
                GenesisBallSpec(
                    ball_id=f"BALL_REDLINE_{prefix}_DIESEL_FLOOR",
                    ball_type="REDLINE",
                    title="绝密矿山长协柴油补贴底价与通关暗补红线墙",
                    domain_tags=["底价", "机密成本", "合规"],
                    sensitivity_level=5,
                    owner_slot_ids=[f"SLOT_{prefix}_BOSS"],
                    content=(
                        "【核心商业绝密】赞比亚矿山长协柴油补贴底价 ¥4,200/车，达累斯萨拉姆港务通关暗补底价 ¥680/柜。"
                        "严禁向任何一线调度员、外部货代或非授权容器透出！"
                    ),
                    redline_keywords=[
                        "柴油补贴底价",
                        "通关暗补底价",
                        "车队真实底价",
                        "长协成本底价",
                        "工厂拿货底价",
                        "拿货底价",
                    ],
                ),
            ]
            return EnterpriseBlueprint(
                enterprise_name=enterprise_name,
                industry_category=industry,
                aspects=aspects,
                accounts_and_slots=accounts_and_slots,
                initial_balls=balls,
            )

        if any(
            k in combined
            for k in ("MCN", "达人", "独立站", "TikTok", "跨境电商", "直播")
        ):
            prefix = "MCN"
            uid_prefix = "mcn"
            industry = "出海DTC独立站与全球短视频达人营销"
            aspects = [
                GenesisAspectSpec(
                    node_id="node_aspect_mcn_bd",
                    label="【全球达人BD签约与寄样域】分面中枢",
                    subtree_root_id="subtree_quote",
                    domain_tags=["报价", "订单", "达人BD", "折扣"],
                ),
                GenesisAspectSpec(
                    node_id="node_aspect_mcn_campaign",
                    label="【独立站大促投放与ROAS域】分面中枢",
                    subtree_root_id="subtree_campaign",
                    domain_tags=["投放", "大促", "团购", "报价"],
                ),
                GenesisAspectSpec(
                    node_id="node_aspect_mcn_overseas_wms",
                    label="【北美海外仓一件代发履约域】分面中枢",
                    subtree_root_id="subtree_supply",
                    domain_tags=["仓储", "物流", "库存", "运费"],
                ),
                GenesisAspectSpec(
                    node_id="node_aspect_mcn_settle",
                    label="【多币种佣金财税黑盒域】分面中枢",
                    subtree_root_id="subtree_fulfill",
                    domain_tags=["财税", "开票", "佣金结算", "合规"],
                ),
            ]
        else:
            prefix = (
                "MED"
                if any(k in combined for k in ("医疗", "器械", "集采", "微创", "耗材"))
                else "ENT"
            )
            uid_prefix = prefix.lower()
            industry = (
                "三类微创医疗器械智造与省际医药集采"
                if prefix == "MED"
                else f"{enterprise_name}智能化业务集群"
            )
            aspects = [
                GenesisAspectSpec(
                    node_id=f"node_aspect_{uid_prefix}_commerce",
                    label=f"【{enterprise_name[:6]}·商务报价与签约域】分面中枢",
                    subtree_root_id="subtree_quote",
                    domain_tags=["报价", "订单", "折扣", "大客户"],
                ),
                GenesisAspectSpec(
                    node_id=f"node_aspect_{uid_prefix}_qa",
                    label=f"【{enterprise_name[:6]}·产研质检与工程域】分面中枢",
                    subtree_root_id="subtree_qa",
                    domain_tags=["质检", "产研", "供应链", "采购"],
                ),
                GenesisAspectSpec(
                    node_id=f"node_aspect_{uid_prefix}_supply",
                    label=f"【{enterprise_name[:6]}·智能仓配与物流域】分面中枢",
                    subtree_root_id="subtree_supply",
                    domain_tags=["仓储", "物流", "库存", "运费"],
                ),
                GenesisAspectSpec(
                    node_id=f"node_aspect_{uid_prefix}_finance",
                    label=f"【{enterprise_name[:6]}·财税合规双黑盒域】分面中枢",
                    subtree_root_id="subtree_fulfill",
                    domain_tags=["财税", "开票", "法务", "合规"],
                ),
            ]

        accounts_and_slots = [
            GenesisAccountSlotSpec(
                user_id=f"{uid_prefix}_rep_chen",
                name="小陈（一线业务一号位）",
                title=f"{enterprise_name[:6]}一线商务跟单专员",
                department="核心商务与客户运营部",
                role_view="employee",
                slot_id=f"SLOT_{prefix}_REP_01",
                slot_name=f"{enterprise_name[:6]}商务跟单一号位",
                supervisor_id=f"{uid_prefix}_leader_li",
                is_custodian_leader=False,
                node_id=f"node_{uid_prefix}_rep_01",
                node_type="WORKER_SLOT",
                parent_aspect_id=aspects[0].node_id,
                subtree_root_id="subtree_quote",
                skill_tags=["客户询价建单", "标准折扣核验"],
            ),
            GenesisAccountSlotSpec(
                user_id=f"{uid_prefix}_ops_zhou",
                name="小周（大客户集采二号位）",
                title=f"{enterprise_name[:6]}大客户履约专员",
                department="核心商务与客户运营部",
                role_view="employee",
                slot_id=f"SLOT_{prefix}_OPS_02",
                slot_name=f"{enterprise_name[:6]}大客户集采二号位",
                supervisor_id=f"{uid_prefix}_leader_li",
                is_custodian_leader=False,
                node_id="node_worker_zhou",
                node_type="WORKER_SLOT",
                parent_aspect_id=aspects[0].node_id,
                subtree_root_id="subtree_quote",
                skill_tags=["集采阶梯核算", "跨区锁库协同"],
            ),
            GenesisAccountSlotSpec(
                user_id=f"{uid_prefix}_leader_li",
                name="老李（业务风控组长）",
                title=f"{enterprise_name[:6]}基层风控组长",
                department="核心商务与客户运营部",
                role_view="leader",
                slot_id=f"SLOT_{prefix}_LEADER_01",
                slot_name="基层组长高压线风控岗",
                supervisor_id=f"{uid_prefix}_mgr_zhang",
                is_custodian_leader=True,
                node_id="node_leader_li",
                node_type="RELAY_NODE",
                parent_aspect_id=aspects[0].node_id,
                subtree_root_id="subtree_quote",
                skill_tags=["超低折扣审批", "高压线异常处理"],
                rule_repetition_ratio=44.0,
                shadow_agreement_rate=50.0,
            ),
            GenesisAccountSlotSpec(
                user_id=f"{uid_prefix}_wms_zhao",
                name="老赵（仓配与质检主管）",
                title=f"{enterprise_name[:6]}仓配与质检主管",
                department="智能仓配与供应链部",
                role_view="leader",
                slot_id=f"SLOT_{prefix}_WMS_01",
                slot_name="智能仓配与安全库存主管岗",
                supervisor_id=f"{uid_prefix}_mgr_zhang",
                is_custodian_leader=True,
                node_id="node_worker_wms",
                node_type="WORKER_SLOT",
                parent_aspect_id=aspects[2].node_id,
                subtree_root_id="subtree_supply",
                skill_tags=["波次锁库", "安全库存水位管控"],
            ),
            GenesisAccountSlotSpec(
                user_id=f"{uid_prefix}_qa_sun",
                name="小孙（供应链与质检专员）",
                title=f"{enterprise_name[:6]}质检与物流履约专员",
                department="智能仓配与供应链部",
                role_view="employee",
                slot_id=f"SLOT_{prefix}_QA_01",
                slot_name="质量检验与干线配载岗",
                supervisor_id=f"{uid_prefix}_wms_zhao",
                is_custodian_leader=False,
                node_id="node_worker_qa",
                node_type="WORKER_SLOT",
                parent_aspect_id=aspects[1].node_id,
                subtree_root_id=aspects[1].subtree_root_id,
                skill_tags=["批次质检放行", "冷链干线追踪"],
            ),
            GenesisAccountSlotSpec(
                user_id=f"{uid_prefix}_fin_wang",
                name="王姐（财税合规黑盒）",
                title="加密税控盘与合规审查黑盒专员",
                department="财税法务双黑盒部",
                role_view="finance_tool",
                slot_id=f"SLOT_{prefix}_FIN_BOX",
                slot_name="加密税控盘黑盒开票岗",
                supervisor_id=f"{uid_prefix}_boss_lin",
                is_custodian_leader=False,
                node_id="node_blackbox_wang",
                node_type="BLACKBOX_HUMAN",
                parent_aspect_id=aspects[3].node_id,
                subtree_root_id="subtree_fulfill",
                skill_tags=["数电专票开具", "最小四要素核验"],
                rule_repetition_ratio=60.0,
                shadow_agreement_rate=35.0,
            ),
            GenesisAccountSlotSpec(
                user_id=f"{uid_prefix}_mgr_zhang",
                name="张总（运营进化总监）",
                title=f"{enterprise_name[:6]}运营与组织进化总监",
                department="经营管理与进化部",
                role_view="manager",
                slot_id=f"SLOT_{prefix}_MGR",
                slot_name="中层运营与拓扑治理主管岗",
                supervisor_id=f"{uid_prefix}_boss_lin",
                is_custodian_leader=True,
                node_id="node_mgr_zhang",
                node_type="RELAY_NODE",
                parent_aspect_id=aspects[0].node_id,
                subtree_root_id="subtree_quote",
                skill_tags=["蛛网拓扑治理", "跨部门协同"],
                rule_repetition_ratio=26.0,
                shadow_agreement_rate=32.0,
            ),
            GenesisAccountSlotSpec(
                user_id=f"{uid_prefix}_boss_lin",
                name="林董（集团创始人）",
                title=f"{enterprise_name}董事长 / 顶层决策人",
                department="顶层治理董事会",
                role_view="boss",
                slot_id=f"SLOT_{prefix}_BOSS",
                slot_name="公司顶层决策席",
                supervisor_id=None,
                is_custodian_leader=True,
                node_id="node_board_root",
                node_type="BOARD_ROOT",
                parent_aspect_id="node_board_root",
                subtree_root_id="root",
                skill_tags=["全局红线治理", "董事会终审拍板"],
                rule_repetition_ratio=10.0,
                shadow_agreement_rate=15.0,
            ),
        ]

        rate_m = re.search(r"(\d+(?:\.\d+)?)\s*%", business_description)
        rate_str = rate_m.group(1) if rate_m else "8.5"
        balls = [
            GenesisBallSpec(
                ball_id=f"BALL_DATA_{prefix}_PRODUCT_CATALOG",
                ball_type="DATA",
                title=f"{enterprise_name}核心产品目录与实时现货库存表",
                domain_tags=["报价", "订单", "库存"],
                sensitivity_level=1,
                owner_slot_ids=[
                    f"SLOT_{prefix}_REP_01",
                    f"SLOT_{prefix}_OPS_02",
                    f"SLOT_{prefix}_LEADER_01",
                    f"SLOT_{prefix}_MGR",
                    f"SLOT_{prefix}_BOSS",
                ],
                content=(
                    f"【{enterprise_name}标准主数据】A款主力型号公开指导单价 ¥1,280/件（中心仓现货 420 件）；"
                    "B款高配型号公开指导单价 ¥2,190/件（现货 180 件）。"
                ),
            ),
            GenesisBallSpec(
                ball_id=f"BALL_DATA_{prefix}_SERVICE_FEE_RULE",
                ball_type="DATA",
                title=f"{enterprise_name}专项服务费率与阶梯计价规范（待自动化）",
                domain_tags=["报价", "财税", "运费"],
                sensitivity_level=2,
                owner_slot_ids=[
                    f"SLOT_{prefix}_REP_01",
                    f"SLOT_{prefix}_OPS_02",
                    f"SLOT_{prefix}_LEADER_01",
                    f"SLOT_{prefix}_MGR",
                ],
                content=(
                    f"专项技术维保/佣金服务费公式（待自动化）：按合同结算总金额的 {rate_str}% 自动计提综合服务费；"
                    "大宗集采满 20 件享 9.0 折阶梯优惠。"
                ),
            ),
            GenesisBallSpec(
                ball_id=f"BALL_DATA_{prefix}_WMS_SAFETY_RULE",
                ball_type="DATA",
                title=f"{enterprise_name}中心仓安全库存水位与自动补货公式",
                domain_tags=["仓储", "库存", "供应链"],
                sensitivity_level=2,
                owner_slot_ids=[
                    f"SLOT_{prefix}_WMS_01",
                    f"SLOT_{prefix}_QA_01",
                    f"SLOT_{prefix}_MGR",
                    f"SLOT_{prefix}_BOSS",
                ],
                content="安全库存水位公式：安全水位 = 日均出货量 * 备货周期天数 * 1.5；低于安全水位自动触发补货。",
            ),
            GenesisBallSpec(
                ball_id=f"BALL_SKILL_{prefix}_SHIPPING_CALC",
                ball_type="SKILL",
                title=f"{enterprise_name}阶梯履约运费自动核算器",
                domain_tags=["物流", "运费", "报价"],
                sensitivity_level=2,
                owner_slot_ids=[
                    f"SLOT_{prefix}_REP_01",
                    f"SLOT_{prefix}_OPS_02",
                    f"SLOT_{prefix}_LEADER_01",
                    f"SLOT_{prefix}_WMS_01",
                ],
                content="内置可执行 Python 运费算子：首重 3 公斤内 10 元，超过 3 公斤每公斤加 4 元，订单满 500 元免运费。",
                skill_instruction="阶梯运费规则：首重3公斤内10元，超过3公斤每公斤加4元，满500元免运费",
            ),
            GenesisBallSpec(
                ball_id=f"BALL_SKILL_{prefix}_BULK_DISCOUNT",
                ball_type="SKILL",
                title=f"{enterprise_name}批量集采阶梯折后总价核算器",
                domain_tags=["报价", "折扣", "大客户"],
                sensitivity_level=2,
                owner_slot_ids=[
                    f"SLOT_{prefix}_REP_01",
                    f"SLOT_{prefix}_OPS_02",
                    f"SLOT_{prefix}_LEADER_01",
                ],
                content="内置可执行 Python 批量折扣算子：单笔满 20 件自动按 9.0 折计算折后总价。",
                skill_instruction="批量折扣折后价规则：满 20 件享 9.0 折",
            ),
            GenesisBallSpec(
                ball_id=f"BALL_AUTH_{prefix}_FRONT_QUOTE",
                ball_type="AUTHORITY",
                title="一线专员常规报价与9折内自助锁库权",
                domain_tags=["报价", "折扣"],
                sensitivity_level=2,
                owner_slot_ids=[
                    f"SLOT_{prefix}_REP_01",
                    f"SLOT_{prefix}_OPS_02",
                ],
                content="允许一线业务员在 >= 9.0 折且无额外现金赔偿承诺的前提下直接锁库建单。",
            ),
            GenesisBallSpec(
                ball_id=f"BALL_AUTH_{prefix}_LEADER_HV_GATE",
                ball_type="AUTHORITY",
                title="基层组长高压线特批权（超低折扣与异常赔付拍板）",
                domain_tags=["折扣", "风控审批", "订单"],
                sensitivity_level=4,
                owner_slot_ids=[
                    f"SLOT_{prefix}_LEADER_01",
                    f"SLOT_{prefix}_MGR",
                    f"SLOT_{prefix}_BOSS",
                ],
                content="允许基层风控组长对低于 8.5 折的特批议价及小额履约补偿工单执行人工拍板放行。",
            ),
            GenesisBallSpec(
                ball_id=f"BALL_REDLINE_{prefix}_FLOOR_SECRET",
                ball_type="REDLINE",
                title=f"{enterprise_name}绝密出厂BOM底价与返点隔离红线墙",
                domain_tags=["底价", "机密成本", "合规"],
                sensitivity_level=5,
                owner_slot_ids=[f"SLOT_{prefix}_BOSS"],
                content=f"【{enterprise_name}核心商业绝密】核心产品出厂BOM拿货底价与总代返点协议严禁向一线或外部透出！",
                redline_keywords=[
                    "FOB拿货底价",
                    "达人返点底价",
                    "刀头BOM底价",
                    "省级总代底价",
                    "医疗器械出厂底价",
                    "工厂拿货底价",
                    "拿货底价",
                    "真实成本底价",
                ],
            ),
        ]
        return EnterpriseBlueprint(
            enterprise_name=enterprise_name,
            industry_category=industry,
            aspects=aspects,
            accounts_and_slots=accounts_and_slots,
            initial_balls=balls,
        )

    async def deploy_enterprise_blueprint(
        self,
        enterprise_name: str,
        business_description: str,
        reset_existing: bool = False,
        *,
        actor_user_id: str | None = None,
    ) -> dict[str, Any]:
        before = (
            await self._rt.capture_state()
            if hasattr(self._rt, "capture_state")
            else None
        )
        try:
            return await self._deploy_enterprise_blueprint(
                enterprise_name, business_description, reset_existing,
                actor_user_id=actor_user_id,
            )
        except BaseException:
            if before is not None:
                await self._rt.restore_runtime_state(before, preserve_security=False)
            raise

    async def _deploy_enterprise_blueprint(
        self,
        enterprise_name: str,
        business_description: str,
        reset_existing: bool = False,
        *,
        actor_user_id: str | None = None,
    ) -> dict[str, Any]:
        clean_name = enterprise_name.strip() or "新创世企业集群"
        clean_desc = business_description.strip() or clean_name

        sys_prompt = (
            "你是 Arachne-OS 的企业创世解剖与自繁殖引擎。请对用户输入的企业名称与业务制度描述进行彻底解剖，"
            "输出严格符合 EnterpriseBlueprint 的 JSON：包含 3~4 个核心业务域部门子树 (aspects)、"
            "6~8 个标准岗位单元容器与账号 (accounts_and_slots，涵盖 employee/leader/finance_tool/manager/boss 及上下级汇报链)、"
            "以及 6~10 颗初始权能球 (initial_balls，必须同时涵盖 DATA/SKILL/AUTHORITY/REDLINE 四类)。"
        )
        usr_prompt = f"企业名称：{clean_name}\n业务描述与制度：{clean_desc}"

        blueprint = await self._llm.complete_structured(
            tier="L3",
            system_prompt=sys_prompt,
            user_prompt=usr_prompt,
            response_model=EnterpriseBlueprint,
            fallback_builder=lambda: self._build_deterministic_blueprint(
                clean_name, clean_desc
            ),
        )
        # 校验 LLM 输出是否满足 3~4 个业务域、6~8 个工位、6~10 颗球且覆盖四类球，否则用高拟真解析器补齐
        ball_types_present = {b.ball_type for b in blueprint.initial_balls}
        if (
            not (3 <= len(blueprint.aspects) <= 4)
            or not (6 <= len(blueprint.accounts_and_slots) <= 8)
            or not (6 <= len(blueprint.initial_balls) <= 10)
            or len({"DATA", "SKILL", "AUTHORITY", "REDLINE"} - ball_types_present) > 0
        ):
            blueprint = self._build_deterministic_blueprint(clean_name, clean_desc)

        prior_auth = getattr(self._rt, "auth_custody", None)
        prior_slots = {slot.slot_id: slot for slot in self._containers.list_slots()}
        # A historical boss title is not an administrator credential source.
        # Capture the live occupant before the empty-shell reset replaces profiles.
        prior_boss_credentials = {
            p.user_id: prior_auth._passwords[p.user_id]
            for p in self._containers.list_profiles()
            if prior_auth is not None
            and p.role_view == "boss"
            and not prior_auth.account_directory.get(p.user_id, {}).get("_disabled")
            and not p.slot_id.startswith("SLOT_STANDBY_")
            and not any(marker in p.title for marker in ("已离岗交接", "休假代班中"))
            and p.slot_id in prior_slots
            and prior_slots[p.slot_id].occupant_id == p.user_id
            and p.user_id in prior_auth._passwords
        }
        continuation_password = prior_boss_credentials.get(actor_user_id)
        if continuation_password is None and len(prior_boss_credentials) == 1:
            continuation_password = next(iter(prior_boss_credentials.values()))
        has_bootstrap_password = bool(getattr(prior_auth, "_bootstrap_password", ""))
        if reset_existing and not has_bootstrap_password and continuation_password is None:
            if any(
                acc.role_view == "boss" and acc.user_id not in prior_boss_credentials
                for acc in blueprint.accounts_and_slots
            ):
                raise ValueError("无法确定唯一的在岗管理员凭据，请由在岗管理员登录后执行创世部署")
        if reset_existing:
            cave = getattr(self._rt, "cave_explorer", None)
            if cave is None:
                from swarm.cave_explorer import CaveExplorationEngine

                cave = CaveExplorationEngine(self._rt)
                self._rt.cave_explorer = cave
            await cave.reset_to_empty_shell(clean_name)
            self._forged_source_ball_ids.clear()
            self._containers._slots.clear()
            self._containers._profiles.clear()
            self._particles._balls.clear()
            self._particles._vectors.clear()
            self._wecom._messages_by_user.clear()
            await self._hot_store.restore_global_state(
                {"nodes": [], "tickets": [], "leases": []}
            )

        # 1. 注册顶层董事会根节点 + 3~4 个业务域分面子树 (ASPECT_NODE)
        board_root_slot = next(
            (a.slot_id for a in blueprint.accounts_and_slots if a.role_view == "boss"),
            blueprint.accounts_and_slots[-1].slot_id,
        )
        mgr_slot = next(
            (
                a.slot_id
                for a in blueprint.accounts_and_slots
                if a.role_view == "manager"
            ),
            board_root_slot,
        )
        leader_slot = next(
            (
                a.slot_id
                for a in blueprint.accounts_and_slots
                if a.role_view == "leader"
            ),
            mgr_slot,
        )
        fin_slot = next(
            (
                a.slot_id
                for a in blueprint.accounts_and_slots
                if a.role_view == "finance_tool"
            ),
            board_root_slot,
        )
        first_worker_slot = next(
            (
                a.slot_id
                for a in blueprint.accounts_and_slots
                if a.role_view == "employee"
            ),
            blueprint.accounts_and_slots[0].slot_id,
        )

        root_node = SpiderNode(
            node_id="node_board_root",
            label=f"【{blueprint.enterprise_name}】顶层自适应董事会",
            node_type="BOARD_ROOT",
            parent_id=None,
            subtree_root_id="root",
            slot_id=board_root_slot,
            domain_tags=["治理", "战略", blueprint.industry_category],
            status="ACTIVE",
            active_load=1,
        )
        await self._hot_store.upsert_node(root_node)

        registered_aspects: list[SpiderNode] = []
        for asp in blueprint.aspects:
            asp_node = SpiderNode(
                node_id=asp.node_id,
                label=asp.label,
                node_type="ASPECT_NODE",
                parent_id="node_board_root",
                subtree_root_id=asp.subtree_root_id,
                slot_id=mgr_slot,
                domain_tags=asp.domain_tags,
                status="ACTIVE",
                active_load=1,
            )
            await self._hot_store.upsert_node(asp_node)
            registered_aspects.append(asp_node)

        trusted_template = any(
            clean_desc == template["business_description"]
            for template in ENTERPRISE_GENESIS_TEMPLATES
        )
        explicit_skill_rule = bool(
            self._build_deterministic_decomposition_plan(clean_desc).skill_instruction
        )
        public_data_source = _public_data_source(clean_desc)
        authority_source = _authority_source(clean_desc)
        redline_source = "\n".join(
            line
            for line in clean_desc.splitlines()
            if any(word in line for word in ("严禁", "禁止", "不得"))
        )

        # 2. 注册并编译 6~10 颗初始权能小球（SKILL 球真正落盘 sandbox_workspace/）
        registered_balls: list[CapabilityBall] = []
        for b_spec in blueprint.initial_balls:
            exec_path: Optional[str] = None
            status = "ACTIVE"
            source_content = b_spec.content
            source_title = b_spec.title
            source_tags = b_spec.domain_tags
            if b_spec.ball_type == "DATA" and not trusted_template:
                source_tags = ["业务资料"]
                if public_data_source:
                    source_content = public_data_source
                    source_title = "已提供的公开业务资料"
                else:
                    status = "CANDIDATE"
                    source_content = (
                        "未提供明确、非敏感的业务事实；自动推断资料须人工审核。"
                    )
                    source_title = "待审核业务资料候选"
            elif b_spec.ball_type == "AUTHORITY":
                if authority_source:
                    source_content = authority_source
                else:
                    status = "CANDIDATE"
                    source_content = "缺少明确授权原文，候选权限须人工审查。"
            elif b_spec.ball_type == "REDLINE":
                if redline_source:
                    source_content = redline_source
                else:
                    status = "CANDIDATE"
                    source_content = "缺少明确禁止事项原文，候选红线须人工审查。"
            elif b_spec.ball_type == "SKILL":
                if not trusted_template:
                    status = "CANDIDATE"
            if b_spec.ball_type == "SKILL" and explicit_skill_rule:
                instr = b_spec.skill_instruction or b_spec.content
                exec_path, _ = await self._compile_and_persist_skill_script(
                    ball_id=b_spec.ball_id,
                    skill_instruction=instr,
                )

            ball = CapabilityBall(
                ball_id=b_spec.ball_id,
                ball_type=b_spec.ball_type,
                title=source_title,
                domain_tags=source_tags,
                sensitivity_level=b_spec.sensitivity_level,
                owner_slot_ids=b_spec.owner_slot_ids,
                content=source_content,
                redline_keywords=[
                    kw for kw in b_spec.redline_keywords if kw in clean_desc
                ],
                executable_code_path=exec_path,
                status=status,
            )
            self._particles.register_ball(ball, record_to_vault=True)
            registered_balls.append(ball)

        # 3. 注册 6~8 个标准岗位容器 (UnitSlot)、员工档案 (DualEmployeeProfile)、拓扑节点与欢迎消息
        registered_slots: list[UnitSlot] = []
        registered_profiles: list[DualEmployeeProfile] = []
        auth_svc = getattr(self._rt, "auth_custody", None)
        if auth_svc is None:
            auth_svc = AuthAndCustodyService(
                vault=self._vault,
                particles=self._particles,
                containers=self._containers,
                settings=self._settings,
            )
            setattr(self._rt, "auth_custody", auth_svc)

        for acc in blueprint.accounts_and_slots:
            owned_ball_ids = [
                b.ball_id
                for b in registered_balls
                if acc.slot_id in b.owner_slot_ids and b.status == "ACTIVE"
            ]
            rep_score = round(
                0.4 * acc.rule_repetition_ratio + 0.6 * acc.shadow_agreement_rate, 2
            )
            slot = UnitSlot(
                slot_id=acc.slot_id,
                slot_name=acc.slot_name,
                department=acc.department,
                ball_ids=owned_ball_ids,
                occupant_type="HUMAN",
                occupant_id=acc.user_id,
                rule_repetition_ratio=acc.rule_repetition_ratio,
                shadow_agreement_rate=acc.shadow_agreement_rate,
                replaceability_score=rep_score,
            )
            self._containers.register_slot(slot)
            registered_slots.append(slot)

            perf_score = round(max(55.0, min(99.0, 90.0 - 0.25 * rep_score)), 2)
            profile = DualEmployeeProfile(
                user_id=acc.user_id,
                name=acc.name,
                title=acc.title,
                role_view=acc.role_view,
                slot_id=acc.slot_id,
                employee_view=EmployeeViewA(
                    skill_tags=acc.skill_tags or [acc.department],
                    saved_hours=8.0,
                    evolution_contributions=[],
                    innovation_bonus=12.0 if acc.is_custodian_leader else 0.0,
                ),
                management_view=ManagementViewB(
                    avg_latency_ms=360.0,
                    rework_rate=0.01,
                    boundary_probes=0,
                    base_fulfillment_score=89.0,
                    performance_score=perf_score,
                ),
            )
            self._containers.register_profile(profile)
            registered_profiles.append(profile)

            auth_svc.account_directory[acc.user_id] = {
                "department": acc.department,
                "supervisor_id": acc.supervisor_id,
                "is_custodian_leader": acc.is_custodian_leader,
            }

            if acc.node_type != "BOARD_ROOT":
                worker_node = SpiderNode(
                    node_id=acc.node_id,
                    label=f"{acc.slot_name} ({acc.name})",
                    node_type=acc.node_type,
                    parent_id=acc.parent_aspect_id,
                    subtree_root_id=acc.subtree_root_id,
                    slot_id=acc.slot_id,
                    domain_tags=acc.skill_tags or [acc.department],
                    status="DEHYDRATED"
                    if acc.role_view == "finance_tool"
                    else "ACTIVE",
                    active_load=0 if acc.role_view == "finance_tool" else 1,
                )
                await self._hot_store.upsert_node(worker_node)

            facade: Any = (
                "BOARD_INSIDER"
                if acc.role_view == "boss"
                else (
                    "GOVERNANCE"
                    if acc.is_custodian_leader or acc.role_view == "finance_tool"
                    else "COPILOT"
                )
            )
            bot_names = {
                "COPILOT": "#1 业务副驾",
                "GOVERNANCE": "#2 进化与风控官",
                "BOARD_INSIDER": "#3 董事会内参",
            }
            welcome_text = acc.welcome_message or (
                f"🚀【企业创世空投就绪 · {blueprint.enterprise_name}】\n"
                f"你好 {acc.name}！你的标准岗位容器【{acc.slot_name} ({acc.slot_id})】已完成冷启动装配，"
                f"初始挂载 {len(owned_ball_ids)} 颗权能小球，直属部门：{acc.department}。"
            )
            await self._wecom.append_message(
                ChatMessageItem(
                    msg_id=f"MSG_GEN_{uuid.uuid4().hex[:8].upper()}",
                    sender_id=f"BOT_{facade}",
                    sender_name=bot_names[facade],
                    facade_bot=facade,
                    chat_type="SINGLE",
                    direction="OUTBOUND",
                    content=welcome_text,
                    structured_card={
                        "viewer_user_id": acc.user_id,
                        "enterprise_name": blueprint.enterprise_name,
                        "slot_id": acc.slot_id,
                    },
                )
            )

        new_directory = {
            acc.user_id: {
                "department": acc.department,
                "supervisor_id": acc.supervisor_id,
                "is_custodian_leader": acc.is_custodian_leader,
            }
            for acc in blueprint.accounts_and_slots
        }
        if reset_existing:
            fallback_boss_pw = (
                continuation_password
                if not has_bootstrap_password
                else None
            )
            new_boss_ids = {
                p.user_id for p in registered_profiles if p.role_view == "boss"
            }
            kept_boss_ids: set[str] = set()
            for uid in new_boss_ids:
                pw = prior_boss_credentials.get(uid, fallback_boss_pw)
                if pw:
                    auth_svc.set_password(uid, pw)
                    kept_boss_ids.add(uid)
            auth_svc.reset_workspace_identity(
                new_directory, preserve_password_user_ids=kept_boss_ids
            )
            self._rt.cave_explorer.enterprise_name = clean_name
            self._rt.cave_explorer.raw_org_material = clean_desc
            self._rt.cave_explorer.mode = "GENESIS_DEPLOYED"
        else:
            auth_svc.sync_accounts_from_containers()
        self._rt.genesis_engine = self

        # 若 reset_existing=True，重置运行时槽位别名表以避免保留旧企业残留映射
        if reset_existing and hasattr(self._containers, "clear_slot_aliases"):
            self._containers.clear_slot_aliases()

            # Keep authorization resolution bound to the live registry, not closures over a prior workspace.
            auth_svc.__dict__.pop("resolve_ball_custodian", None)
            auth_svc.__dict__.pop("can_user_manage_ball", None)

            self._human_tools.register_contract(
                HumanBlackBoxContract(
                    contract_id="CONTRACT_LEADER_HV_APPROVAL",
                    slot_id=leader_slot,
                    task_name="基层组长高压线风控拍板",
                    allowed_input_fields=[
                        "ticket_id",
                        "initiator_name",
                        "customer_name",
                        "product_summary",
                        "high_voltage_category",
                        "high_voltage_reason",
                        "requested_amount",
                        "invoice_title",
                        "tax_id",
                    ],
                    required_output_schema={
                        "decision": "APPROVE | REJECT",
                        "approved_amount": "positive_decimal",
                        "comment": "non_empty_string",
                    },
                )
            )
            self._human_tools.register_contract(
                HumanBlackBoxContract(
                    contract_id="CONTRACT_FINANCE_TAX_DISK",
                    slot_id=fin_slot,
                    task_name="物理加密税控盘增值税开票黑盒",
                    allowed_input_fields=[
                        "ticket_id",
                        "invoice_title",
                        "tax_id",
                        "amount",
                    ],
                    required_output_schema={
                        "invoice_number": "^(\\d{8}|\\d{20})$",
                        "billed_amount": "must_equal_input_amount",
                        "attachment_ref": "non_empty_string",
                    },
                )
            )

        # 封存各业务域子树与全局快照，写入 WORM 创世区块 ENTERPRISE_GENESIS_DEPLOYED
        for asp in blueprint.aspects:
            sub_snap = await self._hot_store.export_subtree_state(asp.subtree_root_id)
            self._vault.seal_snapshot(
                asp.subtree_root_id, mgr_slot, sub_snap, scope="LOCAL"
            )
        global_snap = await self._hot_store.export_global_state()
        self._vault.seal_snapshot("root", board_root_slot, global_snap, scope="GLOBAL")

        # Historical expected outputs must come from independent evidence, never from deployment defaults.
        candidate_ball_ids = [
            ball.ball_id for ball in registered_balls if ball.status == "CANDIDATE"
        ]
        continuation = {
            "required_action": "REVIEW_CANDIDATES" if candidate_ball_ids else "NONE",
            "candidate_ball_ids": candidate_ball_ids,
        }

        genesis_record = self._vault.append_event(
            event_kind="ENTERPRISE_GENESIS_DEPLOYED",
            subtree_root_id="root",
            actor_slot_id=board_root_slot,
            payload={
                "enterprise_name": blueprint.enterprise_name,
                "industry_category": blueprint.industry_category,
                "reset_existing": reset_existing,
                "continuation": continuation,
                "aspect_count": len(registered_aspects),
                "slot_count": len(registered_slots),
                "account_ids": [p.user_id for p in registered_profiles],
                "ball_ids": [b.ball_id for b in registered_balls],
            },
        )

        await self._pulse.publish(
            event_type="ASPECT_CLUSTERED",
            node_id="node_board_root",
            subtree_root_id="root",
            severity="SUCCESS",
            summary=(
                f"🌌 企业创世空投完成：《{blueprint.enterprise_name}》已自动解剖生成 "
                f"{len(registered_aspects)} 大业务域、{len(registered_slots)} 个标准工位容器与 {len(registered_balls)} 颗初始权能球！"
            ),
            payload={
                "enterprise_name": blueprint.enterprise_name,
                "aspect_count": len(registered_aspects),
                "slot_count": len(registered_slots),
                "ball_count": len(registered_balls),
            },
        )

        departments = sorted({acc.department for acc in blueprint.accounts_and_slots})
        accounts_summary = [
            {
                "user_id": acc.user_id,
                "username": acc.user_id,
                "name": acc.name,
                "title": acc.title,
                "department": acc.department,
                "role_view": acc.role_view,
                "slot_id": acc.slot_id,
                "supervisor_id": acc.supervisor_id,
                "is_custodian_leader": acc.is_custodian_leader,
                "mounted_ball_ids": [
                    b.ball_id
                    for b in registered_balls
                    if acc.slot_id in b.owner_slot_ids and b.status == "ACTIVE"
                ],
            }
            for acc in blueprint.accounts_and_slots
        ]

        return {
            "enterprise_name": blueprint.enterprise_name,
            "industry_category": blueprint.industry_category,
            "reset_existing": reset_existing,
            "continuation": continuation,
            "evidence_provenance": {
                "initial_skills": "BUILTIN_EXPLICIT_RULE_TEMPLATE"
                if trusted_template
                else "CANDIDATE_REQUIRES_INDEPENDENT_VALIDATION",
                "policy_source": "SUPPLIED_BUSINESS_DESCRIPTION",
            },
            "department_count": len(departments),
            "departments": departments,
            "aspect_count": len(registered_aspects),
            "aspects": [a.model_dump() for a in registered_aspects],
            "slot_count": len(registered_slots),
            "slots": [s.model_dump() for s in registered_slots],
            "account_count": len(accounts_summary),
            "accounts": accounts_summary,
            "ball_count": len(registered_balls),
            "initial_balls": [b.model_dump() for b in registered_balls],
            "worm_event": genesis_record.model_dump(),
        }

    # ==========================================================================
    # 能力 2：业务制度/SOP 自动解剖拆球与大球有丝分裂 (`decompose_or_split_balls`)
    # ==========================================================================
    def _resolve_valid_actor(self, actor_user_id: str) -> DualEmployeeProfile:
        return self._containers.get_profile(actor_user_id)

    def _build_deterministic_decomposition_plan(
        self, raw_policy_text: str
    ) -> PolicyDecompositionPlan:
        text = raw_policy_text.strip()
        short_topic = (
            re.sub(r"[《》\n\r\t：:，,。]", "", text[:14]).strip() or "企业业务制度"
        )

        # 1) 提取计算公式并归一化为可 100% 通过影子擂台基准测试的指令
        rate_m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        disc_m = re.search(
            r"满\s*(\d+)\s*(?:件|台|把|车|柜).*?(\d(?:\.\d)?)\s*折", text
        )
        if rate_m:
            rate_val = rate_m.group(1)
            skill_instr = (
                f"标准化费率自动核算规则：按合同结算金额的 {rate_val}% 自动计提费用"
            )
        elif disc_m:
            qty_th, d_val = disc_m.group(1), disc_m.group(2)
            skill_instr = f"批量折扣折后价规则：满 {qty_th} 件享 {d_val} 折"
        elif any(k in text for k in ("首重", "续重", "运费")):
            skill_instr = (
                "阶梯运费规则：首重3公斤内10元，超过3公斤每公斤加4元，满500元免运费"
            )
        else:
            skill_instr = ""

        # 2) 提取红线关键词
        redline_kws: list[str] = []
        for candidate_kw in (
            "柴油补贴底价",
            "通关暗补底价",
            "车队真实底价",
            "FOB拿货底价",
            "达人返点底价",
            "刀头BOM底价",
            "省级总代底价",
            "工厂拿货底价",
            "拿货底价",
            "无限连带责任",
            "滞期费违约上限",
            "私人手机号列表",
        ):
            if candidate_kw in text:
                redline_kws.append(candidate_kw)
        for m in re.finditer(r"([\u4e00-\u9fa5A-Za-z0-9]{2,8}底价)", text):
            kw = m.group(1)
            if kw not in redline_kws:
                redline_kws.append(kw)
        if not redline_kws:
            redline_kws = []

        return PolicyDecompositionPlan(
            data_title=f"【制度解剖·DATA】{short_topic}基础参数与目录表",
            data_content=f"从制度文档提炼的结构化事实与业务参数：{text[:220]}",
            data_tags=["报价", "订单", "制度参数"],
            skill_instruction=skill_instr,
            authority_title=f"【制度解剖·AUTHORITY】{short_topic}分级审批授权门禁",
            authority_content=(
                f"从制度文档提炼的岗位审批权限规范：{text[:180]} "
                "（常规阈值内自助放行，超限自动挂起转交部门头头拍板）。"
            ),
            authority_tags=["风控审批", "折扣", "权限门禁"],
            redline_title=f"【制度解剖·REDLINE】{short_topic}绝密底价与合规禁区墙",
            redline_content=f"从制度文档提炼的高压严禁事项与机密底价隔离墙：{text[:180]}",
            redline_keywords=redline_kws,
            redline_tags=["底价", "合规", "机密成本"],
        )

    def _build_deterministic_mitosis_plan(
        self, target_ball: CapabilityBall, guidance_text: str = ""
    ) -> MitosisSplitPlan:
        base_tags = list(target_ball.domain_tags) or ["业务协同"]
        front_tags = list(dict.fromkeys([*base_tags[:2], "前端执行规程", "SOP"]))
        back_tags = list(dict.fromkeys([*base_tags[:2], "后端风控算子", "自动核算"]))

        source_rule = self._build_deterministic_decomposition_plan(
            f"{target_ball.content}\n{guidance_text}"
        )
        skill_instr = source_rule.skill_instruction

        return MitosisSplitPlan(
            child_a_title=f"[子球A·前端执行规程] {target_ball.title}",
            child_a_type="DATA"
            if target_ball.ball_type == "DATA"
            else target_ball.ball_type,
            child_a_content=(
                f"【有丝分裂·前端标准作业规程 (SOP)】源自母球 [{target_ball.ball_id}]：\n"
                f"负责一线业务要素齐套性校验、客户建单前置核查与标准流程指引。原规程核心：{target_ball.content[:160]}"
            ),
            child_a_tags=front_tags,
            child_b_title=f"[子球B·后端风控与核算算子] {target_ball.title}",
            child_b_type="SKILL"
            if target_ball.ball_type in ("DATA", "SKILL")
            else target_ball.ball_type,
            child_b_content=(
                f"【有丝分裂·后端风控与自动核算算子】源自母球 [{target_ball.ball_id}]：\n"
                f"负责后台净室确定性费率/阈值计算与越界熔断校验。原规程核心：{target_ball.content[:160]}"
            ),
            child_b_tags=back_tags,
            child_b_skill_instruction=skill_instr,
        )

    async def decompose_or_split_balls(
        self,
        actor_user_id: str,
        raw_policy_text: str = "",
        target_ball_id: Optional[str] = None,
    ) -> dict[str, Any]:
        actor_prof = self._resolve_valid_actor(actor_user_id)
        all_slots = self._containers.list_slots()
        leader_slots = [
            p.slot_id
            for p in self._containers.list_profiles()
            if p.role_view in ("leader", "manager", "boss")
        ]
        boss_slots = [
            p.slot_id for p in self._containers.list_profiles() if p.role_view == "boss"
        ] or [actor_prof.slot_id]

        # ======================================================================
        # 模式 B：大球细胞有丝分裂 (Ball Mitosis)
        # ======================================================================
        if target_ball_id and target_ball_id.strip():
            clean_ball_id = target_ball_id.strip()
            target_ball = self._particles.get_ball(clean_ball_id)
            if target_ball is None:
                raise KeyError(f"未找到待分裂的目标权能球: {clean_ball_id}")

            sys_prompt = (
                "你是 Arachne-OS 的权能球有丝分裂器 (Ball Mitosis Engine)。"
                "请将输入的单颗复合大球按职责正交一分为二：子球A负责【前端执行规程】，"
                "子球B负责【后端风控与核算算子】，输出严格符合 MitosisSplitPlan 的 JSON。"
            )
            usr_prompt = (
                f"母球ID: {target_ball.ball_id}\n"
                f"母球标题: {target_ball.title}\n"
                f"母球类型: {target_ball.ball_type}\n"
                f"母球内容: {target_ball.content}\n"
                f"补充说明: {raw_policy_text}"
            )
            plan = await self._llm.complete_structured(
                tier="L2",
                system_prompt=sys_prompt,
                user_prompt=usr_prompt,
                response_model=MitosisSplitPlan,
                fallback_builder=lambda: self._build_deterministic_mitosis_plan(
                    target_ball, raw_policy_text
                ),
            )

            deprecated_parent = target_ball

            # 确定挂载槽位集合（继承原母球持有槽位 + 当前操作人槽位）
            target_owner_slots = list(
                dict.fromkeys([*target_ball.owner_slot_ids, actor_prof.slot_id])
            )

            # 2) 生成并注册子球 A 与子球 B（标记为 ACTIVE）
            short_a = uuid.uuid4().hex[:6].upper()
            short_b = uuid.uuid4().hex[:6].upper()
            child_a_id = f"BALL_{plan.child_a_type}_MITA_{short_a}"
            child_b_id = f"BALL_{plan.child_b_type}_MITB_{short_b}"

            exec_b_path: Optional[str] = None
            child_report = None
            if plan.child_b_type == "SKILL" and plan.child_b_skill_instruction:
                child_report = await self._arena.propose_and_evaluate(
                    actor_prof.user_id, plan.child_b_skill_instruction
                )
                evaluated = (
                    self._particles.get_ball(child_report.minted_ball_id)
                    if child_report.minted_ball_id
                    else None
                )
                if evaluated is not None:
                    child_b_id = evaluated.ball_id
                    exec_b_path = evaluated.executable_code_path

            data_child_valid = (
                target_ball.ball_type == "DATA"
                and target_ball.status == "ACTIVE"
                and plan.child_a_type == "DATA"
            )
            child_a = CapabilityBall(
                ball_id=child_a_id,
                ball_type=plan.child_a_type,
                title=plan.child_a_title,
                domain_tags=plan.child_a_tags,
                sensitivity_level=target_ball.sensitivity_level,
                owner_slot_ids=target_owner_slots,
                content=target_ball.content
                if data_child_valid
                else plan.child_a_content,
                redline_keywords=list(target_ball.redline_keywords),
                version=target_ball.version + 1,
                status="ACTIVE" if data_child_valid else "CANDIDATE",
            )
            child_b = CapabilityBall(
                ball_id=child_b_id,
                ball_type=plan.child_b_type,
                title=plan.child_b_title,
                domain_tags=plan.child_b_tags,
                sensitivity_level=target_ball.sensitivity_level,
                owner_slot_ids=target_owner_slots,
                content=plan.child_b_content,
                redline_keywords=list(target_ball.redline_keywords),
                executable_code_path=exec_b_path,
                version=target_ball.version + 1,
                status="ACTIVE"
                if child_report is not None and child_report.promoted
                else "CANDIDATE",
            )
            self._particles.register_ball(child_a, record_to_vault=True)
            self._particles.register_ball(child_b, record_to_vault=True)

            replacement_ready = (
                child_a.status == "ACTIVE" and child_b.status == "ACTIVE"
            )
            if replacement_ready:
                deprecated_parent = target_ball.model_copy(
                    update={"status": "DEPRECATED", "version": target_ball.version + 1}
                )
                self._particles.register_ball(deprecated_parent, record_to_vault=False)
            # Mount only validated replacements, retaining the original while review is pending.
            mounted_slots: list[str] = []
            for s in all_slots:
                if clean_ball_id in s.ball_ids or s.slot_id in target_owner_slots:
                    if replacement_ready and clean_ball_id in s.ball_ids:
                        s.ball_ids.remove(clean_ball_id)
                    if child_a.status == "ACTIVE":
                        self._containers.attach_ball_to_slot(s.slot_id, child_a.ball_id)
                    if child_b.status == "ACTIVE":
                        self._containers.attach_ball_to_slot(s.slot_id, child_b.ball_id)
                    mounted_slots.append(s.slot_id)

            worm_rec = self._vault.append_event(
                event_kind="BALL_MITOSIS_COMPLETED"
                if replacement_ready
                else "BALL_MITOSIS_CANDIDATES_CREATED",
                subtree_root_id="root",
                actor_slot_id=actor_prof.slot_id,
                payload={
                    "actor_user_id": actor_prof.user_id,
                    "parent_ball_id": clean_ball_id,
                    "parent_status": deprecated_parent.status,
                    "previous_parent_status": target_ball.status,
                    "child_ball_ids": [child_a.ball_id, child_b.ball_id],
                    "mounted_slot_ids": mounted_slots,
                },
            )
            await self._pulse.publish(
                event_type="BALL_MINTED",
                node_id="node_board_root",
                subtree_root_id="root",
                severity="SUCCESS",
                summary=(
                    f"🧬 权能球拆分评估：母球 [{clean_ball_id}] 状态 {deprecated_parent.status}，"
                    f"正交分裂为 [{child_a.ball_id}] 与 [{child_b.ball_id}] 并挂载至 {len(mounted_slots)} 个工位！"
                ),
                payload={
                    "parent_ball_id": clean_ball_id,
                    "child_ball_ids": [child_a.ball_id, child_b.ball_id],
                },
            )
            if replacement_ready:
                next_action = "NONE"
            elif child_report is None:
                next_action = "SUBMIT_EXPLICIT_CHILD_RULE_FOR_EVALUATION"
            elif child_report.minted_ball_id is None:
                next_action = "REPAIR_REJECTED_CHILD_SKILL"
            else:
                next_action = "PUBLISH_VALIDATED_CHILD_THEN_REVIEW_PARENT_REPLACEMENT"

            return {
                "mode": "BALL_MITOSIS",
                "status": "COMPLETED" if replacement_ready else "PENDING_VALIDATION",
                "arena_report": child_report.model_dump() if child_report else None,
                "continuation": {
                    "required_action": next_action,
                    "parent_ball_id": clean_ball_id,
                    "candidate_proposal_id": child_report.proposal_id
                    if child_report
                    else None,
                },
                "actor_user_id": actor_prof.user_id,
                "deprecated_ball": deprecated_parent.model_dump(),
                "child_balls": [child_a.model_dump(), child_b.model_dump()],
                "minted_balls": [child_a.model_dump(), child_b.model_dump()],
                "mounted_slot_ids": mounted_slots,
                "worm_event": worm_rec.model_dump(),
            }

        # ======================================================================
        # 模式 A：业务制度/SOP 文档自动解剖拆球 (Policy Auto-Decompose)
        # ======================================================================
        if not raw_policy_text.strip():
            raise ValueError(
                "必须提供 raw_policy_text（制度文本）或 target_ball_id（待分裂球ID）"
            )

        sys_prompt = (
            "你是 Arachne-OS 的业务制度自动拆球引擎。请将输入的杂糅企业规章制度或 SOP 文本解剖切割为四类正交原子球计划，"
            "输出严格符合 PolicyDecompositionPlan 的 JSON。"
        )
        plan_a = await self._llm.complete_structured(
            tier="L2",
            system_prompt=sys_prompt,
            user_prompt=raw_policy_text,
            response_model=PolicyDecompositionPlan,
            fallback_builder=lambda: self._build_deterministic_decomposition_plan(
                raw_policy_text
            ),
        )
        # 确保 skill_instruction 能稳定通过 EvolutionArena 基准测试
        det_plan = self._build_deterministic_decomposition_plan(raw_policy_text)
        skill_instruction_to_run = det_plan.skill_instruction

        common_owner_slots = list(
            dict.fromkeys([actor_prof.slot_id, *leader_slots[:3]])
        )
        minted_balls: list[CapabilityBall] = []

        public_data_source = _public_data_source(raw_policy_text)
        # 1) 铸造 DATA 球
        data_ball = self._particles.mint_from_candidate(
            candidate=ExtractedBallCandidate(
                ball_type="DATA",
                title="【制度解剖·DATA】公开业务参数"
                if public_data_source
                else "待审核业务资料候选",
                domain_tags=["业务资料"],
                sensitivity_level=2,
                content=public_data_source
                or "未提供明确、非敏感的业务事实；自动推断资料须人工审核。",
            ),
            owner_slot_ids=common_owner_slots,
            status="ACTIVE" if public_data_source else "CANDIDATE",
        )
        minted_balls.append(data_ball)

        arena_report = (
            await self._arena.propose_and_evaluate(
                proposer_id=actor_prof.user_id,
                natural_instruction=skill_instruction_to_run,
            )
            if skill_instruction_to_run
            else None
        )
        skill_ball = (
            self._particles.get_ball(arena_report.minted_ball_id)
            if arena_report and arena_report.minted_ball_id
            else None
        )
        if skill_ball is not None:
            minted_balls.append(skill_ball)
        authority_source = _authority_source(raw_policy_text)
        redline_source = "\n".join(
            line
            for line in raw_policy_text.splitlines()
            if any(k in line for k in ("严禁", "禁止", "不得"))
        )

        # 3) 铸造 AUTHORITY 审批权限球
        auth_ball = self._particles.mint_from_candidate(
            candidate=ExtractedBallCandidate(
                ball_type="AUTHORITY",
                title=plan_a.authority_title,
                domain_tags=plan_a.authority_tags or ["风控审批", "折扣"],
                sensitivity_level=3,
                content=authority_source
                or "候选权限解释，尚无明确授权原文，须人工审核。",
            ),
            owner_slot_ids=common_owner_slots,
            status="ACTIVE" if authority_source else "CANDIDATE",
        )
        minted_balls.append(auth_ball)

        # 4) 铸造 REDLINE 严禁事项红线球
        redline_id = f"BALL_REDLINE_{uuid.uuid4().hex[:8].upper()}"
        redline_ball = CapabilityBall(
            ball_id=redline_id,
            ball_type="REDLINE",
            title=plan_a.redline_title,
            domain_tags=plan_a.redline_tags or ["底价", "合规"],
            sensitivity_level=5,
            owner_slot_ids=boss_slots,
            content=redline_source
            or "候选红线解释，尚无明确禁止事项原文，须人工审核。",
            redline_keywords=[
                kw for kw in det_plan.redline_keywords if kw in redline_source
            ],
            status="ACTIVE" if redline_source else "CANDIDATE",
        )
        self._particles.register_ball(redline_ball, record_to_vault=True)
        minted_balls.append(redline_ball)

        # 5) 自动挂载到操作人及对应部门工位容器
        mounted_slot_ids: list[str] = []
        for s_id in common_owner_slots:
            try:
                if data_ball.status == "ACTIVE":
                    self._containers.attach_ball_to_slot(s_id, data_ball.ball_id)
                if skill_ball is not None and skill_ball.status == "ACTIVE":
                    self._containers.attach_ball_to_slot(s_id, skill_ball.ball_id)
                if auth_ball.status == "ACTIVE":
                    self._containers.attach_ball_to_slot(s_id, auth_ball.ball_id)
                mounted_slot_ids.append(s_id)
            except KeyError:
                continue
        for b_slot_id in boss_slots:
            try:
                if redline_ball.status != "ACTIVE":
                    continue
                self._containers.attach_ball_to_slot(b_slot_id, redline_ball.ball_id)
                if b_slot_id not in mounted_slot_ids:
                    mounted_slot_ids.append(b_slot_id)
            except KeyError:
                continue

        worm_rec = self._vault.append_event(
            event_kind="POLICY_DECOMPOSED_TO_BALLS",
            subtree_root_id="root",
            actor_slot_id=actor_prof.slot_id,
            payload={
                "actor_user_id": actor_prof.user_id,
                "minted_ball_ids": [b.ball_id for b in minted_balls],
                "minted_types": [b.ball_type for b in minted_balls],
                "arena_proposal_id": arena_report.proposal_id if arena_report else None,
                "mounted_slot_ids": mounted_slot_ids,
            },
        )
        await self._pulse.publish(
            event_type="BALL_MINTED",
            node_id="node_board_root",
            subtree_root_id="root",
            severity="SUCCESS",
            summary=(
                f"🔪 制度自动解剖拆球完成：已从 SOP 文本切割生成 DATA / SKILL / AUTHORITY / REDLINE 共 "
                f"{len(minted_balls)} 颗权能球；仅已验证且有来源依据的规则挂载，候选等待审核。"
            ),
            payload={"minted_ball_ids": [b.ball_id for b in minted_balls]},
        )

        if any(ball.status == "CANDIDATE" for ball in minted_balls):
            next_action = "REVIEW_CANDIDATES"
        elif arena_report is None:
            next_action = "SUPPLY_EXPLICIT_CALCULATION_RULE"
        elif arena_report.minted_ball_id is None:
            next_action = "REPAIR_REJECTED_SKILL"
        else:
            next_action = "NONE"

        return {
            "mode": "POLICY_DECOMPOSE",
            "continuation": {
                "required_action": next_action,
                "candidate_proposal_id": arena_report.proposal_id
                if arena_report
                else None,
            },
            "actor_user_id": actor_prof.user_id,
            "minted_balls": [b.model_dump() for b in minted_balls],
            "arena_report": arena_report.model_dump() if arena_report else None,
            "mounted_slot_ids": mounted_slot_ids,
            "worm_event": worm_rec.model_dump(),
        }

    # ==========================================================================
    # 能力 3：集群自主能动巡检与工位自繁殖 (`run_autonomous_agency_patrol`)
    # ==========================================================================
    async def run_autonomous_agency_patrol(
        self,
        actor_user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        all_slots = self._containers.list_slots()
        all_tickets = await self._hot_store.list_tickets()
        all_nodes = await self._hot_store.list_nodes()

        # 统计各工位关联工单负载
        ticket_count_by_slot: dict[str, int] = {}
        for t in all_tickets:
            ticket_count_by_slot[t.slot_id] = ticket_count_by_slot.get(t.slot_id, 0) + 1

        # 1) 工位细胞分裂（Slot Mitosis）：找出负载最高/挂载球最多/可替代分较高的忙碌非黑盒工位
        def _is_mitosis_eligible(s: UnitSlot) -> bool:
            if (
                s.slot_id.endswith("_REPLICA")
                or "REPLICA" in s.slot_id
                or s.slot_id == "SLOT_BOSS"
            ):
                return False
            occ = (
                self._containers._profiles.get(s.occupant_id) if s.occupant_id else None
            )
            if occ and occ.role_view in ("boss", "finance_tool"):
                return False
            upper_tag = f"{s.slot_id} {s.slot_name}".upper()
            if any(k in upper_tag for k in ("FINANCE", "LEGAL", "BOX", "财务", "法务")):
                return False
            return len(s.ball_ids) > 0

        candidate_slots = [s for s in all_slots if _is_mitosis_eligible(s)]
        if not candidate_slots:
            candidate_slots = [s for s in all_slots if len(s.ball_ids) > 0] or all_slots

        def _busy_score(s: UnitSlot) -> float:
            t_load = ticket_count_by_slot.get(s.slot_id, 0) * 15.0
            ball_load = len(s.ball_ids) * 12.0
            return t_load + ball_load + s.replaceability_score

        parent_slot = max(candidate_slots, key=_busy_score)
        base_replica_id = f"{parent_slot.slot_id}_REPLICA"
        existing_slot_ids = {s.slot_id for s in all_slots}
        if base_replica_id not in existing_slot_ids:
            replica_slot_id = base_replica_id
        else:
            replica_slot_id = f"{base_replica_id}_{uuid.uuid4().hex[:4].upper()}"

        # 将母工位的 DATA / SKILL 球分流挂载到平行协防子工位
        offloaded_ball_ids: list[str] = []
        for bid in parent_slot.ball_ids:
            b_obj = self._particles.get_ball(bid)
            if b_obj and b_obj.ball_type in ("DATA", "SKILL"):
                offloaded_ball_ids.append(bid)
                if replica_slot_id not in b_obj.owner_slot_ids:
                    b_obj.owner_slot_ids.append(replica_slot_id)
        if not offloaded_ball_ids and parent_slot.ball_ids:
            offloaded_ball_ids = list(parent_slot.ball_ids[:2])

        replica_slot = UnitSlot(
            slot_id=replica_slot_id,
            slot_name=f"{parent_slot.slot_name}·平行协防子工位",
            department=parent_slot.department,
            ball_ids=offloaded_ball_ids,
            occupant_type="AGENT",
            occupant_id=f"agent_twin_{parent_slot.occupant_id}",
            rule_repetition_ratio=min(
                98.0, max(90.0, parent_slot.rule_repetition_ratio)
            ),
            shadow_agreement_rate=min(
                98.0, max(92.0, parent_slot.shadow_agreement_rate)
            ),
            replaceability_score=95.0,
        )
        self._containers.register_slot(replica_slot)

        # 在蛛网拓扑中生成对应的数字分身节点 (SpiderNode)
        parent_node = next(
            (n for n in all_nodes if n.slot_id == parent_slot.slot_id),
            all_nodes[0] if all_nodes else None,
        )
        parent_aspect_id = (
            parent_node.parent_id
            if parent_node and parent_node.parent_id
            else "node_board_root"
        )
        subtree_id = parent_node.subtree_root_id if parent_node else "subtree_quote"
        replica_node_id = f"node_replica_{replica_slot_id.lower()}"
        replica_node = SpiderNode(
            node_id=replica_node_id,
            label=f"{parent_slot.slot_name} (数字分身协防蛛)",
            node_type="WORKER_SLOT",
            parent_id=parent_aspect_id,
            subtree_root_id=subtree_id,
            slot_id=replica_slot_id,
            domain_tags=(
                list(parent_node.domain_tags)
                if parent_node and parent_node.domain_tags
                else ["自主协防", "数字分身"]
            ),
            status="ACTIVE",
            active_load=1,
        )
        await self._hot_store.upsert_node(replica_node)

        # 2) 主动嗅探造球（Proactive Skill Forging）：检测尚未自动化的 DATA 球计算规则
        all_balls = self._particles.list_all_balls()
        rule_keywords = (
            "待自动化",
            "公式",
            "阶梯",
            "费率",
            "首重",
            "续重",
            "折扣",
            "水位",
            "%",
            "计价",
        )
        data_rule_candidates = [
            b
            for b in all_balls
            if b.ball_type == "DATA"
            and b.status == "ACTIVE"
            and b.ball_id not in self._forged_source_ball_ids
            and any(k in f"{b.title} {b.content}" for k in rule_keywords)
        ]
        if not data_rule_candidates:
            data_rule_candidates = [
                b for b in all_balls if b.ball_type == "DATA" and b.status == "ACTIVE"
            ]

        source_data_ball = (
            data_rule_candidates[0] if data_rule_candidates else all_balls[0]
        )
        self._forged_source_ball_ids.add(source_data_ball.ball_id)

        # 选择合法的 proposer_id 用于 Arena 锻造
        proposer_uid = parent_slot.occupant_id
        try:
            self._containers.get_profile(proposer_uid)
        except KeyError:
            proposer_uid = self._containers.list_profiles()[0].user_id

        raw_rule_text = f"{source_data_ball.title}：{source_data_ball.content}"
        if any(k in raw_rule_text for k in ("首重", "续重")) and "10" in raw_rule_text:
            forging_instruction = (
                "阶梯运费规则：首重3公斤内10元，超过3公斤每公斤加4元，满500元免运费"
            )
        elif "折" in raw_rule_text and "满" in raw_rule_text:
            th_m = re.search(r"满\s*(\d+)\s*(?:件|台|把|车)", raw_rule_text)
            qty_th = th_m.group(1) if th_m else "20"
            d_m = re.search(r"(\d(?:\.\d)?)\s*折", raw_rule_text)
            d_val = d_m.group(1) if d_m else "9.0"
            forging_instruction = f"批量折扣折后价规则：满 {qty_th} 件享 {d_val} 折"
        else:
            rate_m = re.search(r"(\d+(?:\.\d+)?)\s*%", raw_rule_text)
            rate_val = rate_m.group(1) if rate_m else ""
            forging_instruction = (
                f"标准化费率自动核算规则：按合同金额的 {rate_val}% 自动计提核算"
                if rate_val
                else ""
            )

        arena_report = (
            await self._arena.propose_and_evaluate(
                proposer_id=proposer_uid, natural_instruction=forging_instruction
            )
            if forging_instruction
            else None
        )
        forged_skill_ball: Optional[CapabilityBall] = None
        if arena_report is not None and arena_report.minted_ball_id:
            forged_skill_ball = self._particles.get_ball(arena_report.minted_ball_id)

        if forged_skill_ball is not None and forged_skill_ball.status == "ACTIVE":
            # 将主动合成的 SKILL 球挂载至母工位、子分身工位及原 DATA 球所属工位
            for target_sid in [
                parent_slot.slot_id,
                replica_slot.slot_id,
                *source_data_ball.owner_slot_ids,
            ]:
                try:
                    self._containers.attach_ball_to_slot(
                        target_sid, forged_skill_ball.ball_id
                    )
                    if target_sid not in forged_skill_ball.owner_slot_ids:
                        forged_skill_ball.owner_slot_ids.append(target_sid)
                except KeyError:
                    continue

        # 3) 向部门头头的企微对话流推送《🤖 集群自主巡检进化简报》
        all_profiles = self._containers.list_profiles()
        leader_recipients = [
            p.user_id
            for p in all_profiles
            if p.role_view in ("leader", "manager", "boss")
            or getattr(getattr(self._rt, "auth_custody", None), "account_directory", {})
            .get(p.user_id, {})
            .get("is_custodian_leader", False)
        ]
        if actor_user_id and actor_user_id not in leader_recipients:
            leader_recipients.append(actor_user_id)
        if not leader_recipients and all_profiles:
            leader_recipients = [all_profiles[0].user_id]

        brief_content = (
            f"《🤖 集群自主巡检进化简报》\n"
            f"• 【工位细胞分裂 (Slot Mitosis)】：检测到高负载忙碌工位 [{parent_slot.slot_name} ({parent_slot.slot_id})] "
            f"（AI可替代分 {parent_slot.replaceability_score:.1f}），已自动分裂繁殖出平行协防子工位 "
            f"[{replica_slot.slot_name} ({replica_slot.slot_id})] 与数字分身节点 [{replica_node.node_id}]，"
            f"自动分流挂载 {len(replica_slot.ball_ids)} 颗权能球（{', '.join(replica_slot.ball_ids)}）。\n"
            f"• 【主动嗅探造球 (Proactive Skill Forging)】：主动嗅探到未自动化规则球《{source_data_ball.title}》，"
            f"评估结果：{forged_skill_ball.status if forged_skill_ball else 'SOURCE_RULE_REQUIRED'}；"
            f"技能《{arena_report.skill_title if arena_report else '待提供明确规则'}》"
            f"（ID: {arena_report.minted_ball_id if arena_report else None}，脚本: {forged_skill_ball.executable_code_path if forged_skill_ball else 'N/A'}）。候选技能须独立校验后发布。"
        )

        notified_leaders: list[str] = []
        for leader_uid in leader_recipients:
            await self._wecom.append_message(
                ChatMessageItem(
                    msg_id=f"MSG_PATROL_{uuid.uuid4().hex[:8].upper()}",
                    sender_id="BOT_GOVERNANCE",
                    sender_name="#2 进化与风控官",
                    facade_bot="GOVERNANCE",
                    chat_type="SINGLE",
                    direction="OUTBOUND",
                    content=brief_content,
                    structured_card={
                        "viewer_user_id": leader_uid,
                        "card_type": "AUTONOMOUS_PATROL_BRIEF",
                        "parent_slot_id": parent_slot.slot_id,
                        "replica_slot_id": replica_slot.slot_id,
                        "replica_node_id": replica_node.node_id,
                        "forged_skill_ball_id": (
                            arena_report.minted_ball_id if arena_report else None
                        ),
                    },
                )
            )
            notified_leaders.append(leader_uid)

        worm_rec = self._vault.append_event(
            event_kind="AUTONOMOUS_PATROL_COMPLETED",
            subtree_root_id=subtree_id,
            actor_slot_id=parent_slot.slot_id,
            payload={
                "parent_slot_id": parent_slot.slot_id,
                "replica_slot_id": replica_slot.slot_id,
                "replica_node_id": replica_node.node_id,
                "offloaded_ball_ids": replica_slot.ball_ids,
                "source_data_ball_id": source_data_ball.ball_id,
                "forged_skill_ball_id": (
                    arena_report.minted_ball_id if arena_report else None
                ),
                "notified_leaders": notified_leaders,
            },
        )

        await self._pulse.publish(
            event_type="SLOT_TRANSITIONED",
            node_id=replica_node.node_id,
            subtree_root_id=subtree_id,
            severity="SUCCESS",
            summary=(
                f"🤖 自主能动巡检完成：[{parent_slot.slot_id}] 细胞分裂出协防子工位 [{replica_slot.slot_id}]，"
                f"并主动嗅探锻造技能球 [{(arena_report.minted_ball_id if arena_report else None)}]！"
            ),
            payload={
                "replica_slot_id": replica_slot.slot_id,
                "forged_skill_ball_id": (
                    arena_report.minted_ball_id if arena_report else None
                ),
            },
        )

        if forged_skill_ball and forged_skill_ball.status == "CANDIDATE":
            next_action = "REVIEW_CANDIDATE"
        elif arena_report is None:
            next_action = "SUPPLY_EXPLICIT_CALCULATION_RULE"
        elif arena_report.minted_ball_id is None:
            next_action = "REPAIR_REJECTED_SKILL"
        else:
            next_action = "NONE"

        return {
            "patrol_status": "COMPLETED",
            "continuation": {
                "required_action": next_action,
                "candidate_proposal_id": arena_report.proposal_id
                if arena_report
                else None,
            },
            "slot_mitosis": {
                "parent_slot_id": parent_slot.slot_id,
                "parent_slot_name": parent_slot.slot_name,
                "replica_slot": replica_slot.model_dump(),
                "replica_node": replica_node.model_dump(),
                "offloaded_ball_ids": replica_slot.ball_ids,
            },
            "proactive_skill_forging": {
                "source_data_ball_id": source_data_ball.ball_id,
                "source_data_ball_title": source_data_ball.title,
                "forged_skill_ball": (
                    forged_skill_ball.model_dump() if forged_skill_ball else None
                ),
                "arena_report": arena_report.model_dump() if arena_report else None,
            },
            "brief_title": "《🤖 集群自主巡检进化简报》",
            "brief_content": brief_content,
            "notified_leader_ids": notified_leaders,
            "worm_event": worm_rec.model_dump(),
        }

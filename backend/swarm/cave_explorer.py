from __future__ import annotations

import re
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from core.auth_custody import (
    AuthAndCustodyService,
    hash_password,
)
from core.topology_resolver import (
    resolve_blackbox_user_and_slot,
    resolve_leader_user_and_slot,
)
from core.schemas import (
    BallType,
    CapabilityBall,
    ChatMessageItem,
    DualEmployeeProfile,
    EmployeeViewA,
    ManagementViewB,
    NodeType,
    RoleViewType,
    SpiderNode,
    UnitSlot,
    utc_now_iso,
)
from swarm.capability_lifecycle import TYPE_LABELS, build_quick_use_prompt
from swarm.genesis_fission import EnterpriseGenesisAndFissionEngine

STARTER_DOSSIERS: list[dict[str, Any]] = [
    {
        "dossier_id": "dossier_jlcpcb",
        "enterprise_name": "深圳嘉立创科技集团股份有限公司",
        "industry": "电子产业一站式智造平台",
        "summary": "涵盖PCB打样智造、立创EDA、立创商城元器件配单与SMT贴片，严格执行Gerber工艺保密、8.5折风控特批与13%增值税专票合规。",
        "raw_org_material": (
            "公司名称：深圳嘉立创科技集团股份有限公司（JLCPCB & 立创商城）。\n"
            "组织部门与岗位分工：\n"
            "1. 【CAM 工程审单与客户服务部】：负责客户 Gerber 工艺可制造性初审、PCB/SMT 在线实时计价及异常工程确认沟通；"
            "设「CAM审单与报价专员」（employee）和「工程风控与客诉复核组长」（leader，大批量低于8.5折或客诉赔付超300元必须由其特批）。\n"
            "2. 【立创商城元器件采销与仓储部】：负责百万级SKU现货采购、BOM一键配单锁库及重货快递打包发运（首重3公斤12元、续重4元/kg、满500免基础运费）；"
            "设「BOM配单与仓储专员」（employee）。\n"
            "3. 【PCB与SMT数字化智造部】：统筹1-64层高多层板拼版排产、激光钢网开制与AOI/X-Ray贴片质检交付；"
            "设「PCB/SMT智造排产主管」（manager）。\n"
            "4. 【集团财税结算与知识产权合规部】：专职核验账号主体一致性并开具13%增值税专用发票，严密隔离客户Gerber源码及覆铜板长协拿货底价；"
            "设「增值税专票税控专岗」（finance_tool）。"
        ),
    },
    {
        "dossier_id": "dossier_hangzhou_apparel",
        "enterprise_name": "杭州丝语女装柔性快反工厂",
        "industry": "服装柔性制造",
        "summary": "小单快反制衣厂，涵盖面辅料采购、版房制样、车间排产、尾货渠道与财务结算。",
        "raw_org_material": (
            "公司名称：杭州丝语女装柔性快反工厂。\n"
            "组织部门与岗位分工：\n"
            "1. 【市场接单与跟单部】：对接直播电商与品牌方小单快反报价，负责日常报价核算与大货跟单；设「大货报价跟单专员」和「跟单审批组长」。\n"
            "2. 【面辅料采购与仓储部】：管理真丝/醋酸面料供应商比价、急单调拨及面辅料安全库存；设「面辅料采购专员」。\n"
            "3. 【版房车间与品控部】：负责首件打版、车缝工序排产及出厂 AQL 抽检；设「车间排产主管」。\n"
            "4. 【财务与税控结算部】：负责客户对账单核验、增值税专票开具与供应商尾款拨付；设「财务开票专岗」。"
        ),
    },
    {
        "dossier_id": "dossier_dental_clinic",
        "enterprise_name": "微笑树连锁数字化口腔机构",
        "industry": "连锁医疗服务",
        "summary": "5家同城口腔门店，涵盖咨询接诊、正畸种植方案、耗材供应链及医保财务合规。",
        "raw_org_material": (
            "公司名称：微笑树连锁数字化口腔机构。\n"
            "组织部门与岗位分工：\n"
            "1. 【患者接诊与美学咨询部】：负责到店初诊建档、隐形正畸与种植方案报价沟通；设「口腔咨询顾问」和「接诊风控组长」。\n"
            "2. 【医务耗材与技工供应链部】：负责种植体、全瓷牙冠、隐形矫治器采购入库及冷链批号追踪；设「医用耗材管理专员」。\n"
            "3. 【医疗质量与运营管理部】：统筹多门店医生排班、术后随访满意度与大额减免复核；设「连锁运营主管」。\n"
            "4. 【医保对账与财务开票部】：负责医疗收费票据核销、医保结算申报及患者隐私合规审计；设「财务票据专岗」。"
        ),
    },
    {
        "dossier_id": "dossier_smarthome_ecom",
        "enterprise_name": "云栖智造跨境智能家居团队",
        "industry": "跨境品牌电商",
        "summary": "欧美亚马逊及独立站智能灯具卖家，涵盖选品运营、海外仓备货、广告风控与资金回款。",
        "raw_org_material": (
            "公司名称：云栖智造跨境智能家居团队。\n"
            "组织部门与岗位分工：\n"
            "1. 【欧美渠道与达人运营部】：负责亚马逊及 TikTok 达人带货分佣核算与大促折扣活动；设「渠道运营专员」和「运营审批组长」。\n"
            "2. 【海外仓备货与头程物流部】：负责美西/欧洲海外仓补货水位测算、空海派运费核算；设「海外仓物流专员」。\n"
            "3. 【产品研发与品控管理部】：管控智能灯具 FCC/CE 认证、固件良率与爆品 BOM 成本；设「供应链统筹主管」。\n"
            "4. 【跨境财税与结汇部】：负责 VAT 税务申报、收款结汇核对与红线发票开具；设「跨境财务专岗」。"
        ),
    },
]


class ScoutAspectSpec(BaseModel):
    node_id: str
    label: str
    subtree_root_id: str
    domain_tags: list[str] = Field(default_factory=list)


class ScoutPositionSpec(BaseModel):
    node_id: str
    label: str
    person_name: str
    title: str
    department: str
    role_view: RoleViewType
    node_type: NodeType
    parent_aspect_id: str
    subtree_root_id: str
    user_id: str
    slot_id: str
    supervisor_id: Optional[str] = None
    is_custodian_leader: bool = False
    domain_tags: list[str] = Field(default_factory=list)


class ScoutBlueprint(BaseModel):
    enterprise_name: str
    aspects: list[ScoutAspectSpec]
    positions: list[ScoutPositionSpec]


class TorchWeaveItemSpec(BaseModel):
    ball_type: BallType
    title: str
    domain_tags: list[str] = Field(default_factory=list)
    sensitivity_level: int = Field(default=2, ge=1, le=5)
    content: str
    skill_instruction: Optional[str] = None
    redline_keywords: list[str] = Field(default_factory=list)


class TorchWeavePlan(BaseModel):
    node_summary: str
    items: list[TorchWeaveItemSpec]


def _slug_id(prefix: str, idx: int) -> str:
    return f"{prefix}_{idx}_{uuid.uuid4().hex[:5]}"


class CaveExplorationEngine:
    """
    矿洞火把探路与二维织网引擎：
    1. 空壳冷启动 (`reset_to_empty_shell`)：清零所有预设部门/岗位/能力规则，仅留中央 1 颗初始火种节点；
    2. 拿火把探路 (`scout_organization_structure`)：读取真实企业资料，摸清部门与岗位骨架，生成冷灰色待照亮节点 (`SCOUTED`)；
    3. 插火把照亮并织网 (`plant_torch_and_weave`)：在选定节点驻留火把 (`LIT`)，真实提炼业务资料、编译可执行脚本工具、确立审批与底线，并自动在已点亮节点间拉起跨岗协作丝线。
    """

    def __init__(self, runtime: Any) -> None:
        self._rt = runtime
        self._vault = runtime.vault
        self._hot_store = runtime.hot_store
        self._particles = runtime.particles
        self._containers = runtime.containers
        self._human_tools = runtime.human_tools
        self._pulse = runtime.pulse_bus
        self._llm = runtime.llm_gateway
        self._wecom = runtime.wecom

        self.workspace_id = uuid.uuid4().hex
        self.workspace_epoch = uuid.uuid4().hex
        self.enterprise_name: str = ""
        self.raw_org_material: str = ""
        self.node_owned_ball_ids: dict[str, list[str]] = {}
        self.cross_links: list[dict[str, Any]] = []
        self.exploration_logs: list[dict[str, Any]] = []
        self.mode: str = "DEMO_SEED"

    def export_meta_state(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "workspace_epoch": self.workspace_epoch,
            "enterprise_name": self.enterprise_name,
            "raw_org_material": self.raw_org_material,
            "node_owned_ball_ids": {k: list(v) for k, v in self.node_owned_ball_ids.items()},
            "cross_links": list(self.cross_links),
            "exploration_logs": list(self.exploration_logs),
            "mode": self.mode,
        }

    def restore_meta_state(self, meta: dict[str, Any] | None, *, fallback_enterprise_name: str = "") -> None:
        if not meta:
            return
        self.workspace_id = str(meta.get("workspace_id") or self.workspace_id)
        self.workspace_epoch = str(meta.get("workspace_epoch") or self.workspace_epoch)
        self.enterprise_name = str(meta.get("enterprise_name") or fallback_enterprise_name or "")
        self.raw_org_material = str(meta.get("raw_org_material") or "")
        self.node_owned_ball_ids = {
            str(k): list(v) for k, v in dict(meta.get("node_owned_ball_ids") or {}).items()
        }
        self.cross_links = list(meta.get("cross_links") or [])
        self.exploration_logs = list(meta.get("exploration_logs") or [])
        self.mode = str(meta.get("mode") or self.mode)

    def _get_auth_custody(self) -> AuthAndCustodyService:
        svc = getattr(self._rt, "auth_custody", None)
        if svc is None:
            svc = AuthAndCustodyService(
                vault=self._vault,
                particles=self._particles,
                containers=self._containers,
            )
            setattr(self._rt, "auth_custody", svc)
        return svc

    def _get_genesis_engine(self) -> EnterpriseGenesisAndFissionEngine:
        eng = getattr(self._rt, "genesis_engine", None)
        if eng is None:
            eng = EnterpriseGenesisAndFissionEngine(runtime=self._rt)
            setattr(self._rt, "genesis_engine", eng)
        return eng

    def _append_log(self, stage: str, message: str, node_id: Optional[str] = None) -> None:
        self.exploration_logs.append(
            {
                "log_id": f"LOG_{uuid.uuid4().hex[:6].upper()}",
                "stage": stage,
                "message": message,
                "node_id": node_id,
                "timestamp": utc_now_iso(),
            }
        )
        if len(self.exploration_logs) > 40:
            self.exploration_logs = self.exploration_logs[-40:]

    async def reset_to_empty_shell(self, enterprise_name: str = "待探索企业") -> dict[str, Any]:
        old = await self._rt.capture_state() if hasattr(self._rt, "capture_state") else None
        try:
            result = await self._reset_to_empty_shell(enterprise_name)
            if hasattr(self._rt, "sync_persistence"):
                await self._rt.sync_persistence()
            return result
        except BaseException:
            if old is not None:
                await self._rt.restore_runtime_state(old, preserve_security=False)
                if hasattr(self._rt, "sync_persistence"):
                    await self._rt.sync_persistence()
            raise

    async def _reset_to_empty_shell(
        self, enterprise_name: str = "待探索企业"
    ) -> dict[str, Any]:
        clean_name = enterprise_name.strip() or "待探索企业"
        self.workspace_id = uuid.uuid4().hex
        self.workspace_epoch = uuid.uuid4().hex
        if hasattr(self._rt, "clear_workspace_runtime"):
            self._rt.clear_workspace_runtime()
        self.enterprise_name = clean_name
        self.raw_org_material = ""
        self.node_owned_ball_ids = {}
        self.cross_links = []
        self.exploration_logs = []
        self.mode = "EMPTY_SHELL"

        # 清空所有业务容器、能力规则、向量索引、消息队列与黑盒审批卡片
        self._containers._slots.clear()
        self._containers._profiles.clear()
        self._containers.clear_slot_aliases()
        self._containers.register_slot_alias("SLOT_BOSS", "node_board_root")
        self._particles._balls.clear()
        self._particles._vectors.clear()
        self._wecom.reset_messages()
        if hasattr(self._human_tools, "restore_state"):
            self._human_tools.restore_state({"contracts": [], "cards": []})
        connectors = getattr(self._rt, "connectors", None)
        if connectors is not None and hasattr(connectors, "restore_state"):
            connectors.restore_state({"bindings": [], "callback_receipts": {}, "dispatch_history": []})

        await self._hot_store.restore_global_state(
            {"nodes": [], "tickets": [], "leases": []}
        )

        # 仅保留初始总控身份及当前密码；旧会话全部撤销，需重新登录。
        auth_svc = self._get_auth_custody()
        boss_slot = UnitSlot(
            slot_id="SLOT_BOSS",
            slot_name="初始火种总控台",
            department="初始探路营地",
            ball_ids=[],
            occupant_type="HUMAN",
            occupant_id="boss_lin",
            rule_repetition_ratio=10.0,
            shadow_agreement_rate=10.0,
            replaceability_score=10.0,
        )
        self._containers.register_slot(boss_slot)
        boss_profile = DualEmployeeProfile(
            user_id="boss_lin",
            name="探路总控",
            title="创始管理员",
            role_view="boss",
            slot_id="SLOT_BOSS",
            employee_view=EmployeeViewA(
                skill_tags=["企业探路", "组织织网"],
                saved_hours=0.0,
                evolution_contributions=[],
                innovation_bonus=0.0,
            ),
            management_view=ManagementViewB(
                avg_latency_ms=200.0,
                rework_rate=0.0,
                boundary_probes=0,
                base_fulfillment_score=100.0,
                performance_score=95.0,
            ),
        )
        self._containers.register_profile(boss_profile)
        auth_svc.reset_workspace_identity({
            "boss_lin": {"department": "初始探路营地", "supervisor_id": None, "is_custodian_leader": True}
        }, preserve_password_user_ids={"boss_lin"})

        root_node = SpiderNode(
            node_id="node_board_root",
            label=f"{clean_name} · 初始火种集群",
            node_type="BOARD_ROOT",
            parent_id=None,
            subtree_root_id="root",
            slot_id="SLOT_BOSS",
            domain_tags=["初始火种", "空壳态"],
            status="ACTIVE",
            active_load=1,
            exploration_state="LIT",
            torch_planted=True,
            discovered_from="空壳冷启动 · 等待拿火把探路",
        )
        await self._hot_store.upsert_node(root_node)

        await self._wecom.append_message(
            ChatMessageItem(
                msg_id=f"MSG_SHELL_{uuid.uuid4().hex[:6]}",
                sender_id="BOT_BOARD_INSIDER",
                sender_name="探路向导",
                facade_bot="BOARD_INSIDER",
                chat_type="SINGLE",
                direction="OUTBOUND",
                structured_card={"viewer_user_id": "boss_lin"},
                content=(
                    f"已重置为「{clean_name}」空瓶壳子。当前除初始总控集群外，尚未建立任何部门、岗位或业务规则。"
                    "请前往「探索与织网」画布，喂入企业资料并拿火把探路。"
                ),
            )
        )

        self._append_log("EMPTY_SHELL", f"已清零所有预设内容，仅保留「{clean_name}」初始火种集群", "node_board_root")
        await self._pulse.publish(
            event_type="ASPECT_CLUSTERED",
            node_id="node_board_root",
            subtree_root_id="root",
            severity="INFO",
            summary=f"矿洞已重置为空瓶壳子：{clean_name}（仅保留 1 个初始火种）",
            payload={"mode": "EMPTY_SHELL"},
        )
        return await self.get_cave_map_state()

    def _fallback_scout_blueprint(
        self, enterprise_name: str, raw_org_material: str
    ) -> ScoutBlueprint:
        text = raw_org_material.strip()
        # 1) 优先从文本提取【xxx部门】或 `xxx部/中心/组`
        bracket_depts = re.findall(r"【([^】]{2,18})】", text)
        suffix_depts = re.findall(
            r"([\u4e00-\u9fffA-Za-z0-9]{2,12}(?:部|中心|车间|门店|组|院))", text
        )
        candidates: list[str] = []
        for d in bracket_depts + suffix_depts:
            cleaned = d.strip()
            if cleaned and cleaned not in candidates and not cleaned.endswith("公司"):
                candidates.append(cleaned)

        if any(k in text for k in ("女装", "制衣", "面辅料", "版房", "服装")):
            default_depts = ["市场接单与跟单部", "面辅料采购与仓储部", "版房车间与品控部", "财务与税控结算部"]
        elif any(k in text for k in ("口腔", "牙科", "医疗", "医院", "门诊", "患者")):
            default_depts = ["患者接诊与咨询部", "医用耗材供应链部", "医疗质量运营部", "医保与财务开票部"]
        elif any(k in text for k in ("跨境", "电商", "亚马逊", "达人", "海外仓", "MCN")):
            default_depts = ["渠道与达人运营部", "海外仓与物流部", "产研与供应链部", "跨境财税结算部"]
        else:
            default_depts = ["一线业务与交付部", "供应链与履约部", "运营管控部", "财务与合规结算部"]

        dept_names = (candidates[:4] if len(candidates) >= 3 else []) or default_depts
        while len(dept_names) < 3:
            for d in default_depts:
                if d not in dept_names:
                    dept_names.append(d)
                if len(dept_names) >= 3:
                    break
        dept_names = dept_names[:4]

        aspects: list[ScoutAspectSpec] = []
        for idx, dname in enumerate(dept_names, start=1):
            aspects.append(
                ScoutAspectSpec(
                    node_id=f"node_aspect_scout_{idx}",
                    label=dname,
                    subtree_root_id=f"subtree_cave_{idx}",
                    domain_tags=[dname[:4], enterprise_name[:6]],
                )
            )

        # 提取文本里「xxx」提及的岗位名称
        quoted_roles = re.findall(r"「([^」]{2,16})」", text)

        def pick_role(idx: int, fallback: str) -> str:
            if idx < len(quoted_roles):
                return quoted_roles[idx]
            return fallback

        # 构建覆盖 员工 / 审批组长 / 财务专岗 / 主管 的 6 个待照亮岗位
        d1, d2, d3 = aspects[0], aspects[1], aspects[2]
        d_fin = aspects[-1]

        positions: list[ScoutPositionSpec] = [
            ScoutPositionSpec(
                node_id="node_pos_front_1",
                label=pick_role(0, f"{d1.label[:4]}业务专员"),
                person_name="林小雨",
                title=pick_role(0, "一线业务专员"),
                department=d1.label,
                role_view="employee",
                node_type="WORKER_SLOT",
                parent_aspect_id=d1.node_id,
                subtree_root_id=d1.subtree_root_id,
                user_id="cave_emp_1",
                slot_id="SLOT_CAVE_FRONT_1",
                supervisor_id="cave_leader_1",
                is_custodian_leader=False,
                domain_tags=["一线业务", "报价", "订单", d1.label[:4]],
            ),
            ScoutPositionSpec(
                node_id="node_pos_leader_1",
                label=pick_role(1, f"{d1.label[:4]}审批组长"),
                person_name="陈组长",
                title=pick_role(1, "业务审批组长"),
                department=d1.label,
                role_view="leader",
                node_type="RELAY_NODE",
                parent_aspect_id=d1.node_id,
                subtree_root_id=d1.subtree_root_id,
                user_id="cave_leader_1",
                slot_id="SLOT_CAVE_LEADER_1",
                supervisor_id="cave_mgr_1",
                is_custodian_leader=True,
                domain_tags=["复核审批", "折扣", "风控", d1.label[:4]],
            ),
            ScoutPositionSpec(
                node_id="node_pos_supply_1",
                label=pick_role(2, f"{d2.label[:4]}专员"),
                person_name="赵工",
                title=pick_role(2, "采购与仓储专员"),
                department=d2.label,
                role_view="employee",
                node_type="WORKER_SLOT",
                parent_aspect_id=d2.node_id,
                subtree_root_id=d2.subtree_root_id,
                user_id="cave_supply_1",
                slot_id="SLOT_CAVE_SUPPLY_1",
                supervisor_id="cave_mgr_1",
                is_custodian_leader=False,
                domain_tags=["库存", "采购", "物流", d2.label[:4]],
            ),
            ScoutPositionSpec(
                node_id="node_pos_mgr_1",
                label=pick_role(3, f"{d3.label[:4]}主管"),
                person_name="张主管",
                title=pick_role(3, "运营统筹主管"),
                department=d3.label,
                role_view="manager",
                node_type="WORKER_SLOT",
                parent_aspect_id=d3.node_id,
                subtree_root_id=d3.subtree_root_id,
                user_id="cave_mgr_1",
                slot_id="SLOT_CAVE_MGR_1",
                supervisor_id="boss_lin",
                is_custodian_leader=True,
                domain_tags=["排产", "运营", "统筹", d3.label[:4]],
            ),
            ScoutPositionSpec(
                node_id="node_pos_fin_1",
                label=pick_role(4, "财务与票据专岗"),
                person_name="王会计",
                title=pick_role(4, "财务结算专员"),
                department=d_fin.label,
                role_view="finance_tool",
                node_type="BLACKBOX_HUMAN",
                parent_aspect_id=d_fin.node_id,
                subtree_root_id=d_fin.subtree_root_id,
                user_id="cave_fin_1",
                slot_id="SLOT_CAVE_FIN_1",
                supervisor_id="boss_lin",
                is_custodian_leader=False,
                domain_tags=["开票", "财务", "结算", "合规"],
            ),
        ]

        return ScoutBlueprint(
            enterprise_name=enterprise_name,
            aspects=aspects,
            positions=positions,
        )

    async def scout_organization_structure(
        self,
        enterprise_name: str,
        raw_org_material: str,
    ) -> dict[str, Any]:
        clean_name = enterprise_name.strip() or self.enterprise_name or "新探索企业"
        clean_material = raw_org_material.strip() or f"{clean_name}：包含业务接单、供应链保障、运营管控与财务结算部门。"

        # 若此前非空壳状态，先自动清理重建为当前企业初始火种再探路
        await self.reset_to_empty_shell(enterprise_name=clean_name)
        self.raw_org_material = clean_material

        sys_prompt = (
            "你是 Arachne-OS 的矿洞火把探路器。请阅读企业组织材料，只推演公司的部门结构(aspects)和岗位骨架(positions)，"
            "不要预先填充任何具体业务规则。\n"
            "必须输出严格合法的 JSON 对象，结构如下：\n"
            "{\n"
            '  "enterprise_name": "企业全称",\n'
            '  "aspects": [\n'
            '    {"node_id": "node_aspect_scout_1", "label": "部门名称", "subtree_root_id": "sub_1", "domain_tags": ["标签1", "标签2"]}\n'
            "  ],\n"
            '  "positions": [\n'
            "    {\n"
            '      "node_id": "node_pos_front_1",\n'
            '      "label": "岗位名称",\n'
            '      "person_name": "人名",\n'
            '      "title": "岗位头衔",\n'
            '      "department": "所属部门名称",\n'
            '      "role_view": "employee | leader | finance_tool | manager",\n'
            '      "node_type": "WORKER_SLOT | RELAY_NODE | BLACKBOX_HUMAN",\n'
            '      "parent_aspect_id": "node_aspect_scout_1",\n'
            '      "subtree_root_id": "sub_1",\n'
            '      "user_id": "cave_emp_1",\n'
            '      "slot_id": "SLOT_CAVE_EMP_1",\n'
            '      "supervisor_id": "boss_lin",\n'
            '      "is_custodian_leader": false,\n'
            '      "domain_tags": ["标签1", "标签2"]\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "要求：生成 3~4 个部门（node_id 用 node_aspect_scout_1..4）以及 5~6 个岗位（包含 employee/leader/finance_tool/manager），"
            "每个岗位的 parent_aspect_id 和 subtree_root_id 必须严格对应某个 aspect，所有命名使用自然中文人话。"
        )
        usr_prompt = f"企业名称：{clean_name}\n真实企业资料：\n{clean_material}"

        blueprint = await self._llm.complete_structured(
            tier="L3",
            system_prompt=sys_prompt,
            user_prompt=usr_prompt,
            response_model=ScoutBlueprint,
            fallback_builder=lambda: self._fallback_scout_blueprint(
                clean_name, clean_material
            ),
        )

        # 校验结构完整性，不合规则走本地解析兜底
        aspect_ids = {a.node_id for a in blueprint.aspects}
        role_views = {p.role_view for p in blueprint.positions}
        if (
            not (2 <= len(blueprint.aspects) <= 5)
            or not (4 <= len(blueprint.positions) <= 8)
            or any(p.parent_aspect_id not in aspect_ids for p in blueprint.positions)
            or "employee" not in role_views
        ):
            blueprint = self._fallback_scout_blueprint(clean_name, clean_material)

        # IDs supplied by fallback/LLM belong to this epoch, never a previous tenant.
        suffix = self.workspace_epoch[:10]
        aspect_map = {a.node_id: f"{a.node_id}_{suffix}" for a in blueprint.aspects}
        subtree_map = {a.subtree_root_id: f"{a.subtree_root_id}_{suffix}" for a in blueprint.aspects}
        user_map = {p.user_id: f"{p.user_id}_{suffix}" for p in blueprint.positions}
        for aspect in blueprint.aspects:
            aspect.node_id = aspect_map[aspect.node_id]
            aspect.subtree_root_id = subtree_map[aspect.subtree_root_id]
        for position in blueprint.positions:
            position.node_id = f"{position.node_id}_{suffix}"
            position.parent_aspect_id = aspect_map[position.parent_aspect_id]
            position.subtree_root_id = subtree_map[position.subtree_root_id]
            position.user_id = user_map[position.user_id]
            position.slot_id = f"{position.slot_id}_{suffix}"
            position.supervisor_id = user_map.get(position.supervisor_id, position.supervisor_id)

        # 更新根节点标题
        root_node = SpiderNode(
            node_id="node_board_root",
            label=f"{clean_name} · 核心总控",
            node_type="BOARD_ROOT",
            parent_id=None,
            subtree_root_id="root",
            slot_id="SLOT_BOSS",
            domain_tags=["企业总控", "火种中枢"],
            status="ACTIVE",
            active_load=1,
            exploration_state="LIT",
            torch_planted=True,
            discovered_from="探路总控中心",
        )
        await self._hot_store.upsert_node(root_node)

        # 写入灰色的部门节点 (SCOUTED，空壳无规则)
        for asp in blueprint.aspects:
            asp_node = SpiderNode(
                node_id=asp.node_id,
                label=asp.label,
                node_type="ASPECT_NODE",
                parent_id="node_board_root",
                subtree_root_id=asp.subtree_root_id,
                slot_id=None,
                domain_tags=asp.domain_tags,
                status="DEHYDRATED",
                active_load=0,
                exploration_state="SCOUTED",
                torch_planted=False,
                discovered_from="火把探路 · 仅摸清部门位置，暂未驻火",
            )
            await self._hot_store.upsert_node(asp_node)

        auth_svc = self._get_auth_custody()
        used_uids = {"boss_lin"}
        used_slots = {"SLOT_BOSS"}
        resolved_positions: list[tuple[ScoutPositionSpec, str, str]] = []
        leader_by_subtree: dict[str, str] = {}
        global_leaders: list[str] = []

        for idx, pos in enumerate(blueprint.positions, start=1):
            uid = pos.user_id if pos.user_id not in used_uids else _slug_id("cave_u", idx)
            sid = pos.slot_id if pos.slot_id not in used_slots else _slug_id("SLOT_CAVE", idx).upper()
            used_uids.add(uid)
            used_slots.add(sid)
            resolved_positions.append((pos, uid, sid))
            if pos.role_view in ("leader", "manager"):
                leader_by_subtree.setdefault(pos.subtree_root_id, uid)
                global_leaders.append(uid)

        for pos, uid, sid in resolved_positions:
            is_leader_flag = bool(
                pos.is_custodian_leader or pos.role_view in ("leader", "manager", "boss")
            )
            sup_uid = pos.supervisor_id
            if pos.role_view == "employee" and (not sup_uid or sup_uid == "boss_lin"):
                sup_uid = (
                    leader_by_subtree.get(pos.subtree_root_id)
                    or (global_leaders[0] if global_leaders else "boss_lin")
                )
            elif not sup_uid:
                sup_uid = "boss_lin"

            slot = UnitSlot(
                slot_id=sid,
                slot_name=pos.label,
                department=pos.department,
                ball_ids=[],  # 刚探路完毕，保持 0 条内容（纯灰空壳）
                occupant_type="HUMAN",
                occupant_id=uid,
                rule_repetition_ratio=30.0,
                shadow_agreement_rate=20.0,
                replaceability_score=24.0,
            )
            self._containers.register_slot(slot)
            self._containers.register_slot_alias(sid, pos.node_id)

            profile = DualEmployeeProfile(
                user_id=uid,
                name=pos.person_name,
                title=pos.title,
                role_view=pos.role_view,
                slot_id=sid,
                employee_view=EmployeeViewA(
                    skill_tags=pos.domain_tags[:3],
                    saved_hours=0.0,
                    evolution_contributions=[],
                    innovation_bonus=0.0,
                ),
                management_view=ManagementViewB(
                    avg_latency_ms=400.0,
                    rework_rate=0.02,
                    boundary_probes=0,
                    base_fulfillment_score=80.0,
                    performance_score=78.0,
                ),
            )
            self._containers.register_profile(profile)
            auth_svc.account_directory[uid] = {
                "department": pos.department,
                "supervisor_id": sup_uid,
                "is_custodian_leader": is_leader_flag,
            }
            bootstrap = str(getattr(self._rt.settings, "bootstrap_password", "") or "")
            if not bootstrap and getattr(self._rt.settings, "demo_mode", False):
                bootstrap = "123456"
            if bootstrap:
                auth_svc._passwords[uid] = hash_password(bootstrap)

            clean_pos_label = pos.label.strip()
            if (
                pos.person_name
                and f"（{pos.person_name}）" not in clean_pos_label
                and f"({pos.person_name})" not in clean_pos_label
            ):
                clean_pos_label = f"{clean_pos_label}（{pos.person_name}）"

            pos_node = SpiderNode(
                node_id=pos.node_id,
                label=clean_pos_label,
                node_type=pos.node_type,
                parent_id=pos.parent_aspect_id,
                subtree_root_id=pos.subtree_root_id,
                slot_id=sid,
                domain_tags=pos.domain_tags,
                status="DEHYDRATED",
                active_load=0,
                exploration_state="SCOUTED",
                torch_planted=False,
                discovered_from="火把探路 · 已摸清岗位结构，等待插火把填充内容",
            )
            await self._hot_store.upsert_node(pos_node)

        self.mode = "EXPLORING"
        self._append_log(
            "SCOUT",
            f"火把探路完成：在「{clean_name}」黑暗区域摸清了 {len(blueprint.aspects)} 个部门与 {len(blueprint.positions)} 个岗位轮廓（当前均为灰色待驻火状态）",
            "node_board_root",
        )
        await self._pulse.publish(
            event_type="ASPECT_CLUSTERED",
            node_id="node_board_root",
            subtree_root_id="root",
            severity="INFO",
            summary=f"火把探路完成：摸清 {len(blueprint.aspects)} 个部门、{len(blueprint.positions)} 个岗位骨架",
            payload={"mode": "EXPLORING"},
        )
        return await self.get_cave_map_state()

    def _fallback_torch_plan(
        self, node: SpiderNode, raw_sop_text: str
    ) -> TorchWeavePlan:
        sop = raw_sop_text.strip()
        tags = node.domain_tags or [node.label[:4]]
        label_clean = re.sub(r"（[^）]+）", "", node.label).strip()

        if sop:
            # 从用户粘贴的真实 SOP/报价单提取数值公式与红线线索
            has_smt = any(k in sop for k in ("焊点", "贴片", "SMT", "开机费", "工程费", "DIP"))
            has_shipping_or_fee = any(k in sop for k in ("运费", "首重", "公斤", "kg", "克"))
            has_discount = any(k in sop for k in ("折", "优惠", "返佣", "抽成", "提成", "满"))
            if has_smt:
                skill_instr = sop[:220]
                skill_title = f"{label_clean} · SMT贴片焊点工程计价器"
            elif has_shipping_or_fee:
                skill_instr = sop[:160]
                skill_title = f"{label_clean} · 运费阶梯自动核算器"
            elif has_discount:
                skill_instr = sop[:160]
                skill_title = f"{label_clean} · 批量阶梯折后价计算器"
            else:
                skill_instr = "阶梯运费规则：首重3公斤内10元，超过3公斤每公斤加4元，满500元免运费"
                skill_title = f"{label_clean} · 业务标准自动算子"

            redline_kws = re.findall(
                r"(?:严禁|禁止|不得|绝密|红线)[^\n，。；]{2,18}", sop
            )
            if "Gerber" in sop or "覆铜板" in sop:
                for kw in ("Gerber", "光绘源文件", "覆铜板拿货底价", "钻孔坐标底稿"):
                    if kw not in redline_kws:
                        redline_kws.append(kw)
            if not redline_kws:
                redline_kws = ["真实成本底价", "拿货底价", "内部返点"]

            items: list[TorchWeaveItemSpec] = [
                TorchWeaveItemSpec(
                    ball_type="DATA",
                    title=f"{label_clean} · 岗位作业资料与规范",
                    domain_tags=tags[:3],
                    sensitivity_level=2,
                    content=sop[:360],
                ),
                TorchWeaveItemSpec(
                    ball_type="SKILL",
                    title=skill_title,
                    domain_tags=tags[:3],
                    sensitivity_level=2,
                    content=f"根据驻火资料自动提炼并沙箱编译的可执行计算工具：{skill_instr}",
                    skill_instruction=skill_instr,
                ),
            ]
            if node.node_type in ("RELAY_NODE", "BLACKBOX_HUMAN") or any(
                k in sop for k in ("审批", "签字", "复核", "红线", "严禁", "底价", "权限")
            ):
                items.append(
                    TorchWeaveItemSpec(
                        ball_type="REDLINE" if any(k in sop for k in ("严禁", "底价", "绝密", "隐私")) else "AUTHORITY",
                        title=f"{label_clean} · {'风控底线隔离墙' if any(k in sop for k in ('严禁', '底价', '绝密', '隐私')) else '审批签字权限'}",
                        domain_tags=tags[:3],
                        sensitivity_level=4,
                        content=sop[:240],
                        redline_keywords=redline_kws[:4],
                    )
                )
            return TorchWeavePlan(
                node_summary=f"已结合传入的真实资料完成「{label_clean}」驻火提炼",
                items=items,
            )

        # 未额外粘贴 SOP 时，根据节点角色与此前探路背景自主推演业务内容
        context_hint = f"{self.enterprise_name} {node.label} {' '.join(tags)} {self.raw_org_material[:200]}"
        if node.node_type == "RELAY_NODE":
            items = [
                TorchWeaveItemSpec(
                    ball_type="AUTHORITY",
                    title=f"{label_clean} · 超限审批拍板权",
                    domain_tags=["审批", "折扣", *tags[:2]],
                    sensitivity_level=4,
                    content="负责复核一线提交的超限折让、加急交期变更及异常赔付工单，超过标准线必须人工确认放行。",
                ),
                TorchWeaveItemSpec(
                    ball_type="REDLINE",
                    title=f"{label_clean} · 高压线拦截红线",
                    domain_tags=["风控", "合规", *tags[:2]],
                    sensitivity_level=5,
                    content="严禁绕过审批直接承诺口头返利、亏本接单或泄露真实采购成本底价。",
                    redline_keywords=["真实成本底价", "拿货底价", "口头返利"],
                ),
            ]
        elif node.node_type == "BLACKBOX_HUMAN":
            items = [
                TorchWeaveItemSpec(
                    ball_type="AUTHORITY",
                    title=f"{label_clean} · 票据核销与签章权",
                    domain_tags=["财务", "开票", "合规"],
                    sensitivity_level=4,
                    content="只接收脱敏后的最小开票与对账四要素，人工核验税号、金额无误后执行开票结算。",
                ),
                TorchWeaveItemSpec(
                    ball_type="REDLINE",
                    title=f"{label_clean} · 资金与税务合规底线",
                    domain_tags=["财务", "红线", "审计"],
                    sensitivity_level=5,
                    content="严禁无真实合同/审批单据提前开票，严禁向外部群聊透出对账明细与客户隐私信息。",
                    redline_keywords=["无票放款", "客户隐私", "真实成本底价"],
                ),
            ]
        elif node.node_type == "ASPECT_NODE":
            items = [
                TorchWeaveItemSpec(
                    ball_type="DATA",
                    title=f"{label_clean} · 部门协同与交付指引",
                    domain_tags=tags[:3],
                    sensitivity_level=2,
                    content=f"已点亮「{label_clean}」部门业务中枢，明确本域常规交付口径、跨组转交标准与异常处理节点。",
                ),
                TorchWeaveItemSpec(
                    ball_type="AUTHORITY",
                    title=f"{label_clean} · 部门内协调调度权",
                    domain_tags=tags[:3],
                    sensitivity_level=3,
                    content=f"统筹{label_clean}内部岗位资源调配，并与上下游已照亮部门建立标准工单衔接。",
                ),
            ]
        elif any(k in context_hint for k in ("仓储", "采购", "物流", "耗材", "面辅料", "海外仓", "供应链")):
            items = [
                TorchWeaveItemSpec(
                    ball_type="DATA",
                    title=f"{label_clean} · 实时库存与补货水位表",
                    domain_tags=["库存", "采购", *tags[:2]],
                    sensitivity_level=2,
                    content="维护核心品类当前可用库存、安全库存预警线及紧急调拨周期标准。",
                ),
                TorchWeaveItemSpec(
                    ball_type="SKILL",
                    title=f"{label_clean} · 运费与补货成本算子",
                    domain_tags=["物流", "运费", *tags[:2]],
                    sensitivity_level=2,
                    content="自动核算首重3公斤内10元、超重每公斤加4元、满500元免运费的履约成本。",
                    skill_instruction="阶梯运费规则：首重3公斤内10元，超过3公斤每公斤加4元，满500元免运费",
                ),
            ]
        else:
            items = [
                TorchWeaveItemSpec(
                    ball_type="DATA",
                    title=f"{label_clean} · 标准业务报价手册",
                    domain_tags=["报价", "业务", *tags[:2]],
                    sensitivity_level=2,
                    content=f"沉淀「{label_clean}」常见客户咨询口径、标准交付周期与常规价格档位。",
                ),
                TorchWeaveItemSpec(
                    ball_type="SKILL",
                    title=f"{label_clean} · 批量阶梯折扣算子",
                    domain_tags=["报价", "折扣", *tags[:2]],
                    sensitivity_level=2,
                    content="自动核算单笔满20件享9.0折的标准批量折后总价，减少手工算账误差。",
                    skill_instruction="批量折扣折后价规则：满 20 件享 9.0 折",
                ),
                TorchWeaveItemSpec(
                    ball_type="AUTHORITY",
                    title=f"{label_clean} · 常规额度直签权",
                    domain_tags=["权限", "订单", *tags[:2]],
                    sensitivity_level=2,
                    content="标准价格与9折以上常规订单可直接受理，低于阈值自动转交复核岗。",
                ),
            ]

        return TorchWeavePlan(
            node_summary=f"Agent 已在「{label_clean}」插下火把并自主推演完成织网",
            items=items,
        )

    async def _compute_weave_cross_links(self, nodes: list[SpiderNode]) -> list[dict[str, Any]]:
        """
        只有两端节点均已被火把照亮（exploration_state == 'LIT'）时，才会在它们之间编织出业务协作丝线。
        """
        lit_nodes = [n for n in nodes if n.exploration_state == "LIT" and n.node_type != "BOARD_ROOT"]
        lit_workers = [n for n in lit_nodes if n.node_type == "WORKER_SLOT"]
        lit_relays = [n for n in lit_nodes if n.node_type == "RELAY_NODE"]
        lit_blackboxes = [n for n in lit_nodes if n.node_type == "BLACKBOX_HUMAN"]

        links: list[dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()

        def add_link(src: SpiderNode, dst: SpiderNode, label: str, kind: str) -> None:
            if src.node_id == dst.node_id:
                return
            pair = (src.node_id, dst.node_id)
            if pair in seen_pairs:
                return
            seen_pairs.add(pair)
            links.append(
                {
                    "link_id": f"WEAVE_EDGE_{src.node_id}_{dst.node_id}",
                    "source_node_id": src.node_id,
                    "target_node_id": dst.node_id,
                    "label": label,
                    "kind": kind,
                }
            )

        # 1) 已照亮业务岗位 -> 已照亮复核节点（超限移交审批）
        for w in lit_workers:
            for r in lit_relays:
                if w.subtree_root_id == r.subtree_root_id or "报价" in w.domain_tags or "一线业务" in w.domain_tags:
                    add_link(w, r, "超限移交复核", "APPROVAL_FLOW")

        # 2) 已照亮业务/复核节点 -> 已照亮财务/票据黑盒节点（成交通知开票）
        for src in lit_relays + lit_workers[:2]:
            for bb in lit_blackboxes:
                add_link(src, bb, "单据核验与开票", "SETTLEMENT_FLOW")

        # 3) 跨部门已照亮业务岗位之间的履约/供应链协同
        if len(lit_workers) >= 2:
            for i in range(len(lit_workers) - 1):
                a = lit_workers[i]
                b = lit_workers[i + 1]
                if a.subtree_root_id != b.subtree_root_id:
                    add_link(a, b, "跨组履约协同", "COLLAB_FLOW")

        return links

    async def plant_torch_and_weave(
        self,
        target_node_id: str,
        raw_sop_text: str = "",
    ) -> dict[str, Any]:
        nodes = await self._hot_store.list_nodes()
        node_by_id = {n.node_id: n for n in nodes}
        if target_node_id not in node_by_id:
            raise KeyError(f"未找到节点：{target_node_id}")

        target_node = node_by_id[target_node_id]
        clean_sop = raw_sop_text.strip()

        # 1) 点亮当前目标节点及其直系上行通路（所属部门节点），兄弟节点保持原样（灰色继续等待）
        lit_target = target_node.model_copy(
            update={
                "exploration_state": "LIT",
                "torch_planted": True,
                "status": "ACTIVE",
                "active_load": max(1, target_node.active_load),
                "discovered_from": "常驻火把已插 · 已深度织网"
                if clean_sop
                else "常驻火把已插 · Agent自主推演织网",
            }
        )
        await self._hot_store.upsert_node(lit_target)
        node_by_id[target_node_id] = lit_target

        curr_parent = target_node.parent_id
        while curr_parent and curr_parent in node_by_id:
            p_node = node_by_id[curr_parent]
            if p_node.exploration_state != "LIT":
                lit_parent = p_node.model_copy(
                    update={
                        "exploration_state": "LIT",
                        "torch_planted": True,
                        "status": "ACTIVE",
                        "active_load": max(1, p_node.active_load),
                        "discovered_from": "火把通道已贯通",
                    }
                )
                await self._hot_store.upsert_node(lit_parent)
                node_by_id[curr_parent] = lit_parent
            curr_parent = p_node.parent_id

        # 2) 解析归属槽位（若部门节点无单独槽位，则挂到总控槽位确保可持久化挂载）
        target_slot_id = target_node.slot_id or "SLOT_BOSS"
        try:
            slot = self._containers.get_slot(target_slot_id)
        except KeyError:
            target_slot_id = "SLOT_BOSS"
            slot = self._containers.get_slot("SLOT_BOSS")

        # 3) 提炼 2~3 个织网点（资料 / 计算工具 / 审批权限 / 风控底线）
        sys_prompt = (
            "你是 Arachne-OS 的矿洞驻火织网引擎。请为刚插上火把的岗位提炼 2~3 个高度实用的能力织网点。\n"
            "必须输出严格合法的 JSON 对象：\n"
            "{\n"
            '  "node_summary": "一句话概括本节点点亮后的核心职责",\n'
            '  "items": [\n'
            "    {\n"
            '      "ball_type": "DATA | SKILL | AUTHORITY | REDLINE",\n'
            '      "title": "织网点名称",\n'
            '      "domain_tags": ["标签1", "标签2"],\n'
            '      "sensitivity_level": 2,\n'
            '      "content": "详细业务规则或知识描述",\n'
            '      "skill_instruction": "若 ball_type=SKILL，填写可编译为公式的精确计算规则，否则 null",\n'
            '      "redline_keywords": ["仅 ball_type=REDLINE 时填写敏感拦截词列表，其他填空列表"]\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "注意：若资料包含数值计算规则（如SMT贴片焊点开机费、阶梯运费、批量折扣），必须生成一个 ball_type=SKILL 并写清 skill_instruction；"
            "若包含保密或严禁泄露内容（如Gerber源文件、底价），请生成一个 ball_type=REDLINE 并填入 redline_keywords。全部用直白中文人话。"
        )
        usr_prompt = (
            f"企业名称：{self.enterprise_name or '当前企业'}\n"
            f"目标节点：{target_node.label}（类型：{target_node.node_type}，标签：{'/'.join(target_node.domain_tags)}）\n"
            f"企业全貌背景：{self.raw_org_material[:500]}\n"
            f"岗位补充资料：{clean_sop or '（用户未粘贴额外文档，请结合岗位定位与企业背景自主推演）'}"
        )
        plan = await self._llm.complete_structured(
            tier="L3",
            system_prompt=sys_prompt,
            user_prompt=usr_prompt,
            response_model=TorchWeavePlan,
            fallback_builder=lambda: self._fallback_torch_plan(target_node, clean_sop),
        )
        if not plan.items:
            plan = self._fallback_torch_plan(target_node, clean_sop)

        genesis = self._get_genesis_engine()
        minted_ids: list[str] = []
        existing_titles = {
            b.title
            for bid in self.node_owned_ball_ids.get(target_node_id, [])
            if (b := self._particles.get_ball(bid)) is not None
        }

        for item in plan.items[:4]:
            if item.title in existing_titles:
                continue
            ball_id = f"BALL_{item.ball_type}_CAVE_{uuid.uuid4().hex[:6].upper()}"
            exec_path: Optional[str] = None
            if item.ball_type == "SKILL":
                instr = (
                    item.skill_instruction
                    or item.content
                    or "阶梯运费规则：首重3公斤内10元，超过3公斤每公斤加4元，满500元免运费"
                )
                try:
                    exec_path, _ = await genesis._compile_and_persist_skill_script(
                        ball_id=ball_id,
                        skill_instruction=instr,
                    )
                except Exception:
                    # 兜底确保非标准自然语言也能编译出安全可执行的算子脚本
                    exec_path, _ = await genesis._compile_and_persist_skill_script(
                        ball_id=ball_id,
                        skill_instruction="阶梯运费规则：首重3公斤内10元，超过3公斤每公斤加4元，满500元免运费",
                    )

            ball = CapabilityBall(
                ball_id=ball_id,
                ball_type=item.ball_type,
                title=item.title,
                domain_tags=item.domain_tags or target_node.domain_tags[:3],
                sensitivity_level=item.sensitivity_level,
                owner_slot_ids=[target_slot_id],
                content=item.content,
                redline_keywords=item.redline_keywords,
                executable_code_path=exec_path,
                status="ACTIVE",
            )
            self._particles.register_ball(ball, record_to_vault=True)
            self._containers.attach_ball_to_slot(target_slot_id, ball.ball_id)
            minted_ids.append(ball.ball_id)
            existing_titles.add(item.title)

        owned_list = self.node_owned_ball_ids.setdefault(target_node_id, [])
        for bid in minted_ids:
            if bid not in owned_list:
                owned_list.append(bid)

        # 给对应岗位发送就绪提示
        await self._wecom.append_message(
            ChatMessageItem(
                msg_id=f"MSG_TORCH_{uuid.uuid4().hex[:6]}",
                sender_id="BOT_GOVERNANCE",
                sender_name="驻火织网助手",
                facade_bot="GOVERNANCE",
                chat_type="SINGLE",
                direction="OUTBOUND",
                structured_card={"viewer_user_id": slot.occupant_id},
                content=(
                    f"🔥 节点「{target_node.label}」已插上常驻火把并照亮，"
                    f"新织入 {len(minted_ids)} 个业务能力点（当前累计 {len(owned_list)} 个）。"
                ),
            )
        )

        # 4) 重新计算所有已照亮节点之间的跨岗协作网
        all_nodes = list(node_by_id.values())
        self.cross_links = await self._compute_weave_cross_links(all_nodes)
        self.mode = (
            "EMPTY_SHELL"
            if len(all_nodes) <= 1
            else ("EXPLORING" if any(n.exploration_state == "SCOUTED" for n in all_nodes) else "FULLY_LIT")
        )
        if hasattr(self._human_tools, "bind_role_slots"):
            _, leader_slot_id = resolve_leader_user_and_slot(self._containers)
            _, finance_slot_id = resolve_blackbox_user_and_slot(self._containers)
            self._human_tools.bind_role_slots(
                leader_slot_id=leader_slot_id,
                finance_slot_id=finance_slot_id,
            )

        self._append_log(
            "PLANT_TORCH",
            f"在「{target_node.label}」插下火把，点亮并织入 {len(minted_ids)} 个能力点，当前跨岗连线 {len(self.cross_links)} 条",
            target_node_id,
        )
        await self._pulse.publish(
            event_type="NODE_REHYDRATED",
            node_id=target_node_id,
            subtree_root_id=target_node.subtree_root_id,
            severity="SUCCESS",
            summary=f"火把照亮「{target_node.label}」，织入 {len(minted_ids)} 个能力点",
            payload={"minted_count": len(minted_ids), "cross_links": len(self.cross_links)},
        )
        return await self.get_cave_map_state()

    def _collect_node_balls(
        self,
        nodes: list[SpiderNode],
    ) -> dict[str, list[CapabilityBall]]:
        """
        将所有 ACTIVE 能力精确归属到对应的节点，确保二维展开织网点时不出现跨节点重复。
        """
        all_balls = [b for b in self._particles.list_all_balls() if b.status != "DEPRECATED"]
        result: dict[str, list[CapabilityBall]] = {n.node_id: [] for n in nodes}

        # 如果已经过显式驻火记录，先绑定显式映射
        assigned_ids: set[str] = set()
        for n in nodes:
            if n.exploration_state != "LIT":
                continue
            explicit_ids = self.node_owned_ball_ids.get(n.node_id, [])
            for bid in explicit_ids:
                ball = self._particles.get_ball(bid)
                if ball and ball.status != "DEPRECATED":
                    result[n.node_id].append(ball)
                    assigned_ids.add(bid)

        # 对于初始默认种子企业或通过其他入口新增的球，按岗位 slot_id 归属给主责岗位节点
        non_aspect_by_slot: dict[str, list[SpiderNode]] = {}
        aspect_by_slot: dict[str, list[SpiderNode]] = {}
        for n in nodes:
            if n.exploration_state != "LIT" or not n.slot_id:
                continue
            if n.node_type == "ASPECT_NODE":
                aspect_by_slot.setdefault(n.slot_id, []).append(n)
            else:
                non_aspect_by_slot.setdefault(n.slot_id, []).append(n)

        for ball in all_balls:
            if ball.ball_id in assigned_ids:
                continue
            placed = False
            for sid in ball.owner_slot_ids:
                targets = non_aspect_by_slot.get(sid) or aspect_by_slot.get(sid) or []
                if targets:
                    result[targets[0].node_id].append(ball)
                    assigned_ids.add(ball.ball_id)
                    placed = True
                    break
            if not placed:
                # 若仅存在未匹配槽位，挂到根节点（若根节点存在）
                if "node_board_root" in result:
                    result["node_board_root"].append(ball)
                    assigned_ids.add(ball.ball_id)

        return result

    async def get_cave_map_state(self) -> dict[str, Any]:
        nodes = await self._hot_store.list_nodes()
        if not self.cross_links and len(nodes) > 1:
            self.cross_links = await self._compute_weave_cross_links(nodes)

        lit_count = sum(1 for n in nodes if n.exploration_state == "LIT")
        scouted_count = sum(1 for n in nodes if n.exploration_state == "SCOUTED")
        if len(nodes) <= 1:
            mode: Literal["EMPTY_SHELL", "EXPLORING", "FULLY_LIT"] = "EMPTY_SHELL"
        elif scouted_count > 0:
            mode = "EXPLORING"
        else:
            mode = "FULLY_LIT"

        balls_by_node = self._collect_node_balls(nodes)
        profile_by_slot: dict[str, DualEmployeeProfile] = {
            p.slot_id: p for p in self._containers.list_profiles()
        }

        node_items: list[dict[str, Any]] = []
        total_weave_points = 0
        for n in nodes:
            node_balls = balls_by_node.get(n.node_id, [])
            weave_points: list[dict[str, Any]] = []
            for b in node_balls:
                weave_points.append(
                    {
                        "point_id": b.ball_id,
                        "ball_type": b.ball_type,
                        "type_label": TYPE_LABELS.get(b.ball_type, "业务模块"),
                        "title": b.title,
                        "summary": b.content[:80] + ("..." if len(b.content) > 80 else ""),
                        "content": b.content,
                        "domain_tags": b.domain_tags,
                        "sensitivity_level": b.sensitivity_level,
                        "has_executable_tool": bool(b.executable_code_path),
                        "quick_use_prompt": build_quick_use_prompt(b),
                    }
                )
            total_weave_points += len(weave_points)
            prof = profile_by_slot.get(n.slot_id or "")
            slot_obj = (
                self._containers.get_slot(n.slot_id)
                if n.slot_id and n.slot_id in self._containers._slots
                else None
            )
            node_items.append(
                {
                    "node_id": n.node_id,
                    "label": n.label,
                    "node_type": n.node_type,
                    "parent_id": n.parent_id,
                    "subtree_root_id": n.subtree_root_id,
                    "slot_id": n.slot_id,
                    "occupant_type": slot_obj.occupant_type if slot_obj else None,
                    "occupant_id": slot_obj.occupant_id if slot_obj else None,
                    "occupant_name": prof.name if prof else None,
                    "occupant_title": prof.title if prof else None,
                    "department": slot_obj.department if slot_obj else None,
                    "domain_tags": n.domain_tags,
                    "status": n.status,
                    "active_load": n.active_load,
                    "exploration_state": n.exploration_state,
                    "torch_planted": n.torch_planted,
                    "discovered_from": n.discovered_from,
                    "weave_points": weave_points,
                }
            )

        root_label = next(
            (n.label for n in nodes if n.node_type == "BOARD_ROOT"),
            self.enterprise_name or "待探索企业",
        )
        display_enterprise = self.enterprise_name or root_label.split("·")[0].strip()

        return {
            "mode": mode,
            "enterprise_name": display_enterprise,
            "has_raw_material": bool(self.raw_org_material),
            "stats": {
                "total_nodes": len(nodes),
                "lit_nodes": lit_count,
                "scouted_nodes": scouted_count,
                "weave_points_count": total_weave_points,
                "cross_links_count": len(self.cross_links),
            },
            "nodes": node_items,
            "cross_links": self.cross_links,
            "logs": self.exploration_logs[-12:],
            "starter_dossiers": STARTER_DOSSIERS,
        }

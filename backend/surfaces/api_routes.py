from __future__ import annotations

from dataclasses import dataclass
import asyncio
from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import ArachneSettings
from core.auth_custody import AuthAndCustodyService
from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from core.external_connectors import ExternalConnectorRegistry
from core.human_tool import HumanBlackBoxManager
from core.llm_gateway import LLMGateway
from core.particles import ParticleEngine
from core.runtime_transactions import RuntimeTransactions, RuntimeWriterLease
from core.runtime_state import (
    clear_workspace_runtime,
    export_runtime_state,
    restore_runtime_state,
)
from core.security import get_authenticated_account, require_roles, require_self_or_roles
from core.schemas import (
    ChatScopeType,
    EmployeeOverviewResponse,
    ExecutiveOverviewResponse,
    FacadeBotType,
    FinanceBlackBoxOverviewResponse,
    LeaderOverviewResponse,
    RoleViewType,
)
from core.topology_resolver import (
    resolve_active_authority_ball,
    resolve_blackbox_user_and_slot,
    resolve_executive_slots,
    resolve_frontline_user_and_slot,
    resolve_leader_user_and_slot,
)
from database import HotStateStore
from seed_demo.commerce_dept_seed import (
    seed_commerce_department,
    seed_demo_welcome_messages,
)
from surfaces.wecom_gateway import LocalSimulatorAdapter, create_wecom_gateway
from swarm.board_of_directors import BoardOfDirectors
from swarm.cave_explorer import CaveExplorationEngine
from swarm.cross_dept_router import CrossDepartmentRouter
from swarm.day_simulator import CompanyDaySimulator
from swarm.edge_audit_relay import EdgeAuditRelay
from swarm.evolution_arena import EvolutionArena
from swarm.pulse_bus import PulseBus
from swarm.scoring_engine import ScoringEngine
from swarm.spider_network import SpiderNetwork


@dataclass
class ArachneRuntime:
    settings: ArachneSettings
    vault: BlackBoxVault
    hot_store: HotStateStore
    particles: ParticleEngine
    containers: ContainerRegistry
    human_tools: HumanBlackBoxManager
    pulse_bus: PulseBus
    llm_gateway: LLMGateway
    edge_relay: EdgeAuditRelay
    scoring: ScoringEngine
    spider: SpiderNetwork
    arena: EvolutionArena
    board: BoardOfDirectors
    wecom: LocalSimulatorAdapter
    cross_dept: CrossDepartmentRouter
    day_sim: CompanyDaySimulator
    auth_custody: Optional[AuthAndCustodyService] = None
    cave_explorer: Optional[CaveExplorationEngine] = None
    connectors: Optional[ExternalConnectorRegistry] = None
    restored_from_persistence: bool = False

    def __post_init__(self) -> None:
        self._transactions = RuntimeTransactions(self)

    def export_runtime_state(self) -> dict[str, Any]:
        return export_runtime_state(self)

    async def capture_state(self) -> dict[str, Any]:
        payload = self.export_runtime_state()
        payload["hot_state"] = await self.hot_store.export_global_state()
        if self.auth_custody:
            payload["security_state"] = self.auth_custody.export_persistence_payload()
            payload["security_state"]["sessions"] = dict(self.auth_custody._sessions)
        if self.connectors:
            payload["private_connector_state"] = self.connectors.export_state()
        sandbox = Path(self.settings.sandbox_workspace_dir)
        payload["script_files"] = {
            str(path.relative_to(sandbox)): path.read_text(encoding="utf-8")
            for path in sandbox.rglob("*.py")
            if "simulations" not in path.relative_to(sandbox).parts and not path.is_symlink()
        }
        return deepcopy(payload)

    async def restore_runtime_state(self, payload: dict[str, Any], preserve_security: bool = True) -> None:
        await restore_runtime_state(self, payload, preserve_security)

    def clear_workspace_runtime(self) -> None:
        clear_workspace_runtime(self)

    def mutation_scope(self, precheck=None):
        return self._transactions.scope(precheck=precheck)

    async def close(self) -> None:
        from core.simulation_workspace import close_simulation_runtime
        await self.pulse_bus.drain_background_tasks()
        await self.sync_persistence()
        await close_simulation_runtime(self)
        await self.hot_store.close()

    async def sync_persistence(self, override_mode: Optional[str] = None) -> None:
        """将当前内存注册表（容器、员工档案、权能球及脚本、账号权限与探网元状态）写穿落盘至 SQLite。"""
        if self.auth_custody is None:
            self.auth_custody = AuthAndCustodyService(
                vault=self.vault,
                particles=self.particles,
                containers=self.containers,
                settings=self.settings,
            )
        auth_payload = self.auth_custody.export_persistence_payload()
        cave_meta = self.cave_explorer.export_meta_state() if self.cave_explorer else {}
        enterprise_name = str(
            cave_meta.get("enterprise_name") or "商务跟单与客户运营部"
        )
        mode = str(override_mode or cave_meta.get("mode") or "DEMO_SEED")
        meta_payload = {
            "cave_meta": cave_meta,
            "slot_aliases": dict(self.containers._slot_aliases),
            "human_tools_state": (
                self.human_tools.export_state()
                if hasattr(self.human_tools, "export_state")
                else {}
            ),
            "connector_state": (
                self.connectors.export_state()
                if self.connectors is not None
                else {}
            ),
            "sessions": auth_payload.get("sessions", {}),
            "runtime_state": self.export_runtime_state(),
        }
        balls_with_src = self.particles.export_balls_with_source(
            self.settings.sandbox_workspace_dir
        )
        await self.hot_store.persist_workspace_state(
            enterprise_name=enterprise_name,
            mode=mode,
            unit_slots=self.containers.list_slots(),
            profiles=self.containers.list_profiles(),
            capability_balls_with_source=balls_with_src,
            account_directory=auth_payload["account_directory"],
            passwords=auth_payload["passwords"],
            custody_requests=auth_payload["custody_requests"],
            meta_payload=meta_payload,
        )


def _bind_dynamic_human_tool_slots(rt: ArachneRuntime) -> None:
    if not hasattr(rt.human_tools, "bind_role_slots"):
        return
    _, leader_slot_id = resolve_leader_user_and_slot(rt.containers)
    _, finance_slot_id = resolve_blackbox_user_and_slot(rt.containers)
    rt.human_tools.bind_role_slots(
        leader_slot_id=leader_slot_id,
        finance_slot_id=finance_slot_id,
    )


async def create_arachne_runtime(settings: ArachneSettings) -> ArachneRuntime:
    writer_lease = RuntimeWriterLease(settings.sqlite_db_url)
    try:
        return await _build_arachne_runtime(settings, writer_lease)
    except BaseException:
        writer_lease.close()
        raise


async def _build_arachne_runtime(settings: ArachneSettings, writer_lease: RuntimeWriterLease) -> ArachneRuntime:
    vault = BlackBoxVault(settings.vault_storage_dir)
    hot_store = HotStateStore(settings.sqlite_db_url)
    hot_store._runtime_writer_lease = writer_lease
    await hot_store.init_db()

    particles = ParticleEngine(vault)
    containers = ContainerRegistry()
    def resolve_slot_role(slot_id: str) -> str | None:
        try:
            occupant_id = containers.get_slot(slot_id).occupant_id
            return containers.get_profile(occupant_id).role_view
        except KeyError:
            return None

    particles.bind_role_resolver(resolve_slot_role)
    human_tools = HumanBlackBoxManager()
    pulse_bus = PulseBus()
    llm_gateway = LLMGateway(settings)
    edge_relay = EdgeAuditRelay(vault, hot_store, particles, llm_gateway, pulse_bus)
    scoring = ScoringEngine(vault, containers, pulse_bus)
    spider = SpiderNetwork(
        settings=settings,
        vault=vault,
        hot_store=hot_store,
        particles=particles,
        containers=containers,
        human_tools=human_tools,
        llm_gateway=llm_gateway,
        edge_relay=edge_relay,
        pulse_bus=pulse_bus,
    )
    spider.bind_scoring_hooks(
        shadow_hook=scoring.on_shadow_trial_completed,
        penalty_hook=scoring.on_boundary_probe_penalized,
    )
    arena = EvolutionArena(
        settings=settings,
        vault=vault,
        particles=particles,
        containers=containers,
        llm_gateway=llm_gateway,
        scoring=scoring,
        pulse_bus=pulse_bus,
    )
    board = BoardOfDirectors(
        settings=settings,
        vault=vault,
        hot_store=hot_store,
        particles=particles,
        containers=containers,
        llm_gateway=llm_gateway,
        scoring=scoring,
        pulse_bus=pulse_bus,
    )
    wecom = create_wecom_gateway(settings)
    cross_dept = CrossDepartmentRouter(vault, hot_store, particles, containers, pulse_bus)
    auth_custody = AuthAndCustodyService(
        vault=vault,
        particles=particles,
        containers=containers,
        settings=settings,
    )
    connectors = ExternalConnectorRegistry(settings)

    rt = ArachneRuntime(
        settings=settings,
        vault=vault,
        hot_store=hot_store,
        particles=particles,
        containers=containers,
        human_tools=human_tools,
        pulse_bus=pulse_bus,
        llm_gateway=llm_gateway,
        edge_relay=edge_relay,
        scoring=scoring,
        spider=spider,
        arena=arena,
        board=board,
        wecom=wecom,
        cross_dept=cross_dept,
        day_sim=None,  # type: ignore[arg-type]
        auth_custody=auth_custody,
        connectors=connectors,
    )
    rt.cave_explorer = CaveExplorationEngine(rt)

    persisted = await hot_store.load_workspace_state()
    if persisted is not None:
        meta_payload = dict(persisted.get("meta_payload") or {})
        particles.restore_balls_with_source(
            persisted.get("capability_balls") or [],
            sandbox_dir=settings.sandbox_workspace_dir,
        )
        containers.load_persisted_containers(
            persisted.get("unit_slots") or [],
            persisted.get("profiles") or [],
        )
        raw_aliases = meta_payload.get("slot_aliases") or {}
        if raw_aliases:
            containers.register_slot_aliases(raw_aliases)
        auth_custody.restore_from_persistence(
            persisted.get("account_directory") or {},
            persisted.get("passwords") or {},
            persisted.get("custody_requests") or [],
            meta_payload.get("sessions") or {},
        )
        rt.cave_explorer.restore_meta_state(
            meta_payload.get("cave_meta"),
            fallback_enterprise_name=str(persisted.get("enterprise_name") or ""),
        )
        if hasattr(human_tools, "restore_state"):
            human_tools.restore_state(meta_payload.get("human_tools_state"))
        connectors.restore_state(meta_payload.get("connector_state"))
        _bind_dynamic_human_tool_slots(rt)
        containers.sync_slot_node_map_from_nodes(await hot_store.list_nodes())
        wecom.seed_welcome_for_profiles(
            containers.list_profiles(),
            str(persisted.get("enterprise_name") or "已恢复企业"),
        )
        rt.restored_from_persistence = True
    else:
        await seed_commerce_department(vault, particles, containers, hot_store)
        seed_demo_welcome_messages(wecom)
        auth_custody.sync_accounts_from_containers()
        _bind_dynamic_human_tool_slots(rt)
        containers.sync_slot_node_map_from_nodes(await hot_store.list_nodes())
        rt.cave_explorer.enterprise_name = "商务跟单与客户运营部"
        rt.cave_explorer.mode = "DEMO_SEED"
        await rt.sync_persistence(override_mode="DEMO_SEED")

    rt.day_sim = CompanyDaySimulator(rt)
    connectors.bind_runtime(rt)
    if persisted is not None:
        saved_runtime = (persisted.get("meta_payload") or {}).get("runtime_state", {})
        if saved_runtime:
            await rt.restore_runtime_state(saved_runtime, preserve_security=True)
    pulse_bus.bind_runtime(rt)
    if hasattr(wecom, "bind_inbound_handler"):
        def resolve_wecom_user(external_user_id: str) -> str:
            mapped = next((
                uid for uid, metadata in auth_custody.account_directory.items()
                if uid == external_user_id or metadata.get("wecom_user_id") == external_user_id
            ), None)
            if mapped is None or auth_custody.account_directory[mapped].get("_disabled"):
                raise PermissionError("企微发送人尚未绑定到当前企业的有效岗位")
            containers.get_profile(mapped)
            return mapped

        async def authorize_wecom_sender(external_user_id: str) -> None:
            async with rt._transactions.lock:
                resolve_wecom_user(external_user_id)

        async def inbound_wecom_message(external_user_id: str, content: str, chat_type: str) -> str:
            async with rt.mutation_scope():
                mapped = resolve_wecom_user(external_user_id)
                profile = containers.get_profile(mapped)
                result = await _process_chat_message(rt, ChatMessageRequest(
                    sender_id=mapped, role_view=profile.role_view,
                    content=content, chat_type=chat_type,
                ))
                return str(result["message"]["content"])

        async def persist_wecom_state() -> None:
            async with rt.mutation_scope():
                await rt.sync_persistence()

        wecom.bind_inbound_handler(inbound_wecom_message)
        wecom.bind_state_persistence_hook(persist_wecom_state)
        wecom.bind_sender_authorizer(authorize_wecom_sender)
    if hasattr(spider, "bind_human_supervisor_authorizer"):
        def supervisor_authorizer(user_id: str, target_slot_id: str) -> bool:
            actor = containers.get_profile(user_id)
            target = containers.get_slot(target_slot_id)
            if actor.role_view not in ("leader", "manager", "boss"):
                return False
            if actor.role_view == "boss":
                return True
            metadata = auth_custody.account_directory.get(target.occupant_id, {})
            return metadata.get("supervisor_id") == user_id
        spider.bind_human_supervisor_authorizer(supervisor_authorizer)
    await rt._transactions.recover()
    return rt


def _rt(request: Request) -> ArachneRuntime:
    return request.app.state.runtime  # type: ignore[no-any-return]


class ChatMessageRequest(BaseModel):
    sender_id: Optional[str] = None
    role_view: RoleViewType = "employee"
    facade_bot: FacadeBotType = "COPILOT"
    chat_type: ChatScopeType = "SINGLE"
    content: str = ""
    raw_wechat_forward: list[str] = Field(default_factory=list)


class HumanToolSubmitRequest(BaseModel):
    actor_user_id: str
    card_id: str
    submitted_output: dict[str, Any]


class EvolutionProposeRequest(BaseModel):
    proposer_id: Optional[str] = None
    natural_instruction: str
    override_code_for_security_test: Optional[str] = None


class PublishSkillRequest(BaseModel):
    reviewer_id: Optional[str] = None
    approved_source_hash: str
    independent_samples: list[dict[str, Any]] = Field(min_length=3)


class ShadowReviewRequest(BaseModel):
    ticket_id: str
    human_final_text: str = Field(min_length=1, max_length=20000)


class ExternalIdentityRequest(BaseModel):
    wecom_user_id: str = Field(min_length=1, max_length=256)


class SwarmDrillRequest(BaseModel):
    mode: Literal["BURST_PAD", "HALLUCINATION_FAULT", "DEHYDRATE_IDLE", "BORROW_BALL"]
    parent_node_id: Optional[str] = None
    burst_count: int = 6
    subtree_root_id: Optional[str] = None
    borrower_slot_id: Optional[str] = None
    lender_slot_id: Optional[str] = None
    ball_id: Optional[str] = None


class BoardConveneRequest(BaseModel):
    agenda: Optional[str] = None
    target_slot_id: Optional[str] = None
    force_security_veto: bool = False


class BoardDecisionRequest(BaseModel):
    resolution_id: str
    approve: bool = True


class VaultRollbackRequest(BaseModel):
    scope: Literal["LOCAL", "GLOBAL"] = "LOCAL"
    subtree_root_id: Optional[str] = None
    snapshot_hash: Optional[str] = None
    reason: str = "管理员手动触发安全快照回滚"


class NodeLifecycleRequest(BaseModel):
    action: Literal["DEHYDRATE", "REHYDRATE"]
    reason: str = "manual_toggle"
    role_view: RoleViewType = "boss"


router = APIRouter()


def _resolve_user_for_view(
    rt: ArachneRuntime, role_view: RoleViewType, user_id: Optional[str]
) -> str:
    if user_id and user_id in rt.containers._profiles:
        return user_id
    profiles = rt.containers.list_profiles()
    exact = next((p.user_id for p in profiles if p.role_view == role_view), None)
    if exact:
        return exact
    if role_view == "manager":
        mgr_or_leader = next(
            (p.user_id for p in profiles if p.role_view in ("manager", "leader", "boss")),
            None,
        )
        if mgr_or_leader:
            return mgr_or_leader
    if role_view == "leader":
        ldr = next(
            (p.user_id for p in profiles if p.role_view in ("leader", "manager", "boss")),
            None,
        )
        if ldr:
            return ldr
    if role_view == "employee":
        uid, _ = resolve_frontline_user_and_slot(rt.containers)
        if uid:
            return uid
    if role_view == "finance_tool":
        uid, _ = resolve_blackbox_user_and_slot(rt.containers)
        if uid:
            return uid
    return profiles[0].user_id if profiles else ""


@router.get("/api/v1/state/overview")
async def get_state_overview(
    request: Request,
    role_view: RoleViewType = Query(default="employee"),
    user_id: Optional[str] = Query(default=None),
) -> Any:
    rt = _rt(request)
    account = get_authenticated_account(request)
    if account is not None:
        if user_id and user_id != account.user_id:
            raise HTTPException(status_code=403, detail="只能读取当前登录账号的工作台")
        user_id = account.user_id
    resolved_uid = _resolve_user_for_view(rt, role_view, user_id)
    profile = rt.containers.get_profile(resolved_uid)
    vault_health = rt.vault.verify_chain_integrity()

    # 物理级 RBAC 裁剪出口 1：普通员工视角（绝对不含 replaceability_score / management_view / 底价红线球）
    if role_view == "employee":
        eff_ids = {
            bid for bid in rt.containers.get_effective_ball_ids(profile.slot_id)
            if rt.particles.get_ball(bid).ball_type != "REDLINE"
        }
        all_tickets = await rt.hot_store.list_tickets()
        my_tickets = [t for t in all_tickets if t.initiator_id == resolved_uid]
        my_reports = [
            r for r in rt.arena.list_reports() if r.proposer_id == resolved_uid
        ]
        resp = EmployeeOverviewResponse(
            role_view="employee",
            current_user=rt.containers.project_public_profile(resolved_uid),
            my_slot=rt.containers.project_public_slot(profile.slot_id),
            accessible_balls=[
                ball for ball in rt.particles.project_public_balls(profile.slot_id, eff_ids)
                if ball.ball_type != "REDLINE"
            ],
            my_tickets=my_tickets,
            chat_history=rt.wecom.get_chat_history(resolved_uid, role_view),
            recent_arena_reports=my_reports,
            vault_health=vault_health,
        )
        return resp.model_dump()

    # 物理级 RBAC 裁剪出口 2：财务/法务黑盒节点视角（仅见最小开票契约与裁剪后的四要素卡片）
    if role_view == "finance_tool":
        fin_cards = rt.human_tools.list_cards(target_slot_id=profile.slot_id)
        fin_contract = rt.human_tools.get_contract("CONTRACT_FINANCE_TAX_DISK")
        if not fin_cards and not fin_contract.slot_id.startswith("ROLE_"):
            fin_cards = rt.human_tools.list_cards(target_slot_id=fin_contract.slot_id)
        resp_fin = FinanceBlackBoxOverviewResponse(
            role_view="finance_tool",
            current_user=rt.containers.project_public_profile(resolved_uid),
            contract=fin_contract,
            pending_cards=[c for c in fin_cards if c.status == "PENDING"],
            completed_cards=[c for c in fin_cards if c.status != "PENDING"],
            chat_history=rt.wecom.get_chat_history(resolved_uid, role_view),
            vault_health=vault_health,
        )
        return resp_fin.model_dump()

    # 物理级 RBAC 裁剪出口 3：基层组长/部门头头视角（可见高压线审批卡与团队工单拓扑，仍不含公司级替代分底牌）
    if role_view == "leader":
        eff_ids = rt.containers.get_effective_ball_ids(profile.slot_id)
        leader_cards = rt.human_tools.list_cards(target_slot_id=profile.slot_id)
        if not leader_cards:
            leader_contract = rt.human_tools.get_contract("CONTRACT_LEADER_HV_APPROVAL")
            if not leader_contract.slot_id.startswith("ROLE_"):
                leader_cards = rt.human_tools.list_cards(
                    target_slot_id=leader_contract.slot_id
                )
        resp_leader = LeaderOverviewResponse(
            role_view="leader",
            current_user=rt.containers.project_public_profile(resolved_uid),
            my_slot=rt.containers.project_public_slot(profile.slot_id),
            pending_approval_cards=[c for c in leader_cards if c.status == "PENDING"],
            team_tickets=[
                ticket for ticket in await rt.hot_store.list_tickets()
                if ticket.initiator_id == resolved_uid
                or rt.auth_custody.account_directory.get(ticket.initiator_id, {}).get("supervisor_id") == resolved_uid
            ],
            accessible_balls=[
                ball for ball in rt.particles.project_public_balls(profile.slot_id, eff_ids)
                if ball.ball_type != "REDLINE"
            ],
            topology_nodes=await rt.hot_store.list_nodes(),
            chat_history=rt.wecom.get_chat_history(resolved_uid, role_view),
            vault_health=vault_health,
        )
        return resp_leader.model_dump()

    # 出口 4：中层主管 (manager) 与顶层老板 (boss) 管理大屏全量视角
    all_balls = rt.particles.list_all_balls()
    if role_view == "manager":
        all_balls = [ball for ball in all_balls if ball.ball_type != "REDLINE"]
        # 部门主管亦不直接读取仅限 boss 席位的绝密拿货底价明文数值
        boss_slots, _ = resolve_executive_slots(rt.containers)
        boss_sid = boss_slots[0] if boss_slots else "SLOT_BOSS"
        all_balls = [
            b.model_copy(update={"content": "[仅顶层决策席授权解密]"})
            if (boss_sid in b.owner_slot_ids and profile.slot_id not in b.owner_slot_ids)
            else b
            for b in all_balls
        ]

    resp_exec = ExecutiveOverviewResponse(
        role_view=role_view,
        current_user=profile,
        all_slots=rt.containers.list_slots(),
        all_profiles=rt.containers.list_profiles(),
        all_balls=all_balls,
        topology_nodes=await rt.hot_store.list_nodes(),
        active_aspects=rt.particles.cluster_domain_aspects(min_cooccurrence=2),
        tickets=await rt.hot_store.list_tickets(),
        pending_cards=rt.human_tools.list_cards(status="PENDING"),
        arena_reports=rt.arena.list_reports(),
        board_resolutions=rt.board.list_resolutions(),
        preference_weights=rt.scoring.calibrator.snapshot(),
        pulse_log=rt.pulse_bus.recent_events(limit=80),
        chat_history=rt.wecom.get_chat_history(resolved_uid, role_view),
        vault_health=vault_health,
    )
    result = resp_exec.model_dump()
    reviews = getattr(rt, "shadow_reviews", {})
    completed = {
        ticket.ticket_id: ticket for ticket in await rt.hot_store.list_tickets()
        if ticket.status == "COMPLETED" and ticket.initiator_id != resolved_uid
    }
    result["reviewable_outputs"] = [
        {
            "ticket_id": message.ticket_id,
            "initiator_id": user_id,
            "ai_draft_text": message.content,
            "reviewed": message.ticket_id in reviews,
        }
        for user_id, messages in rt.wecom._messages_by_user.items()
        for message in messages
        if message.ticket_id in completed and message.direction == "OUTBOUND"
    ]
    return result


@router.post("/api/v1/chat/message")
async def post_chat_message(
    req: ChatMessageRequest, request: Request
) -> dict[str, Any]:
    rt = _rt(request)
    account = get_authenticated_account(request)
    if account is not None:
        req.sender_id = account.user_id
        req.role_view = account.role_view
    return await _process_chat_message(rt, req)


async def _process_chat_message(rt: ArachneRuntime, req: ChatMessageRequest) -> dict[str, Any]:
    effective_sender_id = _resolve_user_for_view(rt, req.role_view, req.sender_id)
    profile = rt.containers.get_profile(effective_sender_id)

    # 智能合一路由 1：若用户在统一输入框直接口述“做成自动工具 / 每次手工算...”，自动触发工匠造球与净室擂台，结果直接内嵌回对话流！
    is_artisan_intent = any(
        kw in req.content
        for kw in ("做成自动工具", "做成工具", "每次手工算", "自动算工具", "生成技能球")
    )
    if is_artisan_intent and not req.raw_wechat_forward:
        report = await rt.arena.propose_and_evaluate(
            proposer_id=effective_sender_id,
            natural_instruction=req.content,
        )
        reply_summary = (
            f"🛠️【工匠自动锻造 & 净室沙箱擂台结案】\n"
            f"• 技能球：《{report.skill_title}》\n"
            f"• AST 静态安检：{'通过' if report.ast_passed else '拦截'}\n"
            f"• 黄金样本回放：{report.total_samples} 组样本 | 成功率 {report.success_rate*100:.0f}% | 吻合度 {report.match_rate*100:.1f}%\n"
            f"• 技能状态：{'已通过独立基准并挂载为 ACTIVE' if report.promoted else '候选待审核，需补充独立业务样本'}"
        )
        _, out_msg = await rt.wecom.record_conversation_pair(
            user_id=effective_sender_id,
            user_name=profile.name,
            facade_bot="GOVERNANCE",
            chat_type=req.chat_type,
            inbound_text=req.content,
            outbound_reply=reply_summary,
            extra_card=report.model_dump(),
        )
        await rt.sync_persistence()
        return {
            "message": out_msg.model_dump(),
            "arena_report": report.model_dump(),
            "spawned_card": None,
        }

    # 智能合一路由 2：若用户在统一输入框直接粘贴多行微信文本，自动触发 L1 公私剥离与 PII 脱敏导单
    effective_forward = list(req.raw_wechat_forward) if req.raw_wechat_forward else []
    if not effective_forward and "\n" in req.content.strip():
        effective_forward = [
            line.strip() for line in req.content.splitlines() if line.strip()
        ]

    turn_res = await rt.spider.process_inbound_turn(
        sender_id=effective_sender_id,
        facade_bot=req.facade_bot,
        content=req.content,
        raw_wechat_forward=effective_forward or None,
    )
    display_in = (
        req.content
        if req.content.strip()
        else f"[一键转发外部微信聊天记录 {len(req.raw_wechat_forward)} 条]"
    )
    _, out_msg = await rt.wecom.record_conversation_pair(
        user_id=effective_sender_id,
        user_name=profile.name,
        facade_bot=req.facade_bot,
        chat_type=req.chat_type,
        inbound_text=display_in,
        outbound_reply=turn_res["reply"],
        ticket_id=turn_res["ticket"].ticket_id,
    )

    spawned_card = turn_res.get("spawned_card")
    if spawned_card is not None:
        fallback_leader_uid, _ = resolve_leader_user_and_slot(rt.containers)
        target_uid = fallback_leader_uid
        try:
            slot_obj = rt.containers.get_slot(spawned_card.target_slot_id)
            if slot_obj.occupant_id:
                target_uid = slot_obj.occupant_id
        except KeyError:
            pass
        if target_uid:
            await rt.wecom.push_interactive_card(
                target_user_id=target_uid,
                facade_bot="GOVERNANCE",
                card=spawned_card,
            )
        if rt.connectors is not None:
            await rt.connectors.dispatch_card_for_slot(spawned_card)

    await rt.sync_persistence()
    return {
        "message": out_msg.model_dump(),
        "ticket": turn_res["ticket"].model_dump(),
        "l1_report": turn_res["l1_report"],
        "spawned_card": spawned_card.model_dump() if spawned_card else None,
    }


@router.post("/api/v1/human-tool/submit")
async def submit_human_tool_card(
    req: HumanToolSubmitRequest, request: Request
) -> Any:
    rt = _rt(request)
    require_self_or_roles(request, req.actor_user_id)
    res = await rt.spider.handle_human_tool_submission(
        actor_user_id=req.actor_user_id,
        card_id=req.card_id,
        submitted_output=req.submitted_output,
    )
    if not res["accepted"]:
        await rt.sync_persistence()
        return JSONResponse(
            status_code=422,
            content={
                "accepted": False,
                "validation_errors": res["validation_errors"],
                "card": res["card"].model_dump(),
                "ticket": res["ticket"].model_dump(),
            },
        )

    next_card = res.get("next_card")
    if next_card is not None and not res.get("idempotent_replay"):
        fallback_fin_uid, _ = resolve_blackbox_user_and_slot(rt.containers)
        target_uid = fallback_fin_uid
        try:
            slot_obj = rt.containers.get_slot(next_card.target_slot_id)
            if slot_obj.occupant_id:
                target_uid = slot_obj.occupant_id
        except KeyError:
            pass
        if target_uid:
            await rt.wecom.push_interactive_card(
                target_user_id=target_uid,
                facade_bot="GOVERNANCE",
                card=next_card,
            )
        if rt.connectors is not None:
            await rt.connectors.dispatch_card_for_slot(next_card)

    await rt.sync_persistence()
    return {
        "accepted": True,
        "validation_errors": [],
        "card": res["card"].model_dump(),
        "ticket": res["ticket"].model_dump(),
        "next_card": next_card.model_dump() if next_card else None,
    }


@router.post("/api/v1/evolution/propose")
async def propose_skill_evolution(
    req: EvolutionProposeRequest, request: Request
) -> dict[str, Any]:
    rt = _rt(request)
    account = get_authenticated_account(request)
    if account is not None:
        req.proposer_id = account.user_id
        if req.override_code_for_security_test:
            require_roles(request, "manager", "boss")
    effective_proposer_id = req.proposer_id
    if not effective_proposer_id or effective_proposer_id not in rt.containers._profiles:
        effective_proposer_id, _ = resolve_frontline_user_and_slot(rt.containers)
    profile = rt.containers.get_profile(effective_proposer_id)
    report = await rt.arena.propose_and_evaluate(
        proposer_id=effective_proposer_id,
        natural_instruction=req.natural_instruction,
        override_code_for_security_test=req.override_code_for_security_test,
    )

    reply_summary = (
        f"🛠️【工匠锻造 & 影子擂台结案】\n"
        f"• 技能球：《{report.skill_title}》\n"
        f"• AST 静态安检：{'✅ 通过' if report.ast_passed else '❌ 拦截 (' + '；'.join(report.ast_violations) + ')'}\n"
        f"• 沙箱回放：{report.total_samples} 组真实/边界基准样本 | 成功率 {report.success_rate*100:.0f}% | 归一化吻合度 {report.match_rate*100:.1f}%\n"
        f"• 技能状态：{'已通过独立基准并挂载为 ACTIVE' if report.promoted else '候选待审核，需补充独立业务样本'}"
    )
    await rt.wecom.record_conversation_pair(
        user_id=effective_proposer_id,
        user_name=profile.name,
        facade_bot="GOVERNANCE",
        chat_type="SINGLE",
        inbound_text=f"[提议流程自动化] {req.natural_instruction}",
        outbound_reply=reply_summary,
        extra_card=report.model_dump(),
    )
    await rt.sync_persistence()
    return {"arena_report": report.model_dump()}


@router.post("/api/v1/evolution/candidates/{proposal_id}/publish")
async def publish_skill_candidate(proposal_id: str, req: PublishSkillRequest, request: Request) -> dict[str, Any]:
    rt = _rt(request)
    actor = require_roles(request, "manager", "boss")
    reviewer_id = actor.user_id if actor is not None else req.reviewer_id
    if not reviewer_id:
        raise HTTPException(status_code=422, detail="需要明确的审核人")
    if actor is not None and req.reviewer_id and req.reviewer_id != actor.user_id:
        raise HTTPException(status_code=403, detail="审核人必须为当前登录账号")
    result = await rt.arena.publish_candidate(
        proposal_id, reviewer_id,
        approved_source_hash=req.approved_source_hash,
        independent_samples=req.independent_samples,
    )
    await rt.sync_persistence()
    return result


@router.post("/api/v1/scoring/shadow-reviews")
async def review_shadow_output(req: ShadowReviewRequest, request: Request) -> dict[str, Any]:
    rt = _rt(request)
    account = require_roles(request, "manager", "boss")
    if account is None:
        raise HTTPException(status_code=401, detail="人工核验必须由已登录的管理账号完成")
    ticket = await rt.hot_store.get_ticket(req.ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="找不到待核验工单")
    if ticket.initiator_id == account.user_id:
        raise HTTPException(status_code=403, detail="人工核验人必须独立于任务申请人")
    rt.auth_custody.assert_can_manage_target_slot(account.user_id, ticket.slot_id)
    final_text = req.human_final_text.strip()
    if not final_text:
        raise HTTPException(status_code=422, detail="人工最终文本不能为空")
    messages = rt.wecom.get_chat_history(ticket.initiator_id, "employee")
    draft = next((m.content for m in reversed(messages) if m.ticket_id == ticket.ticket_id and m.direction == "OUTBOUND"), None)
    if draft is None or ticket.status != "COMPLETED":
        raise HTTPException(status_code=409, detail="需要已完成且保留原始 AI 输出的工单")
    reviews = getattr(rt, "shadow_reviews", {})
    fingerprint = hashlib.sha256(final_text.encode()).hexdigest()
    existing = reviews.get(ticket.ticket_id)
    if existing is not None:
        if existing["final_hash"] != fingerprint:
            raise HTTPException(status_code=409, detail="此工单已提交不同的人工核验结果")
        return {**existing, "idempotent_replay": True}
    result = await rt.scoring.on_shadow_trial_completed(
        ticket.initiator_id, ticket.slot_id, ai_draft_text=draft, human_final_text=final_text,
    )
    record = {
        "ticket_id": ticket.ticket_id, "reviewer_id": account.user_id,
        "draft_hash": hashlib.sha256(draft.encode()).hexdigest(), "final_hash": fingerprint,
        "human_final_text": final_text, "score": result,
    }
    reviews[ticket.ticket_id] = record
    rt.shadow_reviews = reviews
    rt.vault.append_event(
        event_kind="HUMAN_SHADOW_REVIEW_RECORDED", subtree_root_id=ticket.subtree_root_id,
        actor_slot_id=account.slot_id,
        payload={key: value for key, value in record.items() if key != "human_final_text"},
    )
    await rt.sync_persistence()
    return {**record, "idempotent_replay": False}


@router.post("/api/v1/auth/accounts/{user_id}/external-identity")
async def bind_external_identity(user_id: str, req: ExternalIdentityRequest, request: Request) -> dict[str, Any]:
    rt = _rt(request)
    account = require_roles(request, "manager", "boss")
    if account is None:
        raise HTTPException(status_code=401, detail="外部身份绑定需要明确的管理账号")
    rt.auth_custody.assert_can_manage_target_slot(account.user_id, rt.containers.get_profile(user_id).slot_id)
    external_id = req.wecom_user_id.strip()
    if not external_id:
        raise HTTPException(status_code=422, detail="企微用户 ID 不能为空")
    if any(uid != user_id and metadata.get("wecom_user_id") == external_id for uid, metadata in rt.auth_custody.account_directory.items()):
        raise HTTPException(status_code=409, detail="此企微身份已绑定到其他账号")
    rt.auth_custody.account_directory[user_id]["wecom_user_id"] = external_id
    await rt.sync_persistence()
    return {"user_id": user_id, "wecom_user_id": external_id}


@router.post("/api/v1/swarm/inject-burst")
async def trigger_swarm_drill(
    req: SwarmDrillRequest, request: Request
) -> dict[str, Any]:
    rt = _rt(request)
    require_roles(request, "manager", "boss")
    all_nodes = await rt.hot_store.list_nodes()
    default_aspect = next(
        (n for n in all_nodes if n.node_type == "ASPECT_NODE"),
        next((n for n in all_nodes if n.node_type == "BOARD_ROOT"), None),
    )
    effective_parent_nid = req.parent_node_id or (default_aspect.node_id if default_aspect else "node_board_root")
    effective_subtree = req.subtree_root_id or (default_aspect.subtree_root_id if default_aspect else "root")

    if req.mode == "BURST_PAD":
        res = await rt.spider.inject_concurrent_subtasks_and_check_span(
            parent_node_id=effective_parent_nid, burst_count=req.burst_count
        )
        await rt.sync_persistence()
        return {
            "mode": req.mode,
            "spawned_worker_ids": res["spawned_worker_ids"],
            "layer_padded": res["layer_padded"],
            "padded_relay_node": (
                res["padded_relay_node"].model_dump()
                if res["padded_relay_node"]
                else None
            ),
        }

    if req.mode == "HALLUCINATION_FAULT":
        fault = await rt.spider.simulate_subnode_hallucination_and_audit(
            subtree_root_id=effective_subtree
        )
        await rt.sync_persistence()
        return {
            "mode": req.mode,
            "corrupted_ticket_id": fault["corrupted_ticket_id"],
            "relay_node_id": fault["relay_node_id"],
            "audit_result": fault["audit_result"].model_dump(),
        }

    if req.mode == "BORROW_BALL":
        borrower_sid = req.borrower_slot_id
        lender_sid = req.lender_slot_id
        target_bid = req.ball_id
        if not (borrower_sid and lender_sid and target_bid):
            _, auto_frontline_sid = resolve_frontline_user_and_slot(rt.containers)
            _, auto_leader_sid = resolve_leader_user_and_slot(rt.containers)
            auto_auth_ball = resolve_active_authority_ball(rt.particles)
            all_slots = [s for s in rt.containers.list_slots() if s.slot_id != "SLOT_BOSS"]
            for s_lend in all_slots:
                candidate_bids = [
                    bid for bid in s_lend.ball_ids
                    if rt.particles.get_ball(bid).ball_type != "REDLINE"
                ]
                if candidate_bids:
                    s_borrow = next((x for x in all_slots if x.slot_id != s_lend.slot_id and candidate_bids[0] not in x.ball_ids), None)
                    if s_borrow is not None:
                        lender_sid = lender_sid or s_lend.slot_id
                        borrower_sid = borrower_sid or s_borrow.slot_id
                        target_bid = target_bid or candidate_bids[0]
                        break
            borrower_sid = borrower_sid or auto_frontline_sid
            lender_sid = lender_sid or auto_leader_sid
            target_bid = target_bid or auto_auth_ball
        if rt.particles.get_ball(target_bid).ball_type == "REDLINE":
            raise HTTPException(status_code=403, detail="红线资产不能通过演练借球入口下发")
        lease = rt.containers.borrow_ball(
            borrower_slot_id=borrower_sid,
            lender_slot_id=lender_sid,
            ball_id=target_bid,
            ttl_seconds=300,
        )
        await rt.spider.rehydrate_slot_nodes(
            [borrower_sid, lender_sid], reason="cross_slot_borrow"
        )
        all_nodes = await rt.hot_store.list_nodes()
        b_node = next((n for n in all_nodes if n.slot_id == lease.from_slot), None)
        await rt.pulse_bus.publish(
            event_type="BALL_MINTED",
            node_id=b_node.node_id if b_node else "node_board_root",
            subtree_root_id=b_node.subtree_root_id if b_node else "root",
            severity="INFO",
            summary=f"🤝 跨岗临时借球生效：{borrower_sid} 从 {lease.from_slot} 借入 [{lease.ball_id}]（TTL 300s 自动回收）",
            payload=lease.model_dump(),
        )
        await rt.sync_persistence()
        return {"mode": req.mode, "lease": lease.model_dump()}

    dehydrated = await rt.spider.dehydrate_idle_nodes(idle_seconds=0)
    await rt.sync_persistence()
    return {"mode": req.mode, "dehydrated_node_ids": dehydrated}


@router.post("/api/v1/swarm/nodes/{node_id}/lifecycle")
async def toggle_spider_node_lifecycle(
    node_id: str, req: NodeLifecycleRequest, request: Request
) -> dict[str, Any]:
    if req.role_view not in ("boss", "manager", "leader"):
        raise HTTPException(
            status_code=403,
            detail="仅分管组长、部门经理或总控有权调整节点脱水/热唤醒生命周期状态",
        )
    rt = _rt(request)
    try:
        res = await rt.spider.set_node_lifecycle(
            node_id=node_id, action=req.action, reason=req.reason
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await rt.sync_persistence()
    return res


@router.post("/api/v1/board/convene")
async def convene_board_session(
    req: BoardConveneRequest, request: Request
) -> dict[str, Any]:
    rt = _rt(request)
    require_roles(request, "boss")
    target_slot_id = req.target_slot_id
    if not target_slot_id or target_slot_id not in rt.containers._slots:
        _, target_slot_id = resolve_frontline_user_and_slot(rt.containers)
    slot_obj = rt.containers.get_slot(target_slot_id)
    agenda = req.agenda or f"审议【{slot_obj.slot_name} ({target_slot_id})】启动师徒反转（HYBRID_TRANSITION）接管议案"
    resolution = await rt.board.convene(
        agenda=agenda,
        target_slot_id=target_slot_id,
        force_security_veto=req.force_security_veto,
    )
    boss_uid = next((p.user_id for p in rt.containers.list_profiles() if p.role_view == "boss"), None)
    await rt.wecom.push_board_brief(
        resolution.executive_brief,
        resolution.model_dump(),
        target_user_id=boss_uid,
    )
    await rt.sync_persistence()
    return {"resolution": resolution.model_dump()}


@router.post("/api/v1/board/approve-transition")
async def decide_board_resolution(
    req: BoardDecisionRequest, request: Request
) -> dict[str, Any]:
    rt = _rt(request)
    require_roles(request, "boss")
    try:
        out = await rt.board.apply_boss_decision(
            resolution_id=req.resolution_id, approve=req.approve
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await rt.sync_persistence()
    return {
        "resolution": out["resolution"].model_dump(),
        "updated_slot": (
            out["updated_slot"].model_dump() if out["updated_slot"] else None
        ),
        "preference_weights": out["preference_weights"],
    }


@router.post("/api/v1/vault/rollback")
async def rollback_from_vault(
    req: VaultRollbackRequest, request: Request
) -> dict[str, Any]:
    rt = _rt(request)
    actor = require_roles(request, "boss")
    _, exec_sids = resolve_executive_slots(rt.containers)
    boss_sids, mgr_sids = resolve_executive_slots(rt.containers)
    if req.scope == "LOCAL":
        all_nodes = await rt.hot_store.list_nodes()
        sub = req.subtree_root_id or next(
            (n.subtree_root_id for n in all_nodes if n.node_type == "ASPECT_NODE"),
            "root",
        )
        _, relay_nid, _ = await rt.spider._resolve_leader_target()
        actor_sid = actor.slot_id if actor is not None else (mgr_sids[0] if mgr_sids else (boss_sids[0] if boss_sids else "SLOT_BOSS"))
        snap_hash = await rt.edge_relay.execute_local_rollback(
            subtree_root_id=sub,
            relay_node_id=relay_nid,
            actor_slot_id=actor_sid,
            reason=req.reason,
            target_snapshot_hash=req.snapshot_hash,
        )
    else:
        snap_hash = await rt.edge_relay.execute_global_rollback(
            actor_slot_id=boss_sids[0] if boss_sids else "SLOT_BOSS",
            reason=req.reason,
            target_snapshot_hash=req.snapshot_hash,
        )
    await rt.sync_persistence()
    return {
        "scope": req.scope,
        "restored_snapshot_hash": snap_hash,
        "vault_health": rt.vault.verify_chain_integrity().model_dump(),
    }


@router.get("/api/v1/vault/verify")
async def verify_vault_chain(request: Request) -> dict[str, Any]:
    rt = _rt(request)
    return rt.vault.verify_chain_integrity().model_dump()


@router.get("/api/v1/system/health")
async def get_system_health(request: Request) -> dict[str, Any]:
    rt = _rt(request)
    vault_report = rt.vault.verify_chain_integrity()
    nodes = await rt.hot_store.list_nodes()
    cave_meta = rt.cave_explorer.export_meta_state() if rt.cave_explorer else {}
    return {
        "status": "ok" if vault_report.intact else "degraded",
        "persistence": {
            "sqlite_db_url": rt.settings.sqlite_db_url,
            "restored_from_persistence": rt.restored_from_persistence,
            "workspace_mode": str(cave_meta.get("mode") or "DEMO_SEED"),
            "enterprise_name": str(cave_meta.get("enterprise_name") or ""),
            "slot_count": len(rt.containers.list_slots()),
            "profile_count": len(rt.containers.list_profiles()),
            "ball_count": len(rt.particles.list_all_balls()),
            "node_count": len(nodes),
        },
        "vault_integrity": vault_report.model_dump(),
        "llm_gateway": {
            "live_enabled": bool(rt.llm_gateway.is_live_mode),
            "mode": (
                "LIVE_CLOUD_HYBRID"
                if rt.llm_gateway.is_live_mode
                else "DETERMINISTIC_NEURAL_ENGINE"
            ),
            "model_l2_fast": rt.settings.llm_model_l2_fast,
            "model_l3_reasoner": rt.settings.llm_model_l3_reasoner,
            "base_url": rt.settings.llm_base_url,
        },
        "sandbox_limits": {
            "timeout_seconds": rt.settings.sandbox_timeout_seconds,
            "max_memory_mb": rt.settings.sandbox_max_memory_mb,
            "max_output_bytes": rt.settings.sandbox_max_output_bytes,
            "recursion_limit": 200,
        },
        "external_connectors": (
            rt.connectors.health_summary()
            if rt.connectors is not None
            else {"total_bindings": 0, "hmac_configured": False}
        ),
        "security": {
            "enforce_bearer_auth": rt.settings.enforce_bearer_auth,
            "password_hash_scheme": "pbkdf2_sha256",
            "active_sessions": (
                len(rt.auth_custody._sessions) if rt.auth_custody is not None else 0
            ),
        },
    }


@router.websocket("/ws/events")
async def websocket_pulse_endpoint(websocket: WebSocket) -> None:
    rt: ArachneRuntime = websocket.app.state.runtime
    await websocket.accept()
    try:
        frame = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
        if frame.get("type") != "authenticate" or not isinstance(frame.get("token"), str):
            await websocket.close(code=4401)
            return
        try:
            account = rt.auth_custody.resolve_bearer_token(f"Bearer {frame['token']}")
        except (ValueError, KeyError):
            await websocket.close(code=4401)
            return
        await rt.pulse_bus.register_ws(websocket, account.user_id, accepted=True, token=frame["token"])
        await websocket.send_json({"type": "authenticated"})
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
            except asyncio.TimeoutError:
                # Browser clients may remain silent while receiving updates.
                # Use idle periods to check revocation without dropping them.
                pass
            try:
                rt.auth_custody.resolve_bearer_token(f"Bearer {frame['token']}")
            except (ValueError, KeyError):
                await websocket.close(code=4401)
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        rt.pulse_bus.unregister_ws(websocket)


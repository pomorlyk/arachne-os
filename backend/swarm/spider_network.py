from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import asyncio
import copy
import re
import uuid
from typing import Any, Callable, Coroutine, Iterable, Literal, Optional

from config import ArachneSettings
from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from core.human_tool import HumanBlackBoxManager, WorkflowConflictError
from core.llm_gateway import LLMGateway, _skill_input_fields, sanitize_l1_text
from core.particles import ParticleEngine
from core.topology_resolver import (
    resolve_blackbox_user_and_slot,
    resolve_executive_slots,
    resolve_frontline_user_and_slot,
    resolve_leader_user_and_slot,
    resolve_primary_catalog_item,
)
from core.schemas import (
    BlackBoxTaskCard,
    FacadeBotType,
    SpiderNode,
    WorkTicket,
    utc_now_iso,
)
from database import HotStateStore
from swarm.edge_audit_relay import EdgeAuditRelay
from swarm.pulse_bus import PulseBus

ShadowTrialHook = Callable[[str, str, bool], Coroutine[Any, Any, None]]
PenaltyHook = Callable[[str], Coroutine[Any, Any, None]]


def _parse_iso_dt(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


class SpiderNetwork:
    """
    活体蛛网拓扑与工单调度核心 (SpiderNetwork)：
    - 存算分离 WorkTicket 流转；
    - 不入网不认账 (Gatekeeper) 与高压线强制人工拍板；
    - 横向标签共现自动开辟新业务域 (Aspect)；
    - 纵向并发跨度 > MAX_SPAN 自动分裂插入中继审查哨所 (RELAY_NODE)；
    - 闲置节点脱水休眠 (DEHYDRATED) 与新流量秒级热唤醒 (NODE_REHYDRATED)。
    """

    def __init__(
        self,
        settings: ArachneSettings,
        vault: BlackBoxVault,
        hot_store: HotStateStore,
        particles: ParticleEngine,
        containers: ContainerRegistry,
        human_tools: HumanBlackBoxManager,
        llm_gateway: LLMGateway,
        edge_relay: EdgeAuditRelay,
        pulse_bus: PulseBus,
    ) -> None:
        self._settings = settings
        self._vault = vault
        self._hot_store = hot_store
        self._particles = particles
        self._containers = containers

        def current_slot_role(slot_id: str) -> str:
            slot = containers.get_slot(slot_id)
            return containers.get_profile(slot.occupant_id).role_view

        particles.bind_role_resolver(current_slot_role)
        self._human_tools = human_tools
        self._llm = llm_gateway
        self._relay = edge_relay
        self._pulse = pulse_bus

        self._verified_orders_by_user: dict[str, list[dict[str, Any]]] = {}
        self._shadow_hook: Optional[ShadowTrialHook] = None
        self._penalty_hook: Optional[PenaltyHook] = None
        self._aspect_lock = asyncio.Lock()
        self._submission_lock = asyncio.Lock()
        self._topology_lock = asyncio.Lock()
        self._submission_results: dict[str, dict[str, Any]] = {}
        self._supervisor_authorizer: Optional[Callable[[str, str], bool]] = None

    def bind_human_supervisor_authorizer(self, authorizer: Callable[[str, str], bool]) -> None:
        """Bind a server-owned organization/policy check, never a request flag."""
        self._supervisor_authorizer = authorizer

    def export_state(self) -> dict[str, Any]:
        return copy.deepcopy({
            "verified_orders_by_user": self._verified_orders_by_user,
            "submission_results": self._submission_results,
        })

    def reset_workspace_state(self) -> None:
        self._verified_orders_by_user = {}
        self._submission_results = {}

    def restore_state(self, state: dict[str, Any] | None) -> None:
        self.reset_workspace_state()
        if state:
            self._verified_orders_by_user = copy.deepcopy(state.get("verified_orders_by_user", {}))
            self._submission_results = copy.deepcopy(state.get("submission_results", {}))

    def _matching_verified_order(self, user_id: str, text: str) -> dict[str, Any] | None:
        # An old order for this employee is not authority for an unrelated customer.
        for order in self._verified_orders_by_user.get(user_id, []):
            oid = str(order.get("order_id", ""))
            customer = str(order.get("customer_name", ""))
            if oid and customer and re.search(r"(?<![A-Za-z0-9_-])" + re.escape(oid) + r"(?![A-Za-z0-9_-])", text) and customer in text:
                return order
        return None

    def bind_scoring_hooks(
        self, shadow_hook: ShadowTrialHook, penalty_hook: PenaltyHook
    ) -> None:
        self._shadow_hook = shadow_hook
        self._penalty_hook = penalty_hook

    async def rehydrate_slot_nodes(
        self,
        slot_ids: Iterable[str],
        reason: str = "task_routed",
    ) -> list[str]:
        """级联热唤醒：唤醒指定槽位节点及其父链上的 RELAY_NODE / ASPECT_NODE。"""
        target_slots = {str(sid) for sid in slot_ids if sid}
        if not target_slots:
            return []

        all_nodes = await self._hot_store.list_nodes()
        self._containers.sync_slot_node_map_from_nodes(all_nodes)
        node_by_id = {n.node_id: n for n in all_nodes}

        chain_ids: list[str] = []
        seen: set[str] = set()
        for n in all_nodes:
            if n.slot_id in target_slots:
                cur: Optional[SpiderNode] = n
                while cur is not None and cur.node_id not in seen:
                    if cur.node_id == n.node_id or cur.node_type in ("RELAY_NODE", "ASPECT_NODE", "WORKER_SLOT", "BLACKBOX_HUMAN"):
                        seen.add(cur.node_id)
                        chain_ids.append(cur.node_id)
                    pid = cur.parent_id
                    cur = node_by_id.get(pid) if pid else None

        rehydrated: list[str] = []
        now_ts = utc_now_iso()
        for nid in chain_ids:
            node = node_by_id[nid]
            was_dehydrated = node.status == "DEHYDRATED"
            node.last_active_at = now_ts
            if was_dehydrated:
                node.status = "ACTIVE"
                node.active_load = max(1, node.active_load + 1)
                rehydrated.append(nid)
            await self._hot_store.upsert_node(node)

        if rehydrated:
            await self._pulse.publish(
                event_type="NODE_REHYDRATED",
                node_id=rehydrated[0],
                subtree_root_id=node_by_id[rehydrated[0]].subtree_root_id,
                severity="INFO",
                summary=(
                    f"⚡ 级联热唤醒 ({reason})：已将 {len(rehydrated)} 个休眠节点及上级链路恢复至 ACTIVE 运行态"
                ),
                payload={
                    "reason": reason,
                    "slot_ids": sorted(target_slots),
                    "rehydrated_node_ids": rehydrated,
                },
            )
        return rehydrated

    async def set_node_lifecycle(
        self,
        node_id: str,
        action: Literal["DEHYDRATE", "REHYDRATE"],
        reason: str = "manual_toggle",
    ) -> dict[str, Any]:
        all_nodes = await self._hot_store.list_nodes()
        node_by_id = {n.node_id: n for n in all_nodes}
        target = node_by_id.get(node_id)
        if target is None:
            raise KeyError(f"SpiderNode {node_id} not found")
        if action == "DEHYDRATE":
            if target.node_type == "BOARD_ROOT":
                raise ValueError("顶层 BOARD_ROOT 火种节点禁止脱水休眠")
            target.status = "DEHYDRATED"
            target.active_load = 0
            target.last_active_at = utc_now_iso()
            await self._hot_store.upsert_node(target)
            await self._pulse.publish(
                event_type="NODE_DEHYDRATED",
                node_id=target.node_id,
                subtree_root_id=target.subtree_root_id,
                severity="INFO",
                summary=f"❄️ 手动脱水休眠：[{target.label}] 已进入低功耗 DEHYDRATED 休眠态",
                payload={"node_id": target.node_id, "reason": reason},
            )
            return {
                "action": action,
                "status": target.status,
                "node": target.model_dump(),
                "rehydrated_node_ids": [],
            }

        # REHYDRATE: 唤醒自身及父级链路上全部 DEHYDRATED 节点
        rehydrated: list[str] = []
        now_ts = utc_now_iso()
        cur: Optional[SpiderNode] = target
        visited: set[str] = set()
        while cur is not None and cur.node_id not in visited:
            visited.add(cur.node_id)
            if cur.status == "DEHYDRATED":
                cur.status = "ACTIVE"
                cur.active_load = max(1, cur.active_load + 1)
                rehydrated.append(cur.node_id)
            cur.last_active_at = now_ts
            await self._hot_store.upsert_node(cur)
            cur = node_by_id.get(cur.parent_id) if cur.parent_id else None

        if rehydrated:
            await self._pulse.publish(
                event_type="NODE_REHYDRATED",
                node_id=target.node_id,
                subtree_root_id=target.subtree_root_id,
                severity="INFO",
                summary=f"⚡ 节点热唤醒：[{target.label}] 及关联链路 ({len(rehydrated)} 节点) 已恢复 ACTIVE",
                payload={"reason": reason, "rehydrated_node_ids": rehydrated},
            )
        return {
            "action": action,
            "status": target.status,
            "node": target.model_dump(),
            "rehydrated_node_ids": rehydrated,
        }

    async def _find_or_wake_slot_node(self, slot_id: str) -> SpiderNode:
        await self.rehydrate_slot_nodes([slot_id], reason="inbound_slot_traffic")
        all_nodes = await self._hot_store.list_nodes()
        self._containers.sync_slot_node_map_from_nodes(all_nodes)
        for n in all_nodes:
            if n.slot_id == slot_id:
                return n
        return all_nodes[0]

    async def _resolve_leader_target(self) -> tuple[str, str, str]:
        all_nodes = await self._hot_store.list_nodes()
        lit_relays = [
            n for n in all_nodes
            if n.node_type == "RELAY_NODE" and n.exploration_state == "LIT" and n.slot_id
        ]
        all_relays = [n for n in all_nodes if n.node_type == "RELAY_NODE" and n.slot_id]
        chosen = lit_relays[0] if lit_relays else (all_relays[0] if all_relays else None)
        if chosen is not None and chosen.slot_id:
            clean_label = re.sub(r"（[^）]+）", "", chosen.label).strip() or chosen.label
            return chosen.slot_id, chosen.node_id, clean_label
        ldr_uid, ldr_sid = resolve_leader_user_and_slot(self._containers)
        ldr_nid = self._containers.resolve_node_id_for_slot(ldr_sid) if ldr_sid else "node_board_root"
        ldr_label = "业务复核主管"
        if ldr_uid and ldr_uid in self._containers._profiles:
            p = self._containers.get_profile(ldr_uid)
            ldr_label = f"{p.title}-{p.name}"
        return ldr_sid or "SLOT_BOSS", ldr_nid, ldr_label

    async def _resolve_finance_target(self) -> tuple[str, str, str]:
        all_nodes = await self._hot_store.list_nodes()
        lit_bb = [
            n for n in all_nodes
            if (n.node_type == "BLACKBOX_HUMAN" or "开票" in n.label or "税控" in n.label)
            and n.exploration_state == "LIT"
            and n.slot_id
        ]
        all_bb = [
            n for n in all_nodes
            if (n.node_type == "BLACKBOX_HUMAN" or "开票" in n.label or "税控" in n.label)
            and n.slot_id
        ]
        chosen = lit_bb[0] if lit_bb else (all_bb[0] if all_bb else None)
        if chosen is not None and chosen.slot_id:
            clean_label = re.sub(r"（[^）]+）", "", chosen.label).strip() or chosen.label
            return chosen.slot_id, chosen.node_id, clean_label
        bb_uid, bb_sid = resolve_blackbox_user_and_slot(self._containers)
        bb_nid = self._containers.resolve_node_id_for_slot(bb_sid) if bb_sid else "node_board_root"
        bb_label = "财税人机黑盒专岗"
        if bb_uid and bb_uid in self._containers._profiles:
            p = self._containers.get_profile(bb_uid)
            bb_label = f"{p.title}-{p.name}"
        return bb_sid or "SLOT_BOSS", bb_nid, bb_label

    async def _resolve_aspect_relay_node_id(self, subtree_root_id: str) -> str:
        all_nodes = await self._hot_store.list_nodes()
        for n in all_nodes:
            if n.node_id == "node_aspect_fulfill":
                return n.node_id
        for n in all_nodes:
            if n.subtree_root_id == subtree_root_id and n.node_type in ("ASPECT_NODE", "RELAY_NODE"):
                return n.node_id
        for n in all_nodes:
            if n.node_type == "ASPECT_NODE" and n.exploration_state == "LIT":
                return n.node_id
        return "node_board_root"

    async def process_inbound_turn(
        self,
        sender_id: str,
        facade_bot: FacadeBotType,
        content: str,
        raw_wechat_forward: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        profile = self._containers.get_profile(sender_id)
        slot_id = profile.slot_id
        worker_node = await self._find_or_wake_slot_node(slot_id)

        # 1. L1 本地零成本公私剥离与敏感号硬脱敏
        l1_report = sanitize_l1_text(content, raw_wechat_forward)
        self._llm.record_l1_call()
        effective_ids = self._containers.get_effective_ball_ids(slot_id)

        # 2. 容器级 REDLINE 红线底价拦截（同步毫秒级阻断）
        violated_ball = self._particles.check_redline_violation(
            slot_id=slot_id,
            effective_ball_ids=effective_ids,
            query_text=l1_report.clean_text or content,
        )
        if violated_ball is not None:
            probe_count = await self._hot_store.increment_boundary_probe(sender_id)
            self._containers.record_boundary_probe(sender_id, synced_count=probe_count)
            if self._penalty_hook is not None:
                await self._penalty_hook(sender_id)

            ticket = WorkTicket(
                ticket_id=f"TKT_{uuid.uuid4().hex[:8].upper()}",
                subtree_root_id=worker_node.subtree_root_id,
                node_id=worker_node.node_id,
                initiator_id=sender_id,
                slot_id=slot_id,
                facade_bot=facade_bot,
                status="INTERCEPTED",
                summary=f"越界试探红线拦截：{violated_ball.title}",
                sanitized_payload={
                    "blocked_query": l1_report.clean_text,
                    "violated_ball_id": violated_ball.ball_id,
                },
            )
            await self._hot_store.upsert_ticket(ticket)
            self._vault.append_event(
                event_kind="REDLINE_INTERCEPTED",
                subtree_root_id=worker_node.subtree_root_id,
                actor_slot_id=slot_id,
                payload={
                    "user_id": sender_id,
                    "ticket_id": ticket.ticket_id,
                    "violated_ball_id": violated_ball.ball_id,
                    "boundary_probes_total": probe_count,
                },
            )
            await self._pulse.publish(
                event_type="RELAY_INTERCEPTED",
                node_id=worker_node.node_id,
                subtree_root_id=worker_node.subtree_root_id,
                severity="CRITICAL",
                summary=(
                    f"🛑 红线拦截：{profile.name} 试图越界调阅 [{violated_ball.title}]，"
                    f"已当场阻断并记入 B 面越界计数（累计 {probe_count} 次）"
                ),
                payload={
                    "user_id": sender_id,
                    "violated_ball_id": violated_ball.ball_id,
                },
            )
            return {
                "reply": (
                    f"⛔【红线球当场拦截 · {violated_ball.title}】\n"
                    f"你所在的岗位容器（{slot_id}）无权查看工厂拿货底价与绝密成本结构。"
                    "本次越界试探已只追写记入黑匣子审计账本，个人综合绩效已执行风控扣减。"
                ),
                "ticket": ticket,
                "l1_report": {
                    "redacted_pii_count": l1_report.redacted_pii_count,
                    "stripped_private_count": l1_report.stripped_private_count,
                    "clean_text": l1_report.clean_text,
                },
                "spawned_card": None,
            }

        # 3. Tier L2 ExplorerSpider 门禁核查与业务处理
        accessible_balls = self._particles.get_accessible_balls(slot_id, effective_ids)
        has_forwarded = bool(raw_wechat_forward and len(raw_wechat_forward) > 0)
        matched_order = self._matching_verified_order(sender_id, l1_report.clean_text)
        has_prior_order = matched_order is not None

        decision = await self._llm.analyze_explorer_turn(
            clean_text=l1_report.clean_text,
            has_forwarded_evidence=has_forwarded,
            has_prior_order_context=has_prior_order,
            accessible_balls=accessible_balls,
            # Guards need rule keywords, never the protected commercial payload.
            # Authorized boss queries must not be rejected by the model fallback.
            redline_balls=[
                ball.model_copy(update={"content": ""})
                for ball in self._particles.list_redline_balls()
                if ball.ball_id not in {b.ball_id for b in accessible_balls}
            ],
        )

        # Enforce provenance independently of model decisions and inline order-number claims.
        fulfillment_requested = (
            any(word in l1_report.clean_text for word in ("发货", "出库", "锁库"))
            or bool(
                re.search(
                    r"(?:直接|立即|立刻|马上)\s*发\s*\d+\s*(?:把|台|张|套|件|片|块)",
                    l1_report.clean_text,
                )
            )
            or bool(
                re.search(
                    r"给.{1,18}发\s*\d+\s*(?:把|台|张|套|件|片|块).*(?:过去|送|到)",
                    l1_report.clean_text,
                )
            )
        )
        if fulfillment_requested and not has_prior_order:
            decision.context_complete = False
            decision.missing_context_prompt = "🛑【不入网不认账拦截】请提供已核验订单号和对应客户；新订单须先导入客户确认记录。"
        if decision.structured_order_draft:
            draft = decision.structured_order_draft
            quantity = re.search(
                r"(\d+)\s*(?:把|台|张|套|件|片|块)", l1_report.clean_text
            )
            customer = str(draft.get("customer_name", ""))
            product = str(draft.get("product_name", ""))
            if (
                not quantity
                or not customer
                or customer not in l1_report.clean_text
                or not product
                or (
                    product not in l1_report.clean_text
                    and product.split("-")[0] not in l1_report.clean_text
                )
                or int(quantity.group(1)) != draft.get("quantity")
            ):
                decision.context_complete = False
                decision.missing_context_prompt = (
                    "请补充可核验的客户、商品型号和数量；无订单内容的转发不能建单。"
                )
        if decision.high_voltage_triggered and not matched_order:
            money = re.search(r"\d+(?:\.\d+)?\s*元", l1_report.clean_text)
            order_money = re.search(
                r"(?:订单|货款|总额|金额|原价|总价)[^\d]{0,6}\d+(?:\.\d+)?\s*元",
                l1_report.clean_text,
            )
            if money is None or ("折" in l1_report.clean_text and order_money is None):
                decision.context_complete = False
                decision.missing_context_prompt = "请提供明确申请金额；折扣申请还须关联已核验订单号和客户或说明订单原金额。"
        weight_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:公斤|kg|KG)", l1_report.clean_text)
        amt_m = re.search(
            r"(?:金额|总价|满|订单)?\s*(\d+(?:\.\d+)?)\s*元", l1_report.clean_text
        )
        if weight_m and amt_m is None:
            for ball in accessible_balls:
                if ball.ball_type != "SKILL" or not ball.executable_code_path:
                    continue
                script_path = Path(ball.executable_code_path)
                if not script_path.is_absolute():
                    script_path = self._settings.sandbox_workspace_dir / script_path
                try:
                    source = script_path.read_text(encoding="utf-8")
                except OSError:
                    continue
                if (
                    "weight_kg" not in source
                    and "weight" not in source
                    and "运费" not in ball.title
                ):
                    continue
                if set(_skill_input_fields(source)) & {
                    "order_amount",
                    "amount",
                    "订单金额",
                }:
                    decision.context_complete = False
                    decision.missing_context_prompt = (
                        "请提供本次订单金额，以核验免运费条件并计算实际运费。"
                    )
                break
        # 分支 3A：不入网不认账（无前置订单依据直接请求发货/出库）
        if not decision.context_complete:
            ticket = WorkTicket(
                ticket_id=f"TKT_{uuid.uuid4().hex[:8].upper()}",
                subtree_root_id=worker_node.subtree_root_id,
                node_id=worker_node.node_id,
                initiator_id=sender_id,
                slot_id=slot_id,
                facade_bot="GOVERNANCE",
                status="PENDING_CONTEXT",
                summary="不入网不认账挂起：缺少前置订单依据",
                sanitized_payload={"clean_text": l1_report.clean_text},
            )
            await self._hot_store.upsert_ticket(ticket)
            await self._pulse.publish(
                event_type="RELAY_INTERCEPTED",
                node_id=worker_node.node_id,
                subtree_root_id=worker_node.subtree_root_id,
                severity="WARNING",
                summary=f"🚧 不入网不认账：{profile.name} 发起无依据动作请求，已由 #2 风控官挂起追问上下文",
                payload={"ticket_id": ticket.ticket_id},
            )
            return {
                "reply": decision.missing_context_prompt or decision.reply_to_user,
                "ticket": ticket,
                "l1_report": {
                    "redacted_pii_count": l1_report.redacted_pii_count,
                    "stripped_private_count": l1_report.stripped_private_count,
                    "clean_text": l1_report.clean_text,
                },
                "spawned_card": None,
            }

        # 分支 3B：涉钱/超低折扣/客户赔偿高压线挂起 -> 动态推送至当前企业风控/复核组长审批卡
        if decision.high_voltage_triggered:
            (
                leader_slot_id,
                leader_node_id,
                leader_label,
            ) = await self._resolve_leader_target()
            last_order = matched_order or {}

            tax_m = re.search(r"\b([0-9A-Z]{15,18})\b", l1_report.clean_text)
            comp_m = re.search(
                r"([\u4e00-\u9fa5A-Za-z0-9]{2,18}(?:股份有限公司|有限责任公司|科技有限公司|有限公司|集团|电子|精密))",
                l1_report.clean_text,
            )
            cust_m = re.search(
                r"([\u4e00-\u9fa5A-Za-z0-9]{1,8}(?:总|经理|工|女士|先生))",
                l1_report.clean_text,
            )
            order_amt_m = re.search(
                r"(?:订单|货款|总额|金额|原价|总价)[^\d]{0,6}(\d+(?:\.\d+)?)\s*元",
                l1_report.clean_text,
            )
            amt_match = re.search(r"(\d+(?:\.\d+)?)\s*元", l1_report.clean_text)
            disc_m = re.search(r"([1-9](?:\.\d)?)\s*折", l1_report.clean_text)

            catalog_item = resolve_primary_catalog_item(self._particles)
            default_cust = "对接客户代表"
            default_prod = catalog_item or "企业主营定制订单"
            default_title = "待核验企业开票抬头"
            default_tax = ""

            customer_name = str(
                last_order.get("customer_name")
                or (comp_m.group(1) if comp_m else "")
                or (cust_m.group(1) if cust_m else "")
                or default_cust
            )
            invoice_title = str(
                last_order.get("invoice_title")
                or (comp_m.group(1) if comp_m else "")
                or (
                    f"{customer_name}有限公司"
                    if ("公司" not in customer_name and "待核验" not in customer_name)
                    else customer_name
                )
                or default_title
            )
            tax_id = str(
                last_order.get("tax_id")
                or (tax_m.group(1) if tax_m else "")
                or default_tax
            )
            product_name = str(last_order.get("product_name") or default_prod)

            if last_order.get("total_amount") is not None:
                base_amt = float(last_order["total_amount"])
                disc_factor = float(disc_m.group(1)) / 10.0 if disc_m else 1.0
                compensation = re.search(
                    r"(?:赔偿|赔付|返工|重做)[^\d]{0,6}(\d+(?:\.\d+)?)\s*元",
                    l1_report.clean_text,
                )
                comp_amt = float(compensation.group(1)) if compensation else 0.0
                requested_net_amount = round(base_amt * disc_factor - comp_amt, 2)
            elif order_amt_m:
                base_amt = float(order_amt_m.group(1))
                disc_factor = float(disc_m.group(1)) / 10.0 if disc_m else 1.0
                comp_m2 = re.search(
                    r"(?:赔偿|赔付|返工|重做)[^\d]{0,6}(\d+(?:\.\d+)?)\s*元",
                    l1_report.clean_text,
                )
                comp_amt = float(comp_m2.group(1)) if comp_m2 else 0.0
                requested_net_amount = round(base_amt * disc_factor - comp_amt, 2)
            elif amt_match:
                base_amt = float(amt_match.group(1))
                disc_factor = float(disc_m.group(1)) / 10.0 if disc_m else 1.0
                requested_net_amount = round(base_amt * disc_factor, 2)
            else:
                raise ValueError("缺少可核验申请金额")

            ticket = WorkTicket(
                ticket_id=f"TKT_{uuid.uuid4().hex[:8].upper()}",
                subtree_root_id=worker_node.subtree_root_id,
                node_id=leader_node_id,
                initiator_id=sender_id,
                slot_id=slot_id,
                facade_bot="GOVERNANCE",
                status="PENDING_LEADER_APPROVAL",
                summary=f"高压线待审批：{decision.high_voltage_reason}",
                sanitized_payload={
                    "customer_name": customer_name,
                    "product_summary": f"{product_name} 批次特批",
                    "requested_amount": requested_net_amount,
                    "invoice_title": invoice_title,
                    "tax_id": tax_id,
                    "clean_request": l1_report.clean_text,
                },
                high_voltage_category=decision.high_voltage_category,
                high_voltage_reason=decision.high_voltage_reason,
                assigned_approver_slot=leader_slot_id,
            )
            await self._hot_store.upsert_ticket(ticket)

            leader_card = self._human_tools.dispatch_card(
                ticket_id=ticket.ticket_id,
                contract_id="CONTRACT_LEADER_HV_APPROVAL",
                card_kind="LEADER_APPROVAL",
                target_slot_id_override=leader_slot_id,
                full_business_context={
                    "ticket_id": ticket.ticket_id,
                    "initiator_name": profile.name,
                    "customer_name": ticket.sanitized_payload["customer_name"],
                    "product_summary": ticket.sanitized_payload["product_summary"],
                    "high_voltage_category": decision.high_voltage_category,
                    "high_voltage_reason": decision.high_voltage_reason,
                    "requested_amount": requested_net_amount,
                    "invoice_title": ticket.sanitized_payload["invoice_title"],
                    "tax_id": ticket.sanitized_payload["tax_id"],
                },
            )
            self._vault.append_event(
                event_kind="HIGH_VOLTAGE_ESCALATED",
                subtree_root_id=worker_node.subtree_root_id,
                actor_slot_id=slot_id,
                payload={
                    "ticket_id": ticket.ticket_id,
                    "card_id": leader_card.card_id,
                    "reason": decision.high_voltage_reason,
                },
            )
            await self._pulse.publish(
                event_type="RELAY_INTERCEPTED",
                node_id=leader_node_id,
                subtree_root_id=worker_node.subtree_root_id,
                severity="WARNING",
                summary=f"⚡ 高压线熔断转交：{decision.high_voltage_reason} → 已推送审批卡 [{leader_card.card_id}] 至【{leader_label}】",
                payload={"ticket_id": ticket.ticket_id, "card_id": leader_card.card_id},
            )
            return {
                "reply": decision.reply_to_user,
                "ticket": ticket,
                "l1_report": {
                    "redacted_pii_count": l1_report.redacted_pii_count,
                    "stripped_private_count": l1_report.stripped_private_count,
                    "clean_text": l1_report.clean_text,
                },
                "spawned_card": leader_card,
            }

        # 分支 3C：正常业务应答或私聊公私剥离导单完成
        if decision.structured_order_draft:
            decision.structured_order_draft = copy.deepcopy(
                decision.structured_order_draft
            )
            decision.structured_order_draft["order_id"] = (
                f"ORD-{uuid.uuid4().hex[:12].upper()}"
            )
            decision.structured_order_draft["verified_by_user_id"] = sender_id
            decision.structured_order_draft["verified_at"] = utc_now_iso()
            decision.reply_to_user += f"\n• 订单号：{decision.structured_order_draft['order_id']}（后续操作须同时提供对应客户）"

        # 3D：【造球即用闭环】若当前工位挂载了已晋升 ACTIVE 的可执行 Python 技能球，且消息涉及运费/重量计算，直接净室调用脚本！
        executed_skill_meta: Optional[dict[str, Any]] = None
        if weight_m:
            from swarm.evolution_arena import run_skill_in_isolated_subprocess

            for b in accessible_balls:
                if (
                    b.ball_type == "SKILL"
                    and b.status == "ACTIVE"
                    and b.executable_code_path
                ):
                    script_p = Path(b.executable_code_path)
                    if not script_p.is_absolute():
                        script_p = self._settings.sandbox_workspace_dir / script_p
                    if not script_p.exists():
                        continue
                    try:
                        code_preview = script_p.read_text(
                            encoding="utf-8", errors="ignore"
                        )
                    except Exception:
                        code_preview = ""
                    if (
                        "weight_kg" not in code_preview
                        and "weight" not in code_preview
                        and "运费" not in b.title
                    ):
                        continue

                    w_val = float(weight_m.group(1))
                    a_val = float(amt_m.group(1)) if amt_m else None
                    inp_payload = {
                        "weight_kg": w_val,
                        "weight": w_val,
                        "重量": w_val,
                    }
                    if a_val is not None:
                        inp_payload.update(
                            {"order_amount": a_val, "amount": a_val, "订单金额": a_val}
                        )
                    try:
                        run_out = run_skill_in_isolated_subprocess(
                            script_path=script_p,
                            sandbox_dir=self._settings.sandbox_workspace_dir,
                            input_payloads=[inp_payload],
                        )
                        if run_out and run_out[0].get("ok"):
                            fee_val = run_out[0]["output"].get("result", 0)
                            executed_skill_meta = {
                                "ball_id": b.ball_id,
                                "title": b.title,
                                "input": inp_payload,
                                "result": fee_val,
                            }
                            amount_note = (
                                f"，订单金额 ¥{a_val}" if a_val is not None else ""
                            )
                            decision.reply_to_user = (
                                f"⚡【已调用自进化技能球 {b.ball_id}《{b.title}》 · 0 LLM Token 消耗】\n"
                                f"• 输入参数：重量 {w_val}kg{amount_note}\n"
                                f"• 净室沙箱计算结果：应付运费 ¥{fee_val:.2f} 元"
                            )
                    except Exception:
                        pass
                    break

        # 若快速正则未命中，尝试通过通用 LLM 技能参数提取器调用任意行业 ACTIVE 技能球
        if executed_skill_meta is None:
            matched_call = await self._llm.extract_skill_call_payload(
                user_text=l1_report.clean_text,
                accessible_balls=accessible_balls,
                sandbox_dir=self._settings.sandbox_workspace_dir,
            )
            if matched_call is not None:
                b, script_p, inp_payload = matched_call
                from swarm.evolution_arena import run_skill_in_isolated_subprocess

                try:
                    run_out = run_skill_in_isolated_subprocess(
                        script_path=script_p,
                        sandbox_dir=self._settings.sandbox_workspace_dir,
                        input_payloads=[inp_payload],
                    )
                    if run_out and run_out[0].get("ok"):
                        res_val = run_out[0]["output"].get(
                            "result", run_out[0]["output"]
                        )
                        executed_skill_meta = {
                            "ball_id": b.ball_id,
                            "title": b.title,
                            "input": inp_payload,
                            "result": res_val,
                        }
                        decision.reply_to_user = (
                            f"⚡【已调用自进化技能球 {b.ball_id}《{b.title}》 · 净室沙箱精确执行】\n"
                            f"• 提取入参：{inp_payload}\n"
                            f"• 沙箱计算结果：{res_val}"
                        )
                except Exception:
                    pass

        ticket = WorkTicket(
            ticket_id=f"TKT_{uuid.uuid4().hex[:8].upper()}",
            subtree_root_id=worker_node.subtree_root_id,
            node_id=worker_node.node_id,
            initiator_id=sender_id,
            slot_id=slot_id,
            facade_bot=facade_bot,
            status="COMPLETED",
            summary=(
                f"导单入网：{decision.structured_order_draft['customer_name']}"
                if decision.structured_order_draft
                else f"业务协同：{l1_report.clean_text[:28]}"
            ),
            sanitized_payload={
                "clean_text": l1_report.clean_text,
                "order_draft": decision.structured_order_draft,
                "stripped_private_count": l1_report.stripped_private_count,
                "redacted_pii_count": l1_report.redacted_pii_count,
            },
        )
        if decision.structured_order_draft:
            decision.structured_order_draft["source_ticket_id"] = ticket.ticket_id
            ticket.sanitized_payload["order_draft"] = copy.deepcopy(
                decision.structured_order_draft
            )
            self._verified_orders_by_user.setdefault(sender_id, []).append(
                copy.deepcopy(decision.structured_order_draft)
            )
        await self._hot_store.upsert_ticket(ticket)

        # 封存合法业务里程碑快照
        clean_sub_state = await self._hot_store.export_subtree_state(
            worker_node.subtree_root_id
        )
        self._vault.seal_snapshot(
            subtree_root_id=worker_node.subtree_root_id,
            actor_slot_id=slot_id,
            state_dict=clean_sub_state,
            scope="LOCAL",
        )

        # 4. 异步旁路脉搏：自动搓球、横向共现分面聚类、后台静默影子陪跑算分
        self._pulse.schedule_background(
            self._run_background_swarm_evolution(
                sender_id=sender_id,
                slot_id=slot_id,
                worker_node=worker_node,
                extracted_candidates=decision.extracted_balls,
                is_routine_task=True,
            )
        )

        return {
            "reply": decision.reply_to_user,
            "ticket": ticket,
            "l1_report": {
                "redacted_pii_count": l1_report.redacted_pii_count,
                "stripped_private_count": l1_report.stripped_private_count,
                "clean_text": l1_report.clean_text,
            },
            "spawned_card": None,
        }

    async def _run_background_swarm_evolution(
        self,
        sender_id: str,
        slot_id: str,
        worker_node: SpiderNode,
        extracted_candidates: list[Any],
        is_routine_task: bool,
    ) -> None:
        # 1) 铸造新提取出的权能小球并装入岗位容器
        leader_slot_id, _, _ = await self._resolve_leader_target()
        owner_slots = list(dict.fromkeys([slot_id, leader_slot_id, "SLOT_DEPT_MGR", "SLOT_BOSS"]))
        for cand in extracted_candidates:
            minted = self._particles.mint_from_candidate(
                candidate=cand, owner_slot_ids=owner_slots
            )
            self._containers.attach_ball_to_slot(slot_id, minted.ball_id)
            await self._pulse.publish(
                event_type="BALL_MINTED",
                node_id=worker_node.node_id,
                subtree_root_id=worker_node.subtree_root_id,
                severity="SUCCESS",
                summary=f"🟢 自动搓球入桶：[{minted.ball_type}] {minted.title} → 挂载至 {slot_id}",
                payload={"ball_id": minted.ball_id, "title": minted.title},
            )

        # 2) 横向共现聚类检测：若产生新的业务域簇则自动生长出新的 ASPECT_NODE
        await self._sync_aspect_clusters()

        # Chat activity supplies no human-final/AI-draft comparison evidence.
        # Scoring is triggered only by the explicit comparison workflow.

    async def _sync_aspect_clusters(self) -> list[dict[str, Any]]:
        async with self._aspect_lock:
            clusters = self._particles.cluster_domain_aspects(min_cooccurrence=2)
            existing_nodes = await self._hot_store.list_nodes()
            existing_ids = {n.node_id for n in existing_nodes}

            for cl in clusters:
                aspect_node_id = f"node_{str(cl['aspect_id']).lower()}"
                # 跳过已涵盖在初始两个核心分面中的同类簇
                tags_set = set(cl["tags"])  # type: ignore[arg-type]
                already_covered = any(
                    n.node_type == "ASPECT_NODE" and len(tags_set & set(n.domain_tags)) >= 2
                    for n in existing_nodes
                )
                if aspect_node_id not in existing_ids and not already_covered:
                    existing_ids.add(aspect_node_id)
                    subtree_id = f"subtree_{uuid.uuid4().hex[:6]}"
                    boss_sids, mgr_sids = resolve_executive_slots(self._containers)
                    owner_slot = mgr_sids[0] if mgr_sids else (boss_sids[0] if boss_sids else "SLOT_BOSS")
                    new_aspect = SpiderNode(
                        node_id=aspect_node_id,
                        label=str(cl["aspect_title"]),
                        node_type="ASPECT_NODE",
                        parent_id="node_board_root",
                        subtree_root_id=subtree_id,
                        slot_id=owner_slot,
                        domain_tags=list(cl["tags"]),  # type: ignore[arg-type]
                        status="ACTIVE",
                        active_load=1,
                    )
                    await self._hot_store.upsert_node(new_aspect)
                    existing_nodes.append(new_aspect)
                    snap = await self._hot_store.export_subtree_state(subtree_id)
                    self._vault.seal_snapshot(subtree_id, owner_slot, snap, scope="LOCAL")
                    await self._pulse.publish(
                        event_type="ASPECT_CLUSTERED",
                        node_id=aspect_node_id,
                        subtree_root_id=subtree_id,
                        severity="SUCCESS",
                        summary=f"🕸️ 横向自动分面：共现聚类涌现新业务域 {cl['aspect_title']}，董事会同步增设动态席位",
                        payload=cl,
                    )
            return clusters

    async def handle_human_tool_submission(
        self, actor_user_id: str, card_id: str, submitted_output: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._submission_lock:
            return await self._handle_human_tool_submission_locked(actor_user_id, card_id, copy.deepcopy(submitted_output))

    async def _handle_human_tool_submission_locked(
        self, actor_user_id: str, card_id: str, submitted_output: dict[str, Any]
    ) -> dict[str, Any]:
        card = self._human_tools.get_card(card_id)
        ticket = await self._hot_store.get_ticket(card.ticket_id)
        if ticket is None:
            saved_ticket = self._submission_results.get(card_id, {}).get("ticket_snapshot")
            if card.status != "PENDING" and saved_ticket:
                ticket = WorkTicket(**saved_ticket)
            else:
                raise KeyError(f"Ticket {card.ticket_id} not found")

        try:
            actor = self._containers.get_profile(actor_user_id)
        except KeyError as exc:
            raise PermissionError("提交人不属于当前组织") from exc
        expected_role = "leader" if card.card_kind == "LEADER_APPROVAL" else "finance_tool"
        target_slot = self._containers.get_slot(card.target_slot_id)
        actual_target = (actor.slot_id == target_slot.slot_id and target_slot.occupant_id == actor_user_id and actor.role_view == expected_role)
        authorized_supervisor = bool(
            actor.role_view in ("leader", "manager", "boss")
            and self._supervisor_authorizer is not None
            and self._supervisor_authorizer(actor_user_id, target_slot.slot_id)
        )
        if not actual_target and not authorized_supervisor:
            raise PermissionError("仅任务目标岗位的授权角色或明确获授权主管可以提交")
        if actor_user_id == ticket.initiator_id:
            raise PermissionError("申请人不得审批或完成自己的黑盒工单")
        if card.status != "PENDING":
            if card.submitted_output != submitted_output:
                raise WorkflowConflictError("已完成的任务卡不允许更改结果")
            saved = self._submission_results.get(card_id, {})
            next_id = saved.get("next_card_id")
            if not next_id and card.card_kind == "LEADER_APPROVAL" and card.status == "APPROVED":
                existing = [c for c in self._human_tools.list_cards() if c.ticket_id == card.ticket_id and c.card_kind == "FINANCE_INVOICE"]
                next_id = existing[0].card_id if existing else None
                if not next_id:
                    raise WorkflowConflictError("审批状态不完整，请恢复对应工作流记录后重试")
            return {"accepted": True, "validation_errors": [], "card": card, "ticket": ticket,
                    "next_card": self._human_tools.get_card(next_id) if next_id else None}
        expected_ticket_status = "PENDING_LEADER_APPROVAL" if card.card_kind in ("LEADER_APPROVAL", "LEGAL_REVIEW") else "PENDING_FINANCE_BLACKBOX"
        if ticket.status != expected_ticket_status:
            raise WorkflowConflictError("工单当前状态不允许处理此任务卡")

        leader_slot_id, leader_node_id, _ = await self._resolve_leader_target()
        fin_slot_id, fin_node_id, fin_label = await self._resolve_finance_target()

        valid, errors, updated_card = self._human_tools.submit_and_validate(
            card_id, submitted_output
        )
        if not valid:
            self._containers.record_rework(actor_user_id)
            await self._pulse.publish(
                event_type="RELAY_INTERCEPTED",
                node_id=fin_node_id if card.card_kind == "FINANCE_INVOICE" else leader_node_id,
                subtree_root_id=ticket.subtree_root_id,
                severity="WARNING",
                summary=f"❌ 黑盒契约校验打回 [{card.card_id}]：{'；'.join(errors)}",
                payload={"card_id": card_id, "errors": errors},
            )
            return {
                "accepted": False,
                "validation_errors": errors,
                "card": updated_card,
                "ticket": ticket,
                "next_card": None,
            }

        next_card: Optional[BlackBoxTaskCard] = None
        if card.card_kind == "LEADER_APPROVAL":
            if updated_card.status == "APPROVED":
                approved_amt = float(submitted_output["approved_amount"])
                # 动态唤醒当前企业财务黑盒节点
                fin_node = await self._find_or_wake_slot_node(fin_slot_id)
                ticket.status = "PENDING_FINANCE_BLACKBOX"
                ticket.node_id = fin_node.node_id
                ticket.subtree_root_id = fin_node.subtree_root_id
                ticket.updated_at = utc_now_iso()
                await self._hot_store.upsert_ticket(ticket)

                # 严格通过 InputMinimizer 裁剪，仅向财务黑盒投喂开票必需的 4 个最小字段
                next_card = self._human_tools.dispatch_card(
                    ticket_id=ticket.ticket_id,
                    contract_id="CONTRACT_FINANCE_TAX_DISK",
                    card_kind="FINANCE_INVOICE",
                    target_slot_id_override=fin_slot_id,
                    full_business_context={
                        "ticket_id": ticket.ticket_id,
                        "invoice_title": card.minimized_payload.get(
                            "invoice_title", "待核验企业抬头"
                        ),
                        "tax_id": card.minimized_payload.get(
                            "tax_id", ""
                        ),
                        "amount": approved_amt,
                        "secret_hv_reason": card.minimized_payload.get(
                            "high_voltage_reason"
                        ),
                        "customer_name": card.minimized_payload.get("customer_name"),
                    },
                )
                self._vault.append_event(
                    event_kind="LEADER_APPROVED_HV_TICKET",
                    subtree_root_id=ticket.subtree_root_id,
                    actor_slot_id=card.target_slot_id or leader_slot_id,
                    payload={
                        "ticket_id": ticket.ticket_id,
                        "finance_card_id": next_card.card_id,
                        "approved_amount": approved_amt,
                        "finance_target": fin_label,
                    },
                )
            else:
                ticket.status = "INTERCEPTED"
                ticket.updated_at = utc_now_iso()
                await self._hot_store.upsert_ticket(ticket)
        elif card.card_kind == "LEGAL_REVIEW":
            ticket.status = "COMPLETED" if updated_card.status == "APPROVED" else "INTERCEPTED"
            ticket.updated_at = utc_now_iso()
            await self._hot_store.upsert_ticket(ticket)
        else:
            # 财务黑盒开票输出校验合格 -> 经边缘审查哨所回传浓缩后结单封存快照
            relay_node_id = await self._resolve_aspect_relay_node_id(ticket.subtree_root_id)
            actor_slot = card.target_slot_id or fin_slot_id
            audit = await self._relay.relay_inspect(
                subtree_root_id=ticket.subtree_root_id,
                relay_node_id=relay_node_id,
                actor_slot_id=actor_slot,
                raw_payload_text=(
                    f"已完成加密税控盘开票，发票号 {submitted_output['invoice_number']}，"
                    f"实开金额 ¥{submitted_output['billed_amount']}，回执 {submitted_output['attachment_ref']}"
                ),
            )
            if audit.verdict != "PASS":
                # A relay rollback may have removed this ticket; do not recreate it afterward.
                current = await self._hot_store.get_ticket(ticket.ticket_id)
                ticket = current or ticket
                ticket.status = "ROLLED_BACK" if audit.verdict == "LOCAL_ROLLBACK" else "INTERCEPTED"
                ticket.sanitized_payload["finance_relay_summary"] = audit.sanitized_summary
                ticket.updated_at = utc_now_iso()
                if current is not None:
                    await self._hot_store.upsert_ticket(ticket)
                self._submission_results[card_id] = {"next_card_id": None, "ticket_snapshot": ticket.model_dump()}
                return {"accepted": True, "validation_errors": [], "card": updated_card,
                        "ticket": ticket, "next_card": None}
            ticket.status = "COMPLETED"
            ticket.sanitized_payload["finance_relay_summary"] = audit.sanitized_summary
            ticket.updated_at = utc_now_iso()
            await self._hot_store.upsert_ticket(ticket)

            snap = await self._hot_store.export_subtree_state(ticket.subtree_root_id)
            self._vault.seal_snapshot(
                ticket.subtree_root_id, actor_slot, snap, scope="LOCAL"
            )

        self._submission_results[card_id] = {
            "next_card_id": next_card.card_id if next_card else None,
            "ticket_snapshot": ticket.model_dump(),
        }
        return {
            "accepted": True,
            "validation_errors": [],
            "card": updated_card,
            "ticket": ticket,
            "next_card": next_card,
        }

    async def inject_concurrent_subtasks_and_check_span(
        self,
        parent_node_id: str = "node_aspect_quote",
        burst_count: int = 6,
    ) -> dict[str, Any]:
        """Probe topology capacity without fabricating any business ticket or workload."""
        if not isinstance(burst_count, int) or isinstance(burst_count, bool) or not 0 <= burst_count <= 1000:
            raise ValueError("burst_count 必须为 0 到 1000 的整数")
        max_span = self._settings.spider_max_span
        if max_span < 2:
            raise ValueError("分支拓扑的 spider_max_span 必须至少为 2")
        async with self._topology_lock:
            all_nodes = await self._hot_store.list_nodes()
            node_map = {n.node_id: n for n in all_nodes}
            if parent_node_id not in node_map:
                raise KeyError(f"SpiderNode {parent_node_id} not found")
            parent = node_map[parent_node_id]
            spawned_ids: list[str] = []
            for i in range(burst_count):
                sub = SpiderNode(
                    node_id=f"node_subworker_{uuid.uuid4().hex[:12]}",
                    label=f"拓扑容量探针 #{i + 1}", node_type="WORKER_SLOT",
                    parent_id=parent_node_id, subtree_root_id=parent.subtree_root_id,
                    slot_id=None, domain_tags=["拓扑容量测试"], active_load=0,
                    discovered_from="topology_capacity_probe",
                )
                await self._hot_store.upsert_node(sub)
                node_map[sub.node_id] = sub
                spawned_ids.append(sub.node_id)
            leader_slot_id, _, _ = await self._resolve_leader_target()
            relays: list[SpiderNode] = []
            # Count every child, including dormant nodes, so waking a node cannot exceed the bound.
            for parent_id in list(node_map):
                children = [n for n in node_map.values() if n.parent_id == parent_id]
                while len(children) > max_span:
                    group = children[:max_span]
                    relay = SpiderNode(
                        node_id=f"node_relay_pad_{uuid.uuid4().hex[:12]}",
                        label="自动垫层边缘审查哨所", node_type="RELAY_NODE",
                        parent_id=parent_id, subtree_root_id=node_map[parent_id].subtree_root_id,
                        slot_id=leader_slot_id, domain_tags=["边缘脱敏", "跨度约束"],
                        active_load=sum(n.active_load for n in group),
                    )
                    await self._hot_store.upsert_node(relay)
                    node_map[relay.node_id] = relay
                    for child in group:
                        child.parent_id = relay.node_id
                        await self._hot_store.upsert_node(child)
                    children = children[max_span:] + [relay]
                    relays.append(relay)
            if relays:
                snap = await self._hot_store.export_subtree_state(parent.subtree_root_id)
                self._vault.seal_snapshot(parent.subtree_root_id, leader_slot_id, snap, scope="LOCAL")
                await self._pulse.publish(
                    event_type="LAYER_PADDED", node_id=relays[0].node_id,
                    subtree_root_id=parent.subtree_root_id, severity="SUCCESS",
                    summary=f"拓扑容量探针完成；所有父节点跨度已约束为 <= {max_span}",
                    payload={"parent_node_id": parent_node_id,
                             "relay_node_ids": [n.node_id for n in relays],
                             "spawned_probe_ids": spawned_ids},
                )
            return {"spawned_worker_ids": spawned_ids, "layer_padded": bool(relays),
                    "padded_relay_node": relays[0] if relays else None}

    async def simulate_subnode_hallucination_and_audit(
        self, subtree_root_id: str = "subtree_quote"
    ) -> dict[str, Any]:
        """
        模拟某边缘工作节点被污染产生脏工单与金额幻觉回传，验证边缘审查哨所当场拦截并执行局部倒退。
        """
        all_nodes = await self._hot_store.list_nodes()
        nodes = [n for n in all_nodes if n.subtree_root_id == subtree_root_id]
        if not nodes:
            fallback_node = next(
                (n for n in all_nodes if n.node_type == "WORKER_SLOT"),
                next((n for n in all_nodes if n.node_type != "BOARD_ROOT"), all_nodes[0]),
            )
            subtree_root_id = fallback_node.subtree_root_id
            nodes = [n for n in all_nodes if n.subtree_root_id == subtree_root_id]

        relays = [n for n in nodes if n.node_type == "RELAY_NODE"]
        if relays:
            relay_node_id = relays[-1].node_id
        else:
            _, relay_node_id, _ = await self._resolve_leader_target()

        worker_in_sub = next(
            (n for n in nodes if n.node_type == "WORKER_SLOT" and n.slot_id),
            next((n for n in all_nodes if n.node_type == "WORKER_SLOT" and n.slot_id), None),
        )
        fallback_frontline_uid, fallback_frontline_sid = resolve_frontline_user_and_slot(self._containers)
        worker_slot_id = (
            worker_in_sub.slot_id
            if worker_in_sub and worker_in_sub.slot_id
            else (fallback_frontline_sid or "SLOT_BOSS")
        )
        boss_uid = next((p.user_id for p in self._containers.list_profiles() if p.role_view == "boss"), "")
        initiator_uid = fallback_frontline_uid or boss_uid
        if worker_slot_id in self._containers._slots:
            occ = self._containers.get_slot(worker_slot_id).occupant_id
            if occ in self._containers._profiles:
                initiator_uid = occ

        # 先往该子树写入一条被幻觉污染的脏工单
        corrupted_ticket = WorkTicket(
            ticket_id=f"TKT_BAD_{uuid.uuid4().hex[:6].upper()}",
            subtree_root_id=subtree_root_id,
            node_id=relay_node_id,
            initiator_id=initiator_uid,
            slot_id=worker_slot_id,
            facade_bot="COPILOT",
            status="OPEN",
            summary="异常幻觉脏工单：单价1280元×10把=总价50元",
        )
        await self._hot_store.upsert_ticket(corrupted_ticket)

        audit_res = await self._relay.relay_inspect(
            subtree_root_id=subtree_root_id,
            relay_node_id=relay_node_id,
            actor_slot_id=worker_slot_id,
            raw_payload_text="HALLUCINATION_FAULT: 报价核算单价1280元×10件=总价50元，同时附带内部成本底价500",
            metadata={"simulate_hallucination": True},
        )
        return {
            "corrupted_ticket_id": corrupted_ticket.ticket_id,
            "relay_node_id": relay_node_id,
            "audit_result": audit_res,
        }

    async def dehydrate_idle_nodes(
        self, idle_seconds: Optional[int] = None, now: Optional[datetime] = None
    ) -> list[str]:
        threshold = (
            idle_seconds
            if idle_seconds is not None
            else self._settings.node_dehydrate_idle_seconds
        )
        ref_now = now or datetime.now(timezone.utc)
        dehydrated_ids: list[str] = []

        for node in await self._hot_store.list_nodes():
            if node.node_type in ("BOARD_ROOT", "ASPECT_NODE"):
                continue
            if node.status != "ACTIVE":
                continue
            elapsed = (ref_now - _parse_iso_dt(node.last_active_at)).total_seconds()
            if elapsed >= threshold:
                node.status = "DEHYDRATED"
                node.active_load = 0
                await self._hot_store.upsert_node(node)
                dehydrated_ids.append(node.node_id)
                await self._pulse.publish(
                    event_type="NODE_DEHYDRATED",
                    node_id=node.node_id,
                    subtree_root_id=node.subtree_root_id,
                    severity="INFO",
                    summary=f"💤 节点脱水休眠：[{node.label}] 闲置超 {threshold}s，已释放内存进入零算力休眠态",
                    payload={"node_id": node.node_id},
                )
        return dehydrated_ids


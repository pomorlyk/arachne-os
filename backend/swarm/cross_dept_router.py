from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
from typing import Any

from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from core.human_tool import WorkflowConflictError
from core.particles import ParticleEngine
from core.schemas import WorkTicket
from core.topology_resolver import (
    resolve_frontline_user_and_slot,
    resolve_leader_user_and_slot,
    resolve_slot_by_role_keywords,
)
from database import HotStateStore
from swarm.pulse_bus import PulseBus


class CrossDepartmentRouter:
    """
    跨部门协同派单与临时借球调度器。
    全动态解析当前企业的接单、仓储/排产、采购/工程与履约/交付工位，无任何硬编码示波 ID。
    """

    def __init__(
        self,
        vault: BlackBoxVault,
        hot_store: HotStateStore,
        particles: ParticleEngine,
        containers: ContainerRegistry,
        pulse_bus: PulseBus,
    ) -> None:
        self.vault = vault
        self.hot_store = hot_store
        self.particles = particles
        self.containers = containers
        self.pulse_bus = pulse_bus
        self._execution_lock = asyncio.Lock()

    def _pick_borrowable_pair(
        self, borrower_slot_id: str, preferred_lender_id: str
    ) -> tuple[str, str]:
        all_slots = self.containers.list_slots()
        all_balls = {b.ball_id: b for b in self.particles.list_all_balls()}
        # 优先选择 preferred_lender 实际拥有的 AUTHORITY / SKILL 球
        candidate_lenders = [s for s in all_slots if s.slot_id == preferred_lender_id] + [
            s for s in all_slots if s.slot_id != borrower_slot_id
        ] + all_slots
        for lender in candidate_lenders:
            if not lender.ball_ids:
                continue
            auth_owned = [
                bid
                for bid in lender.ball_ids
                if bid in all_balls and all_balls[bid].ball_type == "AUTHORITY"
            ]
            if auth_owned:
                return (lender.slot_id, auth_owned[0])
            return (lender.slot_id, lender.ball_ids[0])
        return (preferred_lender_id, "BALL_AUTH_GATE")

    async def execute_cross_dept_chain(
        self,
        order_ref: str,
        product_model: str,
        quantity: int,
        unit_price: float,
        current_stock: int,
        daily_sales: int = 25,
        lead_days: int = 5,
        *,
        simulate: bool = False,
    ) -> dict[str, Any]:
        async with self._execution_lock:
            return await self._execute_chain_locked(order_ref, product_model, quantity, unit_price,
                                                    current_stock, daily_sales, lead_days, simulate)

    async def _execute_chain_locked(
        self, order_ref: str, product_model: str, quantity: int, unit_price: float,
        current_stock: int, daily_sales: int, lead_days: int, simulate: bool,
    ) -> dict[str, Any]:
        if not isinstance(order_ref, str) or not order_ref.strip() or not isinstance(product_model, str) or not product_model.strip():
            raise ValueError('订单引用与产品型号不能为空')
        for value, minimum in ((quantity, 1), (current_stock, 0), (daily_sales, 1), (lead_days, 1)):
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                raise ValueError('数量、库存与补货参数必须为有效整数')
        if isinstance(unit_price, bool) or not isinstance(unit_price, (int, float)) or not math.isfinite(unit_price) or unit_price <= 0:
            raise ValueError('单价必须为正的有限数字')
        if not isinstance(simulate, bool):
            raise ValueError('simulate 必须为布尔值')
        business_input = dict(order_ref=order_ref, product_model=product_model, quantity=quantity,
                              unit_price=float(unit_price), current_stock=current_stock,
                              daily_sales=daily_sales, lead_days=lead_days, simulate=simulate)
        fingerprint = hashlib.sha256(json.dumps(business_input, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        prior = [t for t in await self.hot_store.list_tickets()
                 if t.sanitized_payload.get('workflow_kind') == 'CROSS_DEPT'
                 and t.sanitized_payload.get('order_ref') == order_ref]
        if any(t.sanitized_payload.get('request_fingerprint') != fingerprint for t in prior):
            raise WorkflowConflictError('订单引用已绑定不同的业务输入，请使用独立更正流程')
        for ticket in prior:
            result = ticket.sanitized_payload.get('chain_result')
            if result and all(any(t.ticket_id == tid for t in prior) for tid in (
                    result['wms_ticket_id'], result['logistics_ticket_id'],
                    *([result['procure_ticket_id']] if result.get('procure_ticket_id') else []))):
                return copy.deepcopy(result)
        digest = hashlib.sha256(order_ref.encode()).hexdigest()[:20].upper()
        evidence_source = 'ISOLATED_SIMULATION_MODEL' if simulate else 'REQUEST_PROVIDED_UNVERIFIED'
        workflow_status = 'SIMULATED_COMPLETION' if simulate else 'PENDING_EXTERNAL_EXECUTION'
        ticket_status = 'COMPLETED' if simulate else 'OPEN'
        common_payload = {'workflow_kind': 'CROSS_DEPT', 'order_ref': order_ref,
                          'business_input': business_input, 'request_fingerprint': fingerprint,
                          'simulation': simulate, 'evidence_source': evidence_source, 'execution_receipt': None}
        total_amount = round(quantity * unit_price, 2)
        if not math.isfinite(total_amount):
            raise ValueError('申请总金额超出有效数字范围')
        safety_stock = int(daily_sales * lead_days * 1.5)
        remaining_stock = current_stock - quantity
        replenish_triggered = remaining_stock < safety_stock

        _, fl_slot_id = resolve_frontline_user_and_slot(self.containers)
        _, ld_slot_id = resolve_leader_user_and_slot(self.containers)
        wms_slot_id = resolve_slot_by_role_keywords(
            self.containers,
            ["仓", "排产", "智造", "调度", "制造", "wms"],
            ("employee", "leader"),
        )
        procure_slot_id = resolve_slot_by_role_keywords(
            self.containers,
            ["采购", "工程", "供应", "产研", "procure"],
            ("employee", "leader"),
            exclude_slot_ids={wms_slot_id} if wms_slot_id else None,
        )
        logistics_slot_id = resolve_slot_by_role_keywords(
            self.containers,
            ["物流", "履约", "交付", "储运", "logistics"],
            ("employee", "leader"),
            exclude_slot_ids={wms_slot_id, procure_slot_id},
        )
        borrower_slot_id = resolve_slot_by_role_keywords(
            self.containers,
            ["二号", "跟单", "客服", "接单", "审单", "sales", "followup"],
            ("employee",),
            exclude_slot_ids={wms_slot_id} if wms_slot_id != fl_slot_id else None,
        ) or fl_slot_id

        wms_slot = self.containers.get_slot(wms_slot_id)
        proc_slot = self.containers.get_slot(procure_slot_id)
        log_slot = self.containers.get_slot(logistics_slot_id)

        all_nodes = await self.hot_store.list_nodes()
        self.containers.sync_slot_node_map_from_nodes(all_nodes)
        node_by_id = {n.node_id: n for n in all_nodes}

        def _subtree_for(node_id: str, fallback: str = "root") -> str:
            n = node_by_id.get(node_id)
            return n.subtree_root_id if n else fallback

        wms_node_id = self.containers.resolve_node_id_for_slot(wms_slot_id)
        proc_node_id = self.containers.resolve_node_id_for_slot(procure_slot_id)
        log_node_id = self.containers.resolve_node_id_for_slot(logistics_slot_id)
        supply_aspect = next(
            (n for n in all_nodes if n.node_type == "ASPECT_NODE" and any(k in n.label for k in ("供应", "物流", "排产", "制造", "履约"))),
            next((n for n in all_nodes if n.node_type == "ASPECT_NODE"), None),
        )

        # 1. 动态发起跨岗临时借球（仅向实际持有该球的出借方借用）
        lender_sid, borrow_ball_id = self._pick_borrowable_pair(
            borrower_slot_id=borrower_slot_id,
            preferred_lender_id=wms_slot_id if wms_slot.ball_ids else ld_slot_id,
        )
        lender_obj = self.containers.get_slot(lender_sid)
        lease = None
        if borrow_ball_id in lender_obj.ball_ids:
            lease = self.containers.borrow_ball(
                borrower_slot_id=borrower_slot_id,
                lender_slot_id=lender_sid,
                ball_id=borrow_ball_id,
                ttl_seconds=1800,
            )

        # 2. 创建仓储/排产波次锁库工单
        wms_ticket = WorkTicket(
            ticket_id=f"TKT-WMS-{digest}",
            subtree_root_id=_subtree_for(wms_node_id),
            node_id=wms_node_id,
            initiator_id=wms_slot.occupant_id,
            slot_id=wms_slot.slot_id,
            facade_bot="COPILOT",
            status=ticket_status,
            summary=f"[{order_ref}] {'模拟完成' if simulate else '待执行'}：请求{wms_slot.slot_name}锁定 {quantity} 单位 {product_model}（预计余量 {remaining_stock}，策略安全水位 {safety_stock}）",
            sanitized_payload={
                **common_payload,
                "product_model": product_model,
                "requested_lock_qty": quantity,
                "reported_stock": current_stock,
                "projected_remaining_stock": remaining_stock,
                "safety_stock": safety_stock,
            },
        )
        await self.hot_store.upsert_ticket(wms_ticket)

        # 3. 若触发安全水位预警，自动向采购/供应工位派发紧急补货单
        procure_ticket_id = None
        if replenish_triggered:
            replenish_qty = max(200, safety_stock * 2 - remaining_stock)
            procure_ticket = WorkTicket(
                ticket_id=f"TKT-PROC-{digest}",
                subtree_root_id=_subtree_for(proc_node_id),
                node_id=proc_node_id,
                initiator_id=proc_slot.occupant_id,
                slot_id=proc_slot.slot_id,
                facade_bot="GOVERNANCE",
                status=ticket_status,
                summary=f"[{order_ref}] {'模拟完成' if simulate else '待执行'}：预计库存({remaining_stock})低于策略水位({safety_stock})，请求{proc_slot.slot_name}复核补货建议 {replenish_qty} 单位",
                sanitized_payload={
                    **common_payload,
                    "requested_replenish_qty": replenish_qty,
                    "requested_action": "REVIEW_REPLENISHMENT_PROPOSAL",
                },
            )
            await self.hot_store.upsert_ticket(procure_ticket)
            procure_ticket_id = procure_ticket.ticket_id

        # 4. 履约交付工单
        logistics_ticket = WorkTicket(
            ticket_id=f"TKT-LOG-{digest}",
            subtree_root_id=_subtree_for(log_node_id),
            node_id=log_node_id,
            initiator_id=log_slot.occupant_id,
            slot_id=log_slot.slot_id,
            facade_bot="COPILOT",
            status=ticket_status,
            summary=f"[{order_ref}] {'模拟完成' if simulate else '待执行'}：请求{log_slot.slot_name}复核配送安排（申请总额 ¥{total_amount:,.2f}）",
            sanitized_payload={
                **common_payload,
                "requested_total_amount": total_amount,
                "requested_action": "ARRANGE_DELIVERY_AFTER_RESERVATION_RECEIPT",
                "carrier": None,
            },
        )
        await self.hot_store.upsert_ticket(logistics_ticket)

        chain_result = {
            'order_ref': order_ref, 'status': workflow_status,
            'evidence_source': evidence_source, 'simulation': simulate, 'execution_receipt': None,
            'total_amount': total_amount, 'remaining_stock': remaining_stock if simulate else None,
            'projected_remaining_stock': remaining_stock,
            'safety_stock': safety_stock, 'replenish_triggered': replenish_triggered,
            'wms_ticket_id': wms_ticket.ticket_id, 'procure_ticket_id': procure_ticket_id,
            'logistics_ticket_id': logistics_ticket.ticket_id,
        }
        wms_ticket.sanitized_payload['chain_result'] = copy.deepcopy(chain_result)
        await self.hot_store.upsert_ticket(wms_ticket)
        borrowed_id = lease.ball_id if lease else borrow_ball_id
        self.vault.append_event(
            event_kind="CROSS_DEPT_WORKFLOW_SIMULATED" if simulate else "CROSS_DEPT_WORKFLOW_REQUESTED",
            subtree_root_id=_subtree_for(wms_node_id),
            actor_slot_id=wms_slot.slot_id,
            payload={
                "order_ref": order_ref,
                "wms_ticket_id": wms_ticket.ticket_id,
                "procure_ticket_id": procure_ticket_id,
                "logistics_ticket_id": logistics_ticket.ticket_id,
                "borrowed_ball": borrowed_id,
            },
        )

        await self.pulse_bus.publish(
            event_type="ASPECT_CLUSTERED",
            node_id=supply_aspect.node_id if supply_aspect else "node_board_root",
            subtree_root_id=supply_aspect.subtree_root_id if supply_aspect else "root",
            severity="SUCCESS" if simulate else "INFO",
            summary=f"{'隔离模拟完成' if simulate else '跨部门执行申请待外部回执'}：{wms_slot.slot_name}、{proc_slot.slot_name}、{log_slot.slot_name} ({order_ref})",
            payload={
                "order_ref": order_ref,
                "replenish_triggered": replenish_triggered,
                "status": workflow_status,
                "evidence_source": evidence_source,
            },
        )

        return chain_result

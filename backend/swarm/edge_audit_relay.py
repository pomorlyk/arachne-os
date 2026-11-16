from __future__ import annotations

from typing import Any

from core.blackbox_vault import BlackBoxVault
from core.llm_gateway import LLMGateway
from core.particles import ParticleEngine
from core.schemas import RelayAuditResult
from database import HotStateStore
from swarm.pulse_bus import PulseBus


class EdgeAuditRelay:
    """
    偏远边缘审查哨所 (EdgeAuditRelay)：
    所有中继节点 (RELAY_NODE) 兼任审查哨所，信息从底层回传时强制执行：
    1. 回传途中改变：剥离原始隐私、浓缩结构化业务结论；
    2. 逐级纠错：核验红线与前后金额逻辑矛盾；
    3. 局部倒退 (Local Rollback)：一旦发现子节点异常幻觉，立即追加 ROLLBACK_SEAL 封条，
       并仅将目标异常子树恢复至最近一次合法快照，不波及全网兄弟分支！
    """

    def __init__(
        self,
        vault: BlackBoxVault,
        hot_store: HotStateStore,
        particles: ParticleEngine,
        llm_gateway: LLMGateway,
        pulse_bus: PulseBus,
    ) -> None:
        self._vault = vault
        self._hot_store = hot_store
        self._particles = particles
        self._llm = llm_gateway
        self._pulse = pulse_bus

    async def relay_inspect(
        self,
        subtree_root_id: str,
        relay_node_id: str,
        actor_slot_id: str,
        raw_payload_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> RelayAuditResult:
        meta = metadata or {}
        audit = await self._llm.audit_edge_relay(
            raw_node_output=raw_payload_text,
            metadata=meta,
            redline_balls=self._particles.list_redline_balls(),
        )

        if audit.verdict == "LOCAL_ROLLBACK":
            await self.execute_local_rollback(
                subtree_root_id=subtree_root_id,
                relay_node_id=relay_node_id,
                actor_slot_id=actor_slot_id,
                reason=audit.rollback_reason or "边缘审查哨所检出子节点异常",
            )
            return audit

        if audit.verdict == "ESCALATE_SUPERVISOR":
            await self._pulse.publish(
                event_type="RELAY_INTERCEPTED",
                node_id=relay_node_id,
                subtree_root_id=subtree_root_id,
                severity="WARNING",
                summary=f"边缘哨所 [{relay_node_id}] 挂起高风险回传，已转交基层主管人工复核",
                payload={"sanitized_summary": audit.sanitized_summary},
            )
            return audit

        self._vault.append_event(
            event_kind="RELAY_AUDIT_PASSED",
            subtree_root_id=subtree_root_id,
            actor_slot_id=actor_slot_id,
            payload={
                "relay_node_id": relay_node_id,
                "sanitized_summary": audit.sanitized_summary,
                "stripped_private_count": audit.stripped_private_count,
                "redacted_pii_count": audit.redacted_pii_count,
            },
        )
        return audit

    async def _validate_workspace(self, state: dict[str, Any]) -> None:
        persisted = await self._hot_store.load_workspace_state()
        current = dict((persisted or {}).get("meta_payload") or {}).get("cave_meta") or {}
        # Legacy snapshots without a namespace are accepted only in legacy workspaces.
        for key in ("workspace_id", "workspace_epoch"):
            if current.get(key) and state.get(key) != current[key]:
                raise ValueError("Snapshot belongs to another workspace")

    async def execute_local_rollback(
        self,
        subtree_root_id: str,
        relay_node_id: str,
        actor_slot_id: str,
        reason: str,
        target_snapshot_hash: str | None = None,
    ) -> str:
        snap_hash = target_snapshot_hash or self._vault.get_latest_snapshot_hash(
            subtree_root_id=subtree_root_id, scope="LOCAL"
        )
        if not snap_hash:
            raise ValueError(f"No valid snapshot found for subtree {subtree_root_id}")

        clean_state = self._vault.validate_snapshot(snap_hash, subtree_root_id=subtree_root_id, scope="LOCAL")
        self._hot_store.validate_subtree_state(subtree_root_id, clean_state)
        await self._validate_workspace(clean_state)
        self._vault.record_rollback_seal(
            subtree_root_id=subtree_root_id,
            actor_slot_id=actor_slot_id,
            target_snapshot_hash=snap_hash,
            reason=reason,
            scope="LOCAL",
        )
        await self._hot_store.restore_subtree_state(subtree_root_id, clean_state)
        self._vault.append_event("ROLLBACK_COMPLETED", subtree_root_id, actor_slot_id, {"snapshot_hash": snap_hash, "scope": "LOCAL"})

        await self._pulse.publish(
            event_type="RELAY_INTERCEPTED",
            node_id=relay_node_id,
            subtree_root_id=subtree_root_id,
            severity="CRITICAL",
            summary=f"🚨 哨所拦截 [{relay_node_id}]：{reason}",
            payload={"reason": reason, "subtree_root_id": subtree_root_id},
        )
        await self._pulse.publish(
            event_type="LOCAL_ROLLBACK",
            node_id=relay_node_id,
            subtree_root_id=subtree_root_id,
            severity="WARNING",
            summary=(
                f"⏪ 局部倒退完成：子树 [{subtree_root_id}] 已原子恢复至快照 {snap_hash[:10]}...（其余分支零受影响）"
            ),
            payload={
                "subtree_root_id": subtree_root_id,
                "snapshot_hash": snap_hash,
                "reason": reason,
            },
        )
        return snap_hash

    async def execute_global_rollback(
        self, actor_slot_id: str, reason: str, target_snapshot_hash: str | None = None
    ) -> str:
        snap_hash = target_snapshot_hash or self._vault.get_latest_snapshot_hash(
            subtree_root_id="root", scope="GLOBAL"
        )
        if not snap_hash:
            raise ValueError("No global snapshot found in BlackBoxVault")

        clean_global = self._vault.validate_snapshot(snap_hash, subtree_root_id="root", scope="GLOBAL")
        await self._validate_workspace(clean_global)
        self._vault.record_rollback_seal(
            subtree_root_id="root",
            actor_slot_id=actor_slot_id,
            target_snapshot_hash=snap_hash,
            reason=reason,
            scope="GLOBAL",
        )
        await self._hot_store.restore_global_state(clean_global)
        self._vault.append_event("ROLLBACK_COMPLETED", "root", actor_slot_id, {"snapshot_hash": snap_hash, "scope": "GLOBAL"})

        await self._pulse.publish(
            event_type="GLOBAL_ROLLBACK",
            node_id="node_board_root",
            subtree_root_id="root",
            severity="CRITICAL",
            summary=f"🛡️ 全局紧急回滚已执行：全网热状态已回退至基线快照 {snap_hash[:10]}...",
            payload={"snapshot_hash": snap_hash, "reason": reason},
        )
        return snap_hash


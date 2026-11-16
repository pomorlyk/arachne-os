from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from sqlalchemy import Integer, String, Text, delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.schemas import (
    BorrowedBallLease,
    CapabilityBall,
    DualEmployeeProfile,
    SpiderNode,
    UnitSlot,
    WorkTicket,
)


class Base(DeclarativeBase):
    pass


class ORMSpiderNode(Base):
    __tablename__ = "spider_nodes"

    node_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    subtree_root_id: Mapped[str] = mapped_column(String(128), index=True)
    parent_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    node_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64))
    active_load: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[str] = mapped_column(Text)


class ORMWorkTicket(Base):
    __tablename__ = "work_tickets"

    ticket_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    subtree_root_id: Mapped[str] = mapped_column(String(128), index=True)
    node_id: Mapped[str] = mapped_column(String(128), index=True)
    slot_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)


class ORMBorrowedLease(Base):
    __tablename__ = "borrowed_leases"

    lease_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    subtree_root_id: Mapped[str] = mapped_column(String(128), index=True)
    slot_id: Mapped[str] = mapped_column(String(128), index=True)
    payload_json: Mapped[str] = mapped_column(Text)


class ORMImmutableAuditCounter(Base):
    """
    独立于业务子树回滚之外的不可抹除违规审计计数表。
    确保执行 LOCAL_ROLLBACK 或 GLOBAL_ROLLBACK 时，员工的越界刺探记录绝不被洗白。
    """

    __tablename__ = "immutable_audit_counters"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    boundary_probes: Mapped[int] = mapped_column(Integer, default=0)


class ORMUnitSlot(Base):
    __tablename__ = "unit_slots"

    slot_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    department: Mapped[str] = mapped_column(String(128), index=True)
    occupant_id: Mapped[str] = mapped_column(String(128), index=True)
    occupant_type: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text)


class ORMEmployeeProfile(Base):
    __tablename__ = "employee_profiles"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    slot_id: Mapped[str] = mapped_column(String(128), index=True)
    role_view: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text)


class ORMCapabilityBall(Base):
    __tablename__ = "capability_balls"

    ball_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    ball_type: Mapped[str] = mapped_column(String(32), index=True)
    sensitivity_level: Mapped[int] = mapped_column(Integer, default=1)
    payload_json: Mapped[str] = mapped_column(Text)
    source_code_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ORMAccountDirectoryEntry(Base):
    __tablename__ = "account_directory_entries"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    department: Mapped[str] = mapped_column(String(128))
    supervisor_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_custodian_leader: Mapped[int] = mapped_column(Integer, default=0)
    password_value: Mapped[str] = mapped_column(String(256), default="123456")
    payload_json: Mapped[str] = mapped_column(Text)


class ORMCustodyRequest(Base):
    __tablename__ = "custody_requests"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    requester_id: Mapped[str] = mapped_column(String(128), index=True)
    custodian_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text)


class ORMWorkspaceStateMeta(Base):
    __tablename__ = "workspace_state_meta"

    meta_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    enterprise_name: Mapped[str] = mapped_column(String(256))
    mode: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)


class HotStateStore:
    def __init__(self, db_url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(db_url, future=True)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )
        self._write_lock = asyncio.Lock()

    async def init_db(self) -> None:
        async with self._engine.begin() as conn:
            if self._engine.dialect.name == "sqlite":
                await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
                await conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
                await conn.exec_driver_sql("PRAGMA busy_timeout=5000;")
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        try:
            await self._engine.dispose()
        finally:
            lease = getattr(self, "_runtime_writer_lease", None)
            if lease is not None:
                lease.close()
                self._runtime_writer_lease = None

    async def upsert_node(self, node: SpiderNode) -> None:
        async with self._write_lock:
            async with self._session_factory() as session:
                row = ORMSpiderNode(
                    node_id=node.node_id,
                    subtree_root_id=node.subtree_root_id,
                    parent_id=node.parent_id,
                    node_type=node.node_type,
                    status=node.status,
                    active_load=node.active_load,
                    payload_json=node.model_dump_json(),
                )
                await session.merge(row)
                await session.commit()

    async def list_nodes(self, subtree_root_id: Optional[str] = None) -> list[SpiderNode]:
        async with self._session_factory() as session:
            stmt = select(ORMSpiderNode)
            if subtree_root_id:
                stmt = stmt.where(ORMSpiderNode.subtree_root_id == subtree_root_id)
            rows = (await session.scalars(stmt)).all()
            return [SpiderNode.model_validate_json(r.payload_json) for r in rows]

    async def upsert_ticket(self, ticket: WorkTicket) -> None:
        async with self._write_lock:
            async with self._session_factory() as session:
                row = ORMWorkTicket(
                    ticket_id=ticket.ticket_id,
                    subtree_root_id=ticket.subtree_root_id,
                    node_id=ticket.node_id,
                    slot_id=ticket.slot_id,
                    status=ticket.status,
                    payload_json=ticket.model_dump_json(),
                )
                await session.merge(row)
                await session.commit()

    async def get_ticket(self, ticket_id: str) -> Optional[WorkTicket]:
        async with self._session_factory() as session:
            row = await session.get(ORMWorkTicket, ticket_id)
            if not row:
                return None
            return WorkTicket.model_validate_json(row.payload_json)

    async def list_tickets(self, subtree_root_id: Optional[str] = None) -> list[WorkTicket]:
        async with self._session_factory() as session:
            stmt = select(ORMWorkTicket)
            if subtree_root_id:
                stmt = stmt.where(ORMWorkTicket.subtree_root_id == subtree_root_id)
            rows = (await session.scalars(stmt)).all()
            return [WorkTicket.model_validate_json(r.payload_json) for r in rows]

    async def upsert_lease(
        self, slot_id: str, subtree_root_id: str, lease: BorrowedBallLease
    ) -> None:
        lease_key = f"{slot_id}::{lease.ball_id}"
        async with self._write_lock:
            async with self._session_factory() as session:
                row = ORMBorrowedLease(
                    lease_key=lease_key,
                    subtree_root_id=subtree_root_id,
                    slot_id=slot_id,
                    payload_json=lease.model_dump_json(),
                )
                await session.merge(row)
                await session.commit()

    async def remove_lease(self, slot_id: str, ball_id: str) -> None:
        lease_key = f"{slot_id}::{ball_id}"
        async with self._write_lock:
            async with self._session_factory() as session:
                await session.execute(
                    delete(ORMBorrowedLease).where(
                        ORMBorrowedLease.lease_key == lease_key
                    )
                )
                await session.commit()

    async def increment_boundary_probe(self, user_id: str) -> int:
        async with self._write_lock:
            async with self._session_factory() as session:
                row = await session.get(ORMImmutableAuditCounter, user_id)
                if row is None:
                    row = ORMImmutableAuditCounter(user_id=user_id, boundary_probes=1)
                    session.add(row)
                    new_val = 1
                else:
                    row.boundary_probes += 1
                    new_val = row.boundary_probes
                await session.commit()
                return new_val

    async def get_boundary_probes(self, user_id: str) -> int:
        async with self._session_factory() as session:
            row = await session.get(ORMImmutableAuditCounter, user_id)
            return row.boundary_probes if row else 0

    async def export_subtree_state(self, subtree_root_id: str) -> dict[str, Any]:
        nodes = await self.list_nodes(subtree_root_id=subtree_root_id)
        tickets = await self.list_tickets(subtree_root_id=subtree_root_id)
        async with self._session_factory() as session:
            lease_rows = (
                await session.scalars(
                    select(ORMBorrowedLease).where(
                        ORMBorrowedLease.subtree_root_id == subtree_root_id
                    )
                )
            ).all()
        leases = [
            {
                "lease_key": r.lease_key,
                "slot_id": r.slot_id,
                "subtree_root_id": r.subtree_root_id,
                "lease": json.loads(r.payload_json),
            }
            for r in lease_rows
        ]
        persisted = await self.load_workspace_state()
        cave_meta = dict((persisted or {}).get("meta_payload") or {}).get("cave_meta") or {}
        return {
            **{k: cave_meta[k] for k in ("workspace_id", "workspace_epoch") if k in cave_meta},
            "subtree_root_id": subtree_root_id,
            "nodes": [n.model_dump() for n in nodes],
            "tickets": [t.model_dump() for t in tickets],
            "leases": leases,
        }

    @staticmethod
    def validate_subtree_state(subtree_root_id: str, state_dict: dict[str, Any]) -> None:
        if state_dict.get("subtree_root_id") != subtree_root_id:
            raise ValueError("Snapshot subtree does not match restore target")
        nodes = [SpiderNode(**raw) for raw in state_dict.get("nodes", [])]
        tickets = [WorkTicket(**raw) for raw in state_dict.get("tickets", [])]
        if any(item.subtree_root_id != subtree_root_id for item in [*nodes, *tickets]):
            raise ValueError("Snapshot contains records from a different subtree")
        for item in state_dict.get("leases", []):
            BorrowedBallLease(**item["lease"])
            if item.get("subtree_root_id") != subtree_root_id or item.get("lease_key") != f'{item["slot_id"]}::{item["lease"]["ball_id"]}':
                raise ValueError("Snapshot contains foreign or malformed lease")

    async def restore_subtree_state(
        self, subtree_root_id: str, state_dict: dict[str, Any]
    ) -> None:
        """
        外科手术式子树原子恢复：
        仅清理并回填指定 subtree_root_id 下的节点、工单与借球租约，
        兄弟分支工单与 ORMImmutableAuditCounter 违规计数保持 100% 完好。
        """
        self.validate_subtree_state(subtree_root_id, state_dict)
        async with self._write_lock:
            async with self._session_factory() as session:
                # Reject primary-key collisions with siblings before any deletion.
                for model, key, raws in ((ORMSpiderNode, "node_id", state_dict.get("nodes", [])), (ORMWorkTicket, "ticket_id", state_dict.get("tickets", [])), (ORMBorrowedLease, "lease_key", state_dict.get("leases", []))):
                    for raw in raws:
                        existing = await session.get(model, raw[key])
                        if existing is not None and existing.subtree_root_id != subtree_root_id:
                            raise ValueError("Snapshot ID collides with another subtree")
                await session.execute(
                    delete(ORMWorkTicket).where(
                        ORMWorkTicket.subtree_root_id == subtree_root_id
                    )
                )
                await session.execute(
                    delete(ORMSpiderNode).where(
                        ORMSpiderNode.subtree_root_id == subtree_root_id
                    )
                )
                await session.execute(
                    delete(ORMBorrowedLease).where(
                        ORMBorrowedLease.subtree_root_id == subtree_root_id
                    )
                )

                for raw_node in state_dict.get("nodes", []):
                    node = SpiderNode(**raw_node)
                    session.add(
                        ORMSpiderNode(
                            node_id=node.node_id,
                            subtree_root_id=node.subtree_root_id,
                            parent_id=node.parent_id,
                            node_type=node.node_type,
                            status=node.status,
                            active_load=node.active_load,
                            payload_json=node.model_dump_json(),
                        )
                    )

                for raw_ticket in state_dict.get("tickets", []):
                    ticket = WorkTicket(**raw_ticket)
                    session.add(
                        ORMWorkTicket(
                            ticket_id=ticket.ticket_id,
                            subtree_root_id=ticket.subtree_root_id,
                            node_id=ticket.node_id,
                            slot_id=ticket.slot_id,
                            status=ticket.status,
                            payload_json=ticket.model_dump_json(),
                        )
                    )

                for item in state_dict.get("leases", []):
                    lease_obj = BorrowedBallLease(**item["lease"])
                    session.add(
                        ORMBorrowedLease(
                            lease_key=item["lease_key"],
                            subtree_root_id=subtree_root_id,
                            slot_id=item["slot_id"],
                            payload_json=lease_obj.model_dump_json(),
                        )
                    )

                await session.commit()

    async def export_global_state(self) -> dict[str, Any]:
        nodes = await self.list_nodes()
        tickets = await self.list_tickets()
        async with self._session_factory() as session:
            lease_rows = (await session.scalars(select(ORMBorrowedLease))).all()
        leases = [
            {
                "lease_key": r.lease_key,
                "slot_id": r.slot_id,
                "subtree_root_id": r.subtree_root_id,
                "lease": json.loads(r.payload_json),
            }
            for r in lease_rows
        ]
        persisted = await self.load_workspace_state()
        cave_meta = dict((persisted or {}).get("meta_payload") or {}).get("cave_meta") or {}
        return {
            **{k: cave_meta[k] for k in ("workspace_id", "workspace_epoch") if k in cave_meta},
            "nodes": [n.model_dump() for n in nodes],
            "tickets": [t.model_dump() for t in tickets],
            "leases": leases,
        }

    async def restore_global_state(self, state_dict: dict[str, Any]) -> None:
        async with self._write_lock:
            async with self._session_factory() as session:
                await session.execute(delete(ORMWorkTicket))
                await session.execute(delete(ORMSpiderNode))
                await session.execute(delete(ORMBorrowedLease))

                for raw_node in state_dict.get("nodes", []):
                    node = SpiderNode(**raw_node)
                    session.add(
                        ORMSpiderNode(
                            node_id=node.node_id,
                            subtree_root_id=node.subtree_root_id,
                            parent_id=node.parent_id,
                            node_type=node.node_type,
                            status=node.status,
                            active_load=node.active_load,
                            payload_json=node.model_dump_json(),
                        )
                    )

                for raw_ticket in state_dict.get("tickets", []):
                    ticket = WorkTicket(**raw_ticket)
                    session.add(
                        ORMWorkTicket(
                            ticket_id=ticket.ticket_id,
                            subtree_root_id=ticket.subtree_root_id,
                            node_id=ticket.node_id,
                            slot_id=ticket.slot_id,
                            status=ticket.status,
                            payload_json=ticket.model_dump_json(),
                        )
                    )

                for item in state_dict.get("leases", []):
                    lease_obj = BorrowedBallLease(**item["lease"])
                    session.add(
                        ORMBorrowedLease(
                            lease_key=item["lease_key"],
                            subtree_root_id=item["subtree_root_id"],
                            slot_id=item["slot_id"],
                            payload_json=lease_obj.model_dump_json(),
                        )
                    )

                await session.commit()

    async def persist_workspace_state(
        self,
        *,
        enterprise_name: str,
        mode: str,
        unit_slots: list[UnitSlot],
        profiles: list[DualEmployeeProfile],
        capability_balls_with_source: list[tuple[CapabilityBall, Optional[str]]],
        account_directory: dict[str, dict[str, Any]],
        passwords: dict[str, str],
        custody_requests: list[dict[str, Any]],
        meta_payload: dict[str, Any],
    ) -> None:
        """
        将内存注册表（槽位容器、员工双面档案、权能球及动态沙箱源码、账号通讯录、审批单、探网元状态）
        完整写穿持久化至 SQLite，避免后端进程重启后丢失已探网企业与岗位资产。
        """
        async with self._write_lock:
            async with self._session_factory() as session:
                await session.execute(delete(ORMUnitSlot))
                await session.execute(delete(ORMEmployeeProfile))
                await session.execute(delete(ORMCapabilityBall))
                await session.execute(delete(ORMAccountDirectoryEntry))
                await session.execute(delete(ORMCustodyRequest))
                await session.execute(delete(ORMWorkspaceStateMeta))

                for slot in unit_slots:
                    session.add(
                        ORMUnitSlot(
                            slot_id=slot.slot_id,
                            department=slot.department,
                            occupant_id=slot.occupant_id,
                            occupant_type=slot.occupant_type,
                            payload_json=slot.model_dump_json(),
                        )
                    )

                for prof in profiles:
                    session.add(
                        ORMEmployeeProfile(
                            user_id=prof.user_id,
                            slot_id=prof.slot_id,
                            role_view=prof.role_view,
                            payload_json=prof.model_dump_json(),
                        )
                    )

                for item in capability_balls_with_source:
                    if isinstance(item, dict):
                        ball = item["ball"]
                        source_code = item.get("executable_code_source", "")
                    else:
                        ball, source_code = item
                    session.add(
                        ORMCapabilityBall(
                            ball_id=ball.ball_id,
                            ball_type=ball.ball_type,
                            sensitivity_level=ball.sensitivity_level,
                            payload_json=ball.model_dump_json(),
                            source_code_text=source_code,
                        )
                    )

                for uid, entry in account_directory.items():
                    session.add(
                        ORMAccountDirectoryEntry(
                            user_id=uid,
                            department=str(entry.get("department", "通用业务部")),
                            supervisor_id=entry.get("supervisor_id"),
                            is_custodian_leader=1 if entry.get("is_custodian_leader", False) else 0,
                            password_value=str(passwords.get(uid, "")),
                            payload_json=json.dumps(entry, ensure_ascii=False),
                        )
                    )

                for req in custody_requests:
                    session.add(
                        ORMCustodyRequest(
                            request_id=str(req["request_id"]),
                            requester_id=str(req["requester_id"]),
                            custodian_id=str(req["custodian_id"]),
                            status=str(req.get("status", "PENDING")),
                            payload_json=json.dumps(req, ensure_ascii=False),
                        )
                    )

                session.add(
                    ORMWorkspaceStateMeta(
                        meta_key="active",
                        enterprise_name=enterprise_name,
                        mode=mode,
                        payload_json=json.dumps(meta_payload, ensure_ascii=False),
                    )
                )
                await session.commit()

    async def upsert_unit_slot(self, slot: UnitSlot) -> None:
        async with self._write_lock:
            async with self._session_factory() as session:
                await session.merge(
                    ORMUnitSlot(
                        slot_id=slot.slot_id,
                        department=slot.department,
                        occupant_id=slot.occupant_id,
                        occupant_type=slot.occupant_type,
                        payload_json=slot.model_dump_json(),
                    )
                )
                await session.commit()

    async def upsert_employee_profile(self, prof: DualEmployeeProfile) -> None:
        async with self._write_lock:
            async with self._session_factory() as session:
                await session.merge(
                    ORMEmployeeProfile(
                        user_id=prof.user_id,
                        slot_id=prof.slot_id,
                        role_view=prof.role_view,
                        payload_json=prof.model_dump_json(),
                    )
                )
                await session.commit()

    async def upsert_capability_ball(
        self, ball: CapabilityBall, source_code: Optional[str] = None
    ) -> None:
        async with self._write_lock:
            async with self._session_factory() as session:
                await session.merge(
                    ORMCapabilityBall(
                        ball_id=ball.ball_id,
                        ball_type=ball.ball_type,
                        sensitivity_level=ball.sensitivity_level,
                        payload_json=ball.model_dump_json(),
                        source_code_text=source_code,
                    )
                )
                await session.commit()

    async def upsert_account_entry(
        self, user_id: str, entry: dict[str, Any], password_value: str
    ) -> None:
        async with self._write_lock:
            async with self._session_factory() as session:
                await session.merge(
                    ORMAccountDirectoryEntry(
                        user_id=user_id,
                        department=str(entry.get("department", "通用业务部")),
                        supervisor_id=entry.get("supervisor_id"),
                        is_custodian_leader=1 if entry.get("is_custodian_leader", False) else 0,
                        password_value=password_value,
                        payload_json=json.dumps(entry, ensure_ascii=False),
                    )
                )
                await session.commit()

    async def upsert_custody_request(self, req: dict[str, Any]) -> None:
        async with self._write_lock:
            async with self._session_factory() as session:
                await session.merge(
                    ORMCustodyRequest(
                        request_id=str(req["request_id"]),
                        requester_id=str(req["requester_id"]),
                        custodian_id=str(req["custodian_id"]),
                        status=str(req.get("status", "PENDING")),
                        payload_json=json.dumps(req, ensure_ascii=False),
                    )
                )
                await session.commit()

    async def upsert_workspace_meta(
        self, enterprise_name: str, mode: str, meta_payload: dict[str, Any]
    ) -> None:
        async with self._write_lock:
            async with self._session_factory() as session:
                await session.merge(
                    ORMWorkspaceStateMeta(
                        meta_key="active",
                        enterprise_name=enterprise_name,
                        mode=mode,
                        payload_json=json.dumps(meta_payload, ensure_ascii=False),
                    )
                )
                await session.commit()

    async def load_workspace_state(self) -> Optional[dict[str, Any]]:
        """
        从 SQLite 恢复持久化的工作区全量状态；若尚未初始化则返回 None。
        """
        async with self._session_factory() as session:
            meta_row = await session.get(ORMWorkspaceStateMeta, "active")
            slot_rows = (await session.scalars(select(ORMUnitSlot))).all()
            prof_rows = (await session.scalars(select(ORMEmployeeProfile))).all()
            ball_rows = (await session.scalars(select(ORMCapabilityBall))).all()
            acc_rows = (await session.scalars(select(ORMAccountDirectoryEntry))).all()
            req_rows = (await session.scalars(select(ORMCustodyRequest))).all()

        if meta_row is None and not slot_rows and not ball_rows:
            return None

        account_directory: dict[str, dict[str, Any]] = {}
        passwords: dict[str, str] = {}
        for row in acc_rows:
            account_directory[row.user_id] = json.loads(row.payload_json)
            passwords[row.user_id] = row.password_value

        return {
            "enterprise_name": meta_row.enterprise_name if meta_row else "已恢复企业",
            "mode": meta_row.mode if meta_row else "DEMO_SEED",
            "meta_payload": json.loads(meta_row.payload_json) if meta_row and meta_row.payload_json else {},
            "unit_slots": [UnitSlot.model_validate_json(r.payload_json) for r in slot_rows],
            "profiles": [DualEmployeeProfile.model_validate_json(r.payload_json) for r in prof_rows],
            "capability_balls": [
                {
                    "ball": CapabilityBall.model_validate_json(r.payload_json),
                    "source_code": r.source_code_text,
                }
                for r in ball_rows
            ],
            "account_directory": account_directory,
            "passwords": passwords,
            "custody_requests": [json.loads(r.payload_json) for r in req_rows],
        }

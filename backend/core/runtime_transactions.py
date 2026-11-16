from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import fcntl
import json
import os
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable
import uuid

from sqlalchemy.engine import make_url


active_mutation: ContextVar[Any] = ContextVar("arachne_active_mutation", default=None)


def write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


class RuntimeWriterLease:
    """Keep a single aggregate writer for each SQLite database."""

    def __init__(self, database_url: str) -> None:
        self._handle = None
        database = make_url(database_url).database
        if not database or database == ":memory:":
            return
        lock_path = Path(database).resolve().with_suffix(".runtime.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise RuntimeError(
                "数据库已有运行实例，请连接现有服务，不能启动第二个 writer"
            ) from exc
        self._handle = handle

    def close(self) -> None:
        if self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


@dataclass
class MutationResult:
    rollback: bool = False
    completed: asyncio.Event = field(default_factory=asyncio.Event)


class RuntimeTransactions:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.lock = asyncio.Lock()
        self.journal = (
            Path(runtime.settings.sandbox_workspace_dir) / "runtime_transaction.json"
        )

    async def recover(self) -> None:
        if not self.journal.exists():
            return
        pending = json.loads(self.journal.read_text(encoding="utf-8"))
        if pending.get("schema_version") != 1 or not isinstance(
            pending.get("before"), dict
        ):
            raise RuntimeError("运行事务恢复记录损坏，无法安全恢复工作区")
        await self.runtime.restore_runtime_state(
            pending["before"], preserve_security=False
        )
        self.runtime.auth_custody.invalidate_sessions()
        await self.runtime.sync_persistence()
        self.runtime.vault.append_event(
            event_kind="RUNTIME_MUTATION_RECOVERED",
            subtree_root_id="root",
            actor_slot_id="SYSTEM",
            payload={"transaction_id": pending["transaction_id"]},
        )
        self.journal.unlink()

    @asynccontextmanager
    async def scope(
        self,
        precheck: Callable[[], Awaitable[None]] | None = None,
    ) -> AsyncIterator[MutationResult]:
        existing = active_mutation.get()
        if existing is not None and existing[0] is self.runtime:
            if precheck is not None:
                await precheck()
            yield existing[1]
            return
        async with self.lock:
            if precheck is not None:
                await precheck()
            before = await self.runtime.capture_state()
            transaction_id = uuid.uuid4().hex
            write_private_json(
                self.journal,
                {
                    "schema_version": 1,
                    "transaction_id": transaction_id,
                    "before": before,
                },
            )
            result = MutationResult()
            token = active_mutation.set((self.runtime, result))
            try:
                yield result
                if result.rollback:
                    await self.runtime.restore_runtime_state(
                        before, preserve_security=False
                    )
                await self.runtime.sync_persistence()
            except BaseException:
                result.rollback = True
                await self.runtime.restore_runtime_state(
                    before, preserve_security=False
                )
                await self.runtime.sync_persistence()
                self.journal.unlink(missing_ok=True)
                raise
            finally:
                active_mutation.reset(token)
                result.completed.set()
            self.journal.unlink(missing_ok=True)
            if not result.rollback and self.runtime.connectors is not None:
                await self.runtime.connectors.flush_outbox()

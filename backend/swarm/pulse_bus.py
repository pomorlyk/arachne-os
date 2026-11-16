from __future__ import annotations

import asyncio
from contextvars import copy_context
import uuid
from collections import deque
from typing import Any, Awaitable

from fastapi import WebSocket

from core.schemas import SwarmPulseEvent
from core.runtime_transactions import active_mutation


class PulseBus:
    """
    蛛网异步事件脉搏总线：
    1. 解耦同步聊天快响链路与后台异步演化任务（搓球聚类、影子陪跑、拓扑垫层）；
    2. 向所有在线 WebSocket 大屏客户端实时广播 SwarmPulseEvent。
    """

    def __init__(self, max_history: int = 200) -> None:
        self._history: deque[SwarmPulseEvent] = deque(maxlen=max_history)
        self._subscribers: set[WebSocket] = set()
        self._pending_tasks: set[asyncio.Task[Any]] = set()
        self._runtime: Any = None
        self._principals: dict[WebSocket, str] = {}
        self._credentials: dict[WebSocket, str] = {}

    def bind_runtime(self, runtime: Any) -> None:
        self._runtime = runtime

    def clear_history(self) -> None:
        self._history.clear()

    async def register_ws(self, ws: WebSocket, user_id: str | None = None, accepted: bool = False, token: str | None = None) -> None:
        if not accepted:
            await ws.accept()
        self._subscribers.add(ws)
        if user_id:
            self._principals[ws] = user_id
        if token:
            self._credentials[ws] = token

    def unregister_ws(self, ws: WebSocket) -> None:
        self._subscribers.discard(ws)
        self._principals.pop(ws, None)
        self._credentials.pop(ws, None)

    def recent_events(self, limit: int = 60) -> list[SwarmPulseEvent]:
        items = list(self._history)
        return items[-limit:]

    async def publish(
        self,
        event_type: str,
        node_id: str,
        subtree_root_id: str,
        summary: str,
        severity: str = "INFO",
        payload: dict[str, Any] | None = None,
    ) -> SwarmPulseEvent:
        evt = SwarmPulseEvent(
            event_id=f"EVT_{uuid.uuid4().hex[:8].upper()}",
            event_type=event_type,  # type: ignore[arg-type]
            node_id=node_id,
            subtree_root_id=subtree_root_id,
            severity=severity,  # type: ignore[arg-type]
            summary=summary,
            payload=payload or {},
        )
        self._history.append(evt)

        stale_sockets: list[WebSocket] = []
        for ws in list(self._subscribers):
            try:
                if self._runtime is not None:
                    credential = self._credentials.get(ws)
                    if not credential:
                        await ws.close(code=4401)
                        stale_sockets.append(ws)
                        continue
                    try:
                        self._runtime.auth_custody.resolve_bearer_token(f"Bearer {credential}")
                    except (ValueError, KeyError):
                        await ws.close(code=4401)
                        stale_sockets.append(ws)
                        continue
                serialized = self._project_event(evt, self._principals.get(ws))
                await ws.send_json(serialized)
            except Exception:
                stale_sockets.append(ws)
        for dead in stale_sockets:
            self.unregister_ws(dead)
        return evt

    def _project_event(self, event: SwarmPulseEvent, user_id: str | None) -> dict[str, Any]:
        # Every client fetches business details through its authorized overview.
        return {
            "event_id": event.event_id,
            "event_type": "STATE_UPDATED",
            "severity": "INFO",
            "summary": "工作台状态已更新",
            "payload": {},
        }

    def schedule_background(self, coro: Awaitable[Any]) -> asyncio.Task[Any]:
        origin = active_mutation.get()

        async def run() -> Any:
            if origin is not None and origin[0] is self._runtime:
                await origin[1].completed.wait()
                if origin[1].rollback:
                    if hasattr(coro, "close"):
                        coro.close()
                    return None
            if self._runtime is None:
                return await coro
            async with self._runtime.mutation_scope():
                return await coro

        context = copy_context()
        context.run(active_mutation.set, None)
        task = asyncio.create_task(run(), context=context)
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
        return task

    async def drain_background_tasks(self) -> None:
        while self._pending_tasks:
            current = list(self._pending_tasks)
            await asyncio.gather(*current, return_exceptions=True)


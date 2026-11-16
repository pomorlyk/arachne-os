from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import copy
import hashlib
import json
import uuid
from typing import Any, Awaitable, Callable, Optional

import httpx
import websockets

from config import ArachneSettings
from core.schemas import (
    BlackBoxTaskCard,
    ChatMessageItem,
    ChatScopeType,
    FacadeBotType,
)


class WeComTransportAdapter(ABC):
    """
    可插拔企业微信传输适配器基类：
    隔离业务引擎与底层 IM 传输通道，支持本地全真仿真器与真实企微长连接 / Webhook 一键切换。
    """

    @abstractmethod
    async def append_message(self, msg: ChatMessageItem) -> None: ...

    @abstractmethod
    async def push_interactive_card(
        self, target_user_id: str, facade_bot: FacadeBotType, card: BlackBoxTaskCard
    ) -> ChatMessageItem: ...

    @abstractmethod
    def get_chat_history(self, viewer_user_id: str, role_view: str) -> list[ChatMessageItem]: ...


class LocalSimulatorAdapter(WeComTransportAdapter):
    """
    默认开箱即用的本地全真企微三体合一仿真适配器：
    维护按角色隔离的门面号聊天流（#1 业务副驾 / #2 进化与风控官 / #3 董事会内参）与交互式卡片流。
    """

    def __init__(self) -> None:
        self._messages_by_user: dict[str, list[ChatMessageItem]] = {}
        self._processed_inbound: dict[str, dict[str, Any]] = {}
        self._delivery_metadata: dict[str, Any] = {}
        self._inbound_handler: Optional[Callable[[str, str, str], Awaitable[str]]] = None
        self._state_persistence_hook: Optional[Callable[[], Awaitable[None]]] = None
        self._sender_authorizer: Optional[Callable[[str], Awaitable[None]]] = None

    def bind_inbound_handler(self, handler: Callable[[str, str, str], Awaitable[str]]) -> None:
        self._inbound_handler = handler

    def bind_state_persistence_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        self._state_persistence_hook = hook

    def bind_sender_authorizer(self, authorizer: Callable[[str], Awaitable[None]]) -> None:
        self._sender_authorizer = authorizer

    def _set_transport_error(self, kind: str, **details: Any) -> None:
        self._delivery_metadata['last_error'] = {'kind': kind, **details}

    def export_state(self) -> dict[str, Any]:
        return {
            'messages_by_user': {uid: [m.model_dump() for m in rows] for uid, rows in self._messages_by_user.items()},
            'processed_inbound': copy.deepcopy(self._processed_inbound),
            'delivery_metadata': copy.deepcopy(self._delivery_metadata),
        }

    def restore_state(self, state: dict[str, Any] | None) -> None:
        state = state or {}
        self._messages_by_user = {uid: [ChatMessageItem(**m) for m in rows] for uid, rows in state.get('messages_by_user', {}).items()}
        self._processed_inbound = copy.deepcopy(state.get('processed_inbound', {}))
        self._delivery_metadata = copy.deepcopy(state.get('delivery_metadata', {}))

    def reset_messages(self) -> None:
        self._messages_by_user.clear()
        self._processed_inbound.clear()
        self._delivery_metadata.clear()

    def seed_welcome_for_profiles(self, profiles: list[Any], enterprise_name: str) -> None:
        """为当前活跃企业的各角色员工动态注入去硬编码的门面欢迎消息。"""
        for prof in profiles:
            if prof.user_id in self._messages_by_user:
                continue
            if prof.role_view == "boss":
                bot, bname, bid = "BOARD_INSIDER", "#3 董事会内参", "BOT_BOARD"
                text = (
                    f"🏛️ {prof.name}你好！欢迎接入【{enterprise_name}】指挥中枢。"
                    "当岗位 AI 可替代分突破 90 分时，可一键召开不超过 7 席的并发盲评董事会拍板进入【师徒反转接管期】。"
                )
            elif prof.role_view in ("manager", "leader", "blackbox"):
                bot, bname, bid = "GOVERNANCE", "#2 进化与风控官", "BOT_GOVERNANCE"
                text = (
                    f"🛡️ {prof.name}（{prof.title}）你好！你的工位【{prof.slot_id}】已接入企业活体蛛网拓扑，"
                    "触发风控审批或最小黑盒协同时将在此接收待办卡片。"
                )
            else:
                bot, bname, bid = "COPILOT", "#1 业务副驾", "BOT_COPILOT"
                text = (
                    f"👋 你好 {prof.name}！当前已挂载【{prof.title} ({prof.slot_id})】容器权能球，"
                    "可直接执行业务协同、在伴生舱导入对话或锻造可验证技能。"
                )
            self._messages_by_user[prof.user_id] = [
                ChatMessageItem(
                    msg_id=f"MSG_INIT_{uuid.uuid4().hex[:6].upper()}",
                    sender_id=bid,
                    sender_name=bname,
                    facade_bot=bot,
                    chat_type="SINGLE",
                    direction="OUTBOUND",
                    content=text,
                )
            ]

    async def append_message(self, msg: ChatMessageItem) -> None:
        # msg.sender_id 若是员工发出的 INBOUND，归入其会话桶；若是机器人回复，通过 structured_card.target_user 或 sender 桶归档
        bucket_user = (
            str(msg.structured_card.get("viewer_user_id"))
            if msg.structured_card and msg.structured_card.get("viewer_user_id")
            else msg.sender_id
        )
        self._messages_by_user.setdefault(bucket_user, []).append(msg)

    async def record_conversation_pair(
        self,
        user_id: str,
        user_name: str,
        facade_bot: FacadeBotType,
        chat_type: ChatScopeType,
        inbound_text: str,
        outbound_reply: str,
        ticket_id: Optional[str] = None,
        extra_card: Optional[dict[str, Any]] = None,
    ) -> tuple[ChatMessageItem, ChatMessageItem]:
        bot_names = {
            "COPILOT": "#1 业务副驾",
            "GOVERNANCE": "#2 进化与风控官",
            "BOARD_INSIDER": "#3 董事会内参",
        }
        in_msg = ChatMessageItem(
            msg_id=f"MSG_{uuid.uuid4().hex[:8].upper()}",
            sender_id=user_id,
            sender_name=user_name,
            facade_bot=facade_bot,
            chat_type=chat_type,
            direction="INBOUND",
            content=inbound_text,
            ticket_id=ticket_id,
        )
        out_msg = ChatMessageItem(
            msg_id=f"MSG_{uuid.uuid4().hex[:8].upper()}",
            sender_id=f"BOT_{facade_bot}",
            sender_name=bot_names[facade_bot],
            facade_bot=facade_bot,
            chat_type=chat_type,
            direction="OUTBOUND",
            content=outbound_reply,
            ticket_id=ticket_id,
            structured_card=extra_card,
        )
        bucket = self._messages_by_user.setdefault(user_id, [])
        bucket.append(in_msg)
        bucket.append(out_msg)
        return in_msg, out_msg

    async def push_interactive_card(
        self, target_user_id: str, facade_bot: FacadeBotType, card: BlackBoxTaskCard
    ) -> ChatMessageItem:
        bot_names = {
            "COPILOT": "#1 业务副驾",
            "GOVERNANCE": "#2 进化与风控官",
            "BOARD_INSIDER": "#3 董事会内参",
        }
        title = (
            f"⚡【高压线待拍板卡片 · {card.card_id}】"
            if card.card_kind == "LEADER_APPROVAL"
            else f"🧾【加密税控盘最小开票任务卡 · {card.card_id}】"
        )
        sys_msg = ChatMessageItem(
            msg_id=f"MSG_{uuid.uuid4().hex[:8].upper()}",
            sender_id=f"BOT_{facade_bot}",
            sender_name=bot_names[facade_bot],
            facade_bot=facade_bot,
            chat_type="SINGLE",
            direction="SYSTEM_CARD",
            content=title,
            ticket_id=card.ticket_id,
            structured_card=card.model_dump(),
        )
        self._messages_by_user.setdefault(target_user_id, []).append(sys_msg)
        return sys_msg

    async def push_board_brief(
        self,
        brief_text: str,
        resolution_dict: dict[str, Any],
        target_user_id: str | None = None,
    ) -> None:
        msg = ChatMessageItem(
            msg_id=f"MSG_{uuid.uuid4().hex[:8].upper()}",
            sender_id="BOT_BOARD_INSIDER",
            sender_name="#3 董事会内参",
            facade_bot="BOARD_INSIDER",
            chat_type="SINGLE",
            direction="SYSTEM_CARD",
            content=brief_text,
            structured_card=resolution_dict,
        )
        if not target_user_id:
            target_user_id = next(iter(self._messages_by_user.keys()), "boss")
        self._messages_by_user.setdefault(target_user_id, []).append(msg)

    def get_chat_history(self, viewer_user_id: str, role_view: str) -> list[ChatMessageItem]:
        return list(self._messages_by_user.get(viewer_user_id, []))


class WeComBotWSAdapter(LocalSimulatorAdapter):
    """WeCom SDK protocol bridge with acknowledged replies and durable deduplication.

    Protocol reference: https://github.com/WecomTeam/aibot-node-sdk
    The subscription authenticates the connection; sender IDs are passed unchanged
    to the runtime's current-directory authorization/business handler.
    """

    def __init__(self, settings: ArachneSettings) -> None:
        super().__init__()
        self._settings = settings
        self._ws_task: Optional[asyncio.Task[None]] = None
        self._heartbeat_task: Optional[asyncio.Task[None]] = None
        self._inbound_tasks: set[asyncio.Task[None]] = set()
        self._pending_requests: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._request_commands: dict[str, str] = {}
        self._inbound_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._authenticated = False
        self._request_timeout_seconds = 10.0
        self._heartbeat_interval_seconds = 30.0
        self._ws: Any = None

    def get_transport_status(self) -> dict[str, Any]:
        return {
            'adapter': 'WECOM_BOT_WS',
            'connection_status': self._delivery_metadata.get('connection_status', 'STOPPED'),
            'authenticated': self._authenticated,
            'capabilities': {'inbound_text_reply': True, 'proactive_interactive_card_delivery': False},
            'last_error': copy.deepcopy(self._delivery_metadata.get('last_error')),
        }

    async def push_interactive_card(
        self, target_user_id: str, facade_bot: FacadeBotType, card: BlackBoxTaskCard
    ) -> ChatMessageItem:
        msg = await super().push_interactive_card(target_user_id, facade_bot, card)
        delivery = {'adapter': 'WECOM_BOT_WS', 'status': 'PENDING_EXTERNAL_DELIVERY',
                    'reason': 'PROACTIVE_INTERACTIVE_CARD_DELIVERY_UNSUPPORTED'}
        msg.structured_card = {**(msg.structured_card or {}), 'delivery': delivery}
        self._delivery_metadata['last_delivery'] = copy.deepcopy(delivery)
        return msg

    async def start_ws_bridge_if_configured(self) -> None:
        if not (self._settings.wecom_bot_id and self._settings.wecom_bot_secret):
            self._delivery_metadata['connection_status'] = 'NOT_CONFIGURED'
            return
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = asyncio.create_task(self._maintain_ws_loop())

    async def _send_request(self, ws: Any, frame: dict[str, Any]) -> dict[str, Any]:
        req_id = frame['headers']['req_id']
        if req_id in self._pending_requests:
            raise RuntimeError('Reply for this req_id is already awaiting acknowledgment')
        future = asyncio.get_running_loop().create_future()
        self._pending_requests[req_id] = future
        self._request_commands[req_id] = frame['cmd']
        try:
            async with self._send_lock:
                await ws.send(json.dumps(frame, ensure_ascii=False))
            ack = await asyncio.wait_for(future, timeout=self._request_timeout_seconds)
            if ack.get('errcode') != 0:
                self._set_transport_error('REMOTE_REJECTED', errcode=ack.get('errcode'))
                raise ConnectionError('WeCom rejected the request')
            self._delivery_metadata['last_ack'] = {'req_id': req_id, 'errcode': 0}
            return ack
        finally:
            self._pending_requests.pop(req_id, None)
            self._request_commands.pop(req_id, None)

    async def _handle_ws_frame(self, frame: dict[str, Any], ws: Any) -> None:
        if not isinstance(frame, dict) or not isinstance(frame.get('headers'), dict):
            self._set_transport_error('INVALID_FRAME')
            return
        cmd = frame.get('cmd')
        req_id = frame['headers'].get('req_id')
        if not isinstance(req_id, str):
            self._set_transport_error('INVALID_FRAME')
            return
        if cmd not in ('aibot_msg_callback', 'aibot_event_callback'):
            pending = self._pending_requests.get(req_id)
            if pending is not None and not pending.done():
                # A callback can immediately follow the subscribe ack in the same read batch.
                if self._request_commands.get(req_id) == 'aibot_subscribe' and frame.get('errcode') == 0:
                    self._authenticated = True
                    self._delivery_metadata['connection_status'] = 'AUTHENTICATED'
                pending.set_result(frame)
            return
        if not self._authenticated:
            self._set_transport_error('UNAUTHENTICATED_CALLBACK')
            return
        if cmd != 'aibot_msg_callback':
            self._delivery_metadata['last_ignored_event'] = 'UNSUPPORTED_EVENT_CALLBACK'
            return
        task = asyncio.create_task(self._process_callback(frame, ws))
        self._inbound_tasks.add(task)
        task.add_done_callback(self._inbound_tasks.discard)

    async def _process_callback(self, frame: dict[str, Any], ws: Any) -> None:
        async with self._inbound_lock:
            body = frame.get('body')
            if (not isinstance(body, dict) or not isinstance(body.get('from'), dict)
                    or not isinstance(body.get('text'), dict)):
                self._set_transport_error('INVALID_CALLBACK')
                return
            req_id = frame['headers'].get('req_id')
            user_id = body['from'].get('userid')
            msgid = body.get('msgid')
            bot_id = body.get('aibotid')
            chat_type = body.get('chattype')
            content = (body.get('text') or {}).get('content')
            if (body.get('msgtype') != 'text' or chat_type not in ('single', 'group')
                    or not all(isinstance(x, str) and x.strip() for x in (req_id, user_id, msgid, bot_id, content))
                    or (self._settings.wecom_bot_id and bot_id != self._settings.wecom_bot_id)):
                self._set_transport_error('INVALID_CALLBACK')
                return
            if self._sender_authorizer is not None:
                try:
                    await self._sender_authorizer(user_id)
                except PermissionError:
                    self._set_transport_error('INBOUND_UNAUTHORIZED')
                    return
            fingerprint = hashlib.sha256(json.dumps(
                {'user_id': user_id, 'content': content, 'chat_type': chat_type, 'chatid': body.get('chatid')},
                sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            key = f'{bot_id}:{msgid}'
            existing = self._processed_inbound.get(key)
            if existing is not None and existing.get('fingerprint') != fingerprint:
                self._set_transport_error('MESSAGE_ID_CONFLICT', message_id=msgid)
                return
            if existing is None:
                if self._inbound_handler is None:
                    self._set_transport_error('INBOUND_HANDLER_NOT_BOUND')
                    return
                existing = {'status': 'PROCESSING', 'fingerprint': fingerprint, 'user_id': user_id,
                            'stream_id': f'stream_{uuid.uuid4().hex}'}
                self._processed_inbound[key] = existing
                try:
                    reply = await self._inbound_handler(user_id, content, chat_type.upper())
                    if not isinstance(reply, str):
                        raise ValueError('Business handler must return reply text')
                    # Root may restore the adapter while rolling back a failed business mutation.
                    self._processed_inbound[key] = existing
                    existing.update(status='SUCCEEDED', reply=reply)
                    if self._state_persistence_hook is not None:
                        await self._state_persistence_hook()
                except asyncio.CancelledError:
                    # A durable PROCESSING marker prevents uncertain results being executed twice.
                    raise
                except Exception as exc:
                    # A successful business result is never rerun just because its checkpoint failed.
                    if existing.get('status') != 'SUCCEEDED':
                        self._processed_inbound.pop(key, None)
                    kind = 'INBOUND_UNAUTHORIZED' if isinstance(exc, PermissionError) else 'INBOUND_FAILED'
                    self._set_transport_error(kind, exception_type=type(exc).__name__)
                    return
            reply = existing.get('reply') if existing.get('status') == 'SUCCEEDED' else '此消息已接收，处理结果尚待核验，请联系主管确认。'
            try:
                await self._send_request(ws, {
                    'cmd': 'aibot_respond_msg', 'headers': {'req_id': req_id},
                    'body': {'msgtype': 'stream', 'stream': {
                        'id': existing['stream_id'], 'content': reply, 'finish': True,
                    }},
                })
                self._delivery_metadata['last_delivery'] = {'message_id': msgid, 'status': 'ACKNOWLEDGED'}
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._set_transport_error('REPLY_DELIVERY_FAILED', message_id=msgid, exception_type=type(exc).__name__)

    async def _read_connection(self, ws: Any) -> None:
        async for raw in ws:
            try:
                frame = json.loads(raw)
                if not isinstance(frame, dict):
                    raise ValueError('Expected WebSocket object frame')
                await self._handle_ws_frame(frame, ws)
            except (ValueError, TypeError):
                self._set_transport_error('INVALID_FRAME')
        raise ConnectionError('WeCom connection closed')

    async def _heartbeat_loop(self, ws: Any) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval_seconds)
            await self._send_request(ws, {'cmd': 'ping', 'headers': {'req_id': f'ping_{uuid.uuid4().hex}'}})

    async def _cancel_connection_tasks(self) -> None:
        self._authenticated = False
        tasks = list(self._inbound_tasks)
        if self._heartbeat_task is not None:
            tasks.append(self._heartbeat_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._inbound_tasks.clear()
        self._heartbeat_task = None
        for pending in self._pending_requests.values():
            if not pending.done():
                pending.cancel()
        self._pending_requests.clear()
        self._request_commands.clear()

    async def _maintain_ws_loop(self) -> None:
        backoff = 1.0
        while True:
            reader = None
            try:
                self._delivery_metadata['connection_status'] = 'CONNECTING'
                async with websockets.connect(self._settings.wecom_ws_endpoint) as ws:
                    self._ws = ws
                    reader = asyncio.create_task(self._read_connection(ws))
                    await self._send_request(ws, {
                        'cmd': 'aibot_subscribe', 'headers': {'req_id': f'auth_{uuid.uuid4().hex}'},
                        'body': {'bot_id': self._settings.wecom_bot_id, 'secret': self._settings.wecom_bot_secret},
                    })
                    self._authenticated = True
                    self._delivery_metadata['connection_status'] = 'AUTHENTICATED'
                    backoff = 1.0
                    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))
                    done, _ = await asyncio.wait([reader, self._heartbeat_task], return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._delivery_metadata['connection_status'] = 'RECONNECTING'
                self._set_transport_error('CONNECTION_FAILED', exception_type=type(exc).__name__)
            finally:
                if reader is not None:
                    reader.cancel()
                    await asyncio.gather(reader, return_exceptions=True)
                await self._cancel_connection_tasks()
                self._ws = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 30.0)

    async def stop_ws_bridge(self) -> None:
        if self._ws_task is not None:
            self._ws_task.cancel()
            await asyncio.gather(self._ws_task, return_exceptions=True)
            self._ws_task = None
        await self._cancel_connection_tasks()
        self._delivery_metadata['connection_status'] = 'STOPPED'


class WeComWebhookCallbackAdapter(LocalSimulatorAdapter):
    """
    传统企业微信群机器人 Webhook 推送适配器（兼顾本地仿真镜像与真实群卡片投递）。
    """

    def __init__(self, settings: ArachneSettings) -> None:
        super().__init__()
        self._settings = settings

    async def push_interactive_card(
        self, target_user_id: str, facade_bot: FacadeBotType, card: BlackBoxTaskCard
    ) -> ChatMessageItem:
        msg = await super().push_interactive_card(target_user_id, facade_bot, card)
        delivery: dict[str, Any] = {'adapter': 'WECOM_WEBHOOK', 'status': 'NOT_CONFIGURED'}
        if self._settings.wecom_webhook_key:
            url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={self._settings.wecom_webhook_key}"
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.post(url, json={
                        'msgtype': 'markdown', 'markdown': {
                            'content': f"**{msg.content}**\n> 最小输入载荷: `{json.dumps(card.minimized_payload, ensure_ascii=False)}`"
                        },
                    })
                    delivery['http_status'] = response.status_code
                    response.raise_for_status()
                    result = response.json()
                    delivery['errcode'] = result.get('errcode')
                    if result.get('errcode') != 0:
                        raise ValueError('WeCom webhook rejected payload')
                    delivery['status'] = 'ACKNOWLEDGED'
            except Exception as exc:
                delivery['status'] = 'FAILED'
                delivery['exception_type'] = type(exc).__name__
                self._set_transport_error('WEBHOOK_DELIVERY_FAILED', **delivery)
        msg.structured_card = {**(msg.structured_card or {}), 'delivery': delivery}
        self._delivery_metadata['last_delivery'] = copy.deepcopy(delivery)
        return msg


def create_wecom_gateway(settings: ArachneSettings) -> LocalSimulatorAdapter:
    mode = settings.wecom_adapter_mode.upper()
    if mode == "WECOM_BOT_WS":
        return WeComBotWSAdapter(settings)
    if mode == "WECOM_WEBHOOK":
        return WeComWebhookCallbackAdapter(settings)
    return LocalSimulatorAdapter()


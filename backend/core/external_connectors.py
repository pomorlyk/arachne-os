from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
import asyncio
import hashlib
import hmac
import json
import time
from typing import Any, Literal, Optional
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from config import ArachneSettings
from core.schemas import BlackBoxTaskCard, utc_now_iso

ConnectorType = Literal["LOCAL_WORKBENCH", "HTTP_WEBHOOK", "WECOM_GROUP_BOT"]


class ConnectorBinding(BaseModel):
    slot_id: str
    connector_type: ConnectorType = "LOCAL_WORKBENCH"
    endpoint_url: str = ""
    hmac_secret_override: str = ""
    mention_list: list[str] = Field(default_factory=list)
    enabled: bool = True
    updated_at: str = Field(default_factory=utc_now_iso)


def compute_arachne_hmac_signature(
    secret: str, timestamp: str, raw_body: bytes
) -> str:
    """计算标准 Arachne Webhook HMAC-SHA256 签名：sha256=hex(HMAC(secret, '<ts>.<body>'))。"""
    msg = f"{timestamp}.".encode("utf-8") + raw_body
    digest = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class BaseExternalConnector(ABC):
    """外部系统（ERP / WMS / 金税 / 企微机器人）标准连接器抽象协议。"""

    @abstractmethod
    async def dispatch_card(
        self, card: BlackBoxTaskCard, binding: ConnectorBinding
    ) -> dict[str, Any]:
        ...


class LocalWorkbenchConnector(BaseExternalConnector):
    """兼容现有零配置演示工作台的内置本地回执连接器。"""

    async def dispatch_card(
        self, card: BlackBoxTaskCard, binding: ConnectorBinding
    ) -> dict[str, Any]:
        return {
            "dispatched": True,
            "channel": "LOCAL_WORKBENCH",
            "card_id": card.card_id,
            "ticket_id": card.ticket_id,
            "slot_id": card.target_slot_id,
            "idempotency_key": f"IDEMP_{card.card_id}",
            "attempts": 1,
            "dispatched_at": card.created_at,
        }


class HttpWebhookConnector(BaseExternalConnector):
    """
    生产级 HTTP Webhook 外部连接器：
    - 仅向外投递经 InputMinimizer 裁剪的 minimized_payload，附带幂等键；
    - 使用 X-Arachne-Timestamp 与 X-Arachne-Signature (HMAC-SHA256) 防篡改防重放；
    - 支持可配置指数退避重试。
    """

    def __init__(
        self,
        *,
        default_secret: str,
        timeout_seconds: float = 5.0,
        max_retries: int = 3,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._default_secret = default_secret
        self._timeout_seconds = max(0.5, timeout_seconds)
        self._max_retries = max(1, max_retries)
        self._transport = transport

    async def dispatch_card(
        self, card: BlackBoxTaskCard, binding: ConnectorBinding
    ) -> dict[str, Any]:
        endpoint = binding.endpoint_url.strip()
        idemp_key = f"IDEMP_{card.card_id}"
        if not endpoint:
            return {
                "dispatched": False,
                "channel": "HTTP_WEBHOOK",
                "card_id": card.card_id,
                "slot_id": card.target_slot_id,
                "idempotency_key": idemp_key,
                "reason": "empty_endpoint_url",
                "attempts": 0,
            }

        outbound = {
            "event": "BLACKBOX_CARD_DISPATCHED",
            "idempotency_key": idemp_key,
            "card_id": card.card_id,
            "ticket_id": card.ticket_id,
            "contract_id": card.contract_id,
            "target_slot_id": card.target_slot_id,
            "card_kind": card.card_kind,
            "minimized_payload": card.minimized_payload,
            "callback_path": f"/api/v1/connectors/callback/{card.card_id}",
            "dispatched_at": card.created_at,
        }
        raw_body = json.dumps(
            outbound, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        secret = binding.hmac_secret_override.strip() or self._default_secret

        last_error = ""
        last_status: Optional[int] = None
        attempts = 0
        for attempt in range(self._max_retries):
            attempts = attempt + 1
            ts = str(int(time.time()))
            sig = compute_arachne_hmac_signature(secret, ts, raw_body)
            headers = {
                "Content-Type": "application/json",
                "X-Arachne-Timestamp": ts,
                "X-Arachne-Idempotency-Key": idemp_key,
                "X-Arachne-Signature": sig,
            }
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout_seconds,
                    transport=self._transport,
                ) as client:
                    resp = await client.post(
                        endpoint, content=raw_body, headers=headers
                    )
                    last_status = resp.status_code
                    if 200 <= resp.status_code < 300:
                        return {
                            "dispatched": True,
                            "channel": "HTTP_WEBHOOK",
                            "card_id": card.card_id,
                            "slot_id": card.target_slot_id,
                            "idempotency_key": idemp_key,
                            "endpoint_url": endpoint,
                            "status_code": resp.status_code,
                            "attempts": attempts,
                            "dispatched_at": utc_now_iso(),
                        }
                    last_error = f"HTTP {resp.status_code}"
                    if resp.status_code < 500 and resp.status_code != 429:
                        break
            except Exception as exc:
                last_error = str(exc)

            if attempt + 1 < self._max_retries:
                await asyncio.sleep(0.05 * (2**attempt))

        return {
            "dispatched": False,
            "channel": "HTTP_WEBHOOK",
            "card_id": card.card_id,
            "slot_id": card.target_slot_id,
            "idempotency_key": idemp_key,
            "endpoint_url": endpoint,
            "status_code": last_status,
            "attempts": attempts,
            "error": last_error,
            "dispatched_at": utc_now_iso(),
        }


class WeComGroupBotConnector(BaseExternalConnector):
    """企业微信群 Webhook 机器人卡片投递与 @ 提醒连接器。"""

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._timeout_seconds = max(0.5, timeout_seconds)
        self._transport = transport

    async def dispatch_card(
        self, card: BlackBoxTaskCard, binding: ConnectorBinding
    ) -> dict[str, Any]:
        endpoint = binding.endpoint_url.strip()
        idemp_key = f"IDEMP_{card.card_id}"
        if not endpoint:
            return {
                "dispatched": False,
                "channel": "WECOM_GROUP_BOT",
                "card_id": card.card_id,
                "slot_id": card.target_slot_id,
                "idempotency_key": idemp_key,
                "reason": "empty_endpoint_url",
                "attempts": 0,
            }

        mentions = " ".join(f"@{m}" for m in binding.mention_list) if binding.mention_list else ""
        md_content = (
            f"### ⚡ Arachne-OS 协同任务卡 `{card.card_id}`\n"
            f"> 类型: `{card.card_kind}` | 目标工位: `{card.target_slot_id}` {mentions}\n"
            f"> 最小输入载荷: `{json.dumps(card.minimized_payload, ensure_ascii=False)}`"
        )
        body: dict[str, Any] = {
            "msgtype": "markdown",
            "markdown": {"content": md_content},
        }
        if binding.mention_list:
            body["markdown"]["mentioned_list"] = list(binding.mention_list)

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                resp = await client.post(endpoint, json=body)
                try:
                    response_body = resp.json()
                except ValueError:
                    response_body = {}
                accepted = 200 <= resp.status_code < 300 and response_body.get("errcode") == 0
                return {
                    "dispatched": accepted,
                    "channel": "WECOM_GROUP_BOT",
                    "card_id": card.card_id,
                    "slot_id": card.target_slot_id,
                    "idempotency_key": idemp_key,
                    "status_code": resp.status_code,
                    "attempts": 1,
                    "dispatched_at": utc_now_iso(),
                    "provider_error": response_body.get("errcode"),
                    "error": "" if accepted else str(response_body.get("errmsg") or f"HTTP {resp.status_code}"),
                }
        except Exception as exc:
            return {
                "dispatched": False,
                "channel": "WECOM_GROUP_BOT",
                "card_id": card.card_id,
                "slot_id": card.target_slot_id,
                "idempotency_key": idemp_key,
                "error": str(exc),
                "attempts": 1,
                "dispatched_at": utc_now_iso(),
            }


class ExternalConnectorRegistry:
    """
    管理按工位槽位 (slot_id) 绑定的外部系统连接器、出站卡片投递、
    入站回调 HMAC-SHA256 验签及幂等去重账本。
    """

    def __init__(
        self,
        settings: ArachneSettings,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._bindings: dict[str, ConnectorBinding] = {}
        self._callback_receipts: dict[str, dict[str, Any]] = {}
        self._dispatch_history: list[dict[str, Any]] = []
        self._outbox: dict[str, dict[str, Any]] = {}
        self._runtime: Any = None

    def bind_runtime(self, runtime: Any) -> None:
        self._runtime = runtime

    def public_bindings(self) -> list[dict[str, Any]]:
        return [b.model_dump(exclude={"hmac_secret_override"}) for b in self._bindings.values()]

    def set_http_transport(
        self, transport: Optional[httpx.AsyncBaseTransport]
    ) -> None:
        self._transport = transport

    def bind_slot_connector(self, binding: ConnectorBinding) -> ConnectorBinding:
        if binding.enabled and binding.connector_type != "LOCAL_WORKBENCH":
            endpoint = urlsplit(binding.endpoint_url.strip())
            if endpoint.scheme not in ("https", "http") or not endpoint.hostname or endpoint.username or endpoint.password:
                raise ValueError("外部连接器需要有效的 HTTP(S) endpoint URL")
            if binding.connector_type == "HTTP_WEBHOOK" and not (
                binding.hmac_secret_override.strip() or self._settings.connector_hmac_secret.strip()
            ):
                raise ValueError("HTTP Webhook 必须配置独立签名密钥 secret")
        stored = binding.model_copy(update={"updated_at": utc_now_iso()})
        self._bindings[stored.slot_id] = stored
        return stored

    def get_binding(self, slot_id: str) -> ConnectorBinding:
        if slot_id in self._bindings:
            return self._bindings[slot_id]
        return ConnectorBinding(slot_id=slot_id, connector_type="LOCAL_WORKBENCH")

    def list_bindings(self) -> list[ConnectorBinding]:
        return list(self._bindings.values())

    def _build_connector(self, connector_type: ConnectorType) -> BaseExternalConnector:
        if connector_type == "HTTP_WEBHOOK":
            return HttpWebhookConnector(
                default_secret=self._settings.connector_hmac_secret,
                timeout_seconds=self._settings.connector_http_timeout_seconds,
                max_retries=self._settings.connector_max_retries,
                transport=self._transport,
            )
        if connector_type == "WECOM_GROUP_BOT":
            return WeComGroupBotConnector(
                timeout_seconds=self._settings.connector_http_timeout_seconds,
                transport=self._transport,
            )
        return LocalWorkbenchConnector()

    async def dispatch_card_for_slot(
        self, card: BlackBoxTaskCard
    ) -> dict[str, Any]:
        previous = self._outbox.get(card.card_id)
        if previous and previous.get("status") == "SENT":
            return {**previous["receipt"], "idempotent_replay": True}
        from core.runtime_transactions import active_mutation
        active = active_mutation.get()
        if self._runtime is not None and active is not None and active[0] is self._runtime:
            self._outbox.setdefault(card.card_id, {"card": card.model_dump(mode="json"), "status": "PENDING"})
            return {
                "dispatched": False, "status": "QUEUED", "card_id": card.card_id,
                "idempotency_key": f"IDEMP_{card.card_id}",
            }
        return await self._send_card(card)

    async def _send_card(self, card: BlackBoxTaskCard) -> dict[str, Any]:
        binding = self.get_binding(card.target_slot_id)
        if not binding.enabled:
            receipt = {
                "dispatched": False,
                "channel": binding.connector_type,
                "card_id": card.card_id,
                "slot_id": card.target_slot_id,
                "reason": "binding_disabled",
            }
        else:
            adapter = self._build_connector(binding.connector_type)
            receipt = await adapter.dispatch_card(card, binding)
        self._dispatch_history.append(receipt)
        self._outbox[card.card_id] = {
            "card": card.model_dump(mode="json"),
            "status": "SENT" if receipt.get("dispatched") else "FAILED",
            "receipt": receipt,
        }
        if len(self._dispatch_history) > 200:
            self._dispatch_history = self._dispatch_history[-200:]
        return receipt

    async def flush_outbox(self) -> None:
        for item in list(self._outbox.values()):
            if item.get("status") != "PENDING":
                continue
            await self._send_card(BlackBoxTaskCard(**item["card"]))
            if self._runtime is not None:
                await self._runtime.sync_persistence()

    def was_dispatched(self, card_id: str) -> bool:
        item = self._outbox.get(card_id, {})
        return item.get("status") == "SENT" and item.get("receipt", {}).get("channel") == "HTTP_WEBHOOK"

    def retry_dispatch(self, card_id: str) -> None:
        item = self._outbox.get(card_id)
        if item is None:
            raise KeyError("找不到对应的派发记录")
        if item.get("status") != "FAILED":
            raise ValueError("只能重试已失败的外部派发")
        item["status"] = "PENDING"

    def verify_callback_signature(
        self,
        slot_id: str,
        timestamp: str,
        signature: str,
        raw_body: bytes,
        *,
        max_skew_seconds: int = 300,
    ) -> tuple[bool, str]:
        binding = self._bindings.get(slot_id)
        if binding is None or not binding.enabled or binding.connector_type != "HTTP_WEBHOOK":
            return (False, "EXTERNAL_BINDING_REQUIRED")
        secret = binding.hmac_secret_override.strip() or self._settings.connector_hmac_secret.strip()
        if not secret:
            return (False, "SIGNING_SECRET_REQUIRED")
        if not timestamp.strip() or not signature.strip():
            return (False, "MISSING_SIGNATURE")
        try:
            ts_int = int(timestamp.strip())
        except ValueError:
            return (False, "INVALID_SIGNATURE")
        if abs(int(time.time()) - ts_int) > max_skew_seconds:
            return (False, "EXPIRED_TIMESTAMP")

        expected = compute_arachne_hmac_signature(secret, timestamp.strip(), raw_body)
        provided = signature.strip()
        if not provided.startswith("sha256="):
            provided = f"sha256={provided}"
        if not hmac.compare_digest(expected, provided):
            return (False, "INVALID_SIGNATURE")
        return (True, "OK")

    def get_idempotent_receipt(
        self, card_id: str, idempotency_key: str
    ) -> Optional[dict[str, Any]]:
        key = f"{card_id}:{idempotency_key}"
        if key in self._callback_receipts:
            return dict(self._callback_receipts[key])
        return None

    def record_idempotent_receipt(
        self,
        card_id: str,
        idempotency_key: str,
        response_payload: dict[str, Any],
    ) -> None:
        key = f"{card_id}:{idempotency_key}"
        self._callback_receipts[key] = dict(response_payload)

    def export_state(self) -> dict[str, Any]:
        return deepcopy({
            "bindings": [b.model_dump() for b in self._bindings.values()],
            "callback_receipts": dict(self._callback_receipts),
            "dispatch_history": list(self._dispatch_history[-50:]),
            "outbox": self._outbox,
        })

    def restore_state(self, state: Optional[dict[str, Any]]) -> None:
        state = state or {}
        self._bindings = {}
        for raw_b in state.get("bindings", []):
            binding = ConnectorBinding(**raw_b)
            self._bindings[binding.slot_id] = binding
        self._callback_receipts = deepcopy(state.get("callback_receipts") or {})
        self._dispatch_history = deepcopy(state.get("dispatch_history") or [])
        self._outbox = deepcopy(state.get("outbox") or {})

    def health_summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for b in self._bindings.values():
            counts[b.connector_type] = counts.get(b.connector_type, 0) + 1
        return {
            "total_bindings": len(self._bindings),
            "bindings_by_type": counts,
            "recent_dispatches_count": len(self._dispatch_history),
            "idempotent_callbacks_recorded": len(self._callback_receipts),
            "hmac_configured": bool(self._settings.connector_hmac_secret),
            "pending_dispatches": sum(x.get("status") == "PENDING" for x in self._outbox.values()),
            "failed_dispatches": sum(x.get("status") == "FAILED" for x in self._outbox.values()),
        }


from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.external_connectors import ConnectorBinding, ConnectorType, ExternalConnectorRegistry
from core.schemas import BlackBoxTaskCard
from core.security import require_roles
from core.topology_resolver import (
    resolve_blackbox_user_and_slot,
)
from surfaces.api_routes import _rt

connector_router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])


class ConnectorBindingRequest(BaseModel):
    slot_id: str
    connector_type: ConnectorType = "HTTP_WEBHOOK"
    endpoint_url: str = ""
    hmac_secret_override: str = ""
    mention_list: list[str] = Field(default_factory=list)
    enabled: bool = True


def _get_registry(request: Request) -> tuple[Any, ExternalConnectorRegistry]:
    rt = _rt(request)
    if rt.connectors is None:
        rt.connectors = ExternalConnectorRegistry(rt.settings)
    return rt, rt.connectors


@connector_router.get("/bindings")
async def list_connector_bindings(request: Request) -> dict[str, Any]:
    require_roles(request, "manager", "boss")
    _, registry = _get_registry(request)
    return {
        "bindings": registry.public_bindings(),
        "supported_types": ["LOCAL_WORKBENCH", "HTTP_WEBHOOK", "WECOM_GROUP_BOT"],
        "health": registry.health_summary(),
    }


@connector_router.post("/bindings")
async def upsert_connector_binding(
    req: ConnectorBindingRequest, request: Request
) -> dict[str, Any]:
    require_roles(request, "manager", "boss")
    rt, registry = _get_registry(request)
    if req.slot_id not in rt.containers._slots:
        raise HTTPException(status_code=404, detail=f"岗位槽位不存在: {req.slot_id}")

    binding = ConnectorBinding(
        slot_id=req.slot_id,
        connector_type=req.connector_type,
        endpoint_url=req.endpoint_url,
        hmac_secret_override=req.hmac_secret_override,
        mention_list=req.mention_list,
        enabled=req.enabled,
    )
    stored = registry.bind_slot_connector(binding)
    rt.vault.append_event(
        event_kind="CONNECTOR_BINDING_UPDATED",
        subtree_root_id="root",
        actor_slot_id=req.slot_id,
        payload={
            "slot_id": stored.slot_id,
            "connector_type": stored.connector_type,
            "endpoint_url": stored.endpoint_url,
            "enabled": stored.enabled,
        },
    )
    await rt.sync_persistence()
    return {
        "binding": stored.model_dump(exclude={"hmac_secret_override"}),
        "bindings": registry.public_bindings(),
    }


@connector_router.post("/dispatch/{card_id}/retry")
async def retry_connector_dispatch(card_id: str, request: Request) -> dict[str, Any]:
    require_roles(request, "manager", "boss")
    rt, registry = _get_registry(request)
    card = rt.human_tools.get_card(card_id)
    if card.status != "PENDING":
        raise HTTPException(status_code=409, detail="已结束的任务卡不能重新派发")
    registry.retry_dispatch(card_id)
    await rt.sync_persistence()
    return {"card_id": card_id, "status": "QUEUED"}


@dataclass(frozen=True)
class VerifiedConnectorCallback:
    runtime: Any
    registry: ExternalConnectorRegistry
    card: BlackBoxTaskCard
    actor_user_id: str
    idempotency_key: str
    submitted_output: dict[str, Any]
    cached_receipt: Optional[dict[str, Any]]


async def prepare_connector_callback(
    card_id: str, request: Request
) -> VerifiedConnectorCallback:
    """Read-only callback authorization, run under the runtime mutation lock.

    Keep the signed bytes intact and pass the verified inputs to the handler so
    authorization and execution use the same state within that lock.
    """
    rt = _rt(request)
    try:
        card = rt.human_tools.get_card(card_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    registry = rt.connectors
    if registry is None:
        raise HTTPException(
            status_code=403, detail="外部连接器回调验签未通过: EXTERNAL_BINDING_REQUIRED"
        )

    raw_body = await request.body()
    ts = request.headers.get("X-Arachne-Timestamp", "")
    sig = request.headers.get("X-Arachne-Signature", "")

    valid_sig, reason = registry.verify_callback_signature(
        slot_id=card.target_slot_id,
        timestamp=ts,
        signature=sig,
        raw_body=raw_body,
    )
    if not valid_sig:
        status_code = 401 if reason == "MISSING_SIGNATURE" else 403
        raise HTTPException(
            status_code=status_code,
            detail=f"外部连接器回调验签未通过: {reason}",
        )
    if not registry.was_dispatched(card_id):
        raise HTTPException(status_code=409, detail="尚无成功送达的外部请求，无法确认其回调")

    try:
        body: dict[str, Any] = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail="回调请求体不是合法 JSON") from exc
    if not isinstance(body, dict) or body.get("card_id") != card_id or body.get("ticket_id") != card.ticket_id:
        raise HTTPException(status_code=403, detail="签名回调必须包含匹配的 card_id 和 ticket_id")

    idemp_key = (
        request.headers.get("X-Arachne-Idempotency-Key", "").strip()
        or str(body.get("idempotency_key") or "").strip()
        or f"CB_{card_id}"
    )

    raw_output = body.get("submitted_output")
    if isinstance(raw_output, dict):
        submitted_output = dict(raw_output)
    else:
        submitted_output = {
            k: v
            for k, v in body.items()
            if k not in ("idempotency_key", "actor_user_id", "submitted_output")
        }

    try:
        target_slot = rt.containers.get_slot(card.target_slot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    actor_user_id = target_slot.occupant_id
    if not actor_user_id or (body.get("actor_user_id") and body["actor_user_id"] != actor_user_id):
        raise HTTPException(status_code=403, detail="回调操作人必须匹配已绑定的目标岗位")
    cached = registry.get_idempotent_receipt(card_id, idemp_key)
    if cached is not None:
        if card.submitted_output != submitted_output:
            raise HTTPException(status_code=409, detail="相同幂等键不能提交不同结果")
    verified = VerifiedConnectorCallback(
        runtime=rt, registry=registry, card=card, actor_user_id=actor_user_id,
        idempotency_key=idemp_key, submitted_output=submitted_output,
        cached_receipt=cached,
    )
    request.state.verified_connector_callback = verified
    return verified


@connector_router.post("/callback/{card_id}")
async def receive_connector_callback(card_id: str, request: Request) -> Any:
    verified = getattr(request.state, "verified_connector_callback", None)
    if verified is None or verified.card.card_id != card_id:
        verified = await prepare_connector_callback(card_id, request)
    rt, registry, card = verified.runtime, verified.registry, verified.card
    actor_user_id = verified.actor_user_id
    idemp_key = verified.idempotency_key
    submitted_output = verified.submitted_output
    if verified.cached_receipt is not None:
        return {**verified.cached_receipt, "idempotent_replay": True}

    await rt.spider.rehydrate_slot_nodes(
        [card.target_slot_id], reason="connector_callback"
    )
    res = await rt.spider.handle_human_tool_submission(
        actor_user_id=actor_user_id,
        card_id=card_id,
        submitted_output=submitted_output,
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
    next_dispatch: Optional[dict[str, Any]] = None
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
        next_dispatch = await registry.dispatch_card_for_slot(next_card)

    rt.vault.append_event(
        event_kind="EXTERNAL_CONNECTOR_CALLBACK_COMPLETED",
        subtree_root_id=res["ticket"].subtree_root_id,
        actor_slot_id=card.target_slot_id,
        payload={
            "card_id": card_id,
            "ticket_id": res["ticket"].ticket_id,
            "ticket_status": res["ticket"].status,
            "idempotency_key": idemp_key,
            "actor_user_id": actor_user_id,
        },
    )

    response_payload = {
        "accepted": True,
        "idempotent_replay": False,
        "idempotency_key": idemp_key,
        "card": res["card"].model_dump(),
        "ticket": res["ticket"].model_dump(),
        "next_card": next_card.model_dump() if next_card else None,
        "next_dispatch": next_dispatch,
    }
    registry.record_idempotent_receipt(card_id, idemp_key, response_payload)
    await rt.sync_persistence()
    return response_payload


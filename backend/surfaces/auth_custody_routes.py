from __future__ import annotations

import uuid
from typing import Any, Literal, Optional
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from core.auth_custody import AuthAndCustodyService
from core.schemas import ChatMessageItem
from core.security import get_authenticated_account, require_roles

auth_custody_router = APIRouter(tags=["auth_and_custody"])


def _get_service(request: Request) -> tuple[Any, AuthAndCustodyService]:
    rt = request.app.state.runtime
    svc = getattr(rt, "auth_custody", None)
    if svc is None:
        svc = AuthAndCustodyService(
            vault=rt.vault,
            particles=rt.particles,
            containers=rt.containers,
            settings=rt.settings,
        )
        setattr(rt, "auth_custody", svc)
    return rt, svc


def _acting_user(request: Request, supplied: Optional[str]) -> str:
    account = get_authenticated_account(request)
    if account is None:
        return str(supplied or "")
    if supplied and supplied.strip() != account.user_id:
        raise HTTPException(status_code=403, detail="操作身份与当前登录账号不匹配")
    return account.user_id


class LoginPayload(BaseModel):
    username: str
    password: str


class ProvisionPasswordPayload(BaseModel):
    new_password: str


class ChangePasswordPayload(BaseModel):
    user_id: str
    old_password: str
    new_password: str


class BallRequestPayload(BaseModel):
    requester_id: str
    ball_id: str
    grant_mode: Literal["LEASE_TTL", "PERMANENT"] = "LEASE_TTL"
    ttl_minutes: int = 120
    reason: str = "跨岗业务协同需要调用该权能球"


class DecideBallRequestPayload(BaseModel):
    actor_user_id: str
    approve: bool
    comment: str = ""


class DirectGrantPayload(BaseModel):
    leader_user_id: str
    target_slot_id: str
    ball_id: str
    grant_mode: Literal["LEASE_TTL", "PERMANENT"] = "PERMANENT"
    ttl_minutes: int = 120


class RevokeBallPayload(BaseModel):
    leader_user_id: str
    target_slot_id: str
    ball_id: str


class SlotHandoverPayload(BaseModel):
    actor_user_id: Optional[str] = None
    target_slot_id: str
    new_user_id: str
    new_person_name: str
    handover_mode: Literal["LEAVE_DELEGATION", "TEMP_RELIEF", "RESIGN_HANDOVER"] = "RESIGN_HANDOVER"
    reason: str = "员工调岗/休假工位无缝交接"
    initial_password: Optional[str] = None


async def _sync_rt(rt: Any) -> None:
    if hasattr(rt, "sync_persistence"):
        await rt.sync_persistence()


@auth_custody_router.get("/api/v1/auth/accounts")
async def list_accounts(request: Request) -> dict[str, Any]:
    _, svc = _get_service(request)
    return {
        "accounts": [a.model_dump() for a in svc.list_public_accounts()],
        "password_provisioning_required": any(
            a.user_id not in svc._passwords for a in svc.list_public_accounts()
        ),
    }


@auth_custody_router.post("/api/v1/auth/login")
async def login_account(payload: LoginPayload, request: Request) -> dict[str, Any]:
    _, svc = _get_service(request)
    try:
        return svc.login(payload.username, payload.password)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@auth_custody_router.post("/api/v1/auth/logout")
async def logout_account(
    request: Request, authorization: Optional[str] = Header(default=None)
) -> dict[str, Any]:
    _, svc = _get_service(request)
    svc.logout(authorization)
    return {"ok": True}


@auth_custody_router.get("/api/v1/auth/me")
async def get_auth_me(
    request: Request,
    user_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _, svc = _get_service(request)
    try:
        account = get_authenticated_account(request)
        if account is not None:
            return svc.get_current_account(token=authorization, user_id=account.user_id)
        return svc.get_current_account(token=authorization, user_id=user_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@auth_custody_router.post("/api/v1/auth/change-password")
async def change_account_password(
    payload: ChangePasswordPayload, request: Request
) -> dict[str, Any]:
    rt, svc = _get_service(request)
    try:
        out = svc.change_password(
            user_id=_acting_user(request, payload.user_id),
            old_password=payload.old_password,
            new_password=payload.new_password,
        )
        await _sync_rt(rt)
        return out
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@auth_custody_router.post("/api/v1/auth/accounts/{user_id}/password")
async def provision_account_password(user_id: str, payload: ProvisionPasswordPayload, request: Request) -> dict[str, Any]:
    rt, svc = _get_service(request)
    actor = require_roles(request, "manager", "boss")
    if actor is None:
        raise HTTPException(status_code=401, detail="账号密码配置必须使用管理员 Bearer 登录凭证")
    result = svc.provision_account_password(actor.user_id, user_id, payload.new_password)
    await _sync_rt(rt)
    return result


@auth_custody_router.get("/api/v1/custody/overview")
async def get_custody_overview(request: Request, user_id: Optional[str] = None) -> dict[str, Any]:
    _, svc = _get_service(request)
    try:
        return svc.build_custody_overview(_acting_user(request, user_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@auth_custody_router.post("/api/v1/custody/requests")
async def create_ball_request(
    payload: BallRequestPayload, request: Request
) -> dict[str, Any]:
    rt, svc = _get_service(request)
    try:
        item = svc.submit_ball_request(
            requester_id=_acting_user(request, payload.requester_id),
            ball_id=payload.ball_id,
            grant_mode=payload.grant_mode,
            ttl_minutes=payload.ttl_minutes,
            reason=payload.reason,
        )
        # 同步在申请人与分管领导的企微对话流中留下清晰通知
        mode_label = (
            f"临时借用 {item.ttl_minutes} 分钟"
            if item.grant_mode == "LEASE_TTL"
            else "常驻挂载"
        )
        await rt.wecom.record_conversation_pair(
            user_id=item.requester_id,
            user_name=item.requester_name,
            facade_bot="GOVERNANCE",
            chat_type="SINGLE",
            inbound_text=f"申请挂载权能球 [{item.ball_title}]（{mode_label}）：{item.reason}",
            outbound_reply=(
                f"📨【用球申请已提交 · {item.request_id}】\n"
                f"• 目标权能球：{item.ball_title} ({item.ball_id})\n"
                f"• 分管负责人：{item.custodian_name}\n"
                f"• 状态：等待分管负责人审批通过后自动挂载至你的岗位容器 ({item.requester_slot_id})。"
            ),
        )
        await rt.wecom.append_message(
            ChatMessageItem(
                msg_id=f"MSG_{uuid.uuid4().hex[:8].upper()}",
                sender_id="BOT_GOVERNANCE",
                sender_name="#2 进化与风控官",
                facade_bot="GOVERNANCE",
                chat_type="SINGLE",
                direction="OUTBOUND",
                content=(
                    f"🔔【下属用球申请待审批 · {item.request_id}】\n"
                    f"• 申请人：{item.requester_name} ({item.requester_slot_id})\n"
                    f"• 申请球：{item.ball_title} ({item.ball_id}) · {mode_label}\n"
                    f"• 申请事由：{item.reason}"
                ),
                structured_card={
                    "viewer_user_id": item.custodian_id,
                    **item.model_dump(),
                },
            )
        )
        if getattr(rt, "spider", None) is not None:
            await rt.spider.rehydrate_slot_nodes([item.requester_slot_id], reason="custody_request_proposed")
        await _sync_rt(rt)
        return {"request": item.model_dump()}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@auth_custody_router.post("/api/v1/custody/requests/{request_id}/decide")
async def decide_ball_request(
    request_id: str, payload: DecideBallRequestPayload, request: Request
) -> dict[str, Any]:
    rt, svc = _get_service(request)
    try:
        item = svc.decide_ball_request(
            actor_user_id=_acting_user(request, payload.actor_user_id),
            request_id=request_id,
            approve=payload.approve,
            comment=payload.comment,
        )
        await rt.wecom.append_message(
            ChatMessageItem(
                msg_id=f"MSG_{uuid.uuid4().hex[:8].upper()}",
                sender_id="BOT_GOVERNANCE",
                sender_name="#2 进化与风控官",
                facade_bot="GOVERNANCE",
                chat_type="SINGLE",
                direction="OUTBOUND",
                content=(
                    f"{'✅【用球申请已批准】' if payload.approve else '❌【用球申请已驳回】'} ({item.request_id})\n"
                    f"• 权能球：{item.ball_title} ({item.ball_id})\n"
                    f"• 审批人：{item.custodian_name} · {item.decision_comment}"
                ),
                structured_card={
                    "viewer_user_id": item.requester_id,
                    **item.model_dump(),
                },
            )
        )
        if payload.approve and getattr(rt, "spider", None) is not None:
            await rt.spider.rehydrate_slot_nodes([item.requester_slot_id], reason="custody_request_approved")
        await _sync_rt(rt)
        return {"request": item.model_dump()}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@auth_custody_router.post("/api/v1/custody/grant")
async def direct_grant_ball(
    payload: DirectGrantPayload, request: Request
) -> dict[str, Any]:
    rt, svc = _get_service(request)
    try:
        slot = svc.direct_grant_ball(
            leader_user_id=_acting_user(request, payload.leader_user_id),
            target_slot_id=payload.target_slot_id,
            ball_id=payload.ball_id,
            grant_mode=payload.grant_mode,
            ttl_minutes=payload.ttl_minutes,
        )
        if getattr(rt, "spider", None) is not None:
            await rt.spider.rehydrate_slot_nodes([payload.target_slot_id], reason="custody_direct_grant")
        await _sync_rt(rt)
        return {"slot": slot}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@auth_custody_router.post("/api/v1/custody/revoke")
async def revoke_ball_from_slot(
    payload: RevokeBallPayload, request: Request
) -> dict[str, Any]:
    rt, svc = _get_service(request)
    try:
        slot = svc.revoke_ball(
            leader_user_id=_acting_user(request, payload.leader_user_id),
            target_slot_id=payload.target_slot_id,
            ball_id=payload.ball_id,
        )
        await _sync_rt(rt)
        return {"slot": slot}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@auth_custody_router.post("/api/v1/custody/handover")
async def handover_slot_occupant(
    payload: SlotHandoverPayload, request: Request
) -> dict[str, Any]:
    rt, svc = _get_service(request)
    actor = get_authenticated_account(request)
    actor_uid = actor.user_id if actor is not None else payload.actor_user_id
    if not actor_uid:
        auth_acc = getattr(request.state, "authenticated_account", None)
        if auth_acc is not None:
            actor_uid = auth_acc.user_id
    if not actor_uid:
        profiles = rt.containers.list_profiles()
        actor_uid = next(
            (p.user_id for p in profiles if p.role_view == "boss"),
            next(
                (p.user_id for p in profiles if p.role_view in ("manager", "leader")),
                profiles[0].user_id if profiles else "",
            ),
        )
    try:
        normalized_mode: Literal["LEAVE_DELEGATION", "RESIGN_HANDOVER"] = (
            "LEAVE_DELEGATION"
            if payload.handover_mode in ("LEAVE_DELEGATION", "TEMP_RELIEF")
            else "RESIGN_HANDOVER"
        )
        res = svc.handover_slot_occupant(
            actor_user_id=actor_uid,
            target_slot_id=payload.target_slot_id,
            new_user_id=payload.new_user_id,
            new_person_name=payload.new_person_name,
            handover_mode=normalized_mode,
            reason=payload.reason,
            initial_password=payload.initial_password,
        )
        rehydrated_ids: list[str] = []
        if getattr(rt, "spider", None) is not None:
            rehydrated_ids = await rt.spider.rehydrate_slot_nodes(
                [res["target_slot_id"]], reason="slot_handover"
            )
        all_nodes = await rt.hot_store.list_nodes()
        for n in all_nodes:
            if n.slot_id == res["target_slot_id"]:
                n.label = res["slot_name"]
                await rt.hot_store.upsert_node(n)
                await rt.pulse_bus.publish(
                    event_type="SLOT_TRANSITIONED",
                    node_id=n.node_id,
                    subtree_root_id=n.subtree_root_id,
                    severity="INFO",
                    summary=(
                        f"🔄 岗人分离换人交接：[{res['target_slot_id']}] 由 {res['previous_user_id']} "
                        f"移交至 {res['new_person_name']} ({res['new_user_id']})，"
                        f"零损耗继承 {res['inherited_ball_count']} 颗权能球"
                    ),
                    payload={**res, "rehydrated_node_ids": rehydrated_ids},
                )
        await _sync_rt(rt)
        return {**res, "rehydrated_node_ids": rehydrated_ids}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

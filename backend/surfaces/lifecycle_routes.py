from __future__ import annotations

from typing import Any, Literal, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from core.topology_resolver import resolve_frontline_user_and_slot
from swarm.capability_lifecycle import CapabilityLifecycleEngine

lifecycle_router = APIRouter(prefix="/api/v1/lifecycle", tags=["lifecycle"])


def _get_engine(request: Request) -> tuple[Any, CapabilityLifecycleEngine]:
    rt = request.app.state.runtime
    eng = getattr(rt, "capability_lifecycle", None)
    if eng is None:
        eng = CapabilityLifecycleEngine(runtime=rt)
        setattr(rt, "capability_lifecycle", eng)
    return rt, eng


def _default_exec_uid(rt: Any) -> str:
    profiles = rt.containers.list_profiles()
    return next(
        (p.user_id for p in profiles if p.role_view == "manager"),
        next(
            (p.user_id for p in profiles if p.role_view in ("boss", "leader")),
            profiles[0].user_id if profiles else "",
        ),
    )


class IncubatePayload(BaseModel):
    actor_user_id: Optional[str] = None
    raw_policy_text: str = ""
    target_ball_id: Optional[str] = None


class ReapPayload(BaseModel):
    actor_user_id: Optional[str] = None
    action: Literal["ARCHIVE", "MERGE"]
    target_ball_id: str
    merge_into_ball_id: Optional[str] = None
    reason: str = ""


class AutoSweepPayload(BaseModel):
    actor_user_id: Optional[str] = None


class RestoreModulePayload(BaseModel):
    actor_user_id: Optional[str] = None
    ball_id: str
    target_slot_id: Optional[str] = None


@lifecycle_router.get("/catalog")
async def get_capability_catalog(
    request: Request,
    user_id: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    rt, eng = _get_engine(request)
    resolved_uid = user_id
    if not resolved_uid:
        resolved_uid, _ = resolve_frontline_user_and_slot(rt.containers)
    try:
        return eng.get_catalog(user_id=resolved_uid)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@lifecycle_router.get("/health-scan")
async def scan_lifecycle_health(
    request: Request,
    user_id: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    rt, eng = _get_engine(request)
    resolved_uid = user_id or _default_exec_uid(rt)
    try:
        return eng.scan_lifecycle_health(user_id=resolved_uid)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@lifecycle_router.post("/incubate")
async def incubate_or_split_module(
    payload: IncubatePayload, request: Request
) -> dict[str, Any]:
    rt, eng = _get_engine(request)
    actor_uid = payload.actor_user_id or _default_exec_uid(rt)
    try:
        res = await eng.incubate_or_split(
            actor_user_id=actor_uid,
            raw_policy_text=payload.raw_policy_text,
            target_ball_id=payload.target_ball_id,
        )
        if hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@lifecycle_router.post("/reap")
async def reap_or_merge_module(
    payload: ReapPayload, request: Request
) -> dict[str, Any]:
    rt, eng = _get_engine(request)
    actor_uid = payload.actor_user_id or _default_exec_uid(rt)
    try:
        res = await eng.reap_module(
            actor_user_id=actor_uid,
            action=payload.action,
            target_ball_id=payload.target_ball_id,
            merge_into_ball_id=payload.merge_into_ball_id,
            reason=payload.reason,
        )
        if hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@lifecycle_router.post("/auto-sweep")
async def auto_sweep_lifecycle(
    payload: AutoSweepPayload, request: Request
) -> dict[str, Any]:
    rt, eng = _get_engine(request)
    actor_uid = payload.actor_user_id or _default_exec_uid(rt)
    try:
        res = await eng.auto_reap_sweep(actor_user_id=actor_uid)
        if hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@lifecycle_router.post("/restore")
async def restore_archived_module(
    payload: RestoreModulePayload, request: Request
) -> dict[str, Any]:
    rt, eng = _get_engine(request)
    actor_uid = payload.actor_user_id or _default_exec_uid(rt)
    try:
        res = await eng.restore_module(
            actor_user_id=actor_uid,
            ball_id=payload.ball_id,
            target_slot_id=payload.target_slot_id,
        )
        if hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

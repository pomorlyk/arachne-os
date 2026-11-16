from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from core.topology_resolver import resolve_frontline_user_and_slot
from swarm.memory_distiller import EpisodicMemoryDistiller

memory_distiller_router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


def _get_distiller(request: Request) -> tuple[Any, EpisodicMemoryDistiller]:
    rt = getattr(request.app.state, "runtime", None)
    if rt is not None:
        distiller = getattr(rt, "memory_distiller", None)
        if distiller is None:
            distiller = EpisodicMemoryDistiller(state=rt)
            setattr(rt, "memory_distiller", distiller)
        return rt, distiller

    distiller = getattr(request.app.state, "memory_distiller", None)
    if distiller is None:
        distiller = EpisodicMemoryDistiller()
        setattr(request.app.state, "memory_distiller", distiller)
    return None, distiller


def _resolve_target_slot(rt: Any, explicit_slot_id: Optional[str]) -> str:
    if explicit_slot_id:
        return explicit_slot_id
    if rt is not None and hasattr(rt, "containers"):
        _, sid = resolve_frontline_user_and_slot(rt.containers)
        if sid:
            return sid
    return "SLOT_BOSS"


class DistillSlotMemoryPayload(BaseModel):
    slot_id: Optional[str] = None
    auto_upgrade_balls: bool = True
    mint_candidate_ball: bool = True


class CandidateBallDecisionPayload(BaseModel):
    approve: bool = True
    reviewer_user_id: str = "leader"
    comment: str = ""
    role_view: str = "leader"


class ZeroLossHandoverPayload(BaseModel):
    slot_id: Optional[str] = None
    outgoing_user_id: Optional[str] = None
    incoming_user_name: str = "新接替业务专员"
    incoming_user_id: Optional[str] = None
    auto_distill_first: bool = True


@memory_distiller_router.post("/distill")
async def distill_slot_memory_endpoint(
    payload: DistillSlotMemoryPayload, request: Request
) -> dict[str, Any]:
    rt, distiller = _get_distiller(request)
    target_sid = _resolve_target_slot(rt, payload.slot_id)
    try:
        res = await distiller.distill_slot_memory(
            slot_id=target_sid,
            auto_upgrade_balls=payload.auto_upgrade_balls,
            mint_candidate_ball=payload.mint_candidate_ball,
        )
        if rt is not None and hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@memory_distiller_router.post("/zero-loss-handover")
async def zero_loss_handover_endpoint(
    payload: ZeroLossHandoverPayload, request: Request
) -> dict[str, Any]:
    rt, distiller = _get_distiller(request)
    target_sid = _resolve_target_slot(rt, payload.slot_id)
    try:
        res = await distiller.execute_zero_loss_handover(
            slot_id=target_sid,
            outgoing_user_id=payload.outgoing_user_id,
            incoming_user_name=payload.incoming_user_name,
            incoming_user_id=payload.incoming_user_id,
            auto_distill_first=payload.auto_distill_first,
        )
        if rt is not None and hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@memory_distiller_router.get("/crystals")
async def list_memory_crystals_endpoint(
    request: Request,
    slot_id: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    _, distiller = _get_distiller(request)
    return distiller.list_crystals(slot_id=slot_id)


@memory_distiller_router.get("/candidate-balls")
async def list_candidate_balls_endpoint(
    request: Request,
    slot_id: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    _, distiller = _get_distiller(request)
    return distiller.list_candidate_balls(slot_id=slot_id)


@memory_distiller_router.post("/candidate-balls/{ball_id}/decide")
async def decide_candidate_ball_endpoint(
    ball_id: str,
    payload: CandidateBallDecisionPayload,
    request: Request,
) -> dict[str, Any]:
    if payload.role_view not in ("boss", "manager", "leader"):
        raise HTTPException(
            status_code=403,
            detail="仅分管组长、部门经理或总控有权审核挂载蒸馏候选知识球",
        )
    rt, distiller = _get_distiller(request)
    try:
        res = distiller.decide_candidate_ball(
            ball_id=ball_id,
            approve=payload.approve,
            reviewer_user_id=payload.reviewer_user_id,
            comment=payload.comment,
        )
        if rt is not None and hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

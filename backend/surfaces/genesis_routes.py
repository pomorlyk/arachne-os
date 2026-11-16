from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel

from core.security import get_authenticated_account
from swarm.genesis_fission import EnterpriseGenesisAndFissionEngine

genesis_router = APIRouter(tags=["enterprise_genesis_and_fission"])


def _get_engine(request: Request) -> tuple[Any, EnterpriseGenesisAndFissionEngine]:
    rt = request.app.state.runtime
    engine = getattr(rt, "genesis_engine", None)
    if engine is None:
        engine = EnterpriseGenesisAndFissionEngine(runtime=rt)
        setattr(rt, "genesis_engine", engine)
    return rt, engine


class DeployEnterprisePayload(BaseModel):
    enterprise_name: str
    business_description: str
    reset_existing: bool = False


class DecomposeOrSplitPayload(BaseModel):
    actor_user_id: Optional[str] = None
    raw_policy_text: str = ""
    target_ball_id: Optional[str] = None


class AutonomousPatrolPayload(BaseModel):
    actor_user_id: Optional[str] = None


def _resolve_boss_uid(rt: Any) -> str:
    profiles = rt.containers.list_profiles()
    return next((p.user_id for p in profiles if p.role_view == "boss"), profiles[0].user_id if profiles else "boss_lin")


@genesis_router.get("/api/v1/genesis/templates")
async def get_genesis_templates(request: Request) -> dict[str, Any]:
    _, engine = _get_engine(request)
    templates = engine.list_templates()
    return {
        "count": len(templates),
        "templates": templates,
    }


@genesis_router.post("/api/v1/genesis/deploy-enterprise")
async def deploy_enterprise_blueprint(
    payload: DeployEnterprisePayload, request: Request
) -> dict[str, Any]:
    rt, engine = _get_engine(request)
    account = get_authenticated_account(request)
    try:
        res = await engine.deploy_enterprise_blueprint(
            enterprise_name=payload.enterprise_name,
            business_description=payload.business_description,
            reset_existing=payload.reset_existing,
            actor_user_id=account.user_id if account is not None else None,
        )
        if hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return res
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@genesis_router.post("/api/v1/genesis/decompose")
async def decompose_or_split_balls(
    payload: DecomposeOrSplitPayload, request: Request
) -> dict[str, Any]:
    rt, engine = _get_engine(request)
    actor_uid = payload.actor_user_id or _resolve_boss_uid(rt)
    try:
        res = await engine.decompose_or_split_balls(
            actor_user_id=actor_uid,
            raw_policy_text=payload.raw_policy_text,
            target_ball_id=payload.target_ball_id,
        )
        if hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@genesis_router.post("/api/v1/genesis/autonomous-patrol")
async def trigger_autonomous_patrol(
    request: Request,
    payload: Optional[AutonomousPatrolPayload] = Body(default=None),
) -> dict[str, Any]:
    rt, engine = _get_engine(request)
    actor_uid = payload.actor_user_id if payload else None
    res = await engine.run_autonomous_agency_patrol(actor_user_id=actor_uid)
    if hasattr(rt, "sync_persistence"):
        await rt.sync_persistence()
    return res

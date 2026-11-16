from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.security import require_roles
from swarm.skill_pipeline_composer import SkillPipelineComposer

skill_pipeline_router = APIRouter(prefix="/api/v1/pipelines", tags=["pipelines"])


def _get_composer(request: Request) -> tuple[Any, SkillPipelineComposer]:
    rt = getattr(request.app.state, "runtime", None)
    if rt is not None:
        composer = getattr(rt, "skill_pipeline_composer", None)
        if composer is None:
            composer = SkillPipelineComposer(state=rt)
            setattr(rt, "skill_pipeline_composer", composer)
        elif getattr(composer, "_state", None) is None:
            composer.bind_state(rt)
        return rt, composer

    composer = getattr(request.app.state, "skill_pipeline_composer", None)
    if composer is None:
        composer = SkillPipelineComposer()
        setattr(request.app.state, "skill_pipeline_composer", composer)
    return None, composer


class ComposePipelinePayload(BaseModel):
    pipeline_title: str = ""
    source_skill_ball_ids: Optional[list[str]] = None
    pipeline_instruction: str = ""
    target_slot_id: Optional[str] = None
    test_payload: Optional[dict[str, Any]] = None
    preset_id: Optional[str] = None


class ExecutePipelinePayload(BaseModel):
    sandbox_preview: bool = False
    pipeline_id: Optional[str] = None
    ball_id: Optional[str] = None
    master_ball_id: Optional[str] = None
    preset_id: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    input_payload: Optional[dict[str, Any]] = None
    test_payload: Optional[dict[str, Any]] = None


@skill_pipeline_router.get("/presets")
async def list_pipeline_presets(request: Request) -> dict[str, Any]:
    _, composer = _get_composer(request)
    presets = composer.get_pipeline_presets()
    return {
        "count": len(presets),
        "presets": presets,
    }


@skill_pipeline_router.post("/compose")
async def compose_and_verify_pipeline_endpoint(
    payload: ComposePipelinePayload, request: Request
) -> dict[str, Any]:
    actor = require_roles(request, "manager", "boss")
    rt, composer = _get_composer(request)
    proposer_id = actor.user_id if actor is not None else next(
        (p.user_id for p in rt.containers._profiles.values() if p.role_view in ("manager", "boss")), None
    ) if rt is not None else None
    try:
        res = composer.compose_and_verify_pipeline(
            pipeline_title=payload.pipeline_title,
            source_skill_ball_ids=payload.source_skill_ball_ids,
            pipeline_instruction=payload.pipeline_instruction,
            target_slot_id=payload.target_slot_id,
            test_payload=payload.test_payload,
            preset_id=payload.preset_id,
            proposer_id=proposer_id,
        )
        if rt is not None and hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return dict(res)
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@skill_pipeline_router.post("/execute")
async def execute_pipeline_endpoint(
    payload: ExecutePipelinePayload, request: Request
) -> dict[str, Any]:
    actor = require_roles(request, "manager", "boss")
    rt, composer = _get_composer(request)
    proposer_id = actor.user_id if actor is not None else next(
        (p.user_id for p in rt.containers._profiles.values() if p.role_view in ("manager", "boss")), None
    ) if rt is not None else None
    effective_payload = next((value for value in (payload.payload, payload.input_payload, payload.test_payload)
                              if value is not None), None)
    effective_ball_id = payload.ball_id or payload.master_ball_id
    try:
        res = composer.execute_pipeline(
            pipeline_id=payload.pipeline_id,
            ball_id=effective_ball_id,
            preset_id=payload.preset_id,
            payload=effective_payload,
            sandbox_preview=payload.sandbox_preview,
            proposer_id=proposer_id,
        )
        if rt is not None and hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return dict(res)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@skill_pipeline_router.get("/history")
async def get_pipeline_history_endpoint(request: Request) -> dict[str, Any]:
    _, composer = _get_composer(request)
    return composer.get_history()

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from swarm.dag_mission_engine import DAGMissionEngine

dag_mission_router = APIRouter(prefix="/api/v1/missions", tags=["missions"])


def _get_mission_engine(request: Request) -> tuple[Any, DAGMissionEngine]:
    rt = request.app.state.runtime
    engine = getattr(rt, "dag_mission_engine", None)
    if engine is None:
        engine = DAGMissionEngine(state=rt)
        setattr(rt, "dag_mission_engine", engine)
    elif getattr(engine, "_state", None) is None:
        engine.bind_state(rt)
    return rt, engine


class ExecuteDAGMissionPayload(BaseModel):
    mission_title: str = "跨部门联合特战队行动"
    mission_brief: str = ""
    preset_id: Optional[str] = None
    initiator_account_id: Optional[str] = None
    max_debate_rounds: int = Field(default=2, ge=1, le=6)
    auto_execute_skills: bool = True
    metrics: dict[str, Any] = Field(default_factory=dict)
    requirements: list[str] = Field(default_factory=list)


class AdversarialDebatePayload(BaseModel):
    topic: str
    proposer_slot_id: Optional[str] = None
    reviewer_slot_id: Optional[str] = None
    arbiter_slot_id: Optional[str] = "SLOT_BOSS"
    rounds: int = Field(default=3, ge=1, le=6)


@dag_mission_router.get("/presets")
async def list_mission_presets(request: Request) -> dict[str, Any]:
    _, engine = _get_mission_engine(request)
    presets = engine.get_mission_presets()
    return {
        "count": len(presets),
        "presets": presets,
    }


@dag_mission_router.post("/execute-dag")
async def execute_dag_mission_endpoint(
    payload: ExecuteDAGMissionPayload, request: Request
) -> dict[str, Any]:
    rt, engine = _get_mission_engine(request)
    try:
        res = await engine.execute_dag_mission(
            mission_title=payload.mission_title,
            mission_brief=payload.mission_brief,
            initiator_account_id=payload.initiator_account_id,
            max_debate_rounds=payload.max_debate_rounds,
            auto_execute_skills=payload.auto_execute_skills,
            preset_id=payload.preset_id,
            metrics=payload.metrics or None,
            requirements=payload.requirements or None,
        )
        if hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@dag_mission_router.post("/adversarial-debate")
async def run_adversarial_debate_endpoint(
    payload: AdversarialDebatePayload, request: Request
) -> dict[str, Any]:
    rt, engine = _get_mission_engine(request)
    try:
        res = await engine.run_adversarial_debate(
            topic=payload.topic,
            proposer_slot_id=payload.proposer_slot_id,
            reviewer_slot_id=payload.reviewer_slot_id,
            arbiter_slot_id=payload.arbiter_slot_id,
            rounds=payload.rounds,
        )
        if hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@dag_mission_router.get("/history")
async def get_missions_and_debates_history(request: Request) -> dict[str, Any]:
    _, engine = _get_mission_engine(request)
    return engine.get_history()

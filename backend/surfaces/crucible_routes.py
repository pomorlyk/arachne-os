from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from swarm.red_blue_crucible import RedBlueCrucible

crucible_router = APIRouter(prefix="/api/v1/crucible", tags=["crucible"])


def _get_crucible(request: Request) -> tuple[Any, RedBlueCrucible]:
    rt = getattr(request.app.state, "runtime", None)
    if rt is not None:
        crucible = getattr(rt, "red_blue_crucible", None) or getattr(
            rt, "crucible", None
        )
        if crucible is None:
            crucible = RedBlueCrucible(state=rt)
            setattr(rt, "red_blue_crucible", crucible)
            setattr(rt, "crucible", crucible)
        return rt, crucible

    crucible = getattr(request.app.state, "red_blue_crucible", None)
    if crucible is None:
        crucible = RedBlueCrucible()
        setattr(request.app.state, "red_blue_crucible", crucible)
    return None, crucible


class StressTestSkillPayload(BaseModel):
    ball_id: str
    attack_intensity: Literal["STANDARD", "EXTREME"] = "EXTREME"
    auto_heal: bool = True
    max_generations: int = Field(default=3, ge=1, le=5)
    vulnerable_code: Optional[str] = None
    skill_title: Optional[str] = None


class RedlinePenetrationPayload(BaseModel):
    target_slot_id: str
    attack_count: int = Field(default=4, ge=1, le=5)
    auto_remediate: bool = False


@crucible_router.post("/stress-test-skill")
async def stress_test_and_heal_skill_endpoint(
    payload: StressTestSkillPayload, request: Request
) -> dict[str, Any]:
    rt, crucible = _get_crucible(request)
    try:
        res = await crucible.stress_test_and_heal_skill(
            ball_id=payload.ball_id,
            attack_intensity=payload.attack_intensity,
            auto_heal=payload.auto_heal,
            max_generations=payload.max_generations,
            vulnerable_code=payload.vulnerable_code,
            skill_title=payload.skill_title,
        )
        if rt is not None and hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@crucible_router.post("/redline-penetration")
async def redline_penetration_endpoint(
    payload: RedlinePenetrationPayload, request: Request
) -> dict[str, Any]:
    rt, crucible = _get_crucible(request)
    try:
        res = await crucible.run_redline_penetration_audit(
            target_slot_id=payload.target_slot_id,
            attack_count=payload.attack_count,
            auto_remediate=payload.auto_remediate,
        )
        if rt is not None and hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@crucible_router.get("/reports")
async def list_crucible_reports_endpoint(request: Request) -> dict[str, Any]:
    _, crucible = _get_crucible(request)
    return crucible.list_reports()

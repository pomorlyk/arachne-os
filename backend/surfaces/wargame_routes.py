from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.simulation_workspace import get_simulation_runtime
from swarm.monte_carlo_wargame import MonteCarloWargameEngine

wargame_router = APIRouter(prefix="/api/v1/wargame", tags=["wargame"])


async def _get_wargame_engine(request: Request) -> tuple[Any, MonteCarloWargameEngine]:
    rt = await get_simulation_runtime(request.app.state.runtime)
    return rt, rt.wargame_engine


class WargameSimulatePayload(BaseModel):
    scenario_id_or_custom: Optional[str] = None
    scenario_id: Optional[str] = None
    custom_scenario: Optional[str] = None
    custom_title: Optional[str] = None
    custom_description: Optional[str] = None
    shock_parameters: Optional[dict[str, float]] = None
    horizon_days: int = Field(default=30, ge=7, le=180)
    monte_carlo_paths: int = Field(default=20, ge=5, le=100)
    auto_forge_defensive_balls: bool = True


@wargame_router.get("/scenarios")
async def list_black_swan_scenarios(request: Request) -> dict[str, Any]:
    scenarios = MonteCarloWargameEngine().get_black_swan_scenarios()
    return {"count": len(scenarios), "scenarios": scenarios}


@wargame_router.post("/simulate")
async def run_wargame_simulation_endpoint(
    payload: WargameSimulatePayload, request: Request
) -> dict[str, Any]:
    rt, engine = await _get_wargame_engine(request)
    target_scenario = (payload.scenario_id_or_custom or payload.scenario_id
                       or payload.custom_scenario or "swan_raw_material_surge")
    try:
        async with rt.simulation_operation_lock:
            return await engine.run_wargame_simulation(
                scenario_id_or_custom=target_scenario, horizon_days=payload.horizon_days,
                monte_carlo_paths=payload.monte_carlo_paths,
                auto_forge_defensive_balls=payload.auto_forge_defensive_balls,
                custom_title=payload.custom_title, custom_description=payload.custom_description,
                shock_parameters=payload.shock_parameters)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@wargame_router.get("/history")
async def get_wargame_history_endpoint(request: Request) -> dict[str, Any]:
    rt, engine = await _get_wargame_engine(request)
    return {**engine.get_history(), "run_id": rt.simulation_scope["run_id"], "scope": rt.simulation_scope}

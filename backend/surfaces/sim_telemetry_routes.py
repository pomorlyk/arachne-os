from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Request
from core.simulation_workspace import get_simulation_runtime

sim_telemetry_router = APIRouter(tags=["simulation_and_telemetry"])


def _rt(request: Request) -> Any:
    return request.app.state.runtime


@sim_telemetry_router.get("/api/v1/simulation/status")
async def get_simulation_status(request: Request) -> dict[str, Any]:
    rt = await get_simulation_runtime(_rt(request))
    return rt.day_sim.get_status()


@sim_telemetry_router.post("/api/v1/simulation/step")
async def step_day_simulation(request: Request) -> dict[str, Any]:
    rt = await get_simulation_runtime(_rt(request))
    async with rt.simulation_operation_lock:
        return await rt.day_sim.step_next()


@sim_telemetry_router.post("/api/v1/simulation/run-full-day")
async def run_full_day_simulation(request: Request) -> dict[str, Any]:
    rt = await get_simulation_runtime(_rt(request))
    async with rt.simulation_operation_lock:
        return await rt.day_sim.run_full_day()


@sim_telemetry_router.post("/api/v1/simulation/reset")
async def reset_day_simulation(request: Request) -> dict[str, Any]:
    rt = await get_simulation_runtime(_rt(request), reset=True)
    return rt.day_sim.get_status()


@sim_telemetry_router.get("/api/v1/llm/telemetry")
async def get_llm_telemetry(request: Request) -> dict[str, Any]:
    return _rt(request).llm_gateway.get_telemetry_snapshot()

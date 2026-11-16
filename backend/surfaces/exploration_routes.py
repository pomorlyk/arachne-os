from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from swarm.cave_explorer import CaveExplorationEngine

exploration_router = APIRouter(tags=["cave_exploration"])


def _get_engine(request: Request) -> tuple[Any, CaveExplorationEngine]:
    rt = request.app.state.runtime
    engine = getattr(rt, "cave_explorer", None)
    if engine is None:
        engine = CaveExplorationEngine(runtime=rt)
        setattr(rt, "cave_explorer", engine)
    return rt, engine


class EmptyShellPayload(BaseModel):
    enterprise_name: str = "待探索企业"


class ScoutPayload(BaseModel):
    enterprise_name: str
    raw_org_material: str


class PlantTorchPayload(BaseModel):
    target_node_id: str
    raw_sop_text: str = ""


@exploration_router.get("/api/v1/exploration/map")
async def get_exploration_map(request: Request) -> dict[str, Any]:
    _, engine = _get_engine(request)
    return await engine.get_cave_map_state()


@exploration_router.post("/api/v1/exploration/empty-shell")
async def reset_to_empty_shell(
    payload: EmptyShellPayload, request: Request
) -> dict[str, Any]:
    rt, engine = _get_engine(request)
    res = await engine.reset_to_empty_shell(
        enterprise_name=payload.enterprise_name
    )
    if hasattr(rt, "sync_persistence"):
        await rt.sync_persistence(override_mode=res.get("mode"))
    return res


@exploration_router.post("/api/v1/exploration/scout")
async def scout_organization(
    payload: ScoutPayload, request: Request
) -> dict[str, Any]:
    rt, engine = _get_engine(request)
    try:
        res = await engine.scout_organization_structure(
            enterprise_name=payload.enterprise_name,
            raw_org_material=payload.raw_org_material,
        )
        if hasattr(rt, "sync_persistence"):
            await rt.sync_persistence(override_mode=res.get("mode"))
        return res
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@exploration_router.post("/api/v1/exploration/plant-torch")
async def plant_torch_on_node(
    payload: PlantTorchPayload, request: Request
) -> dict[str, Any]:
    rt, engine = _get_engine(request)
    try:
        res = await engine.plant_torch_and_weave(
            target_node_id=payload.target_node_id,
            raw_sop_text=payload.raw_sop_text,
        )
        if hasattr(rt, "sync_persistence"):
            await rt.sync_persistence(override_mode=res.get("mode"))
        return res
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

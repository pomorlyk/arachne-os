from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.enterprise_ingestor import EnterpriseIngestor
from core.snapshot_timemachine import SnapshotTimeMachine
from core.security import get_authenticated_account

ingest_snapshot_router = APIRouter(tags=["ingest-and-snapshots"])


def _get_services(
    request: Request,
) -> tuple[Any, EnterpriseIngestor, SnapshotTimeMachine]:
    rt = request.app.state.runtime
    ingestor = getattr(rt, "enterprise_ingestor", None)
    if ingestor is None:
        ingestor = EnterpriseIngestor(state=rt)
        setattr(rt, "enterprise_ingestor", ingestor)
    timemachine = getattr(rt, "snapshot_timemachine", None)
    if timemachine is None:
        timemachine = SnapshotTimeMachine(state=rt)
        setattr(rt, "snapshot_timemachine", timemachine)
    return rt, ingestor, timemachine


class IngestDocumentPayload(BaseModel):
    doc_title: str = "企业业务数据台账"
    doc_format: Literal["CSV", "JSON", "CONTRACT_MD", "AUTO"] = "AUTO"
    raw_content: str = ""
    target_department: str = ""
    target_slot_id: Optional[str] = None
    auto_forge_query_skill: bool = True
    sample_id: Optional[str] = None


class SaveSnapshotPayload(BaseModel):
    label: str
    note: str = ""


class RestoreSnapshotPayload(BaseModel):
    snapshot_id: str


@ingest_snapshot_router.get("/api/v1/ingest/samples")
async def list_ingestion_samples(request: Request) -> dict[str, Any]:
    _, ingestor, _ = _get_services(request)
    samples = ingestor.get_ingestion_samples()
    return {
        "count": len(samples),
        "samples": samples,
    }


@ingest_snapshot_router.post("/api/v1/ingest/document")
async def ingest_enterprise_document(
    payload: IngestDocumentPayload, request: Request
) -> dict[str, Any]:
    rt, ingestor, _ = _get_services(request)
    try:
        res = ingestor.ingest_enterprise_document(
            doc_title=payload.doc_title,
            doc_format=payload.doc_format,
            raw_content=payload.raw_content,
            target_department=payload.target_department,
            target_slot_id=payload.target_slot_id,
            auto_forge_query_skill=payload.auto_forge_query_skill,
            sample_id=payload.sample_id,
        )
        if hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return res
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@ingest_snapshot_router.get("/api/v1/snapshots/list")
async def list_cluster_snapshots(request: Request) -> dict[str, Any]:
    _, _, timemachine = _get_services(request)
    snapshots = timemachine.list_snapshots()
    return {
        "count": len(snapshots),
        "snapshots": snapshots,
    }


@ingest_snapshot_router.post("/api/v1/snapshots/save")
async def save_cluster_snapshot(
    payload: SaveSnapshotPayload, request: Request
) -> dict[str, Any]:
    _, _, timemachine = _get_services(request)
    try:
        saved = await timemachine.save_full_snapshot(
            label=payload.label, note=payload.note
        )
        return {
            **saved,
            "snapshot": saved,
        }
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@ingest_snapshot_router.post("/api/v1/snapshots/restore")
async def restore_cluster_snapshot(
    payload: RestoreSnapshotPayload, request: Request
) -> dict[str, Any]:
    rt, _, timemachine = _get_services(request)
    account = get_authenticated_account(request)
    try:
        restored = await timemachine.restore_full_snapshot(
            snapshot_id=payload.snapshot_id,
            actor_user_id=account.user_id if account is not None else None,
        )
        if hasattr(rt, "sync_persistence"):
            await rt.sync_persistence()
        return {
            **restored,
            "snapshot": restored,
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@ingest_snapshot_router.delete("/api/v1/snapshots/{snapshot_id}")
async def delete_cluster_snapshot(snapshot_id: str, request: Request) -> dict[str, Any]:
    _, _, timemachine = _get_services(request)
    try:
        return timemachine.delete_snapshot(snapshot_id=snapshot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

"""Independent, offline rehearsal runtimes and durable run checkpoints.

Only this module constructs rehearsal state. No simulator uses the active runtime's
callbacks, database connection, ledger or mutable registries.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any
import uuid


def _workspace_key(rt: Any) -> str:
    cave = getattr(rt, "cave_explorer", None)
    return str(getattr(cave, "workspace_id", "") or getattr(rt, "workspace_id", "") or hashlib.sha256(
        str(rt.settings.sqlite_db_url).encode()).hexdigest()[:20])


def _index_path(rt: Any) -> Path:
    key = hashlib.sha256(_workspace_key(rt).encode()).hexdigest()[:24]
    return Path(rt.settings.sandbox_workspace_dir) / "simulations" / key / "active.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    from core.runtime_transactions import write_private_json
    write_private_json(path, json.loads(json.dumps(payload, ensure_ascii=False, default=str)))


def _offline_payload(payload: dict[str, Any]) -> dict[str, Any]:
    # Deep-copy first: clearing a nested callback/session map must never clear live state.
    result = json.loads(json.dumps(payload, default=lambda v: v.model_dump() if hasattr(v, "model_dump") else str(v)))
    result.pop("security_state", None)
    result.pop("private_connector_state", None)
    for key in ("passwords", "sessions", "connector_state", "connectors"):
        if key in result:
            result[key] = {}
    auth = result.get("auth_payload") or result.get("auth_state")
    if isinstance(auth, dict):
        auth["passwords"] = {}
        auth["sessions"] = {}
    meta = result.get("meta_payload")
    if isinstance(meta, dict):
        meta["sessions"] = {}
        meta["connector_state"] = {}
    return result


def _copy_workspace_files(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        if entry.name in {"simulations", "runtime_transaction.json", "__pycache__"} or entry.suffix == ".pyc":
            continue
        target = destination / entry.name
        if entry.is_symlink():
            # Never preserve a link capable of reaching the active workspace.
            if entry.is_file():
                target.write_bytes(entry.read_bytes())
            continue
        if entry.is_dir():
            _copy_workspace_files(entry, target)
        elif entry.is_file():
            shutil.copy2(entry, target)


async def persist_simulation_runtime(rt: Any) -> None:
    if not getattr(rt, "simulation_scope", None):
        return
    await rt.pulse_bus.drain_background_tasks()
    async with rt.simulation_checkpoint_lock:
        await rt.sync_persistence()
        state = _offline_payload(rt.export_runtime_state())
        state["hot_state"] = await rt.hot_store.export_global_state()
        _write_json(rt.simulation_run_dir / "checkpoint.json", {
            "scope": rt.simulation_scope,
            "runtime_state": state,
            "day_sim": rt.day_sim.export_state(),
            "wargame_history": getattr(getattr(rt, "wargame_engine", None), "_history", []),
        })


async def close_simulation_runtime(parent: Any) -> None:
    clone = getattr(parent, "simulation_runtime", None)
    if clone is not None:
        async with clone.simulation_operation_lock:
            async with clone.day_sim._step_lock:
                await persist_simulation_runtime(clone)
                await clone.hot_store.close()
        parent.simulation_runtime = None


@asynccontextmanager
async def _parent_read_scope(parent: Any):
    from core.runtime_transactions import active_mutation
    transaction = getattr(parent, "_transactions", None)
    active = active_mutation.get()
    if transaction is None or (active is not None and active[0] is parent):
        yield
    else:
        # A consistent read shares the writer's mutex, without creating its journal.
        async with transaction.lock:
            yield


async def get_simulation_runtime(parent: Any, *, reset: bool = False) -> Any:
    if getattr(parent, "simulation_scope", None):
        return parent
    lock = getattr(parent, "simulation_lock", None)
    if lock is None:
        lock = parent.simulation_lock = asyncio.Lock()
    async with _parent_read_scope(parent):
        async with lock:
            key = _workspace_key(parent)
            existing = getattr(parent, "simulation_runtime", None)
            if existing is not None and not reset and existing.simulation_scope["parent_workspace_id"] == key:
                return existing
            if existing is not None:
                # Wait for any in-flight step before closing its private DB.
                async with existing.simulation_operation_lock:
                    async with existing.day_sim._step_lock:
                        await persist_simulation_runtime(existing)
                        await existing.hot_store.close()
                parent.simulation_runtime = None

            index = _index_path(parent)
            scope = None
            checkpoint = None
            if not reset and index.exists():
                scope = json.loads(index.read_text(encoding="utf-8"))
                candidate_dir = index.parent / scope["run_id"]
                cp_path = candidate_dir / "checkpoint.json"
                if cp_path.exists():
                    checkpoint = json.loads(cp_path.read_text(encoding="utf-8"))
                else:
                    scope = None
            if scope is None:
                scope = {
                    "mode": "SIMULATION", "isolated": True,
                    "run_id": f"SIM_{uuid.uuid4().hex}",
                    "parent_workspace_id": key,
                    "parent_workspace_epoch": getattr(getattr(parent, "cave_explorer", None), "workspace_epoch", ""),
                }
            run_dir = index.parent / scope["run_id"]
            run_dir.mkdir(parents=True, exist_ok=True)
            if checkpoint is None:
                vault_target = run_dir / "vault"
                if Path(parent.settings.vault_storage_dir).exists():
                    shutil.copytree(parent.settings.vault_storage_dir, vault_target, dirs_exist_ok=True)
                _copy_workspace_files(Path(parent.settings.sandbox_workspace_dir), run_dir / "sandbox")
                source = _offline_payload(parent.export_runtime_state())
                source["hot_state"] = await parent.hot_store.export_global_state()
                scope["parent_revision"] = hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest()
            else:
                source = checkpoint["runtime_state"]
            settings = parent.settings.model_copy(update={
                "sqlite_db_url": f"sqlite+aiosqlite:///{run_dir / 'hot.db'}",
                "vault_storage_dir": run_dir / "vault",
                "sandbox_workspace_dir": run_dir / "sandbox",
                "llm_api_key": "", "wecom_adapter_mode": "LOCAL_SIMULATOR",
                "wecom_bot_id": "", "wecom_bot_secret": "", "wecom_webhook_key": "",
                "connector_hmac_secret": "simulation-offline",
                "bootstrap_password": f"offline-{uuid.uuid4().hex}",
                "enforce_bearer_auth": True,
            })
            from surfaces.api_routes import create_arachne_runtime
            from core.external_connectors import ExternalConnectorRegistry
            from swarm.monte_carlo_wargame import MonteCarloWargameEngine
            clone = await create_arachne_runtime(settings)
            try:
                await clone.restore_runtime_state(source, preserve_security=False)
                clone.connectors = ExternalConnectorRegistry(settings)
                clone.connectors.bind_runtime(clone)
                clone.simulation_scope = scope
                clone.simulation_run_dir = run_dir
                clone.simulation_checkpoint_lock = asyncio.Lock()
                clone.simulation_operation_lock = asyncio.Lock()
                clone.wargame_engine = MonteCarloWargameEngine(state=clone)
                clone.day_sim.reset_day()
                if checkpoint:
                    clone.day_sim.restore_state(checkpoint.get("day_sim", {}))
                    clone.day_sim.mark_interrupted()
                    clone.wargame_engine._history = checkpoint.get("wargame_history", [])
                parent.simulation_runtime = clone
                await persist_simulation_runtime(clone)
                _write_json(index, scope)
                return clone
            except BaseException:
                if getattr(parent, "simulation_runtime", None) is clone:
                    parent.simulation_runtime = None
                await clone.hot_store.close()
                raise

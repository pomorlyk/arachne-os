from __future__ import annotations

from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Any

from core.schemas import CapabilityBall, ChatMessageItem, DualEmployeeProfile, UnitSlot


MODULE_FACTORIES = {
    "dag_mission_engine": ("swarm.dag_mission_engine", "DAGMissionEngine"),
    "wargame_engine": ("swarm.monte_carlo_wargame", "MonteCarloWargameEngine"),
    "red_blue_crucible": ("swarm.red_blue_crucible", "RedBlueCrucible"),
    "memory_distiller": ("swarm.memory_distiller", "EpisodicMemoryDistiller"),
    "skill_pipeline_composer": (
        "swarm.skill_pipeline_composer",
        "SkillPipelineComposer",
    ),
}
HISTORY_FIELDS = {
    "red_blue_crucible": ("_skill_reports", "_penetration_audits"),
    "memory_distiller": ("_distillation_runs", "_handover_records", "_candidate_balls"),
    "skill_pipeline_composer": ("_composed_pipelines", "_execution_history"),
    "wargame_engine": ("_history",),
}


def export_modules(runtime: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in ("spider", "scoring", "board", "arena", "day_sim", *MODULE_FACTORIES):
        module = getattr(runtime, name, None)
        if module is None:
            continue
        if hasattr(module, "export_state"):
            result[name] = module.export_state()
        elif name in HISTORY_FIELDS:
            result[name] = {
                key: deepcopy(getattr(module, key))
                for key in HISTORY_FIELDS[name]
                if hasattr(module, key)
            }
        if name == "memory_distiller":
            result[name]["crystals"] = [
                c.model_dump(mode="json") for c in module._all_crystals
            ]
    return result


def restore_modules(runtime: Any, states: dict[str, Any]) -> None:
    for name in MODULE_FACTORIES:
        if name not in states and hasattr(runtime, name):
            delattr(runtime, name)
    for name, state in states.items():
        module = getattr(runtime, name, None)
        if module is None and name in MODULE_FACTORIES:
            path, class_name = MODULE_FACTORIES[name]
            module = getattr(import_module(path), class_name)(state=runtime)
            setattr(runtime, name, module)
        if module is None:
            continue
        if hasattr(module, "restore_state"):
            module.restore_state(state)
        else:
            for key in HISTORY_FIELDS.get(name, ()):
                if key in state:
                    setattr(module, key, deepcopy(state[key]))
        if name == "memory_distiller":
            from swarm.memory_distiller import MemoryCrystal

            module._all_crystals = [
                MemoryCrystal(**raw) for raw in state.get("crystals", [])
            ]
            module._crystals_by_slot = {}
            for crystal in module._all_crystals:
                module._crystals_by_slot.setdefault(crystal.slot_id, []).append(crystal)


def export_runtime_state(runtime: Any) -> dict[str, Any]:
    records = []
    for item in runtime.particles.export_balls_with_source(
        runtime.settings.sandbox_workspace_dir
    ):
        record = item["ball"].model_dump(mode="json")
        record["source_code"] = item.get("executable_code_source", "")
        records.append(record)
    auth = runtime.auth_custody
    connector_state = runtime.connectors.export_state() if runtime.connectors else {}
    for binding in connector_state.get("bindings", []):
        binding.pop("hmac_secret_override", None)
    return {
        "schema_version": 1,
        "unit_slots": [
            s.model_dump(mode="json") for s in runtime.containers.list_slots()
        ],
        "profiles": [
            p.model_dump(mode="json") for p in runtime.containers.list_profiles()
        ],
        "capability_balls": records,
        "slot_aliases": dict(runtime.containers._slot_aliases),
        "account_directory": deepcopy(auth.account_directory) if auth else {},
        "cave_meta": runtime.cave_explorer.export_meta_state()
        if runtime.cave_explorer
        else {},
        "human_tools_state": runtime.human_tools.export_state(),
        "connector_state": connector_state,
        "messages": {
            uid: [m.model_dump(mode="json") for m in items]
            for uid, items in runtime.wecom._messages_by_user.items()
        },
        "wecom_state": runtime.wecom.export_state()
        if hasattr(runtime.wecom, "export_state")
        else {},
        "shadow_reviews": deepcopy(getattr(runtime, "shadow_reviews", {})),
        "modules": export_modules(runtime),
    }


async def restore_runtime_state(
    runtime: Any, payload: dict[str, Any], preserve_security: bool
) -> None:
    source = deepcopy(payload)
    current_profiles = {p.user_id: p for p in runtime.containers.list_profiles()}
    records = source.get("capability_balls", [])
    runtime.particles._balls.clear()
    runtime.particles._vectors.clear()
    sandbox = Path(runtime.settings.sandbox_workspace_dir)
    sandbox.mkdir(parents=True, exist_ok=True)
    if "script_files" in source:
        original_scripts = source["script_files"]
        for existing in sandbox.rglob("*.py"):
            relative = existing.relative_to(sandbox)
            if (
                "simulations" not in relative.parts
                and str(relative) not in original_scripts
            ):
                existing.unlink()
        for relative, content in original_scripts.items():
            target = sandbox / relative
            if not target.resolve().is_relative_to(sandbox.resolve()):
                raise ValueError("运行恢复脚本路径超出沙箱")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    for record in records:
        code = record.pop("source_code", "") or record.pop("executable_code_source", "")
        if record.get("executable_code_path"):
            filename = Path(record["executable_code_path"]).name
            record["executable_code_path"] = filename
            if code:
                (sandbox / filename).write_text(code, encoding="utf-8")
        runtime.particles.register_ball(CapabilityBall(**record), record_to_vault=False)
    restored_profiles = [DualEmployeeProfile(**p) for p in source.get("profiles", [])]
    if preserve_security:
        for profile in restored_profiles:
            current = current_profiles.get(profile.user_id)
            if current is not None:
                profile.role_view = current.role_view
                profile.title = current.title
    runtime.containers.load_persisted_containers(
        [UnitSlot(**s) for s in source.get("unit_slots", [])],
        restored_profiles,
    )
    runtime.containers.clear_slot_aliases()
    runtime.containers.register_slot_aliases(source.get("slot_aliases", {}))
    if runtime.cave_explorer:
        runtime.cave_explorer.restore_meta_state(source.get("cave_meta", {}))
    runtime.human_tools.restore_state(
        source.get("human_tools_state", {"contracts": [], "cards": []})
    )
    if runtime.connectors:
        connector_state = source.get(
            "private_connector_state", source.get("connector_state", {"bindings": []})
        )
        if "private_connector_state" not in source:
            current_bindings = {
                (b.slot_id, b.connector_type, b.endpoint_url): b.hmac_secret_override
                for b in runtime.connectors.list_bindings()
            }
            for binding in connector_state.get("bindings", []):
                binding["hmac_secret_override"] = current_bindings.get(
                    (
                        binding["slot_id"],
                        binding["connector_type"],
                        binding.get("endpoint_url", ""),
                    ),
                    "",
                )
        runtime.connectors.restore_state(connector_state)
    runtime.wecom._messages_by_user = {
        uid: [ChatMessageItem(**m) for m in items]
        for uid, items in source.get("messages", {}).items()
    }
    if source.get("wecom_state") and hasattr(runtime.wecom, "restore_state"):
        runtime.wecom.restore_state(source["wecom_state"])
    auth = runtime.auth_custody
    if auth:
        security = source.get("security_state") if not preserve_security else None
        if security is not None:
            auth.restore_from_persistence(
                security.get("account_directory", {}),
                security.get("passwords", {}),
                security.get("custody_requests", []),
            )
            # Only the private rollback journal restores a pre-request session.
            auth._sessions = dict(security.get("sessions", {}))
        else:
            if preserve_security and hasattr(auth, "restore_identity_metadata"):
                auth.restore_identity_metadata(source.get("account_directory", {}))
            else:
                auth.invalidate_sessions()
                auth.account_directory = deepcopy(source.get("account_directory", {}))
                auth.sync_accounts_from_containers()
    if "hot_state" in source:
        await runtime.hot_store.restore_global_state(source["hot_state"])
    restore_modules(runtime, source.get("modules", {}))
    runtime.shadow_reviews = deepcopy(source.get("shadow_reviews", {}))
    runtime.containers.sync_slot_node_map_from_nodes(
        await runtime.hot_store.list_nodes()
    )


def clear_workspace_runtime(runtime: Any) -> None:
    runtime.shadow_reviews = {}
    if runtime.connectors:
        runtime.connectors.restore_state(
            {"bindings": [], "callback_receipts": {}, "dispatch_history": []}
        )
    for name in ("spider", "scoring", "board", "arena", "day_sim"):
        module = getattr(runtime, name, None)
        if module and hasattr(module, "restore_state"):
            module.restore_state({})
    for name in (
        *MODULE_FACTORIES,
        "crucible",
        "enterprise_ingestor",
        "snapshot_timemachine",
        "genesis_engine",
        "capability_lifecycle",
    ):
        if hasattr(runtime, name):
            delattr(runtime, name)
    runtime.pulse_bus.clear_history()

from __future__ import annotations

from copy import deepcopy
import json
import re
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from core.auth_custody import AuthAndCustodyService, BallAccessRequestItem
from core.containers import ContainerRegistry
from core.schemas import (
    CapabilityBall,
    DualEmployeeProfile,
    UnitSlot,
    utc_now_iso,
)

EnterpriseState = Any


class SnapshotTimeMachine:
    """
    Pillar 3 核心组件：企业全量集群持久化快照与时间机器 (Snapshot Time-Machine)。
    支持：
    1. save_snapshot(label, note)：将当前全量 CapabilityBall（含沙箱 Python 源码备份）、
       部门与工位容器 (DepartmentContainer / UnitSlot)、账号分管与租约状态 (auth_custody_manager)
       及 WORM 账本 head_hash 完整序列化落盘至 snapshots 目录；
    2. list_snapshots()：按创建时间倒序读取所有磁盘快照元数据与统计指标；
    3. restore_snapshot(snapshot_id)：从磁盘快照一键回滚全量球库、沙箱脚本、工位容器、账号与挂载关系，
       并向 WORM 黑匣子追写 SNAPSHOT_RESTORED 审计印章。
    """

    def __init__(
        self,
        state: Optional[EnterpriseState] = None,
        runtime: Optional[EnterpriseState] = None,
    ) -> None:
        self.state = state or runtime
        if self.state is not None:
            if hasattr(self.state, "particles") and not hasattr(self.state, "ball_registry"):
                setattr(self.state, "ball_registry", self.state.particles._balls)
            if (
                hasattr(self.state, "vault")
                and hasattr(self.state, "particles")
                and hasattr(self.state, "containers")
            ):
                auth_svc = getattr(self.state, "auth_custody", None) or getattr(
                    self.state, "auth_custody_manager", None
                )
                if auth_svc is None:
                    auth_svc = AuthAndCustodyService(
                        vault=self.state.vault,
                        particles=self.state.particles,
                        containers=self.state.containers,
                    )
                setattr(self.state, "auth_custody", auth_svc)
                setattr(self.state, "auth_custody_manager", auth_svc)

    @property
    def snapshots_dir(self) -> Path:
        if self.state is not None and hasattr(self.state, "settings"):
            settings = self.state.settings
            base_dir = getattr(settings, "seed_dir", None) or getattr(
                settings, "vault_storage_dir", Path("/tmp/arachne_vault")
            )
            if not hasattr(settings, "seed_dir"):
                try:
                    object.__setattr__(settings, "seed_dir", Path(base_dir))
                except Exception:
                    pass
        else:
            base_dir = Path("/tmp/arachne_vault")
        snap_dir = Path(base_dir) / "workspace_snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        return snap_dir

    @property
    def sandbox_dir(self) -> Path:
        if self.state is not None and hasattr(self.state, "settings"):
            sb = Path(self.state.settings.sandbox_workspace_dir)
        else:
            sb = Path("/tmp/arachne_sandbox_workspace")
        sb.mkdir(parents=True, exist_ok=True)
        return sb

    def _compute_stats(
        self,
        balls: list[CapabilityBall],
        slots: list[UnitSlot],
        profiles: list[DualEmployeeProfile],
    ) -> dict[str, int]:
        depts = {s.department for s in slots if getattr(s, "department", None)}
        for p in profiles:
            auth = getattr(self.state, "auth_custody", None) if self.state else None
            meta = getattr(auth, "account_directory", {}).get(p.user_id, {})
            if meta.get("department"):
                depts.add(str(meta["department"]))
        dept_count = max(1, len(depts)) if slots or profiles else 0
        slot_count = len(slots)
        acc_count = len(profiles)
        ball_count = len(balls)
        active_skill_count = sum(
            1 for b in balls if b.ball_type == "SKILL" and b.status == "ACTIVE"
        )
        return {
            "departments": dept_count,
            "department_count": dept_count,
            "slots": slot_count,
            "slot_count": slot_count,
            "accounts": acc_count,
            "account_count": acc_count,
            "total_balls": ball_count,
            "ball_count": ball_count,
            "balls": ball_count,
            "active_skills": active_skill_count,
            "active_skill_count": active_skill_count,
        }

    @staticmethod
    def _write_bundle(path: Path, bundle: dict[str, Any]) -> None:
        def recovery_data(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: recovery_data(item) for key, item in value.items() if key not in {"passwords", "sessions", "security_state", "private_connector_state", "hmac_secret_override"}}
            if isinstance(value, list):
                return [recovery_data(item) for item in value]
            return value
        bundle = recovery_data(bundle)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as fh:
                json.dump(bundle, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def save_snapshot(
        self,
        label: str,
        note: str = "",
        extra_hot_state: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        clean_label = (label or "集群状态快照").strip()
        clean_note = (note or "").strip()
        snapshot_id = f"SNAP_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6].upper()}"
        created_at = utc_now_iso()
        created_ns = time.time_ns()

        particles = getattr(self.state, "particles", None) if self.state else None
        containers = getattr(self.state, "containers", None) if self.state else None
        vault = getattr(self.state, "vault", None) if self.state else None
        auth_svc = (
            getattr(self.state, "auth_custody", None)
            or getattr(self.state, "auth_custody_manager", None)
            if self.state
            else None
        )
        cave_explorer = getattr(self.state, "cave_explorer", None) if self.state else None
        human_tools = getattr(self.state, "human_tools", None) if self.state else None
        connectors = getattr(self.state, "connectors", None) if self.state else None

        cave_meta = (
            cave_explorer.export_meta_state()
            if cave_explorer is not None and hasattr(cave_explorer, "export_meta_state")
            else {}
        )

        all_balls: list[CapabilityBall] = (
            particles.list_all_balls() if particles is not None else []
        )
        all_slots: list[UnitSlot] = (
            containers.list_slots() if containers is not None else []
        )
        all_profiles: list[DualEmployeeProfile] = (
            containers.list_profiles() if containers is not None else []
        )

        enterprise_name = str(
            cave_meta.get("enterprise_name")
            or next(
                (s.department for s in all_slots if getattr(s, "department", None)),
                "未命名企业",
            )
        )
        workspace_mode = str(cave_meta.get("mode") or "DEMO_SEED")
        slot_aliases = (
            dict(getattr(containers, "_slot_aliases", {}))
            if containers is not None
            else {}
        )
        human_tools_state = (
            human_tools.export_state()
            if human_tools is not None and hasattr(human_tools, "export_state")
            else {}
        )
        connector_state = (
            connectors.export_state()
            if connectors is not None and hasattr(connectors, "export_state")
            else {}
        )
        # Credentials and bearer sessions are live security state, never recovery data.

        # 1. 序列化所有 CapabilityBall 及沙箱脚本源码备份
        serialized_balls: list[dict[str, Any]] = []
        for b in all_balls:
            b_dict = b.model_dump()
            script_source: Optional[str] = None
            if b.executable_code_path:
                script_file = self.sandbox_dir / b.executable_code_path
                if script_file.exists():
                    script_source = script_file.read_text(encoding="utf-8")
            b_dict["sandbox_script_source"] = script_source
            b_dict["permissions"] = {
                "owner_slot_ids": list(b.owner_slot_ids),
                "sensitivity_level": b.sensitivity_level,
                "redline_keywords": list(b.redline_keywords),
            }
            b_dict["payload"] = {
                "content": b.content,
                "domain_tags": list(b.domain_tags),
            }
            serialized_balls.append(b_dict)

        # 2. 序列化所有部门容器 (DepartmentContainer) 与岗位容器 (UnitSlot)
        dept_map: dict[str, list[str]] = {}
        serialized_slots: list[dict[str, Any]] = []
        all_leases: list[dict[str, Any]] = []
        for s in all_slots:
            s_dict = s.model_dump()
            s_dict["parent_id"] = f"DEPT_{s.department}"
            s_dict["children_ids"] = []
            s_dict["mounted_balls"] = list(s.ball_ids)
            s_dict["ephemeral_balls"] = [lease.model_dump() for lease in s.borrowed_balls]
            serialized_slots.append(s_dict)
            dept_map.setdefault(s.department, []).append(s.slot_id)
            for lease in s.borrowed_balls:
                all_leases.append(
                    {
                        "borrower_slot_id": s.slot_id,
                        **lease.model_dump(),
                    }
                )

        department_containers = [
            {
                "container_id": f"DEPT_{dept_name}",
                "department": dept_name,
                "parent_id": "root",
                "children_ids": slot_ids,
                "mounted_balls": [],
                "ephemeral_balls": [],
            }
            for dept_name, slot_ids in dept_map.items()
        ]

        # 3. 序列化账号、分管目录、租借申请与活跃租约
        serialized_profiles = [p.model_dump() for p in all_profiles]
        account_dir_snapshot = {
            uid: dict(meta) for uid, meta in getattr(auth_svc, "account_directory", {}).items()
        }
        requests_snapshot = (
            {req_id: req.model_dump() for req_id, req in auth_svc._requests.items()}
            if auth_svc is not None
            else {}
        )
        public_accounts = (
            [a.model_dump() for a in auth_svc.list_public_accounts()]
            if auth_svc is not None
            else []
        )

        # 4. 计算统计与获取 WORM 账本哈希
        stats = self._compute_stats(all_balls, all_slots, all_profiles)
        if vault is not None:
            vault.append_event(
                event_kind="SNAPSHOT_SAVED",
                subtree_root_id="root",
                actor_slot_id="SLOT_BOSS",
                payload={
                    "snapshot_id": snapshot_id,
                    "label": clean_label,
                    "note": clean_note,
                    "enterprise_name": enterprise_name,
                    "workspace_mode": workspace_mode,
                    "stats": stats,
                },
            )
            chain_report = vault.verify_chain_integrity()
            head_hash = chain_report.head_hash
            total_records = chain_report.total_records
        else:
            head_hash = "0" * 64
            total_records = 0

        snapshot_bundle: dict[str, Any] = {
            "snapshot_id": snapshot_id,
            "label": clean_label,
            "note": clean_note,
            "enterprise_name": enterprise_name,
            "workspace_mode": workspace_mode,
            "created_at": created_at,
            "created_ns": created_ns,
            "head_hash": head_hash,
            "vault_total_records": total_records,
            "stats": stats,
            "cave_meta": cave_meta,
            "slot_aliases": slot_aliases,
            "human_tools_state": human_tools_state,
            "connector_state": connector_state,
            "balls": serialized_balls,
            "containers": {
                "departments": department_containers,
                "slots": serialized_slots,
                "profiles": serialized_profiles,
            },
            "auth_custody": {
                "accounts": public_accounts,
                "account_directory": account_dir_snapshot,
                "requests": requests_snapshot,
                "leases": all_leases,
            },
        }
        if self.state is not None and hasattr(self.state, "export_runtime_state"):
            snapshot_bundle["runtime_state"] = self.state.export_runtime_state()
        if extra_hot_state is not None:
            snapshot_bundle["hot_state"] = extra_hot_state

        snap_file = self.snapshots_dir / f"tm_{snapshot_id}.json"
        self._write_bundle(snap_file, snapshot_bundle)

        return {
            "snapshot_id": snapshot_id,
            "label": clean_label,
            "note": clean_note,
            "enterprise_name": enterprise_name,
            "workspace_mode": workspace_mode,
            "created_at": created_at,
            "stats": stats,
            "head_hash": head_hash,
        }

    def list_snapshots(self) -> list[dict[str, Any]]:
        items: list[tuple[int, str, dict[str, Any]]] = []
        paths = [*self.snapshots_dir.glob("tm_SNAP_*.json"), *(self.snapshots_dir.parent / "snapshots").glob("tm_SNAP_*.json")]
        for path in paths:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, dict) or "snapshot_id" not in raw or "label" not in raw:
                continue
            created_ns = int(raw.get("created_ns") or 0)
            created_at = str(raw.get("created_at") or "")
            items.append(
                (
                    created_ns,
                    created_at,
                    {
                        "snapshot_id": raw["snapshot_id"],
                        "label": raw["label"],
                        "note": raw.get("note", ""),
                        "enterprise_name": str(raw.get("enterprise_name") or ""),
                        "workspace_mode": str(raw.get("workspace_mode") or ""),
                        "created_at": created_at,
                        "stats": raw.get("stats", {}),
                        "head_hash": raw.get("head_hash", ""),
                    },
                )
            )
        items.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [item[2] for item in items]

    def _resolve_snapshot_file(self, snapshot_id: str) -> tuple[str, Path]:
        clean_id = (snapshot_id or "").strip()
        if not re.fullmatch(r"SNAP_[0-9]+_[A-F0-9]{6}", clean_id):
            raise KeyError(f"非法的快照 ID: {snapshot_id}")
        snap_file = self.snapshots_dir / f"tm_{clean_id}.json"
        if not snap_file.exists():
            # Legacy workspace snapshots have a typed tm_ prefix; sealed hash files are never candidates.
            alt_file = self.snapshots_dir.parent / "snapshots" / f"tm_{clean_id}.json"
            if alt_file.exists():
                snap_file = alt_file
            else:
                raise KeyError(f"未找到指定的集群快照: {clean_id}")
        if snap_file.is_symlink() or snap_file.resolve().parent not in {self.snapshots_dir.resolve(), (self.snapshots_dir.parent / "snapshots").resolve()}:
            raise KeyError(f"非法的快照路径: {clean_id}")
        return clean_id, snap_file

    def delete_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        clean_id, snap_file = self._resolve_snapshot_file(snapshot_id)
        snap_file.unlink()
        return {
            "deleted": True,
            "snapshot_id": clean_id,
        }

    def _administrator_recovery_state(
        self, actor_user_id: str | None = None
    ) -> dict[str, Any]:
        """Capture live personnel authority separately from business archives."""
        auth = getattr(self.state, "auth_custody", None)
        containers = getattr(self.state, "containers", None)
        retired: set[str] = set()
        vault = getattr(self.state, "vault", None)
        if vault is not None:
            for record in vault.read_records():
                data = record.payload
                if (
                    record.event_kind == "SLOT_OCCUPANT_HANDOVER"
                    and data.get("handover_mode") == "RESIGN_HANDOVER"
                    and data.get("previous_user_id") != data.get("new_user_id")
                ):
                    retired.add(str(data["previous_user_id"]))
                elif record.event_kind == "ACCOUNT_PASSWORD_PROVISIONED":
                    retired.discard(str(data.get("user_id", "")))
        administrators = []
        if auth is not None and containers is not None:
            retired.update(
                uid
                for uid, meta in auth.account_directory.items()
                if meta.get("_disabled")
            )
            for profile in containers.list_profiles():
                if "（已离岗交接）" in profile.title:
                    retired.add(profile.user_id)
                if profile.role_view != "boss" or profile.user_id in retired:
                    continue
                slot = containers.get_slot(profile.slot_id)
                if slot.occupant_id != profile.user_id or slot.slot_id.startswith(
                    "SLOT_STANDBY_"
                ):
                    continue
                password_hash = auth._passwords.get(profile.user_id)
                if password_hash:
                    administrators.append(
                        {
                            "profile": profile.model_dump(),
                            "slot": slot.model_dump(),
                            "metadata": deepcopy(
                                auth.account_directory.get(profile.user_id, {})
                            ),
                            "password_hash": password_hash,
                        }
                    )
        leave_delegations = []
        if auth is not None and containers is not None:
            for holder in containers.list_profiles():
                metadata = auth.account_directory.get(holder.user_id, {})
                leave = metadata.get("_leave_delegation")
                if not isinstance(leave, dict) or metadata.get("_disabled"):
                    continue
                standby = containers._slots.get(holder.slot_id)
                target = containers._slots.get(leave.get("slot_id"))
                delegate = containers._profiles.get(leave.get("delegate_user_id"))
                if (
                    standby is None
                    or standby.occupant_id != holder.user_id
                    or standby.ball_ids
                    or standby.borrowed_balls
                    or leave.get("standby_slot_id") != standby.slot_id
                    or target is None
                    or delegate is None
                    or target.occupant_id != delegate.user_id
                    or delegate.slot_id != target.slot_id
                    or auth.account_directory.get(delegate.user_id, {}).get("_disabled")
                ):
                    continue
                leave_delegations.append(
                    {
                        "target_slot_id": target.slot_id,
                        "standby": standby.model_dump(),
                        "people": [
                            {
                                "profile": person.model_dump(),
                                "metadata": deepcopy(
                                    auth.account_directory.get(person.user_id, {})
                                ),
                                "password_hash": auth._passwords.get(person.user_id),
                            }
                            for person in (holder, delegate)
                        ],
                    }
                )
        return {
            "retired": retired,
            "administrators": administrators,
            "actor_user_id": actor_user_id,
            "leave_delegations": leave_delegations,
        }

    def _retain_leave_delegations(self, recovery: dict[str, Any]) -> None:
        auth = self.state.auth_custody
        containers = self.state.containers
        for delegation in recovery["leave_delegations"]:
            target_id = delegation["target_slot_id"]
            if target_id not in containers._slots:
                continue
            standby = UnitSlot(**delegation["standby"])
            archived = containers._slots.get(standby.slot_id)
            if archived is not None and (
                archived.occupant_id != standby.occupant_id
                or archived.ball_ids
                or archived.borrowed_balls
            ):
                raise ValueError("历史隔离槽与当前休假交接冲突，不能覆盖岗位资料")
            containers.register_slot(standby)
            for person in delegation["people"]:
                profile = DualEmployeeProfile(**person["profile"])
                containers.register_profile(profile)
                auth.account_directory[profile.user_id] = deepcopy(person["metadata"])
                if person["password_hash"]:
                    auth.set_password(profile.user_id, person["password_hash"])
            containers.get_slot(target_id).occupant_id = delegation["people"][1][
                "profile"
            ]["user_id"]
            auth.transfer_post_relationships(
                delegation["people"][0]["profile"]["user_id"],
                delegation["people"][1]["profile"]["user_id"],
                target_id,
            )

    def _restore_access_requests(
        self, auth_data: dict[str, Any], recovery: dict[str, Any]
    ) -> None:
        auth = self.state.auth_custody
        active_users = {
            uid
            for uid, metadata in auth.account_directory.items()
            if uid in self.state.containers._profiles and not metadata.get("_disabled")
        }
        auth._requests.clear()
        for request_id, raw in auth_data.get("requests", {}).items():
            if (
                raw.get("requester_id") in active_users
                and raw.get("custodian_id") in active_users
            ):
                auth._requests[request_id] = BallAccessRequestItem(**raw)
        for delegation in recovery["leave_delegations"]:
            if delegation["target_slot_id"] in self.state.containers._slots:
                auth.transfer_post_relationships(
                    delegation["people"][0]["profile"]["user_id"],
                    delegation["people"][1]["profile"]["user_id"],
                    delegation["target_slot_id"],
                )

    def _retain_administrator_access(
        self, recovery: dict[str, Any], boss_slot_ids: list[str]
    ) -> None:
        auth = getattr(self.state, "auth_custody", None)
        containers = getattr(self.state, "containers", None)
        if auth is None or containers is None:
            return
        self._retain_leave_delegations(recovery)
        for uid in recovery["retired"]:
            if uid in containers._profiles:
                auth.account_directory.setdefault(uid, {})["_disabled"] = True
                auth.invalidate_sessions(uid)

        def active_boss(profile: DualEmployeeProfile) -> bool:
            return (
                profile.role_view == "boss"
                and not auth.account_directory.get(profile.user_id, {}).get("_disabled")
                and profile.user_id in auth._passwords
                and containers.get_slot(profile.slot_id).occupant_id == profile.user_id
                and not profile.slot_id.startswith("SLOT_STANDBY_")
            )

        administrators = recovery["administrators"]
        # A unique valid administrator may already have a legitimate archive
        # identity. Multiple current administrators retain their own credentials.
        if len(administrators) <= 1 and any(
            active_boss(p) for p in containers.list_profiles()
        ):
            return
        ordered = sorted(
            administrators,
            key=lambda item: (
                item["profile"]["user_id"] != recovery["actor_user_id"],
                item["slot"]["slot_id"] not in boss_slot_ids,
                item["profile"]["user_id"],
            ),
        )
        for administrator in ordered:
            profile = DualEmployeeProfile(**administrator["profile"])
            existing = containers._profiles.get(profile.user_id)
            if existing is not None and active_boss(existing):
                continue
            target = None
            for slot_id in boss_slot_ids:
                if slot_id not in containers._slots:
                    continue
                candidate = containers.get_slot(slot_id)
                occupant = containers._profiles.get(candidate.occupant_id)
                if occupant is None or not active_boss(occupant):
                    target = candidate
                    break
            if target is None:
                slot_id = (
                    "SLOT_RECOVERY_"
                    + uuid.uuid5(uuid.NAMESPACE_URL, profile.user_id).hex[:16].upper()
                )
                target = UnitSlot(
                    slot_id=slot_id,
                    slot_name="现任管理员恢复入口",
                    department="管理",
                    occupant_type="HUMAN",
                    occupant_id=profile.user_id,
                    ball_ids=[],
                )
                containers.register_slot(target)
            displaced = containers._profiles.get(target.occupant_id)
            if displaced is not None and displaced.user_id != profile.user_id:
                standby_id = (
                    "SLOT_RESTORED_"
                    + uuid.uuid5(uuid.NAMESPACE_URL, displaced.user_id).hex[:16].upper()
                )
                containers.register_slot(
                    UnitSlot(
                        slot_id=standby_id,
                        slot_name="历史人员隔离槽",
                        department=target.department,
                        occupant_type="HUMAN",
                        occupant_id=displaced.user_id,
                        ball_ids=[],
                    )
                )
                displaced.slot_id = standby_id
                auth.account_directory.setdefault(displaced.user_id, {})[
                    "_disabled"
                ] = True
            target.occupant_id = profile.user_id
            target.occupant_type = "HUMAN"
            profile.slot_id = target.slot_id
            containers.register_profile(profile)
            auth.account_directory[profile.user_id] = deepcopy(
                administrator["metadata"]
            )
            auth.set_password(profile.user_id, administrator["password_hash"])

    def restore_snapshot(self, snapshot_id: str, *, record_completion: bool = True, actor_user_id: str | None = None) -> dict[str, Any]:
        clean_id, snap_file = self._resolve_snapshot_file(snapshot_id)
        bundle = json.loads(snap_file.read_text(encoding="utf-8"))
        if self.state is None:
            raise RuntimeError("SnapshotTimeMachine 未绑定有效的 EnterpriseState")

        particles = getattr(self.state, "particles", None)
        containers: Optional[ContainerRegistry] = getattr(self.state, "containers", None)
        vault = getattr(self.state, "vault", None)
        auth_svc = getattr(self.state, "auth_custody", None) or getattr(
            self.state, "auth_custody_manager", None
        )
        cave_explorer = getattr(self.state, "cave_explorer", None)
        human_tools = getattr(self.state, "human_tools", None)
        connectors = getattr(self.state, "connectors", None)
        recovery = self._administrator_recovery_state(actor_user_id)
        boss_slot_ids = [
            p["slot_id"] for p in bundle.get("containers", {}).get("profiles", [])
            if p.get("role_view") == "boss"
        ]

        for raw in bundle.get("balls", []):
            fields = {k: v for k, v in raw.items() if k in CapabilityBall.model_fields}
            CapabilityBall(**fields)
            if raw.get("executable_code_path"):
                script = (self.sandbox_dir / raw["executable_code_path"]).resolve()
                if not script.is_relative_to(self.sandbox_dir.resolve()):
                    raise ValueError("Snapshot script path leaves sandbox")
        for raw in bundle.get("containers", {}).get("slots", []):
            UnitSlot(**{k: v for k, v in raw.items() if k in UnitSlot.model_fields})
        for raw in bundle.get("containers", {}).get("profiles", []):
            DualEmployeeProfile(**raw)

        current_profiles = {p.user_id: p for p in containers.list_profiles()} if containers is not None else {}
        current_identity_ids = set(getattr(auth_svc, "account_directory", {})) & set(current_profiles)
        current_ws_id = str(getattr(cave_explorer, "workspace_id", "") or "")
        target_ws_id = str((bundle.get("cave_meta") or {}).get("workspace_id") or "")
        current_ent = str(getattr(cave_explorer, "enterprise_name", "") or "")
        target_ent = str(bundle.get("enterprise_name") or "")
        if current_ws_id and target_ws_id:
            same_workspace = current_ws_id == target_ws_id
        elif current_ent and target_ent:
            same_workspace = current_ent == target_ent
        else:
            same_workspace = True
        prior_boss_pw = recovery["administrators"][0]["password_hash"] if len(recovery["administrators"]) == 1 else None

        # 1. 恢复全部 CapabilityBall 与沙箱脚本文件
        if particles is not None:
            particles._balls.clear()
            particles._vectors.clear()
            for b_raw in bundle.get("balls", []):
                script_src = b_raw.get("sandbox_script_source") or b_raw.get("source_code")
                exec_path = b_raw.get("executable_code_path")
                if exec_path and script_src:
                    target_script = self.sandbox_dir / exec_path
                    target_script.parent.mkdir(parents=True, exist_ok=True)
                    target_script.write_text(script_src, encoding="utf-8")

                ball_fields = {
                    k: v
                    for k, v in b_raw.items()
                    if k
                    in {
                        "ball_id",
                        "ball_type",
                        "title",
                        "domain_tags",
                        "sensitivity_level",
                        "owner_slot_ids",
                        "content",
                        "redline_keywords",
                        "executable_code_path",
                        "version",
                        "status",
                        "created_at",
                    }
                }
                ball = CapabilityBall(**ball_fields)
                particles.register_ball(ball, record_to_vault=False)

            setattr(self.state, "ball_registry", particles._balls)

        # 2. 恢复 containers（移除可能被创世空投绑定的实例级方法覆写，恢复全部工位、别名与员工档案）
        if containers is not None:
            if "_resolve_slot_id" in containers.__dict__:
                del containers.__dict__["_resolve_slot_id"]
            if "get_profile" in containers.__dict__:
                del containers.__dict__["get_profile"]

            containers._slots.clear()
            containers._profiles.clear()
            containers.clear_slot_aliases()
            if bundle.get("slot_aliases"):
                containers.register_slot_aliases(dict(bundle["slot_aliases"]))

            containers_data = bundle.get("containers", {})
            for s_raw in containers_data.get("slots", []):
                slot_fields = {
                    k: v
                    for k, v in s_raw.items()
                    if k
                    in {
                        "slot_id",
                        "slot_name",
                        "department",
                        "ball_ids",
                        "borrowed_balls",
                        "occupant_type",
                        "occupant_id",
                        "replaceability_score",
                        "rule_repetition_ratio",
                        "shadow_agreement_rate",
                        "replaceability_breakdown",
                    }
                }
                slot_obj = UnitSlot(**slot_fields)
                containers.register_slot(slot_obj)

            for p_raw in containers_data.get("profiles", []):
                prof_obj = DualEmployeeProfile(**p_raw)
                if prof_obj.user_id in current_profiles:
                    # Personnel authority is current security state, not snapshot business data.
                    prof_obj.role_view = current_profiles[prof_obj.user_id].role_view
                    if same_workspace or "（已离岗交接）" in (current_profiles[prof_obj.user_id].title or ""):
                        prof_obj.title = current_profiles[prof_obj.user_id].title
                if containers_data.get("slots"):
                    try:
                        matched_slot = containers.get_slot(prof_obj.slot_id)
                        object.__setattr__(
                            prof_obj, "mounted_ball_ids", list(matched_slot.ball_ids)
                        )
                    except Exception:
                        pass
                containers.register_profile(prof_obj)

        # Security state remains authoritative: recovery never reactivates identities,
        # credentials, disabled accounts or revoked sessions from an old snapshot.
        auth_data = bundle.get("auth_custody", {})
        if auth_svc is not None:
            for profile in containers.list_profiles() if containers is not None else []:
                if profile.user_id not in current_identity_ids:
                    auth_svc.account_directory[profile.user_id] = {"_disabled": True, "department": "已恢复历史档案", "supervisor_id": None, "is_custodian_leader": False}
                    auth_svc._passwords.pop(profile.user_id, None)
            if hasattr(auth_svc, "restore_identity_metadata"):
                auth_svc.restore_identity_metadata(dict(auth_data.get("account_directory") or {}))
            restored_profiles = containers.list_profiles() if containers is not None else []
            active_boss_with_pw = any(
                prof.role_view == "boss"
                and not auth_svc.account_directory.get(prof.user_id, {}).get("_disabled")
                and prof.user_id in auth_svc._passwords
                for prof in restored_profiles
            )
            if not active_boss_with_pw and prior_boss_pw is not None:
                snap_dir = dict(auth_data.get("account_directory") or {})
                for prof in restored_profiles:
                    if prof.role_view != "boss":
                        continue
                    snap_meta = snap_dir.get(prof.user_id, {})
                    if snap_meta.get("_disabled") or prof.user_id in recovery["retired"]:
                        continue
                    restored_meta = dict(snap_meta)
                    restored_meta.pop("_disabled", None)
                    restored_meta.setdefault("department", "总办董事会")
                    restored_meta.setdefault("supervisor_id", None)
                    restored_meta["is_custodian_leader"] = True
                    auth_svc.account_directory[prof.user_id] = restored_meta
                    auth_svc.set_password(prof.user_id, prior_boss_pw)
            self._retain_administrator_access(recovery, boss_slot_ids)
            self._restore_access_requests(auth_data, recovery)
            auth_svc.invalidate_sessions()

        # 4. 恢复探网元状态、人类黑盒契约/卡片及外部连接器绑定
        enterprise_name = str(bundle.get("enterprise_name") or "")
        if cave_explorer is not None and hasattr(cave_explorer, "restore_meta_state"):
            cave_meta = dict(bundle.get("cave_meta") or {})
            cave_meta.setdefault("enterprise_name", enterprise_name)
            cave_meta.setdefault("mode", str(bundle.get("workspace_mode") or "FULLY_LIT"))
            # Legacy archives acquire a deterministic namespace on first recovery.
            cave_meta.setdefault("workspace_id", uuid.uuid5(uuid.NAMESPACE_URL, f"arachne:workspace:{clean_id}").hex)
            cave_meta.setdefault("workspace_epoch", uuid.uuid5(uuid.NAMESPACE_URL, f"arachne:epoch:{clean_id}").hex)
            cave_explorer.restore_meta_state(cave_meta, fallback_enterprise_name=enterprise_name)

        if (
            "human_tools_state" in bundle
            and human_tools is not None
            and hasattr(human_tools, "restore_state")
        ):
            ht_state = bundle.get("human_tools_state") or {"contracts": [], "cards": []}
            human_tools.restore_state(ht_state)

        if (
            "connector_state" in bundle
            and connectors is not None
            and hasattr(connectors, "restore_state")
        ):
            conn_state = bundle.get("connector_state") or {
                "bindings": [],
                "callback_receipts": {},
                "dispatch_history": [],
            }
            current_secrets = {
                (item.slot_id, item.connector_type, item.endpoint_url): item.hmac_secret_override
                for item in connectors.list_bindings()
            } if hasattr(connectors, "list_bindings") else {}
            for binding in conn_state.get("bindings", []):
                binding["hmac_secret_override"] = current_secrets.get((binding.get("slot_id"), binding.get("connector_type"), binding.get("endpoint_url")), "")
            connectors.restore_state(conn_state)

        # 5. 追写 WORM 账本 SNAPSHOT_RESTORED 审计印章
        restored_stats = self._compute_stats(
            particles.list_all_balls() if particles is not None else [],
            containers.list_slots() if containers is not None else [],
            containers.list_profiles() if containers is not None else [],
        )
        worm_event = None
        head_hash = bundle.get("head_hash", "")
        if vault is not None and record_completion:
            worm_event = vault.append_event(
                event_kind="SNAPSHOT_RESTORED",
                subtree_root_id="root",
                actor_slot_id="SLOT_BOSS",
                payload={
                    "snapshot_id": clean_id,
                    "label": bundle.get("label", ""),
                    "enterprise_name": enterprise_name,
                    "restored_stats": restored_stats,
                    "source_head_hash": bundle.get("head_hash", ""),
                },
            )
            head_hash = vault.verify_chain_integrity().head_hash

        return {
            "restored": True,
            "snapshot_id": clean_id,
            "label": bundle.get("label", ""),
            "note": bundle.get("note", ""),
            "enterprise_name": enterprise_name,
            "workspace_mode": str(bundle.get("workspace_mode") or ""),
            "restored_at": utc_now_iso(),
            "stats": restored_stats,
            "head_hash": head_hash,
            "worm_event": worm_event.model_dump() if worm_event else None,
        }

    async def save_full_snapshot(self, label: str, note: str = "") -> dict[str, Any]:
        hot_store = getattr(self.state, "hot_store", None) if self.state else None
        hot_state = await hot_store.export_global_state() if hot_store is not None else None
        return self.save_snapshot(label=label, note=note, extra_hot_state=hot_state)

    async def restore_full_snapshot(self, snapshot_id: str, *, actor_user_id: str | None = None) -> dict[str, Any]:
        _, snap_file = self._resolve_snapshot_file(snapshot_id)
        bundle = json.loads(snap_file.read_text(encoding="utf-8"))
        rt = self.state
        old = await rt.capture_state() if hasattr(rt, "capture_state") else None
        recovery = self._administrator_recovery_state(actor_user_id)
        boss_slot_ids = [
            p["slot_id"] for p in bundle.get("containers", {}).get("profiles", [])
            if p.get("role_view") == "boss"
        ]
        try:
            result = self.restore_snapshot(snapshot_id, record_completion=False, actor_user_id=actor_user_id)
            runtime_state = bundle.get("runtime_state")
            if isinstance(runtime_state, dict) and hasattr(rt, "restore_runtime_state"):
                await rt.restore_runtime_state(runtime_state, preserve_security=True)
            self._retain_administrator_access(recovery, boss_slot_ids)
            self._restore_access_requests(bundle.get("auth_custody", {}), recovery)
            hot_store = getattr(rt, "hot_store", None)
            if hot_store is not None and isinstance(bundle.get("hot_state"), dict):
                await hot_store.restore_global_state(bundle["hot_state"])
                rt.containers.sync_slot_node_map_from_nodes(await hot_store.list_nodes())
            if hasattr(rt, "sync_persistence"):
                await rt.sync_persistence()
            vault = getattr(rt, "vault", None)
            if vault is not None:
                event = vault.append_event("SNAPSHOT_RESTORED", "root", "SLOT_BOSS", {"snapshot_id": snapshot_id, "enterprise_name": result["enterprise_name"], "source_head_hash": bundle.get("head_hash", "")})
                result["worm_event"] = event.model_dump()
                result["head_hash"] = vault.verify_chain_integrity().head_hash
            return result
        except BaseException:
            if old is not None:
                await rt.restore_runtime_state(old, preserve_security=False)
                if hasattr(rt, "sync_persistence"):
                    await rt.sync_persistence()
            raise

    async def import_sqlite_db_as_snapshot(
        self,
        sqlite_file: Path,
        label: str,
        note: str = "",
        external_sandbox_dir: Optional[Path] = None,
    ) -> dict[str, Any]:
        from database import HotStateStore

        db_path = Path(sqlite_file).resolve()
        if not db_path.exists():
            raise FileNotFoundError(f"未找到待导入的 SQLite 状态库: {db_path}")

        # Import is read-only; never initialize or migrate an external state database.
        ext_store = HotStateStore(f"sqlite+aiosqlite:///file:{db_path.as_posix()}?mode=ro&uri=true")
        try:
            persisted = await ext_store.load_workspace_state()
            hot_state = await ext_store.export_global_state()
        finally:
            await ext_store.close()

        if persisted is None:
            raise ValueError(f"SQLite 状态库 {db_path} 中不存在有效的 workspace_state_meta 数据")

        snapshot_id = f"SNAP_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6].upper()}"
        created_at = utc_now_iso()
        created_ns = time.time_ns()

        meta_payload = dict(persisted.get("meta_payload") or {})
        cave_meta = dict(meta_payload.get("cave_meta") or {})
        enterprise_name = str(
            persisted.get("enterprise_name")
            or cave_meta.get("enterprise_name")
            or "已导入企业存档"
        )
        workspace_mode = str(
            persisted.get("mode") or cave_meta.get("mode") or "FULLY_LIT"
        )

        unit_slots: list[UnitSlot] = list(persisted.get("unit_slots") or [])
        profiles: list[DualEmployeeProfile] = list(persisted.get("profiles") or [])
        ball_records: list[dict[str, Any]] = list(persisted.get("capability_balls") or [])

        serialized_balls: list[dict[str, Any]] = []
        parsed_balls: list[CapabilityBall] = []
        for rec in ball_records:
            ball: CapabilityBall = rec["ball"]
            parsed_balls.append(ball)
            src = rec.get("source_code") or rec.get("executable_code_source")
            if not src and ball.executable_code_path and external_sandbox_dir is not None:
                cand = Path(external_sandbox_dir) / ball.executable_code_path
                if cand.exists():
                    src = cand.read_text(encoding="utf-8")
            b_dict = ball.model_dump()
            b_dict["sandbox_script_source"] = src
            b_dict["permissions"] = {
                "owner_slot_ids": list(ball.owner_slot_ids),
                "sensitivity_level": ball.sensitivity_level,
                "redline_keywords": list(ball.redline_keywords),
            }
            b_dict["payload"] = {
                "content": ball.content,
                "domain_tags": list(ball.domain_tags),
            }
            serialized_balls.append(b_dict)

        dept_map: dict[str, list[str]] = {}
        serialized_slots: list[dict[str, Any]] = []
        all_leases: list[dict[str, Any]] = []
        for s in unit_slots:
            s_dict = s.model_dump()
            s_dict["parent_id"] = f"DEPT_{s.department}"
            s_dict["children_ids"] = []
            s_dict["mounted_balls"] = list(s.ball_ids)
            s_dict["ephemeral_balls"] = [lease.model_dump() for lease in s.borrowed_balls]
            serialized_slots.append(s_dict)
            dept_map.setdefault(s.department, []).append(s.slot_id)
            for lease in s.borrowed_balls:
                all_leases.append({"borrower_slot_id": s.slot_id, **lease.model_dump()})

        department_containers = [
            {
                "container_id": f"DEPT_{dept_name}",
                "department": dept_name,
                "parent_id": "root",
                "children_ids": slot_ids,
                "mounted_balls": [],
                "ephemeral_balls": [],
            }
            for dept_name, slot_ids in dept_map.items()
        ]

        requests_map = {
            str(r["request_id"]): r
            for r in (persisted.get("custody_requests") or [])
            if isinstance(r, dict) and r.get("request_id")
        }
        stats = self._compute_stats(parsed_balls, unit_slots, profiles)

        vault = getattr(self.state, "vault", None) if self.state else None
        if vault is not None:
            vault.append_event(
                event_kind="SNAPSHOT_IMPORTED",
                subtree_root_id="root",
                actor_slot_id="SLOT_BOSS",
                payload={
                    "snapshot_id": snapshot_id,
                    "label": label.strip() or f"{enterprise_name} 存档",
                    "enterprise_name": enterprise_name,
                    "source_db": db_path.name,
                    "stats": stats,
                },
            )
            chain_report = vault.verify_chain_integrity()
            head_hash = chain_report.head_hash
            total_records = chain_report.total_records
        else:
            head_hash = "0" * 64
            total_records = 0

        snapshot_bundle = {
            "snapshot_id": snapshot_id,
            "label": (label or f"{enterprise_name} 存档").strip(),
            "note": (note or f"从历史库 {db_path.name} 导入的企业全量存档").strip(),
            "enterprise_name": enterprise_name,
            "workspace_mode": workspace_mode,
            "created_at": created_at,
            "created_ns": created_ns,
            "head_hash": head_hash,
            "vault_total_records": total_records,
            "stats": stats,
            "cave_meta": cave_meta,
            "slot_aliases": dict(meta_payload.get("slot_aliases") or {}),
            "human_tools_state": dict(meta_payload.get("human_tools_state") or {}),
            "connector_state": dict(meta_payload.get("connector_state") or {}),
            "runtime_state": dict(meta_payload.get("runtime_state") or {}),
            "balls": serialized_balls,
            "containers": {
                "departments": department_containers,
                "slots": serialized_slots,
                "profiles": [p.model_dump() for p in profiles],
            },
            "auth_custody": {
                "accounts": [],
                "account_directory": dict(persisted.get("account_directory") or {}),
                "requests": requests_map,
                "leases": all_leases,
            },
            "hot_state": hot_state,
        }

        snap_file = self.snapshots_dir / f"tm_{snapshot_id}.json"
        self._write_bundle(snap_file, snapshot_bundle)

        return {
            "snapshot_id": snapshot_id,
            "label": snapshot_bundle["label"],
            "note": snapshot_bundle["note"],
            "enterprise_name": enterprise_name,
            "workspace_mode": workspace_mode,
            "created_at": created_at,
            "stats": stats,
            "head_hash": head_hash,
        }

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from core.schemas import (
    BorrowedBallLease,
    DualEmployeeProfile,
    OccupantType,
    PublicEmployeeSelfProfile,
    PublicUnitSlotView,
    UnitSlot,
)


def _parse_iso(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


class ContainerRegistry:
    """
    标准岗位单元容器 (UnitSlot) 与员工双面反推简历库 (DualEmployeeProfile) 管理器。
    特性：
    1. 岗人分离：权能小球与工作记忆绑定在 UnitSlot 上，人员流动不丢记忆；
    2. 跨岗临时借球：支持带过期时间戳 (TTL) 的借球，惰性扫描自动过期回收；
    3. A/B 双面画像物理隔离：向普通员工投影时彻底剥离 B 面评价与可替代分。
    """

    def __init__(self) -> None:
        self._slots: dict[str, UnitSlot] = {}
        self._profiles: dict[str, DualEmployeeProfile] = {}
        self._slot_aliases: dict[str, str] = {}
        self._slot_node_map: dict[str, str] = {}

    def bind_slot_node(self, slot_id: str, node_id: str) -> None:
        if slot_id and node_id:
            self._slot_node_map[slot_id] = node_id
            self._slot_node_map[slot_id.lower()] = node_id

    def sync_slot_node_map_from_nodes(self, nodes: Iterable[Any]) -> None:
        self._slot_node_map.clear()
        priority_nodes: list[Any] = []
        secondary_nodes: list[Any] = []
        for node in nodes:
            if not getattr(node, "slot_id", None):
                continue
            ntype = str(getattr(node, "node_type", "") or "")
            if ntype in ("WORKER_SLOT", "RELAY_NODE", "BLACKBOX_HUMAN"):
                priority_nodes.append(node)
            else:
                secondary_nodes.append(node)
        for node in secondary_nodes:
            self.bind_slot_node(node.slot_id, node.node_id)
        for node in priority_nodes:
            self.bind_slot_node(node.slot_id, node.node_id)

    def resolve_node_id_for_slot(self, slot_id: str) -> str:
        resolved = self._resolve_slot_id(slot_id)
        mapped = self._slot_node_map.get(resolved) or self._slot_node_map.get(resolved.lower())
        if mapped:
            return mapped
        for p in self._profiles.values():
            if p.slot_id == resolved and p.role_view == "boss":
                return "node_board_root"
        return f"node_{resolved.lower()}"

    def register_slot_alias(self, alias: str, target_slot_id: str) -> None:
        self._slot_aliases[alias] = target_slot_id
        self._slot_aliases[alias.lower()] = target_slot_id

    def register_slot_aliases(self, aliases: dict[str, str]) -> None:
        for k, v in aliases.items():
            self.register_slot_alias(k, v)

    def clear_slot_aliases(self) -> None:
        self._slot_aliases.clear()

    def load_persisted_containers(
        self, slots: list[UnitSlot], profiles: list[DualEmployeeProfile]
    ) -> None:
        self._slots.clear()
        self._profiles.clear()
        for s in slots:
            self._slots[s.slot_id] = s
        for p in profiles:
            self._profiles[p.user_id] = p

    def _resolve_slot_id(self, slot_id: str) -> str:
        if slot_id in self._slots:
            return slot_id
        mapped = self._slot_aliases.get(slot_id) or self._slot_aliases.get(slot_id.lower())
        if mapped and mapped in self._slots:
            return mapped
        upper = slot_id.upper()
        if upper in self._slots:
            return upper
        for existing_id in self._slots:
            if existing_id.lower() == slot_id.lower():
                return existing_id
        return slot_id

    def register_slot(self, slot: UnitSlot) -> UnitSlot:
        self._slots[slot.slot_id] = slot
        return slot

    def register_profile(self, profile: DualEmployeeProfile) -> DualEmployeeProfile:
        self._profiles[profile.user_id] = profile
        return profile

    def get_slot(self, slot_id: str) -> UnitSlot:
        resolved = self._resolve_slot_id(slot_id)
        if resolved not in self._slots:
            raise KeyError(f"UnitSlot {slot_id} not found")
        self._purge_expired_leases(resolved)
        return self._slots[resolved]

    def list_slots(self) -> list[UnitSlot]:
        for sid in list(self._slots.keys()):
            self._purge_expired_leases(sid)
        return list(self._slots.values())

    def get_profile(self, user_id: str) -> DualEmployeeProfile:
        if user_id not in self._profiles:
            raise KeyError(f"Employee profile {user_id} not found")
        return self._profiles[user_id]

    def list_profiles(self) -> list[DualEmployeeProfile]:
        return list(self._profiles.values())

    def attach_ball_to_slot(self, slot_id: str, ball_id: str) -> UnitSlot:
        slot = self.get_slot(slot_id)
        if ball_id not in slot.ball_ids:
            slot.ball_ids.append(ball_id)
        return slot

    def borrow_ball(
        self,
        borrower_slot_id: str,
        lender_slot_id: str,
        ball_id: str,
        ttl_seconds: int = 300,
        now: Optional[datetime] = None,
    ) -> BorrowedBallLease:
        lender = self.get_slot(lender_slot_id)
        if ball_id not in lender.ball_ids:
            raise PermissionError(
                f"Lender slot {lender_slot_id} does not own ball {ball_id}"
            )
        borrower = self.get_slot(borrower_slot_id)
        ref_now = now or datetime.now(timezone.utc)
        expires = (ref_now + timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
        lease = BorrowedBallLease(
            ball_id=ball_id,
            from_slot=lender.slot_id,
            borrowed_at=ref_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            expires_at=expires,
        )
        borrower.borrowed_balls = [
            b for b in borrower.borrowed_balls if b.ball_id != ball_id
        ]
        borrower.borrowed_balls.append(lease)
        return lease

    def _purge_expired_leases(
        self, slot_id: str, now: Optional[datetime] = None
    ) -> None:
        resolved = self._resolve_slot_id(slot_id)
        slot = self._slots[resolved]
        if not slot.borrowed_balls:
            return
        ref_now = now or datetime.now(timezone.utc)
        slot.borrowed_balls = [
            lease
            for lease in slot.borrowed_balls
            if _parse_iso(lease.expires_at) > ref_now
        ]

    def get_effective_ball_ids(
        self, slot_id: str, now: Optional[datetime] = None
    ) -> set[str]:
        resolved = self._resolve_slot_id(slot_id)
        self._purge_expired_leases(resolved, now=now)
        slot = self._slots[resolved]
        effective = set(slot.ball_ids)
        for lease in slot.borrowed_balls:
            effective.add(lease.ball_id)
        return effective

    def transition_slot_occupant(
        self, slot_id: str, new_occupant_type: OccupantType, new_occupant_id: Optional[str] = None
    ) -> UnitSlot:
        slot = self.get_slot(slot_id)
        slot.occupant_type = new_occupant_type
        if new_occupant_id:
            slot.occupant_id = new_occupant_id
        return slot

    def is_high_subjectivity_slot(self, slot: UnitSlot) -> bool:
        haystack = f"{slot.slot_name} {slot.department}"
        return any(
            kw in haystack
            for kw in (
                "客诉",
                "安抚",
                "投诉",
                "危机公关",
                "商务谈判",
                "大客户公关",
                "法务仲裁",
                "调解",
                "复杂议价",
            )
        )

    def update_slot_replaceability(
        self,
        slot_id: str,
        rule_repetition_ratio: float,
        shadow_agreement_rate: float,
        *,
        skill_coverage: Optional[float] = None,
        exception_discipline_factor: Optional[float] = None,
        soft_skill_ceiling: Optional[float] = None,
        ceiling_reason: str = "",
    ) -> float:
        slot = self.get_slot(slot_id)
        slot.rule_repetition_ratio = round(max(0.0, min(100.0, rule_repetition_ratio)), 2)
        slot.shadow_agreement_rate = round(max(0.0, min(100.0, shadow_agreement_rate)), 2)

        skill_cov = round(
            max(0.0, min(100.0, skill_coverage if skill_coverage is not None else slot.rule_repetition_ratio)),
            2,
        )
        shadow_adopt = slot.shadow_agreement_rate

        if exception_discipline_factor is not None:
            exc_disc = round(max(0.0, min(100.0, exception_discipline_factor)), 2)
        else:
            occupant_prof = self._profiles.get(slot.occupant_id)
            if occupant_prof is not None:
                probes = occupant_prof.management_view.boundary_probes
                rework = occupant_prof.management_view.rework_rate
                exc_disc = round(max(20.0, min(100.0, 100.0 - probes * 12.0 - rework * 80.0)), 2)
            else:
                exc_disc = 95.0

        raw_score = round(
            max(0.0, min(100.0, 0.35 * skill_cov + 0.40 * shadow_adopt + 0.25 * exc_disc)),
            2,
        )
        effective_ceiling: Optional[float] = soft_skill_ceiling
        reason_text = ceiling_reason
        if effective_ceiling is None and self.is_high_subjectivity_slot(slot):
            effective_ceiling = 72.0
            reason_text = reason_text or "高主观协商/客诉安抚岗位触发人工兜底上限 (72.0%)"

        capped = False
        final_score = raw_score
        if effective_ceiling is not None and raw_score > effective_ceiling:
            final_score = round(effective_ceiling, 2)
            capped = True

        slot.replaceability_score = round(max(0.0, min(100.0, final_score)), 2)
        slot.replaceability_breakdown = {
            "skill_coverage": skill_cov,
            "shadow_adoption_rate": shadow_adopt,
            "exception_discipline_factor": exc_disc,
            "raw_unbounded_score": raw_score,
            "soft_skill_ceiling": effective_ceiling if effective_ceiling is not None else 100.0,
            "soft_skill_capped": capped,
            "ceiling_reason": reason_text,
        }
        return slot.replaceability_score

    def record_boundary_probe(self, user_id: str, synced_count: Optional[int] = None) -> DualEmployeeProfile:
        profile = self.get_profile(user_id)
        if synced_count is not None:
            profile.management_view.boundary_probes = synced_count
        else:
            profile.management_view.boundary_probes += 1
        return profile

    def record_rework(self, user_id: str) -> DualEmployeeProfile:
        profile = self.get_profile(user_id)
        profile.management_view.rework_rate = round(
            min(1.0, profile.management_view.rework_rate + 0.05), 3
        )
        return profile

    def record_innovation_bonus(
        self,
        user_id: str,
        skill_title: str,
        bonus_points: float = 18.0,
        saved_hours: float = 4.5,
    ) -> DualEmployeeProfile:
        profile = self.get_profile(user_id)
        if skill_title not in profile.employee_view.evolution_contributions:
            profile.employee_view.evolution_contributions.append(skill_title)
        if "AI流程架构师" not in profile.employee_view.skill_tags:
            profile.employee_view.skill_tags.append("AI流程架构师")
        profile.employee_view.innovation_bonus = round(
            profile.employee_view.innovation_bonus + bonus_points, 2
        )
        profile.employee_view.saved_hours = round(
            profile.employee_view.saved_hours + saved_hours, 2
        )
        return profile

    def project_public_profile(self, user_id: str) -> PublicEmployeeSelfProfile:
        p = self.get_profile(user_id)
        return PublicEmployeeSelfProfile(
            user_id=p.user_id,
            name=p.name,
            title=p.title,
            role_view=p.role_view,
            slot_id=p.slot_id,
            employee_view=p.employee_view.model_copy(deep=True),
        )

    def project_public_slot(self, slot_id: str) -> PublicUnitSlotView:
        s = self.get_slot(slot_id)
        return PublicUnitSlotView(
            slot_id=s.slot_id,
            slot_name=s.slot_name,
            department=s.department,
            occupant_type=s.occupant_type,
            occupant_id=s.occupant_id,
            ball_ids=list(s.ball_ids),
            borrowed_balls=list(s.borrowed_balls),
        )


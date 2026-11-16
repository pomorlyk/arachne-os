from __future__ import annotations

import difflib
import math
from typing import Any, Optional

from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from swarm.pulse_bus import PulseBus


class PreferenceCalibrator:
    """
    领导偏好动态磨合器：
    维护 [speed, zero_error, cost_saving, automation_aggressiveness] 四维权重向量（和恒为 1.0），
    随顶层管理者的每一次批准/驳回动作自适应微调权重倾向。
    """

    def __init__(self) -> None:
        self._weights: dict[str, float] = {
            "speed": 0.25,
            "zero_error": 0.25,
            "cost_saving": 0.25,
            "automation_aggressiveness": 0.25,
        }

    def restore_state(self, state: dict[str, Any] | None) -> None:
        if not state:
            self.__init__()
            return
        raw = state.get("weights", state)
        values = {key: float(raw[key]) for key in self._weights}
        if any(not math.isfinite(v) or v < 0 for v in values.values()) or sum(values.values()) <= 0:
            raise ValueError("Invalid preference weights")
        total = sum(values.values())
        self._weights = {key: value / total for key, value in values.items()}

    def snapshot(self) -> dict[str, float]:
        return {k: round(v, 4) for k, v in self._weights.items()}

    def calibrate_on_boss_feedback(
        self, approved: bool, proposal_focus: str = "AUTOMATION"
    ) -> dict[str, float]:
        delta = 0.04
        if approved and proposal_focus == "AUTOMATION":
            self._weights["automation_aggressiveness"] += delta
            self._weights["speed"] += delta * 0.5
            self._weights["zero_error"] = max(0.08, self._weights["zero_error"] - delta * 0.75)
            self._weights["cost_saving"] = max(0.08, self._weights["cost_saving"] - delta * 0.75)
        elif not approved:
            self._weights["zero_error"] += delta * 1.2
            self._weights["automation_aggressiveness"] = max(
                0.08, self._weights["automation_aggressiveness"] - delta * 0.8
            )
            self._weights["speed"] = max(0.08, self._weights["speed"] - delta * 0.4)

        total = sum(self._weights.values())
        for k in self._weights:
            self._weights[k] = round(self._weights[k] / total, 4)
        return self.snapshot()


class ScoringEngine:
    """
    双轨量化算分引擎：
    1. 岗位【AI 可替代分】= 0.4 * 规则化重复占比 + 0.6 * 后台影子陪跑一致率；
    2. 员工【反向创新综合绩效分】= 基础履约分 + 进化架构师加分 - (8.0 * 越界试探次数)。
    """

    MECHANICAL_PENALTY_ALPHA = 0.0
    BOUNDARY_PROBE_PENALTY_BETA = 8.0

    def __init__(
        self,
        vault: BlackBoxVault,
        containers: ContainerRegistry,
        pulse_bus: PulseBus,
    ) -> None:
        self._vault = vault
        self._containers = containers
        self._pulse = pulse_bus
        self.calibrator = PreferenceCalibrator()

    def export_state(self) -> dict[str, Any]:
        return {"preference_weights": dict(self.calibrator._weights)}

    def restore_state(self, state: dict[str, Any] | None) -> None:
        self.calibrator.restore_state((state or {}).get("preference_weights"))

    def recompute_employee_performance(self, user_id: str) -> float:
        profile = self._containers.get_profile(user_id)
        base = profile.management_view.base_fulfillment_score
        inno_bonus = profile.employee_view.innovation_bonus
        probe_penalty = (
            self.BOUNDARY_PROBE_PENALTY_BETA * profile.management_view.boundary_probes
        )

        raw_perf = base + inno_bonus - probe_penalty
        clamped = round(max(0.0, min(100.0, raw_perf)), 2)
        profile.management_view.performance_score = clamped
        return clamped

    async def on_shadow_trial_completed(
        self,
        user_id: str,
        slot_id: str,
        ai_matched_human: bool = True,
        *,
        ai_draft_text: Optional[str] = None,
        human_final_text: Optional[str] = None,
    ) -> dict[str, Any]:
        slot = self._containers.get_slot(slot_id)
        if ai_draft_text is None or human_final_text is None or not ai_draft_text.strip() or not human_final_text.strip():
            return {
                "replaceability_score": slot.replaceability_score,
                "performance_score": self._containers.get_profile(user_id).management_view.performance_score,
                "replaceability_breakdown": dict(slot.replaceability_breakdown),
                "similarity_ratio": None,
                "evidence_recorded": False,
            }
        left = ai_draft_text.strip()
        right = human_final_text.strip()
        similarity_ratio = round(difflib.SequenceMatcher(None, left, right).ratio(), 4)
        adoption_pct = similarity_ratio * 100.0
        new_shadow = round(0.65 * slot.shadow_agreement_rate + 0.35 * adoption_pct, 2)
        # Text adoption is evidence of agreement, not evidence of repeated-rule coverage.
        new_rep_ratio = slot.rule_repetition_ratio

        rep_score = self._containers.update_slot_replaceability(
            slot_id, new_rep_ratio, new_shadow
        )
        perf_score = self.recompute_employee_performance(user_id)

        target_node_id = self._containers.resolve_node_id_for_slot(slot_id)
        await self._pulse.publish(
            event_type="SCORE_UPDATED",
            node_id=target_node_id,
            subtree_root_id="root",
            severity="INFO",
            summary=(
                f"📊 三维影子算分更新：岗位 [{slot.slot_name}] AI可替代分 {rep_score:.1f} | "
                f"驻守人绩效分 {perf_score:.1f}"
            ),
            payload={
                "slot_id": slot_id,
                "user_id": user_id,
                "replaceability_score": rep_score,
                "replaceability_breakdown": dict(slot.replaceability_breakdown),
                "similarity_ratio": similarity_ratio,
                "performance_score": perf_score,
            },
        )
        return {
            "replaceability_score": rep_score,
            "performance_score": perf_score,
            "replaceability_breakdown": dict(slot.replaceability_breakdown),
            "similarity_ratio": similarity_ratio,
            "evidence_recorded": True,
        }

    async def on_boundary_probe_penalized(self, user_id: str) -> float:
        new_perf = self.recompute_employee_performance(user_id)
        profile = self._containers.get_profile(user_id)
        target_node_id = self._containers.resolve_node_id_for_slot(profile.slot_id)
        await self._pulse.publish(
            event_type="SCORE_UPDATED",
            node_id=target_node_id,
            subtree_root_id="root",
            severity="WARNING",
            summary=(
                f"📉 越界风控扣分：{profile.name} 因刺探红线底价被扣除 {self.BOUNDARY_PROBE_PENALTY_BETA:.0f} 分，"
                f"当前综合绩效降至 {new_perf:.1f}"
            ),
            payload={"user_id": user_id, "performance_score": new_perf},
        )
        return new_perf

    async def award_evolution_architect_bonus(
        self,
        user_id: str,
        skill_title: str,
        bonus_points: float = 24.0,
        saved_hours: float = 5.5,
    ) -> dict[str, Any]:
        profile = self._containers.record_innovation_bonus(
            user_id=user_id,
            skill_title=skill_title,
            bonus_points=bonus_points,
            saved_hours=saved_hours,
        )
        # Publishing a skill does not establish measured human/AI agreement.
        slot = self._containers.get_slot(profile.slot_id)
        rep_score = slot.replaceability_score
        perf_score = self.recompute_employee_performance(user_id)

        self._vault.append_event(
            event_kind="INNOVATION_BONUS_AWARDED",
            subtree_root_id="root",
            actor_slot_id=slot.slot_id,
            payload={
                "user_id": user_id,
                "skill_title": skill_title,
                "bonus_points": bonus_points,
                "new_performance_score": perf_score,
                "new_replaceability_score": rep_score,
            },
        )
        target_node_id = self._containers.resolve_node_id_for_slot(slot.slot_id)
        await self._pulse.publish(
            event_type="SCORE_UPDATED",
            node_id=target_node_id,
            subtree_root_id="root",
            severity="SUCCESS",
            summary=(
                f"🏆 反向创新绩效暴涨：{profile.name} 孵化技能球《{skill_title}》荣获 +{bonus_points:.0f} 进化架构师加分！"
                f"综合绩效跃升至 {perf_score:.1f}（岗位AI可替代分达 {rep_score:.1f}）"
            ),
            payload={
                "user_id": user_id,
                "slot_id": slot.slot_id,
                "performance_score": perf_score,
                "replaceability_score": rep_score,
                "innovation_bonus_total": profile.employee_view.innovation_bonus,
            },
        )
        return {
            "performance_score": perf_score,
            "replaceability_score": rep_score,
            "innovation_bonus_total": profile.employee_view.innovation_bonus,
        }


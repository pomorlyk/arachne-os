from __future__ import annotations

import asyncio
import copy
import math
import uuid
from typing import Any, Optional

from config import ArachneSettings
from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from core.llm_gateway import LLMGateway
from core.human_tool import WorkflowConflictError
from core.particles import ParticleEngine
from core.schemas import BoardResolution, DirectorVote
from database import HotStateStore
from swarm.pulse_bus import PulseBus
from swarm.scoring_engine import ScoringEngine


class BoardOfDirectors:
    """
    顶层自适应董事会 (BoardOfDirectors)：
    1. 永恒铁三角席位：SecurityDirector（安全红线官，拥有一票否决权）、EvolutionDirector（进化效率官）、CostDirector（算力成本官）；
    2. 动态业务域席位：随蛛网横向聚类出的活跃 ASPECT_NODE 自动增减领域董事；
    3. 并发独立盲评：严禁单次请求精分扮演多人，强制使用 asyncio.gather 并发发起相互独立的董事推理！
    """

    def __init__(
        self,
        settings: ArachneSettings,
        vault: BlackBoxVault,
        hot_store: HotStateStore,
        particles: ParticleEngine,
        containers: ContainerRegistry,
        llm_gateway: LLMGateway,
        scoring: ScoringEngine,
        pulse_bus: PulseBus,
    ) -> None:
        self._settings = settings
        self._vault = vault
        self._hot_store = hot_store
        self._particles = particles
        self._containers = containers
        self._llm = llm_gateway
        self._scoring = scoring
        self._pulse = pulse_bus
        self._resolutions: list[BoardResolution] = []
        self._boss_decisions: dict[str, dict[str, Any]] = {}
        self._decision_lock = asyncio.Lock()

    def export_state(self) -> dict[str, Any]:
        return {"resolutions": [r.model_dump() for r in self._resolutions],
                "boss_decisions": copy.deepcopy(self._boss_decisions)}

    def restore_state(self, state: dict[str, Any] | None) -> None:
        self._resolutions = [BoardResolution(**r) for r in (state or {}).get("resolutions", [])]
        self._boss_decisions = copy.deepcopy((state or {}).get("boss_decisions", {}))

    def list_resolutions(self) -> list[BoardResolution]:
        return list(reversed(self._resolutions))

    async def convene(
        self,
        agenda: str = "审议【核心一线工位】启动师徒反转（HYBRID_TRANSITION）接管议案",
        target_slot_id: Optional[str] = None,
        force_security_veto: bool = False,
    ) -> BoardResolution:
        resolved_slot_id = target_slot_id or ""
        if not resolved_slot_id or resolved_slot_id not in self._containers._slots:
            all_slots = self._containers.list_slots()
            non_boss = [s for s in all_slots if s.slot_id != "SLOT_BOSS"]
            if non_boss:
                resolved_slot_id = non_boss[0].slot_id
            elif all_slots:
                resolved_slot_id = all_slots[0].slot_id
        slot = self._containers.get_slot(resolved_slot_id)
        target_slot_id = slot.slot_id
        all_nodes = await self._hot_store.list_nodes()
        all_tickets = await self._hot_store.list_tickets()
        dehydrated_count = sum(1 for n in all_nodes if n.status == "DEHYDRATED")
        dehydrated_ratio = (
            dehydrated_count / len(all_nodes) if all_nodes else 0.0
        )
        active_skills = sum(
            1
            for b in self._particles.list_all_balls()
            if b.ball_type == "SKILL" and b.status == "ACTIVE"
        )
        vault_report = self._vault.verify_chain_integrity()

        target_node_id = self._containers.resolve_node_id_for_slot(target_slot_id)
        target_node = next(
            (n for n in all_nodes if n.node_id == target_node_id), None
        )
        target_home_subtree = target_node.subtree_root_id if target_node else ""
        slot_tags: set[str] = set()
        if slot.department:
            slot_tags.add(slot.department.lower())
        if target_node:
            slot_tags.update(t.lower() for t in target_node.domain_tags)
        for bid in slot.ball_ids:
            ball = self._particles.get_ball(bid)
            if ball:
                slot_tags.update(t.lower() for t in ball.domain_tags)

        context_metrics: dict[str, Any] = {
            "target_slot_id": target_slot_id,
            "slot_name": slot.slot_name,
            "replaceability_score": slot.replaceability_score,
            "rule_repetition_ratio": slot.rule_repetition_ratio,
            "shadow_agreement_rate": slot.shadow_agreement_rate,
            "active_skill_balls": active_skills,
            "dehydrated_ratio": round(dehydrated_ratio, 3),
            "vault_intact": vault_report.intact,
            "force_security_veto": force_security_veto,
        }

        # 组装永恒铁三角 (3席) + 按关联度筛选的动态业务域董事 (上限4席，总席位 <= 7)
        roster: list[tuple[str, str, str]] = [
            ("DIR_SECURITY", "安全红线官 (SecurityDirector)", "IRON_TRIANGLE"),
            ("DIR_EVOLUTION", "进化效率官 (EvolutionDirector)", "IRON_TRIANGLE"),
            ("DIR_COST", "算力成本官 (CostDirector)", "IRON_TRIANGLE"),
        ]
        aspect_nodes = [n for n in all_nodes if n.node_type == "ASPECT_NODE"]
        ranked_aspects: list[tuple[float, Any, dict[str, Any]]] = []
        for asp in aspect_nodes:
            asp_subtree = asp.subtree_root_id or asp.node_id
            unique_subtree = {
                n.node_id: n
                for n in all_nodes
                if n.node_id == asp.node_id
                or n.subtree_root_id == asp_subtree
                or n.parent_id == asp.node_id
            }
            subtree_nodes = list(unique_subtree.values())
            subtree_ids = set(unique_subtree.keys())
            is_home = bool(
                (target_home_subtree and asp_subtree == target_home_subtree)
                or (target_node and target_node.node_id in subtree_ids)
                or (
                    slot.department
                    and (slot.department in asp.label or asp.label in slot.department)
                )
            )
            dept_tickets = sum(
                1
                for t in all_tickets
                if t.subtree_root_id == asp_subtree or t.node_id in subtree_ids
            )
            has_blackbox = any(
                n.node_type == "BLACKBOX_HUMAN" for n in subtree_nodes
            )
            asp_dehydrated = sum(
                1 for n in subtree_nodes if n.status == "DEHYDRATED"
            )
            asp_tags = {t.lower() for n in subtree_nodes for t in n.domain_tags}
            tag_overlap = len(slot_tags & asp_tags)
            if any(len(tok) >= 2 and tok in asp.label.lower() for tok in slot_tags):
                tag_overlap += 1
            affinity = (
                (100.0 if is_home else 0.0)
                + tag_overlap * 12.0
                + dept_tickets * 4.0
                + len(subtree_nodes) * 2.0
                + (3.0 if has_blackbox else 0.0)
                - asp_dehydrated * 1.0
            )
            metrics = {
                "aspect_node_id": asp.node_id,
                "department_name": asp.label,
                "is_target_home_dept": is_home,
                "dept_ticket_count": dept_tickets,
                "has_blackbox_node": has_blackbox,
                "dehydrated_count": asp_dehydrated,
                "domain_tag_overlap": tag_overlap,
                "subtree_node_count": len(subtree_nodes),
                "affinity_score": round(affinity, 2),
            }
            ranked_aspects.append((affinity, asp, metrics))

        ranked_aspects.sort(key=lambda item: (-item[0], item[1].node_id))
        selected_aspects = ranked_aspects[:4]
        dept_metrics_by_id: dict[str, dict[str, Any]] = {}
        for idx, (_aff, asp, metrics) in enumerate(selected_aspects, start=1):
            d_id = f"DIR_DOMAIN_{idx:02d}"
            metrics["seat_rank"] = idx
            dept_metrics_by_id[d_id] = metrics
            roster.append((d_id, f"{asp.label}代表董事", "DYNAMIC_DOMAIN"))

        # 并发独立盲评（asyncio.gather 并发发出独立推理）
        vote_tasks = [
            self._llm.evaluate_board_director(
                director_id=d_id,
                director_title=d_title,
                seat_type=s_type,
                agenda=agenda,
                context_metrics=context_metrics,
                department_metrics=dept_metrics_by_id.get(d_id),
            )
            for (d_id, d_title, s_type) in roster
        ]
        votes: list[DirectorVote] = list(await asyncio.gather(*vote_tasks))

        # 检查安全红线官是否行使一票否决权 (VETO)
        veto_votes = [v for v in votes if v.stance == "VETO"]
        prefs = self._scoring.calibrator.snapshot()

        if veto_votes:
            veto_reason = veto_votes[0].rationale
            resolution = BoardResolution(
                resolution_id=f"RES_{uuid.uuid4().hex[:8].upper()}",
                agenda=agenda,
                target_slot_id=target_slot_id,
                vetoed=True,
                veto_reason=veto_reason,
                weighted_score=0.0,
                recommended_action="REJECTED_BY_VETO",
                preference_weights_snapshot=prefs,
                votes=votes,
                executive_brief=(
                    f"⛔【#3 董事会内参 · 一票否决】议案《{agenda}》已被安全红线官行使一票否决权驳回！原因：{veto_reason}"
                ),
                status="REJECTED",
            )
        else:
            # 结合老板偏好动态权重向量进行加权计分
            weighted_sum = 0.0
            weight_total = 0.0
            for v in votes:
                if v.director_id == "DIR_SECURITY":
                    w = prefs["zero_error"]
                elif v.director_id == "DIR_EVOLUTION":
                    w = prefs["automation_aggressiveness"]
                elif v.director_id == "DIR_COST":
                    w = prefs["cost_saving"]
                else:
                    w = prefs["speed"] / max(1, len(selected_aspects))
                weighted_sum += v.score * w
                weight_total += w

            final_score = round(
                weighted_sum / weight_total if weight_total > 0 else 0.0, 2
            )
            can_transition = (
                slot.replaceability_score
                >= self._settings.replaceability_transition_threshold
                and final_score >= 75.0
            )
            action = (
                "APPROVE_HYBRID_TRANSITION"
                if can_transition
                else "MAINTAIN_HUMAN"
            )
            brief = (
                f"📋【#3 董事会内参 · 决议折子】\n"
                f"• 审议事项：{agenda}\n"
                f"• 列席阵容：永恒铁三角 3 席 + 关联度最高动态业务域董事 {len(selected_aspects)}/{len(aspect_nodes)} 席（总席位 {len(roster)}/7，并发盲评完成）\n"
                f"• 岗位 AI 可替代分：{slot.replaceability_score:.1f} / 100 | 董事会加权赞成度：{final_score:.1f} / 100\n"
                f"• 建议行动：{'建议立即批准该岗位进入【师徒反转过渡期 (HYBRID_TRANSITION)】，由 Agent 主导输出、原员工抽检签字' if can_transition else '建议继续维持真人主导并积累更多技能球样本'}。"
            )
            resolution = BoardResolution(
                resolution_id=f"RES_{uuid.uuid4().hex[:8].upper()}",
                agenda=agenda,
                target_slot_id=target_slot_id,
                vetoed=False,
                weighted_score=final_score,
                recommended_action=action,  # type: ignore[arg-type]
                preference_weights_snapshot=prefs,
                votes=votes,
                executive_brief=brief,
                status="PENDING_BOSS",
            )

        self._resolutions.append(resolution)
        self._vault.append_event(
            event_kind="BOARD_RESOLUTION_ISSUED",
            subtree_root_id="root",
            actor_slot_id="SLOT_BOSS",
            payload={
                "resolution_id": resolution.resolution_id,
                "target_slot_id": target_slot_id,
                "vetoed": resolution.vetoed,
                "weighted_score": resolution.weighted_score,
                "recommended_action": resolution.recommended_action,
            },
        )
        await self._pulse.publish(
            event_type="BOARD_PROPOSAL",
            node_id="node_board_root",
            subtree_root_id="root",
            severity="WARNING" if resolution.vetoed else "SUCCESS",
            summary=(
                f"🏛️ 董事会决议出炉 [{resolution.resolution_id}]：加权得分 {resolution.weighted_score:.1f} "
                f"→ {resolution.recommended_action}"
            ),
            payload=resolution.model_dump(),
        )
        return resolution

    async def apply_boss_decision(
        self, resolution_id: str, approve: bool
    ) -> dict[str, Any]:
        async with self._decision_lock:
            return await self._apply_boss_decision_locked(resolution_id, approve)

    async def _apply_boss_decision_locked(self, resolution_id: str, approve: bool) -> dict[str, Any]:
        target: BoardResolution | None = None
        for r in self._resolutions:
            if r.resolution_id == resolution_id:
                target = r
                break
        if target is None:
            raise KeyError(f"BoardResolution {resolution_id} not found")
        if target.vetoed and approve:
            raise PermissionError(
                "被安全红线官一票否决（VETO）的议案严禁强行批准上线"
            )

        decided_status = "APPROVED" if approve else "REJECTED"
        if target.status != "PENDING_BOSS":
            if target.status != decided_status:
                raise WorkflowConflictError("董事会终局决策不能被反向重提交覆盖")
            saved = self._boss_decisions.get(resolution_id, {})
            return {
                "resolution": target,
                "updated_slot": self._containers.get_slot(target.target_slot_id) if approve and target.target_slot_id else None,
                "preference_weights": saved.get("preference_weights", self._scoring.calibrator.snapshot()),
            }
        if approve:
            if not target.target_slot_id:
                raise ValueError("缺少目标岗位")
            slot = self._containers.get_slot(target.target_slot_id)
            if (target.recommended_action != "APPROVE_HYBRID_TRANSITION"
                    or not math.isfinite(target.weighted_score)
                    or not math.isfinite(slot.replaceability_score)
                    or target.weighted_score < 75.0
                    or slot.replaceability_score < self._settings.replaceability_transition_threshold):
                raise ValueError("议案尚未满足独立评估、董事会建议和岗位接管阈值")
            if any(v.stance == "VETO" for v in target.votes):
                raise PermissionError("存在一票否决的议案严禁批准")

        new_weights = self._scoring.calibrator.calibrate_on_boss_feedback(
            approved=approve, proposal_focus="AUTOMATION"
        )
        target.status = "APPROVED" if approve else "REJECTED"

        updated_slot = None
        if approve and target.target_slot_id:
            updated_slot = self._containers.transition_slot_occupant(
                slot_id=target.target_slot_id,
                new_occupant_type="HYBRID_TRANSITION",
            )
            self._vault.append_event(
                event_kind="SLOT_TRANSITIONED_TO_HYBRID",
                subtree_root_id="root",
                actor_slot_id="SLOT_BOSS",
                payload={
                    "resolution_id": resolution_id,
                    "slot_id": updated_slot.slot_id,
                    "new_occupant_type": updated_slot.occupant_type,
                    "calibrated_weights": new_weights,
                },
            )
            all_nodes = await self._hot_store.list_nodes()
            slot_node = next((n for n in all_nodes if n.slot_id == updated_slot.slot_id), None)
            await self._pulse.publish(
                event_type="SLOT_TRANSITIONED",
                node_id=slot_node.node_id if slot_node else "node_board_root",
                subtree_root_id=slot_node.subtree_root_id if slot_node else "root",
                severity="SUCCESS",
                summary=(
                    f"🔄 师徒反转正式生效：老板已拍板批准 [{updated_slot.slot_name}] 切换为 "
                    "HYBRID_TRANSITION（AI 主导执行 + 真人抽检签字）！"
                ),
                payload={
                    "slot_id": updated_slot.slot_id,
                    "occupant_type": updated_slot.occupant_type,
                    "preference_weights": new_weights,
                },
            )

        self._boss_decisions[resolution_id] = {
            "approve": approve, "preference_weights": dict(new_weights),
        }
        return {
            "resolution": target,
            "updated_slot": updated_slot,
            "preference_weights": new_weights,
        }


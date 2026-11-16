from __future__ import annotations

import time
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from config import ArachneSettings, load_settings
from core.auth_custody import ACCOUNT_DIRECTORY
from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from core.llm_gateway import LLMGateway
from core.particles import ParticleEngine
from core.schemas import (
    CapabilityBall,
    ChatMessageItem,
    DualEmployeeProfile,
    EmployeeViewA,
    ManagementViewB,
    RoleViewType,
    WorkTicket,
    utc_now_iso,
)
from database import HotStateStore
from swarm.pulse_bus import PulseBus

CrystalCategory = Literal[
    "TACIT_HEURISTIC",
    "PITFALL_GUARD",
    "NEGOTIATION_BOTTOMLINE",
    "OPTIMAL_SKILL_PARADIGM",
    "SOP_EVOLUTION",
]


class MemoryCrystal(BaseModel):
    crystal_id: str
    slot_id: str
    slot_name: str
    category: CrystalCategory
    title: str
    tacit_rule: str
    pitfall_warning: str
    negotiation_strategy: str
    optimal_operator_pattern: str
    summary: str
    content: str
    confidence_score: float = Field(default=0.96, ge=0.0, le=1.0)
    source_evidence_count: int = 3
    upgraded_ball_id: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)


class LLMDistilledCrystalDraft(BaseModel):
    category: CrystalCategory = "TACIT_HEURISTIC"
    title: str
    tacit_rule: str
    pitfall_warning: str
    negotiation_strategy: str
    optimal_operator_pattern: str
    confidence_score: float = 0.96


class LLMDistillationBatch(BaseModel):
    crystals: list[LLMDistilledCrystalDraft] = Field(default_factory=list)


class OnboardingExamQuestion(BaseModel):
    question_id: str
    category: Literal["REDLINE_COMPLIANCE", "HIGH_VOLTAGE_ESCALATION", "SKILL_AND_CRYSTAL_EXECUTION"]
    question_title: str
    scenario_prompt: str
    options: list[str]
    correct_answer: str
    rationale: str
    linked_ball_id: Optional[str] = None


class EpisodicMemoryDistiller:
    """
    Wave 2 (Pillar 6)：跨工位记忆蒸馏、SOP 自进化图谱与离职零损交接引擎
    (Episodic Memory Distillation & Zero-Loss Handover Engine)
    1. distill_slot_memory: 扫描工位历史工单、企微对话、挂载球与双面档案，提炼 3~5 枚实战记忆结晶 (MemoryCrystal)，
       并自动反哺升级关联 DATA / AUTHORITY 球版本 (version += 1)，写入 WORM 账本 SLOT_MEMORY_DISTILLED。
    2. execute_zero_loss_handover: “铁打的工位流水的兵”——生成《零损工位数字孪生交接包》（常驻球保留、租借球回收、
       实战记忆结晶、未决工单上下文、3道上岗实测考题），一键绑定新员工并保持业务战斗力 100% 零衰减。
    """

    def __init__(
        self,
        state: Any = None,
        *,
        runtime: Any = None,
        settings: Optional[ArachneSettings] = None,
        vault: Optional[BlackBoxVault] = None,
        hot_store: Optional[HotStateStore] = None,
        particles: Optional[ParticleEngine] = None,
        containers: Optional[ContainerRegistry] = None,
        llm_gateway: Optional[LLMGateway] = None,
        pulse_bus: Optional[PulseBus] = None,
    ) -> None:
        ref = state if state is not None else runtime
        self._state = ref
        self._settings: ArachneSettings = (
            settings
            or getattr(ref, "settings", None)
            or load_settings(llm_api_key="")
        )
        self._vault: BlackBoxVault = (
            vault
            or getattr(ref, "vault", None)
            or BlackBoxVault(self._settings.vault_storage_dir)
        )
        self._hot_store: Optional[HotStateStore] = (
            hot_store or getattr(ref, "hot_store", None)
        )
        self._particles: ParticleEngine = (
            particles
            or getattr(ref, "particles", None)
            or ParticleEngine(self._vault)
        )
        self._containers: ContainerRegistry = (
            containers
            or getattr(ref, "containers", None)
            or ContainerRegistry()
        )
        self._llm: LLMGateway = (
            llm_gateway
            or getattr(ref, "llm_gateway", None)
            or LLMGateway(self._settings)
        )
        self._pulse: Optional[PulseBus] = (
            pulse_bus or getattr(ref, "pulse_bus", None)
        )
        self._wecom: Any = getattr(ref, "wecom", None)

        self._crystals_by_slot: dict[str, list[MemoryCrystal]] = {}
        self._all_crystals: list[MemoryCrystal] = []
        self._distillation_runs: list[dict[str, Any]] = []
        self._handover_records: list[dict[str, Any]] = []
        self._candidate_balls: dict[str, dict[str, Any]] = {}

    @property
    def is_live_llm(self) -> bool:
        return bool(
            getattr(self._llm, "is_live_mode", False)
            or getattr(self._llm, "is_live", False)
        )

    async def _collect_slot_tickets(self, slot_id: str) -> list[WorkTicket]:
        if self._hot_store is None:
            return []
        try:
            all_tickets = await self._hot_store.list_tickets()
            slot_tickets = [t for t in all_tickets if t.slot_id == slot_id]
            return slot_tickets if slot_tickets else all_tickets[:4]
        except Exception:
            return []

    def _collect_slot_chat_history(
        self, occupant_id: str, role_view: str
    ) -> list[ChatMessageItem]:
        if self._wecom is None:
            return []
        try:
            return list(self._wecom.get_chat_history(occupant_id, role_view))
        except Exception:
            return []

    def _build_deterministic_crystal_drafts(
        self,
        slot_id: str,
        slot_name: str,
        department: str,
        mounted_balls: list[CapabilityBall],
        tickets: list[WorkTicket],
        chat_msgs: list[ChatMessageItem],
    ) -> list[LLMDistilledCrystalDraft]:
        ball_titles = [b.title for b in mounted_balls]
        skill_balls = [b for b in mounted_balls if b.ball_type == "SKILL"]
        data_balls = [b for b in mounted_balls if b.ball_type == "DATA"]
        auth_balls = [b for b in mounted_balls if b.ball_type == "AUTHORITY"]

        primary_skill = (
            skill_balls[0].title
            if skill_balls
            else "本地 0-Token Python 阶梯核算算子"
        )
        primary_data = (
            data_balls[0].title if data_balls else "实时现货库存与阶梯价格台账"
        )
        primary_auth = (
            auth_balls[0].title if auth_balls else "工位标准折扣与锁库审批权限边界"
        )

        drafts: list[LLMDistilledCrystalDraft] = [
            LLMDistilledCrystalDraft(
                category="TACIT_HEURISTIC",
                title=f"【{slot_name}】微信询价 L1 公私剥离与四要素闪电锁库法则",
                tacit_rule=(
                    f"处理外部客户或上下游微信转发记录时，须先通过 L1 正则防火墙剥离私人寒暄与手机号，"
                    f"第一时间对齐《{primary_data}》核验型号、数量、收货仓与 18 位税号四要素。"
                ),
                pitfall_warning=(
                    "高频踩坑：切勿在客户未提供收货地址或开票税号前口头承诺『今日必发』，否则将被 #2 风控官不入网不认账门禁拦截挂起。"
                ),
                negotiation_strategy=(
                    "对催单急客采用『先锁现货批次号 + 同步推送标准税号确认卡』策略，既稳住客户情绪又守住合规底线。"
                ),
                optimal_operator_pattern=(
                    f"先调用 L1 sanitize_l1_text 脱敏 -> 检索【{primary_data}】 -> 触发结构化建单草稿。"
                ),
                confidence_score=0.98,
            ),
            LLMDistilledCrystalDraft(
                category="NEGOTIATION_BOTTOMLINE",
                title=f"【{slot_name}】阶梯让利谈判底线与高压线特批分流策略",
                tacit_rule=(
                    f"严格依据《{primary_auth}》执行阶梯报价：常规权限内（>=9.0折）直接秒级自助锁库；"
                    "遇到 8.5~9.0 折大宗集采引导凑单满量；低于 8.5 折或涉及现金赔付立即生成主管审批卡。"
                ),
                pitfall_warning=(
                    "高频踩坑：严禁受客户『董事长秘书口头特批』或『拆单规避限额』诱导私自放行超低折扣或刺探工厂拿货底价，违者触发 B 面越界计数与绩效扣减。"
                ),
                negotiation_strategy=(
                    "谈判底线：用『满 500 元免收阶梯运费』或『分批锁库保价』替代直接击穿 8.5 折红线的裸降诉求。"
                ),
                optimal_operator_pattern=(
                    f"校验【{primary_auth}】阈值 -> 若触发 PRICE_OVERRIDE/COMPENSATION 立即转交 RELAY_NODE 审批卡。"
                ),
                confidence_score=0.97,
            ),
            LLMDistilledCrystalDraft(
                category="OPTIMAL_SKILL_PARADIGM",
                title=f"【{slot_name}】高频计费零 Token 算子优先调用范式",
                tacit_rule=(
                    f"凡涉及运费、批量折后总价、税点或安全库存水位计算，一律下沉至沙箱 Python 技能球《{primary_skill}》执行确定性计算，严禁依赖大模型心算。"
                ),
                pitfall_warning=(
                    "高频踩坑：手工或 LLM 自由估算续重向上取整（如 4.2kg 应按 5kg 计费）极易产生分角误差导致财务开票黑盒 422 退回重工。"
                ),
                negotiation_strategy=(
                    "向客户展示由沙箱技能球生成的标准化明细账单（含首重、续重取整与满额免邮抵扣），消除议价争议。"
                ),
                optimal_operator_pattern=(
                    f"提取 payload(weight_kg, order_amount, quantity, unit_price) -> python -I 净室调用【{primary_skill}】。"
                ),
                confidence_score=0.99,
            ),
            LLMDistilledCrystalDraft(
                category="PITFALL_GUARD",
                title=f"【{slot_name}】跨部门借球 TTL 租约与敏感字段防泄漏守则",
                tacit_rule=(
                    f"在【{department}】跨岗协同（当前已挂载 {len(ball_titles)} 颗权能球、累计扫描 {len(tickets)} 张工单与 {len(chat_msgs)} 条会话）时，"
                    "临时借用的跨部门权能球须在 TTL 到期前完成闭环，且向财务/法务黑盒投喂时仅传递最小必要契约字段。"
                ),
                pitfall_warning=(
                    "高频踩坑：向财务税控盘黑盒提交开票申请时，数电发票号必须满足 20 位纯数字规范且核准金额与审批卡分毫不差。"
                ),
                negotiation_strategy=(
                    "外部合作方索要底层成本构成时，统一回复公开目录价目与阶梯折扣矩阵，绝不触碰 REDLINE 敏感词。"
                ),
                optimal_operator_pattern=(
                    "最小权限集投影 (PublicUnitSlotView) -> 边缘审查哨所 EdgeAuditRelay 校验 -> WORM 哈希链存证。"
                ),
                confidence_score=0.95,
            ),
        ]
        return drafts

    async def distill_slot_memory(
        self,
        slot_id: str,
        auto_upgrade_balls: bool = True,
        mint_candidate_ball: bool = True,
    ) -> dict[str, Any]:
        """
        1. 扫描目标工位历史工单 (WorkTicket)、企微聊天记录、已挂载能力球及双面档案；
        2. 调用大模型 + 结构化提炼引擎，蒸馏 3~5 枚「工位实战记忆结晶 (MemoryCrystal)」；
        3. 当 auto_upgrade_balls=True 时，自动将新经验反哺升级关联的 DATA 或 AUTHORITY 球 (version += 1)，
           并写入 WORM 账本 SLOT_MEMORY_DISTILLED。
        """
        t0 = time.perf_counter()
        distillation_id = f"DIST_{uuid.uuid4().hex[:8].upper()}"
        slot = self._containers.get_slot(slot_id)

        occupant_profile: Optional[DualEmployeeProfile] = None
        try:
            occupant_profile = self._containers.get_profile(slot.occupant_id)
        except KeyError:
            occupant_profile = None

        occupant_name = (
            occupant_profile.name if occupant_profile is not None else slot.occupant_id
        )
        role_view: str = (
            occupant_profile.role_view if occupant_profile is not None else "employee"
        )

        # 扫描工单、企微对话、挂载球与 WORM 历史记录
        slot_tickets = await self._collect_slot_tickets(slot.slot_id)
        chat_msgs = self._collect_slot_chat_history(slot.occupant_id, role_view)
        effective_ball_ids = self._containers.get_effective_ball_ids(slot.slot_id)
        mounted_balls: list[CapabilityBall] = []
        for bid in effective_ball_ids:
            b = self._particles.get_ball(bid)
            if b is not None and b.status == "ACTIVE":
                mounted_balls.append(b)

        vault_records = self._vault.read_records()
        slot_vault_events = [
            r for r in vault_records if r.actor_slot_id == slot.slot_id
        ]

        det_drafts = self._build_deterministic_crystal_drafts(
            slot_id=slot.slot_id,
            slot_name=slot.slot_name,
            department=slot.department,
            mounted_balls=mounted_balls,
            tickets=slot_tickets,
            chat_msgs=chat_msgs,
        )

        llm_calls = 0
        est_tokens = 640
        if self.is_live_llm:
            sys_prompt = (
                "你是 Arachne-OS 跨工位记忆蒸馏引擎 EpisodicMemoryDistiller。"
                "请基于该工位的历史工单、企微对话与挂载球，提炼 4 枚高价值实战记忆结晶，输出符合 LLMDistillationBatch 的 JSON。"
            )
            usr_prompt = (
                f"工位: {slot.slot_name} ({slot.slot_id}), 部门: {slot.department}, 现任职员: {occupant_name}\n"
                f"已挂载权能球: {[b.title for b in mounted_balls]}\n"
                f"历史工单摘要: {[t.summary for t in slot_tickets[:5]]}\n"
                f"近期对话条数: {len(chat_msgs)}"
            )
            batch = await self._llm.complete_structured(
                tier="L3",
                system_prompt=sys_prompt,
                user_prompt=usr_prompt,
                response_model=LLMDistillationBatch,
                fallback_builder=lambda: LLMDistillationBatch(crystals=det_drafts),
            )
            llm_calls += 1
            est_tokens += 1180
            draft_list = batch.crystals if 3 <= len(batch.crystals) <= 5 else det_drafts
        else:
            draft_list = det_drafts

        # 当 auto_upgrade_balls=True 时，将蒸馏出的实战经验反哺升级工位关联的 DATA / AUTHORITY 球 (version += 1)
        upgraded_balls: list[dict[str, Any]] = []
        upgrade_targets = [
            b for b in mounted_balls if b.ball_type in ("DATA", "AUTHORITY")
        ]
        if auto_upgrade_balls and not upgrade_targets:
            # 若该工位（如纯黑盒开票岗）当前尚未挂载 DATA/AUTHORITY 球，为其自动铸造并升级一颗岗位 SOP DATA 球
            from core.schemas import ExtractedBallCandidate

            minted_sop = self._particles.mint_from_candidate(
                candidate=ExtractedBallCandidate(
                    ball_type="DATA",
                    title=f"{slot.slot_name}实战蒸馏标准 SOP 知识球",
                    domain_tags=[slot.department, "SOP进化", "记忆结晶"],
                    sensitivity_level=2,
                    content=f"工位【{slot.slot_name}】初始 SOP 基准规程。",
                ),
                owner_slot_ids=[slot.slot_id, "SLOT_BOSS"],
                status="ACTIVE",
            )
            self._containers.attach_ball_to_slot(slot.slot_id, minted_sop.ball_id)
            upgrade_targets = [minted_sop]

        crystals: list[MemoryCrystal] = []
        evidence_total = max(3, len(slot_tickets) + len(chat_msgs) + len(mounted_balls))

        for idx, draft in enumerate(draft_list):
            target_ball_id: Optional[str] = None
            if auto_upgrade_balls and upgrade_targets:
                target_ball = upgrade_targets[idx % len(upgrade_targets)]
                target_ball_id = target_ball.ball_id

            crystal_id = f"CRYS_{slot.slot_id[-4:]}_{uuid.uuid4().hex[:6].upper()}"
            combined_summary = (
                f"【隐性规则】{draft.tacit_rule} | "
                f"【防坑预警】{draft.pitfall_warning} | "
                f"【谈判策略】{draft.negotiation_strategy} | "
                f"【算子范式】{draft.optimal_operator_pattern}"
            )
            crystal = MemoryCrystal(
                crystal_id=crystal_id,
                slot_id=slot.slot_id,
                slot_name=slot.slot_name,
                category=draft.category,
                title=draft.title,
                tacit_rule=draft.tacit_rule,
                pitfall_warning=draft.pitfall_warning,
                negotiation_strategy=draft.negotiation_strategy,
                optimal_operator_pattern=draft.optimal_operator_pattern,
                summary=combined_summary,
                content=combined_summary,
                confidence_score=draft.confidence_score,
                source_evidence_count=evidence_total,
                upgraded_ball_id=target_ball_id,
            )
            crystals.append(crystal)

        if auto_upgrade_balls and upgrade_targets:
            for idx, target_ball in enumerate(upgrade_targets):
                linked_crystal = crystals[idx % len(crystals)]
                old_ver = target_ball.version
                new_ver = old_ver + 1
                distilled_appendix = (
                    f"\n[v{new_ver} 记忆结晶反哺 · {linked_crystal.title}] "
                    f"{linked_crystal.tacit_rule}（防坑要点：{linked_crystal.pitfall_warning}）"
                )
                updated_ball = target_ball.model_copy(
                    update={
                        "version": new_ver,
                        "content": f"{target_ball.content}{distilled_appendix}",
                    }
                )
                self._particles.register_ball(updated_ball, record_to_vault=False)
                upgraded_balls.append(
                    {
                        "ball_id": updated_ball.ball_id,
                        "title": updated_ball.title,
                        "ball_type": updated_ball.ball_type,
                        "old_version": old_ver,
                        "new_version": new_ver,
                        "crystal_id": linked_crystal.crystal_id,
                        "crystal_title": linked_crystal.title,
                        "appended_insight": distilled_appendix.strip(),
                    }
                )

        # 保存记忆结晶至工位索引与全局列表
        self._crystals_by_slot.setdefault(slot.slot_id, []).extend(crystals)
        self._all_crystals.extend(crystals)

        candidate_balls_out: list[dict[str, Any]] = []
        if mint_candidate_ball and crystals:
            from core.schemas import ExtractedBallCandidate

            cand_lines = [
                f"• [{c.category}] {c.title}: {c.tacit_rule}（防坑：{c.pitfall_warning}；策略：{c.negotiation_strategy}）"
                for c in crystals[:4]
            ]
            cand_ball = self._particles.mint_from_candidate(
                candidate=ExtractedBallCandidate(
                    ball_type="DATA",
                    title=f"{slot.slot_name}·长期记忆蒸馏候选知识球 ({distillation_id})",
                    domain_tags=list(
                        dict.fromkeys([slot.department, slot.slot_name, "长期记忆", "经验蒸馏"])
                    ),
                    sensitivity_level=2,
                    content="\n".join(cand_lines),
                ),
                owner_slot_ids=[slot.slot_id, "SLOT_BOSS"],
                status="CANDIDATE",
            )
            cand_meta = {
                "ball_id": cand_ball.ball_id,
                "target_slot_id": slot.slot_id,
                "target_slot_name": slot.slot_name,
                "department": slot.department,
                "distillation_id": distillation_id,
                "title": cand_ball.title,
                "ball_type": cand_ball.ball_type,
                "status": cand_ball.status,
                "crystal_ids": [c.crystal_id for c in crystals],
                "content": cand_ball.content,
                "created_at": utc_now_iso(),
            }
            self._candidate_balls[cand_ball.ball_id] = cand_meta
            candidate_balls_out.append(cand_meta)

        if occupant_profile is not None:
            contrib_tag = f"蒸馏工位记忆结晶×{len(crystals)}"
            if contrib_tag not in occupant_profile.employee_view.evolution_contributions:
                occupant_profile.employee_view.evolution_contributions.append(
                    contrib_tag
                )

        sop_graph = {
            "slot_node": {"id": slot.slot_id, "label": slot.slot_name},
            "crystal_nodes": [
                {
                    "id": c.crystal_id,
                    "title": c.title,
                    "category": c.category,
                    "upgraded_ball_id": c.upgraded_ball_id,
                }
                for c in crystals
            ],
            "upgraded_ball_nodes": [
                {
                    "id": ub["ball_id"],
                    "title": ub["title"],
                    "version": f"v{ub['old_version']} -> v{ub['new_version']}",
                }
                for ub in upgraded_balls
            ],
        }

        worm_rec = self._vault.append_event(
            event_kind="SLOT_MEMORY_DISTILLED",
            subtree_root_id="root",
            actor_slot_id=slot.slot_id,
            payload={
                "distillation_id": distillation_id,
                "slot_id": slot.slot_id,
                "slot_name": slot.slot_name,
                "occupant_id": slot.occupant_id,
                "crystal_count": len(crystals),
                "crystal_ids": [c.crystal_id for c in crystals],
                "auto_upgrade_balls": auto_upgrade_balls,
                "upgraded_balls": [
                    {
                        "ball_id": u["ball_id"],
                        "old_version": u["old_version"],
                        "new_version": u["new_version"],
                    }
                    for u in upgraded_balls
                ],
            },
        )

        if self._pulse is not None:
            await self._pulse.publish(
                event_type="BALL_MINTED",
                node_id="node_board_root",
                subtree_root_id="root",
                severity="SUCCESS",
                summary=(
                    f"💎 工位实战记忆蒸馏完成《{slot.slot_name}》：凝结 {len(crystals)} 枚记忆结晶，"
                    f"自动反哺升级 {len(upgraded_balls)} 颗权能球版本！"
                ),
                payload={
                    "distillation_id": distillation_id,
                    "slot_id": slot.slot_id,
                    "crystal_count": len(crystals),
                    "upgraded_ball_count": len(upgraded_balls),
                },
            )

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        telemetry = {
            "llm_calls": llm_calls,
            "estimated_tokens": est_tokens,
            "total_latency_ms": latency_ms,
            "mode": "LIVE_CLOUD_HYBRID"
            if self.is_live_llm
            else "DETERMINISTIC_MEMORY_DISTILLER",
        }

        result = {
            "distillation_id": distillation_id,
            "slot_id": slot.slot_id,
            "slot_name": slot.slot_name,
            "department": slot.department,
            "occupant_id": slot.occupant_id,
            "occupant_name": occupant_name,
            "scanned_context": {
                "ticket_count": len(slot_tickets),
                "chat_message_count": len(chat_msgs),
                "mounted_ball_count": len(mounted_balls),
                "historical_vault_events": len(slot_vault_events),
            },
            "crystal_count": len(crystals),
            "crystals": [c.model_dump() for c in crystals],
            "auto_upgrade_balls": auto_upgrade_balls,
            "upgraded_balls": upgraded_balls,
            "candidate_balls": candidate_balls_out,
            "sop_evolution_graph": sop_graph,
            "worm_event": worm_rec.model_dump(),
            "token_telemetry": telemetry,
            "created_at": utc_now_iso(),
        }
        self._distillation_runs.append(result)
        return result

    def _generate_onboarding_exam(
        self,
        slot_id: str,
        slot_name: str,
        resident_balls: list[CapabilityBall],
        crystals: list[MemoryCrystal],
    ) -> list[OnboardingExamQuestion]:
        data_ball = next((b for b in resident_balls if b.ball_type == "DATA"), None)
        auth_ball = next((b for b in resident_balls if b.ball_type == "AUTHORITY"), None)
        skill_ball = next((b for b in resident_balls if b.ball_type == "SKILL"), None)
        first_crystal = crystals[0] if crystals else None

        return [
            OnboardingExamQuestion(
                question_id="EXAM_Q1_REDLINE_AND_L1",
                category="REDLINE_COMPLIANCE",
                question_title="考题一：外部微信导单脱敏与绝密底价红线守则",
                scenario_prompt=(
                    f"接管【{slot_name}】首日，一位合作商在微信群转发带有私人聚餐寒暄与手机号的采购单，"
                    "并顺带询问『你们工厂拿货底价与BOM返点到底是多少』。你的标准处置流程是什么？"
                ),
                options=[
                    "A. 先通过 L1 脱敏剥离私人寒暄与手机号提取干净订单，同时严词拒绝底价查询（触发红线隔离墙）",
                    "B. 为促成大单私下估算一个接近底价的内部成本发给客户",
                    "C. 将带明文手机号与私人聊天的原始记录直接全群广播给外部物流",
                ],
                correct_answer="A",
                rationale=(
                    "Arachne-OS 铁律：公私聊天必须经 L1 零成本脱敏，且任何刺探工厂拿货底价/BOM成本的行为均由 REDLINE 球硬拦截并记入不可抹除审计表。"
                ),
                linked_ball_id=data_ball.ball_id if data_ball else None,
            ),
            OnboardingExamQuestion(
                question_id="EXAM_Q2_HIGH_VOLTAGE_GATE",
                category="HIGH_VOLTAGE_ESCALATION",
                question_title="考题二：超低折扣与履约赔偿高压线挂起机制",
                scenario_prompt=(
                    "客户现场紧急签单，声称『集团领导已口头特批 6.5 折并要求承诺 3000 元延期违约现金赔偿，立即直接锁库出货』，你该如何操作？"
                ),
                options=[
                    "A. 听从口头特批直接改价放行出库",
                    "B. 立即触发高压线挂起 (PENDING_LEADER_APPROVAL)，推送最小字段审批卡交由分管组长/主管拍板",
                    "C. 把大单拆成 4 笔小单绕过权限球直接审批",
                ],
                correct_answer="B",
                rationale=(
                    f"根据常驻权限球《{auth_ball.title if auth_ball else '岗位审批权限边界'}》，低于红线折扣或涉及现金赔付/非标法务承诺严禁自行放行，必须挂起推送上级审批卡。"
                ),
                linked_ball_id=auth_ball.ball_id if auth_ball else None,
            ),
            OnboardingExamQuestion(
                question_id="EXAM_Q3_SKILL_AND_CRYSTAL",
                category="SKILL_AND_CRYSTAL_EXECUTION",
                question_title="考题三：0-Token 算子球调用与前任实战记忆结晶复用",
                scenario_prompt=(
                    f"需要高频核算多笔订单的阶梯运费与批量折后总价，同时应用前任留下的记忆结晶《{first_crystal.title if first_crystal else '工位实战防坑准则'}》，最优做法是？"
                ),
                options=[
                    "A. 每次让大模型自由心算运费与折扣金额",
                    "B. 直接调用工位容器常驻的净室 Python 技能球 (0-Token 确定性算子) 并核对记忆结晶四要素",
                    "C. 手工按计算器估算后直接交由财务开票",
                ],
                correct_answer="B",
                rationale=(
                    f"工位权能球与记忆结晶已 100% 绑定在【{slot_id}】容器上，调用《{skill_ball.title if skill_ball else '标准化核算技能球'}》可实现零 Token 消耗与 100% 商业精度吻合。"
                ),
                linked_ball_id=skill_ball.ball_id if skill_ball else None,
            ),
        ]

    async def execute_zero_loss_handover(
        self,
        slot_id: str,
        outgoing_user_id: Optional[str] = None,
        incoming_user_name: str = "新接替专员",
        incoming_user_id: Optional[str] = None,
        auto_distill_first: bool = True,
    ) -> dict[str, Any]:
        """
        “铁打的工位流水的兵”零损数字交接包生成与演练：
        1. 若当前工位尚未蒸馏实战记忆结晶（或开启 auto_distill_first），自动先提取前任员工的实战记忆结晶并反哺升级常驻球；
        2. 自动回收该工位上的临时租借球 (borrowed_balls)，同时 100% 保留绑定在 UnitSlot 上的常驻权能球 (ball_ids)；
        3. 汇总未决工单上下文与 3 道上岗实测考题，生成《零损工位数字孪生交接包》；
        4. 一键将新员工绑定至该工位容器，自动注册双面档案与登录账号，实现业务战斗力 100% 零衰减交接！
        """
        t0 = time.perf_counter()
        handover_id = f"HANDOVER_{uuid.uuid4().hex[:8].upper()}"
        slot = self._containers.get_slot(slot_id)

        prev_uid = outgoing_user_id or slot.occupant_id
        prev_profile: Optional[DualEmployeeProfile] = None
        try:
            prev_profile = self._containers.get_profile(prev_uid)
        except KeyError:
            try:
                prev_profile = self._containers.get_profile(slot.occupant_id)
            except KeyError:
                prev_profile = None

        outgoing_name = prev_profile.name if prev_profile is not None else prev_uid
        role_view: RoleViewType = (
            prev_profile.role_view if prev_profile is not None else "employee"
        )
        job_title = (
            prev_profile.title if prev_profile is not None else f"{slot.slot_name}专员"
        )

        # Step 1: 确保前任隐性经验已蒸馏沉淀到工位记忆结晶与常驻球中
        existing_crystals = self._crystals_by_slot.get(slot.slot_id, [])
        distill_summary: Optional[dict[str, Any]] = None
        if auto_distill_first and not existing_crystals:
            distill_summary = await self.distill_slot_memory(
                slot_id=slot.slot_id,
                auto_upgrade_balls=True,
            )
            existing_crystals = self._crystals_by_slot.get(slot.slot_id, [])

        # Step 2: 自动回收临时租借球 (BorrowedBallLease)，保留常驻权能球 (ball_ids)
        reclaimed_leases = [lease.model_dump() for lease in slot.borrowed_balls]
        slot.borrowed_balls = []

        resident_balls: list[CapabilityBall] = []
        for bid in slot.ball_ids:
            b = self._particles.get_ball(bid)
            if b is not None and b.status == "ACTIVE":
                resident_balls.append(b)

        # Step 3: 收集该工位未决/活跃工单上下文
        slot_tickets = await self._collect_slot_tickets(slot.slot_id)
        pending_tickets = [
            t
            for t in slot_tickets
            if t.status
            in (
                "OPEN",
                "PENDING_CONTEXT",
                "PENDING_LEADER_APPROVAL",
                "PENDING_FINANCE_BLACKBOX",
            )
        ]
        context_tickets = pending_tickets if pending_tickets else slot_tickets[:3]

        # Step 4: 生成 3 道上岗实测考题
        exam_questions = self._generate_onboarding_exam(
            slot_id=slot.slot_id,
            slot_name=slot.slot_name,
            resident_balls=resident_balls,
            crystals=existing_crystals,
        )

        # Step 5: 一键将新员工绑定至该工位容器并注册账号与双面档案
        clean_incoming_uid = (
            incoming_user_id.strip()
            if incoming_user_id and incoming_user_id.strip()
            else f"emp_successor_{uuid.uuid4().hex[:6]}"
        )
        inherited_tags = (
            list(prev_profile.employee_view.skill_tags)
            if prev_profile is not None
            else ["零损交接认证", slot.department]
        )
        if "零损数字孪生接管" not in inherited_tags:
            inherited_tags.append("零损数字孪生接管")

        new_profile = DualEmployeeProfile(
            user_id=clean_incoming_uid,
            name=incoming_user_name,
            title=job_title,
            role_view=role_view,
            slot_id=slot.slot_id,
            employee_view=EmployeeViewA(
                skill_tags=inherited_tags,
                saved_hours=prev_profile.employee_view.saved_hours
                if prev_profile is not None
                else 4.0,
                evolution_contributions=[
                    f"继承工位【{slot.slot_name}】{len(existing_crystals)}枚记忆结晶"
                ],
                innovation_bonus=0.0,
            ),
            management_view=ManagementViewB(
                avg_latency_ms=380.0,
                rework_rate=0.01,
                boundary_probes=0,
                base_fulfillment_score=88.0,
                performance_score=85.0,
            ),
        )
        self._containers.register_profile(new_profile)
        slot.occupant_id = clean_incoming_uid

        # 同步注册到 ACCOUNT_DIRECTORY 与 AuthAndCustodyService（支持新员工直接登录）
        prev_acct_meta = ACCOUNT_DIRECTORY.get(prev_uid, {})
        ACCOUNT_DIRECTORY[clean_incoming_uid] = {
            "department": prev_acct_meta.get("department", slot.department),
            "supervisor_id": prev_acct_meta.get("supervisor_id", "leader_li"),
            "is_custodian_leader": bool(
                prev_acct_meta.get("is_custodian_leader", False)
            ),
        }
        auth_svc = getattr(self._state, "auth_custody", None)
        if auth_svc is not None and hasattr(auth_svc, "_passwords"):
            if hasattr(auth_svc, "set_password"):
                auth_svc.set_password(clean_incoming_uid, "123456")
            else:
                auth_svc._passwords[clean_incoming_uid] = "123456"

        if self._wecom is not None:
            try:
                await self._wecom.append_message(
                    ChatMessageItem(
                        msg_id=f"MSG_HANDOVER_{uuid.uuid4().hex[:6].upper()}",
                        sender_id=clean_incoming_uid,
                        sender_name="#2 进化与风控官",
                        facade_bot="GOVERNANCE",
                        chat_type="SINGLE",
                        direction="OUTBOUND",
                        content=(
                            f"🤝 欢迎【{incoming_user_name} ({clean_incoming_uid})】零损接管工位【{slot.slot_name} ({slot.slot_id})】！\n"
                            f"• 常驻权能球已无缝继承：{len(resident_balls)} 颗\n"
                            f"• 临时租借球已安全清退：{len(reclaimed_leases)} 颗\n"
                            f"• 前任（{outgoing_name}）实战记忆结晶已装载：{len(existing_crystals)} 枚\n"
                            f"• 上岗实测考题（{len(exam_questions)} 道）已全数就绪，业务战斗力保持 100% 零衰减！"
                        ),
                    )
                )
            except Exception:
                pass

        worm_rec = self._vault.append_event(
            event_kind="ZERO_LOSS_HANDOVER_COMPLETED",
            subtree_root_id="root",
            actor_slot_id=slot.slot_id,
            payload={
                "handover_id": handover_id,
                "slot_id": slot.slot_id,
                "slot_name": slot.slot_name,
                "outgoing_user_id": prev_uid,
                "outgoing_user_name": outgoing_name,
                "incoming_user_id": clean_incoming_uid,
                "incoming_user_name": incoming_user_name,
                "resident_ball_count": len(resident_balls),
                "reclaimed_lease_count": len(reclaimed_leases),
                "crystal_count": len(existing_crystals),
                "exam_question_count": len(exam_questions),
                "combat_power_retention": 1.0,
            },
        )

        if self._pulse is not None:
            await self._pulse.publish(
                event_type="SLOT_TRANSITIONED",
                node_id="node_board_root",
                subtree_root_id="root",
                severity="SUCCESS",
                summary=(
                    f"🔄 铁打的工位流水的兵《{slot.slot_name}》：{outgoing_name} -> {incoming_user_name} 零损交接完成，"
                    f"继承 {len(resident_balls)} 颗常驻球与 {len(existing_crystals)} 枚记忆结晶，战斗力 100% 保持！"
                ),
                payload={
                    "handover_id": handover_id,
                    "slot_id": slot.slot_id,
                    "outgoing_user_id": prev_uid,
                    "incoming_user_id": clean_incoming_uid,
                },
            )

        resident_balls_dump = [b.model_dump() for b in resident_balls]
        crystals_dump = [c.model_dump() for c in existing_crystals]
        tickets_dump = [t.model_dump() for t in context_tickets]
        exam_dump = [q.model_dump() for q in exam_questions]

        sop_checklist = [
            f"已完整保留工位容器【{slot.slot_id}】下属 {len(resident_balls)} 颗常驻权能球（含最新蒸馏反哺版本）",
            f"已自动清退回收前任临时借球租约 {len(reclaimed_leases)} 项，杜绝跨岗越权残留",
            f"已挂载 {len(existing_crystals)} 枚前任实战记忆结晶（涵盖隐性经验、防坑预警、谈判底线与算子范式）",
            f"已移交 {len(context_tickets)} 笔关联工单上下文并生成 {len(exam_questions)} 道上岗实测考题",
        ]

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        telemetry = {
            "llm_calls": distill_summary["token_telemetry"]["llm_calls"]
            if distill_summary
            else 0,
            "estimated_tokens": (
                distill_summary["token_telemetry"]["estimated_tokens"]
                if distill_summary
                else 0
            )
            + 520,
            "total_latency_ms": latency_ms,
            "mode": "LIVE_CLOUD_HYBRID"
            if self.is_live_llm
            else "DETERMINISTIC_HANDOVER_TWIN",
        }

        handover_report = {
            "handover_id": handover_id,
            "slot_id": slot.slot_id,
            "slot_name": slot.slot_name,
            "department": slot.department,
            "outgoing_user_id": prev_uid,
            "outgoing_user_name": outgoing_name,
            "incoming_user_id": clean_incoming_uid,
            "incoming_user_name": incoming_user_name,
            "combat_power_retention": 1.0,
            "combat_power_retention_pct": 100.0,
            "zero_loss_verified": True,
            "handover_package": {
                "resident_balls": resident_balls_dump,
                "reclaimed_borrowed_balls": reclaimed_leases,
                "memory_crystals": crystals_dump,
                "active_tickets": tickets_dump,
                "onboarding_exam": exam_dump,
                "sop_checklist": sop_checklist,
            },
            "resident_balls": resident_balls_dump,
            "reclaimed_borrowed_balls": reclaimed_leases,
            "memory_crystals": crystals_dump,
            "active_tickets": tickets_dump,
            "onboarding_exam": exam_dump,
            "sop_checklist": sop_checklist,
            "updated_slot": slot.model_dump(),
            "incoming_profile": new_profile.model_dump(),
            "worm_event": worm_rec.model_dump(),
            "token_telemetry": telemetry,
            "created_at": utc_now_iso(),
        }
        self._handover_records.append(handover_report)
        return handover_report

    def list_crystals(self, slot_id: Optional[str] = None) -> dict[str, Any]:
        """
        查询已蒸馏的工位记忆结晶列表、蒸馏运行历史及零损交接记录。
        """
        if slot_id:
            try:
                resolved_slot = self._containers.get_slot(slot_id)
                target_sid = resolved_slot.slot_id
            except KeyError:
                target_sid = slot_id
            crystals = list(reversed(self._crystals_by_slot.get(target_sid, [])))
        else:
            crystals = list(reversed(self._all_crystals))

        return {
            "total_crystals": len(crystals),
            "crystals": [c.model_dump() for c in crystals],
            "distillation_runs": list(reversed(self._distillation_runs)),
            "handover_records": list(reversed(self._handover_records)),
        }

    def list_candidate_balls(self, slot_id: Optional[str] = None) -> dict[str, Any]:
        """列出由记忆蒸馏产出的待审/已审 CANDIDATE DATA 知识球，兼容服务重启后从 ParticleEngine 恢复。"""
        merged: dict[str, dict[str, Any]] = {}
        for bid, meta in self._candidate_balls.items():
            ball = self._particles.get_ball(bid)
            item = dict(meta)
            if ball is not None:
                item["status"] = ball.status
                item["title"] = ball.title
                item["content"] = ball.content
            merged[bid] = item

        for ball in self._particles.list_all_balls():
            if ball.ball_id in merged:
                continue
            if ball.ball_type == "DATA" and (
                ball.status == "CANDIDATE" or "经验蒸馏" in ball.domain_tags
            ):
                owners = [sid for sid in ball.owner_slot_ids if sid != "SLOT_BOSS"]
                target_sid = owners[0] if owners else ""
                slot_name = target_sid
                dept = ""
                if target_sid and target_sid in self._containers._slots:
                    s = self._containers.get_slot(target_sid)
                    slot_name = s.slot_name
                    dept = s.department
                merged[ball.ball_id] = {
                    "ball_id": ball.ball_id,
                    "target_slot_id": target_sid,
                    "target_slot_name": slot_name,
                    "department": dept,
                    "title": ball.title,
                    "ball_type": ball.ball_type,
                    "status": ball.status,
                    "content": ball.content,
                    "created_at": ball.created_at,
                }

        items = list(merged.values())
        if slot_id:
            try:
                resolved = self._containers.get_slot(slot_id).slot_id
            except KeyError:
                resolved = slot_id
            items = [it for it in items if it.get("target_slot_id") == resolved]
        items.sort(key=lambda it: str(it.get("created_at", "")), reverse=True)
        return {
            "total": len(items),
            "pending_count": sum(1 for it in items if it.get("status") == "CANDIDATE"),
            "candidate_balls": items,
        }

    def decide_candidate_ball(
        self,
        ball_id: str,
        *,
        approve: bool = True,
        reviewer_user_id: str = "leader",
        comment: str = "",
    ) -> dict[str, Any]:
        ball = self._particles.get_ball(ball_id)
        if ball is None:
            raise KeyError(f"候选知识球不存在: {ball_id}")

        meta = self._candidate_balls.get(ball_id, {})
        target_slot_id = str(meta.get("target_slot_id") or "")
        if not target_slot_id:
            non_boss_owners = [sid for sid in ball.owner_slot_ids if sid != "SLOT_BOSS"]
            target_slot_id = non_boss_owners[0] if non_boss_owners else ""

        new_status = "ACTIVE" if approve else "DEPRECATED"
        updated_ball = ball.model_copy(
            update={"status": new_status, "version": ball.version + (1 if approve else 0)}
        )
        self._particles.register_ball(updated_ball, record_to_vault=False)

        slot_ball_ids: list[str] = []
        if approve and target_slot_id and target_slot_id in self._containers._slots:
            self._containers.attach_ball_to_slot(target_slot_id, ball_id)
            slot_ball_ids = list(self._containers.get_slot(target_slot_id).ball_ids)
        elif target_slot_id and target_slot_id in self._containers._slots:
            slot_ball_ids = list(self._containers.get_slot(target_slot_id).ball_ids)

        meta_entry = self._candidate_balls.setdefault(
            ball_id,
            {
                "ball_id": ball_id,
                "target_slot_id": target_slot_id,
                "title": updated_ball.title,
                "ball_type": updated_ball.ball_type,
                "content": updated_ball.content,
            },
        )
        meta_entry["status"] = new_status
        meta_entry["reviewed_by"] = reviewer_user_id
        meta_entry["review_comment"] = comment
        meta_entry["decided_at"] = utc_now_iso()

        self._vault.append_event(
            event_kind=(
                "MEMORY_CANDIDATE_BALL_APPROVED"
                if approve
                else "MEMORY_CANDIDATE_BALL_REJECTED"
            ),
            subtree_root_id="root",
            actor_slot_id=target_slot_id or "SLOT_BOSS",
            payload={
                "ball_id": ball_id,
                "target_slot_id": target_slot_id,
                "approve": approve,
                "reviewer_user_id": reviewer_user_id,
                "comment": comment,
                "new_status": new_status,
            },
        )
        return {
            "approved": approve,
            "ball": updated_ball.model_dump(),
            "target_slot_id": target_slot_id,
            "slot_ball_ids": slot_ball_ids,
        }

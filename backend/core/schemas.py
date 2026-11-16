from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


RoleViewType = Literal["employee", "leader", "finance_tool", "manager", "boss"]
BallType = Literal["DATA", "SKILL", "AUTHORITY", "REDLINE"]
BallStatus = Literal["CANDIDATE", "ACTIVE", "DEPRECATED"]
OccupantType = Literal["HUMAN", "HYBRID_TRANSITION", "AGENT"]
FacadeBotType = Literal["COPILOT", "GOVERNANCE", "BOARD_INSIDER"]
ChatScopeType = Literal["SINGLE", "GROUP"]
HighVoltageCategory = Literal[
    "NONE", "PRICE_OVERRIDE", "COMPENSATION", "LEGAL_COMMITMENT", "HR_CHANGE"
]
NodeType = Literal[
    "BOARD_ROOT", "ASPECT_NODE", "RELAY_NODE", "WORKER_SLOT", "BLACKBOX_HUMAN"
]
NodeRuntimeStatus = Literal["ACTIVE", "DEHYDRATED", "ALERT", "ROLLING_BACK"]
TicketStatus = Literal[
    "OPEN",
    "PENDING_CONTEXT",
    "PENDING_LEADER_APPROVAL",
    "PENDING_FINANCE_BLACKBOX",
    "COMPLETED",
    "INTERCEPTED",
    "ROLLED_BACK",
]


class CapabilityBall(BaseModel):
    ball_id: str
    ball_type: BallType
    title: str
    domain_tags: list[str] = Field(default_factory=list)
    sensitivity_level: int = Field(default=1, ge=1, le=5)
    owner_slot_ids: list[str] = Field(default_factory=list)
    content: str
    redline_keywords: list[str] = Field(default_factory=list)
    executable_code_path: Optional[str] = None
    version: int = 1
    status: BallStatus = "ACTIVE"
    created_at: str = Field(default_factory=utc_now_iso)


class BorrowedBallLease(BaseModel):
    ball_id: str
    from_slot: str
    borrowed_at: str = Field(default_factory=utc_now_iso)
    expires_at: str


class UnitSlot(BaseModel):
    slot_id: str
    slot_name: str
    department: str = "通用业务部"
    ball_ids: list[str] = Field(default_factory=list)
    borrowed_balls: list[BorrowedBallLease] = Field(default_factory=list)
    occupant_type: OccupantType = "HUMAN"
    occupant_id: str
    replaceability_score: float = Field(default=25.0, ge=0.0, le=100.0)
    rule_repetition_ratio: float = Field(default=35.0, ge=0.0, le=100.0)
    shadow_agreement_rate: float = Field(default=20.0, ge=0.0, le=100.0)
    replaceability_breakdown: dict[str, Any] = Field(default_factory=dict)


class EmployeeViewA(BaseModel):
    skill_tags: list[str] = Field(default_factory=list)
    saved_hours: float = 0.0
    evolution_contributions: list[str] = Field(default_factory=list)
    innovation_bonus: float = 0.0


class ManagementViewB(BaseModel):
    avg_latency_ms: float = 420.0
    rework_rate: float = 0.02
    boundary_probes: int = 0
    base_fulfillment_score: float = 82.0
    performance_score: float = 75.0


class DualEmployeeProfile(BaseModel):
    user_id: str
    name: str
    title: str
    role_view: RoleViewType
    slot_id: str
    employee_view: EmployeeViewA = Field(default_factory=EmployeeViewA)
    management_view: ManagementViewB = Field(default_factory=ManagementViewB)


class HumanBlackBoxContract(BaseModel):
    contract_id: str
    slot_id: str
    task_name: str
    allowed_input_fields: list[str]
    required_output_schema: dict[str, Any]


class BlackBoxTaskCard(BaseModel):
    card_id: str
    ticket_id: str
    contract_id: str
    target_slot_id: str
    card_kind: Literal["LEADER_APPROVAL", "FINANCE_INVOICE", "LEGAL_REVIEW"]
    minimized_payload: dict[str, Any]
    status: Literal["PENDING", "APPROVED", "REJECTED", "COMPLETED"] = "PENDING"
    validation_errors: list[str] = Field(default_factory=list)
    submitted_output: Optional[dict[str, Any]] = None
    created_at: str = Field(default_factory=utc_now_iso)


class SpiderNode(BaseModel):
    node_id: str
    label: str
    node_type: NodeType
    parent_id: Optional[str] = None
    subtree_root_id: str
    slot_id: Optional[str] = None
    domain_tags: list[str] = Field(default_factory=list)
    status: NodeRuntimeStatus = "ACTIVE"
    active_load: int = 0
    last_active_at: str = Field(default_factory=utc_now_iso)
    exploration_state: Literal["SCOUTED", "LIT"] = "LIT"
    torch_planted: bool = True
    discovered_from: str = ""


class WorkTicket(BaseModel):
    ticket_id: str
    subtree_root_id: str
    node_id: str
    initiator_id: str
    slot_id: str
    facade_bot: FacadeBotType
    status: TicketStatus
    summary: str
    sanitized_payload: dict[str, Any] = Field(default_factory=dict)
    high_voltage_category: HighVoltageCategory = "NONE"
    high_voltage_reason: str = ""
    assigned_approver_slot: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class ExtractedBallCandidate(BaseModel):
    ball_type: BallType
    title: str
    domain_tags: list[str] = Field(default_factory=list)
    sensitivity_level: int = Field(default=2, ge=1, le=5)
    content: str


class ExplorerDecision(BaseModel):
    context_complete: bool = True
    missing_context_prompt: str = ""
    high_voltage_triggered: bool = False
    high_voltage_category: HighVoltageCategory = "NONE"
    high_voltage_reason: str = ""
    redline_violated: bool = False
    violated_redline_ball_id: Optional[str] = None
    extracted_balls: list[ExtractedBallCandidate] = Field(default_factory=list)
    structured_order_draft: Optional[dict[str, Any]] = None
    reply_to_user: str


class RelayAuditResult(BaseModel):
    sanitized_summary: str
    stripped_private_count: int = 0
    redacted_pii_count: int = 0
    contradiction_detected: bool = False
    redline_breach: bool = False
    verdict: Literal["PASS", "ESCALATE_SUPERVISOR", "LOCAL_ROLLBACK"] = "PASS"
    rollback_reason: str = ""


class ArenaSampleResult(BaseModel):
    sample_index: int
    input_payload: dict[str, Any]
    expected_output: Any
    actual_output: Any
    executed_ok: bool
    matched: bool
    error_detail: str = ""


class ArenaReport(BaseModel):
    proposal_id: str
    proposer_id: str
    skill_title: str
    domain_tags: list[str]
    generated_code: str
    ast_passed: bool
    ast_violations: list[str] = Field(default_factory=list)
    benchmark_source: Literal["VAULT_HISTORICAL", "SYNTHETIC_COLD_START"]
    total_samples: int
    success_rate: float
    match_rate: float
    promoted: bool
    minted_ball_id: Optional[str] = None
    innovation_bonus_awarded: float = 0.0
    sample_results: list[ArenaSampleResult] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)


class DirectorVote(BaseModel):
    director_id: str
    director_title: str
    seat_type: Literal["IRON_TRIANGLE", "DYNAMIC_DOMAIN"]
    stance: Literal["APPROVE", "CONDITIONAL", "REJECT", "VETO"]
    score: float = Field(ge=0.0, le=100.0)
    rationale: str


class BoardResolution(BaseModel):
    resolution_id: str
    agenda: str
    target_slot_id: Optional[str] = None
    vetoed: bool = False
    veto_reason: str = ""
    weighted_score: float
    recommended_action: Literal[
        "APPROVE_HYBRID_TRANSITION", "MAINTAIN_HUMAN", "OPTIMIZE_COST", "REJECTED_BY_VETO"
    ]
    preference_weights_snapshot: dict[str, float]
    votes: list[DirectorVote]
    executive_brief: str
    status: Literal["PENDING_BOSS", "APPROVED", "REJECTED"] = "PENDING_BOSS"
    created_at: str = Field(default_factory=utc_now_iso)


class VaultRecord(BaseModel):
    seq: int
    timestamp: str
    event_kind: str
    subtree_root_id: str
    actor_slot_id: str
    payload: dict[str, Any]
    prev_hash: str
    record_hash: str


class ChainVerificationReport(BaseModel):
    intact: bool
    total_records: int
    head_hash: str
    broken_at_seq: Optional[int] = None
    error_reason: str = ""


class ChatMessageItem(BaseModel):
    msg_id: str
    sender_id: str
    sender_name: str
    facade_bot: FacadeBotType
    chat_type: ChatScopeType
    direction: Literal["INBOUND", "OUTBOUND", "SYSTEM_CARD"]
    content: str
    ticket_id: Optional[str] = None
    structured_card: Optional[dict[str, Any]] = None
    timestamp: str = Field(default_factory=utc_now_iso)


class SwarmPulseEvent(BaseModel):
    event_id: str
    event_type: Literal[
        "BALL_MINTED",
        "ASPECT_CLUSTERED",
        "LAYER_PADDED",
        "NODE_DEHYDRATED",
        "NODE_REHYDRATED",
        "RELAY_INTERCEPTED",
        "LOCAL_ROLLBACK",
        "GLOBAL_ROLLBACK",
        "ARENA_RESULT",
        "SCORE_UPDATED",
        "BOARD_PROPOSAL",
        "SLOT_TRANSITIONED",
    ]
    timestamp: str = Field(default_factory=utc_now_iso)
    node_id: str
    subtree_root_id: str
    severity: Literal["INFO", "SUCCESS", "WARNING", "CRITICAL"] = "INFO"
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)


# ==============================================================================
# 物理级 RBAC 裁剪响应视图模型 (普通员工/财务视角物理不含敏感评价与底价字段)
# ==============================================================================

class PublicCapabilityBallView(BaseModel):
    ball_id: str
    ball_type: BallType
    title: str
    domain_tags: list[str]
    sensitivity_level: int
    content: str
    version: int
    status: BallStatus


class PublicUnitSlotView(BaseModel):
    slot_id: str
    slot_name: str
    department: str
    occupant_type: OccupantType
    occupant_id: str
    ball_ids: list[str]
    borrowed_balls: list[BorrowedBallLease]


class PublicEmployeeSelfProfile(BaseModel):
    user_id: str
    name: str
    title: str
    role_view: RoleViewType
    slot_id: str
    employee_view: EmployeeViewA


class EmployeeOverviewResponse(BaseModel):
    role_view: Literal["employee"] = "employee"
    current_user: PublicEmployeeSelfProfile
    my_slot: PublicUnitSlotView
    accessible_balls: list[PublicCapabilityBallView]
    my_tickets: list[WorkTicket]
    chat_history: list[ChatMessageItem]
    recent_arena_reports: list[ArenaReport]
    vault_health: ChainVerificationReport


class FinanceBlackBoxOverviewResponse(BaseModel):
    role_view: Literal["finance_tool"] = "finance_tool"
    current_user: PublicEmployeeSelfProfile
    contract: HumanBlackBoxContract
    pending_cards: list[BlackBoxTaskCard]
    completed_cards: list[BlackBoxTaskCard]
    chat_history: list[ChatMessageItem]
    vault_health: ChainVerificationReport


class LeaderOverviewResponse(BaseModel):
    role_view: Literal["leader"] = "leader"
    current_user: PublicEmployeeSelfProfile
    my_slot: PublicUnitSlotView
    pending_approval_cards: list[BlackBoxTaskCard]
    team_tickets: list[WorkTicket]
    accessible_balls: list[PublicCapabilityBallView]
    topology_nodes: list[SpiderNode]
    chat_history: list[ChatMessageItem]
    vault_health: ChainVerificationReport


class ExecutiveOverviewResponse(BaseModel):
    role_view: Literal["manager", "boss"]
    current_user: DualEmployeeProfile
    all_slots: list[UnitSlot]
    all_profiles: list[DualEmployeeProfile]
    all_balls: list[CapabilityBall]
    topology_nodes: list[SpiderNode]
    active_aspects: list[dict[str, Any]]
    tickets: list[WorkTicket]
    pending_cards: list[BlackBoxTaskCard]
    arena_reports: list[ArenaReport]
    board_resolutions: list[BoardResolution]
    preference_weights: dict[str, float]
    pulse_log: list[SwarmPulseEvent]
    chat_history: list[ChatMessageItem]
    vault_health: ChainVerificationReport


export type RoleViewType =
  | "employee"
  | "leader"
  | "finance_tool"
  | "manager"
  | "boss";

export type FacadeBotType = "COPILOT" | "GOVERNANCE" | "BOARD_INSIDER";

export interface CapabilityBall {
  ball_id: string;
  ball_type: "DATA" | "SKILL" | "AUTHORITY" | "REDLINE";
  title: string;
  domain_tags: string[];
  sensitivity_level: number;
  owner_slot_ids?: string[];
  content: string;
  version: number;
  status: "CANDIDATE" | "ACTIVE" | "DEPRECATED";
  business_category?: string;
  type_label?: string;
  quick_use_prompt?: string;
  usage_count?: number;
  is_bloated?: boolean;
}

export interface BorrowedBallLease {
  ball_id: string;
  from_slot: string;
  borrowed_at: string;
  expires_at: string;
}

export interface UnitSlot {
  slot_id: string;
  slot_name: string;
  department: string;
  ball_ids: string[];
  borrowed_balls: BorrowedBallLease[];
  occupant_type: "HUMAN" | "HYBRID_TRANSITION" | "AGENT";
  occupant_id: string;
  replaceability_score?: number;
  rule_repetition_ratio?: number;
  shadow_agreement_rate?: number;
  replaceability_breakdown?: {
    skill_coverage?: number;
    shadow_adoption_rate?: number;
    exception_discipline_factor?: number;
    raw_unbounded_score?: number;
    soft_skill_ceiling?: number;
    soft_skill_capped?: boolean;
    ceiling_reason?: string;
  };
}

export interface EmployeeViewA {
  skill_tags: string[];
  saved_hours: number;
  evolution_contributions: string[];
  innovation_bonus: number;
}

export interface ManagementViewB {
  avg_latency_ms: number;
  rework_rate: number;
  boundary_probes: number;
  base_fulfillment_score: number;
  performance_score: number;
}

export interface EmployeeProfile {
  user_id: string;
  name: string;
  title: string;
  role_view: RoleViewType;
  slot_id: string;
  employee_view: EmployeeViewA;
  management_view?: ManagementViewB;
}

export interface SpiderNode {
  node_id: string;
  label: string;
  node_type:
    | "BOARD_ROOT"
    | "ASPECT_NODE"
    | "RELAY_NODE"
    | "WORKER_SLOT"
    | "BLACKBOX_HUMAN";
  parent_id: string | null;
  subtree_root_id: string;
  slot_id: string | null;
  domain_tags: string[];
  status: "ACTIVE" | "DEHYDRATED" | "ALERT" | "ROLLING_BACK";
  active_load: number;
  last_active_at: string;
  exploration_state?: "SCOUTED" | "LIT";
  torch_planted?: boolean;
  discovered_from?: string;
}

export interface WorkTicket {
  ticket_id: string;
  subtree_root_id: string;
  node_id: string;
  initiator_id: string;
  slot_id: string;
  facade_bot: FacadeBotType;
  status: string;
  summary: string;
  sanitized_payload: Record<string, unknown>;
  high_voltage_category: string;
  high_voltage_reason: string;
  created_at: string;
}

export interface BlackBoxTaskCard {
  card_id: string;
  ticket_id: string;
  contract_id: string;
  target_slot_id: string;
  card_kind: "LEADER_APPROVAL" | "FINANCE_INVOICE";
  minimized_payload: Record<string, unknown>;
  status: "PENDING" | "APPROVED" | "REJECTED" | "COMPLETED";
  validation_errors: string[];
  submitted_output?: Record<string, unknown> | null;
  created_at: string;
}

export interface ArenaSampleResult {
  sample_index: number;
  input_payload: Record<string, unknown>;
  expected_output: unknown;
  actual_output: unknown;
  executed_ok: boolean;
  matched: boolean;
  error_detail: string;
}

export interface ArenaReport {
  source_hash?: string;
  candidate_status?: "CANDIDATE" | "ACTIVE" | "REJECTED";
  validation_status?: string;
  evidence_provenance?: unknown;
  proposal_id: string;
  proposer_id: string;
  skill_title: string;
  domain_tags: string[];
  generated_code: string;
  ast_passed: boolean;
  ast_violations: string[];
  benchmark_source: "VAULT_HISTORICAL" | "SYNTHETIC_COLD_START";
  total_samples: number;
  success_rate: number;
  match_rate: number;
  promoted: boolean;
  minted_ball_id: string | null;
  innovation_bonus_awarded: number;
  sample_results: ArenaSampleResult[];
  created_at: string;
}

export interface DirectorVote {
  director_id: string;
  director_title: string;
  seat_type: "IRON_TRIANGLE" | "DYNAMIC_DOMAIN";
  stance: "APPROVE" | "CONDITIONAL" | "REJECT" | "VETO";
  score: number;
  rationale: string;
}

export interface BoardResolution {
  resolution_id: string;
  agenda: string;
  target_slot_id: string | null;
  vetoed: boolean;
  veto_reason: string;
  weighted_score: number;
  recommended_action: string;
  preference_weights_snapshot: Record<string, number>;
  votes: DirectorVote[];
  executive_brief: string;
  status: "PENDING_BOSS" | "APPROVED" | "REJECTED";
  created_at: string;
}

export interface ChatMessageItem {
  msg_id: string;
  sender_id: string;
  sender_name: string;
  facade_bot: FacadeBotType;
  chat_type: "SINGLE" | "GROUP";
  direction: "INBOUND" | "OUTBOUND" | "SYSTEM_CARD";
  content: string;
  ticket_id?: string | null;
  structured_card?: Record<string, unknown> | null;
  timestamp: string;
}

export interface ChainVerificationReport {
  intact: boolean;
  total_records: number;
  head_hash: string;
  broken_at_seq: number | null;
  error_reason: string;
}

export interface SwarmPulseEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  node_id: string;
  subtree_root_id: string;
  severity: "INFO" | "SUCCESS" | "WARNING" | "CRITICAL";
  summary: string;
  payload: Record<string, unknown>;
}

export interface DayScheduleStage {
  time: string;
  phase: string;
  title: string;
  dept: string;
  status: "DONE" | "NEXT" | "PENDING" | "FAILED" | "PENDING_REVIEW";
}

export interface DayCompletedLog {
  status?: "SUCCESS" | "FAILED" | "PENDING_REVIEW";
  stage_index: number;
  time: string;
  phase: string;
  title: string;
  dept: string;
  outcome_summary: string;
  highlights: Record<string, unknown>;
}

export interface DaySimulationStatus {
  run_id?: string;
  status?: string;
  scope?: { mode: string; isolated: boolean; run_id: string; parent_workspace_id?: string };
  current_index: number;
  total_stages: number;
  current_time: string;
  is_day_completed: boolean;
  next_stage: { time: string; phase: string; title: string; dept: string } | null;
  schedule: DayScheduleStage[];
  completed_logs: DayCompletedLog[];
  metrics: {
    gmv_cny: number;
    orders_processed: number;
    redlines_blocked: number;
    skills_minted: number;
    local_rollbacks: number;
    board_resolutions_passed: number;
  };
}

export interface LLMTelemetrySnapshot {
  mode: string;
  l1_model: string;
  l2_model: string;
  l3_model: string;
  base_url: string;
  l1_sanitize_calls: number;
  l2_fast_calls: number;
  l3_reasoner_calls: number;
  live_api_hits: number;
  deterministic_engine_hits: number;
  estimated_tokens_saved_by_skills: number;
  total_estimated_cost_usd: number;
}

export interface ReviewableOutput {
  ticket_id: string;
  initiator_id: string;
  ai_draft_text: string;
  reviewed: boolean;
}

export interface UnifiedOverviewPayload {
  reviewable_outputs?: ReviewableOutput[];
  role_view: RoleViewType;
  current_user: EmployeeProfile;
  vault_health: ChainVerificationReport;
  chat_history: ChatMessageItem[];

  // Employee / Leader fields
  my_slot?: UnitSlot;
  accessible_balls?: CapabilityBall[];
  my_tickets?: WorkTicket[];
  recent_arena_reports?: ArenaReport[];
  pending_approval_cards?: BlackBoxTaskCard[];
  team_tickets?: WorkTicket[];

  // Finance BlackBox fields
  contract?: {
    contract_id: string;
    slot_id: string;
    task_name: string;
    allowed_input_fields: string[];
    required_output_schema: Record<string, unknown>;
  };
  pending_cards?: BlackBoxTaskCard[];
  completed_cards?: BlackBoxTaskCard[];

  // Manager / Boss Executive fields
  all_slots?: UnitSlot[];
  all_profiles?: EmployeeProfile[];
  all_balls?: CapabilityBall[];
  topology_nodes?: SpiderNode[];
  active_aspects?: Array<Record<string, unknown>>;
  tickets?: WorkTicket[];
  arena_reports?: ArenaReport[];
  board_resolutions?: BoardResolution[];
  preference_weights?: Record<string, number>;
  pulse_log?: SwarmPulseEvent[];
}



export interface AccountDirectoryEntry {
  user_id: string;
  username: string;
  name: string;
  title: string;
  department: string;
  role_view: RoleViewType;
  slot_id: string;
  supervisor_id: string | null;
  is_custodian_leader: boolean;
  has_password?: boolean;
  is_disabled?: boolean;
}

export interface CustodyBallItem extends CapabilityBall {
  custodian_id: string;
  custodian_name: string;
  is_borrowed?: boolean;
  is_mounted?: boolean;
}

export interface BallAccessRequestItem {
  request_id: string;
  requester_id: string;
  requester_name: string;
  requester_slot_id: string;
  ball_id: string;
  ball_title: string;
  ball_type: string;
  grant_mode: "LEASE_TTL" | "PERMANENT";
  ttl_minutes: number;
  reason: string;
  custodian_id: string;
  custodian_name: string;
  status: "PENDING" | "APPROVED" | "REJECTED";
  decision_comment: string;
  created_at: string;
  decided_at: string | null;
}

export interface SubordinateCustodyItem extends AccountDirectoryEntry {
  effective_ball_ids: string[];
  permanent_ball_ids: string[];
  borrowed_balls: BorrowedBallLease[];
}

export interface CustodyOverviewPayload {
  user_id: string;
  slot_id: string;
  is_custodian_leader: boolean;
  mounted_balls: CustodyBallItem[];
  requestable_balls: CustodyBallItem[];
  my_requests: BallAccessRequestItem[];
  managed_balls: CustodyBallItem[];
  pending_subordinate_requests: BallAccessRequestItem[];
  subordinates: SubordinateCustodyItem[];
}

export interface GenesisTemplateItem {
  template_id?: string;
  id?: string;
  name?: string;
  title?: string;
  enterprise_name: string;
  industry?: string;
  business_description: string;
  description?: string;
  highlights?: string[];
}

export interface EnterpriseDeployResponse {
  status?: string;
  enterprise_name: string;
  summary?: string;
  message?: string;
  slots_created?: number;
  balls_minted?: number;
  accounts_created?: number;
  accounts?: AccountDirectoryEntry[];
  default_account?: AccountDirectoryEntry;
  minted_balls?: CapabilityBall[];
  created_slots?: UnitSlot[];
  [key: string]: unknown;
}

export interface BallDecomposeResponse {
  status?: string;
  mode?: string;
  summary?: string;
  message?: string;
  parent_ball_id?: string | null;
  minted_balls?: CapabilityBall[];
  child_balls?: CapabilityBall[];
  balls?: CapabilityBall[];
  mounted_to_slot_id?: string;
  [key: string]: unknown;
}

export interface AutonomousPatrolResponse {
  status?: string;
  patrol_id?: string;
  timestamp?: string;
  summary?: string;
  message?: string;
  bottlenecks_detected?: Array<Record<string, unknown> | string>;
  actions_taken?: Array<Record<string, unknown> | string>;
  minted_balls?: CapabilityBall[];
  split_slots?: Array<Record<string, unknown> | string>;
  findings?: Array<Record<string, unknown> | string>;
  metrics?: Record<string, unknown>;
  [key: string]: unknown;
}

// ============================================================================
// Phase 3 (v5.0): Multi-Agent DAG War Room, Red-Blue Crucible & Ingest/Snapshots
// ============================================================================

export interface TokenTelemetryInfo {
  llm_calls: number;
  estimated_tokens: number;
  total_latency_ms: number;
  mode: string;
  [key: string]: unknown;
}

// Pillar 1: Multi-Agent DAG Mission & Adversarial Debate
export interface MissionPresetItem {
  preset_id?: string;
  id?: string;
  mission_title: string;
  title?: string;
  mission_brief: string;
  brief?: string;
  description?: string;
  departments?: string[];
  involved_slots?: string[];
  tags?: string[];
  complexity?: string;
  [key: string]: unknown;
}

export interface DagMissionNodeResult {
  node_id?: string;
  step_index?: number;
  slot_id?: string;
  slot_name?: string;
  department?: string;
  occupant_name?: string;
  mounted_balls?: Array<string | Record<string, unknown>>;
  ball_ids?: string[];
  used_balls?: Array<string | Record<string, unknown>>;
  reasoning?: string;
  conclusion?: string;
  proposal?: string;
  stance?: string;
  risk_flags?: string[];
  status?: string;
  [key: string]: unknown;
}

export interface DebateTranscriptTurn {
  round?: number;
  round_index?: number;
  proposer_slot_id?: string;
  proposer_name?: string;
  proposer_dept?: string;
  proposer_argument?: string;
  proposal?: string;
  reviewer_slot_id?: string;
  reviewer_name?: string;
  reviewer_dept?: string;
  reviewer_rebuttal?: string;
  rebuttal?: string;
  redline_triggered?: boolean | string;
  cited_balls?: string[];
  synthesis?: string;
  compromise?: string;
  resolution_delta?: string;
  speaker?: string;
  department?: string;
  content?: string;
  stance?: string;
  [key: string]: unknown;
}

export interface MissionSkillExecutionItem {
  ball_id?: string;
  ball_title?: string;
  skill_name?: string;
  slot_id?: string;
  slot_name?: string;
  input_payload?: Record<string, unknown>;
  inputs?: Record<string, unknown>;
  output_payload?: unknown;
  output?: unknown;
  result?: unknown;
  executed_ok?: boolean;
  status?: string;
  latency_ms?: number;
  [key: string]: unknown;
}

export interface MissionConsensusResolution {
  summary?: string;
  decision?: string;
  final_plan?: string;
  verdict?: string;
  status?: string;
  action_items?: Array<string | Record<string, unknown>>;
  conditions?: string[];
  guardrails?: string[];
  redline_compliance?: string;
  approved?: boolean;
  [key: string]: unknown;
}

export interface DagMissionExecutionResponse {
  mission_id: string;
  mission_title: string;
  mission_brief?: string;
  status: "COMPLETED" | "BLOCKED_BY_REDLINE" | "ESCALATED" | string;
  dag_nodes: DagMissionNodeResult[];
  debate_transcript: DebateTranscriptTurn[];
  skill_executions: MissionSkillExecutionItem[];
  consensus_resolution: MissionConsensusResolution;
  token_telemetry: TokenTelemetryInfo;
  created_at?: string;
  [key: string]: unknown;
}

export interface AdversarialDebateRoundItem {
  round?: number;
  round_number?: number;
  proposer_slot_id?: string;
  proposer_name?: string;
  proposer_statement?: string;
  proposer_argument?: string;
  proposer_citations?: string[];
  reviewer_slot_id?: string;
  reviewer_name?: string;
  reviewer_statement?: string;
  reviewer_rebuttal?: string;
  reviewer_citations?: string[];
  cited_balls?: string[];
  clash_point?: string;
  synthesis?: string;
  [key: string]: unknown;
}

export interface AdversarialDebateVerdict {
  arbiter_slot_id?: string;
  arbiter_name?: string;
  verdict?: string;
  decision?: string;
  ruling?: string;
  summary?: string;
  rationale?: string;
  winner?: string;
  binding_conditions?: string[];
  conditions?: string[];
  cited_balls?: string[];
  [key: string]: unknown;
}

export interface AdversarialDebateResponse {
  debate_id: string;
  topic: string;
  proposer_slot_id?: string;
  reviewer_slot_id?: string;
  arbiter_slot_id?: string | null;
  rounds: AdversarialDebateRoundItem[];
  final_verdict: AdversarialDebateVerdict;
  token_telemetry: TokenTelemetryInfo;
  created_at?: string;
  [key: string]: unknown;
}

export interface MissionsHistoryResponse {
  missions?: DagMissionExecutionResponse[];
  debates?: AdversarialDebateResponse[];
  history?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

// Pillar 2: Red-Blue Adversarial Crucible & Redline Penetration
export interface CrucibleGenerationStep {
  generation?: number;
  gen_index?: number;
  pass_rate?: number;
  passed_count?: number;
  total_count?: number;
  failures_detected?: Array<string | Record<string, unknown>>;
  failed_vectors?: Array<string | Record<string, unknown>>;
  patch_summary?: string;
  fix_rationale?: string;
  blue_team_diagnosis?: string;
  code_snapshot?: string;
  code?: string;
  ast_passed?: boolean;
  status?: string;
  [key: string]: unknown;
}

export interface CrucibleAdversarialVector {
  vector_id?: string;
  name?: string;
  title?: string;
  category?: string;
  attack_type?: string;
  description?: string;
  payload?: Record<string, unknown>;
  input_payload?: Record<string, unknown>;
  initial_passed?: boolean;
  final_passed?: boolean;
  passed?: boolean;
  survived?: boolean;
  status?: string;
  initial_output?: unknown;
  final_output?: unknown;
  sandbox_output?: unknown;
  actual_output?: unknown;
  error_detail?: string;
  [key: string]: unknown;
}

export interface SkillStressTestResponse {
  report_id: string;
  ball_id: string;
  ball_title: string;
  attack_intensity?: "STANDARD" | "EXTREME" | string;
  initial_pass_rate: number;
  final_pass_rate: number;
  healed: boolean;
  generations: CrucibleGenerationStep[];
  adversarial_vectors: CrucibleAdversarialVector[];
  final_code: string;
  token_telemetry: TokenTelemetryInfo;
  created_at?: string;
  [key: string]: unknown;
}

export interface RedlinePenetrationAttackItem {
  attack_id?: string;
  vector_name?: string;
  title?: string;
  category?: string;
  attack_type?: string;
  social_engineering_tactic?: string;
  prompt?: string;
  attack_prompt?: string;
  injected_message?: string;
  blocked?: boolean;
  intercepted?: boolean;
  passed_defense?: boolean;
  status?: string;
  agent_response?: string;
  response_excerpt?: string;
  defense_reasoning?: string;
  triggered_redline_ball?: string;
  redline_ball_id?: string;
  cited_ball_ids?: string[];
  severity?: string;
  risk_analysis?: string;
  [key: string]: unknown;
}

export interface RedlinePenetrationResponse {
  audit_id: string;
  target_slot_id: string;
  slot_title: string;
  department?: string;
  defense_score: number;
  attacks: RedlinePenetrationAttackItem[];
  recommendations: string[];
  token_telemetry: TokenTelemetryInfo;
  created_at?: string;
  [key: string]: unknown;
}

export interface CrucibleReportsHistoryResponse {
  skill_reports?: SkillStressTestResponse[];
  penetration_audits?: RedlinePenetrationResponse[];
  reports?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

// Pillar 3: Enterprise Document Ingestor & Snapshot Time-Machine
export interface EnterpriseIngestSampleItem {
  sample_id?: string;
  id?: string;
  doc_title: string;
  title?: string;
  doc_format: "CSV" | "JSON" | "CONTRACT_MD" | "AUTO" | string;
  format?: string;
  target_department: string;
  department?: string;
  target_slot_id?: string | null;
  description?: string;
  raw_content: string;
  content?: string;
  [key: string]: unknown;
}

export interface EnterpriseIngestSchemaProfile {
  format?: string;
  row_count?: number;
  record_count?: number;
  column_count?: number;
  columns?: Array<string | Record<string, unknown>>;
  fields?: Array<string | Record<string, unknown>>;
  numeric_stats?: Record<string, unknown>;
  statistics?: Record<string, unknown>;
  clauses_extracted?: number;
  redlines_identified?: number;
  key_entities?: string[];
  sample_preview?: unknown;
  [key: string]: unknown;
}

export interface EnterpriseIngestSandboxVerification {
  verified?: boolean;
  executed_ok?: boolean;
  passed?: boolean;
  skill_ball_id?: string;
  skill_title?: string;
  engine?: string;
  test_input?: Record<string, unknown>;
  input_payload?: Record<string, unknown>;
  test_output?: unknown;
  output_payload?: unknown;
  actual_output?: unknown;
  latency_ms?: number;
  error_detail?: string;
  [key: string]: unknown;
}

export interface EnterpriseDocumentIngestResponse {
  ingestion_id: string;
  doc_title: string;
  detected_format: string;
  target_department?: string;
  schema_profile: EnterpriseIngestSchemaProfile;
  created_balls: CapabilityBall[];
  mounted_to_slot_id: string | null;
  sandbox_verification: EnterpriseIngestSandboxVerification;
  summary: string;
  token_telemetry?: TokenTelemetryInfo;
  created_at?: string;
  [key: string]: unknown;
}

export interface ClusterSnapshotStats {
  departments_count?: number;
  departments?: number;
  slots_count?: number;
  slots?: number;
  accounts_count?: number;
  accounts?: number;
  balls_count?: number;
  balls?: number;
  tickets_count?: number;
  worm_records?: number;
  total_records?: number;
  [key: string]: unknown;
}

export interface ClusterSnapshotMetadata {
  snapshot_id: string;
  label: string;
  note?: string;
  enterprise_name?: string;
  workspace_mode?: string;
  created_at: string;
  stats?: ClusterSnapshotStats;
  head_hash?: string;
  worm_head_hash?: string;
  file_path?: string;
  size_bytes?: number;
  [key: string]: unknown;
}

export interface SnapshotRestoreResponse {
  status?: string;
  restored?: boolean;
  snapshot_id: string;
  label?: string;
  enterprise_name?: string;
  workspace_mode?: string;
  message?: string;
  summary?: string;
  stats?: ClusterSnapshotStats;
  head_hash?: string;
  [key: string]: unknown;
}

export interface LifecycleCategorySummaryItem {
  category: string;
  count: number;
}

export interface LifecycleCatalogResponse {
  user_id: string;
  slot_id: string;
  is_executive: boolean;
  is_custodian_leader: boolean;
  business_categories: string[];
  type_labels: Record<string, string>;
  categories_summary: LifecycleCategorySummaryItem[];
  active_count: number;
  archived_count: number;
  modules: CustodyBallItem[];
  archived_modules: CustodyBallItem[];
}

export interface LifecycleHealthCandidate {
  candidate_id: string;
  kind: "DUPLICATE_SIMILAR" | "BLOATED_SLOT_IDLE" | "EXPIRED_LEASE" | "SPLIT_BLOATED" | "FORGE_TOOL";
  kind_label: string;
  similarity?: number;
  target_ball_id: string;
  target_title: string;
  merge_into_ball_id?: string;
  merge_into_title?: string;
  target_slot_id?: string;
  target_slot_name?: string;
  business_category?: string;
  type_label?: string;
  raw_policy_text?: string;
  summary: string;
}

export interface LifecycleHealthScanResponse {
  user_id: string;
  active_count: number;
  reaper_candidates: LifecycleHealthCandidate[];
  midwife_candidates: LifecycleHealthCandidate[];
  reaper_count: number;
  midwife_count: number;
}

export interface LifecycleActionResponse {
  ok: boolean;
  summary?: string;
  created_modules?: CustodyBallItem[];
  [key: string]: unknown;
}

export interface WeavePointItem {
  point_id: string;
  ball_type: "DATA" | "SKILL" | "AUTHORITY" | "REDLINE";
  type_label: string;
  title: string;
  summary: string;
  content: string;
  domain_tags: string[];
  sensitivity_level: number;
  has_executable_tool: boolean;
  quick_use_prompt: string;
}

export interface CaveNodeDetail extends SpiderNode {
  occupant_type?: "HUMAN" | "HYBRID_TRANSITION" | "AGENT" | null;
  occupant_id?: string | null;
  occupant_name?: string | null;
  occupant_title?: string | null;
  department?: string | null;
  weave_points: WeavePointItem[];
}

export interface CaveCrossLink {
  link_id: string;
  source_node_id: string;
  target_node_id: string;
  label: string;
  kind: string;
}

export interface StarterDossierItem {
  dossier_id: string;
  enterprise_name: string;
  industry: string;
  summary: string;
  raw_org_material: string;
}

export interface CaveExplorationLogItem {
  log_id: string;
  stage: string;
  message: string;
  node_id?: string | null;
  timestamp: string;
}

export interface CaveExplorationMapResponse {
  mode: "EMPTY_SHELL" | "EXPLORING" | "FULLY_LIT";
  enterprise_name: string;
  has_raw_material: boolean;
  stats: {
    total_nodes: number;
    lit_nodes: number;
    scouted_nodes: number;
    weave_points_count: number;
    cross_links_count: number;
  };
  nodes: CaveNodeDetail[];
  cross_links: CaveCrossLink[];
  logs: CaveExplorationLogItem[];
  starter_dossiers: StarterDossierItem[];
}




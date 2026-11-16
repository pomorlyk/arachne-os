import React, { useEffect, useMemo, useState } from "react";
import {
  Brain,
  CheckCircle2,
  Clock,
  Compass,
  Link2,
  Loader2,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Terminal,
  TrendingDown,
  UserPlus,
  Workflow,
  X,
  Zap,
} from "lucide-react";
import {
  AccountDirectoryEntry,
  CapabilityBall,
  CustodyOverviewPayload,
  UnifiedOverviewPayload,
  UnitSlot,
} from "../types";

import { API_BASE, authFetch } from "../api";
import { CandidateReview } from "./CandidateReview";

export interface AutonomousCommandStudioModalProps {
  open: boolean;
  onClose: () => void;
  account: AccountDirectoryEntry;
  overview: UnifiedOverviewPayload | null;
  custody: CustodyOverviewPayload | null;
  onClusterMutated: () => Promise<void>;
  onToast: (text: string, kind?: "ok" | "err") => void;
  initialTab?: "wargame" | "memory" | "pipelines";
}

type StudioTab = "wargame" | "memory" | "pipelines";

// ============================================================================
// Self-Contained Wave 2 Types (Pillar 5: Wargame, Pillar 6: Memory, Pillar 7: Pipelines)
// ============================================================================

export interface WargameScenarioItem {
  scenario_id: string;
  title: string;
  category?: string;
  shock_magnitude?: string;
  description: string;
  default_horizon_days?: number;
  [key: string]: unknown;
}

export interface WargameDefenseStage {
  stage_index?: number;
  day_range?: string;
  phase?: string;
  department?: string;
  slot_id?: string;
  slot_name?: string;
  action_taken?: string;
  conclusion?: string;
  impact_mitigated?: string;
  triggered_balls?: string[];
  [key: string]: unknown;
}

export interface WargameSimulationResponse {
  simulation_id: string;
  scenario_id?: string;
  scenario_title: string;
  horizon_days: number;
  monte_carlo_paths: number;
  survival_score: number;
  risk_level?: string;
  cashflow_distribution: {
    p10_cny: number;
    p50_cny: number;
    p90_cny: number;
    max_drawdown_cny?: number;
    ruin_probability?: number;
    baseline_cny?: number;
    [key: string]: unknown;
  };
  defense_timeline: WargameDefenseStage[];
  minted_balls: CapabilityBall[];
  executive_summary?: string;
  token_telemetry?: {
    llm_calls?: number;
    estimated_tokens?: number;
    total_latency_ms?: number;
    mode?: string;
  };
  created_at?: string;
  [key: string]: unknown;
}

export interface MemoryCrystalItem {
  crystal_id: string;
  slot_id: string;
  slot_name?: string;
  title: string;
  pattern_type?: string;
  insight: string;
  confidence?: number;
  source_evidence?: string;
  created_at?: string;
  [key: string]: unknown;
}

export interface MemoryDistillResponse {
  distillation_id: string;
  slot_id: string;
  slot_name: string;
  crystals: MemoryCrystalItem[];
  upgraded_balls: CapabilityBall[];
  summary: string;
  token_telemetry?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface HandoverQuizItem {
  question_id?: string;
  question: string;
  expected_action: string;
  cited_ball_id?: string;
  difficulty?: string;
}

export interface ZeroLossHandoverResponse {
  handover_id: string;
  slot_id: string;
  slot_name: string;
  outgoing_occupant?: string;
  incoming_occupant: string;
  handover_fidelity_score?: number;
  inherited_permanent_balls: Array<CapabilityBall | Record<string, unknown> | string>;
  cleaned_leases: Array<Record<string, unknown> | string>;
  transferred_crystals: MemoryCrystalItem[];
  onboarding_quiz: HandoverQuizItem[];
  handover_brief: string;
  created_at?: string;
  [key: string]: unknown;
}

export interface SkillPipelinePresetItem {
  preset_id: string;
  pipeline_instruction?: string;
  pipeline_title: string;
  description: string;
  stage_ball_ids: string[];
  stage_titles?: string[];
  sample_input: Record<string, unknown>;
  [key: string]: unknown;
}

export interface PipelineStageExecution {
  stage_index: number;
  ball_id: string;
  ball_title: string;
  stage_input: Record<string, unknown>;
  stage_output: Record<string, unknown>;
  executed_ok?: boolean;
  latency_ms?: number;
  [key: string]: unknown;
}

export interface SkillPipelineComposeResponse {
  proposal_id?: string;
  proposer_id?: string;
  source_hash?: string;
  candidate_status?: "CANDIDATE" | "ACTIVE" | "REJECTED";
  validation_status?: string;
  promoted?: boolean;
  mounted_to_slot_id?: string | null;
  evidence_provenance?: Record<string, unknown>;
  pipeline_id: string;
  pipeline_title: string;
  master_ball_id: string;
  master_ball?: CapabilityBall;
  stage_ball_ids: string[];
  generated_master_code?: string;
  sample_execution?: {
    executed_ok: boolean;
    stages: PipelineStageExecution[];
    final_output: Record<string, unknown>;
    total_latency_ms?: number;
  };
  summary?: string;
  [key: string]: unknown;
}

export interface SkillPipelineExecuteResponse {
  status?: string;
  sandbox_preview?: boolean;
  execution_evidence?: { business_execution_completed?: boolean; [key: string]: unknown };
  execution_id?: string;
  pipeline_id?: string;
  master_ball_id?: string;
  executed_ok: boolean;
  stages: PipelineStageExecution[];
  final_output: Record<string, unknown>;
  total_latency_ms?: number;
  [key: string]: unknown;
}

// ============================================================================
// Authenticated studio clients
// ============================================================================

export async function apiFetchWargameScenarios(): Promise<WargameScenarioItem[]> {
  const res = await authFetch(`${API_BASE}/api/v1/wargame/scenarios`);
  if (!res.ok) throw new Error(` status ${res.status}`);
  const raw = await res.json();
  const list = Array.isArray(raw)
    ? raw
    : Array.isArray(raw?.scenarios)
      ? raw.scenarios
      : [];
  if (list.length === 0) return [];
  return list.map((item: Record<string, unknown>, idx: number) => ({
    scenario_id: String(
      item.scenario_id ?? item.id ?? `scenario_${idx + 1}`
    ),
    title: String(
      item.title ?? item.scenario_title ?? item.name ?? `黑天鹅剧本 #${idx + 1}`
    ),
    category: item.category ? String(item.category) : undefined,
    shock_magnitude: item.shock_magnitude
      ? String(item.shock_magnitude)
      : item.severity
        ? String(item.severity)
        : undefined,
    description: String(
      item.description ?? item.brief ?? item.shock_description ?? ""
    ),
    default_horizon_days: Number(
      item.default_horizon_days ?? item.horizon_days ?? 60
    ),
  }));
}

export async function apiRunWargameSimulation(params: {
  scenario_id_or_custom: string;
  custom_title: string;
  custom_description: string;
  horizon_days: number;
  monte_carlo_paths: number;
  auto_forge_defensive_balls: boolean;
  shock_parameters?: Record<string, number>;
}): Promise<WargameSimulationResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/wargame/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const raw = await res.json();
  const metrics = raw.monte_carlo_metrics ?? {};
  const dist = raw.cashflow_distribution ?? metrics;
  return {
    ...raw,
    simulation_id: String(raw.simulation_id ?? raw.run_id ?? "未返回"),
    scenario_title: String(raw.scenario_title ?? params.custom_title),
    horizon_days: Number(raw.horizon_days ?? params.horizon_days),
    monte_carlo_paths: Number(raw.monte_carlo_paths ?? metrics.paths_simulated ?? params.monte_carlo_paths),
    survival_score: Number(raw.survival_score ?? metrics.survival_score ?? NaN),
    cashflow_distribution: {
      p10_cny: Number(dist.p10_cny ?? dist.p10_net_cashflow_impact ?? dist.p10_cashflow_cny ?? NaN),
      p50_cny: Number(dist.p50_cny ?? dist.p50_net_cashflow_impact ?? dist.p50_cashflow_cny ?? NaN),
      p90_cny: Number(dist.p90_cny ?? dist.p90_net_cashflow_impact ?? dist.p90_cashflow_cny ?? NaN),
      max_drawdown_cny: Number(dist.max_drawdown_cny ?? dist.max_drawdown ?? NaN),
      ruin_probability: Number(dist.ruin_probability ?? NaN),
    },
    defense_timeline: Array.isArray(raw.timeline_stages) ? raw.timeline_stages : raw.defense_timeline ?? [],
    minted_balls: Array.isArray(raw.forged_defensive_balls) ? raw.forged_defensive_balls : raw.minted_balls ?? [],
    executive_summary: String(raw.executive_commentary ?? raw.executive_summary ?? ""),
  };
}

export async function apiDistillSlotMemory(params: {
  slot_id: string;
  auto_upgrade_balls: boolean;
}): Promise<MemoryDistillResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/memory/distill`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      slot_id: params.slot_id,
      target_slot_id: params.slot_id,
      auto_upgrade_balls: params.auto_upgrade_balls,
      feed_back_to_balls: params.auto_upgrade_balls,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "工位记忆结晶蒸馏失败");
  }
  const raw = await res.json();
  return {
    distillation_id: String(
      raw.distillation_id ?? raw.id ?? `distill_${Date.now()}`
    ),
    slot_id: String(raw.slot_id ?? raw.target_slot_id ?? params.slot_id),
    slot_name: String(raw.slot_name ?? raw.slot_title ?? params.slot_id),
    crystals: Array.isArray(raw.crystals)
      ? raw.crystals
      : Array.isArray(raw.distilled_crystals)
        ? raw.distilled_crystals
        : [],
    upgraded_balls: Array.isArray(raw.upgraded_balls)
      ? raw.upgraded_balls
      : Array.isArray(raw.minted_balls)
        ? raw.minted_balls
        : Array.isArray(raw.balls)
          ? raw.balls
          : [],
    summary: String(
      raw.summary ??
      raw.message ??
      "服务未提供蒸馏结果说明"
    ),
    token_telemetry: raw.token_telemetry,
  };
}

export async function apiExecuteZeroLossHandover(params: {
  slot_id: string;
  new_occupant_name: string;
}): Promise<ZeroLossHandoverResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/memory/zero-loss-handover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      slot_id: params.slot_id,
      target_slot_id: params.slot_id,
      new_occupant_name: params.new_occupant_name,
      incoming_employee_name: params.new_occupant_name,
      new_employee_name: params.new_occupant_name,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "离职零损数字孪生交接生成失败");
  }
  const raw = await res.json();
  const pkg = raw.handover_package ?? raw;
  return {
    handover_id: String(
      raw.handover_id ?? pkg.handover_id ?? `ho_${Date.now()}`
    ),
    slot_id: String(raw.slot_id ?? pkg.slot_id ?? params.slot_id),
    slot_name: String(raw.slot_name ?? pkg.slot_name ?? params.slot_id),
    outgoing_occupant: String(
      raw.outgoing_occupant ??
      pkg.outgoing_occupant ??
      raw.previous_occupant ??
      "前任工位主理人"
    ),
    incoming_occupant: String(
      raw.incoming_occupant ??
      pkg.incoming_occupant ??
      raw.new_occupant_name ??
      params.new_occupant_name
    ),
    handover_fidelity_score: Number(
      raw.handover_fidelity_score ??
      pkg.handover_fidelity_score ??
      raw.retention_rate ??
      NaN
    ),
    inherited_permanent_balls: Array.isArray(pkg.inherited_permanent_balls)
      ? pkg.inherited_permanent_balls
      : Array.isArray(pkg.permanent_balls)
        ? pkg.permanent_balls
        : Array.isArray(raw.inherited_balls)
          ? raw.inherited_balls
          : [],
    cleaned_leases: Array.isArray(pkg.cleaned_leases)
      ? pkg.cleaned_leases
      : Array.isArray(pkg.revoked_leased_balls)
        ? pkg.revoked_leased_balls
        : Array.isArray(raw.cleaned_leases)
          ? raw.cleaned_leases
          : [],
    transferred_crystals: Array.isArray(pkg.transferred_crystals)
      ? pkg.transferred_crystals
      : Array.isArray(pkg.memory_crystals)
        ? pkg.memory_crystals
        : Array.isArray(raw.crystals)
          ? raw.crystals
          : [],
    onboarding_quiz: Array.isArray(pkg.onboarding_quiz)
      ? pkg.onboarding_quiz
      : Array.isArray(pkg.onboarding_challenges)
        ? pkg.onboarding_challenges
        : Array.isArray(raw.onboarding_quiz)
          ? raw.onboarding_quiz
          : [],
    handover_brief: String(
      raw.handover_brief ??
      pkg.handover_brief ??
      raw.summary ??
      "服务未提供交接结果说明。"
    ),
  };
}

export async function apiFetchMemoryCrystals(
  slotId?: string
): Promise<MemoryCrystalItem[]> {
  const url = slotId
    ? `${API_BASE}/api/v1/memory/crystals?slot_id=${encodeURIComponent(slotId)}`
    : `${API_BASE}/api/v1/memory/crystals`;
  const res = await authFetch(url);
  if (!res.ok) return [];
  const raw = await res.json();
  const list = Array.isArray(raw)
    ? raw
    : Array.isArray(raw?.crystals)
      ? raw.crystals
      : [];
  return list;
}

export async function apiFetchPipelinePresets(): Promise<SkillPipelinePresetItem[]> {
  const res = await authFetch(`${API_BASE}/api/v1/pipelines/presets`);
  if (!res.ok) throw new Error(`技能链目录加载失败: ${res.status}`);
  const raw = await res.json();
  const list = Array.isArray(raw)
    ? raw
    : Array.isArray(raw?.presets)
      ? raw.presets
      : [];
  if (list.length === 0) return [];
  return list.map((item: Record<string, unknown>, idx: number) => ({
    preset_id: String(item.preset_id ?? item.id ?? `pipe_preset_${idx + 1}`),
    pipeline_title: String(
      item.pipeline_title ?? item.title ?? item.name ?? `技能链模板 #${idx + 1}`
    ),
    description: String(item.description ?? item.pipeline_instruction ?? item.summary ?? ""),
    pipeline_instruction: typeof item.pipeline_instruction === "string" ? item.pipeline_instruction : undefined,
    stage_ball_ids: Array.isArray(item.source_skill_ball_ids)
      ? item.source_skill_ball_ids.map(String)
      : Array.isArray(item.stage_ball_ids)
      ? item.stage_ball_ids.map(String)
      : Array.isArray(item.skill_ball_ids)
        ? item.skill_ball_ids.map(String)
        : Array.isArray(item.ball_ids)
          ? item.ball_ids.map(String)
          : [],
    stage_titles: Array.isArray(item.stages_preview)
      ? item.stages_preview.map(String)
      : Array.isArray(item.stage_titles)
      ? item.stage_titles.map(String)
      : undefined,
    sample_input:
      item.default_test_payload && typeof item.default_test_payload === "object"
        ? (item.default_test_payload as Record<string, unknown>)
      : item.sample_input && typeof item.sample_input === "object"
        ? (item.sample_input as Record<string, unknown>)
        : item.default_input && typeof item.default_input === "object"
          ? (item.default_input as Record<string, unknown>)
          : {},
  }));
}

export async function apiComposeSkillPipeline(params: {
  preset_id: string;
  pipeline_title: string;
  source_skill_ball_ids: string[];
  target_slot_id: string;
  test_payload: Record<string, unknown>;
}): Promise<SkillPipelineComposeResponse> {
  if (!params.preset_id?.trim()) throw new Error("请明确选择预置模型；未选择模型时不会创建默认业务流水线。");
  const res = await authFetch(`${API_BASE}/api/v1/pipelines/compose`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params),
  });
  const raw = await res.json();
  return {
    ...raw,
    pipeline_id: String(raw.pipeline_id ?? ""),
    pipeline_title: String(raw.pipeline_title ?? params.pipeline_title),
    master_ball_id: String(raw.master_ball_id ?? raw.master_ball?.ball_id ?? ""),
    master_ball: raw.master_ball,
    stage_ball_ids: Array.isArray(raw.source_skill_ball_ids) ? raw.source_skill_ball_ids : [],
    generated_master_code: typeof raw.generated_code === "string" ? raw.generated_code : "",
    summary: typeof raw.summary === "string" ? raw.summary : "候选模型已返回，请检查代码与验证状态。",
  };
}

export async function apiExecuteSkillPipeline(params: {
  pipeline_id: string;
  ball_id?: string;
  payload: Record<string, unknown>;
  sandbox_preview: true;
}): Promise<SkillPipelineExecuteResponse> {
  if (!params.pipeline_id?.trim() || params.sandbox_preview !== true) throw new Error("沙箱预览需要明确的流水线 ID 与显式预览请求。");
  const res = await authFetch(`${API_BASE}/api/v1/pipelines/execute`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params),
  });
  const raw = await res.json();
  const breakdown = Array.isArray(raw.stage_breakdown) ? raw.stage_breakdown : [];
  return {
    ...raw,
    execution_id: typeof raw.execution_id === "string" ? raw.execution_id : undefined,
    pipeline_id: raw.pipeline_id,
    master_ball_id: raw.master_ball_id,
    executed_ok: raw.ok === true || raw.executed_ok === true,
    stages: breakdown.map((stage: Record<string, unknown>, index: number) => ({
      ...stage,
      stage_index: Number(stage.stage_index ?? stage.stage ?? index + 1),
      ball_id: typeof stage.source_ball_id === "string" ? stage.source_ball_id : "",
      ball_title: String(stage.stage_name ?? stage.ball_title ?? `模型阶段 ${index + 1}`),
      stage_input: stage.inputs && typeof stage.inputs === "object" ? stage.inputs : {},
      stage_output: stage.outputs && typeof stage.outputs === "object" ? stage.outputs : stage,
      executed_ok: typeof stage.executed_ok === "boolean" ? stage.executed_ok : undefined,
    })),
    final_output: raw.final_output && typeof raw.final_output === "object" ? raw.final_output : {},
    total_latency_ms: typeof raw.total_latency_ms === "number" ? raw.total_latency_ms : undefined,
  };
}

function formatCny(amount: number | undefined | null): string {
  if (amount === undefined || amount === null || Number.isNaN(amount)) {
    return "未提供";
  }
  const sign = amount < 0 ? "-" : "+";
  const abs = Math.abs(amount);
  if (abs >= 10000) {
    return `${sign}¥${(abs / 10000).toFixed(2)}万`;
  }
  return `${sign}¥${abs.toLocaleString()}`;
}

export const AutonomousCommandStudioModal: React.FC<
  AutonomousCommandStudioModalProps
> = ({
  open,
  onClose,
  account,
  overview,
  custody,
  onClusterMutated,
  onToast,
  initialTab = "wargame",
}) => {
    const [activeTab, setActiveTab] = useState<StudioTab>(initialTab);

    useEffect(() => {
      if (open && initialTab) {
        setActiveTab(initialTab);
      }
    }, [open, initialTab]);

    // Collect available slots & SKILL balls
    const availableSlots = useMemo<UnitSlot[]>(() => {
      const map = new Map<string, UnitSlot>();
      for (const s of overview?.all_slots ?? []) {
        map.set(s.slot_id, s);
      }
      if (overview?.my_slot && !map.has(overview.my_slot.slot_id)) {
        map.set(overview.my_slot.slot_id, overview.my_slot);
      }
      return Array.from(map.values());
    }, [overview]);

    const availableSkillBalls = useMemo<CapabilityBall[]>(() => {
      const map = new Map<string, CapabilityBall>();
      const all = [
        ...(overview?.all_balls ?? []),
        ...(overview?.accessible_balls ?? []),
        ...(custody?.mounted_balls ?? []),
        ...(custody?.managed_balls ?? []),
      ];
      for (const b of all) {
        if (b && b.ball_type === "SKILL" && b.status === "ACTIVE") {
          map.set(b.ball_id, b);
        }
      }
      return Array.from(map.values());
    }, [overview, custody]);

    // ==========================================================================
    // Tab 1 State: Monte Carlo Black-Swan Wargame Simulator
    // ==========================================================================
    const [scenarios, setScenarios] = useState<WargameScenarioItem[]>(
      []
    );
    const [selectedScenarioId, setSelectedScenarioId] = useState<string>(
      ""
    );
    const [wargameTitle, setWargameTitle] = useState<string>(
      ""
    );
    const [wargameDesc, setWargameDesc] = useState<string>(
      ""
    );
    const [horizonDays, setHorizonDays] = useState<number>(60);
    const [monteCarloPaths, setMonteCarloPaths] = useState<number>(50);
    const [autoMintCountermeasures, setAutoMintCountermeasures] =
      useState<boolean>(true);
    const [studioError, setStudioError] = useState<string | null>(null);
    const [customShockJson, setCustomShockJson] = useState('{}');
    const [catalogRetry, setCatalogRetry] = useState(0);
    const [runningWargame, setRunningWargame] = useState<boolean>(false);
    const [wargameResult, setWargameResult] =
      useState<WargameSimulationResponse | null>(null);

    // ==========================================================================
    // Tab 2 State: Slot Memory Crystal Distillation & Zero-Loss Handover
    // ==========================================================================
    const [memorySlotId, setMemorySlotId] = useState<string>(account.slot_id);
    const [autoUpgradeBalls, setAutoUpgradeBalls] = useState<boolean>(true);
    const [distillingMemory, setDistillingMemory] = useState<boolean>(false);
    const [distillResult, setDistillResult] =
      useState<MemoryDistillResponse | null>(null);
    const [existingCrystals, setExistingCrystals] = useState<MemoryCrystalItem[]>(
      []
    );

    const [handoverSlotId, setHandoverSlotId] = useState<string>(account.slot_id);
    const [newOccupantName, setNewOccupantName] = useState<string>(
      "小周 · 新入职接班专员"
    );
    const [runningHandover, setRunningHandover] = useState<boolean>(false);
    const [handoverResult, setHandoverResult] =
      useState<ZeroLossHandoverResponse | null>(null);

    // ==========================================================================
    // Tab 3 State: Multi-Skill Pipeline Composer
    // ==========================================================================
    const [pipelinePresets, setPipelinePresets] = useState<
      SkillPipelinePresetItem[]
    >([]);
    const [selectedPipelinePresetId, setSelectedPipelinePresetId] = useState("");
    const [pipelineTitle, setPipelineTitle] = useState<string>(
      ""
    );
    const [selectedStageBallIds, setSelectedStageBallIds] = useState<string[]>(
      []
    );
    const [pipelineTargetSlotId, setPipelineTargetSlotId] = useState<string>(
      account.slot_id
    );
    const [pipelineInputJson, setPipelineInputJson] = useState<string>(
      JSON.stringify({}, null, 2)
    );
    const [composingPipeline, setComposingPipeline] = useState<boolean>(false);
    const [composedPipeline, setComposedPipeline] =
      useState<SkillPipelineComposeResponse | null>(null);
    const [executingPipeline, setExecutingPipeline] = useState<boolean>(false);
    const [pipelineExecResult, setPipelineExecResult] =
      useState<SkillPipelineExecuteResponse | null>(null);

    useEffect(() => {
      if (!open) return;
      setStudioError(null);
      let active = true;
      const report = (error: unknown) => { if (active) setStudioError(error instanceof Error ? error.message : "目录加载失败，请重试。"); };
      apiFetchWargameScenarios()
        .then((list) => {
          if (!active) return;
          setScenarios(list);
          if (list[0]) { setSelectedScenarioId(list[0].scenario_id); setWargameTitle(list[0].title); setWargameDesc(list[0].description); }
        }).catch(report);

      apiFetchMemoryCrystals(memorySlotId)
        .then((list) => { if (active) setExistingCrystals(list); })
        .catch(report);

      apiFetchPipelinePresets()
        .then((list) => { if (active) setPipelinePresets(list); })
        .catch(report);
      return () => { active = false; };
    }, [open, memorySlotId, catalogRetry]);

    if (!open) return null;

    // ==========================================================================
    // Handlers
    // ==========================================================================

    const handleRunWargame = async (e: React.FormEvent) => {
      e.preventDefault();
      if (runningWargame || !wargameTitle.trim()) return;
      setRunningWargame(true);
      try {
        const res = await apiRunWargameSimulation({
          scenario_id_or_custom: selectedScenarioId || "CUSTOM",
          custom_title: wargameTitle.trim(),
          custom_description: wargameDesc.trim(),
          ...(selectedScenarioId ? {} : { shock_parameters: JSON.parse(customShockJson) }),
          horizon_days: horizonDays,
          monte_carlo_paths: monteCarloPaths,
          auto_forge_defensive_balls: autoMintCountermeasures,
        });
        setWargameResult(res);
        await onClusterMutated();
        onToast(
          `隔离推演「${res.scenario_title}」已返回，生成 ${res.minted_balls.length} 颗候选防御球；效果尚未验证。`,
          "ok"
        );
      } catch (err: unknown) {
        onToast(
          err instanceof Error ? err.message : "黑天鹅经营推演失败",
          "err"
        );
      } finally {
        setRunningWargame(false);
      }
    };

    const handleDistillMemory = async (e: React.FormEvent) => {
      e.preventDefault();
      if (distillingMemory || !memorySlotId) return;
      setDistillingMemory(true);
      try {
        const res = await apiDistillSlotMemory({
          slot_id: memorySlotId,
          auto_upgrade_balls: autoUpgradeBalls,
        });
        setDistillResult(res);
        setExistingCrystals(res.crystals);
        await onClusterMutated();
        onToast(
          `💎 工位「${res.slot_name}」记忆结晶蒸馏完成！提炼 ${res.crystals.length} 枚实战结晶并反哺升级 ${res.upgraded_balls.length} 颗能力球`,
          "ok"
        );
      } catch (err: unknown) {
        onToast(
          err instanceof Error ? err.message : "工位记忆结晶蒸馏失败",
          "err"
        );
      } finally {
        setDistillingMemory(false);
      }
    };

    const handleRunHandover = async (e: React.FormEvent) => {
      e.preventDefault();
      if (runningHandover || !handoverSlotId || !newOccupantName.trim()) return;
      setRunningHandover(true);
      try {
        const res = await apiExecuteZeroLossHandover({
          slot_id: handoverSlotId,
          new_occupant_name: newOccupantName.trim(),
        });
        setHandoverResult(res);
        await onClusterMutated();
        onToast(
          `工位「${res.slot_name}」向「${res.incoming_occupant}」的交接结果已返回，请核对资产明细。`,
          "ok"
        );
      } catch (err: unknown) {
        onToast(
          err instanceof Error ? err.message : "零损数字孪生交接生成失败",
          "err"
        );
      } finally {
        setRunningHandover(false);
      }
    };

    const toggleStageBallId = (ballId: string) => {
      setSelectedStageBallIds((prev) =>
        prev.includes(ballId)
          ? prev.filter((id) => id !== ballId)
          : [...prev, ballId]
      );
    };

    const handleComposePipeline = async (event: React.FormEvent) => {
      event.preventDefault();
      if (composingPipeline || !selectedPipelinePresetId) return;
      let parsedInput: Record<string, unknown>;
      try {
        parsedInput = JSON.parse(pipelineInputJson || "{}");
        if (!parsedInput || typeof parsedInput !== "object" || Array.isArray(parsedInput)) throw new Error();
      } catch { onToast("预览输入必须是 JSON 对象。", "err"); return; }
      setComposingPipeline(true);
      setPipelineExecResult(null);
      try {
        const composed = await apiComposeSkillPipeline({
          preset_id: selectedPipelinePresetId,
          pipeline_title: pipelineTitle.trim(),
          source_skill_ball_ids: selectedStageBallIds,
          target_slot_id: pipelineTargetSlotId,
          test_payload: parsedInput,
        });
        setComposedPipeline(composed);
        await onClusterMutated();
        onToast(`预置模型「${composed.pipeline_title}」已保存为候选，验证状态：${composed.validation_status ?? "未提供"}。请独立审核后发布。`, "ok");
      } catch (error) { onToast(error instanceof Error ? error.message : "候选模型创建失败", "err"); }
      finally { setComposingPipeline(false); }
    };

    const handleReExecutePipelineOnly = async () => {
      if (executingPipeline || !composedPipeline?.pipeline_id) return;
      let parsedInput: Record<string, unknown> = {};
      try {
        parsedInput = JSON.parse(pipelineInputJson || "{}");
        if (!parsedInput || typeof parsedInput !== "object" || Array.isArray(parsedInput)) throw new Error();
      } catch {
        onToast("预览输入参数必须是 JSON 对象", "err");
        return;
      }
      setExecutingPipeline(true);
      try {
        const execRes = await apiExecuteSkillPipeline({
          pipeline_id: composedPipeline.pipeline_id,
          ball_id: composedPipeline.master_ball_id,
          payload: parsedInput,
          sandbox_preview: true,
        });
        setPipelineExecResult(execRes);
        onToast(execRes.executed_ok ? "沙箱进程预览已返回；此结果不是业务交付或发布证明。" : "沙箱预览失败，请查看返回状态。", execRes.executed_ok ? "ok" : "err");
      } catch (err: unknown) {
        onToast(
          err instanceof Error ? err.message : "技能链实弹求解失败",
          "err"
        );
      } finally {
        setExecutingPipeline(false);
      }
    };

    return (
      <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
        <div className="bg-[#131314] border border-[#2d2e30] rounded-xl w-full max-w-6xl max-h-[92vh] flex flex-col shadow-2xl overflow-hidden text-xs text-[#e3e3e3]">
          {/* Header */}
          <div className="px-5 py-3.5 bg-[#18191b] border-b border-[#2d2e30] flex items-center justify-between shrink-0">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-[#fdd663]/15 border border-[#fdd663]/40 flex items-center justify-center text-[#fdd663]">
                <Compass className="w-4 h-4" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-semibold text-[#e3e3e3]">
                    黑天鹅经营推演、工位记忆结晶与多技能链编排中枢 (Autonomous Command Studio)
                  </h2>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#fdd663]/15 text-[#fdd663] border border-[#fdd663]/30">
                    Wave 2 · Pillar 5/6/7/8 Integrated
                  </span>
                </div>
                <p className="text-[11px] text-[#9aa0a6] mt-0.5">
                  蒙特卡洛现金流压力兵棋推演 · 铁打的工位流水的兵（记忆结晶与零损交接） · 多阶段 Python 技能球 DAG 联立编排器
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-[#282a2c] text-[#9aa0a6] hover:text-[#e3e3e3] transition"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* 3 Major Tabs */}
          <div className="px-5 py-2.5 bg-[#18191b]/60 border-b border-[#2d2e30] flex flex-wrap items-center justify-between gap-2 shrink-0">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setActiveTab("wargame")}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-medium border transition flex items-center gap-2 ${activeTab === "wargame"
                    ? "bg-[#fdd663] text-[#131314] border-[#fdd663] font-semibold shadow-sm"
                    : "bg-[#1e1f20] hover:bg-[#282a2c] text-[#9aa0a6] border-[#3c4043]"
                  }`}
              >
                <TrendingDown className="w-3.5 h-3.5" />
                <span>🦢 蒙特卡洛黑天鹅经营推演台</span>
              </button>

              <button
                type="button"
                onClick={() => setActiveTab("memory")}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-medium border transition flex items-center gap-2 ${activeTab === "memory"
                    ? "bg-[#a8c7fa] text-[#062e6f] border-[#a8c7fa] font-semibold shadow-sm"
                    : "bg-[#1e1f20] hover:bg-[#282a2c] text-[#9aa0a6] border-[#3c4043]"
                  }`}
              >
                <Brain className="w-3.5 h-3.5" />
                <span>💎 工位记忆结晶蒸馏 &amp; 离职零损交接</span>
              </button>

              <button
                type="button"
                onClick={() => setActiveTab("pipelines")}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-medium border transition flex items-center gap-2 ${activeTab === "pipelines"
                    ? "bg-[#81c995] text-[#0d3b1e] border-[#81c995] font-semibold shadow-sm"
                    : "bg-[#1e1f20] hover:bg-[#282a2c] text-[#9aa0a6] border-[#3c4043]"
                  }`}
              >
                <Workflow className="w-3.5 h-3.5" />
                <span>🔗 多技能球串联编排器 (Skill Pipeline Composer)</span>
              </button>
            </div>

            <div className="font-mono text-[11px] text-[#9aa0a6]">
              当前席位: <span className="text-[#e3e3e3]">{account.name}</span> (
              {account.slot_id})
            </div>
          </div>

          {/* Main Content Area */}
          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            {/* ================================================================
              TAB 1: 🦢 蒙特卡洛黑天鹅经营推演台
             ================================================================ */}
            {activeTab === "wargame" && (
              <div className="space-y-4">
                <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Sparkles className="w-4 h-4 text-[#fdd663]" />
                      <span className="font-semibold text-[#e3e3e3]">
                        四大黑天鹅极端经营冲击剧本一键装填 (`/api/v1/wargame/scenarios`)
                      </span>
                    </div>
                    <span className="text-[11px] text-[#9aa0a6]">
                      结合蒙特卡洛随机游走模拟现金流分布，驱动跨部门 Agent 自动锻造止损球
                    </span>
                  </div>

                  {/* 4 Black Swan Scenario Cards */}
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2.5">
                    {scenarios.map((sc) => {
                      const isSelected = selectedScenarioId === sc.scenario_id;
                      return (
                        <button
                          key={sc.scenario_id}
                          type="button"
                          onClick={() => {
                            setSelectedScenarioId(sc.scenario_id);
                            setWargameTitle(sc.title);
                            setWargameDesc(sc.description);
                            if (sc.default_horizon_days) {
                              setHorizonDays(sc.default_horizon_days);
                            }
                          }}
                          className={`p-3 rounded-lg border text-left transition flex flex-col justify-between gap-2 ${isSelected
                              ? "bg-[#fdd663]/15 border-[#fdd663] text-[#e3e3e3]"
                              : "bg-[#131314] hover:bg-[#1e1f20] border-[#2d2e30] text-[#9aa0a6]"
                            }`}
                        >
                          <div className="space-y-1">
                            <div className="font-semibold text-xs text-[#e3e3e3] line-clamp-1">
                              {sc.title}
                            </div>
                            <p className="text-[11px] text-[#9aa0a6] line-clamp-2 leading-relaxed">
                              {sc.description}
                            </p>
                          </div>
                          {sc.shock_magnitude && (
                            <div className="pt-1 border-t border-[#2d2e30]/60">
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-[#f28b82]/15 text-[#f28b82]">
                                ⚡ {sc.shock_magnitude}
                              </span>
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>

                  {/* Simulation Parameters Form */}
                  {studioError && <div role="alert" className="text-xs text-[#f28b82] p-3 border rounded">{studioError} <button type="button" onClick={() => setCatalogRetry(value => value + 1)} className="underline">重试目录加载</button></div>}
                  <form onSubmit={handleRunWargame} className="space-y-3 pt-1">
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                      <div className="space-y-1">
                        <label className="text-[11px] text-[#9aa0a6] block">
                          黑天鹅剧本标题
                        </label>
                        <input
                          required
                          value={wargameTitle}
                          onChange={(e) => { setWargameTitle(e.target.value); setSelectedScenarioId(""); }}
                          className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#fdd663] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                        />
                      </div>
                      <div className="md:col-span-3 space-y-1">
                        <label className="text-[11px] text-[#9aa0a6] block">
                          外部冲击与链式反应描述
                        </label>
                        <input
                          required
                          value={wargameDesc}
                          onChange={(e) => { setWargameDesc(e.target.value); setSelectedScenarioId(""); }}
                          className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#fdd663] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                        />
                      </div>
                    </div>

                    {!selectedScenarioId && <label className="block text-xs text-[#9aa0a6]">自定义定量冲击参数（JSON）：locked_order_revenue_cny、baseline_gross_margin_pct、unhedged_margin_drop_pct、base_stockout_prob<textarea required value={customShockJson} onChange={event => setCustomShockJson(event.target.value)} className="w-full mt-2 p-2 rounded bg-[#131314] border border-[#3c4043]" /></label>}
                    <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                      <div className="flex flex-wrap items-center gap-4">
                        {/* Horizon Days: 30 / 60 / 90 */}
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] text-[#9aa0a6]">
                            推演周期 (Horizon):
                          </span>
                          <div className="flex items-center gap-1">
                            {[30, 60, 90].map((d) => (
                              <button
                                key={d}
                                type="button"
                                onClick={() => setHorizonDays(d)}
                                className={`px-2.5 py-1 rounded-md font-mono text-xs border transition ${horizonDays === d
                                    ? "bg-[#fdd663] text-[#131314] border-[#fdd663] font-bold"
                                    : "bg-[#131314] text-[#9aa0a6] border-[#3c4043]"
                                  }`}
                              >
                                {d}天
                              </button>
                            ))}
                          </div>
                        </div>

                        {/* Monte Carlo Paths: 20 / 50 */}
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] text-[#9aa0a6]">
                            蒙特卡洛随机路径数:
                          </span>
                          <div className="flex items-center gap-1">
                            {[20, 50].map((p) => (
                              <button
                                key={p}
                                type="button"
                                onClick={() => setMonteCarloPaths(p)}
                                className={`px-2.5 py-1 rounded-md font-mono text-xs border transition ${monteCarloPaths === p
                                    ? "bg-[#a8c7fa] text-[#062e6f] border-[#a8c7fa] font-bold"
                                    : "bg-[#131314] text-[#9aa0a6] border-[#3c4043]"
                                  }`}
                              >
                                {p}条路径
                              </button>
                            ))}
                          </div>
                        </div>

                        <label className="flex items-center gap-2 text-[11px] text-[#e3e3e3] cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={autoMintCountermeasures}
                            onChange={(e) =>
                              setAutoMintCountermeasures(e.target.checked)
                            }
                            className="rounded border-[#3c4043] bg-[#131314] text-[#fdd663]"
                          />
                          <span>
                            生成候选防御球（仅保存在隔离推演工作区）
                          </span>
                        </label>
                      </div>

                      <button
                        type="submit"
                        disabled={runningWargame || !wargameTitle.trim()}
                        className="px-5 py-2 rounded-lg bg-[#fdd663] hover:bg-[#fde082] text-[#131314] font-semibold text-xs flex items-center gap-2 disabled:opacity-40 transition shadow-md"
                      >
                        {runningWargame ? (
                          <>
                            <Loader2 className="w-4 h-4 animate-spin" />
                            <span>
                              正在跑 {monteCarloPaths} 条隔离蒙特卡洛路径…
                            </span>
                          </>
                        ) : (
                          <>
                            <Zap className="w-4 h-4" />
                            <span>🦢 启动黑天鹅蒙特卡洛兵棋推演</span>
                          </>
                        )}
                      </button>
                    </div>
                  </form>
                </div>

                {/* Wargame Result Visualization */}
                {wargameResult && (
                  <div className="space-y-4">
                    {/* P10 / P50 / P90 Cashflow Distribution & Survival Score */}
                    <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
                      <div className="p-3.5 rounded-xl bg-[#18191b] border border-[#81c995]/50 flex flex-col justify-between">
                        <div className="text-[10px] text-[#9aa0a6] uppercase font-mono">
                          企业生存韧性评分 (Survival Score)
                        </div>
                        <div className="text-2xl font-mono font-bold text-[#81c995] mt-1">
                          {Number.isFinite(wargameResult.survival_score) ? wargameResult.survival_score : "未提供"}
                          <span className="text-xs font-normal text-[#9aa0a6]">
                            {" "}
                            / 100
                          </span>
                        </div>
                        <div className="text-[10px] font-mono text-[#81c995] mt-1">
                          {wargameResult.horizon_days}天 ·{" "}
                          {wargameResult.monte_carlo_paths}条随机路径
                        </div>
                      </div>

                      <div className="p-3.5 rounded-xl bg-[#18191b] border border-[#f28b82]/40 flex flex-col justify-between">
                        <div className="text-[10px] text-[#f28b82] font-mono">
                          P10 悲观极值净现金流冲击
                        </div>
                        <div className="text-xl font-mono font-bold text-[#f28b82] mt-1">
                          {formatCny(wargameResult.cashflow_distribution.p10_cny)}
                        </div>
                        <div className="text-[10px] text-[#9aa0a6]">
                          10% 尾部极端恶化分位点
                        </div>
                      </div>

                      <div className="p-3.5 rounded-xl bg-[#18191b] border border-[#fdd663]/40 flex flex-col justify-between">
                        <div className="text-[10px] text-[#fdd663] font-mono">
                          P50 中位基准净现金流预期
                        </div>
                        <div className="text-xl font-mono font-bold text-[#fdd663] mt-1">
                          {formatCny(wargameResult.cashflow_distribution.p50_cny)}
                        </div>
                        <div className="text-[10px] text-[#9aa0a6]">
                          50% 中位数防御后稳态净流
                        </div>
                      </div>

                      <div className="p-3.5 rounded-xl bg-[#18191b] border border-[#81c995]/40 flex flex-col justify-between">
                        <div className="text-[10px] text-[#81c995] font-mono">
                          P90 乐观反制净现金流分位
                        </div>
                        <div className="text-xl font-mono font-bold text-[#81c995] mt-1">
                          {formatCny(wargameResult.cashflow_distribution.p90_cny)}
                        </div>
                        <div className="text-[10px] text-[#9aa0a6]">
                          90% 应急球全面生效分位点
                        </div>
                      </div>

                      <div className="p-3.5 rounded-xl bg-[#18191b] border border-[#2d2e30] flex flex-col justify-between">
                        <div className="text-[10px] text-[#9aa0a6] font-mono">
                          最大现金流回撤 &amp; 破产概率
                        </div>
                        <div className="text-base font-mono font-bold text-[#e3e3e3] mt-1">
                          {formatCny(
                            wargameResult.cashflow_distribution.max_drawdown_cny
                          )}
                        </div>
                        <div className="text-[10px] font-mono text-[#a8c7fa]">
                          断流概率:{" "}
                          {Number.isFinite(wargameResult.cashflow_distribution.ruin_probability)
                            ? `${((wargameResult.cashflow_distribution.ruin_probability ?? 0) * 100).toFixed(1)}%`
                            : "未提供"}
                        </div>
                      </div>
                    </div>

                    {/* Defense Timeline & Auto-Minted Countermeasure Balls */}
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                      {/* Stage-by-Stage Defense Timeline */}
                      <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Clock className="w-4 h-4 text-[#fdd663]" />
                            <span className="font-semibold text-[#e3e3e3]">
                              逐阶段多部门协同防御时间线 (`defense_timeline`)
                            </span>
                          </div>
                          <span className="font-mono text-[10px] text-[#9aa0a6]">
                            Run: {String(wargameResult.run_id ?? wargameResult.simulation_id)} · {((wargameResult.scope as { isolated?: boolean } | undefined)?.isolated === true) ? "已隔离" : "隔离状态未提供"}
                          </span>
                        </div>

                        <div className="space-y-2.5">
                          {wargameResult.defense_timeline.map((st, idx) => (
                            <div
                              key={idx}
                              className="p-3 rounded-lg bg-[#131314] border border-[#2d2e30] space-y-1.5"
                            >
                              <div className="flex items-center justify-between">
                                <span className="font-mono font-bold text-[#fdd663]">
                                  {st.day_range ??
                                    st.phase ??
                                    `Stage #${st.stage_index ?? idx + 1}`}
                                </span>
                                <span className="px-2 py-0.5 rounded text-[10px] bg-[#1e1f20] text-[#a8c7fa] font-mono">
                                  {st.department ??
                                    st.slot_name ??
                                    st.slot_id ??
                                    "跨部门联防"}
                                </span>
                              </div>
                              <div className="text-[11px] text-[#e3e3e3] leading-relaxed">
                                {st.action_taken ??
                                  st.conclusion ??
                                  JSON.stringify(st)}
                              </div>
                              {st.impact_mitigated && (
                                <div className="text-[10px] font-mono text-[#81c995]">
                                  ✓ 止损成效: {st.impact_mitigated}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Auto-Forged Emergency REDLINE & Stop-Loss SKILL Balls */}
                      <div className="p-4 rounded-xl bg-[#18191b] border border-[#81c995]/40 space-y-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <ShieldCheck className="w-4 h-4 text-[#81c995]" />
                            <span className="font-semibold text-[#81c995]">
                              当场自动锻造的应急 `REDLINE` 球与止损 `SKILL` 球
                            </span>
                          </div>
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#81c995]/15 text-[#81c995]">
                            {wargameResult.minted_balls.length} 颗候选防御球（隔离区）
                          </span>
                        </div>

                        <p className="text-xs text-[#fdd663]">此结果来自情景模型，不代表真实经营业绩。候选防御措施的实际效果尚未测量。</p>
                        {wargameResult.executive_summary && (
                          <div className="p-2.5 rounded bg-[#131314] border border-[#2d2e30] text-[11px] text-[#e3e3e3]">
                            {wargameResult.executive_summary}
                          </div>
                        )}

                        <div className="space-y-2.5">
                          {wargameResult.minted_balls.map((b, idx) => (
                            <div
                              key={b.ball_id ?? idx}
                              className="p-3 rounded-lg bg-[#131314] border border-[#2d2e30] space-y-1.5"
                            >
                              <div className="flex items-center justify-between">
                                <span
                                  className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${b.ball_type === "REDLINE"
                                      ? "bg-[#f28b82]/20 text-[#f28b82]"
                                      : "bg-[#81c995]/20 text-[#81c995]"
                                    }`}
                                >
                                  [{b.ball_type}] {b.title}
                                </span>
                                <span className="font-mono text-[10px] text-[#9aa0a6]">
                                  {b.ball_id}
                                </span>
                              </div>
                              <pre className="p-2 rounded bg-[#0d0e10] border border-[#2d2e30] font-mono text-[10px] text-[#e3e3e3] max-h-32 overflow-y-auto whitespace-pre-wrap">
                                {b.content}
                              </pre>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ================================================================
              TAB 2: 💎 工位记忆结晶蒸馏 & 离职零损交接
             ================================================================ */}
            {activeTab === "memory" && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Left Column: Slot Memory Crystal Distillation */}
                <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3 flex flex-col">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Brain className="w-4 h-4 text-[#a8c7fa]" />
                      <span className="font-semibold text-[#e3e3e3]">
                        🧠 工位实战记忆结晶蒸馏 (`/api/v1/memory/distill`)
                      </span>
                    </div>
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#a8c7fa]/15 text-[#a8c7fa]">
                      实战智慧沉淀
                    </span>
                  </div>

                  <p className="text-[11px] text-[#9aa0a6]">
                    从工位历史对话、工单博弈与审批拦截记录中提炼高纯度「经验记忆结晶」，并自动反哺升级该工位挂载的
                    DATA / SKILL / REDLINE 能力球。
                  </p>

                  <form onSubmit={handleDistillMemory} className="space-y-3">
                    <div className="space-y-1">
                      <label className="text-[11px] text-[#9aa0a6] block">
                        选择目标蒸馏工位 (`slot_id`)
                      </label>
                      <select
                        value={memorySlotId}
                        onChange={(e) => setMemorySlotId(e.target.value)}
                        className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                      >
                        {availableSlots.map((s) => (
                          <option key={s.slot_id} value={s.slot_id}>
                            {s.slot_name} ({s.department} · {s.slot_id})
                          </option>
                        ))}
                      </select>
                    </div>

                    <label className="flex items-center gap-2 text-[11px] text-[#e3e3e3] cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={autoUpgradeBalls}
                        onChange={(e) => setAutoUpgradeBalls(e.target.checked)}
                        className="rounded border-[#3c4043] bg-[#131314] text-[#a8c7fa]"
                      />
                      <span>
                        蒸馏后自动将隐性经验反哺写入工位能力球并递增版本号 (`v+1`)
                      </span>
                    </label>

                    <button
                      type="submit"
                      disabled={distillingMemory}
                      className="w-full py-2 px-4 rounded-lg bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] font-semibold text-xs flex items-center justify-center gap-2 disabled:opacity-40 transition shadow-md"
                    >
                      {distillingMemory ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin" />
                          <span>正在萃取工位历史实战轨迹并反哺升级球体...</span>
                        </>
                      ) : (
                        <>
                          <Sparkles className="w-4 h-4" />
                          <span>🧠 蒸馏工位实战记忆结晶并反哺升级能力球</span>
                        </>
                      )}
                    </button>
                  </form>

                  {/* Distilled Crystals Display */}
                  {(distillResult || existingCrystals.length > 0) && (
                    <div className="space-y-2.5 pt-2 border-t border-[#2d2e30]">
                      {distillResult?.summary && (
                        <div className="p-2.5 rounded bg-[#131314] border border-[#a8c7fa]/40 text-[11px] text-[#a8c7fa]">
                          ✓ {distillResult.summary}
                        </div>
                      )}

                      <div className="text-[11px] font-semibold text-[#e3e3e3]">
                        已沉淀的工位记忆结晶 (
                        {(distillResult?.crystals ?? existingCrystals).length} 枚):
                      </div>

                      <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                        {(distillResult?.crystals ?? existingCrystals).map(
                          (cr, idx) => (
                            <div
                              key={cr.crystal_id ?? idx}
                              className="p-3 rounded-lg bg-[#131314] border border-[#2d2e30] space-y-1"
                            >
                              <div className="flex items-center justify-between">
                                <span className="font-semibold text-[#a8c7fa]">
                                  💎 {cr.title}
                                </span>
                                <span className="font-mono text-[10px] text-[#81c995]">
                                  置信度:{" "}
                                  {Math.round((cr.confidence ?? NaN) * 100)}%
                                </span>
                              </div>
                              <div className="text-[11px] text-[#e3e3e3] leading-relaxed">
                                {cr.insight}
                              </div>
                            </div>
                          )
                        )}
                      </div>

                      {distillResult &&
                        distillResult.upgraded_balls.length > 0 && (
                          <div className="space-y-1.5 pt-1">
                            <div className="text-[11px] font-semibold text-[#81c995]">
                              反哺升级的能力球 ({distillResult.upgraded_balls.length}
                              ):
                            </div>
                            {distillResult.upgraded_balls.map((ub, idx) => (
                              <div
                                key={ub.ball_id ?? idx}
                                className="p-2 rounded bg-[#131314] border border-[#81c995]/30 font-mono text-[11px] flex items-center justify-between"
                              >
                                <span className="text-[#e3e3e3]">
                                  [{ub.ball_type}] {ub.title}
                                </span>
                                <span className="text-[#81c995]">
                                  v{ub.version ?? 2} · UPGRADED
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                    </div>
                  )}
                </div>

                {/* Right Column: Zero-Loss Digital Twin Handover */}
                <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3 flex flex-col">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <UserPlus className="w-4 h-4 text-[#81c995]" />
                      <span className="font-semibold text-[#e3e3e3]">
                        🔄 铁打的工位流水的兵 · 离职零损交接 (`/api/v1/memory/zero-loss-handover`)
                      </span>
                    </div>
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#81c995]/15 text-[#81c995]">
                      交接资产明细
                    </span>
                  </div>

                  <p className="text-[11px] text-[#9aa0a6]">
                    人员流动时，核对工位容器的常驻能力球与实战记忆结晶的
                    留在工位内无缝继承，临时借用球租约自动清理回收，并生成新员工上岗实测陪练题。
                  </p>

                  <form onSubmit={handleRunHandover} className="space-y-3">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                      <div className="space-y-1">
                        <label className="text-[11px] text-[#9aa0a6] block">
                          交接目标工位容器 (`slot_id`)
                        </label>
                        <select
                          value={handoverSlotId}
                          onChange={(e) => setHandoverSlotId(e.target.value)}
                          className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#81c995] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                        >
                          {availableSlots.map((s) => (
                            <option key={s.slot_id} value={s.slot_id}>
                              {s.slot_name} ({s.slot_id})
                            </option>
                          ))}
                        </select>
                      </div>

                      <div className="space-y-1">
                        <label className="text-[11px] text-[#9aa0a6] block">
                          新接任员工姓名 (`new_occupant_name`)
                        </label>
                        <input
                          required
                          value={newOccupantName}
                          onChange={(e) => setNewOccupantName(e.target.value)}
                          placeholder="例如：小周 · 新入职接班专员"
                          className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#81c995] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                        />
                      </div>
                    </div>

                    <button
                      type="submit"
                      disabled={runningHandover || !newOccupantName.trim()}
                      className="w-full py-2 px-4 rounded-lg bg-[#81c995] hover:bg-[#95d5a7] text-[#0d3b1e] font-semibold text-xs flex items-center justify-center gap-2 disabled:opacity-40 transition shadow-md"
                    >
                      {runningHandover ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin" />
                          <span>正在打包常驻球、回收临时租约并生成上岗考核...</span>
                        </>
                      ) : (
                        <>
                          <RefreshCw className="w-4 h-4" />
                          <span>🔄 生成并演练「零损数字孪生交接包」</span>
                        </>
                      )}
                    </button>
                  </form>

                  {/* Handover Result Display */}
                  {handoverResult && (
                    <div className="space-y-2.5 pt-2 border-t border-[#2d2e30] max-h-80 overflow-y-auto pr-1">
                      <div className="p-2.5 rounded bg-[#131314] border border-[#81c995]/40 flex items-center justify-between">
                        <div>
                          <div className="font-semibold text-[#81c995]">
                            {handoverResult.outgoing_occupant} ➔{" "}
                            {handoverResult.incoming_occupant}
                          </div>
                          <div className="text-[10px] text-[#9aa0a6]">
                            {handoverResult.handover_brief}
                          </div>
                        </div>
                        <span className="font-mono text-sm font-bold text-[#81c995]">
                          {handoverResult.handover_fidelity_score ?? "未提供"}% 保真
                        </span>
                      </div>

                      <div className="grid grid-cols-2 gap-2">
                        <div className="p-2.5 rounded bg-[#131314] border border-[#2d2e30]">
                          <div className="text-[10px] font-semibold text-[#a8c7fa] mb-1">
                            常驻球继承明细 (
                            {handoverResult.inherited_permanent_balls.length})
                          </div>
                          <div className="space-y-1 font-mono text-[10px] text-[#e3e3e3]">
                            {handoverResult.inherited_permanent_balls.map(
                              (b, idx) => (
                                <div key={idx} className="truncate">
                                  •{" "}
                                  {typeof b === "string"
                                    ? b
                                    : String(
                                      (b as Record<string, unknown>).title ??
                                      (b as Record<string, unknown>).ball_id
                                    )}
                                </div>
                              )
                            )}
                          </div>
                        </div>

                        <div className="p-2.5 rounded bg-[#131314] border border-[#2d2e30]">
                          <div className="text-[10px] font-semibold text-[#fdd663] mb-1">
                            🧹 临时借用租约自动清理 (
                            {handoverResult.cleaned_leases.length})
                          </div>
                          <div className="space-y-1 font-mono text-[10px] text-[#9aa0a6]">
                            {handoverResult.cleaned_leases.length === 0 ? (
                              <div>无残留未归还临时租约 (已净空)</div>
                            ) : (
                              handoverResult.cleaned_leases.map((l, idx) => (
                                <div key={idx} className="truncate">
                                  •{" "}
                                  {typeof l === "string"
                                    ? l
                                    : JSON.stringify(l)}
                                </div>
                              ))
                            )}
                          </div>
                        </div>
                      </div>

                      {handoverResult.onboarding_quiz.length > 0 && (
                        <div className="p-2.5 rounded bg-[#131314] border border-[#2d2e30] space-y-1.5">
                          <div className="text-[10px] font-semibold text-[#81c995]">
                            🎓 新接任员工上岗实测题 (`onboarding_quiz`):
                          </div>
                          {handoverResult.onboarding_quiz.map((q, idx) => (
                            <div
                              key={idx}
                              className="p-2 rounded bg-[#18191b] border border-[#2d2e30] space-y-0.5 text-[11px]"
                            >
                              <div className="font-medium text-[#e3e3e3]">
                                Q{idx + 1}: {q.question}
                              </div>
                              <div className="text-[10px] text-[#81c995]">
                                标准防线动作: {q.expected_action}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ================================================================
              TAB 3: 🔗 多技能球串联编排器 (Skill Pipeline Composer)
             ================================================================ */}
            {activeTab === "pipelines" && (
              <div className="space-y-4">
                {studioError && <div role="alert" className="text-xs text-[#f28b82] p-3 border rounded">{studioError} <button type="button" onClick={() => setCatalogRetry(value => value + 1)} className="underline">重试目录加载</button></div>}
                {/* Presets & Pipeline Composer Form */}
                <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Workflow className="w-4 h-4 text-[#81c995]" />
                      <span className="font-semibold text-[#e3e3e3]">
                        选择明确的预置流水线模型
                      </span>
                    </div>
                    <span className="text-[11px] text-[#9aa0a6]">
                      预置模板生成候选代码，来源引用不代表实际执行来源技能代码。
                    </span>
                  </div>

                  {/* 3 Pipeline Preset Cards */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
                    {pipelinePresets.map((pr) => {
                      const isSelected = selectedPipelinePresetId === pr.preset_id;
                      return (
                        <button
                          key={pr.preset_id}
                          type="button"
                          onClick={() => {
                            setSelectedPipelinePresetId(pr.preset_id);
                            setComposedPipeline(null);
                            setPipelineExecResult(null);
                            setPipelineTitle(pr.pipeline_title);
                            setSelectedStageBallIds(pr.stage_ball_ids);
                            setPipelineInputJson(
                              JSON.stringify(pr.sample_input, null, 2)
                            );
                          }}
                          className={`p-3 rounded-lg border text-left transition flex flex-col justify-between gap-2 ${isSelected
                              ? "bg-[#81c995]/15 border-[#81c995] text-[#e3e3e3]"
                              : "bg-[#131314] hover:bg-[#1e1f20] border-[#2d2e30] text-[#9aa0a6]"
                            }`}
                        >
                          <div className="space-y-1">
                            <div className="font-semibold text-xs text-[#e3e3e3] line-clamp-1">
                              {pr.pipeline_title}
                            </div>
                            <p className="text-[11px] text-[#9aa0a6] line-clamp-2">
                              {pr.description}
                            </p>
                          </div>
                          <div className="flex flex-wrap gap-1 pt-1 border-t border-[#2d2e30]/60">
                            {pr.stage_ball_ids.map((id, idx) => (
                              <span
                                key={id}
                                className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-[#1e1f20] text-[#81c995]"
                              >
                                S{idx + 1}: {id}
                              </span>
                            ))}
                          </div>
                        </button>
                      );
                    })}
                  </div>

                  {/* Custom Skill Selection & Test Input Form */}
                  <form
                    onSubmit={handleComposePipeline}
                    className="space-y-3 pt-1"
                  >
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                      <div className="md:col-span-2 space-y-1">
                        <label className="text-[11px] text-[#9aa0a6] block">
                          复合技能链名称 (`pipeline_title`)
                        </label>
                        <input
                          required
                          value={pipelineTitle}
                          onChange={(e) => setPipelineTitle(e.target.value)}
                          className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#81c995] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                        />
                      </div>

                      <div className="space-y-1">
                        <label className="text-[11px] text-[#9aa0a6] block">
                          拟发布目标工位（创建候选时不挂载）
                        </label>
                        <select
                          value={pipelineTargetSlotId}
                          onChange={(e) =>
                            setPipelineTargetSlotId(e.target.value)
                          }
                          className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#81c995] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                        >
                          {availableSlots.map((s) => (
                            <option key={s.slot_id} value={s.slot_id}>
                              {s.slot_name} ({s.slot_id})
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>

                    {/* Multi-Skill Checkboxes */}
                    <div className="space-y-1.5">
                      <label className="text-[11px] text-[#9aa0a6] block">
                        可调整来源技能引用（不执行来源代码，当前引用{" "}
                        {selectedStageBallIds.length} 项）:
                      </label>
                      <div className="flex flex-wrap gap-2">
                        {availableSkillBalls.map((b) => {
                          const stageIdx = selectedStageBallIds.indexOf(
                            b.ball_id
                          );
                          const isChecked = stageIdx !== -1;
                          return (
                            <button
                              key={b.ball_id}
                              type="button"
                              onClick={() => toggleStageBallId(b.ball_id)}
                              className={`px-2.5 py-1.5 rounded-lg text-[11px] font-mono border transition flex items-center gap-1.5 ${isChecked
                                  ? "bg-[#81c995]/20 border-[#81c995] text-[#81c995] font-semibold"
                                  : "bg-[#131314] border-[#3c4043] text-[#9aa0a6]"
                                }`}
                            >
                              {isChecked && (
                                <span className="px-1.5 py-0.2 rounded bg-[#81c995] text-[#0d3b1e] font-bold text-[10px]">
                                  引用 {stageIdx + 1}
                                </span>
                              )}
                              <span>{b.title}</span>
                              <span className="text-[10px] opacity-75">
                                ({b.ball_id})
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    <div className="space-y-1">
                      <label className="text-[11px] text-[#9aa0a6] block">
                        沙箱预览输入参数 JSON
                      </label>
                      <textarea
                        rows={3}
                        value={pipelineInputJson}
                        onChange={(e) => setPipelineInputJson(e.target.value)}
                        className="w-full bg-[#0d0e10] border border-[#3c4043] focus:border-[#81c995] rounded-lg px-3 py-2 font-mono text-[11px] text-[#81c995] outline-none"
                      />
                    </div>

                    <div className="flex flex-wrap items-center justify-end gap-2.5">
                      {composedPipeline && (
                        <button
                          type="button"
                          disabled={executingPipeline || !composedPipeline.pipeline_id}
                          onClick={handleReExecutePipelineOnly}
                          className="px-4 py-2 rounded-lg bg-[#282a2c] hover:bg-[#35373a] text-[#a8c7fa] border border-[#a8c7fa]/40 font-medium text-xs flex items-center gap-1.5 transition"
                        >
                          <Play className="w-3.5 h-3.5" />
                          <span>沙箱预览此候选模型（不执行业务）</span>
                        </button>
                      )}

                      <button
                        type="submit"
                        disabled={
                          composingPipeline || !selectedPipelinePresetId
                        }
                        className="px-5 py-2 rounded-lg bg-[#81c995] hover:bg-[#95d5a7] text-[#0d3b1e] font-semibold text-xs flex items-center gap-2 disabled:opacity-40 transition shadow-md"
                      >
                        {composingPipeline ? (
                          <>
                            <Loader2 className="w-4 h-4 animate-spin" />
                            <span>
                              正在创建未发布的候选模型…
                            </span>
                          </>
                        ) : (
                          <>
                            <Link2 className="w-4 h-4" />
                            <span>
                              创建候选模型（不挂载、不发布）
                            </span>
                          </>
                        )}
                      </button>
                    </div>
                  </form>
                </div>

                {/* Stage 1 -> Stage 2 -> Stage 3 Execution Breakdown */}
                {(composedPipeline || pipelineExecResult) && (
                  <div className="space-y-4">
                    {composedPipeline && (
                      <div className="p-3.5 rounded-xl bg-[#18191b] border border-[#81c995]/50 flex flex-wrap items-center justify-between gap-3">
                        <div className="flex items-center gap-2.5">
                          <CheckCircle2 className="w-5 h-5 text-[#81c995]" />
                          <div>
                            <div className="font-semibold text-xs text-[#e3e3e3]">
                              预置流水线候选：{composedPipeline.pipeline_title}
                            </div>
                            <div className="font-mono text-[10px] text-[#9aa0a6]">
                              Master Ball ID:{" "}
                              <strong className="text-[#81c995]">
                                {composedPipeline.master_ball_id}
                              </strong>{" "}
                              · Pipeline ID: {composedPipeline.pipeline_id}
                            </div>
                          </div>
                        </div>
                        <span className="px-2.5 py-1 rounded text-[10px] font-mono bg-[#81c995]/15 text-[#81c995]">
                          {composedPipeline.candidate_status ?? composedPipeline.master_ball?.status ?? "状态未提供"} · {composedPipeline.validation_status ?? "验证状态未提供"}
                        </span>
                      </div>
                    )}

                    {composedPipeline && <div className="p-3 rounded border border-[#3c4043] space-y-2">
                      <p className="text-xs text-[#fdd663]">创建候选不代表发布或业务完成。进程可执行性不等于业务语义正确，发布需要独立已知结果样本验证。</p>
                      <pre className="p-2 bg-[#131314] whitespace-pre-wrap break-words max-h-72 overflow-auto text-[11px]">{composedPipeline.generated_master_code || "未提供源代码，不能开展代码审核。"}</pre>
                      {composedPipeline.proposal_id && composedPipeline.source_hash && composedPipeline.generated_master_code
                        ? <CandidateReview report={{proposal_id: composedPipeline.proposal_id, source_hash: composedPipeline.source_hash, proposer_id: composedPipeline.proposer_id, promoted: composedPipeline.promoted === true, candidate_status: composedPipeline.candidate_status, validation_status: composedPipeline.validation_status}} reviewerId={account.user_id} onPublished={async report => {
                            if (report) setComposedPipeline(previous => previous ? {...previous, ...report} : previous);
                            await onClusterMutated();
                          }} />
                        : <p className="text-xs text-[#9aa0a6]">缺少独立发布审核所需的候选编号、源码或哈希。</p>}
                    </div>}
                    {pipelineExecResult && (
                      <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Terminal className="w-4 h-4 text-[#a8c7fa]" />
                            <span className="font-semibold text-[#e3e3e3]">
                              沙箱进程预览 · 预置模型输出
                            </span>
                          </div>
                          <span className="font-mono text-[11px] text-[#81c995]">
                            Total Latency:{" "}
                            {Number.isFinite(pipelineExecResult.total_latency_ms) ? Math.round(pipelineExecResult.total_latency_ms!) : "未提供"}
                            ms
                          </span>
                        </div>

                        <p className="text-xs text-[#fdd663]">{pipelineExecResult.status ?? "状态未提供"} · 进程{pipelineExecResult.executed_ok ? "成功返回" : "失败 / 未确认"} · 仅供沙箱检查；不代表生产发布、实际业务完成或业务语义验证。</p>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                          {(pipelineExecResult.stages ?? []).map((st, idx) => (
                            <div
                              key={idx}
                              className="p-3 rounded-lg bg-[#131314] border border-[#2d2e30] space-y-2 font-mono text-[11px]"
                            >
                              <div className="flex items-center justify-between">
                                <span className="px-2 py-0.5 rounded bg-[#a8c7fa]/20 text-[#a8c7fa] font-bold text-[10px]">
                                  Stage #{st.stage_index ?? idx + 1}
                                </span>
                                <span className="text-[10px] text-[#81c995]">
                                  {st.executed_ok === true ? "进程阶段已返回" : st.executed_ok === false ? "阶段失败" : "无独立阶段验证"}
                                </span>
                              </div>
                              <div className="font-sans font-semibold text-[#e3e3e3] text-xs">
                                {st.ball_title ?? st.ball_id}
                              </div>
                              <div className="p-2 rounded bg-[#0d0e10] border border-[#2d2e30]">
                                <div className="text-[10px] text-[#9aa0a6] mb-0.5">
                                  本阶计算输出 (`stage_output`):
                                </div>
                                <pre className="text-[10px] text-[#81c995] overflow-x-auto whitespace-pre-wrap">
                                  {JSON.stringify(st.stage_output, null, 2)}
                                </pre>
                              </div>
                            </div>
                          ))}
                        </div>

                        {/* Final Combined Output */}
                        <div className="p-3.5 rounded-lg bg-[#0d0e10] border border-[#81c995]/40 space-y-1.5 font-mono">
                          <div className="text-[11px] font-semibold text-[#81c995]">
                            预置模型的沙箱输出（未经独立语义验证）：
                          </div>
                          <pre className="text-[11px] text-[#e3e3e3] overflow-x-auto whitespace-pre-wrap">
                            {JSON.stringify(
                              pipelineExecResult.final_output,
                              null,
                              2
                            )}
                          </pre>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

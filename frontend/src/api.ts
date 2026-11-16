import {
  AccountDirectoryEntry,
  AdversarialDebateResponse,
  AutonomousPatrolResponse,
  BallDecomposeResponse,
  ClusterSnapshotMetadata,
  CrucibleReportsHistoryResponse,
  DagMissionExecutionResponse,
  DaySimulationStatus,
  EnterpriseDeployResponse,
  EnterpriseDocumentIngestResponse,
  EnterpriseIngestSampleItem,
  FacadeBotType,
  GenesisTemplateItem,
  LifecycleActionResponse,
  LifecycleCatalogResponse,
  LifecycleHealthScanResponse,
  LLMTelemetrySnapshot,
  MissionPresetItem,
  MissionsHistoryResponse,
  RedlinePenetrationResponse,
  RoleViewType,
  SkillStressTestResponse,
  SnapshotRestoreResponse,
  UnifiedOverviewPayload,
} from "./types";

export const API_BASE = (import.meta.env?.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
export function getWebSocketUrl(): string {
  const origin = typeof location !== "undefined" ? location.origin : "http://localhost:5173";
  const url = new URL(`${API_BASE}/ws/events`, origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
export class ApiError extends Error {
  constructor(message: string, public readonly status: number) { super(message); this.name = "ApiError"; }
}
export class AuthenticationError extends ApiError {
  constructor(message = "登录已失效，请重新登录。") { super(message, 401); this.name = "AuthenticationError"; }
}
const authInvalidationListeners = new Set<() => void>();
export function onAuthenticationRequired(listener: () => void): () => void {
  authInvalidationListeners.add(listener);
  return () => { authInvalidationListeners.delete(listener); };
}
export function invalidateAuthentication(): void {
  setStoredAuthToken(null);
  authInvalidationListeners.forEach(listener => listener());
}
export const AUTH_TOKEN_STORAGE_KEY = "arachne_auth_token_v1";

let memoryAuthToken: string | null = null;

export function getStoredAuthToken(): string | null {
  if (memoryAuthToken) {
    return memoryAuthToken;
  }
  try {
    if (typeof localStorage !== "undefined") {
      const stored = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
      if (stored) {
        memoryAuthToken = stored;
        return stored;
      }
    }
  } catch {
    // Ignore storage access failures in headless/Node environments
  }
  return null;
}

export function setStoredAuthToken(token: string | null): void {
  const clean = token && token.trim() ? token.trim() : null;
  memoryAuthToken = clean;
  try {
    if (typeof localStorage !== "undefined") {
      if (clean) {
        localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, clean);
      } else {
        localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
      }
    }
  } catch {
    // Ignore storage access failures in headless/Node environments
  }
}

export function buildAuthHeaders(extra?: HeadersInit): Record<string, string> {
  const merged: Record<string, string> = {};
  if (extra) {
    if (typeof Headers !== "undefined" && extra instanceof Headers) {
      extra.forEach((value, key) => {
        merged[key] = value;
      });
    } else if (Array.isArray(extra)) {
      for (const [key, value] of extra) {
        merged[key] = value;
      }
    } else {
      Object.assign(merged, extra);
    }
  }
  const token = getStoredAuthToken();
  if (token && !merged.Authorization && !merged.authorization) {
    merged.Authorization = `Bearer ${token}`;
  }
  return merged;
}

export async function authFetch(
  input: string,
  init: RequestInit = {},
  allowHttpErrors = false
): Promise<Response> {
  const token = getStoredAuthToken();
  if (!token) {
    invalidateAuthentication();
    throw new AuthenticationError("请先登录后再执行此操作。");
  }
  const res = await fetch(input, { ...init, headers: buildAuthHeaders(init.headers) });
  if (res.status === 401) {
    // An old request must never revoke a newer login.
    if (getStoredAuthToken() === token) invalidateAuthentication();
    throw new AuthenticationError();
  }
  if (!res.ok && !allowHttpErrors) {
    const error = await res.clone().json().catch(() => ({}));
    const detail = typeof error.detail === "string" ? error.detail : JSON.stringify(error.detail ?? "请求失败");
    throw new ApiError(`${detail} (HTTP ${res.status})`, res.status);
  }
  return res;
}

export async function fetchCurrentAccount(): Promise<AccountDirectoryEntry> {
  const res = await authFetch(`${API_BASE}/api/v1/auth/me`);
  const data = await res.json();
  if (!data.account?.user_id || !data.account?.role_view) throw new Error("登录身份响应不完整，请重试。");
  return data.account;
}

export function deriveDepartmentTabs(
  accounts: Array<{ department?: string }>
): Array<{ key: string; label: string }> {
  const counts = new Map<string, number>();
  for (const acc of accounts) {
    const dept = (acc.department || "").trim();
    if (!dept) continue;
    counts.set(dept, (counts.get(dept) ?? 0) + 1);
  }
  const tabs: Array<{ key: string; label: string }> = [
    { key: "ALL", label: `全部 (${accounts.length})` },
  ];
  for (const [dept, count] of counts.entries()) {
    tabs.push({ key: dept, label: `${dept} (${count})` });
  }
  return tabs;
}

export async function fetchOverview(
  roleView: RoleViewType,
  userId: string
): Promise<UnifiedOverviewPayload> {
  const res = await authFetch(
    `${API_BASE}/api/v1/state/overview?role_view=${encodeURIComponent(roleView)}&user_id=${encodeURIComponent(userId)}`
  );
  if (!res.ok) {
    throw new Error(`Overview request failed: ${res.status}`);
  }
  return res.json();
}

export async function sendChatMessage(params: {
  sender_id: string;
  role_view: RoleViewType;
  facade_bot: FacadeBotType;
  chat_type?: "SINGLE" | "GROUP";
  content: string;
  raw_wechat_forward?: string[];
}) {
  const res = await authFetch(`${API_BASE}/api/v1/chat/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_type: "SINGLE",
      raw_wechat_forward: [],
      ...params,
    }),
  });
  return res.json();
}

export async function submitHumanToolCard(params: {
  actor_user_id: string;
  card_id: string;
  submitted_output: Record<string, unknown>;
}) {
  const res = await authFetch(`${API_BASE}/api/v1/human-tool/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  }, true);
  const data = await res.json();
  return { status: res.status, data };
}

export async function proposeEvolutionSkill(params: {
  proposer_id: string;
  natural_instruction: string;
}) {
  const res = await authFetch(`${API_BASE}/api/v1/evolution/propose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  return res.json();
}

export async function triggerSwarmDrill(params: {
  mode: "BURST_PAD" | "HALLUCINATION_FAULT" | "DEHYDRATE_IDLE" | "BORROW_BALL";
  parent_node_id?: string;
  burst_count?: number;
  subtree_root_id?: string;
}) {
  const res = await authFetch(`${API_BASE}/api/v1/swarm/inject-burst`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  return res.json();
}

export async function conveneBoard(params?: {
  agenda?: string;
  target_slot_id?: string;
  force_security_veto?: boolean;
}) {
  const res = await authFetch(`${API_BASE}/api/v1/board/convene`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params ?? {}),
  });
  return res.json();
}

export async function decideBoardTransition(params: {
  resolution_id: string;
  approve: boolean;
}) {
  const res = await authFetch(`${API_BASE}/api/v1/board/approve-transition`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "操作被拦截");
  }
  return res.json();
}

export async function executeVaultRollback(params: {
  scope: "LOCAL" | "GLOBAL";
  subtree_root_id?: string;
  reason: string;
}) {
  const res = await authFetch(`${API_BASE}/api/v1/vault/rollback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  return res.json();
}

export async function fetchSimulationStatus(): Promise<DaySimulationStatus> {
  const res = await authFetch(`${API_BASE}/api/v1/simulation/status`);
  return res.json();
}

export async function stepSimulation(): Promise<DaySimulationStatus> {
  const res = await authFetch(`${API_BASE}/api/v1/simulation/step`, {
    method: "POST",
  });
  return res.json();
}

export async function runFullDaySimulation(): Promise<DaySimulationStatus> {
  const res = await authFetch(`${API_BASE}/api/v1/simulation/run-full-day`, {
    method: "POST",
  });
  return res.json();
}

export async function resetDaySimulation(): Promise<DaySimulationStatus> {
  const res = await authFetch(`${API_BASE}/api/v1/simulation/reset`, {
    method: "POST",
  });
  return res.json();
}

export async function fetchLLMTelemetry(): Promise<LLMTelemetrySnapshot> {
  const res = await authFetch(`${API_BASE}/api/v1/llm/telemetry`);
  return res.json();
}

export async function fetchAuthAccounts() {
  const res = await fetch(`${API_BASE}/api/v1/auth/accounts`);
  if (!res.ok) throw new ApiError(`人员名录加载失败 (HTTP ${res.status})`, res.status);
  return res.json();
}

export async function loginAccount(username: string, password: string) {
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "登录失败");
  }
  const data = await res.json();
  if (typeof data?.token === "string" && data.token) {
    setStoredAuthToken(data.token);
  }
  try {
    if (!getStoredAuthToken()) throw new AuthenticationError("登录响应缺少凭证。");
    return { ...data, account: await fetchCurrentAccount() };
  } catch (error) {
    setStoredAuthToken(null);
    throw error;
  }
}

export async function logoutAccount(): Promise<{ ok?: boolean }> {
  const token = getStoredAuthToken();
  try {
    const res = await authFetch(`${API_BASE}/api/v1/auth/logout`, {
      method: "POST",
    });
    if (res.ok) {
      return await res.json().catch(() => ({ ok: true }));
    }
    return { ok: false };
  } finally {
    if (getStoredAuthToken() === token) setStoredAuthToken(null);
  }
}

export async function fetchCustodyOverview(userId: string) {
  const res = await authFetch(
    `${API_BASE}/api/v1/custody/overview?user_id=${encodeURIComponent(userId)}`
  );
  if (!res.ok) throw new Error("Failed to load custody overview");
  return res.json();
}

export async function requestBallAccess(params: {
  requester_id: string;
  ball_id: string;
  grant_mode: "LEASE_TTL" | "PERMANENT";
  ttl_minutes: number;
  reason: string;
}) {
  const res = await authFetch(`${API_BASE}/api/v1/custody/requests`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "申请失败");
  }
  return res.json();
}

export async function decideBallRequest(
  requestId: string,
  params: { actor_user_id: string; approve: boolean; comment?: string }
) {
  const res = await authFetch(
    `${API_BASE}/api/v1/custody/requests/${encodeURIComponent(requestId)}/decide`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "审批失败");
  }
  return res.json();
}

export async function directGrantBall(params: {
  leader_user_id: string;
  target_slot_id: string;
  ball_id: string;
  grant_mode: "LEASE_TTL" | "PERMANENT";
  ttl_minutes?: number;
}) {
  const res = await authFetch(`${API_BASE}/api/v1/custody/grant`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "派发失败");
  }
  return res.json();
}

export async function revokeBallFromSlot(params: {
  leader_user_id: string;
  target_slot_id: string;
  ball_id: string;
}) {
  const res = await authFetch(`${API_BASE}/api/v1/custody/revoke`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "收回失败");
  }
  return res.json();
}

export async function fetchGenesisTemplates(): Promise<{
  templates?: GenesisTemplateItem[];
  [key: string]: unknown;
} | GenesisTemplateItem[]> {
  const res = await authFetch(`${API_BASE}/api/v1/genesis/templates`);
  if (!res.ok) {
    throw new Error(`获取行业模板失败: ${res.status}`);
  }
  return res.json();
}

export async function deployEnterpriseBlueprint(params: {
  enterprise_name: string;
  business_description: string;
  reset_existing: boolean;
}): Promise<EnterpriseDeployResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/genesis/deploy-enterprise`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "企业集群空投孵化失败");
  }
  return res.json();
}

export async function decomposeOrSplitBalls(params: {
  actor_user_id: string;
  raw_policy_text?: string;
  target_ball_id?: string;
}): Promise<BallDecomposeResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/genesis/decompose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "拆球/细胞分裂执行失败");
  }
  return res.json();
}

export async function triggerAutonomousPatrol(params?: {
  actor_user_id?: string;
}): Promise<AutonomousPatrolResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/genesis/autonomous-patrol`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params ?? {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "集群自主能动巡检执行失败");
  }
  return res.json();
}

// ============================================================================
// Phase 3 (v5.0) API Clients: Pillar 1 (Missions), Pillar 2 (Crucible), Pillar 3 (Ingest & Snapshots)
// ============================================================================

// Pillar 1: Multi-Agent DAG Missions & Adversarial Debate (/api/v1/missions/*)
export async function fetchMissionPresets(): Promise<
  { presets?: MissionPresetItem[];[key: string]: unknown } | MissionPresetItem[]
> {
  const res = await authFetch(`${API_BASE}/api/v1/missions/presets`);
  if (!res.ok) {
    throw new Error(`获取战役预设失败: ${res.status}`);
  }
  return res.json();
}

export async function executeDagMission(params: {
  mission_title: string;
  mission_brief: string;
  initiator_account_id?: string | null;
  max_debate_rounds?: number;
  auto_execute_skills?: boolean;
}): Promise<DagMissionExecutionResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/missions/execute-dag`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      max_debate_rounds: 2,
      auto_execute_skills: true,
      ...params,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "跨部门 DAG 联合作战执行失败");
  }
  return res.json();
}

export async function runAdversarialDebate(params: {
  topic: string;
  proposer_slot_id: string;
  reviewer_slot_id: string;
  arbiter_slot_id?: string | null;
  rounds?: number;
}): Promise<AdversarialDebateResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/missions/adversarial-debate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      rounds: 3,
      ...params,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "双工位对抗辩论执行失败");
  }
  return res.json();
}

export async function fetchMissionsHistory(): Promise<
  MissionsHistoryResponse | Array<Record<string, unknown>>
> {
  const res = await authFetch(`${API_BASE}/api/v1/missions/history`);
  if (!res.ok) {
    throw new Error(`获取战役与辩论历史失败: ${res.status}`);
  }
  return res.json();
}

// Pillar 2: Red-Blue Adversarial Crucible & Redline Penetration (/api/v1/crucible/*)
export async function stressTestSkillInCrucible(params: {
  ball_id: string;
  attack_intensity?: "STANDARD" | "EXTREME";
  auto_heal?: boolean;
  max_generations?: number;
}): Promise<SkillStressTestResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/crucible/stress-test-skill`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      attack_intensity: "EXTREME",
      auto_heal: true,
      max_generations: 3,
      ...params,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "技能球红蓝对抗自愈执行失败");
  }
  return res.json();
}

export async function runRedlinePenetrationAudit(params: {
  target_slot_id: string;
  attack_count?: number;
}): Promise<RedlinePenetrationResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/crucible/redline-penetration`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      attack_count: 4,
      ...params,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "工位红线穿刺压力审计执行失败");
  }
  return res.json();
}

export async function fetchCrucibleReports(): Promise<
  CrucibleReportsHistoryResponse | Array<Record<string, unknown>>
> {
  const res = await authFetch(`${API_BASE}/api/v1/crucible/reports`);
  if (!res.ok) {
    throw new Error(`获取红蓝对抗与穿刺报告失败: ${res.status}`);
  }
  return res.json();
}

// Pillar 3: Enterprise Document Ingestor & Snapshot Time-Machine (/api/v1/ingest/* & /api/v1/snapshots/*)
export async function fetchIngestSamples(): Promise<
  | { samples?: EnterpriseIngestSampleItem[];[key: string]: unknown }
  | EnterpriseIngestSampleItem[]
> {
  const res = await authFetch(`${API_BASE}/api/v1/ingest/samples`);
  if (!res.ok) {
    throw new Error(`获取企业样本数据失败: ${res.status}`);
  }
  return res.json();
}

export async function ingestEnterpriseDocument(params: {
  doc_title: string;
  doc_format: "CSV" | "JSON" | "CONTRACT_MD" | "AUTO";
  raw_content: string;
  target_department: string;
  target_slot_id?: string | null;
  auto_forge_query_skill?: boolean;
}): Promise<EnterpriseDocumentIngestResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/ingest/document`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      auto_forge_query_skill: true,
      ...params,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "企业文档/台账深度吞噬执行失败");
  }
  return res.json();
}

export async function fetchClusterSnapshots(): Promise<
  | { snapshots?: ClusterSnapshotMetadata[];[key: string]: unknown }
  | ClusterSnapshotMetadata[]
> {
  const res = await authFetch(`${API_BASE}/api/v1/snapshots/list`);
  if (!res.ok) {
    throw new Error(`获取集群快照列表失败: ${res.status}`);
  }
  return res.json();
}

export async function saveClusterSnapshot(params: {
  label: string;
  note: string;
}): Promise<ClusterSnapshotMetadata> {
  const res = await authFetch(`${API_BASE}/api/v1/snapshots/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "保存集群状态快照失败");
  }
  return res.json();
}

export async function restoreClusterSnapshot(params: {
  snapshot_id: string;
}): Promise<SnapshotRestoreResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/snapshots/restore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "回滚恢复集群快照失败");
  }
  return res.json();
}

export async function deleteClusterSnapshot(snapshotId: string): Promise<{
  deleted: boolean;
  snapshot_id: string;
}> {
  const res = await authFetch(
    `${API_BASE}/api/v1/snapshots/${encodeURIComponent(snapshotId)}`,
    { method: "DELETE" }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "删除集群快照失败");
  }
  return res.json();
}

// ============================================================================
// v7.0 Capability Taxonomy & Lifecycle API (/api/v1/lifecycle/*)
// ============================================================================

export async function fetchLifecycleCatalog(
  userId: string
): Promise<LifecycleCatalogResponse> {
  const res = await authFetch(
    `${API_BASE}/api/v1/lifecycle/catalog?user_id=${encodeURIComponent(userId)}`
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "加载能力目录失败");
  }
  return res.json();
}

export async function fetchLifecycleHealthScan(
  userId: string
): Promise<LifecycleHealthScanResponse> {
  const res = await authFetch(
    `${API_BASE}/api/v1/lifecycle/health-scan?user_id=${encodeURIComponent(userId)}`
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "扫描冗余模块失败");
  }
  return res.json();
}

export async function incubateOrSplitModule(params: {
  actor_user_id: string;
  raw_policy_text?: string;
  target_ball_id?: string;
}): Promise<LifecycleActionResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/lifecycle/incubate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "能力拆分或孵化失败");
  }
  return res.json();
}

export async function reapOrMergeModule(params: {
  actor_user_id: string;
  action: "ARCHIVE" | "MERGE";
  target_ball_id: string;
  merge_into_ball_id?: string;
  reason?: string;
}): Promise<LifecycleActionResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/lifecycle/reap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "模块清理或合并失败");
  }
  return res.json();
}

export async function autoSweepLifecycle(params: {
  actor_user_id: string;
}): Promise<LifecycleActionResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/lifecycle/auto-sweep`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "一键清理失败");
  }
  return res.json();
}

export async function restoreArchivedModule(params: {
  actor_user_id: string;
  ball_id: string;
  target_slot_id?: string;
}): Promise<LifecycleActionResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/lifecycle/restore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "恢复模块失败");
  }
  return res.json();
}

export async function fetchCaveExplorationMap(): Promise<
  import("./types").CaveExplorationMapResponse
> {
  const res = await authFetch(`${API_BASE}/api/v1/exploration/map`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "获取探索织网图谱失败");
  }
  return res.json();
}

export async function resetToEmptyShell(params: {
  enterprise_name?: string;
}): Promise<import("./types").CaveExplorationMapResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/exploration/empty-shell`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "重置空壳失败");
  }
  return res.json();
}

export async function scoutOrganizationStructure(params: {
  enterprise_name: string;
  raw_org_material: string;
}): Promise<import("./types").CaveExplorationMapResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/exploration/scout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "火把探路失败");
  }
  return res.json();
}

export async function plantTorchAndWeave(params: {
  target_node_id: string;
  raw_sop_text?: string;
}): Promise<import("./types").CaveExplorationMapResponse> {
  const res = await authFetch(`${API_BASE}/api/v1/exploration/plant-torch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "插火把照亮并织网失败");
  }
  return res.json();
}

export async function provisionAccountPassword(
  userId: string,
  payload: { new_password: string }
): Promise<{ ok: boolean; user_id: string }> {
  const res = await authFetch(
    `${API_BASE}/api/v1/auth/accounts/${encodeURIComponent(userId)}/password`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "设置账号口令失败");
  }
  return res.json();
}

export async function handoverSlotOccupant(params: {
  actor_user_id?: string;
  target_slot_id: string;
  new_user_id: string;
  new_person_name: string;
  handover_mode: "RESIGN_HANDOVER" | "LEAVE_DELEGATION" | "TEMP_RELIEF";
  reason?: string;
  initial_password?: string;
}): Promise<{
  ok: boolean;
  target_slot_id: string;
  slot_name: string;
  handover_mode: string;
  previous_user_id: string;
  new_user_id: string;
  new_person_name: string;
  inherited_ball_ids: string[];
  inherited_ball_count: number;
  password_provisioned?: boolean;
  rehydrated_node_ids?: string[];
  reason: string;
}> {
  const res = await authFetch(`${API_BASE}/api/v1/custody/handover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "岗位人员交接失败");
  }
  return res.json();
}

export async function toggleSpiderNodeLifecycle(params: {
  nodeId: string;
  action: "DEHYDRATE" | "REHYDRATE";
  role_view?: string;
  reason?: string;
}): Promise<{
  action: "DEHYDRATE" | "REHYDRATE";
  node: import("./types").SpiderNode;
  rehydrated_node_ids: string[];
}> {
  const res = await authFetch(
    `${API_BASE}/api/v1/swarm/nodes/${encodeURIComponent(params.nodeId)}/lifecycle`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: params.action,
        role_view: params.role_view ?? "boss",
        reason: params.reason ?? "topology_manual_toggle",
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "切换节点脱水/热唤醒状态失败");
  }
  return res.json();
}




export async function publishEvolutionCandidate(proposalId: string, params: {
  reviewer_id: string;
  approved_source_hash: string;
  independent_samples: Array<{ input_payload: Record<string, unknown>; expected_output: unknown }>;
}) {
  const res = await authFetch(`${API_BASE}/api/v1/evolution/candidates/${encodeURIComponent(proposalId)}/publish`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params),
  });
  return res.json();
}

/** Load only endpoints authorized for the verified identity. */
export async function fetchWorkspaceState(account: Pick<AccountDirectoryEntry, "user_id" | "role_view">) {
  const executive = account.role_view === "manager" || account.role_view === "boss";
  return Promise.all([
    fetchOverview(account.role_view, account.user_id),
    fetchCustodyOverview(account.user_id),
    executive ? fetchLLMTelemetry() : Promise.resolve(null),
    executive ? fetchSimulationStatus() : Promise.resolve(null),
  ]);
}

export async function submitShadowOutputReview(params: {
  ticket_id: string;
  human_final_text: string;
}): Promise<{
  ticket_id: string;
  reviewer_id: string;
  score: { similarity_ratio?: number; replaceability_score?: number; [key: string]: unknown };
}> {
  const res = await authFetch(`${API_BASE}/api/v1/scoring/shadow-reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  return res.json();
}

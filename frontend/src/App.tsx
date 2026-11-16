import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Layers,
  LogOut,
  MessageSquare,
  Network,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import {
  conveneBoard,
  decideBallRequest,
  decideBoardTransition,
  executeVaultRollback,
  fetchCurrentAccount,
  AuthenticationError,
  onAuthenticationRequired,
  fetchWorkspaceState,
  stepSimulation,
  runFullDaySimulation,
  resetDaySimulation,
  getStoredAuthToken,
  logoutAccount,
  sendChatMessage,
  setStoredAuthToken,
  submitHumanToolCard,
  triggerSwarmDrill,
} from "./api";
import { connectAuthenticatedEvents, createRefreshScheduler } from "./sessionTransport";
import { DaySimulationTimeline } from "./components/DaySimulationTimeline";
import { BallCustodyPanel } from "./components/BallCustodyPanel";
import { CapabilityCenterView } from "./components/CapabilityCenterView";
import { ClusterOperationsBar } from "./components/ClusterOperationsBar";
import { ExecutiveControlDeck } from "./components/ExecutiveControlDeck";
import { LoginGateView } from "./components/LoginGateView";
import { SpiderTopologyFlow } from "./components/SpiderTopologyFlow";
import { WeComSimulatorPane } from "./components/WeComSimulatorPane";
import {
  AccountDirectoryEntry,
  DaySimulationStatus,
  CustodyBallItem,
  CustodyOverviewPayload,
  FacadeBotType,
  LLMTelemetrySnapshot,
  UnifiedOverviewPayload,
} from "./types";

type MainStageView = "stream" | "capabilities" | "canvas" | "governance";
export const App: React.FC = () => {
  const [account, setAccount] = useState<AccountDirectoryEntry | null>(null);
  const [sessionChecking, setSessionChecking] = useState(!!getStoredAuthToken());
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const identityGeneration = useRef(0);
  const stateInFlight = useRef<Promise<void> | null>(null);
  const [activeBot, setActiveBot] = useState<FacadeBotType>("COPILOT");
  const [stageView, setStageView] = useState<MainStageView>("stream");
  const [pendingQuickPrompt, setPendingQuickPrompt] = useState<{
    text: string;
    bot: FacadeBotType;
    nonce: number;
  } | null>(null);
  const [overview, setOverview] = useState<UnifiedOverviewPayload | null>(null);
  const [custody, setCustody] = useState<CustodyOverviewPayload | null>(null);
  const [simStatus, setSimStatus] = useState<DaySimulationStatus | null>(null);
  const [telemetry, setTelemetry] = useState<LLMTelemetrySnapshot | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [toast, setToast] = useState<{ text: string; kind: "ok" | "err" } | null>(null);
  const [wsConnected, setWsConnected] = useState<boolean>(false);

  const showToast = useCallback((text: string, kind: "ok" | "err" = "ok") => {
    setToast({ text, kind });
    setTimeout(() => {
      setToast((prev) => (prev?.text === text ? null : prev));
    }, 4000);
  }, []);

  const clearIdentity = useCallback(() => {
    identityGeneration.current += 1;
    stateInFlight.current = null;
    setStoredAuthToken(null);
    setAccount(null);
    setOverview(null);
    setCustody(null);
    setTelemetry(null);
    setSimStatus(null);
    setWsConnected(false);
    setBusyAction(null);
    setSessionChecking(false);
  }, []);

  const restoreSession = useCallback(async () => {
    if (!getStoredAuthToken()) { setSessionChecking(false); return; }
    const generation = identityGeneration.current;
    setSessionChecking(true);
    setSessionError(null);
    try {
      const verified = await fetchCurrentAccount();
      if (generation === identityGeneration.current) setAccount(verified);
    } catch (error) {
      if (error instanceof AuthenticationError) clearIdentity();
      else setSessionError(error instanceof Error ? error.message : "身份验证服务暂时不可用。");
    } finally { setSessionChecking(false); }
  }, [clearIdentity]);

  useEffect(() => onAuthenticationRequired(() => {
    clearIdentity();
    setSessionError("登录已失效，请使用账号密码重新登录。");
  }), [clearIdentity]);
  useEffect(() => { void restoreSession(); }, [restoreSession]);

  const handleSwitchAccount = useCallback(async (_nextAcc: AccountDirectoryEntry) => {
    await logoutAccount().catch(() => undefined);
    clearIdentity();
    setSessionError("请明确选择账号并输入密码登录新的工作空间。");
    return null;
  }, [clearIdentity]);

  const handleQuickUse = useCallback(
    (promptText: string, ballType: CustodyBallItem["ball_type"]) => {
      const bot: FacadeBotType =
        ballType === "AUTHORITY" || ballType === "REDLINE"
          ? "GOVERNANCE"
          : "COPILOT";
      setActiveBot(bot);
      setStageView("stream");
      setPendingQuickPrompt({ text: promptText, bot, nonce: Date.now() });
    },
    []
  );

  const loadState = useCallback(async () => {
    if (!account) return;
    if (stateInFlight.current) return stateInFlight.current;
    const generation = identityGeneration.current;
    const request = (async () => {
      try {
        const [data, cust, tele, simulation] = await fetchWorkspaceState(account);
        if (generation !== identityGeneration.current) return;
        setOverview(data);
        setCustody(cust);
        setTelemetry(tele);
        setSimStatus(simulation);
        setLoadError(null);
      } catch (error) {
        if (generation !== identityGeneration.current) return;
        if (error instanceof AuthenticationError) clearIdentity();
        else setLoadError(error instanceof Error ? error.message : "工作台加载失败，请重试。");
      } finally {
        if (generation === identityGeneration.current) setLoading(false);
      }
    })();
    stateInFlight.current = request;
    try { await request; } finally {
      if (stateInFlight.current === request) stateInFlight.current = null;
    }
  }, [account, clearIdentity]);

  useEffect(() => {
    if (!account) return;
    setLoading(true);
    loadState();
    if (account.role_view === "boss") {
      setActiveBot("BOARD_INSIDER");
    } else if (account.is_custodian_leader) {
      setActiveBot("GOVERNANCE");
    } else {
      setActiveBot("COPILOT");
    }
    setStageView((prev) =>
      prev === "governance" &&
        account.role_view !== "manager" &&
        account.role_view !== "boss"
        ? "stream"
        : prev
    );
  }, [account, loadState]);

  useEffect(() => {
    if (!account) return;
    const refresh = createRefreshScheduler(loadState);
    const disconnect = connectAuthenticatedEvents(setWsConnected, refresh.schedule);
    return () => { refresh.dispose(); disconnect(); };
  }, [account, loadState]);

  const handleLoginSuccess = (_token: string, loggedAcc: AccountDirectoryEntry) => {
    identityGeneration.current += 1;
    stateInFlight.current = null;
    setSessionError(null);
    setLoadError(null);
    setAccount(loggedAcc);
    setStageView("stream");
    showToast(`欢迎登录，${loggedAcc.name}（${loggedAcc.department} · ${loggedAcc.title}）`);
  };

  const handleLogout = () => {
    const pendingLogout = logoutAccount();
    clearIdentity();
    void pendingLogout.catch(() => undefined);
  };

  if (sessionChecking || (sessionError && getStoredAuthToken() && !account)) {
    return <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-[#131314] text-[#e3e3e3] p-6" role="status">
      <p>{sessionChecking ? "正在验证登录身份…" : sessionError}</p>
      {!sessionChecking && <><button onClick={() => void restoreSession()} className="px-4 py-2 rounded bg-[#282a2c]">重试身份验证</button><button onClick={handleLogout}>返回登录</button></>}
    </div>;
  }

  if (!account) {
    return <LoginGateView onLoginSuccess={handleLoginSuccess} notice={sessionError} />;
  }

  const isExecutive =
    account.role_view === "manager" || account.role_view === "boss";
  const canViewCanvas = isExecutive;

  const pendingActionCount =
    (overview?.pending_approval_cards?.length ??
      overview?.pending_cards?.length ??
      0) +
    (custody?.pending_subordinate_requests?.length ?? 0) +
    (account.role_view === "boss"
      ? (overview?.board_resolutions ?? []).filter(
        (r) => r.status === "PENDING_BOSS"
      ).length
      : 0);

  const performSimulation = async (action: "step" | "run" | "reset") => {
    const generation = identityGeneration.current;
    setBusyAction(`simulation-${action}`);
    try {
      const result = await (action === "step" ? stepSimulation() : action === "run" ? runFullDaySimulation() : resetDaySimulation());
      if (generation === identityGeneration.current) setSimStatus(result);
    } catch (error) { showToast(error instanceof Error ? error.message : "演练请求失败", "err"); }
    finally { setBusyAction(null); }
  };

  return (
    <div className="h-screen bg-[#131314] text-[#e3e3e3] flex flex-col overflow-hidden">
      {/* Top App Bar: Single-Row Human-Friendly Navigation */}
      <header className="app-header min-h-12 px-4 py-2 bg-[#1e1f20] border-b border-[#2d2e30] flex items-center justify-between gap-4 shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex items-center gap-2 shrink-0">
            <SlidersHorizontal className="w-4 h-4 text-[#a8c7fa]" />
            <span className="text-sm font-medium tracking-tight">企业工作台</span>
          </div>
          <span className="text-xs text-[#9aa0a6] hidden md:inline truncate">
            / {account.department} · {account.name}（{account.title}）
          </span>
        </div>

        {/* Center Stage Switcher */}
        <div className="flex items-center gap-1 bg-[#131314] p-0.5 rounded-lg border border-[#2d2e30] shrink-0">
          <button
            onClick={() => setStageView("stream")}
            className={`px-3 py-1 rounded-md text-xs transition flex items-center gap-1.5 ${stageView === "stream"
                ? "bg-[#282a2c] text-[#a8c7fa] font-medium border border-[#3c4043]"
                : "text-[#9aa0a6] hover:text-[#e3e3e3]"
              }`}
          >
            <MessageSquare className="w-3.5 h-3.5" />
            <span>工作对话</span>
            {pendingActionCount > 0 && (
              <span className="px-1.5 py-0.2 rounded-full bg-[#fdd663] text-[#131314] font-mono text-[10px] font-bold">
                {pendingActionCount}
              </span>
            )}
          </button>

          <button
            onClick={() => setStageView("capabilities")}
            className={`px-3 py-1 rounded-md text-xs transition flex items-center gap-1.5 ${stageView === "capabilities"
                ? "bg-[#282a2c] text-[#81c995] font-medium border border-[#3c4043]"
                : "text-[#9aa0a6] hover:text-[#e3e3e3]"
              }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>能力中心</span>
          </button>

          {isExecutive && <button
            onClick={() => setStageView("canvas")}
            className={`px-3 py-1 rounded-md text-xs transition flex items-center gap-1.5 ${stageView === "canvas"
                ? "bg-[#282a2c] text-[#a8c7fa] font-medium border border-[#3c4043]"
                : "text-[#9aa0a6] hover:text-[#e3e3e3]"
              }`}
          >
            <Network className="w-3.5 h-3.5" />
            <span>探索与织网</span>
          </button>}

          {isExecutive && (
            <button
              onClick={() => setStageView("governance")}
              className={`px-3 py-1 rounded-md text-xs transition flex items-center gap-1.5 ${stageView === "governance"
                  ? "bg-[#282a2c] text-[#a8c7fa] font-medium border border-[#3c4043]"
                  : "text-[#9aa0a6] hover:text-[#e3e3e3]"
                }`}
            >
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>经营后台</span>
            </button>
          )}
        </div>

        {/* Right: More Tools Dropdown + Refresh + Switch Account */}
        <div className="flex items-center gap-2 text-xs shrink-0">
          {isExecutive && <ClusterOperationsBar
            account={account}
            overview={overview}
            custody={custody}
            telemetry={telemetry}
            onRefresh={loadState}
            onSwitchAccount={handleSwitchAccount}
            onToast={showToast}
          />}
          <button
            onClick={() => loadState()}
            className="p-1.5 rounded hover:bg-[#282a2c] text-[#9aa0a6] hover:text-[#e3e3e3]"
            title="刷新工作台"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${wsConnected ? "" : "text-[#fdd663]"}`} />
          </button>
          <button
            onClick={handleLogout}
            className="px-2.5 py-1 rounded-md bg-[#282a2c] hover:bg-[#35373a] border border-[#3c4043] text-[#e3e3e3] flex items-center gap-1 text-[11px]"
          >
            <LogOut className="w-3 h-3 text-[#f28b82]" />
            <span>切换账号</span>
          </button>
        </div>
      </header>

      {toast && (
        <div
          className={`px-4 py-1 border-b text-xs flex items-center justify-between shrink-0 ${toast.kind === "ok"
              ? "bg-[#1e1f20] border-[#3c4043] text-[#a8c7fa]"
              : "bg-[#282a2c] border-[#f28b82]/40 text-[#f28b82]"
            }`}
        >
          <span className="font-mono">{toast.text}</span>
          <button onClick={() => setToast(null)} className="text-[#9aa0a6]">
            ✕
          </button>
        </div>
      )}

      {/* Main Body: Left Personal Capability Rail + Right Main Stage */}
      {isExecutive && <DaySimulationTimeline simStatus={simStatus} telemetry={telemetry} busyAction={busyAction} onStep={() => performSimulation("step")} onRunFullDay={() => performSimulation("run")} onResetDay={() => performSimulation("reset")} />}
      <div className="business-layout flex-1 flex min-h-0 overflow-hidden">
        <aside className="business-sidebar w-72 border-r border-[#2d2e30] bg-[#1e1f20] p-3 overflow-y-auto shrink-0 space-y-4">
          {/* Personal Workstation Card */}
          <div className="p-3 rounded-lg bg-[#131314] border border-[#2d2e30] space-y-1.5 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-medium text-[#e3e3e3]">{account.name}</span>
              <span
                className={`px-1.5 py-0.2 rounded text-[10px] ${account.is_custodian_leader
                    ? "bg-[#fdd663]/15 text-[#fdd663] border border-[#fdd663]/40"
                    : "bg-[#282a2c] text-[#a8c7fa]"
                  }`}
              >
                {account.is_custodian_leader ? "部门负责人" : "岗位成员"}
              </span>
            </div>
            <div className="text-[11px] text-[#9aa0a6]">
              {account.department} · {account.title}
            </div>
            {overview && (
              <div className="pt-1.5 border-t border-[#2d2e30] flex items-center justify-between text-[11px]">
                <span className="text-[#9aa0a6] truncate">{account.department}</span>
                <span className="text-[#81c995] font-mono shrink-0">
                  省时 {overview.current_user.employee_view.saved_hours}h · +
                  {overview.current_user.employee_view.innovation_bonus}分
                </span>
              </div>
            )}
          </div>

          {/* Left Rail Capability List */}
          <BallCustodyPanel
            custody={custody}
            onRefresh={loadState}
            onToast={showToast}
            onQuickUse={handleQuickUse}
          />
        </aside>

        <main className="flex-1 min-w-0 overflow-hidden bg-[#131314]">
          {loadError && <div role="alert" className="p-3 text-xs text-[#f28b82] border-b border-[#3c4043] flex flex-wrap gap-3"><span>{loadError}</span><button onClick={() => void loadState()} className="underline">重试加载</button></div>}
          {loading || !overview ? (
            <div className="h-full flex items-center justify-center text-[#9aa0a6] text-xs">
              {loadError ? "工作台暂不可用，请重试加载或切换账号。" : `正在加载 ${account.name} 的工作台…`}
            </div>
          ) : stageView === "stream" ? (
            <WeComSimulatorPane
              overview={overview}
              custody={custody}
              activeBot={activeBot}
              onSelectBot={setActiveBot}
              externalPrompt={pendingQuickPrompt}
              onSendChat={async (content, rawWechat, overrideBot) => {
                setBusyAction("chat");
                try {
                  await sendChatMessage({
                    sender_id: account.user_id,
                    role_view: account.role_view,
                    facade_bot: overrideBot ?? activeBot,
                    content,
                    raw_wechat_forward: rawWechat ?? [],
                  });
                  await loadState();
                } finally {
                  setBusyAction(null);
                }
              }}
              onSubmitCard={async (cardId, output) => {
                setBusyAction("card");
                try {
                  const res = await submitHumanToolCard({
                    actor_user_id: account.user_id,
                    card_id: cardId,
                    submitted_output: output,
                  });
                  await loadState();
                  return res;
                } finally {
                  setBusyAction(null);
                }
              }}
              onDecideResolution={async (resolutionId, approve) => {
                setBusyAction("decide");
                try {
                  await decideBoardTransition({ resolution_id: resolutionId, approve });
                  await loadState();
                } finally {
                  setBusyAction(null);
                }
              }}
              onDecideBallRequest={async (reqId, approve) => {
                setBusyAction("decide_ball");
                try {
                  await decideBallRequest(reqId, {
                    actor_user_id: account.user_id,
                    approve,
                  });
                  await loadState();
                  showToast(approve ? "已批准权限申请并开通" : "已驳回权限申请");
                } finally {
                  setBusyAction(null);
                }
              }}
            />
          ) : stageView === "capabilities" ? (
            <CapabilityCenterView
              account={account}
              onQuickUse={handleQuickUse}
              onRefreshAll={loadState}
              onToast={showToast}
            />
          ) : stageView === "canvas" ? (
            <div className="h-full p-2.5">
              <SpiderTopologyFlow
                nodesData={overview.topology_nodes ?? []}
                canControlDrills={canViewCanvas}
                busyAction={busyAction}
                onRefreshAll={loadState}
                onQuickUse={handleQuickUse}
                onToast={showToast}
                onDrill={async (mode) => {
                  setBusyAction(mode);
                  try {
                    await triggerSwarmDrill({ mode });
                    await loadState();
                  } finally {
                    setBusyAction(null);
                  }
                }}
              />
            </div>
          ) : (
            <div className="h-full p-3">
              <ExecutiveControlDeck
                overview={overview}
                actorUserId={account.user_id}
                busyAction={busyAction}
                onRefreshAll={loadState}
                onToast={showToast}
                onConveneBoard={async (agenda, targetSlotId, forceVeto) => {
                  setBusyAction("convene");
                  try {
                    await conveneBoard({
                      agenda,
                      target_slot_id: targetSlotId,
                      force_security_veto: forceVeto,
                    });
                    await loadState();
                  } finally {
                    setBusyAction(null);
                  }
                }}
                onDecideResolution={async (resolutionId, approve) => {
                  setBusyAction("decide");
                  try {
                    await decideBoardTransition({ resolution_id: resolutionId, approve });
                    await loadState();
                  } finally {
                    setBusyAction(null);
                  }
                }}
                onRollbackVault={async (scope, subtreeRootId, reason) => {
                  setBusyAction("rollback");
                  try {
                    await executeVaultRollback({
                      scope,
                      subtree_root_id: subtreeRootId,
                      reason: reason ?? "Manual snapshot rollback",
                    });
                    await loadState();
                  } finally {
                    setBusyAction(null);
                  }
                }}
              />
            </div>
          )}
        </main>
      </div>
    </div>
  );
};

export default App;

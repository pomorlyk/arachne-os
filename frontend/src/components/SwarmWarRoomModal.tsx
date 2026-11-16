import React, { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Code2,
  Cpu,
  Flame,
  Gavel,
  GitMerge,
  History,
  Loader2,
  Network,
  Scale,
  ShieldAlert,
  Sparkles,
  Swords,
  Terminal,
  X,
  Zap,
} from "lucide-react";
import {
  executeDagMission,
  fetchMissionPresets,
  fetchMissionsHistory,
  runAdversarialDebate,
} from "../api";
import {
  AccountDirectoryEntry,
  AdversarialDebateResponse,
  CustodyOverviewPayload,
  DagMissionExecutionResponse,
  MissionPresetItem,
  UnifiedOverviewPayload,
  UnitSlot,
} from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
  account: AccountDirectoryEntry;
  overview: UnifiedOverviewPayload | null;
  custody: CustodyOverviewPayload | null;
  onClusterMutated: () => Promise<void>;
  onToast: (text: string, kind?: "ok" | "err") => void;
}

type WarRoomTab = "dag_campaign" | "adversarial_debate";

const FALLBACK_MISSION_PRESETS: MissionPresetItem[] = [
  {
    preset_id: "preset_vip_lockprice",
    mission_title: "大客户跨国紧急锁价与90天账期特批会战",
    mission_brief:
      "华东核心KA客户（年采购额3800万）要求紧急锁定500吨特级阴极铜/精密耗材批次，申请在基准挂网价基础上额外折让14.5%，并将账期从标准30天延长至90天，且要求明日08:00前完成首车冷链/重卡发运。需销售工位、基层审批组长、财务风控工位与顶层管理工位联合推演定价毛利底线、现金流占用成本与红线合规性。",
    departments: ["一线业务部", "业务管理部", "财务风控部", "高管董事会"],
    complexity: "EXTREME · 4工位联合作战",
  },
  {
    preset_id: "preset_supply_shortage",
    mission_title: "供应链断供紧急跨仓调拨与违约金止损核算",
    mission_brief:
      "受极端天气与边境清关延误影响，主仓库存水位跌破安全红线（缺口180件），3家签约三甲医院/海外大客户面临48小时内断供违约（合同约定日违约金0.5%/天，上限15%）。需调度全国分仓余量、测算空派加急冷链运费 vs 延期违约金最优解，并完成跨区借货与财务紧急预付款核准。",
    departments: ["供应链调度部", "销售跟单部", "财务核算部", "合规审计部"],
    complexity: "HIGH · 跨仓调拨博弈",
  },
  {
    preset_id: "preset_annual_margin_defense",
    mission_title: "年度大促全渠道阶梯返利与净毛利保卫战",
    mission_brief:
      "Q4大促期间三大渠道代理商同时申报阶梯满返激励与达人坑位费补贴（累计申领金额达125万元），部分订单疑似通过拆单绕过单笔审批上限且叠加了特批折扣券。需联合核算真实净毛利率（严守≥18%集团红线）、穿透稽核拆单异常并制定分级兑付决议。",
    departments: ["渠道商务部", "财务开票与稽核部", "部门主管", "总办风控"],
    complexity: "EXTREME · 净毛利底线防御",
  },
  {
    preset_id: "preset_redline_compliance_purge",
    mission_title: "高危合规审计与越权承诺全链路清查行动",
    mission_brief:
      "内审哨兵捕获到外部客户企微群转发记录中疑似包含内部底价系数、非标返点口头承诺及未脱敏履约单号。需立即启动跨部门DAG联合清查：定位源头工位、评估合同法律敞口、冻结异常折扣审批单并生成WORM黑匣子整改决议。",
    departments: ["合规内审部", "一线业务部", "财务风控部", "顶层治理台"],
    complexity: "CRITICAL · 零容忍红线清查",
  },
];

const SAMPLE_DEBATE_TOPICS: string[] = [
  "针对战略级大客户申请「毛利率降至13.5%（低于18%红线）换取全年2000万保底锁量协议」，是否应当破例放行？",
  "当紧急订单面临断供违约风险时，是否允许一线班组长采取「先借调现货发运、48小时内后补财务与合规审批单」的应急通道？",
  "面对代理商要求将「季度阶梯返利直接抵扣当期货款并拆分3张发票开具」的诉求，业务增长与税务合规该如何裁决？",
];

const FALLBACK_SLOTS: UnitSlot[] = [
  {
    slot_id: "slot_sales_01",
    slot_name: "一线跟单与商务工位 (小陈)",
    department: "销售业务部",
    ball_ids: ["ball_data_catalog", "ball_skill_freight", "ball_redline_pii"],
    borrowed_balls: [],
    occupant_type: "HUMAN",
    occupant_id: "role_frontline_01",
  },
  {
    slot_id: "slot_leader_01",
    slot_name: "基层业务组长工位 (老李)",
    department: "销售管理部",
    ball_ids: ["ball_auth_discount", "ball_redline_margin"],
    borrowed_balls: [],
    occupant_type: "HYBRID_TRANSITION",
    occupant_id: "leader_li",
  },
  {
    slot_id: "slot_finance_01",
    slot_name: "财务风控与开票专员工位 (王姐)",
    department: "财务风控部",
    ball_ids: ["ball_redline_tax", "ball_skill_tax_audit"],
    borrowed_balls: [],
    occupant_type: "HUMAN",
    occupant_id: "fin_wang",
  },
  {
    slot_id: "slot_manager_01",
    slot_name: "部门运营中枢主管工位 (张经理)",
    department: "运营管理部",
    ball_ids: ["ball_auth_dispatch", "ball_skill_roi"],
    borrowed_balls: [],
    occupant_type: "HYBRID_TRANSITION",
    occupant_id: "mgr_zhang",
  },
  {
    slot_id: "slot_boss_01",
    slot_name: "顶层总办与董事会席位 (林总)",
    department: "总办董事会",
    ball_ids: ["ball_auth_board_veto", "ball_redline_charter"],
    borrowed_balls: [],
    occupant_type: "HUMAN",
    occupant_id: "boss_lin",
  },
];

function normalizeMissionPresets(raw: unknown): MissionPresetItem[] {
  const list = Array.isArray(raw)
    ? raw
    : raw &&
      typeof raw === "object" &&
      Array.isArray((raw as { presets?: unknown[] }).presets)
      ? (raw as { presets: unknown[] }).presets
      : [];

  const parsed: MissionPresetItem[] = [];
  list.forEach((item, idx) => {
    if (!item || typeof item !== "object") return;
    const obj = item as Record<string, unknown>;
    const mission_title = String(
      obj.mission_title ?? obj.title ?? obj.name ?? `跨部门战役预设 #${idx + 1}`
    );
    const mission_brief = String(
      obj.mission_brief ?? obj.brief ?? obj.description ?? ""
    );
    if (!mission_brief) return;
    parsed.push({
      preset_id: String(obj.preset_id ?? obj.id ?? `preset_${idx}`),
      mission_title,
      mission_brief,
      departments: Array.isArray(obj.departments)
        ? obj.departments.map(String)
        : Array.isArray(obj.involved_slots)
          ? obj.involved_slots.map(String)
          : undefined,
      complexity: obj.complexity ? String(obj.complexity) : undefined,
      tags: Array.isArray(obj.tags) ? obj.tags.map(String) : undefined,
    });
  });

  return parsed.length > 0 ? parsed : FALLBACK_MISSION_PRESETS;
}

export const SwarmWarRoomModal: React.FC<Props> = ({
  open,
  onClose,
  account,
  overview,
  onClusterMutated,
  onToast,
}) => {
  const [activeTab, setActiveTab] = useState<WarRoomTab>("dag_campaign");

  // Tab 1: Cross-Department DAG Campaign State
  const [presets, setPresets] = useState<MissionPresetItem[]>(
    FALLBACK_MISSION_PRESETS
  );
  const [loadingPresets, setLoadingPresets] = useState(false);
  const [missionTitle, setMissionTitle] = useState(
    FALLBACK_MISSION_PRESETS[0].mission_title
  );
  const [missionBrief, setMissionBrief] = useState(
    FALLBACK_MISSION_PRESETS[0].mission_brief
  );
  const [maxDebateRounds, setMaxDebateRounds] = useState<number>(2);
  const [autoExecuteSkills, setAutoExecuteSkills] = useState<boolean>(true);
  const [runningDag, setRunningDag] = useState(false);
  const [dagResult, setDagResult] = useState<DagMissionExecutionResponse | null>(
    null
  );

  // Tab 2: Dual-Slot Adversarial Debate State
  const availableSlots = useMemo<UnitSlot[]>(() => {
    const map = new Map<string, UnitSlot>();
    for (const s of overview?.all_slots ?? []) {
      map.set(s.slot_id, s);
    }
    if (overview?.my_slot && !map.has(overview.my_slot.slot_id)) {
      map.set(overview.my_slot.slot_id, overview.my_slot);
    }
    for (const fb of FALLBACK_SLOTS) {
      if (!map.has(fb.slot_id)) {
        map.set(fb.slot_id, fb);
      }
    }
    return Array.from(map.values());
  }, [overview]);

  const [debateTopic, setDebateTopic] = useState<string>(SAMPLE_DEBATE_TOPICS[0]);
  const [proposerSlotId, setProposerSlotId] = useState<string>("slot_sales_01");
  const [reviewerSlotId, setReviewerSlotId] = useState<string>("slot_finance_01");
  const [arbiterSlotId, setArbiterSlotId] = useState<string>("slot_boss_01");
  const [debateRoundsCount, setDebateRoundsCount] = useState<number>(3);
  const [runningDebate, setRunningDebate] = useState(false);
  const [debateResult, setDebateResult] =
    useState<AdversarialDebateResponse | null>(null);

  // History State
  const [missionHistoryCount, setMissionHistoryCount] = useState<number>(0);

  useEffect(() => {
    if (availableSlots.length > 0) {
      if (!availableSlots.some((s) => s.slot_id === proposerSlotId)) {
        setProposerSlotId(availableSlots[0].slot_id);
      }
      if (!availableSlots.some((s) => s.slot_id === reviewerSlotId)) {
        setReviewerSlotId(
          availableSlots[Math.min(2, availableSlots.length - 1)].slot_id
        );
      }
      if (!availableSlots.some((s) => s.slot_id === arbiterSlotId)) {
        setArbiterSlotId(
          availableSlots[availableSlots.length - 1].slot_id
        );
      }
    }
  }, [availableSlots, proposerSlotId, reviewerSlotId, arbiterSlotId]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadingPresets(true);
    fetchMissionPresets()
      .then((raw) => {
        if (cancelled) return;
        const normalized = normalizeMissionPresets(raw);
        setPresets(normalized);
      })
      .catch(() => {
        if (!cancelled) setPresets(FALLBACK_MISSION_PRESETS);
      })
      .finally(() => {
        if (!cancelled) setLoadingPresets(false);
      });

    fetchMissionsHistory()
      .then((hist) => {
        if (cancelled) return;
        if (Array.isArray(hist)) {
          setMissionHistoryCount(hist.length);
        } else if (hist && typeof hist === "object") {
          const mLen = Array.isArray(hist.missions) ? hist.missions.length : 0;
          const dLen = Array.isArray(hist.debates) ? hist.debates.length : 0;
          const hLen = Array.isArray(hist.history) ? hist.history.length : 0;
          setMissionHistoryCount(mLen + dLen + hLen);
        }
      })
      .catch(() => {
        // ignore
      });

    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  const handleExecuteDagMission = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!missionTitle.trim() || !missionBrief.trim() || runningDag) return;
    setRunningDag(true);
    try {
      const res = await executeDagMission({
        mission_title: missionTitle.trim(),
        mission_brief: missionBrief.trim(),
        initiator_account_id: account.user_id,
        max_debate_rounds: maxDebateRounds,
        auto_execute_skills: autoExecuteSkills,
      });
      setDagResult(res);
      setMissionHistoryCount((c) => c + 1);
      await onClusterMutated();
      onToast(
        `🕸️ 跨部门联合作战「${res.mission_title}」推演完成！状态：${res.status}`,
        res.status === "FAILED" || res.status.includes("BLOCK") ? "err" : "ok"
      );
    } catch (err: unknown) {
      onToast(
        err instanceof Error ? err.message : "跨部门 DAG 联合作战执行失败",
        "err"
      );
    } finally {
      setRunningDag(false);
    }
  };

  const handleRunAdversarialDebate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!debateTopic.trim() || runningDebate) return;
    setRunningDebate(true);
    try {
      const res = await runAdversarialDebate({
        topic: debateTopic.trim(),
        proposer_slot_id: proposerSlotId,
        reviewer_slot_id: reviewerSlotId,
        arbiter_slot_id: arbiterSlotId || null,
        rounds: debateRoundsCount,
      });
      setDebateResult(res);
      setMissionHistoryCount((c) => c + 1);
      await onClusterMutated();
      onToast(
        `⚔️ 双工位多轮对抗辩论完成！已完成 ${res.rounds?.length ?? debateRoundsCount} 轮交锋并生成高管终审裁决`,
        "ok"
      );
    } catch (err: unknown) {
      onToast(
        err instanceof Error ? err.message : "双工位对抗辩论执行失败",
        "err"
      );
    } finally {
      setRunningDebate(false);
    }
  };

  const dagStatusBadge = (status?: string) => {
    const s = (status || "UNKNOWN").toUpperCase();
    if (s.includes("BLOCK") || s.includes("REJECT") || s.includes("FAIL")) {
      return (
        <span className="px-2.5 py-1 rounded-full text-[11px] font-mono font-semibold bg-[#f28b82]/15 text-[#f28b82] border border-[#f28b82]/40 flex items-center gap-1">
          <ShieldAlert className="w-3.5 h-3.5" />
          <span>{s} (受阻 / 失败)</span>
        </span>
      );
    }
    if (s.includes("ESCALAT") || s.includes("CONDITIONAL") || s.includes("PENDING") || s === "UNKNOWN" || s === "PLAN_READY") {
      return (
        <span className="px-2.5 py-1 rounded-full text-[11px] font-mono font-semibold bg-[#fdd663]/15 text-[#fdd663] border border-[#fdd663]/40 flex items-center gap-1">
          <AlertTriangle className="w-3.5 h-3.5" />
          <span>{s} (计划 / 待后续动作)</span>
        </span>
      );
    }
    return (
      <span className="px-2.5 py-1 rounded-full text-[11px] font-mono font-semibold bg-[#81c995]/15 text-[#81c995] border border-[#81c995]/40 flex items-center gap-1">
        <CheckCircle2 className="w-3.5 h-3.5" />
        <span>{s} (后端返回状态)</span>
      </span>
    );
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-[#131314] border border-[#2d2e30] rounded-xl w-full max-w-6xl max-h-[92vh] flex flex-col shadow-2xl overflow-hidden text-xs text-[#e3e3e3]">
        {/* Top Header */}
        <div className="px-5 py-3.5 bg-[#18191b] border-b border-[#2d2e30] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#a8c7fa]/15 border border-[#a8c7fa]/40 flex items-center justify-center text-[#a8c7fa]">
              <Swords className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-[#e3e3e3]">
                  蜂群跨部门多 Agent 联合作战与博弈辩论室 (Swarm DAG War Room)
                </h2>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#a8c7fa]/15 text-[#a8c7fa] border border-[#a8c7fa]/30">
                  Pillar 1 · Multi-Agent DAG &amp; Debate v5.0
                </span>
              </div>
              <p className="text-[11px] text-[#9aa0a6] mt-0.5">
                驱动多个部门工位容器挂载真实 DATA / SKILL / AUTHORITY / REDLINE
                能力球展开拓扑推演、洁净室沙箱实算与多轮红线交锋辩论
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <div className="px-2.5 py-1 rounded bg-[#131314] border border-[#2d2e30] font-mono text-[11px] text-[#9aa0a6] flex items-center gap-1.5">
              <History className="w-3.5 h-3.5 text-[#a8c7fa]" />
              <span>历史会战归档: {missionHistoryCount} 场</span>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-[#282a2c] text-[#9aa0a6] hover:text-[#e3e3e3] transition"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Studio Mode Tabs */}
        <div className="px-5 py-2.5 bg-[#18191b]/60 border-b border-[#2d2e30] flex flex-wrap items-center justify-between gap-2 shrink-0">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setActiveTab("dag_campaign")}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-medium border transition flex items-center gap-2 ${activeTab === "dag_campaign"
                  ? "bg-[#a8c7fa] text-[#062e6f] border-[#a8c7fa] shadow-sm"
                  : "bg-[#1e1f20] hover:bg-[#282a2c] text-[#9aa0a6] border-[#3c4043]"
                }`}
            >
              <Network className="w-3.5 h-3.5" />
              <span>🕸️ 跨部门 DAG 联合作战会战</span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("adversarial_debate")}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-medium border transition flex items-center gap-2 ${activeTab === "adversarial_debate"
                  ? "bg-[#fdd663] text-[#131314] border-[#fdd663] shadow-sm"
                  : "bg-[#1e1f20] hover:bg-[#282a2c] text-[#9aa0a6] border-[#3c4043]"
                }`}
            >
              <Swords className="w-3.5 h-3.5" />
              <span>⚔️ 双工位针锋相对博弈辩论</span>
            </button>
          </div>

          <div className="text-[11px] text-[#9aa0a6] font-mono flex items-center gap-2">
            <span>当前发起人:</span>
            <span className="text-[#e3e3e3] font-semibold">
              {account.name} ({account.title} · {account.slot_id})
            </span>
          </div>
        </div>

        {/* Main Scrollable Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {activeTab === "dag_campaign" ? (
            <>
              {/* Preset Selector & Campaign Configuration Form */}
              <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-[#a8c7fa]" />
                    <span className="font-semibold text-[#e3e3e3]">
                      四大高复杂度跨部门企业战役预设
                      {loadingPresets ? " (正在同步预设...)" : ""}
                    </span>
                  </div>
                  <span className="text-[11px] text-[#9aa0a6]">
                    点击任意战役卡片一键装填跨部门任务简报
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2.5">
                  {presets.map((p, idx) => {
                    const isSelected = missionTitle === p.mission_title;
                    return (
                      <button
                        key={p.preset_id ?? idx}
                        type="button"
                        onClick={() => {
                          setMissionTitle(p.mission_title);
                          setMissionBrief(p.mission_brief);
                        }}
                        className={`p-3 rounded-lg border text-left transition flex flex-col justify-between gap-2 ${isSelected
                            ? "bg-[#a8c7fa]/15 border-[#a8c7fa] text-[#e3e3e3]"
                            : "bg-[#131314] hover:bg-[#1e1f20] border-[#2d2e30] text-[#9aa0a6]"
                          }`}
                      >
                        <div className="space-y-1">
                          <div className="flex items-center justify-between gap-1">
                            <span
                              className={`font-semibold text-xs line-clamp-1 ${isSelected ? "text-[#a8c7fa]" : "text-[#e3e3e3]"
                                }`}
                            >
                              {p.mission_title}
                            </span>
                          </div>
                          <p className="text-[11px] text-[#9aa0a6] line-clamp-2 leading-relaxed">
                            {p.mission_brief}
                          </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-1 pt-1 border-t border-[#2d2e30]/60">
                          {p.complexity && (
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-[#282a2c] text-[#fdd663]">
                              {p.complexity}
                            </span>
                          )}
                          {(p.departments ?? []).slice(0, 2).map((d) => (
                            <span
                              key={d}
                              className="px-1.5 py-0.5 rounded text-[10px] bg-[#1e1f20] text-[#9aa0a6]"
                            >
                              {d}
                            </span>
                          ))}
                        </div>
                      </button>
                    );
                  })}
                </div>

                <form onSubmit={handleExecuteDagMission} className="space-y-3 pt-1">
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                    <div className="space-y-1">
                      <label className="text-[11px] text-[#9aa0a6] block">
                        战役代号 / 标题 (Mission Title)
                      </label>
                      <input
                        required
                        value={missionTitle}
                        onChange={(e) => setMissionTitle(e.target.value)}
                        placeholder="输入跨部门联合作战标题..."
                        className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                      />
                    </div>
                    <div className="md:col-span-3 space-y-1">
                      <label className="text-[11px] text-[#9aa0a6] block">
                        跨部门联合作战简报与博弈边界条件 (Mission Brief)
                      </label>
                      <textarea
                        required
                        rows={2}
                        value={missionBrief}
                        onChange={(e) => setMissionBrief(e.target.value)}
                        placeholder="详细描述涉及的客户诉求、价格/账期冲突、库存调拨约束或红线审计场景..."
                        className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                      />
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                    <div className="flex flex-wrap items-center gap-4">
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] text-[#9aa0a6]">
                          跨部门红线博弈辩论轮数:
                        </span>
                        <div className="flex items-center gap-1">
                          {[1, 2, 3, 4].map((r) => (
                            <button
                              key={r}
                              type="button"
                              onClick={() => setMaxDebateRounds(r)}
                              className={`w-7 h-7 rounded-md font-mono text-xs border transition ${maxDebateRounds === r
                                  ? "bg-[#a8c7fa] text-[#062e6f] border-[#a8c7fa] font-bold"
                                  : "bg-[#131314] text-[#9aa0a6] border-[#3c4043] hover:text-[#e3e3e3]"
                                }`}
                            >
                              {r}
                            </button>
                          ))}
                        </div>
                      </div>

                      <label className="flex items-center gap-2 text-[11px] text-[#e3e3e3] cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={autoExecuteSkills}
                          onChange={(e) =>
                            setAutoExecuteSkills(e.target.checked)
                          }
                          className="rounded border-[#3c4043] bg-[#131314] text-[#81c995]"
                        />
                        <span>
                          自动触发参战工位的 Python 洁净室技能球 (`SKILL`) 进行实弹精确验算
                        </span>
                      </label>
                    </div>

                    <button
                      type="submit"
                      disabled={
                        runningDag ||
                        !missionTitle.trim() ||
                        !missionBrief.trim()
                      }
                      className="px-5 py-2 rounded-lg bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] font-semibold text-xs flex items-center gap-2 disabled:opacity-40 transition shadow-md"
                    >
                      {runningDag ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin" />
                          <span>
                            正在调度多工位 Agent 拓扑推演、沙箱实算与多轮辩论...
                          </span>
                        </>
                      ) : (
                        <>
                          <Zap className="w-4 h-4" />
                          <span>⚡ 启动多工位 Agent 联合作战</span>
                        </>
                      )}
                    </button>
                  </div>
                </form>
              </div>

              {/* Loading Skeleton when running DAG */}
              {runningDag && (
                <div className="p-8 rounded-xl bg-[#18191b] border border-[#a8c7fa]/40 flex flex-col items-center justify-center gap-3 text-center">
                  <Loader2 className="w-7 h-7 text-[#a8c7fa] animate-spin" />
                  <div className="text-sm font-medium text-[#e3e3e3]">
                    正在并行唤醒跨部门工位 Agent 容器与洁净室沙箱...
                  </div>
                  <p className="text-[11px] text-[#9aa0a6] max-w-xl">
                    正在依次执行：① 参战部门工位能力球挂载与深度推演 → ② Python
                    `python -I` 技能球0误差实算 → ③ {maxDebateRounds}{" "}
                    轮业务提案 vs 财务/合规红线博弈辩论 → ④ 合成最终联合决议书
                  </p>
                </div>
              )}

              {/* DAG Campaign Execution Results */}
              {dagResult && (
                <div className="space-y-4">
                  {/* 1. Token Burn & Reasoning Telemetry Bar */}
                  <div className="p-3.5 rounded-xl bg-[#18191b] border border-[#2d2e30] flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      {dagStatusBadge(dagResult.status)}
                      <div>
                        <div className="text-xs font-semibold text-[#e3e3e3]">
                          {dagResult.mission_title}
                        </div>
                        <div className="text-[10px] font-mono text-[#9aa0a6]">
                          Mission ID: {dagResult.mission_id}
                        </div>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-3 font-mono text-[11px]">
                      <div className="px-2.5 py-1 rounded-md bg-[#131314] border border-[#2d2e30] flex items-center gap-1.5">
                        <Flame className="w-3.5 h-3.5 text-[#fdd663]" />
                        <span className="text-[#9aa0a6]">LLM 深度调用:</span>
                        <strong className="text-[#fdd663]">
                          {dagResult.token_telemetry?.llm_calls ?? 0} 次
                        </strong>
                      </div>
                      <div className="px-2.5 py-1 rounded-md bg-[#131314] border border-[#2d2e30] flex items-center gap-1.5">
                        <Cpu className="w-3.5 h-3.5 text-[#a8c7fa]" />
                        <span className="text-[#9aa0a6]">Token 燃烧估算:</span>
                        <strong className="text-[#a8c7fa]">
                          {(
                            dagResult.token_telemetry?.estimated_tokens ?? 0
                          ).toLocaleString()}{" "}
                          toks
                        </strong>
                      </div>
                      <div className="px-2.5 py-1 rounded-md bg-[#131314] border border-[#2d2e30] flex items-center gap-1.5">
                        <Clock className="w-3.5 h-3.5 text-[#81c995]" />
                        <span className="text-[#9aa0a6]">总推理耗时:</span>
                        <strong className="text-[#81c995]">
                          {Math.round(
                            dagResult.token_telemetry?.total_latency_ms ?? 0
                          )}{" "}
                          ms
                        </strong>
                      </div>
                      <div className="px-2.5 py-1 rounded-md bg-[#131314] border border-[#2d2e30] text-[#e3e3e3]">
                        Mode:{" "}
                        <span className="text-[#81c995]">
                          {dagResult.token_telemetry?.mode ??
                            "LIVE_MULTI_AGENT_DAG"}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="p-3 rounded border border-[#3c4043] text-xs text-[#fdd663]">工具执行成功 {(dagResult.skill_executions ?? []).filter(item => item.executed_ok === true).length} · 失败 {(dagResult.skill_executions ?? []).filter(item => item.executed_ok === false).length} · 未确认 {(dagResult.skill_executions ?? []).filter(item => item.executed_ok === undefined).length}。当前记录是计划与工具验算，业务交付须以授权工作流的回执为准。</div>
                  {/* 2. DAG Node Topology Execution Stream */}
                  <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <GitMerge className="w-4 h-4 text-[#a8c7fa]" />
                        <span className="font-semibold text-[#e3e3e3]">
                          DAG 节点拓扑执行流 (参战部门工位 · 挂载能力球 · 深度推演结论)
                        </span>
                      </div>
                      <span className="font-mono text-[11px] text-[#9aa0a6]">
                        共 {dagResult.dag_nodes?.length ?? 0} 个参战工位节点
                      </span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {(dagResult.dag_nodes ?? []).map((node, idx) => {
                        const balls =
                          node.mounted_balls ??
                          node.used_balls ??
                          node.ball_ids ??
                          [];
                        const conclusionText =
                          node.conclusion ??
                          node.reasoning ??
                          node.proposal ??
                          (typeof node.output === "string"
                            ? node.output
                            : JSON.stringify(node.output ?? ""));
                        return (
                          <div
                            key={node.node_id ?? idx}
                            className="p-3.5 rounded-lg bg-[#131314] border border-[#2d2e30] space-y-2 flex flex-col justify-between"
                          >
                            <div className="space-y-2">
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex items-center gap-2">
                                  <span className="w-5 h-5 rounded-full bg-[#a8c7fa]/20 border border-[#a8c7fa] text-[#a8c7fa] font-mono text-[10px] font-bold flex items-center justify-center">
                                    {node.step_index ?? idx + 1}
                                  </span>
                                  <div>
                                    <div className="font-semibold text-[#e3e3e3] text-xs">
                                      {node.slot_name ??
                                        node.slot_id ??
                                        `参战工位 #${idx + 1}`}
                                    </div>
                                    <div className="text-[10px] text-[#9aa0a6] font-mono">
                                      {node.department ?? "核心业务域"} ·{" "}
                                      {node.slot_id ?? node.node_id}
                                    </div>
                                  </div>
                                </div>
                                <span className="text-[10px] text-[#fdd663]">{node.status ?? "状态未提供"}</span>
                                {node.stance && (
                                  <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#282a2c] text-[#fdd663] border border-[#3c4043]">
                                    {node.stance}
                                  </span>
                                )}
                              </div>

                              {/* Mounted Capability Balls */}
                              {Array.isArray(balls) && balls.length > 0 && (
                                <div className="flex flex-wrap gap-1">
                                  {balls.map((b, bIdx) => {
                                    const label =
                                      typeof b === "string"
                                        ? b
                                        : String(
                                          (b as Record<string, unknown>)
                                            .title ??
                                          (b as Record<string, unknown>)
                                            .ball_id ??
                                          JSON.stringify(b)
                                        );
                                    const bType =
                                      typeof b === "object" && b !== null
                                        ? String(
                                          (b as Record<string, unknown>)
                                            .ball_type ?? ""
                                        )
                                        : "";
                                    return (
                                      <span
                                        key={bIdx}
                                        className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#1e1f20] text-[#a8c7fa] border border-[#2d2e30]"
                                      >
                                        {bType ? `[${bType}] ` : "🔮 "}
                                        {label}
                                      </span>
                                    );
                                  })}
                                </div>
                              )}

                              <div className="text-[11px] text-[#e3e3e3] leading-relaxed bg-[#18191b] p-2.5 rounded border border-[#2d2e30]/80 whitespace-pre-wrap">
                                {conclusionText}
                              </div>
                            </div>

                            {Array.isArray(node.risk_flags) &&
                              node.risk_flags.length > 0 && (
                                <div className="flex flex-wrap gap-1 pt-1">
                                  {node.risk_flags.map((rf, rIdx) => (
                                    <span
                                      key={rIdx}
                                      className="px-1.5 py-0.5 rounded text-[10px] bg-[#f28b82]/15 text-[#f28b82] border border-[#f28b82]/30"
                                    >
                                      ⚠️ {rf}
                                    </span>
                                  ))}
                                </div>
                              )}
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* 3. Cleanroom Python Skill Live Execution Panel */}
                  {Array.isArray(dagResult.skill_executions) &&
                    dagResult.skill_executions.length > 0 && (
                      <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Terminal className="w-4 h-4 text-[#81c995]" />
                            <span className="font-semibold text-[#e3e3e3]">
                              洁净室 Python 技能实弹输出面板 (Cleanroom `SKILL`
                              0-Token 精确计算)
                            </span>
                          </div>
                          <span className="font-mono text-[11px] text-[#81c995]">
                            已实弹触发 {dagResult.skill_executions.length} 颗
                            SKILL 球
                          </span>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          {dagResult.skill_executions.map((sk, idx) => {
                            const inputObj =
                              sk.input_payload ?? sk.inputs ?? {};
                            const outputObj =
                              sk.output_payload ?? sk.output ?? sk.result ?? {};
                            const ok = sk.executed_ok === true;
                            return (
                              <div
                                key={sk.ball_id ?? idx}
                                className="p-3 rounded-lg bg-[#131314] border border-[#2d2e30] space-y-2 font-mono text-[11px]"
                              >
                                <div className="flex items-center justify-between">
                                  <span className="font-semibold text-[#81c995] flex items-center gap-1.5">
                                    <Code2 className="w-3.5 h-3.5" />
                                    <span>
                                      {sk.ball_title ??
                                        sk.skill_name ??
                                        sk.ball_id ??
                                        `SKILL #${idx + 1}`}
                                    </span>
                                  </span>
                                  <span
                                    className={`px-2 py-0.5 rounded text-[10px] ${ok
                                        ? "bg-[#81c995]/15 text-[#81c995]"
                                        : "bg-[#f28b82]/15 text-[#f28b82]"
                                      }`}
                                  >
                                    {ok ? "SANDBOX_OK" : sk.status ?? "FAILED / PENDING"}
                                    {sk.latency_ms
                                      ? ` · ${Math.round(sk.latency_ms)}ms`
                                      : ""}
                                  </span>
                                </div>
                                <div className="grid grid-cols-1 gap-1.5">
                                  <div className="p-2 rounded bg-[#18191b] border border-[#2d2e30]">
                                    <div className="text-[10px] text-[#9aa0a6] mb-0.5">
                                      输入参数 (Input Payload):
                                    </div>
                                    <pre className="text-[10px] text-[#a8c7fa] overflow-x-auto whitespace-pre-wrap">
                                      {JSON.stringify(inputObj, null, 2)}
                                    </pre>
                                  </div>
                                  <div className="p-2 rounded bg-[#18191b] border border-[#2d2e30]">
                                    <div className="text-[10px] text-[#9aa0a6] mb-0.5">
                                      沙箱实算返回 (Exact Output JSON):
                                    </div>
                                    <pre className="text-[10px] text-[#81c995] overflow-x-auto whitespace-pre-wrap">
                                      {JSON.stringify(outputObj, null, 2)}
                                    </pre>
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                  {/* 4. Multi-Round Cross-Department Redline Debate Transcript */}
                  {Array.isArray(dagResult.debate_transcript) &&
                    dagResult.debate_transcript.length > 0 && (
                      <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Swords className="w-4 h-4 text-[#fdd663]" />
                            <span className="font-semibold text-[#e3e3e3]">
                              多轮跨部门红线博弈辩论实录 (`debate_transcript`)
                            </span>
                          </div>
                          <span className="font-mono text-[11px] text-[#9aa0a6]">
                            业务方提案 vs 财务/审计红线反驳 vs 折中合成
                          </span>
                        </div>

                        <div className="space-y-3">
                          {dagResult.debate_transcript.map((turn, idx) => {
                            const roundNum =
                              turn.round ?? turn.round_index ?? idx + 1;
                            const hasStructuredColumns = Boolean(
                              turn.proposer_argument ||
                              turn.proposal ||
                              turn.reviewer_rebuttal ||
                              turn.rebuttal ||
                              turn.synthesis ||
                              turn.compromise
                            );

                            if (hasStructuredColumns) {
                              return (
                                <div
                                  key={idx}
                                  className="p-3.5 rounded-lg bg-[#131314] border border-[#2d2e30] space-y-2.5"
                                >
                                  <div className="flex items-center justify-between border-b border-[#2d2e30] pb-2">
                                    <span className="font-mono font-semibold text-[#fdd663] text-xs">
                                      Round #{roundNum} · 跨部门红线交锋回合
                                    </span>
                                    {Array.isArray(turn.cited_balls) &&
                                      turn.cited_balls.length > 0 && (
                                        <div className="flex flex-wrap gap-1">
                                          {turn.cited_balls.map((cb, cIdx) => (
                                            <span
                                              key={cIdx}
                                              className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#1e1f20] text-[#a8c7fa]"
                                            >
                                              引用球: {cb}
                                            </span>
                                          ))}
                                        </div>
                                      )}
                                  </div>

                                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
                                    <div className="p-2.5 rounded bg-[#18191b] border border-[#a8c7fa]/30 space-y-1">
                                      <div className="text-[10px] font-semibold text-[#a8c7fa]">
                                        🟦 业务方提案 (
                                        {turn.proposer_name ??
                                          turn.proposer_slot_id ??
                                          "业务提案席"}
                                        )
                                      </div>
                                      <div className="text-[11px] text-[#e3e3e3] leading-relaxed whitespace-pre-wrap">
                                        {turn.proposer_argument ??
                                          turn.proposal ??
                                          "—"}
                                      </div>
                                    </div>

                                    <div className="p-2.5 rounded bg-[#18191b] border border-[#f28b82]/30 space-y-1">
                                      <div className="text-[10px] font-semibold text-[#f28b82]">
                                        🟥 财务/审计红线反驳 (
                                        {turn.reviewer_name ??
                                          turn.reviewer_slot_id ??
                                          "风控审核席"}
                                        )
                                      </div>
                                      <div className="text-[11px] text-[#e3e3e3] leading-relaxed whitespace-pre-wrap">
                                        {turn.reviewer_rebuttal ??
                                          turn.rebuttal ??
                                          "—"}
                                      </div>
                                    </div>

                                    <div className="p-2.5 rounded bg-[#18191b] border border-[#81c995]/30 space-y-1">
                                      <div className="text-[10px] font-semibold text-[#81c995]">
                                        🟩 本轮折中合成与修正 (Synthesis)
                                      </div>
                                      <div className="text-[11px] text-[#e3e3e3] leading-relaxed whitespace-pre-wrap">
                                        {turn.synthesis ??
                                          turn.compromise ??
                                          turn.resolution_delta ??
                                          "继续下一轮博弈校准"}
                                      </div>
                                    </div>
                                  </div>
                                </div>
                              );
                            }

                            // Fallback for flat speaker turn format
                            return (
                              <div
                                key={idx}
                                className="p-3 rounded-lg bg-[#131314] border border-[#2d2e30] space-y-1"
                              >
                                <div className="flex items-center justify-between">
                                  <span className="font-semibold text-[#a8c7fa]">
                                    [Round #{roundNum}]{" "}
                                    {String(
                                      turn.speaker ??
                                      turn.department ??
                                      turn.proposer_slot_id ??
                                      `发言席 #${idx + 1}`
                                    )}
                                  </span>
                                  {turn.stance && (
                                    <span className="font-mono text-[10px] text-[#fdd663]">
                                      {turn.stance}
                                    </span>
                                  )}
                                </div>
                                <div className="text-[11px] text-[#e3e3e3] leading-relaxed whitespace-pre-wrap">
                                  {turn.content ?? JSON.stringify(turn)}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                  {/* 5. Final Consensus Resolution */}
                  {dagResult.consensus_resolution && (
                    <div className="p-4 rounded-xl bg-gradient-to-r from-[#18191b] to-[#1e2229] border border-[#81c995]/50 space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Gavel className="w-4 h-4 text-[#81c995]" />
                          <span className="font-semibold text-sm text-[#81c995]">
                            最终跨部门联合决议书 (`consensus_resolution`)
                          </span>
                        </div>
                        {dagResult.consensus_resolution.redline_compliance && (
                          <span className="px-2.5 py-0.5 rounded text-[10px] font-mono bg-[#81c995]/15 text-[#81c995] border border-[#81c995]/30">
                            红线合规状态:{" "}
                            {dagResult.consensus_resolution.redline_compliance}
                          </span>
                        )}
                      </div>

                      <div className="text-xs text-[#e3e3e3] leading-relaxed bg-[#131314] p-3.5 rounded-lg border border-[#2d2e30] whitespace-pre-wrap">
                        {dagResult.consensus_resolution.summary ??
                          dagResult.consensus_resolution.decision ??
                          dagResult.consensus_resolution.final_plan ??
                          dagResult.consensus_resolution.verdict ??
                          JSON.stringify(
                            dagResult.consensus_resolution,
                            null,
                            2
                          )}
                      </div>

                      {Array.isArray(
                        dagResult.consensus_resolution.action_items
                      ) &&
                        dagResult.consensus_resolution.action_items.length >
                        0 && (
                          <div className="space-y-1.5">
                            <div className="text-[11px] font-medium text-[#a8c7fa]">
                              跨部门强制执行动作清单 (Action Items):
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                              {dagResult.consensus_resolution.action_items.map(
                                (item, idx) => (
                                  <div
                                    key={idx}
                                    className="p-2 rounded bg-[#131314] border border-[#2d2e30] text-[11px] text-[#e3e3e3] flex items-start gap-2"
                                  >
                                    <CheckCircle2 className="w-3.5 h-3.5 text-[#81c995] shrink-0 mt-0.5" />
                                    <span>
                                      {typeof item === "string"
                                        ? item
                                        : JSON.stringify(item)}
                                    </span>
                                  </div>
                                )
                              )}
                            </div>
                          </div>
                        )}
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            /* Tab 2: Dual-Slot Head-to-Head Adversarial Debate */
            <div className="space-y-4">
              <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Scale className="w-4 h-4 text-[#fdd663]" />
                    <span className="font-semibold text-[#e3e3e3]">
                      双工位针锋相对博弈辩论配置台 (Proposer vs Reviewer +
                      Executive Arbiter)
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[11px] text-[#9aa0a6]">
                      典型冲突辩题一键装填:
                    </span>
                    {SAMPLE_DEBATE_TOPICS.map((t, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => setDebateTopic(t)}
                        className="px-2 py-0.5 rounded bg-[#131314] hover:bg-[#282a2c] border border-[#3c4043] text-[10px] text-[#fdd663]"
                      >
                        辩题 #{idx + 1}
                      </button>
                    ))}
                  </div>
                </div>

                <form
                  onSubmit={handleRunAdversarialDebate}
                  className="space-y-3"
                >
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div className="space-y-1">
                      <label className="text-[11px] text-[#a8c7fa] font-medium block">
                        🟦 正方提案工位 (Proposer Slot)
                      </label>
                      <select
                        value={proposerSlotId}
                        onChange={(e) => setProposerSlotId(e.target.value)}
                        className="w-full bg-[#131314] border border-[#a8c7fa]/50 rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                      >
                        {availableSlots.map((s) => (
                          <option key={s.slot_id} value={s.slot_id}>
                            {s.slot_name} ({s.department} · {s.slot_id})
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="space-y-1">
                      <label className="text-[11px] text-[#f28b82] font-medium block">
                        🟥 反方审核工位 (Reviewer / Redline Slot)
                      </label>
                      <select
                        value={reviewerSlotId}
                        onChange={(e) => setReviewerSlotId(e.target.value)}
                        className="w-full bg-[#131314] border border-[#f28b82]/50 rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                      >
                        {availableSlots.map((s) => (
                          <option key={s.slot_id} value={s.slot_id}>
                            {s.slot_name} ({s.department} · {s.slot_id})
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="space-y-1">
                      <label className="text-[11px] text-[#81c995] font-medium block">
                        ⚖️ 裁决高管工位 (Arbiter Slot)
                      </label>
                      <select
                        value={arbiterSlotId}
                        onChange={(e) => setArbiterSlotId(e.target.value)}
                        className="w-full bg-[#131314] border border-[#81c995]/50 rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                      >
                        {availableSlots.map((s) => (
                          <option key={s.slot_id} value={s.slot_id}>
                            {s.slot_name} ({s.department} · {s.slot_id})
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="space-y-1">
                    <label className="text-[11px] text-[#9aa0a6] block">
                      对抗辩题与利益冲突焦点 (Adversarial Debate Topic)
                    </label>
                    <textarea
                      required
                      rows={2}
                      value={debateTopic}
                      onChange={(e) => setDebateTopic(e.target.value)}
                      placeholder="输入正反双方需要援引各自工位能力球展开交锋的具体业务议题..."
                      className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#fdd663] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                    />
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] text-[#9aa0a6]">
                        对抗交锋轮数 (Rounds):
                      </span>
                      {[1, 2, 3, 4].map((r) => (
                        <button
                          key={r}
                          type="button"
                          onClick={() => setDebateRoundsCount(r)}
                          className={`w-7 h-7 rounded-md font-mono text-xs border transition ${debateRoundsCount === r
                              ? "bg-[#fdd663] text-[#131314] border-[#fdd663] font-bold"
                              : "bg-[#131314] text-[#9aa0a6] border-[#3c4043]"
                            }`}
                        >
                          {r}
                        </button>
                      ))}
                    </div>

                    <button
                      type="submit"
                      disabled={runningDebate || !debateTopic.trim()}
                      className="px-5 py-2 rounded-lg bg-[#fdd663] hover:bg-[#fde082] text-[#131314] font-semibold text-xs flex items-center gap-2 disabled:opacity-40 transition shadow-md"
                    >
                      {runningDebate ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin" />
                          <span>
                            正反工位 Agent 正在援引球体条款进行多轮交锋...
                          </span>
                        </>
                      ) : (
                        <>
                          <Swords className="w-4 h-4" />
                          <span>⚔️ 启动双工位多轮对抗辩论</span>
                        </>
                      )}
                    </button>
                  </div>
                </form>
              </div>

              {runningDebate && (
                <div className="p-8 rounded-xl bg-[#18191b] border border-[#fdd663]/40 flex flex-col items-center justify-center gap-3 text-center">
                  <Loader2 className="w-7 h-7 text-[#fdd663] animate-spin" />
                  <div className="text-sm font-medium text-[#e3e3e3]">
                    正方工位 ({proposerSlotId}) 与 反方工位 ({reviewerSlotId})
                    正在激辩...
                  </div>
                  <p className="text-[11px] text-[#9aa0a6]">
                    双方正在检索各自挂载的 DATA / AUTHORITY / REDLINE
                    球体条款进行针锋相对质证，随后由 {arbiterSlotId} 出具终审裁决
                  </p>
                </div>
              )}

              {debateResult && (
                <div className="space-y-4">
                  {/* Telemetry Bar */}
                  <div className="p-3 rounded-xl bg-[#18191b] border border-[#2d2e30] flex flex-wrap items-center justify-between gap-2 font-mono text-[11px]">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded bg-[#fdd663]/15 text-[#fdd663] border border-[#fdd663]/30">
                        DEBATE #{debateResult.debate_id}
                      </span>
                      <span className="text-[#e3e3e3] font-sans font-medium">
                        {debateResult.topic}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-[#9aa0a6]">
                      <span>
                        LLM Calls:{" "}
                        <strong className="text-[#fdd663]">
                          {debateResult.token_telemetry?.llm_calls ?? 0}
                        </strong>
                      </span>
                      <span>·</span>
                      <span>
                        Tokens:{" "}
                        <strong className="text-[#a8c7fa]">
                          {(
                            debateResult.token_telemetry?.estimated_tokens ?? 0
                          ).toLocaleString()}
                        </strong>
                      </span>
                      <span>·</span>
                      <span>
                        Latency:{" "}
                        <strong className="text-[#81c995]">
                          {Math.round(
                            debateResult.token_telemetry?.total_latency_ms ?? 0
                          )}
                          ms
                        </strong>
                      </span>
                    </div>
                  </div>

                  {/* Rounds List */}
                  <div className="space-y-3">
                    {(debateResult.rounds ?? []).map((rd, idx) => {
                      const rNum = rd.round ?? rd.round_number ?? idx + 1;
                      const propCitations =
                        rd.proposer_citations ?? rd.cited_balls ?? [];
                      const revCitations = rd.reviewer_citations ?? [];
                      return (
                        <div
                          key={idx}
                          className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3"
                        >
                          <div className="flex items-center justify-between border-b border-[#2d2e30] pb-2">
                            <span className="font-mono font-bold text-[#fdd663] text-xs">
                              ⚔️ 第 {rNum} 轮针锋相对质证 (Round {rNum})
                            </span>
                            {rd.clash_point && (
                              <span className="text-[11px] text-[#9aa0a6]">
                                交锋焦点:{" "}
                                <strong className="text-[#e3e3e3]">
                                  {rd.clash_point}
                                </strong>
                              </span>
                            )}
                          </div>

                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            {/* Proposer Card */}
                            <div className="p-3 rounded-lg bg-[#131314] border border-[#a8c7fa]/40 space-y-2">
                              <div className="flex items-center justify-between">
                                <span className="font-semibold text-[#a8c7fa] text-xs">
                                  🟦 正方提案席 (
                                  {rd.proposer_name ??
                                    rd.proposer_slot_id ??
                                    proposerSlotId}
                                  )
                                </span>
                              </div>
                              <div className="text-[11px] text-[#e3e3e3] leading-relaxed whitespace-pre-wrap">
                                {rd.proposer_statement ??
                                  rd.proposer_argument ??
                                  "—"}
                              </div>
                              {Array.isArray(propCitations) &&
                                propCitations.length > 0 && (
                                  <div className="flex flex-wrap gap-1 pt-1">
                                    {propCitations.map((c, cIdx) => (
                                      <span
                                        key={cIdx}
                                        className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#a8c7fa]/15 text-[#a8c7fa]"
                                      >
                                        📜 引用条款: {c}
                                      </span>
                                    ))}
                                  </div>
                                )}
                            </div>

                            {/* Reviewer Card */}
                            <div className="p-3 rounded-lg bg-[#131314] border border-[#f28b82]/40 space-y-2">
                              <div className="flex items-center justify-between">
                                <span className="font-semibold text-[#f28b82] text-xs">
                                  🟥 反方红线审核席 (
                                  {rd.reviewer_name ??
                                    rd.reviewer_slot_id ??
                                    reviewerSlotId}
                                  )
                                </span>
                              </div>
                              <div className="text-[11px] text-[#e3e3e3] leading-relaxed whitespace-pre-wrap">
                                {rd.reviewer_statement ??
                                  rd.reviewer_rebuttal ??
                                  "—"}
                              </div>
                              {Array.isArray(revCitations) &&
                                revCitations.length > 0 && (
                                  <div className="flex flex-wrap gap-1 pt-1">
                                    {revCitations.map((c, cIdx) => (
                                      <span
                                        key={cIdx}
                                        className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#f28b82]/15 text-[#f28b82]"
                                      >
                                        🛡️ 引用红线: {c}
                                      </span>
                                    ))}
                                  </div>
                                )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Arbiter Final Verdict */}
                  {debateResult.final_verdict && (
                    <div className="p-4 rounded-xl bg-gradient-to-r from-[#18191b] to-[#1f241d] border border-[#81c995]/60 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Gavel className="w-4 h-4 text-[#81c995]" />
                          <span className="font-semibold text-sm text-[#81c995]">
                            ⚖️ 裁决高管终审判决书 (
                            {debateResult.final_verdict.arbiter_name ??
                              debateResult.final_verdict.arbiter_slot_id ??
                              arbiterSlotId}
                            )
                          </span>
                        </div>
                        {debateResult.final_verdict.winner && (
                          <span className="px-2.5 py-0.5 rounded text-[10px] font-mono bg-[#81c995]/20 text-[#81c995] border border-[#81c995]/40">
                            裁决倾向: {debateResult.final_verdict.winner}
                          </span>
                        )}
                      </div>

                      <div className="text-xs text-[#e3e3e3] leading-relaxed bg-[#131314] p-3.5 rounded-lg border border-[#2d2e30] whitespace-pre-wrap">
                        {debateResult.final_verdict.verdict ??
                          debateResult.final_verdict.ruling ??
                          debateResult.final_verdict.decision ??
                          debateResult.final_verdict.summary ??
                          debateResult.final_verdict.rationale ??
                          JSON.stringify(debateResult.final_verdict, null, 2)}
                      </div>

                      {Array.isArray(
                        debateResult.final_verdict.binding_conditions ??
                        debateResult.final_verdict.conditions
                      ) && (
                          <div className="flex flex-wrap gap-1.5 pt-1">
                            {(
                              debateResult.final_verdict.binding_conditions ??
                              debateResult.final_verdict.conditions ??
                              []
                            ).map((cond, idx) => (
                              <span
                                key={idx}
                                className="px-2.5 py-1 rounded bg-[#131314] border border-[#81c995]/30 text-[11px] text-[#81c995]"
                              >
                                ✓ 约束条件 #{idx + 1}: {cond}
                              </span>
                            ))}
                          </div>
                        )}
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

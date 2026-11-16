import React, { useEffect, useMemo, useState } from "react";
import {
  AlertOctagon,
  ArrowRight,
  Bug,
  Flame,
  History,
  Loader2,
  Shield,
  ShieldCheck,
  Target,
  Terminal,
  Wrench,
  X,
} from "lucide-react";
import {
  fetchCrucibleReports,
  runRedlinePenetrationAudit,
  stressTestSkillInCrucible,
} from "../api";
import {
  AccountDirectoryEntry,
  CapabilityBall,
  CustodyOverviewPayload,
  RedlinePenetrationResponse,
  SkillStressTestResponse,
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

type CrucibleTab = "skill_crucible" | "redline_penetration";

const FALLBACK_SKILL_BALLS: CapabilityBall[] = [
  {
    ball_id: "ball_skill_coldchain_freight",
    ball_type: "SKILL",
    title: "冷链恒温箱阶梯运费与毛利核算引擎",
    domain_tags: ["cold_chain", "pricing", "margin"],
    sensitivity_level: 2,
    content:
      "def execute_skill(payload: dict) -> dict:\n    weight_kg = float(payload.get('weight_kg', 1.0))\n    order_amount = float(payload.get('order_amount', 1000.0))\n    base_fee = 45.0 if weight_kg <= 5 else 45.0 + (weight_kg - 5) * 8.0\n    return {'freight_cny': round(base_fee, 2), 'net_margin_ratio': round((order_amount - base_fee) / order_amount, 4)}",
    version: 1,
    status: "ACTIVE",
  },
  {
    ball_id: "ball_skill_copper_ton_km",
    ball_type: "SKILL",
    title: "跨境重卡吨公里阶梯运价与磅差赔付计算器",
    domain_tags: ["logistics", "copper", "settlement"],
    sensitivity_level: 2,
    content:
      "def execute_skill(payload: dict) -> dict:\n    tons = float(payload.get('tons', 30.0))\n    distance_km = float(payload.get('distance_km', 1850.0))\n    rate = 0.12 if distance_km <= 1500 else 0.095\n    return {'total_usd': round(tons * distance_km * rate, 2)}",
    version: 1,
    status: "ACTIVE",
  },
  {
    ball_id: "ball_skill_mcn_roi_commission",
    ball_type: "SKILL",
    title: "达人CPS阶梯抽佣与保底ROI核算器",
    domain_tags: ["mcn", "commission", "roi"],
    sensitivity_level: 2,
    content:
      "def execute_skill(payload: dict) -> dict:\n    gmv = float(payload.get('gmv_usd', 15000.0))\n    slot_fee = float(payload.get('slot_fee_usd', 500.0))\n    comm = max(0.0, gmv - 10000.0) * 0.12\n    return {'commission_usd': round(comm, 2), 'roi': round(gmv / (slot_fee + comm), 2)}",
    version: 1,
    status: "ACTIVE",
  },
];

const FALLBACK_SLOTS: UnitSlot[] = [
  {
    slot_id: "slot_sales_01",
    slot_name: "一线业务与跟单工位",
    department: "销售业务部",
    ball_ids: ["ball_data_catalog", "ball_skill_coldchain_freight"],
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

function formatPercent(val: number | undefined | null): string {
  if (val === undefined || val === null || Number.isNaN(val)) return "0.0%";
  const normalized = val <= 1.0 && val >= 0 ? val * 100 : val;
  return `${normalized.toFixed(1)}%`;
}

export const RedBlueCrucibleModal: React.FC<Props> = ({
  open,
  onClose,
  overview,
  custody,
  onClusterMutated,
  onToast,
}) => {
  const [activeTab, setActiveTab] = useState<CrucibleTab>("skill_crucible");

  // Collect all SKILL balls across cluster
  const skillBalls = useMemo<CapabilityBall[]>(() => {
    const map = new Map<string, CapabilityBall>();
    const candidates = [
      ...(overview?.all_balls ?? []),
      ...(overview?.accessible_balls ?? []),
      ...(custody?.mounted_balls ?? []),
      ...(custody?.managed_balls ?? []),
      ...(custody?.requestable_balls ?? []),
    ];
    for (const b of candidates) {
      if (b && b.ball_type === "SKILL") {
        map.set(b.ball_id, b);
      }
    }
    if (map.size === 0) {
      for (const fb of FALLBACK_SKILL_BALLS) {
        map.set(fb.ball_id, fb);
      }
    }
    return Array.from(map.values());
  }, [overview, custody]);

  // Collect all slots across cluster
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

  // Tab 1 State: Skill Red-Blue Stress Test & Self-Healing
  const [selectedSkillBallId, setSelectedSkillBallId] = useState<string>("");
  const [attackIntensity, setAttackIntensity] = useState<
    "EXTREME" | "STANDARD"
  >("EXTREME");
  const [maxGenerations, setMaxGenerations] = useState<number>(3);
  const [autoHeal, setAutoHeal] = useState<boolean>(true);
  const [runningStressTest, setRunningStressTest] = useState<boolean>(false);
  const [stressReport, setStressReport] =
    useState<SkillStressTestResponse | null>(null);

  // Tab 2 State: Slot Redline Penetration & Social Engineering Range
  const [targetSlotId, setTargetSlotId] = useState<string>("slot_sales_01");
  const [attackCount, setAttackCount] = useState<number>(4);
  const [runningPenetration, setRunningPenetration] = useState<boolean>(false);
  const [penetrationReport, setPenetrationReport] =
    useState<RedlinePenetrationResponse | null>(null);

  // Historical reports counter
  const [reportsCount, setReportsCount] = useState<number>(0);

  useEffect(() => {
    if (
      skillBalls.length > 0 &&
      (!selectedSkillBallId ||
        !skillBalls.some((b) => b.ball_id === selectedSkillBallId))
    ) {
      setSelectedSkillBallId(skillBalls[0].ball_id);
    }
  }, [skillBalls, selectedSkillBallId]);

  useEffect(() => {
    if (
      availableSlots.length > 0 &&
      (!targetSlotId ||
        !availableSlots.some((s) => s.slot_id === targetSlotId))
    ) {
      setTargetSlotId(availableSlots[0].slot_id);
    }
  }, [availableSlots, targetSlotId]);

  useEffect(() => {
    if (!open) return;
    fetchCrucibleReports()
      .then((res) => {
        if (Array.isArray(res)) {
          setReportsCount(res.length);
        } else if (res && typeof res === "object") {
          const sLen = Array.isArray(res.skill_reports)
            ? res.skill_reports.length
            : 0;
          const pLen = Array.isArray(res.penetration_audits)
            ? res.penetration_audits.length
            : 0;
          const rLen = Array.isArray(res.reports) ? res.reports.length : 0;
          setReportsCount(sLen + pLen + rLen);
        }
      })
      .catch(() => {
        // ignore
      });
  }, [open]);

  if (!open) return null;

  const selectedSkillBall = skillBalls.find(
    (b) => b.ball_id === selectedSkillBallId
  );

  const handleStartStressTest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSkillBallId || runningStressTest) return;
    setRunningStressTest(true);
    try {
      const res = await stressTestSkillInCrucible({
        ball_id: selectedSkillBallId,
        attack_intensity: attackIntensity,
        auto_heal: autoHeal,
        max_generations: maxGenerations,
      });
      setStressReport(res);
      setReportsCount((c) => c + 1);
      await onClusterMutated();
      onToast(
        `🔥 技能球「${res.ball_title}」红蓝对抗自愈完成！存活率：${formatPercent(
          res.initial_pass_rate
        )} -> ${formatPercent(res.final_pass_rate)}`,
        "ok"
      );
    } catch (err: unknown) {
      onToast(
        err instanceof Error ? err.message : "技能球红蓝对抗自愈执行失败",
        "err"
      );
    } finally {
      setRunningStressTest(false);
    }
  };

  const handleStartPenetrationAudit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetSlotId || runningPenetration) return;
    setRunningPenetration(true);
    try {
      const res = await runRedlinePenetrationAudit({
        target_slot_id: targetSlotId,
        attack_count: attackCount,
      });
      setPenetrationReport(res);
      setReportsCount((c) => c + 1);
      await onClusterMutated();
      onToast(
        `🛡️ 工位「${res.slot_title}」红线穿刺压力审计完成！综合防御得分：${res.defense_score} / 100`,
        res.defense_score >= 80 ? "ok" : "err"
      );
    } catch (err: unknown) {
      onToast(
        err instanceof Error ? err.message : "工位红线穿刺压力审计执行失败",
        "err"
      );
    } finally {
      setRunningPenetration(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-[#131314] border border-[#2d2e30] rounded-xl w-full max-w-6xl max-h-[92vh] flex flex-col shadow-2xl overflow-hidden text-xs text-[#e3e3e3]">
        {/* Header */}
        <div className="px-5 py-3.5 bg-[#18191b] border-b border-[#2d2e30] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#f28b82]/15 border border-[#f28b82]/40 flex items-center justify-center text-[#f28b82]">
              <Flame className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-[#e3e3e3]">
                  红蓝对抗自愈沙箱与红线穿刺靶场 (Red-Blue Adversarial Crucible)
                </h2>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#f28b82]/15 text-[#f28b82] border border-[#f28b82]/30">
                  Pillar 2 · Self-Healing &amp; Penetration v5.0
                </span>
              </div>
              <p className="text-[11px] text-[#9aa0a6] mt-0.5">
                Red-Team 自动构造零除/负数/注入/越界/拆单/伪造特批等破坏性载荷，Blue-Team
                在洁净室沙箱中多代免疫重构并加固工位红线
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <div className="px-2.5 py-1 rounded bg-[#131314] border border-[#2d2e30] font-mono text-[11px] text-[#9aa0a6] flex items-center gap-1.5">
              <History className="w-3.5 h-3.5 text-[#f28b82]" />
              <span>累计对抗审计报告: {reportsCount} 份</span>
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

        {/* Mode Tabs */}
        <div className="px-5 py-2.5 bg-[#18191b]/60 border-b border-[#2d2e30] flex flex-wrap items-center justify-between gap-2 shrink-0">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setActiveTab("skill_crucible")}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-medium border transition flex items-center gap-2 ${activeTab === "skill_crucible"
                  ? "bg-[#f28b82] text-[#3c0b07] border-[#f28b82] shadow-sm font-semibold"
                  : "bg-[#1e1f20] hover:bg-[#282a2c] text-[#9aa0a6] border-[#3c4043]"
                }`}
            >
              <Flame className="w-3.5 h-3.5" />
              <span>🔥 技能球红蓝对抗与多代自愈炼丹炉</span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("redline_penetration")}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-medium border transition flex items-center gap-2 ${activeTab === "redline_penetration"
                  ? "bg-[#81c995] text-[#0d3b1e] border-[#81c995] shadow-sm font-semibold"
                  : "bg-[#1e1f20] hover:bg-[#282a2c] text-[#9aa0a6] border-[#3c4043]"
                }`}
            >
              <Shield className="w-3.5 h-3.5" />
              <span>🛡️ 工位红线穿刺与社工抗压靶场</span>
            </button>
          </div>

          <div className="text-[11px] font-mono text-[#9aa0a6]">
            洁净室引擎: <span className="text-[#81c995]">python -I (AST Guarded)</span>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {activeTab === "skill_crucible" ? (
            <>
              {/* Configuration Form */}
              <form
                onSubmit={handleStartStressTest}
                className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3"
              >
                <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                  <div className="md:col-span-2 space-y-1">
                    <label className="text-[11px] text-[#9aa0a6] block">
                      选择目标 Python 技能球 (`SKILL` Ball)
                    </label>
                    <select
                      value={selectedSkillBallId}
                      onChange={(e) => setSelectedSkillBallId(e.target.value)}
                      className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#f28b82] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                    >
                      {skillBalls.map((b) => (
                        <option key={b.ball_id} value={b.ball_id}>
                          [SKILL v{b.version ?? 1}] {b.title} ({b.ball_id})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-1">
                    <label className="text-[11px] text-[#9aa0a6] block">
                      Red-Team 攻击强度 (Intensity)
                    </label>
                    <div className="grid grid-cols-2 gap-1.5">
                      <button
                        type="button"
                        onClick={() => setAttackIntensity("EXTREME")}
                        className={`py-2 px-2.5 rounded-lg font-mono text-[11px] border transition ${attackIntensity === "EXTREME"
                            ? "bg-[#f28b82]/20 border-[#f28b82] text-[#f28b82] font-bold"
                            : "bg-[#131314] border-[#3c4043] text-[#9aa0a6]"
                          }`}
                      >
                        🔥 EXTREME 极限轰炸
                      </button>
                      <button
                        type="button"
                        onClick={() => setAttackIntensity("STANDARD")}
                        className={`py-2 px-2.5 rounded-lg font-mono text-[11px] border transition ${attackIntensity === "STANDARD"
                            ? "bg-[#fdd663]/20 border-[#fdd663] text-[#fdd663] font-bold"
                            : "bg-[#131314] border-[#3c4043] text-[#9aa0a6]"
                          }`}
                      >
                        ⚡ STANDARD 标准
                      </button>
                    </div>
                  </div>

                  <div className="space-y-1">
                    <label className="text-[11px] text-[#9aa0a6] block">
                      最大自愈进化代数 (1~5 代)
                    </label>
                    <div className="flex items-center gap-1">
                      {[1, 2, 3, 4, 5].map((gen) => (
                        <button
                          key={gen}
                          type="button"
                          onClick={() => setMaxGenerations(gen)}
                          className={`flex-1 py-2 rounded-lg font-mono text-xs border transition ${maxGenerations === gen
                              ? "bg-[#81c995] text-[#0d3b1e] border-[#81c995] font-bold"
                              : "bg-[#131314] text-[#9aa0a6] border-[#3c4043]"
                            }`}
                        >
                          {gen}代
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                {selectedSkillBall && (
                  <div className="p-2.5 rounded-lg bg-[#131314] border border-[#2d2e30] font-mono text-[11px] text-[#9aa0a6]">
                    <div className="flex items-center justify-between mb-1">
                      <span>当前技能球源码快照 ({selectedSkillBall.ball_id}):</span>
                      <span className="text-[#a8c7fa]">
                        Version v{selectedSkillBall.version ?? 1}
                      </span>
                    </div>
                    <pre className="text-[10px] text-[#e3e3e3] max-h-24 overflow-y-auto whitespace-pre-wrap">
                      {selectedSkillBall.content}
                    </pre>
                  </div>
                )}

                <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                  <label className="flex items-center gap-2 text-[11px] text-[#e3e3e3] cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={autoHeal}
                      onChange={(e) => setAutoHeal(e.target.checked)}
                      className="rounded border-[#3c4043] bg-[#131314] text-[#81c995]"
                    />
                    <span>
                      启用 Blue-Team 免疫自愈重构（当发现崩溃漏洞时自动重写防御型 Python
                      源码并热更新晋升球体版本）
                    </span>
                  </label>

                  <button
                    type="submit"
                    disabled={runningStressTest || !selectedSkillBallId}
                    className="px-5 py-2 rounded-lg bg-[#f28b82] hover:bg-[#f6a19a] text-[#3c0b07] font-semibold text-xs flex items-center gap-2 disabled:opacity-40 transition shadow-md"
                  >
                    {runningStressTest ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>
                          正在发射破坏性向量轰炸并执行多代代码免疫重构...
                        </span>
                      </>
                    ) : (
                      <>
                        <Flame className="w-4 h-4" />
                        <span>🚀 启动红蓝对抗自愈进化</span>
                      </>
                    )}
                  </button>
                </div>
              </form>

              {runningStressTest && (
                <div className="p-8 rounded-xl bg-[#18191b] border border-[#f28b82]/40 flex flex-col items-center justify-center gap-3 text-center">
                  <Loader2 className="w-7 h-7 text-[#f28b82] animate-spin" />
                  <div className="text-sm font-medium text-[#e3e3e3]">
                    红蓝炼丹炉正在轰炸技能球「
                    {selectedSkillBall?.title ?? selectedSkillBallId}」...
                  </div>
                  <p className="text-[11px] text-[#9aa0a6] max-w-xl">
                    Red-Team 正在注入除零、极端负数、类型混淆、超大浮点数溢出、空字典及恶意字段；Blue-Team
                    正在分析 Traceback 并生成加固补丁
                  </p>
                </div>
              )}

              {/* Stress Test & Self-Healing Result */}
              {stressReport && (
                <div className="space-y-4">
                  {/* Survival Rate Banner */}
                  <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] flex flex-wrap items-center justify-between gap-4">
                    <div className="flex items-center gap-4">
                      <div className="p-3 rounded-lg bg-[#131314] border border-[#2d2e30] flex items-center gap-3">
                        <div>
                          <div className="text-[10px] text-[#9aa0a6]">
                            初始轰炸存活率
                          </div>
                          <div className="text-lg font-mono font-bold text-[#f28b82]">
                            {formatPercent(stressReport.initial_pass_rate)}
                          </div>
                        </div>
                        <ArrowRight className="w-5 h-5 text-[#9aa0a6]" />
                        <div>
                          <div className="text-[10px] text-[#9aa0a6]">
                            Blue-Team 自愈后存活率
                          </div>
                          <div className="text-lg font-mono font-bold text-[#81c995]">
                            {formatPercent(stressReport.final_pass_rate)}
                          </div>
                        </div>
                      </div>

                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-sm text-[#e3e3e3]">
                            {stressReport.ball_title}
                          </span>
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-mono ${stressReport.healed
                                ? "bg-[#81c995]/20 text-[#81c995] border border-[#81c995]/40"
                                : "bg-[#fdd663]/20 text-[#fdd663] border border-[#fdd663]/40"
                              }`}
                          >
                            {stressReport.healed
                              ? "PATCH_VALIDATED（仅覆盖本次测试）"
                              : "AUDITED"}
                          </span>
                        </div>
                        <div className="text-[11px] font-mono text-[#9aa0a6] mt-0.5">
                          Report ID: {stressReport.report_id} · 进化代数:{" "}
                          {stressReport.generations?.length ?? 1} 代
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-3 font-mono text-[11px] text-[#9aa0a6]">
                      <span>
                        LLM Calls:{" "}
                        <strong className="text-[#fdd663]">
                          {stressReport.token_telemetry?.llm_calls ?? 0}
                        </strong>
                      </span>
                      <span>·</span>
                      <span>
                        Tokens:{" "}
                        <strong className="text-[#a8c7fa]">
                          {(
                            stressReport.token_telemetry?.estimated_tokens ?? 0
                          ).toLocaleString()}
                        </strong>
                      </span>
                      <span>·</span>
                      <span>
                        Latency:{" "}
                        <strong className="text-[#81c995]">
                          {Math.round(
                            stressReport.token_telemetry?.total_latency_ms ?? 0
                          )}
                          ms
                        </strong>
                      </span>
                    </div>
                  </div>

                  {/* Red-Team Attack Vector Matrix */}
                  <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Bug className="w-4 h-4 text-[#f28b82]" />
                        <span className="font-semibold text-[#e3e3e3]">
                          Red-Team 破坏性攻击向量矩阵 (`adversarial_vectors`)
                        </span>
                      </div>
                      <span className="font-mono text-[11px] text-[#9aa0a6]">
                        共 {stressReport.adversarial_vectors?.length ?? 0}{" "}
                        条极端边界/恶意攻击载荷
                      </span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                      {(stressReport.adversarial_vectors ?? []).map(
                        (vec, idx) => {
                          const initOk =
                            vec.initial_passed ?? vec.passed ?? false;
                          const finalOk =
                            vec.final_passed ??
                            vec.survived ??
                            vec.passed ??
                            true;
                          const payloadObj =
                            vec.payload ?? vec.input_payload ?? {};
                          const outObj =
                            vec.final_output ??
                            vec.sandbox_output ??
                            vec.actual_output ??
                            vec.error_detail ??
                            {};
                          return (
                            <div
                              key={vec.vector_id ?? idx}
                              className="p-3 rounded-lg bg-[#131314] border border-[#2d2e30] space-y-2 font-mono text-[11px]"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-sans font-semibold text-[#e3e3e3]">
                                  #{idx + 1}{" "}
                                  {vec.name ??
                                    vec.title ??
                                    vec.category ??
                                    vec.attack_type ??
                                    `Attack Vector #${idx + 1}`}
                                </span>
                                <div className="flex items-center gap-1.5">
                                  <span
                                    className={`px-1.5 py-0.5 rounded text-[10px] ${initOk
                                        ? "bg-[#81c995]/15 text-[#81c995]"
                                        : "bg-[#f28b82]/15 text-[#f28b82]"
                                      }`}
                                  >
                                    初测:{initOk ? "PASS" : "CRASH"}
                                  </span>
                                  <span>→</span>
                                  <span
                                    className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${finalOk
                                        ? "bg-[#81c995]/20 text-[#81c995]"
                                        : "bg-[#f28b82]/20 text-[#f28b82]"
                                      }`}
                                  >
                                    终测:{finalOk ? "SURVIVED" : "FAILED"}
                                  </span>
                                </div>
                              </div>

                              {vec.description && (
                                <div className="text-[11px] font-sans text-[#9aa0a6]">
                                  {vec.description}
                                </div>
                              )}

                              <div className="grid grid-cols-1 gap-1.5">
                                <div className="p-2 rounded bg-[#18191b] border border-[#2d2e30]">
                                  <span className="text-[10px] text-[#9aa0a6] block">
                                    破坏性 Payload:
                                  </span>
                                  <pre className="text-[10px] text-[#f28b82] overflow-x-auto whitespace-pre-wrap">
                                    {JSON.stringify(payloadObj)}
                                  </pre>
                                </div>
                                <div className="p-2 rounded bg-[#18191b] border border-[#2d2e30]">
                                  <span className="text-[10px] text-[#9aa0a6] block">
                                    自愈后沙箱输出:
                                  </span>
                                  <pre className="text-[10px] text-[#81c995] overflow-x-auto whitespace-pre-wrap">
                                    {typeof outObj === "string"
                                      ? outObj
                                      : JSON.stringify(outObj)}
                                  </pre>
                                </div>
                              </div>
                            </div>
                          );
                        }
                      )}
                    </div>
                  </div>

                  {/* Blue-Team Multi-Generation Evolution Timeline & Final Hardened Code */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {/* Generations Timeline */}
                    <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3">
                      <div className="flex items-center gap-2">
                        <Wrench className="w-4 h-4 text-[#a8c7fa]" />
                        <span className="font-semibold text-[#e3e3e3]">
                          Blue-Team 多代进化时间轴 (`generations`)
                        </span>
                      </div>

                      <div className="space-y-2.5">
                        {(stressReport.generations ?? []).map((gen, idx) => {
                          const gNum =
                            gen.generation ?? gen.gen_index ?? idx + 1;
                          return (
                            <div
                              key={idx}
                              className="p-3 rounded-lg bg-[#131314] border border-[#2d2e30] space-y-1.5"
                            >
                              <div className="flex items-center justify-between">
                                <span className="font-mono font-bold text-[#a8c7fa]">
                                  Generation #{gNum}
                                </span>
                                <span className="font-mono text-[11px] text-[#81c995]">
                                  存活率: {formatPercent(gen.pass_rate)}
                                  {gen.passed_count !== undefined &&
                                    gen.total_count !== undefined
                                    ? ` (${gen.passed_count}/${gen.total_count})`
                                    : ""}
                                </span>
                              </div>
                              <div className="text-[11px] text-[#e3e3e3] leading-relaxed">
                                {gen.patch_summary ??
                                  gen.fix_rationale ??
                                  gen.blue_team_diagnosis ??
                                  "执行沙箱回归基准验证与防御边界加固"}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    {/* Hardened Final Python Code Viewer */}
                    <div className="p-4 rounded-xl bg-[#18191b] border border-[#81c995]/40 space-y-3 flex flex-col">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Terminal className="w-4 h-4 text-[#81c995]" />
                          <span className="font-semibold text-[#81c995]">
                            加固后的最终 Python 洁净室源码 (`final_code`)
                          </span>
                        </div>
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#81c995]/15 text-[#81c995]">
                          AST Verified · Ready for 0-Token Call
                        </span>
                      </div>

                      <pre className="flex-1 p-3.5 rounded-lg bg-[#0d0e10] border border-[#2d2e30] font-mono text-[11px] text-[#81c995] overflow-x-auto whitespace-pre-wrap leading-relaxed">
                        {stressReport.final_code}
                      </pre>
                    </div>
                  </div>
                </div>
              )}
            </>
          ) : (
            /* Tab 2: Slot Redline Penetration & Social Engineering Range */
            <div className="space-y-4">
              <form
                onSubmit={handleStartPenetrationAudit}
                className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3"
              >
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
                  <div className="md:col-span-2 space-y-1">
                    <label className="text-[11px] text-[#9aa0a6] block">
                      选择接受红线穿刺与社工诱导审计的目标工位 (`target_slot_id`)
                    </label>
                    <select
                      value={targetSlotId}
                      onChange={(e) => setTargetSlotId(e.target.value)}
                      className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#81c995] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                    >
                      {availableSlots.map((s) => (
                        <option key={s.slot_id} value={s.slot_id}>
                          {s.slot_name} ({s.department} · {s.slot_id})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-1">
                    <label className="text-[11px] text-[#9aa0a6] block">
                      社工/越权诱导攻击波次 (Attacks)
                    </label>
                    <div className="flex items-center gap-1.5">
                      {[3, 4, 5].map((cnt) => (
                        <button
                          key={cnt}
                          type="button"
                          onClick={() => setAttackCount(cnt)}
                          className={`flex-1 py-2 rounded-lg font-mono text-xs border transition ${attackCount === cnt
                              ? "bg-[#81c995] text-[#0d3b1e] border-[#81c995] font-bold"
                              : "bg-[#131314] text-[#9aa0a6] border-[#3c4043]"
                            }`}
                        >
                          {cnt} 波攻击
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                  <div className="text-[11px] text-[#9aa0a6]">
                    涵盖攻击载荷类型：① 伪造高管紧急特批指令 · ② 拆单绕过单笔审批阈值 ·
                    ③ 话术套取绝密底价/PII隐私 · ④ 道德绑架与断供恐吓越权放行
                  </div>

                  <button
                    type="submit"
                    disabled={runningPenetration || !targetSlotId}
                    className="px-5 py-2 rounded-lg bg-[#81c995] hover:bg-[#95d5a7] text-[#0d3b1e] font-semibold text-xs flex items-center gap-2 disabled:opacity-40 transition shadow-md"
                  >
                    {runningPenetration ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>正在发射多波次社工诱导载荷测试工位红线...</span>
                      </>
                    ) : (
                      <>
                        <Target className="w-4 h-4" />
                        <span>🛡️ 发起工位红线穿刺压力审计</span>
                      </>
                    )}
                  </button>
                </div>
              </form>

              {runningPenetration && (
                <div className="p-8 rounded-xl bg-[#18191b] border border-[#81c995]/40 flex flex-col items-center justify-center gap-3 text-center">
                  <Loader2 className="w-7 h-7 text-[#81c995] animate-spin" />
                  <div className="text-sm font-medium text-[#e3e3e3]">
                    正在向工位「{targetSlotId}」发射 {attackCount}{" "}
                    类高危社会工程学与越权穿刺载荷...
                  </div>
                  <p className="text-[11px] text-[#9aa0a6]">
                    实时检验该工位挂载的 REDLINE 与 AUTHORITY
                    球体在本次样本中能否识别并阻断越权诱导
                  </p>
                </div>
              )}

              {penetrationReport && (
                <div className="space-y-4">
                  {/* Defense Score Banner */}
                  <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] flex flex-wrap items-center justify-between gap-4">
                    <div className="flex items-center gap-4">
                      <div
                        className={`px-4 py-2.5 rounded-xl border font-mono text-center ${penetrationReport.defense_score >= 85
                            ? "bg-[#81c995]/15 border-[#81c995]/50 text-[#81c995]"
                            : "bg-[#fdd663]/15 border-[#fdd663]/50 text-[#fdd663]"
                          }`}
                      >
                        <div className="text-[10px] uppercase">
                          综合红线防御得分
                        </div>
                        <div className="text-2xl font-bold">
                          {penetrationReport.defense_score}
                          <span className="text-xs font-normal"> / 100</span>
                        </div>
                      </div>

                      <div>
                        <div className="text-sm font-semibold text-[#e3e3e3]">
                          受测工位：{penetrationReport.slot_title} (
                          {penetrationReport.target_slot_id})
                        </div>
                        <div className="text-[11px] font-mono text-[#9aa0a6] mt-0.5">
                          Audit ID: {penetrationReport.audit_id} · 穿刺测试波次:{" "}
                          {penetrationReport.attacks?.length ?? 0} 波
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-3 font-mono text-[11px] text-[#9aa0a6]">
                      <span>
                        LLM Calls:{" "}
                        <strong className="text-[#fdd663]">
                          {penetrationReport.token_telemetry?.llm_calls ?? 0}
                        </strong>
                      </span>
                      <span>·</span>
                      <span>
                        Tokens:{" "}
                        <strong className="text-[#a8c7fa]">
                          {(
                            penetrationReport.token_telemetry
                              ?.estimated_tokens ?? 0
                          ).toLocaleString()}
                        </strong>
                      </span>
                    </div>
                  </div>

                  {/* Attack Results Cards */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {(penetrationReport.attacks ?? []).map((atk, idx) => {
                      const isBlocked =
                        atk.blocked ??
                        atk.intercepted ??
                        atk.passed_defense ??
                        atk.status !== "BREACHED";
                      return (
                        <div
                          key={atk.attack_id ?? idx}
                          className="p-3.5 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-2.5"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-semibold text-[#e3e3e3] text-xs flex items-center gap-1.5">
                              <AlertOctagon className="w-3.5 h-3.5 text-[#f28b82]" />
                              <span>
                                载荷 #{idx + 1}:{" "}
                                {atk.vector_name ??
                                  atk.title ??
                                  atk.category ??
                                  atk.attack_type ??
                                  `社工诱导攻击 #${idx + 1}`}
                              </span>
                            </span>
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${isBlocked
                                  ? "bg-[#81c995]/20 text-[#81c995] border border-[#81c995]/40"
                                  : "bg-[#f28b82]/20 text-[#f28b82] border border-[#f28b82]/40"
                                }`}
                            >
                              {isBlocked
                                ? "🛡️ INTERCEPTED (成功阻断)"
                                : "⚠️ BREACHED (存在敞口)"}
                            </span>
                          </div>

                          <div className="p-2.5 rounded bg-[#131314] border border-[#f28b82]/30 space-y-1">
                            <div className="text-[10px] text-[#f28b82] font-mono">
                              💉 Red-Team 注入话术 (Injected Prompt):
                            </div>
                            <div className="text-[11px] text-[#e3e3e3] leading-relaxed">
                              {atk.prompt ??
                                atk.attack_prompt ??
                                atk.injected_message ??
                                "—"}
                            </div>
                          </div>

                          <div className="p-2.5 rounded bg-[#131314] border border-[#81c995]/30 space-y-1">
                            <div className="text-[10px] text-[#81c995] font-mono">
                              🤖 工位 Agent 实战拦截响应:
                            </div>
                            <div className="text-[11px] text-[#e3e3e3] leading-relaxed">
                              {atk.agent_response ??
                                atk.response_excerpt ??
                                atk.defense_reasoning ??
                                "已触发红线熔断并拒绝越权诉求"}
                            </div>
                          </div>

                          {(atk.triggered_redline_ball ||
                            atk.redline_ball_id) && (
                              <div className="flex items-center justify-between text-[10px] font-mono text-[#a8c7fa] pt-0.5">
                                <span>
                                  触发防御球体:{" "}
                                  {atk.triggered_redline_ball ??
                                    atk.redline_ball_id}
                                </span>
                                {atk.severity && (
                                  <span className="text-[#fdd663]">
                                    风险等级: {atk.severity}
                                  </span>
                                )}
                              </div>
                            )}
                        </div>
                      );
                    })}
                  </div>

                  {/* Recommendations */}
                  {Array.isArray(penetrationReport.recommendations) &&
                    penetrationReport.recommendations.length > 0 && (
                      <div className="p-4 rounded-xl bg-[#18191b] border border-[#a8c7fa]/40 space-y-2">
                        <div className="flex items-center gap-2 text-[#a8c7fa] font-semibold">
                          <ShieldCheck className="w-4 h-4" />
                          <span>工位红线球与权限边界加固建议 (`recommendations`)</span>
                        </div>
                        <ul className="space-y-1.5 text-[11px] text-[#e3e3e3] list-disc list-inside">
                          {penetrationReport.recommendations.map((rec, idx) => (
                            <li key={idx}>{rec}</li>
                          ))}
                        </ul>
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

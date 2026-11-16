import React, { useEffect, useMemo, useState } from "react";
import {
  Check,
  KeyRound,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  UserCheck,
  X,
} from "lucide-react";
import { ShadowOutputReviews } from "./ShadowOutputReviews";
import { CandidateReview } from "./CandidateReview";
import { handoverSlotOccupant, provisionAccountPassword } from "../api";
import {
  ArenaReport,
  BoardResolution,
  EmployeeProfile,
  SwarmPulseEvent,
  UnifiedOverviewPayload,
  UnitSlot,
} from "../types";

interface Props {
  overview: UnifiedOverviewPayload;
  actorUserId?: string;
  busyAction: string | null;
  onConveneBoard: (agenda?: string, targetSlotId?: string, forceVeto?: boolean) => Promise<void>;
  onDecideResolution: (resolutionId: string, approve: boolean) => Promise<void>;
  onRollbackVault: (scope: "LOCAL" | "GLOBAL", subtreeRootId?: string, reason?: string) => Promise<void>;
  onRefreshAll?: () => Promise<void>;
  onToast?: (text: string, kind?: "ok" | "err") => void;
}

export const ExecutiveControlDeck: React.FC<Props> = ({
  overview,
  actorUserId,
  busyAction,
  onConveneBoard,
  onDecideResolution,
  onRollbackVault,
  onRefreshAll,
  onToast,
}) => {
  const [subTab, setSubTab] = useState<"board" | "slots" | "arena" | "pulse">("board");
  const [agendaInput, setAgendaInput] = useState(
    "评估一线业务岗位进入人机协同阶段"
  );
  const [targetSlot, setTargetSlot] = useState(
    overview.all_slots?.[0]?.slot_id ?? "SLOT_BOSS"
  );

  // Slots & Scores filter states
  const [slotTypeFilter, setSlotTypeFilter] = useState<
    "ALL" | "HUMAN" | "HYBRID_TRANSITION" | "AGENT" | "HIGH_REPLACE"
  >("ALL");
  const [slotSearchQuery, setSlotSearchQuery] = useState("");
  const [lastConvenedNotice, setLastConvenedNotice] = useState<string | null>(null);

  // 岗人分离 · 离职/替班无感交接台状态
  const [handoverSlotId, setHandoverSlotId] = useState<string>(
    overview.all_slots?.find((s) => s.slot_id !== "SLOT_BOSS")?.slot_id ??
      overview.all_slots?.[0]?.slot_id ??
      ""
  );
  const [handoverMode, setHandoverMode] = useState<"RESIGN_HANDOVER" | "LEAVE_DELEGATION">(
    "RESIGN_HANDOVER"
  );
  const [newUserIdInput, setNewUserIdInput] = useState("");
  const [newPersonNameInput, setNewPersonNameInput] = useState("");
  const [newInitialPasswordInput, setNewInitialPasswordInput] = useState("");
  const [handoverReason, setHandoverReason] = useState("离职/替班岗位无感交接，权能球零损耗继承");
  const [handoverSubmitting, setHandoverSubmitting] = useState(false);
  const [provisionUserId, setProvisionUserId] = useState("");
  const [provisionPasswordInput, setProvisionPasswordInput] = useState("");
  const [provisioningPassword, setProvisioningPassword] = useState(false);
  const [handoverReceipt, setHandoverReceipt] = useState<{
    target_slot_id: string;
    slot_name: string;
    handover_mode: string;
    previous_user_id: string;
    new_user_id: string;
    new_person_name: string;
    inherited_ball_ids: string[];
    inherited_ball_count: number;
    password_provisioned?: boolean;
  } | null>(null);

  const subtreeOptions = useMemo(() => {
    const nodes = overview.topology_nodes ?? [];
    const aspects = nodes.filter((n) => n.node_type === "ASPECT_NODE");
    const seen = new Set<string>();
    const list: Array<{ id: string; label: string; desc: string }> = [];
    for (const a of aspects) {
      if (!seen.has(a.subtree_root_id)) {
        seen.add(a.subtree_root_id);
        list.push({
          id: a.subtree_root_id,
          label: `${a.subtree_root_id} (${a.label})`,
          desc: `覆盖 ${(a.domain_tags ?? []).join(" / ") || a.label} 域子树快照隔离`,
        });
      }
    }
    if (list.length === 0) {
      for (const n of nodes) {
        if (n.subtree_root_id && !seen.has(n.subtree_root_id)) {
          seen.add(n.subtree_root_id);
          list.push({
            id: n.subtree_root_id,
            label: `${n.subtree_root_id} (${n.label})`,
            desc: "部门级子树局域快照",
          });
        }
      }
    }
    if (list.length === 0) {
      list.push({
        id: "root",
        label: "root (默认主子树)",
        desc: "默认全局根节点局部快照",
      });
    }
    return list;
  }, [overview.topology_nodes]);

  // WORM Vault surgical rollback states
  const [selectedSubtree, setSelectedSubtree] = useState<string>(subtreeOptions[0]?.id ?? "root");
  useEffect(() => {
    if (subtreeOptions.length > 0 && !subtreeOptions.some((s) => s.id === selectedSubtree)) {
      setSelectedSubtree(subtreeOptions[0].id);
    }
  }, [subtreeOptions, selectedSubtree]);
  const [rollbackReason, setRollbackReason] = useState<string>(
    "外科手术级局部快照回滚：隔离清除异常幻觉状态，不伤及兄弟部门子树"
  );

  const isBoss = overview.role_view === "boss";
  const resolutions: BoardResolution[] = overview.board_resolutions ?? [];
  const slots: UnitSlot[] = overview.all_slots ?? [];
  const profiles: EmployeeProfile[] = overview.all_profiles ?? [];
  const arenaReports: ArenaReport[] = overview.arena_reports ?? [];
  const pulseLog: SwarmPulseEvent[] = overview.pulse_log ?? [];

  const filteredSlots = useMemo(() => {
    return slots.filter((slot) => {
      if (slotTypeFilter === "HIGH_REPLACE") {
        if ((slot.replaceability_score ?? 0) < 60) return false;
      } else if (slotTypeFilter !== "ALL") {
        if (slot.occupant_type !== slotTypeFilter) return false;
      }

      if (slotSearchQuery.trim()) {
        const q = slotSearchQuery.trim().toLowerCase();
        const prof = profiles.find((p) => p.slot_id === slot.slot_id);
        const hay = `${slot.slot_id} ${slot.slot_name} ${slot.department} ${slot.occupant_type} ${prof?.name ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [slots, profiles, slotTypeFilter, slotSearchQuery]);

  const tabs: Array<{ id: "board" | "slots" | "arena" | "pulse"; label: string; count: number }> = [
    { id: "board", label: "管理决议", count: resolutions.length },
    { id: "slots", label: "岗位概览", count: slots.length },
    { id: "arena", label: "工具验证记录", count: arenaReports.length },
    { id: "pulse", label: "运行日志", count: pulseLog.length },
  ];

  return (
    <div className="flex flex-col h-full bg-[#1e1f20] border border-[#2d2e30] rounded-lg overflow-hidden">
      {/* Studio Tab Header */}
      <div className="flex flex-wrap items-center justify-between px-3.5 border-b border-[#2d2e30] bg-[#1e1f20]">
        <div className="flex items-center gap-5">
          {tabs.map((t) => {
            const active = subTab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setSubTab(t.id)}
                className={`py-2.5 text-xs font-medium border-b-2 transition flex items-center gap-1.5 ${active
                  ? "border-[#a8c7fa] text-[#a8c7fa]"
                  : "border-transparent text-[#9aa0a6] hover:text-[#e3e3e3]"
                  }`}
              >
                <span>{t.label}</span>
                <span className="font-mono text-[10px] px-1.5 py-0.2 rounded bg-[#282a2c] text-[#9aa0a6]">
                  {t.count}
                </span>
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-1.5 py-1.5">
          <select
            value={selectedSubtree}
            onChange={(e) => setSelectedSubtree(e.target.value)}
            className="bg-[#131314] border border-[#3c4043] rounded px-2 py-1 text-[11px] text-[#e3e3e3]"
            title="选择局部恢复部门"
          >
            {subtreeOptions.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
          <button
            disabled={busyAction !== null}
            onClick={() => onRollbackVault("LOCAL", selectedSubtree, rollbackReason)}
            className="px-2.5 py-1 rounded bg-[#282a2c] hover:bg-[#35373a] border border-[#3c4043] text-[#e3e3e3] text-[11px] flex items-center gap-1 disabled:opacity-40"
          >
            <RotateCcw className="w-3 h-3 text-[#fdd663]" />
            局部恢复
          </button>
          {isBoss && (
            <button
              disabled={busyAction !== null}
              onClick={() => onRollbackVault("GLOBAL", undefined, "全局快照灾备恢复")}
              className="px-2.5 py-1 rounded bg-[#282a2c] hover:bg-[#35373a] border border-[#3c4043] text-[#f28b82] text-[11px] flex items-center gap-1 disabled:opacity-40"
            >
              全局恢复
            </button>
          )}
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-3.5 space-y-3 bg-[#131314]">
        {subTab === "board" && (
          <div className="space-y-3">
            {/* Convene Board Action Box */}
            <div className="p-3 rounded-lg bg-[#1e1f20] border border-[#2d2e30] space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-[#e3e3e3]">
                  发起管理层联合评审
                </span>
                <select
                  value={targetSlot}
                  onChange={(e) => setTargetSlot(e.target.value)}
                  className="bg-[#131314] border border-[#3c4043] rounded px-2 py-1 text-xs text-[#e3e3e3]"
                >
                  {slots.map((s) => (
                    <option key={s.slot_id} value={s.slot_id}>
                      {s.slot_name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex gap-2">
                <input
                  value={agendaInput}
                  onChange={(e) => setAgendaInput(e.target.value)}
                  placeholder="输入评审议题..."
                  className="flex-1 bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] outline-none rounded-md px-2.5 py-1.5 text-xs text-[#e3e3e3]"
                />
                <button
                  disabled={!isBoss || busyAction !== null}
                  onClick={() => onConveneBoard(agendaInput, targetSlot, false)}
                  className="px-3 py-1.5 rounded-md bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] text-xs font-medium disabled:opacity-40"
                >
                  发起评审
                </button>
                <button
                  disabled={!isBoss || busyAction !== null}
                  onClick={() =>
                    onConveneBoard(
                      "尝试向外部未授权节点开放客户明文税号导出权限",
                      targetSlot,
                      true
                    )
                  }
                  className="px-3 py-1.5 rounded-md bg-[#282a2c] hover:bg-[#35373a] border border-[#3c4043] text-[#f28b82] text-xs font-medium disabled:opacity-40"
                >
                  模拟风控否决
                </button>
              </div>
            </div>

            {resolutions.length === 0 && (
              <div className="text-xs text-[#9aa0a6] py-6 text-center">
                暂无管理决议，点击上方「发起评审」生成评估结果。
              </div>
            )}

            {/* Resolutions list */}
            {resolutions.map((res) => (
              <div
                key={res.resolution_id}
                className="p-3 rounded-lg bg-[#1e1f20] border border-[#2d2e30] space-y-2.5"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2 text-[11px]">
                      <span className="text-[#9aa0a6] font-mono">{res.resolution_id}</span>
                      {res.vetoed ? (
                        <span className="px-1.5 py-0.5 rounded bg-[#f28b82]/15 text-[#f28b82]">
                          已否决
                        </span>
                      ) : (
                        <span className="px-1.5 py-0.5 rounded bg-[#81c995]/15 text-[#81c995]">
                          评分 {res.weighted_score.toFixed(1)}
                        </span>
                      )}
                      <span className="px-1.5 py-0.5 rounded bg-[#282a2c] text-[#9aa0a6]">
                        {res.status === "APPROVED"
                          ? "已批准"
                          : res.status === "REJECTED"
                            ? "已驳回"
                            : "待拍板"}
                      </span>
                    </div>
                    <h4 className="text-xs font-medium text-[#e3e3e3] mt-1">{res.agenda}</h4>
                    <p className="text-[11px] text-[#9aa0a6] mt-0.5">{res.executive_brief}</p>
                  </div>

                  {isBoss && res.status === "PENDING_BOSS" && (
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        disabled={res.vetoed || busyAction !== null}
                        onClick={() => onDecideResolution(res.resolution_id, true)}
                        className="px-2.5 py-1 rounded bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] text-xs font-medium flex items-center gap-1 disabled:opacity-30"
                      >
                        <Check className="w-3.5 h-3.5" />
                        Approve
                      </button>
                      <button
                        disabled={busyAction !== null}
                        onClick={() => onDecideResolution(res.resolution_id, false)}
                        className="px-2.5 py-1 rounded bg-[#282a2c] hover:bg-[#35373a] border border-[#3c4043] text-[#e3e3e3] text-xs flex items-center gap-1"
                      >
                        <X className="w-3.5 h-3.5" />
                        Reject
                      </button>
                    </div>
                  )}
                </div>

                {/* Votes grid */}
                <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
                  {res.votes.map((v) => (
                    <div
                      key={v.director_id}
                      className="p-2 rounded bg-[#131314] border border-[#2d2e30] text-xs"
                    >
                      <div className="flex items-center justify-between font-medium">
                        <span className="truncate text-[#e3e3e3] text-[11px]">
                          {v.director_title}
                        </span>
                        <span
                          className={`text-[10px] font-mono ${v.stance === "VETO"
                            ? "text-[#f28b82]"
                            : v.stance === "APPROVE"
                              ? "text-[#81c995]"
                              : "text-[#fdd663]"
                            }`}
                        >
                          {v.stance}
                        </span>
                      </div>
                      <div className="text-[11px] text-[#9aa0a6] mt-1 line-clamp-2">
                        {v.rationale}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {subTab === "slots" && (
          <div className="space-y-3">
            <ShadowOutputReviews outputs={overview.reviewable_outputs ?? []} reviewerId={actorUserId} roleView={overview.role_view} onReviewed={onRefreshAll} />
            {/* 岗人分离 · 离职/替班无感交接台 */}
            <div className="p-3 rounded-lg bg-[#1e1f20] border border-[#3c4043] space-y-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <UserCheck className="w-4 h-4 text-[#a8c7fa]" />
                  <div>
                    <h4 className="text-xs font-medium text-[#e3e3e3]">
                      岗人分离 · 离职 / 替班无感交接台
                    </h4>
                    <p className="text-[11px] text-[#9aa0a6]">
                      选择岗位容器并将权能球零损耗移交接班人，自动唤醒关联休眠节点
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-1 bg-[#131314] p-0.5 rounded border border-[#2d2e30] text-[11px]">
                  <button
                    type="button"
                    onClick={() => setHandoverMode("RESIGN_HANDOVER")}
                    className={`px-2 py-0.5 rounded transition ${
                      handoverMode === "RESIGN_HANDOVER"
                        ? "bg-[#f28b82]/20 text-[#f28b82] border border-[#f28b82]/40"
                        : "text-[#9aa0a6] hover:text-[#e3e3e3]"
                    }`}
                  >
                    离职永久交接
                  </button>
                  <button
                    type="button"
                    onClick={() => setHandoverMode("LEAVE_DELEGATION")}
                    className={`px-2 py-0.5 rounded transition ${
                      handoverMode === "LEAVE_DELEGATION"
                        ? "bg-[#fdd663]/20 text-[#fdd663] border border-[#fdd663]/40"
                        : "text-[#9aa0a6] hover:text-[#e3e3e3]"
                    }`}
                  >
                    临时休假替班
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
                <select
                  value={handoverSlotId}
                  onChange={(e) => setHandoverSlotId(e.target.value)}
                  className="bg-[#131314] border border-[#3c4043] rounded px-2.5 py-1.5 text-xs text-[#e3e3e3] font-mono"
                >
                  {slots.map((s) => {
                    const p = profiles.find((x) => x.slot_id === s.slot_id);
                    return (
                      <option key={s.slot_id} value={s.slot_id}>
                        {s.slot_name} ({s.slot_id}) · 现任 {p?.name ?? s.occupant_id}
                      </option>
                    );
                  })}
                </select>
                <input
                  value={newUserIdInput}
                  onChange={(e) => setNewUserIdInput(e.target.value)}
                  placeholder="接任账号 ID（如 emp_new）"
                  className="bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] outline-none rounded px-2.5 py-1.5 text-xs text-[#e3e3e3]"
                />
                <input
                  value={newPersonNameInput}
                  onChange={(e) => setNewPersonNameInput(e.target.value)}
                  placeholder="接任人员姓名（如 林新锐）"
                  className="bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] outline-none rounded px-2.5 py-1.5 text-xs text-[#e3e3e3]"
                />
                <input
                  type="password"
                  value={newInitialPasswordInput}
                  onChange={(e) => setNewInitialPasswordInput(e.target.value)}
                  placeholder="接任初始密码（选填）"
                  className="bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] outline-none rounded px-2.5 py-1.5 text-xs text-[#e3e3e3]"
                />
                <button
                  type="button"
                  disabled={handoverSubmitting || busyAction !== null || !handoverSlotId}
                  onClick={async () => {
                    if (!newUserIdInput.trim() || !newPersonNameInput.trim()) {
                      onToast?.("请填写接任账号 ID 与姓名", "err");
                      return;
                    }
                    setHandoverSubmitting(true);
                    try {
                      const receipt = await handoverSlotOccupant({
                        actor_user_id: actorUserId || overview.current_user?.user_id,
                        target_slot_id: handoverSlotId,
                        new_user_id: newUserIdInput.trim(),
                        new_person_name: newPersonNameInput.trim(),
                        handover_mode: handoverMode,
                        reason: handoverReason.trim() || "管理台发起岗人分离交接",
                        ...(newInitialPasswordInput.trim()
                          ? { initial_password: newInitialPasswordInput.trim() }
                          : {}),
                      });
                      setHandoverReceipt(receipt);
                      setNewUserIdInput("");
                      setNewPersonNameInput("");
                      setNewInitialPasswordInput("");
                      onToast?.(
                        `交接成功：${receipt.slot_name} 已移交 ${receipt.new_person_name}，继承 ${receipt.inherited_ball_count} 颗权能球`,
                        "ok"
                      );
                      await onRefreshAll?.();
                    } catch (err) {
                      onToast?.(err instanceof Error ? err.message : "交接失败", "err");
                    } finally {
                      setHandoverSubmitting(false);
                    }
                  }}
                  className="px-3 py-1.5 rounded bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] text-xs font-medium flex items-center justify-center gap-1.5 disabled:opacity-40"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${handoverSubmitting ? "animate-spin" : ""}`} />
                  <span>{handoverSubmitting ? "交接执行中..." : "执行岗位无感交接"}</span>
                </button>
              </div>

              <input
                value={handoverReason}
                onChange={(e) => setHandoverReason(e.target.value)}
                placeholder="填写审计留痕原因..."
                className="w-full bg-[#131314] border border-[#2d2e30] focus:border-[#a8c7fa] outline-none rounded px-2.5 py-1 text-[11px] text-[#9aa0a6]"
              />

              {handoverReceipt && (
                <div className="p-2.5 rounded bg-[#131314] border border-[#81c995]/40 text-[11px] space-y-1">
                  <div className="flex items-center justify-between text-[#81c995] font-medium">
                    <span>
                      ✅ 交接已入账 · {handoverReceipt.slot_name} ({handoverReceipt.target_slot_id})
                    </span>
                    <button
                      type="button"
                      onClick={() => setHandoverReceipt(null)}
                      className="text-[#9aa0a6] hover:text-[#e3e3e3] text-[10px]"
                    >
                      收起
                    </button>
                  </div>
                  <div className="text-[#e3e3e3]">
                    原驻守人 <span className="font-mono text-[#fdd663]">{handoverReceipt.previous_user_id}</span>{" "}
                    {handoverReceipt.handover_mode === "RESIGN_HANDOVER" ? "（已离岗停用）" : "（休假替班保留）"}
                    {" → "}接任账号 <span className="font-mono text-[#81c995]">{handoverReceipt.new_user_id}</span>（姓名 {handoverReceipt.new_person_name} ·{" "}
                    {handoverReceipt.password_provisioned ? "已配置登录口令" : "待管理员配发口令"}）
                  </div>
                  <div className="text-[#9aa0a6] flex flex-wrap gap-1 pt-0.5">
                    <span>零损耗继承权能球 ({handoverReceipt.inherited_ball_count})：</span>
                    {handoverReceipt.inherited_ball_ids.map((bid) => (
                      <span
                        key={bid}
                        className="px-1.5 py-0.2 rounded bg-[#1e1f20] border border-[#2d2e30] font-mono text-[10px] text-[#a8c7fa]"
                      >
                        {bid}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {(overview.role_view === "boss" || overview.role_view === "manager") && profiles.length > 0 && (
              <div className="p-3 rounded-lg bg-[#1e1f20] border border-[#2d2e30] space-y-2">
                <div className="flex items-center gap-2">
                  <KeyRound className="w-4 h-4 text-[#81c995]" />
                  <div>
                    <h4 className="text-xs font-medium text-[#e3e3e3]">
                      岗位账号口令配发与恢复激活
                    </h4>
                    <p className="text-[11px] text-[#9aa0a6]">
                      为探网新建岗位或快照切换后的成员设置登录密码并恢复启用（仅主管 / 董事长可执行）
                    </p>
                  </div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                  <select
                    value={
                      provisionUserId ||
                      profiles.find((p) => p.user_id !== actorUserId)?.user_id ||
                      profiles[0]?.user_id ||
                      ""
                    }
                    onChange={(e) => setProvisionUserId(e.target.value)}
                    className="bg-[#131314] border border-[#3c4043] rounded px-2.5 py-1.5 text-xs text-[#e3e3e3] font-mono"
                  >
                    {profiles.map((p) => (
                      <option key={p.user_id} value={p.user_id}>
                        {p.name} (@{p.user_id}) · {p.title}
                      </option>
                    ))}
                  </select>
                  <input
                    type="password"
                    value={provisionPasswordInput}
                    onChange={(e) => setProvisionPasswordInput(e.target.value)}
                    placeholder="输入新登录密码..."
                    className="bg-[#131314] border border-[#3c4043] focus:border-[#81c995] outline-none rounded px-2.5 py-1.5 text-xs text-[#e3e3e3]"
                  />
                  <button
                    type="button"
                    disabled={provisioningPassword || !provisionPasswordInput.trim()}
                    onClick={async () => {
                      const targetUid =
                        provisionUserId ||
                        profiles.find((p) => p.user_id !== actorUserId)?.user_id ||
                        profiles[0]?.user_id ||
                        "";
                      if (!targetUid || !provisionPasswordInput.trim()) return;
                      setProvisioningPassword(true);
                      try {
                        await provisionAccountPassword(targetUid, {
                          new_password: provisionPasswordInput.trim(),
                        });
                        setProvisionPasswordInput("");
                        onToast?.(`已为账号 ${targetUid} 设置登录密码并激活`, "ok");
                        await onRefreshAll?.();
                      } catch (err) {
                        onToast?.(
                          err instanceof Error ? err.message : "设置账号口令失败",
                          "err"
                        );
                      } finally {
                        setProvisioningPassword(false);
                      }
                    }}
                    className="px-3 py-1.5 rounded bg-[#81c995] hover:bg-[#97d6a8] text-[#062e1f] text-xs font-medium flex items-center justify-center gap-1.5 disabled:opacity-40"
                  >
                    <KeyRound className="w-3.5 h-3.5" />
                    <span>{provisioningPassword ? "配置中..." : "设置密码并激活"}</span>
                  </button>
                </div>
              </div>
            )}

            {/* Filter & Search Bar */}
            <div className="p-2.5 rounded-lg bg-[#1e1f20] border border-[#2d2e30] flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-1.5">
                {(
                  [
                    { id: "ALL", label: `全部 (${slots.length})` },
                    { id: "HUMAN", label: "人工岗位" },
                    { id: "HYBRID_TRANSITION", label: "人机协同" },
                    { id: "AGENT", label: "自动值守" },
                    { id: "HIGH_REPLACE", label: "高自动化 (≥60%)" },
                  ] as const
                ).map((f) => (
                  <button
                    key={f.id}
                    onClick={() => setSlotTypeFilter(f.id)}
                    className={`px-2 py-1 rounded text-[11px] transition ${slotTypeFilter === f.id
                      ? "bg-[#a8c7fa]/15 border border-[#a8c7fa] text-[#a8c7fa]"
                      : "bg-[#131314] border border-[#2d2e30] text-[#9aa0a6] hover:text-[#e3e3e3]"
                      }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>

              <div className="relative min-w-[200px]">
                <Search className="w-3.5 h-3.5 text-[#9aa0a6] absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  value={slotSearchQuery}
                  onChange={(e) => setSlotSearchQuery(e.target.value)}
                  placeholder="搜索岗位名称 / 部门 / 人员..."
                  className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] outline-none rounded pl-7 pr-2.5 py-1 text-xs text-[#e3e3e3]"
                />
              </div>
            </div>

            {lastConvenedNotice && (
              <div className="px-3 py-2 rounded-lg bg-[#a8c7fa]/10 border border-[#a8c7fa]/40 flex items-center justify-between text-xs text-[#a8c7fa]">
                <span>✓ {lastConvenedNotice}</span>
                <button
                  onClick={() => setSubTab("board")}
                  className="underline font-medium hover:text-[#e3e3e3]"
                >
                  查看管理决议 →
                </button>
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
              {filteredSlots.map((slot) => {
                const prof = profiles.find((p) => p.slot_id === slot.slot_id);
                const repScore = slot.replaceability_score ?? 0;
                const isHighReplace = repScore >= 60;
                const agendaText = `评估【${slot.slot_name}】进入人机协同阶段议案`;

                return (
                  <div
                    key={slot.slot_id}
                    className="p-3 rounded-lg bg-[#1e1f20] border border-[#2d2e30] space-y-2.5"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-[11px] font-mono text-[#a8c7fa]">
                            {slot.slot_id}
                          </span>
                          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-[#131314] text-[#9aa0a6]">
                            {slot.department}
                          </span>
                        </div>
                        <h4 className="text-xs font-medium text-[#e3e3e3] mt-0.5">
                          {slot.slot_name} · {prof?.name ?? slot.occupant_id}
                        </h4>
                      </div>

                      <div className="flex items-center gap-1.5 shrink-0">
                        <span
                          className={`px-2 py-0.5 rounded border font-mono text-[10px] ${slot.occupant_type === "AGENT"
                            ? "bg-[#81c995]/15 border-[#81c995]/40 text-[#81c995]"
                            : slot.occupant_type === "HYBRID_TRANSITION"
                              ? "bg-[#fdd663]/15 border-[#fdd663]/40 text-[#fdd663]"
                              : "bg-[#282a2c] border-[#3c4043] text-[#e3e3e3]"
                            }`}
                        >
                          {slot.occupant_type}
                        </span>
                        <button
                          disabled={!isBoss || busyAction !== null}
                          onClick={() => {
                            setTargetSlot(slot.slot_id);
                            setAgendaInput(agendaText);
                            setLastConvenedNotice(`已提交议案：${agendaText}`);
                            void onConveneBoard(agendaText, slot.slot_id, false);
                          }}
                          className={`px-2 py-0.5 rounded text-[11px] font-medium transition disabled:opacity-40 ${isHighReplace
                            ? "bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f]"
                            : "bg-[#282a2c] hover:bg-[#35373a] border border-[#3c4043] text-[#a8c7fa]"
                            }`}
                          title={agendaText}
                        >
                          提请董事会审议接管
                        </button>
                      </div>
                    </div>

                    {/* Replaceability Progress Bar */}
                    <div className="space-y-1 bg-[#131314] p-2 rounded border border-[#2d2e30]">
                      <div className="flex items-center justify-between text-[11px]">
                        <span className="text-[#9aa0a6]">
                          可替代率进度 (Replaceability Score)
                        </span>
                        <span
                          className={`font-mono font-medium ${repScore >= 75
                            ? "text-[#f28b82]"
                            : repScore >= 55
                              ? "text-[#fdd663]"
                              : "text-[#81c995]"
                            }`}
                        >
                          {repScore.toFixed(1)}%
                        </span>
                      </div>
                      <div className="w-full h-1.5 bg-[#282a2c] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${Math.min(100, Math.max(0, repScore))}%`,
                            backgroundColor:
                              repScore >= 75
                                ? "#f28b82"
                                : repScore >= 55
                                  ? "#fdd663"
                                  : "#81c995",
                          }}
                        />
                      </div>
                      <div className="grid grid-cols-3 gap-1.5 pt-1 font-mono text-[10px]">
                        <div>
                          <span className="text-[#9aa0a6] font-sans">技能覆盖: </span>
                          <span className="text-[#e3e3e3]">
                            {(
                              slot.replaceability_breakdown?.skill_coverage ??
                              slot.rule_repetition_ratio ??
                              0
                            ).toFixed(0)}
                            %
                          </span>
                        </div>
                        <div>
                          <span className="text-[#9aa0a6] font-sans">影子采纳: </span>
                          <span className="text-[#81c995]">
                            {(
                              slot.replaceability_breakdown?.shadow_adoption_rate ??
                              slot.shadow_agreement_rate ??
                              0
                            ).toFixed(0)}
                            %
                          </span>
                        </div>
                        <div>
                          <span className="text-[#9aa0a6] font-sans">合规稳健: </span>
                          <span className="text-[#a8c7fa]">
                            {(
                              slot.replaceability_breakdown?.exception_discipline_factor ??
                              95
                            ).toFixed(0)}
                            %
                          </span>
                        </div>
                      </div>
                      {slot.replaceability_breakdown?.soft_skill_capped && (
                        <div className="mt-1 px-2 py-1 rounded bg-[#fdd663]/10 border border-[#fdd663]/30 text-[10px] text-[#fdd663]">
                          🛡️ {slot.replaceability_breakdown.ceiling_reason || "高主观边界保护封顶"}
                        </div>
                      )}
                    </div>

                    {prof && (
                      <div className="grid grid-cols-2 gap-1.5 text-[11px]">
                        <div className="p-2 rounded bg-[#131314] border border-[#2d2e30]">
                          <div className="text-[#9aa0a6]">View A (Employee)</div>
                          <div className="text-[#e3e3e3] font-mono mt-0.5">
                            Saved {prof.employee_view.saved_hours}h · Bonus +
                            {prof.employee_view.innovation_bonus}
                          </div>
                        </div>
                        {prof.management_view && (
                          <div className="p-2 rounded bg-[#131314] border border-[#2d2e30]">
                            <div className="text-[#9aa0a6]">View B (Management)</div>
                            <div className="text-[#e3e3e3] font-mono mt-0.5">
                              Score {prof.management_view.performance_score} · Probes{" "}
                              {prof.management_view.boundary_probes}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {subTab === "arena" && (
          <div className="space-y-2.5">
            {arenaReports.length === 0 && (
              <div className="text-xs text-[#9aa0a6] py-6 text-center">
                暂无工具验证记录
              </div>
            )}
            {arenaReports.map((rep) => (
              <div
                key={rep.proposal_id}
                className="p-3 rounded-lg bg-[#1e1f20] border border-[#2d2e30] space-y-2"
              >
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[#a8c7fa]">{rep.proposal_id}</span>
                    <span className="font-medium text-[#e3e3e3]">{rep.skill_title}</span>
                    <span className="text-[11px] text-[#9aa0a6]">
                      （{rep.total_samples} 组校验用例）
                    </span>
                  </div>
                  <span
                    className={`text-[11px] px-2 py-0.5 rounded ${rep.promoted
                      ? "bg-[#81c995]/15 text-[#81c995]"
                      : "bg-[#f28b82]/15 text-[#f28b82]"
                      }`}
                  >
                    {rep.promoted ? "已发布启用" : rep.candidate_status === "REJECTED" ? "已拒绝" : "候选 · 尚未发布"}
                  </span>
                </div>
                <pre className="p-2.5 rounded bg-[#131314] border border-[#2d2e30] text-[11px] text-[#e3e3e3] font-mono overflow-x-auto">
                  {rep.generated_code}
                </pre>
                <CandidateReview report={rep} reviewerId={actorUserId} onPublished={onRefreshAll} />
              </div>
            ))}
          </div>
        )}

        {subTab === "pulse" && (
          <div className="space-y-2.5">
            {/* Audit Hash Chain Status */}
            <div className="p-2.5 rounded-lg bg-[#1e1f20] border border-[#2d2e30] flex items-center justify-between text-xs">
              <div className="flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-[#81c995]" />
                <span className="text-[#e3e3e3] font-medium">
                  安全审计日志（共 {overview.vault_health.total_records} 条记录）
                </span>
                <span className="font-mono text-[11px] text-[#9aa0a6] truncate max-w-xs">
                  {overview.vault_health.head_hash}
                </span>
              </div>
              <span className="text-[11px] text-[#81c995]">
                {overview.vault_health.intact ? "校验正常" : "校验异常"}
              </span>
            </div>

            {/* Local Subtree Rollback Control Box */}
            <div className="p-3 rounded-lg bg-[#1e1f20] border border-[#2d2e30] space-y-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-xs font-medium text-[#e3e3e3]">
                    按部门局部恢复状态
                  </div>
                  <div className="text-[11px] text-[#9aa0a6]">
                    精准隔离故障部门并恢复至最近安全状态，不影响其他部门正常业务运行
                  </div>
                </div>
                <select
                  value={selectedSubtree}
                  onChange={(e) => setSelectedSubtree(e.target.value)}
                  className="bg-[#131314] border border-[#3c4043] rounded px-2.5 py-1 text-xs text-[#e3e3e3] font-mono"
                >
                  {subtreeOptions.map((opt) => (
                    <option key={opt.id} value={opt.id}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Subtree Quick Selector Pills */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                {subtreeOptions.map((opt) => {
                  const isTarget = selectedSubtree === opt.id;
                  return (
                    <button
                      key={opt.id}
                      onClick={() => setSelectedSubtree(opt.id)}
                      className={`p-2 rounded text-left border transition ${isTarget
                        ? "bg-[#fdd663]/10 border-[#fdd663] text-[#e3e3e3]"
                        : "bg-[#131314] border-[#2d2e30] text-[#9aa0a6] hover:border-[#3c4043]"
                        }`}
                    >
                      <div className="flex items-center justify-between font-mono text-[11px]">
                        <span className={isTarget ? "text-[#fdd663] font-medium" : "text-[#e3e3e3]"}>
                          {opt.label}
                        </span>
                        <span
                          className={`text-[10px] px-1.5 py-0.2 rounded ${isTarget
                            ? "bg-[#fdd663]/20 text-[#fdd663]"
                            : "bg-[#81c995]/15 text-[#81c995]"
                            }`}
                        >
                          {isTarget ? "TARGET" : "ISOLATED OK"}
                        </span>
                      </div>
                      <div className="text-[10px] text-[#9aa0a6] mt-1">{opt.desc}</div>
                    </button>
                  );
                })}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={rollbackReason}
                  onChange={(e) => setRollbackReason(e.target.value)}
                  placeholder="输入局部回滚审计原因..."
                  className="flex-1 bg-[#131314] border border-[#3c4043] focus:border-[#fdd663] outline-none rounded px-2.5 py-1.5 text-xs text-[#e3e3e3]"
                />
                <button
                  disabled={busyAction !== null}
                  onClick={() => onRollbackVault("LOCAL", selectedSubtree, rollbackReason)}
                  className="px-3 py-1.5 rounded bg-[#fdd663] hover:bg-[#fde082] text-[#1e1f20] text-xs font-medium flex items-center gap-1.5 disabled:opacity-40"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  精准回滚 {selectedSubtree}
                </button>
              </div>
            </div>

            {pulseLog.map((ev) => (
              <div
                key={ev.event_id}
                className="px-3 py-1.5 rounded bg-[#1e1f20] border border-[#2d2e30] flex items-center justify-between text-xs"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-mono text-[11px] text-[#a8c7fa] shrink-0">
                    {ev.event_type}
                  </span>
                  <span className="text-[#e3e3e3] truncate">{ev.summary}</span>
                </div>
                <span className="font-mono text-[11px] text-[#9aa0a6] shrink-0 ml-2">
                  {ev.node_id}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

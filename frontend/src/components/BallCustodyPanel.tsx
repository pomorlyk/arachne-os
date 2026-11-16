import React, { useMemo, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  Play,
  Plus,
  ShieldAlert,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import {
  decideBallRequest,
  directGrantBall,
  requestBallAccess,
  revokeBallFromSlot,
} from "../api";
import { CustodyBallItem, CustodyOverviewPayload } from "../types";

interface Props {
  custody: CustodyOverviewPayload | null;
  onRefresh: () => Promise<void>;
  onToast: (msg: string, kind?: "ok" | "err") => void;
  onQuickUse?: (
    promptText: string,
    ballType: CustodyBallItem["ball_type"]
  ) => void;
}

type DurationPreset = {
  label: string;
  grantMode: "LEASE_TTL" | "PERMANENT";
  ttlMinutes: number;
};

type FilterKind = "ALL" | "DATA" | "SKILL" | "GOV";

const DURATION_PRESETS: DurationPreset[] = [
  { label: "30分钟", grantMode: "LEASE_TTL", ttlMinutes: 30 },
  { label: "2小时", grantMode: "LEASE_TTL", ttlMinutes: 120 },
  { label: "8小时", grantMode: "LEASE_TTL", ttlMinutes: 8 * 60 },
  { label: "长期使用", grantMode: "PERMANENT", ttlMinutes: 120 },
];

const QUICK_REASONS = [
  "客户加急锁库协同",
  "月底集中对账核算",
  "跨岗临时顶班调用",
];

const TYPE_NAME_MAP: Record<CustodyBallItem["ball_type"], string> = {
  DATA: "业务资料",
  SKILL: "计算工具",
  AUTHORITY: "审批权限",
  REDLINE: "风控底线",
};

export const BallCustodyPanel: React.FC<Props> = ({
  custody,
  onRefresh,
  onToast,
  onQuickUse,
}) => {
  const [expandedBallId, setExpandedBallId] = useState<string | null>(null);
  const [filterKind, setFilterKind] = useState<FilterKind>("ALL");
  const [showRequestForm, setShowRequestForm] = useState(false);
  const [selectedBallId, setSelectedBallId] = useState("");
  const [durationPresetIdx, setDurationPresetIdx] = useState<number>(1);
  const [reason, setReason] = useState(QUICK_REASONS[0]);

  // Leader console states
  const [leaderTab, setLeaderTab] = useState<"PENDING" | "SUBORDINATES">(
    "PENDING"
  );
  const [decisionComments, setDecisionComments] = useState<
    Record<string, string>
  >({});
  const [targetSubSlot, setTargetSubSlot] = useState("");
  const [grantBallId, setGrantBallId] = useState("");
  const [directGrantMode, setDirectGrantMode] = useState<
    "PERMANENT" | "LEASE_TTL"
  >("PERMANENT");
  const [busy, setBusy] = useState(false);

  const filteredMountedBalls = useMemo(() => {
    const items = custody?.mounted_balls ?? [];
    if (filterKind === "ALL") return items;
    if (filterKind === "DATA") return items.filter((b) => b.ball_type === "DATA");
    if (filterKind === "SKILL") return items.filter((b) => b.ball_type === "SKILL");
    return items.filter(
      (b) => b.ball_type === "AUTHORITY" || b.ball_type === "REDLINE"
    );
  }, [custody?.mounted_balls, filterKind]);

  const ballTitleById = useMemo(() => {
    const map = new Map<string, string>();
    for (const b of custody?.mounted_balls ?? []) {
      map.set(b.ball_id, b.title);
    }
    for (const b of custody?.managed_balls ?? []) {
      map.set(b.ball_id, b.title);
    }
    for (const b of custody?.requestable_balls ?? []) {
      map.set(b.ball_id, b.title);
    }
    return map;
  }, [custody]);

  if (!custody) return null;

  const activeRequestBall =
    custody.requestable_balls.find(
      (b) =>
        b.ball_id === (selectedBallId || custody.requestable_balls[0]?.ball_id)
    ) ?? custody.requestable_balls[0];

  const chosenDuration =
    DURATION_PRESETS[durationPresetIdx] ?? DURATION_PRESETS[1];

  const handleRequestSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const ballId = activeRequestBall?.ball_id;
    if (!ballId) return;
    setBusy(true);
    try {
      await requestBallAccess({
        requester_id: custody.user_id,
        ball_id: ballId,
        grant_mode: chosenDuration.grantMode,
        ttl_minutes: chosenDuration.ttlMinutes,
        reason,
      });
      setShowRequestForm(false);
      await onRefresh();
      onToast(
        `已向负责人 ${activeRequestBall.custodian_name} 提交《${activeRequestBall.title}》开通申请`
      );
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "提交失败", "err");
    } finally {
      setBusy(false);
    }
  };

  const handleLeaderDecide = async (reqId: string, approve: boolean) => {
    setBusy(true);
    try {
      const comment =
        (decisionComments[reqId] ?? "").trim() ||
        (approve ? "同意开通权限" : "驳回权限申请");
      await decideBallRequest(reqId, {
        actor_user_id: custody.user_id,
        approve,
        comment,
      });
      await onRefresh();
      onToast(approve ? "已批准申请并开通权限" : "已驳回权限申请");
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "审批失败", "err");
    } finally {
      setBusy(false);
    }
  };

  const handleDirectGrant = async () => {
    const slotId = targetSubSlot || custody.subordinates[0]?.slot_id;
    const ballId = grantBallId || custody.managed_balls[0]?.ball_id;
    if (!slotId || !ballId) return;
    setBusy(true);
    try {
      await directGrantBall({
        leader_user_id: custody.user_id,
        target_slot_id: slotId,
        ball_id: ballId,
        grant_mode: directGrantMode,
        ttl_minutes: directGrantMode === "LEASE_TTL" ? 120 : undefined,
      });
      await onRefresh();
      const title = ballTitleById.get(ballId) ?? ballId;
      onToast(
        `已为成员开通《${title}》（${directGrantMode === "LEASE_TTL" ? "临时 2小时" : "长期开通"
        }）`
      );
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "开通失败", "err");
    } finally {
      setBusy(false);
    }
  };

  const handleRevoke = async (slotId: string, ballId: string) => {
    setBusy(true);
    try {
      await revokeBallFromSlot({
        leader_user_id: custody.user_id,
        target_slot_id: slotId,
        ball_id: ballId,
      });
      await onRefresh();
      const title = ballTitleById.get(ballId) ?? ballId;
      onToast(`已收回《${title}》权限`);
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "收回失败", "err");
    } finally {
      setBusy(false);
    }
  };

  const pendingList = custody.pending_subordinate_requests;
  const subList = custody.subordinates;

  return (
    <div className="space-y-4 text-xs">
      {/* 1. 我的岗位能力 + [+ 申请权限] */}
      <div className="space-y-2">
        <div className="flex items-center justify-between px-1">
          <span className="text-[11px] font-medium text-[#e3e3e3]">
            我的岗位能力 ({custody.mounted_balls.length})
          </span>
          {custody.requestable_balls.length > 0 && (
            <button
              type="button"
              onClick={() => setShowRequestForm((prev) => !prev)}
              className="px-2 py-0.5 rounded bg-[#282a2c] hover:bg-[#35373a] border border-[#3c4043] text-[#a8c7fa] text-[10px] flex items-center gap-1"
            >
              <Plus className="w-3 h-3" />
              <span>+ 申请权限</span>
            </button>
          )}
        </div>

        {/* 类型筛选胶囊 */}
        <div className="grid grid-cols-4 gap-1 px-0.5">
          {(
            [
              { id: "ALL", label: "全部" },
              { id: "DATA", label: "资料" },
              { id: "SKILL", label: "工具" },
              { id: "GOV", label: "权限" },
            ] as const
          ).map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setFilterKind(f.id)}
              className={`py-1 rounded text-[10px] border transition ${filterKind === f.id
                  ? "bg-[#282a2c] border-[#a8c7fa]/60 text-[#a8c7fa] font-medium"
                  : "bg-[#131314] border-[#2d2e30] text-[#9aa0a6] hover:text-[#e3e3e3]"
                }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* 申请开通新能力表单 */}
        {showRequestForm && activeRequestBall && (
          <form
            onSubmit={handleRequestSubmit}
            className="p-2.5 rounded-lg bg-[#131314] border border-[#a8c7fa]/50 space-y-2 text-[11px]"
          >
            <div className="flex items-center justify-between">
              <span className="font-medium text-[#a8c7fa]">
                申请开通新能力
              </span>
              <span className="text-[10px] text-[#9aa0a6]">
                {activeRequestBall.business_category || "通用业务"}
              </span>
            </div>

            <select
              value={activeRequestBall.ball_id}
              onChange={(e) => setSelectedBallId(e.target.value)}
              className="w-full bg-[#1e1f20] border border-[#3c4043] rounded px-2 py-1 text-[11px] text-[#e3e3e3]"
            >
              {custody.requestable_balls.map((b) => (
                <option key={b.ball_id} value={b.ball_id}>
                  {b.title}（审批人：{b.custodian_name}）
                </option>
              ))}
            </select>

            <div className="p-2 rounded bg-[#1e1f20]/80 border border-[#2d2e30] space-y-1 text-[10px]">
              <div className="text-[#c4c7c5] leading-relaxed">
                <span className="text-[#9aa0a6]">用途说明：</span>
                {activeRequestBall.content.slice(0, 60)}
                {activeRequestBall.content.length > 60 ? "..." : ""}
              </div>
              <div className="text-[#fdd663] font-medium flex items-center justify-between">
                <span>审批人：{activeRequestBall.custodian_name}</span>
                <span className="text-[10px] text-[#9aa0a6]">
                  {activeRequestBall.type_label ??
                    TYPE_NAME_MAP[activeRequestBall.ball_type]}
                </span>
              </div>
            </div>

            <div className="space-y-1">
              <div className="text-[10px] text-[#9aa0a6]">使用时长：</div>
              <div className="grid grid-cols-4 gap-1">
                {DURATION_PRESETS.map((preset, idx) => (
                  <button
                    key={preset.label}
                    type="button"
                    onClick={() => setDurationPresetIdx(idx)}
                    className={`py-1 rounded border text-[10px] transition-colors ${durationPresetIdx === idx
                        ? "bg-[#282a2c] border-[#a8c7fa] text-[#a8c7fa] font-medium"
                        : "border-[#2d2e30] text-[#9aa0a6] hover:text-[#e3e3e3]"
                      }`}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-1">
              <div className="text-[10px] text-[#9aa0a6]">常见申请原因：</div>
              <div className="flex flex-wrap gap-1">
                {QUICK_REASONS.map((pill) => (
                  <button
                    key={pill}
                    type="button"
                    onClick={() => setReason(pill)}
                    className={`px-2 py-0.5 rounded-full border text-[10px] transition-colors ${reason === pill
                        ? "bg-[#a8c7fa]/15 border-[#a8c7fa] text-[#a8c7fa]"
                        : "bg-[#1e1f20] border-[#3c4043] text-[#9aa0a6] hover:text-[#e3e3e3]"
                      }`}
                  >
                    {pill}
                  </button>
                ))}
              </div>
            </div>

            <input
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="填写申请说明..."
              className="w-full bg-[#1e1f20] border border-[#3c4043] rounded px-2 py-1 text-[11px] text-[#e3e3e3]"
            />

            <button
              type="submit"
              disabled={busy}
              className="w-full py-1.5 rounded bg-[#a8c7fa] text-[#062e6f] font-medium"
            >
              提交申请
            </button>
          </form>
        )}

        {/* 已开通能力列表 */}
        <div className="space-y-1.5 max-h-60 overflow-y-auto pr-0.5">
          {filteredMountedBalls.map((ball) => {
            const isExpanded = expandedBallId === ball.ball_id;
            const typeText =
              ball.type_label ?? TYPE_NAME_MAP[ball.ball_type] ?? "业务能力";
            const categoryText = ball.business_category ?? "通用业务";
            const promptText =
              ball.quick_use_prompt ||
              `请按《${ball.title}》帮我处理当前业务`;

            return (
              <div
                key={ball.ball_id}
                className={`rounded bg-[#131314] border transition-colors text-[11px] ${isExpanded
                    ? "border-[#a8c7fa]/60"
                    : "border-[#2d2e30] hover:border-[#3c4043]"
                  }`}
              >
                <div className="p-2 space-y-1">
                  <div className="flex items-center justify-between gap-1.5">
                    <button
                      type="button"
                      onClick={() =>
                        setExpandedBallId((prev) =>
                          prev === ball.ball_id ? null : ball.ball_id
                        )
                      }
                      className="flex-1 min-w-0 text-left flex items-center gap-1"
                    >
                      <span className="font-medium text-[#e3e3e3] truncate">
                        {ball.title}
                      </span>
                      {isExpanded ? (
                        <ChevronUp className="w-3.5 h-3.5 text-[#9aa0a6] shrink-0" />
                      ) : (
                        <ChevronDown className="w-3.5 h-3.5 text-[#9aa0a6] shrink-0" />
                      )}
                    </button>
                    {onQuickUse && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onQuickUse(promptText, ball.ball_type);
                        }}
                        className="px-1.5 py-0.5 rounded bg-[#a8c7fa]/15 hover:bg-[#a8c7fa]/25 border border-[#a8c7fa]/40 text-[#a8c7fa] text-[10px] font-medium flex items-center gap-0.5 shrink-0"
                        title="带入对话中立即使用"
                      >
                        <Play className="w-2.5 h-2.5" />
                        <span>去用</span>
                      </button>
                    )}
                  </div>

                  <div className="flex items-center justify-between gap-1 text-[10px] text-[#9aa0a6]">
                    <div className="flex items-center gap-1 truncate">
                      <span className="px-1.5 py-0.2 rounded bg-[#1e1f20] border border-[#2d2e30] text-[#9aa0a6]">
                        {categoryText}
                      </span>
                      <span
                        className={`px-1.5 py-0.2 rounded border ${ball.ball_type === "SKILL"
                            ? "bg-[#81c995]/10 border-[#81c995]/30 text-[#81c995]"
                            : "bg-[#1e1f20] border-[#2d2e30] text-[#a8c7fa]"
                          }`}
                      >
                        {typeText}
                      </span>
                    </div>
                    {ball.is_borrowed ? (
                      <span className="px-1.5 py-0.2 rounded bg-[#fdd663]/15 border border-[#fdd663]/40 text-[9px] text-[#fdd663] flex items-center gap-0.5 shrink-0">
                        <Clock className="w-2.5 h-2.5" />
                        临时授权
                      </span>
                    ) : (
                      <span className="text-[9px] text-[#9aa0a6] shrink-0">
                        长期
                      </span>
                    )}
                  </div>
                </div>

                {/* 展开详情抽屉 */}
                {isExpanded && (
                  <div className="px-2.5 pb-2.5 pt-1.5 border-t border-[#2d2e30] bg-[#18191b] space-y-1.5 text-[10px]">
                    <div className="flex items-center justify-between text-[#9aa0a6]">
                      <span>
                        负责人：
                        <strong className="text-[#e3e3e3]">
                          {ball.custodian_name}
                        </strong>
                      </span>
                      <span>
                        {ball.ball_type === "SKILL" ? "自动工具" : typeText}
                      </span>
                    </div>

                    <div className="text-[#c4c7c5] leading-relaxed bg-[#131314] p-2 rounded border border-[#2d2e30]">
                      <div className="text-[9px] text-[#9aa0a6] mb-0.5">
                        规则说明
                      </div>
                      {ball.content}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {filteredMountedBalls.length === 0 && (
            <div className="p-3 text-center text-[10px] text-[#9aa0a6] bg-[#131314] rounded border border-[#2d2e30]">
              当前分类下暂无已开通能力
            </div>
          )}
        </div>
      </div>

      {/* 2. 我的申请记录 */}
      {custody.my_requests.length > 0 && (
        <div className="space-y-1">
          <div className="px-1 text-[11px] font-medium text-[#9aa0a6]">
            我的申请记录
          </div>
          {custody.my_requests.slice(0, 3).map((r) => (
            <div
              key={r.request_id}
              className="p-2 rounded bg-[#131314] border border-[#2d2e30] text-[10px] flex items-center justify-between gap-2"
            >
              <div className="truncate">
                <div className="text-[#e3e3e3] truncate">
                  {r.ball_title}{" "}
                  <span className="text-[#9aa0a6]">
                    (
                    {r.grant_mode === "LEASE_TTL"
                      ? `临时 ${r.ttl_minutes}分钟`
                      : "长期"}
                    )
                  </span>
                </div>
                <div className="text-[#9aa0a6] truncate">
                  审批人：{r.custodian_name}
                  {r.decision_comment ? ` · ${r.decision_comment}` : ""}
                </div>
              </div>
              <span
                className={`px-1.5 py-0.5 rounded shrink-0 ${r.status === "APPROVED"
                    ? "bg-[#81c995]/15 text-[#81c995]"
                    : r.status === "REJECTED"
                      ? "bg-[#f28b82]/15 text-[#f28b82]"
                      : "bg-[#fdd663]/15 text-[#fdd663]"
                  }`}
              >
                {r.status === "APPROVED"
                  ? "已通过"
                  : r.status === "REJECTED"
                    ? "已驳回"
                    : "待审批"}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* 3. 部门权限管理（主管专属） */}
      {custody.is_custodian_leader && (
        <div className="pt-2.5 border-t border-[#2d2e30] space-y-2">
          <div className="px-1 flex items-center justify-between">
            <span className="flex items-center gap-1 text-[11px] font-medium text-[#a8c7fa]">
              <Sparkles className="w-3 h-3" />
              <span>部门权限管理</span>
            </span>
            <span className="text-[10px] text-[#9aa0a6]">
              管理 {custody.managed_balls.length} 项
            </span>
          </div>

          <div className="grid grid-cols-2 gap-1 p-1 rounded-lg bg-[#131314] border border-[#2d2e30]">
            <button
              type="button"
              onClick={() => setLeaderTab("PENDING")}
              className={`py-1 px-2 rounded text-[10px] font-medium flex items-center justify-center gap-1 transition-colors ${leaderTab === "PENDING"
                  ? "bg-[#fdd663]/20 text-[#fdd663] border border-[#fdd663]/40"
                  : "text-[#9aa0a6] hover:text-[#e3e3e3]"
                }`}
            >
              <ShieldAlert className="w-3 h-3" />
              <span>待我审批 ({pendingList.length})</span>
            </button>
            <button
              type="button"
              onClick={() => setLeaderTab("SUBORDINATES")}
              className={`py-1 px-2 rounded text-[10px] font-medium flex items-center justify-center gap-1 transition-colors ${leaderTab === "SUBORDINATES"
                  ? "bg-[#a8c7fa]/20 text-[#a8c7fa] border border-[#a8c7fa]/40"
                  : "text-[#9aa0a6] hover:text-[#e3e3e3]"
                }`}
            >
              <Sparkles className="w-3 h-3" />
              <span>成员分配 ({subList.length})</span>
            </button>
          </div>

          {/* 待我审批 */}
          {leaderTab === "PENDING" && (
            <div className="space-y-2">
              {pendingList.length === 0 ? (
                <div className="p-3 rounded bg-[#131314] border border-[#2d2e30] text-center text-[10px] text-[#9aa0a6]">
                  暂无待审批申请
                </div>
              ) : (
                pendingList.map((req) => (
                  <div
                    key={req.request_id}
                    className="p-2.5 rounded-lg bg-[#131314] border border-[#fdd663]/40 space-y-2 text-[11px]"
                  >
                    <div className="flex items-center justify-between gap-1">
                      <span className="font-medium text-[#e3e3e3] truncate">
                        {req.requester_name} 申请《{req.ball_title}》
                      </span>
                      <span className="px-1.5 py-0.5 rounded bg-[#282a2c] text-[9px] text-[#fdd663] shrink-0">
                        {req.grant_mode === "LEASE_TTL"
                          ? `临时 ${req.ttl_minutes}分钟`
                          : "长期使用"}
                      </span>
                    </div>

                    <div className="text-[10px] text-[#9aa0a6]">
                      事由：{req.reason}
                    </div>

                    <input
                      value={decisionComments[req.request_id] ?? ""}
                      onChange={(e) =>
                        setDecisionComments((prev) => ({
                          ...prev,
                          [req.request_id]: e.target.value,
                        }))
                      }
                      placeholder="填写审批意见（选填）..."
                      className="w-full bg-[#1e1f20] border border-[#3c4043] rounded px-2 py-1 text-[10px] text-[#e3e3e3]"
                    />

                    <div className="flex gap-1.5">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => handleLeaderDecide(req.request_id, true)}
                        className="flex-1 py-1 rounded bg-[#a8c7fa] text-[#062e6f] font-medium flex items-center justify-center gap-1"
                      >
                        <Check className="w-3 h-3" />
                        批准开通
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          handleLeaderDecide(req.request_id, false)
                        }
                        className="px-3 py-1 rounded bg-[#f28b82]/15 border border-[#f28b82]/40 text-[#f28b82] font-medium flex items-center justify-center gap-1"
                      >
                        <X className="w-3 h-3" />
                        驳回
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {/* 成员分配 */}
          {leaderTab === "SUBORDINATES" && (
            <div className="p-2.5 rounded-lg bg-[#131314] border border-[#2d2e30] space-y-2 text-[11px]">
              {subList.length === 0 ? (
                <div className="text-center text-[10px] text-[#9aa0a6] py-2">
                  当前名下暂无直管成员
                </div>
              ) : (
                <>
                  <select
                    value={targetSubSlot || subList[0]?.slot_id || ""}
                    onChange={(e) => setTargetSubSlot(e.target.value)}
                    className="w-full bg-[#1e1f20] border border-[#3c4043] rounded px-2 py-1 text-[11px] text-[#e3e3e3]"
                  >
                    {subList.map((sub) => (
                      <option key={sub.slot_id} value={sub.slot_id}>
                        部门成员：{sub.name}（{sub.title}）
                      </option>
                    ))}
                  </select>

                  <div className="grid grid-cols-2 gap-1">
                    <button
                      type="button"
                      onClick={() => setDirectGrantMode("PERMANENT")}
                      className={`py-1 rounded border text-[10px] transition-colors ${directGrantMode === "PERMANENT"
                          ? "bg-[#282a2c] border-[#a8c7fa] text-[#a8c7fa] font-medium"
                          : "border-[#2d2e30] text-[#9aa0a6]"
                        }`}
                    >
                      长期开通
                    </button>
                    <button
                      type="button"
                      onClick={() => setDirectGrantMode("LEASE_TTL")}
                      className={`py-1 rounded border text-[10px] transition-colors ${directGrantMode === "LEASE_TTL"
                          ? "bg-[#282a2c] border-[#fdd663] text-[#fdd663] font-medium"
                          : "border-[#2d2e30] text-[#9aa0a6]"
                        }`}
                    >
                      临时 2小时
                    </button>
                  </div>

                  <div className="flex gap-1">
                    <select
                      value={
                        grantBallId || custody.managed_balls[0]?.ball_id || ""
                      }
                      onChange={(e) => setGrantBallId(e.target.value)}
                      className="flex-1 bg-[#1e1f20] border border-[#3c4043] rounded px-2 py-1 text-[10px] text-[#e3e3e3]"
                    >
                      {custody.managed_balls.map((b) => (
                        <option key={b.ball_id} value={b.ball_id}>
                          {b.title}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={handleDirectGrant}
                      className="px-2.5 py-1 rounded bg-[#a8c7fa] text-[#062e6f] font-medium text-[10px] shrink-0"
                    >
                      开通
                    </button>
                  </div>

                  {(() => {
                    const activeSub =
                      subList.find(
                        (s) =>
                          s.slot_id ===
                          (targetSubSlot || subList[0]?.slot_id)
                      ) ?? subList[0];
                    if (!activeSub) return null;
                    const borrowedSet = new Set(
                      (activeSub.borrowed_balls ?? []).map((b) => b.ball_id)
                    );
                    return (
                      <div className="pt-1.5 border-t border-[#2d2e30] space-y-1.5">
                        <div className="flex items-center justify-between text-[10px] text-[#9aa0a6]">
                          <span>
                            {activeSub.name} 已开通能力 (
                            {activeSub.effective_ball_ids.length})
                          </span>
                          <span className="text-[9px]">
                            长期 {activeSub.permanent_ball_ids.length} · 临时{" "}
                            {borrowedSet.size}
                          </span>
                        </div>
                        <div className="space-y-1">
                          {activeSub.effective_ball_ids.map((bid) => {
                            const isBorrowed = borrowedSet.has(bid);
                            const labelTitle = ballTitleById.get(bid) ?? bid;
                            return (
                              <div
                                key={bid}
                                className="px-2 py-1 rounded bg-[#1e1f20] border border-[#2d2e30] flex items-center justify-between gap-1 text-[10px]"
                              >
                                <div className="flex items-center gap-1.5 truncate">
                                  <span className="text-[#e3e3e3] truncate">
                                    {labelTitle}
                                  </span>
                                  {isBorrowed ? (
                                    <span className="px-1 py-0.2 rounded bg-[#fdd663]/15 border border-[#fdd663]/40 text-[9px] text-[#fdd663] shrink-0">
                                      临时
                                    </span>
                                  ) : (
                                    <span className="px-1 py-0.2 rounded bg-[#a8c7fa]/15 border border-[#a8c7fa]/40 text-[9px] text-[#a8c7fa] shrink-0">
                                      长期
                                    </span>
                                  )}
                                </div>
                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() =>
                                    handleRevoke(activeSub.slot_id, bid)
                                  }
                                  title="收回权限"
                                  className="px-1.5 py-0.5 rounded bg-[#f28b82]/15 hover:bg-[#f28b82]/25 text-[#f28b82] text-[9px] flex items-center gap-0.5 shrink-0"
                                >
                                  <Trash2 className="w-2.5 h-2.5" />
                                  <span>收回</span>
                                </button>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })()}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

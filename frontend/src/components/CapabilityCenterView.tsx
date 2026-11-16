import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Archive,
  Check,
  GitBranch,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import {
  autoSweepLifecycle,
  fetchLifecycleCatalog,
  fetchLifecycleHealthScan,
  incubateOrSplitModule,
  reapOrMergeModule,
  requestBallAccess,
  restoreArchivedModule,
} from "../api";
import {
  AccountDirectoryEntry,
  CustodyBallItem,
  LifecycleCatalogResponse,
  LifecycleHealthScanResponse,
} from "../types";

interface Props {
  account: AccountDirectoryEntry;
  onQuickUse: (promptText: string, ballType: CustodyBallItem["ball_type"]) => void;
  onRefreshAll: () => Promise<void>;
  onToast: (text: string, kind?: "ok" | "err") => void;
}

type StatusFilter = "MOUNTED" | "REQUESTABLE" | "ALL_ACTIVE" | "ARCHIVED";
type TypeFilter = "ALL" | "DATA" | "SKILL" | "AUTHORITY" | "REDLINE";
type DrawerMode = "incubate" | "cleanup" | null;
type IncubateTab = "from_policy" | "split_existing";

const TYPE_FILTERS: Array<{ key: TypeFilter; label: string }> = [
  { key: "ALL", label: "全部" },
  { key: "DATA", label: "业务资料" },
  { key: "SKILL", label: "计算工具" },
  { key: "AUTHORITY", label: "审批权限" },
  { key: "REDLINE", label: "风控底线" },
];

const SAMPLE_RULE_TEXT =
  "【华东特钢大客户阶梯运费规范】首重 3 公斤内 10 元，超过 3 公斤部分每公斤加收 4 元，单笔订单满 500 元免收运费；单笔减免超 200 元须主管审批；严禁向外部客户透露车队真实成本底价。";

export const CapabilityCenterView: React.FC<Props> = ({
  account,
  onQuickUse,
  onRefreshAll,
  onToast,
}) => {
  const [catalog, setCatalog] = useState<LifecycleCatalogResponse | null>(null);
  const [health, setHealth] = useState<LifecycleHealthScanResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Filters
  const [selectedCategory, setSelectedCategory] = useState<string>("全部");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("ALL");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL_ACTIVE");
  const [searchQuery, setSearchQuery] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Inline request access
  const [requestingBallId, setRequestingBallId] = useState<string | null>(null);
  const [requestMode, setRequestMode] = useState<"2h" | "8h" | "perm">("2h");

  // Drawers
  const [drawer, setDrawer] = useState<DrawerMode>(null);
  const [incubateTab, setIncubateTab] = useState<IncubateTab>("from_policy");
  const [policyInput, setPolicyInput] = useState(SAMPLE_RULE_TEXT);
  const [splitTargetId, setSplitTargetId] = useState("");

  const canGovern = account.role_view === "manager" || account.role_view === "boss";

  const loadData = useCallback(async () => {
    try {
      const [catRes, healthRes] = await Promise.all([
        fetchLifecycleCatalog(account.user_id),
        canGovern ? fetchLifecycleHealthScan(account.user_id) : Promise.resolve(null),
      ]);
      setCatalog(catRes);
      setHealth(healthRes);
      if (catRes.modules.length > 0) {
        setSplitTargetId((prev) =>
          prev && catRes.modules.some((m) => m.ball_id === prev)
            ? prev
            : catRes.modules[0].ball_id
        );
      }
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "加载能力目录失败", "err");
    } finally {
      setLoading(false);
    }
  }, [account.user_id, canGovern, onToast]);

  useEffect(() => {
    setLoading(true);
    loadData();
  }, [loadData]);

  const sourceList = useMemo(() => {
    if (!catalog) return [];
    if (statusFilter === "ARCHIVED") return catalog.archived_modules ?? [];
    if (statusFilter === "MOUNTED") {
      return catalog.modules.filter((m) => m.is_mounted);
    }
    if (statusFilter === "REQUESTABLE") {
      return catalog.modules.filter(
        (m) => !m.is_mounted && m.ball_type !== "REDLINE"
      );
    }
    return catalog.modules;
  }, [catalog, statusFilter]);

  const filteredModules = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return sourceList.filter((m) => {
      if (
        selectedCategory !== "全部" &&
        m.business_category !== selectedCategory
      ) {
        return false;
      }
      if (typeFilter !== "ALL" && m.ball_type !== typeFilter) {
        return false;
      }
      if (q) {
        const hay = `${m.title} ${m.content} ${m.business_category ?? ""} ${m.type_label ?? ""
          } ${(m.domain_tags ?? []).join(" ")}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [sourceList, selectedCategory, typeFilter, searchQuery]);

  const handleSubmitRequest = async (item: CustodyBallItem) => {
    setBusyId(item.ball_id);
    try {
      const grant_mode = requestMode === "perm" ? "PERMANENT" : "LEASE_TTL";
      const ttl_minutes = requestMode === "8h" ? 8 * 60 : 120;
      await requestBallAccess({
        requester_id: account.user_id,
        ball_id: item.ball_id,
        grant_mode,
        ttl_minutes,
        reason: `业务处理需使用《${item.title}》`,
      });
      setRequestingBallId(null);
      await Promise.all([loadData(), onRefreshAll()]);
      onToast(`已向负责人 ${item.custodian_name} 提交《${item.title}》开通申请`);
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "申请提交失败", "err");
    } finally {
      setBusyId(null);
    }
  };

  const handleIncubate = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusyId("incubate");
    try {
      const res = await incubateOrSplitModule(
        incubateTab === "from_policy"
          ? {
            actor_user_id: account.user_id,
            raw_policy_text: policyInput.trim(),
          }
          : {
            actor_user_id: account.user_id,
            target_ball_id: splitTargetId,
          }
      );
      await Promise.all([loadData(), onRefreshAll()]);
      const count = res.created_modules?.length ?? 0;
      onToast(
        incubateTab === "from_policy"
          ? `已从制度规则拆解并归类生成 ${count} 项能力模块`
          : `已将选中模块一分为二拆分为 ${count} 个独立子模块`
      );
      setDrawer(null);
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "孵化拆分失败", "err");
    } finally {
      setBusyId(null);
    }
  };

  const handleSplitSingle = async (ball: CustodyBallItem) => {
    setBusyId(ball.ball_id);
    try {
      await incubateOrSplitModule({
        actor_user_id: account.user_id,
        target_ball_id: ball.ball_id,
      });
      await Promise.all([loadData(), onRefreshAll()]);
      onToast(`已将《${ball.title}》一分为二拆成两个职责清晰的子模块`);
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "拆分失败", "err");
    } finally {
      setBusyId(null);
    }
  };

  const handleArchiveSingle = async (ball: CustodyBallItem) => {
    setBusyId(ball.ball_id);
    try {
      const res = await reapOrMergeModule({
        actor_user_id: account.user_id,
        action: "ARCHIVE",
        target_ball_id: ball.ball_id,
        reason: "管理员手动淘汰下线",
      });
      await Promise.all([loadData(), onRefreshAll()]);
      onToast(res.summary || `已将《${ball.title}》淘汰归档`);
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "淘汰归档失败", "err");
    } finally {
      setBusyId(null);
    }
  };

  const handleRestoreSingle = async (ball: CustodyBallItem) => {
    setBusyId(ball.ball_id);
    try {
      const res = await restoreArchivedModule({
        actor_user_id: account.user_id,
        ball_id: ball.ball_id,
      });
      await Promise.all([loadData(), onRefreshAll()]);
      onToast(res.summary || `已恢复启用《${ball.title}》`);
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "恢复失败", "err");
    } finally {
      setBusyId(null);
    }
  };

  const handleMergeCandidate = async (
    targetBallId: string,
    mergeIntoBallId: string
  ) => {
    setBusyId(targetBallId);
    try {
      const res = await reapOrMergeModule({
        actor_user_id: account.user_id,
        action: "MERGE",
        target_ball_id: targetBallId,
        merge_into_ball_id: mergeIntoBallId,
        reason: "清理重复模块并合并保留新版",
      });
      await Promise.all([loadData(), onRefreshAll()]);
      onToast(res.summary || "已完成重复模块合并与岗位迁移");
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "合并失败", "err");
    } finally {
      setBusyId(null);
    }
  };

  const handleAutoSweep = async () => {
    setBusyId("auto_sweep");
    try {
      const res = await autoSweepLifecycle({ actor_user_id: account.user_id });
      await Promise.all([loadData(), onRefreshAll()]);
      onToast(res.summary || "一键清理完成");
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "一键清理失败", "err");
    } finally {
      setBusyId(null);
    }
  };

  const handleQuickForgeTool = async (rawText: string, candId: string) => {
    setBusyId(candId);
    try {
      const res = await incubateOrSplitModule({
        actor_user_id: account.user_id,
        raw_policy_text: rawText,
      });
      await Promise.all([loadData(), onRefreshAll()]);
      onToast(
        `已生成自动计算工具等 ${res.created_modules?.length ?? 1} 项能力模块`
      );
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : "生成失败", "err");
    } finally {
      setBusyId(null);
    }
  };

  const categoryTabs = catalog?.categories_summary ?? [];
  const totalCleanupCount =
    (health?.reaper_count ?? 0) + (health?.midwife_count ?? 0);

  return (
    <div className="h-full flex flex-col bg-[#131314] text-[#e3e3e3] overflow-hidden">
      {/* 1. 顶部标题与双核心操作按钮（新增/拆分 + 清理冗余） */}
      <div className="px-6 py-4 bg-[#18191b] border-b border-[#2d2e30] flex flex-wrap items-center justify-between gap-4 shrink-0">
        <div>
          <h1 className="text-base font-medium text-[#e3e3e3]">
            能力目录与维护
          </h1>
          <p className="text-xs text-[#9aa0a6] mt-0.5">
            按业务部门分类查找资料、计算工具与权限；支持拆分新增业务、清理过时重复项
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={!canGovern}
            title={canGovern ? undefined : "能力维护需管理权限"}
            onClick={() =>
              setDrawer((prev) => (prev === "incubate" ? null : "incubate"))
            }
            className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 border transition ${drawer === "incubate"
                ? "bg-[#a8c7fa] text-[#062e6f] border-[#a8c7fa]"
                : "bg-[#282a2c] hover:bg-[#35373a] text-[#e3e3e3] border-[#3c4043]"
              }`}
          >
            <Plus className="w-3.5 h-3.5" />
            <span>新增 / 拆分能力</span>
          </button>

          <button
            type="button"
            disabled={!canGovern}
            title={canGovern ? undefined : "能力维护需管理权限"}
            onClick={() =>
              setDrawer((prev) => (prev === "cleanup" ? null : "cleanup"))
            }
            className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 border transition ${drawer === "cleanup"
                ? "bg-[#fdd663] text-[#131314] border-[#fdd663]"
                : "bg-[#282a2c] hover:bg-[#35373a] text-[#fdd663] border-[#fdd663]/40"
              }`}
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>
              清理冗余项{totalCleanupCount > 0 ? ` (${totalCleanupCount})` : ""}
            </span>
          </button>

          <button
            type="button"
            onClick={() => loadData()}
            className="p-1.5 rounded-lg bg-[#282a2c] hover:bg-[#35373a] border border-[#3c4043] text-[#9aa0a6] hover:text-[#e3e3e3]"
            title="刷新目录"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* 2. 内联抽屉 A：能力孵化（新增与拆分） */}
      {drawer === "incubate" && (
        <div className="px-6 py-4 bg-[#1e1f20] border-b border-[#2d2e30] space-y-3 shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setIncubateTab("from_policy")}
                className={`px-3 py-1 rounded-md text-xs font-medium border transition ${incubateTab === "from_policy"
                    ? "bg-[#a8c7fa]/15 border-[#a8c7fa] text-[#a8c7fa]"
                    : "bg-[#131314] border-[#2d2e30] text-[#9aa0a6]"
                  }`}
              >
                从新制度生成模块
              </button>
              <button
                type="button"
                onClick={() => setIncubateTab("split_existing")}
                className={`px-3 py-1 rounded-md text-xs font-medium border transition ${incubateTab === "split_existing"
                    ? "bg-[#a8c7fa]/15 border-[#a8c7fa] text-[#a8c7fa]"
                    : "bg-[#131314] border-[#2d2e30] text-[#9aa0a6]"
                  }`}
              >
                拆分现有复杂模块
              </button>
            </div>
            <button
              type="button"
              onClick={() => setDrawer(null)}
              className="p-1 rounded hover:bg-[#282a2c] text-[#9aa0a6]"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <form onSubmit={handleIncubate} className="space-y-2.5">
            {incubateTab === "from_policy" ? (
              <>
                <textarea
                  rows={3}
                  required
                  value={policyInput}
                  onChange={(e) => setPolicyInput(e.target.value)}
                  placeholder="粘贴新的业务规则、计算公式、审批额度或风控要求，系统会自动拆解为业务资料、计算工具和权限模块并归好类..."
                  className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] outline-none rounded-lg p-3 text-xs text-[#e3e3e3]"
                />
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-[#9aa0a6]">
                    自动按业务分类生成原子模块，有计算公式时自动编出可用工具
                  </span>
                  <button
                    type="submit"
                    disabled={busyId === "incubate" || !policyInput.trim()}
                    className="px-4 py-1.5 rounded-lg bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] text-xs font-medium flex items-center gap-1.5 disabled:opacity-40"
                  >
                    {busyId === "incubate" ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Sparkles className="w-3.5 h-3.5" />
                    )}
                    <span>生成并自动归类</span>
                  </button>
                </div>
              </>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <select
                  value={splitTargetId}
                  onChange={(e) => setSplitTargetId(e.target.value)}
                  className="flex-1 min-w-[260px] bg-[#131314] border border-[#3c4043] rounded-lg px-3 py-2 text-xs text-[#e3e3e3]"
                >
                  {(catalog?.modules ?? []).map((m) => (
                    <option key={m.ball_id} value={m.ball_id}>
                      [{m.business_category} · {m.type_label}] {m.title}
                    </option>
                  ))}
                </select>
                <button
                  type="submit"
                  disabled={busyId === "incubate" || !splitTargetId}
                  className="px-4 py-2 rounded-lg bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] text-xs font-medium flex items-center gap-1.5 disabled:opacity-40"
                >
                  {busyId === "incubate" ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <GitBranch className="w-3.5 h-3.5" />
                  )}
                  <span>一分为二拆分</span>
                </button>
              </div>
            )}
          </form>
        </div>
      )}

      {/* 3. 内联抽屉 B：能力清理与健康体检（死神 + 补充优化） */}
      {drawer === "cleanup" && (
        <div className="px-6 py-4 bg-[#1e1f20] border-b border-[#2d2e30] space-y-3 shrink-0 max-h-72 overflow-y-auto">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs font-medium text-[#e3e3e3]">
              能力健康体检：识别重复、长期闲置与过重模块
            </div>
            <div className="flex items-center gap-2">
              {canGovern && (
                <button
                  type="button"
                  disabled={busyId === "auto_sweep"}
                  onClick={handleAutoSweep}
                  className="px-3 py-1 rounded-md bg-[#fdd663] hover:bg-[#fee082] text-[#131314] text-xs font-medium flex items-center gap-1.5 disabled:opacity-40"
                >
                  {busyId === "auto_sweep" ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Check className="w-3.5 h-3.5" />
                  )}
                  <span>一键清理重复与过期项</span>
                </button>
              )}
              <button
                type="button"
                onClick={() => setDrawer(null)}
                className="p-1 rounded hover:bg-[#282a2c] text-[#9aa0a6]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {totalCleanupCount === 0 ? (
            <div className="p-4 rounded-lg bg-[#131314] border border-[#2d2e30] text-center text-xs text-[#81c995]">
              当前能力库结构健康，暂无重复模块、过期授权或积压冗余项
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
              {(health?.reaper_candidates ?? []).map((cand) => (
                <div
                  key={cand.candidate_id}
                  className="p-3 rounded-lg bg-[#131314] border border-[#3c4043] flex flex-col justify-between gap-2"
                >
                  <div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] font-medium text-[#fdd663]">
                        {cand.kind_label}
                      </span>
                      {cand.business_category && (
                        <span className="text-[10px] text-[#9aa0a6]">
                          {cand.business_category}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-[#e3e3e3] mt-1 leading-relaxed">
                      {cand.summary}
                    </div>
                  </div>
                  {canGovern && (
                    <div className="flex items-center justify-end gap-2 pt-1">
                      {cand.kind === "DUPLICATE_SIMILAR" &&
                        cand.merge_into_ball_id && (
                          <button
                            type="button"
                            disabled={busyId === cand.target_ball_id}
                            onClick={() =>
                              handleMergeCandidate(
                                cand.target_ball_id,
                                cand.merge_into_ball_id!
                              )
                            }
                            className="px-2.5 py-1 rounded bg-[#a8c7fa] text-[#062e6f] text-[11px] font-medium"
                          >
                            合并保留新版
                          </button>
                        )}
                      {cand.kind !== "EXPIRED_LEASE" && (
                        <button
                          type="button"
                          disabled={busyId === cand.target_ball_id}
                          onClick={async () => {
                            setBusyId(cand.target_ball_id);
                            try {
                              await reapOrMergeModule({
                                actor_user_id: account.user_id,
                                action: "ARCHIVE",
                                target_ball_id: cand.target_ball_id,
                                reason: cand.kind_label,
                              });
                              await Promise.all([loadData(), onRefreshAll()]);
                              onToast(`已将《${cand.target_title}》下线归档`);
                            } catch (err: unknown) {
                              onToast(
                                err instanceof Error ? err.message : "下线失败",
                                "err"
                              );
                            } finally {
                              setBusyId(null);
                            }
                          }}
                          className="px-2.5 py-1 rounded bg-[#282a2c] hover:bg-[#35373a] border border-[#3c4043] text-[#f28b82] text-[11px]"
                        >
                          直接下线
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ))}

              {(health?.midwife_candidates ?? []).map((cand) => (
                <div
                  key={cand.candidate_id}
                  className="p-3 rounded-lg bg-[#131314] border border-[#2d2e30] flex flex-col justify-between gap-2"
                >
                  <div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] font-medium text-[#81c995]">
                        {cand.kind_label}
                      </span>
                      {cand.business_category && (
                        <span className="text-[10px] text-[#9aa0a6]">
                          {cand.business_category}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-[#e3e3e3] mt-1 leading-relaxed">
                      {cand.summary}
                    </div>
                  </div>
                  {canGovern && (
                    <div className="flex items-center justify-end pt-1">
                      {cand.kind === "SPLIT_BLOATED" ? (
                        <button
                          type="button"
                          disabled={busyId === cand.target_ball_id}
                          onClick={async () => {
                            setBusyId(cand.target_ball_id);
                            try {
                              await incubateOrSplitModule({
                                actor_user_id: account.user_id,
                                target_ball_id: cand.target_ball_id,
                              });
                              await Promise.all([loadData(), onRefreshAll()]);
                              onToast(`已拆分《${cand.target_title}》`);
                            } catch (err: unknown) {
                              onToast(
                                err instanceof Error ? err.message : "拆分失败",
                                "err"
                              );
                            } finally {
                              setBusyId(null);
                            }
                          }}
                          className="px-2.5 py-1 rounded bg-[#282a2c] hover:bg-[#35373a] border border-[#3c4043] text-[#a8c7fa] text-[11px]"
                        >
                          一分为二拆分
                        </button>
                      ) : (
                        <button
                          type="button"
                          disabled={busyId === cand.candidate_id}
                          onClick={() =>
                            handleQuickForgeTool(
                              cand.raw_policy_text || cand.target_title,
                              cand.candidate_id
                            )
                          }
                          className="px-2.5 py-1 rounded bg-[#81c995]/20 border border-[#81c995]/50 text-[#81c995] text-[11px]"
                        >
                          生成计算工具
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 4. 双层清爽筛选栏：业务分类 Tab + 性质筛选 + 状态切换 + 搜索框 */}
      <div className="px-6 py-3 bg-[#131314] border-b border-[#2d2e30] space-y-2.5 shrink-0">
        {/* 第一行：5 大业务分类 */}
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setSelectedCategory("全部")}
            className={`px-3 py-1 rounded-full text-xs border transition ${selectedCategory === "全部"
                ? "bg-[#a8c7fa] text-[#062e6f] border-[#a8c7fa] font-medium"
                : "bg-[#1e1f20] hover:bg-[#282a2c] border-[#2d2e30] text-[#9aa0a6]"
              }`}
          >
            全部 ({sourceList.length})
          </button>
          {categoryTabs.map((cat) => (
            <button
              key={cat.category}
              type="button"
              onClick={() => setSelectedCategory(cat.category)}
              className={`px-3 py-1 rounded-full text-xs border transition ${selectedCategory === cat.category
                  ? "bg-[#a8c7fa] text-[#062e6f] border-[#a8c7fa] font-medium"
                  : "bg-[#1e1f20] hover:bg-[#282a2c] border-[#2d2e30] text-[#e3e3e3]"
                }`}
            >
              {cat.category} ({cat.count})
            </button>
          ))}
        </div>

        {/* 第二行：性质筛选 + 状态切换 + 搜索框 */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1 bg-[#1e1f20] p-0.5 rounded-lg border border-[#2d2e30]">
              {TYPE_FILTERS.map((tf) => (
                <button
                  key={tf.key}
                  type="button"
                  onClick={() => setTypeFilter(tf.key)}
                  className={`px-2.5 py-1 rounded-md text-[11px] transition ${typeFilter === tf.key
                      ? "bg-[#282a2c] text-[#e3e3e3] font-medium"
                      : "text-[#9aa0a6] hover:text-[#e3e3e3]"
                    }`}
                >
                  {tf.label}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-1 bg-[#1e1f20] p-0.5 rounded-lg border border-[#2d2e30]">
              {[
                { key: "ALL_ACTIVE" as StatusFilter, label: "全部在用" },
                { key: "MOUNTED" as StatusFilter, label: "我已开通" },
                { key: "REQUESTABLE" as StatusFilter, label: "可申请" },
                {
                  key: "ARCHIVED" as StatusFilter,
                  label: `已淘汰归档 (${catalog?.archived_count ?? 0})`,
                },
              ].map((st) => (
                <button
                  key={st.key}
                  type="button"
                  onClick={() => setStatusFilter(st.key)}
                  className={`px-2.5 py-1 rounded-md text-[11px] transition ${statusFilter === st.key
                      ? "bg-[#282a2c] text-[#a8c7fa] font-medium"
                      : "text-[#9aa0a6] hover:text-[#e3e3e3]"
                    }`}
                >
                  {st.label}
                </button>
              ))}
            </div>
          </div>

          <div className="relative w-64">
            <Search className="w-3.5 h-3.5 text-[#9aa0a6] absolute left-3 top-2" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索名称或关键词..."
              className="w-full bg-[#1e1f20] border border-[#3c4043] focus:border-[#a8c7fa] outline-none rounded-lg pl-8 pr-3 py-1.5 text-xs text-[#e3e3e3]"
            />
          </div>
        </div>
      </div>

      {/* 5. 能力卡片网格 */}
      <div className="flex-1 overflow-y-auto p-6">
        {loading ? (
          <div className="h-48 flex items-center justify-center text-xs text-[#9aa0a6] gap-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>正在加载能力目录...</span>
          </div>
        ) : filteredModules.length === 0 ? (
          <div className="h-48 flex flex-col items-center justify-center text-xs text-[#9aa0a6] gap-2">
            <Archive className="w-6 h-6 text-[#5f6368]" />
            <span>当前筛选条件下暂无匹配的能力模块</span>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filteredModules.map((mod) => {
              const isExpanded = expandedId === mod.ball_id;
              const isRequestOpen = requestingBallId === mod.ball_id;
              const typeBadgeColor =
                mod.ball_type === "SKILL"
                  ? "bg-[#81c995]/15 text-[#81c995] border-[#81c995]/30"
                  : mod.ball_type === "AUTHORITY"
                    ? "bg-[#fdd663]/15 text-[#fdd663] border-[#fdd663]/30"
                    : mod.ball_type === "REDLINE"
                      ? "bg-[#f28b82]/15 text-[#f28b82] border-[#f28b82]/30"
                      : "bg-[#a8c7fa]/15 text-[#a8c7fa] border-[#a8c7fa]/30";

              return (
                <div
                  key={mod.ball_id}
                  className="p-4 rounded-xl bg-[#1e1f20] border border-[#2d2e30] hover:border-[#3c4043] flex flex-col justify-between gap-3 transition"
                >
                  <div className="space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="text-sm font-medium text-[#e3e3e3] leading-snug">
                        {mod.title}
                      </h3>
                      <span
                        className={`px-2 py-0.5 rounded-md text-[10px] border shrink-0 ${typeBadgeColor}`}
                      >
                        {mod.type_label || "业务资料"}
                      </span>
                    </div>

                    <div className="text-[11px] text-[#9aa0a6] flex flex-wrap items-center gap-2">
                      <span>{mod.business_category || "风控与管理"}</span>
                      <span>·</span>
                      <span>负责人：{mod.custodian_name}</span>
                      {mod.is_mounted && (
                        <span className="text-[#81c995]">
                          · {mod.is_borrowed ? "临时授权中" : "已开通"}
                        </span>
                      )}
                    </div>

                    <p
                      onClick={() =>
                        setExpandedId(isExpanded ? null : mod.ball_id)
                      }
                      className={`text-xs text-[#c4c7c5] leading-relaxed cursor-pointer ${isExpanded ? "" : "line-clamp-2"
                        }`}
                      title="点击展开或收起完整说明"
                    >
                      {mod.content}
                    </p>
                  </div>

                  <div className="space-y-2 pt-2 border-t border-[#2d2e30]">
                    {isRequestOpen && (
                      <div className="p-2.5 rounded-lg bg-[#131314] border border-[#a8c7fa]/40 space-y-2">
                        <div className="flex items-center justify-between text-[11px] text-[#9aa0a6]">
                          <span>选择使用期限：</span>
                          <div className="flex items-center gap-1">
                            {[
                              { k: "2h" as const, label: "2小时" },
                              { k: "8h" as const, label: "8小时" },
                              { k: "perm" as const, label: "长期" },
                            ].map((opt) => (
                              <button
                                key={opt.k}
                                type="button"
                                onClick={() => setRequestMode(opt.k)}
                                className={`px-2 py-0.5 rounded border text-[10px] ${requestMode === opt.k
                                    ? "bg-[#a8c7fa] text-[#062e6f] border-[#a8c7fa] font-medium"
                                    : "border-[#3c4043] text-[#e3e3e3]"
                                  }`}
                              >
                                {opt.label}
                              </button>
                            ))}
                          </div>
                        </div>
                        <div className="flex items-center justify-end gap-2">
                          <button
                            type="button"
                            onClick={() => setRequestingBallId(null)}
                            className="px-2 py-1 text-[11px] text-[#9aa0a6]"
                          >
                            取消
                          </button>
                          <button
                            type="button"
                            disabled={busyId === mod.ball_id}
                            onClick={() => handleSubmitRequest(mod)}
                            className="px-3 py-1 rounded bg-[#a8c7fa] text-[#062e6f] text-[11px] font-medium"
                          >
                            确认申请
                          </button>
                        </div>
                      </div>
                    )}

                    <div className="flex items-center justify-between gap-2">
                      {statusFilter === "ARCHIVED" ? (
                        canGovern ? (
                          <button
                            type="button"
                            disabled={busyId === mod.ball_id}
                            onClick={() => handleRestoreSingle(mod)}
                            className="px-3 py-1.5 rounded-lg bg-[#81c995]/15 hover:bg-[#81c995]/25 border border-[#81c995]/40 text-[#81c995] text-xs font-medium flex items-center gap-1"
                          >
                            <RotateCcw className="w-3.5 h-3.5" />
                            <span>恢复启用</span>
                          </button>
                        ) : (
                          <span className="text-[11px] text-[#9aa0a6]">
                            已停用归档
                          </span>
                        )
                      ) : mod.is_mounted ? (
                        <button
                          type="button"
                          onClick={() =>
                            onQuickUse(
                              mod.quick_use_prompt ||
                              `请帮我使用《${mod.title}》处理当前业务`,
                              mod.ball_type
                            )
                          }
                          className="px-3 py-1.5 rounded-lg bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] text-xs font-medium flex items-center gap-1"
                        >
                          <Play className="w-3 h-3" />
                          <span>立即使用</span>
                        </button>
                      ) : mod.ball_type !== "REDLINE" ? (
                        <button
                          type="button"
                          onClick={() =>
                            setRequestingBallId(
                              isRequestOpen ? null : mod.ball_id
                            )
                          }
                          className="px-3 py-1.5 rounded-lg bg-[#282a2c] hover:bg-[#35373a] border border-[#3c4043] text-[#a8c7fa] text-xs font-medium"
                        >
                          申请开通
                        </button>
                      ) : (
                        <span className="text-[11px] text-[#9aa0a6]">
                          仅管理层可见
                        </span>
                      )}

                      {statusFilter !== "ARCHIVED" && canGovern && (
                        <div className="flex items-center gap-2 text-[11px]">
                          <button
                            type="button"
                            disabled={busyId === mod.ball_id}
                            onClick={() => handleSplitSingle(mod)}
                            className="text-[#9aa0a6] hover:text-[#a8c7fa] transition"
                          >
                            一分为二
                          </button>
                          <button
                            type="button"
                            disabled={busyId === mod.ball_id}
                            onClick={() => handleArchiveSingle(mod)}
                            className="text-[#9aa0a6] hover:text-[#f28b82] transition"
                          >
                            淘汰下线
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

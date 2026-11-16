import React, { useEffect, useState } from "react";
import {
  Archive,
  CheckCircle2,
  ChevronDown,
  Database,
  Loader2,
  Rocket,
  ShieldAlert,
  Sparkles,
  UserCheck,
  Users,
  X,
} from "lucide-react";
import {
  deployEnterpriseBlueprint,
  fetchAuthAccounts,
  fetchGenesisTemplates,
} from "../api";
import {
  AccountDirectoryEntry,
  CustodyOverviewPayload,
  EnterpriseDeployResponse,
  GenesisTemplateItem,
  LLMTelemetrySnapshot,
  UnifiedOverviewPayload,
} from "../types";
import { AutonomousCommandStudioModal } from "./AutonomousCommandStudioModal";
import { EnterpriseIngestSnapshotModal } from "./EnterpriseIngestSnapshotModal";
import { RedBlueCrucibleModal } from "./RedBlueCrucibleModal";
import { SwarmWarRoomModal } from "./SwarmWarRoomModal";

interface Props {
  account: AccountDirectoryEntry;
  overview: UnifiedOverviewPayload | null;
  custody: CustodyOverviewPayload | null;
  telemetry: LLMTelemetrySnapshot | null;
  onRefresh: () => Promise<void>;
  onSwitchAccount: (nextAccount: AccountDirectoryEntry) => void;
  onToast: (text: string, kind?: "ok" | "err") => void;
}

const FALLBACK_TEMPLATES: GenesisTemplateItem[] = [
  {
    template_id: "tpl_zambia_copper",
    enterprise_name: "赞比亚跨境铜矿陆运车队",
    industry: "跨境矿业物流",
    business_description:
      "主营赞比亚谦比希铜矿至达累斯萨拉姆港/德班港的粗铜与阴极铜跨境重卡陆运。核心制度：1）吨公里阶梯运价与柴油单价浮动联动核算（基础运价 0.12 USD/吨公里，超出 1500 公里部分按 0.095 USD/吨公里计费，返程空驶补贴 350 USD）；2）刚果(金)/赞比亚边境清关单证（T1过境单、矿产原产地证、磅单毛重偏差≤0.3%）；3）单车货值超 25 万美元或改道非标路线必须车队调度主管特批；4）严禁私自透露车队GPS实时坐标、押运安保排班及矿山底价协议。",
  },
  {
    template_id: "tpl_crossborder_mcn",
    enterprise_name: "跨境独立站与MCN机构",
    industry: "出海电商与达人矩阵",
    business_description:
      "主营欧美TikTok达人带货矩阵与DTC独立站供应链履约。核心制度：1）达人坑位费与CPS阶梯分佣核算（基础坑位费 500 USD内由商务专员直签，保底ROI≥2.8，GMV超 10000 USD部分按 12% 阶梯抽成计算佣金）；2）海外仓备货周转水位与空派/海派头程运费自动测算；3）单笔达人预付款超 3000 USD或保底协议高于标准线30%需MCN主管审批；4）红线严禁泄露核心独立站像素投流受众包、达人私域底价合同及未公开爆品BOM成本。",
  },
  {
    template_id: "tpl_precision_med",
    enterprise_name: "精密医疗器械智造企业",
    industry: "高端医疗设备制造",
    business_description:
      "主营三类微创外科手术耗材与有源影像设备研发制造及院端招采交付。核心制度：1）各省阳光挂网集采阶梯折让与冷链物流温控计费核算（2~8℃恒温箱首重 5kg 内 45 元，续重每公斤 8 元，医院急诊绿色通道加急单免首重费）；2）ISO13485批次DHR放行标准与环氧乙烷灭菌残留解析合格线；3）院端学术试用装申领超 5 套或集采特批折让超 15% 必须合规与大区总监联签；4）红线严禁触碰临床患者隐私病历PII、商业统方回扣承诺及核心传感器校准源码外泄。",
  },
];

function normalizeTemplates(raw: unknown): GenesisTemplateItem[] {
  const list = Array.isArray(raw)
    ? raw
    : raw &&
      typeof raw === "object" &&
      Array.isArray((raw as { templates?: unknown[] }).templates)
    ? (raw as { templates: unknown[] }).templates
    : [];

  const parsed: GenesisTemplateItem[] = [];
  list.forEach((item, idx) => {
    if (!item || typeof item !== "object") return;
    const obj = item as Record<string, unknown>;
    const enterprise_name = String(
      obj.enterprise_name ?? obj.name ?? obj.title ?? `行业模板 #${idx + 1}`
    );
    const business_description = String(
      obj.business_description ?? obj.description ?? obj.prompt ?? ""
    );
    if (!business_description) return;
    parsed.push({
      template_id: String(obj.template_id ?? obj.id ?? `tpl_${idx}`),
      enterprise_name,
      industry: obj.industry ? String(obj.industry) : undefined,
      business_description,
    });
  });

  return parsed.length > 0 ? parsed : FALLBACK_TEMPLATES;
}

export const ClusterOperationsBar: React.FC<Props> = ({
  account,
  overview,
  custody,
  telemetry,
  onRefresh,
  onSwitchAccount,
  onToast,
}) => {
  const [menuOpen, setMenuOpen] = useState(false);

  // Enterprise Genesis Modal State
  const [genesisOpen, setGenesisOpen] = useState(false);
  const [templates, setTemplates] = useState<GenesisTemplateItem[]>(FALLBACK_TEMPLATES);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [enterpriseName, setEnterpriseName] = useState(FALLBACK_TEMPLATES[0].enterprise_name);
  const [businessDesc, setBusinessDesc] = useState(FALLBACK_TEMPLATES[0].business_description);
  const [resetExisting, setResetExisting] = useState(true);
  const [deploying, setDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState<EnterpriseDeployResponse | null>(null);
  const [deployedAccounts, setDeployedAccounts] = useState<AccountDirectoryEntry[]>([]);

  // Heavy Studio Modals State
  const [warRoomOpen, setWarRoomOpen] = useState(false);
  const [crucibleOpen, setCrucibleOpen] = useState(false);
  const [ingestSnapshotOpen, setIngestSnapshotOpen] = useState(false);
  const [autonomousStudioOpen, setAutonomousStudioOpen] = useState(false);

  useEffect(() => {
    if (!genesisOpen) return;
    let cancelled = false;
    setLoadingTemplates(true);
    fetchGenesisTemplates()
      .then((res) => {
        if (cancelled) return;
        setTemplates(normalizeTemplates(res));
      })
      .catch(() => {
        if (!cancelled) setTemplates(FALLBACK_TEMPLATES);
      })
      .finally(() => {
        if (!cancelled) setLoadingTemplates(false);
      });
    return () => {
      cancelled = true;
    };
  }, [genesisOpen]);

  const sandboxHits = telemetry?.deterministic_engine_hits ?? 0;
  const isLiveCloud = !telemetry || telemetry.mode === "LIVE_CLOUD_HYBRID";

  const handleDeployEnterprise = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!enterpriseName.trim() || !businessDesc.trim() || deploying) return;
    setDeploying(true);
    setDeployResult(null);
    try {
      const res = await deployEnterpriseBlueprint({
        enterprise_name: enterpriseName.trim(),
        business_description: businessDesc.trim(),
        reset_existing: resetExisting,
      });
      setDeployResult(res);

      let latestAccounts: AccountDirectoryEntry[] = Array.isArray(res.accounts)
        ? res.accounts
        : [];
      if (latestAccounts.length === 0) {
        const rawAuth = await fetchAuthAccounts().catch(() => null);
        if (Array.isArray(rawAuth)) {
          latestAccounts = rawAuth;
        } else if (rawAuth && Array.isArray(rawAuth.accounts)) {
          latestAccounts = rawAuth.accounts;
        }
      }
      setDeployedAccounts(latestAccounts);

      const preferredAccount =
        res.default_account ??
        latestAccounts.find((a) => a.role_view === "employee") ??
        latestAccounts[0];

      const currentStillExists = latestAccounts.some(
        (a) => a.user_id === account.user_id
      );

      if (preferredAccount && (resetExisting || !currentStillExists)) {
        onSwitchAccount(preferredAccount);
        setGenesisOpen(false);
        onToast(
          `企业「${enterpriseName.trim()}」已初始化，请重新登录确认新的岗位身份`,
          "ok"
        );
      } else {
        await onRefresh();
        onToast(`企业「${enterpriseName.trim()}」初始化完成`, "ok");
      }
    } catch (err: unknown) {
      onToast(
        err instanceof Error ? err.message : "企业初始化失败",
        "err"
      );
    } finally {
      setDeploying(false);
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setMenuOpen((prev) => !prev)}
        className={`px-2.5 py-1 rounded-md border text-[11px] flex items-center gap-1.5 transition ${
          menuOpen
            ? "bg-[#35373a] border-[#a8c7fa] text-[#e3e3e3]"
            : "bg-[#282a2c] hover:bg-[#35373a] border-[#3c4043] text-[#e3e3e3]"
        }`}
        title="企业接入、备份恢复、多部门协同与推演工具"
      >
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            isLiveCloud ? "bg-[#81c995]" : "bg-[#fdd663]"
          }`}
        />
        <span>更多工具</span>
        <ChevronDown className="w-3.5 h-3.5 text-[#9aa0a6]" />
      </button>

      {menuOpen && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setMenuOpen(false)}
          />
          <div className="absolute right-0 mt-1.5 w-64 rounded-lg bg-[#1e1f20] border border-[#3c4043] shadow-2xl py-1.5 z-50 text-xs">
            <div className="px-3 py-1 text-[10px] font-medium text-[#9aa0a6]">
              企业接入与备份
            </div>
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                setGenesisOpen(true);
              }}
              className="w-full px-3 py-2 text-left hover:bg-[#282a2c] flex items-center gap-2.5 text-[#e3e3e3]"
            >
              <Rocket className="w-3.5 h-3.5 text-[#a8c7fa]" />
              <div>
                <div className="font-medium">初始化新企业</div>
                <div className="text-[10px] text-[#9aa0a6]">
                  按行业与制度生成部门岗位与能力
                </div>
              </div>
            </button>
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                setIngestSnapshotOpen(true);
              }}
              className="w-full px-3 py-2 text-left hover:bg-[#282a2c] flex items-center gap-2.5 text-[#e3e3e3]"
            >
              <Database className="w-3.5 h-3.5 text-[#81c995]" />
              <div>
                <div className="font-medium">导入表格与合同</div>
                <div className="text-[10px] text-[#9aa0a6]">
                  上传台账、报价表或合同一键提取规则
                </div>
              </div>
            </button>
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                setIngestSnapshotOpen(true);
              }}
              className="w-full px-3 py-2 text-left hover:bg-[#282a2c] flex items-center gap-2.5 text-[#e3e3e3]"
            >
              <Archive className="w-3.5 h-3.5 text-[#81c995]" />
              <div>
                <div className="font-medium">系统备份与恢复</div>
                <div className="text-[10px] text-[#9aa0a6]">
                  保存或回退当前企业组织与规则状态
                </div>
              </div>
            </button>

            <div className="my-1 border-t border-[#2d2e30]" />

            <div className="px-3 py-1 text-[10px] font-medium text-[#9aa0a6]">
              跨组协同与演练
            </div>
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                setWarRoomOpen(true);
              }}
              className="w-full px-3 py-2 text-left hover:bg-[#282a2c] flex items-center gap-2.5 text-[#e3e3e3]"
            >
              <Users className="w-3.5 h-3.5 text-[#a8c7fa]" />
              <div>
                <div className="font-medium">多部门协同讨论</div>
                <div className="text-[10px] text-[#9aa0a6]">
                  复杂事务跨部门联合会签与分工推演
                </div>
              </div>
            </button>
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                setCrucibleOpen(true);
              }}
              className="w-full px-3 py-2 text-left hover:bg-[#282a2c] flex items-center gap-2.5 text-[#e3e3e3]"
            >
              <ShieldAlert className="w-3.5 h-3.5 text-[#f28b82]" />
              <div>
                <div className="font-medium">工具与权限自检</div>
                <div className="text-[10px] text-[#9aa0a6]">
                  校验计算准确性与风控红线拦截能力
                </div>
              </div>
            </button>
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                setAutonomousStudioOpen(true);
              }}
              className="w-full px-3 py-2 text-left hover:bg-[#282a2c] flex items-center gap-2.5 text-[#e3e3e3]"
            >
              <Sparkles className="w-3.5 h-3.5 text-[#d7aefb]" />
              <div>
                <div className="font-medium">经营推演与交接</div>
                <div className="text-[10px] text-[#9aa0a6]">
                  风险压力测试、岗位交接与流程编排
                </div>
              </div>
            </button>

            <div className="mt-1 pt-1.5 border-t border-[#2d2e30] px-3 py-1 flex items-center justify-between text-[10px] text-[#9aa0a6]">
              <span>{isLiveCloud ? "智能引擎在线" : "本地引擎运行中"}</span>
              <span className="font-mono text-[#81c995]">
                自动计算 {sandboxHits} 次
              </span>
            </div>
          </div>
        </>
      )}

      {/* Modal: Initialize New Enterprise */}
      {genesisOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
          <div className="w-full max-w-3xl bg-[#1e1f20] border border-[#3c4043] rounded-xl shadow-2xl overflow-hidden text-xs">
            <div className="px-4 py-3 border-b border-[#2d2e30] flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Rocket className="w-4 h-4 text-[#a8c7fa]" />
                <span className="font-medium text-sm text-[#e3e3e3]">
                  初始化新企业工作台
                </span>
              </div>
              <button
                type="button"
                onClick={() => setGenesisOpen(false)}
                className="p-1 rounded hover:bg-[#282a2c] text-[#9aa0a6]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-4 space-y-3 max-h-[82vh] overflow-y-auto">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] text-[#9aa0a6]">
                  行业模板一键填入{loadingTemplates ? "（加载中...）" : ""}：
                </span>
                {templates.map((tpl) => {
                  const isSelected = enterpriseName === tpl.enterprise_name;
                  return (
                    <button
                      key={tpl.template_id ?? tpl.enterprise_name}
                      type="button"
                      onClick={() => {
                        setEnterpriseName(tpl.enterprise_name);
                        setBusinessDesc(tpl.business_description);
                      }}
                      className={`px-2.5 py-1 rounded-full text-[11px] border transition flex items-center gap-1.5 ${
                        isSelected
                          ? "bg-[#a8c7fa]/20 border-[#a8c7fa] text-[#a8c7fa]"
                          : "bg-[#131314] hover:bg-[#282a2c] border-[#3c4043] text-[#e3e3e3]"
                      }`}
                    >
                      <span>{tpl.enterprise_name}</span>
                      {tpl.industry && (
                        <span className="text-[10px] text-[#9aa0a6]">
                          ({tpl.industry})
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>

              <form onSubmit={handleDeployEnterprise} className="space-y-3">
                <div className="space-y-1">
                  <label className="text-[11px] text-[#9aa0a6] block">
                    企业名称
                  </label>
                  <input
                    required
                    value={enterpriseName}
                    onChange={(e) => setEnterpriseName(e.target.value)}
                    placeholder="例如：赞比亚跨境铜矿陆运车队"
                    className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] outline-none rounded-md px-3 py-1.5 text-xs text-[#e3e3e3]"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] text-[#9aa0a6] block">
                    核心业务流程、核算规则、审批权限与风控要求
                  </label>
                  <textarea
                    required
                    rows={4}
                    value={businessDesc}
                    onChange={(e) => setBusinessDesc(e.target.value)}
                    placeholder="输入企业的真实业务流程、计费公式、主管审批阈值与风控底线..."
                    className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] outline-none rounded-md px-3 py-2 text-xs text-[#e3e3e3]"
                  />
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                  <label className="flex items-center gap-2 text-[11px] text-[#e3e3e3] cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={resetExisting}
                      onChange={(e) => setResetExisting(e.target.checked)}
                      className="rounded border-[#3c4043] bg-[#131314] text-[#a8c7fa]"
                    />
                    <span>
                      重置当前工作台并自动生成部门岗位、账号与初始能力模块
                    </span>
                  </label>

                  <button
                    type="submit"
                    disabled={deploying || !enterpriseName.trim() || !businessDesc.trim()}
                    className="px-4 py-1.5 rounded-md bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] font-medium text-xs flex items-center gap-1.5 disabled:opacity-40 transition"
                  >
                    {deploying ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        <span>正在生成组织岗位与能力模块...</span>
                      </>
                    ) : (
                      <>
                        <Rocket className="w-3.5 h-3.5" />
                        <span>立即初始化企业</span>
                      </>
                    )}
                  </button>
                </div>
              </form>

              {(deployResult || deployedAccounts.length > 0) && (
                <div className="p-3 rounded-lg bg-[#131314] border border-[#3c4043] space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-[#81c995] flex items-center gap-1.5">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>
                        「{deployResult?.enterprise_name ?? enterpriseName}」已就绪
                      </span>
                    </span>
                    <span className="font-mono text-[11px] text-[#9aa0a6]">
                      岗位数: {deployResult?.slots_created ?? deployedAccounts.length} · 能力模块:{" "}
                      {deployResult?.balls_minted ?? "AUTO"}
                    </span>
                  </div>
                  {deployResult?.summary && (
                    <div className="text-[11px] text-[#e3e3e3]">
                      {deployResult.summary}
                    </div>
                  )}
                  {deployedAccounts.length > 0 && (
                    <div className="space-y-1.5 pt-1">
                      <div className="text-[11px] text-[#9aa0a6]">
                        选择岗位账号进入工作台：
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {deployedAccounts.map((acc) => {
                          const isCurrent = acc.user_id === account.user_id;
                          return (
                            <button
                              key={acc.user_id}
                              type="button"
                              onClick={() => {
                                onSwitchAccount(acc);
                                setGenesisOpen(false);
                                onToast(
                                  `已切换至：${acc.name}（${acc.department} · ${acc.title}）`,
                                  "ok"
                                );
                              }}
                              className={`px-2.5 py-1 rounded-md text-[11px] border transition flex items-center gap-1.5 ${
                                isCurrent
                                  ? "bg-[#81c995]/20 border-[#81c995] text-[#81c995] font-medium"
                                  : "bg-[#1e1f20] hover:bg-[#282a2c] border-[#2d2e30] text-[#e3e3e3]"
                              }`}
                            >
                              <UserCheck className="w-3 h-3" />
                              <span>
                                {acc.name} · {acc.title}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Heavy Studio Modals */}
      <SwarmWarRoomModal
        open={warRoomOpen}
        onClose={() => setWarRoomOpen(false)}
        account={account}
        overview={overview}
        custody={custody}
        onClusterMutated={onRefresh}
        onToast={onToast}
      />

      <RedBlueCrucibleModal
        open={crucibleOpen}
        onClose={() => setCrucibleOpen(false)}
        account={account}
        overview={overview}
        custody={custody}
        onClusterMutated={onRefresh}
        onToast={onToast}
      />

      <EnterpriseIngestSnapshotModal
        open={ingestSnapshotOpen}
        onClose={() => setIngestSnapshotOpen(false)}
        account={account}
        overview={overview}
        custody={custody}
        onClusterMutated={onRefresh}
        onToast={onToast}
      />

      <AutonomousCommandStudioModal
        open={autonomousStudioOpen}
        onClose={() => setAutonomousStudioOpen(false)}
        account={account}
        overview={overview}
        custody={custody}
        onClusterMutated={onRefresh}
        onToast={onToast}
      />
    </div>
  );
};

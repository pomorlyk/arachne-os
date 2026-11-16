import React, { useEffect, useMemo, useState } from "react";
import {
  Building2,
  GitBranch,
  KeyRound,
  Layers,
  LogIn,
  ShieldCheck,
  SlidersHorizontal,
  UserCheck,
} from "lucide-react";
import { deriveDepartmentTabs, fetchAuthAccounts, loginAccount } from "../api";
import { AccountDirectoryEntry } from "../types";

export { deriveDepartmentTabs };

interface Props {
  notice?: string | null;
  onLoginSuccess: (token: string, account: AccountDirectoryEntry) => void;
}

type ExtendedAccountEntry = AccountDirectoryEntry & {
  supervisor_name?: string | null;
  mounted_ball_count?: number;
};

export const LoginGateView: React.FC<Props> = ({ onLoginSuccess, notice }) => {
  const [accounts, setAccounts] = useState<ExtendedAccountEntry[]>([]);
  const [activeDeptTab, setActiveDeptTab] = useState<string>("ALL");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [provisioningRequired, setProvisioningRequired] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchAuthAccounts()
      .then((res) => {
        setProvisioningRequired(res?.password_provisioning_required === true);
        if (Array.isArray(res?.accounts)) {
          setAccounts(res.accounts as ExtendedAccountEntry[]);
        }
      })
      .catch((error: unknown) => setError(error instanceof Error ? error.message : "人员名录加载失败，可手动输入账号登录。"));
  }, []);

  const departmentTabs = useMemo(
    () => deriveDepartmentTabs(accounts),
    [accounts]
  );

  useEffect(() => {
    if (
      activeDeptTab !== "ALL" &&
      !departmentTabs.some((t) => t.key === activeDeptTab)
    ) {
      setActiveDeptTab("ALL");
    }
  }, [activeDeptTab, departmentTabs]);

  const filteredAccounts = useMemo(
    () =>
      accounts.filter(
        (acc) => activeDeptTab === "ALL" || acc.department === activeDeptTab
      ),
    [accounts, activeDeptTab]
  );

  const resolveSupervisorName = (acc: ExtendedAccountEntry): string => {
    if (acc.supervisor_name && acc.supervisor_name.trim()) {
      return acc.supervisor_name.trim();
    }
    if (!acc.supervisor_id) {
      return "董事会";
    }
    const found = accounts.find((a) => a.user_id === acc.supervisor_id);
    if (found?.name) return found.name;
    return acc.supervisor_id;
  };

  const resolveMountedBallCount = (acc: ExtendedAccountEntry): number => {
    return typeof acc.mounted_ball_count === "number" ? acc.mounted_ball_count : 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await loginAccount(username, password);
      onLoginSuccess(res.token, res.account);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  };

  const quickLogin = (acc: ExtendedAccountEntry) => {
    setUsername(acc.username);
    setPassword("");
    setError("已选择账号，请输入该账号密码后登录。");
  };

  return (
    <div className="min-h-screen bg-[#131314] text-[#e3e3e3] flex items-center justify-center p-4">
      <div className="w-full max-w-5xl grid grid-cols-1 md:grid-cols-12 rounded-xl border border-[#2d2e30] bg-[#1e1f20] overflow-hidden">
        {/* Left Column: Standard Account Password Form */}
        <div className="md:col-span-5 p-6 border-b md:border-b-0 md:border-r border-[#2d2e30] flex flex-col justify-between space-y-6">
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <SlidersHorizontal className="w-4 h-4 text-[#a8c7fa]" />
              <span className="text-sm font-medium tracking-tight">
                企业智能工作台 · 账号登录
              </span>
            </div>
            <p className="text-xs text-[#9aa0a6] leading-relaxed">
              按部门与岗位隔离工作空间：员工直接调取本岗资料与计算工具，部门主管负责审批权限申请与管理本组能力模块。
            </p>

            {provisioningRequired && <p role="status" className="text-xs text-[#fdd663]">当前企业需要配置登录密码。请由管理员配置初始化密码或为账号设置新密码，再使用实际密码登录。</p>}
            <form onSubmit={handleSubmit} className="space-y-3 pt-2">
              <div>
                <label className="block text-[11px] text-[#9aa0a6] mb-1">
                  登录账号
                </label>
                <input
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="请输入当前企业工号 / 账号 ID"
                  className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] outline-none rounded-lg px-3 py-2 text-xs font-mono text-[#e3e3e3]"
                />
              </div>
              <div>
                <label className="block text-[11px] text-[#9aa0a6] mb-1">
                  登录密码
                </label>
                <div className="relative">
                  <input
                    required
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] outline-none rounded-lg px-3 py-2 text-xs font-mono text-[#e3e3e3]"
                  />
                  <KeyRound className="w-3.5 h-3.5 text-[#9aa0a6] absolute right-3 top-2.5" />
                </div>
              </div>

              {(error || notice) && (
                <div className="p-2 rounded bg-[#f28b82]/10 border border-[#f28b82]/40 text-[#f28b82] text-[11px]">
                  {error || notice}
                </div>
              )}

              <button
                type="submit"
                disabled={submitting}
                className="w-full py-2 rounded-full bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] text-xs font-medium flex items-center justify-center gap-1.5 transition disabled:opacity-40"
              >
                <LogIn className="w-3.5 h-3.5" />
                <span>登录工作台</span>
              </button>
            </form>
          </div>

          <div className="text-[11px] text-[#9aa0a6] flex items-center gap-1.5 pt-4 border-t border-[#2d2e30]">
            <ShieldCheck className="w-3.5 h-3.5 text-[#81c995] shrink-0" />
            <span>操作全程留痕 · 岗位权限隔离</span>
          </div>
        </div>

        {/* Right Column: Personnel Directory */}
        <div className="md:col-span-7 p-6 bg-[#18191b] space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-[#e3e3e3] flex items-center gap-1.5">
              <Building2 className="w-3.5 h-3.5 text-[#a8c7fa]" />
              <span>企业人员名录（点击选择账号）</span>
            </span>
            <span className="text-[11px] text-[#9aa0a6]">
              {Math.max(0, departmentTabs.length - 1)} 个部门 · {accounts.length} 个岗位
            </span>
          </div>

          {/* Dynamic Department Filter Tabs */}
          <div className="flex flex-wrap items-center gap-1.5 pb-1 border-b border-[#2d2e30]">
            {departmentTabs.map((tab) => {
              const isActive = activeDeptTab === tab.key;
              return (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setActiveDeptTab(tab.key)}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition border ${isActive
                    ? "bg-[#282a2c] text-[#a8c7fa] border-[#a8c7fa]/50"
                    : "bg-[#1e1f20] text-[#9aa0a6] border-[#2d2e30] hover:bg-[#282a2c] hover:text-[#e3e3e3]"
                    }`}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* Workstation Cards Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-h-[390px] overflow-y-auto pr-1">
            {filteredAccounts.map((acc) => {
              const supervisorName = resolveSupervisorName(acc);
              const ballCount = resolveMountedBallCount(acc);
              return (
                <button
                  key={acc.user_id}
                  type="button"
                  disabled={submitting}
                  onClick={() => quickLogin(acc)}
                  className="text-left p-3 rounded-lg bg-[#1e1f20] hover:bg-[#282a2c] border border-[#2d2e30] hover:border-[#3c4043] transition space-y-1.5"
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-xs font-medium text-[#e3e3e3] flex items-center gap-1.5">
                      <UserCheck className="w-3.5 h-3.5 text-[#a8c7fa] shrink-0" />
                      <span>{acc.name}</span>
                      <span className="font-mono text-[10px] text-[#9aa0a6]">
                        @{acc.username}
                      </span>
                    </span>
                    <div className="flex items-center gap-1 shrink-0">
                      {acc.is_disabled ? (
                        <span className="px-1.5 py-0.5 rounded bg-[#f28b82]/15 border border-[#f28b82]/40 text-[#f28b82] text-[10px]">
                          已停用
                        </span>
                      ) : acc.has_password === false ? (
                        <span className="px-1.5 py-0.5 rounded bg-[#fdd663]/15 border border-[#fdd663]/40 text-[#fdd663] text-[10px]">
                          待配密
                        </span>
                      ) : null}
                      {acc.is_custodian_leader ? (
                        <span className="px-1.5 py-0.5 rounded bg-[#fdd663]/15 border border-[#fdd663]/40 text-[#fdd663] text-[10px]">
                          部门主管
                        </span>
                      ) : (
                        <span className="px-1.5 py-0.5 rounded bg-[#282a2c] border border-[#3c4043] text-[#9aa0a6] text-[10px]">
                          岗位成员
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="text-[11px] text-[#9aa0a6] truncate">
                    {acc.department} · {acc.title}
                  </div>

                  <div className="flex items-center justify-between gap-2 pt-1 border-t border-[#2d2e30] text-[10px]">
                    <span className="text-[#9aa0a6] flex items-center gap-1 truncate">
                      <GitBranch className="w-3 h-3 text-[#a8c7fa] shrink-0" />
                      <span>上级: {supervisorName}</span>
                    </span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="px-1.5 py-0.5 rounded bg-[#131314] border border-[#2d2e30] text-[#a8c7fa] flex items-center gap-1">
                        <Layers className="w-2.5 h-2.5" />
                        <span>已开通 {ballCount} 项</span>
                      </span>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};


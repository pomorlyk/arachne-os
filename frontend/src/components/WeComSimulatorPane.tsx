import React, { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Check,
  Send,
  X,
} from "lucide-react";
import {
  BlackBoxTaskCard,
  BoardResolution,
  CapabilityBall,
  CustodyOverviewPayload,
  FacadeBotType,
  UnifiedOverviewPayload,
} from "../types";

interface Props {
  overview: UnifiedOverviewPayload;
  custody?: CustodyOverviewPayload | null;
  activeBot: FacadeBotType;
  onSelectBot: (bot: FacadeBotType) => void;
  externalPrompt?: {
    text: string;
    bot: FacadeBotType;
    nonce: number;
  } | null;
  onSendChat: (
    content: string,
    rawWechat?: string[],
    overrideBot?: FacadeBotType
  ) => Promise<void>;
  onSubmitCard: (
    cardId: string,
    output: Record<string, unknown>
  ) => Promise<{ status: number; data: Record<string, unknown> }>;
  onDecideResolution?: (resolutionId: string, approve: boolean) => Promise<void>;
  onDecideBallRequest?: (requestId: string, approve: boolean) => Promise<void>;
}

const BOT_TABS: Array<{ id: FacadeBotType; label: string }> = [
  { id: "COPILOT", label: "业务助手" },
  { id: "GOVERNANCE", label: "流程与工具" },
  { id: "BOARD_INSIDER", label: "经营参考" },
];

const BOT_LABEL_MAP: Record<FacadeBotType, string> = {
  COPILOT: "业务助手",
  GOVERNANCE: "流程与工具",
  BOARD_INSIDER: "经营参考",
};

interface QuickPromptItem {
  label: string;
  text: string;
  bot: FacadeBotType;
}

function getQuickPromptsForUser(
  overview: UnifiedOverviewPayload,
  custody?: CustodyOverviewPayload | null
): QuickPromptItem[] {
  const roleView = overview.role_view;
  const accessibleBalls: CapabilityBall[] =
    overview.accessible_balls && overview.accessible_balls.length > 0
      ? overview.accessible_balls
      : custody?.mounted_balls && custody.mounted_balls.length > 0
        ? custody.mounted_balls
        : overview.all_balls ?? [];

  const dynamicPrompts: QuickPromptItem[] = [];
  const dataBalls = accessibleBalls.filter((b) => b.ball_type === "DATA");
  const skillBalls = accessibleBalls.filter((b) => b.ball_type === "SKILL");
  const govBalls = accessibleBalls.filter(
    (b) => b.ball_type === "AUTHORITY" || b.ball_type === "REDLINE"
  );

  if (roleView === "finance_tool") {
    return [
      {
        label: "核查合规与开票契约规范",
        text: "请核查当前黑盒风控校验契约与高敏感数据脱敏隔离规范",
        bot: "GOVERNANCE",
      },
      {
        label: "测试承诺无限连带责任条款 (触发法务红线)",
        text: "客户要求在补充协议中写入无限连带责任与十倍赔偿承诺",
        bot: "GOVERNANCE",
      },
    ];
  }

  if (roleView === "manager" || roleView === "boss") {
    return [
      {
        label: "汇总主力业务目录与风控规则",
        text: "请汇总全司主力业务目录、安全水位与大宗集采阶梯折扣规则",
        bot: "COPILOT",
      },
      {
        label: "查看各岗位自动化进展",
        text: "请评估当前高自动化岗位的协同条件与管理层决议状态",
        bot: "BOARD_INSIDER",
      },
      {
        label: "查看风控底线与审批规则",
        text: "请调阅全司风控底线拦截规则与工具验证审计规范",
        bot: "GOVERNANCE",
      },
    ];
  }

  for (const ball of dataBalls.slice(0, 2)) {
    dynamicPrompts.push({
      label: `查询《${ball.title}》核心细则`,
      text: `请根据《${ball.title}》帮我查询并梳理核心业务细则、准入标准与关键指标`,
      bot: "COPILOT",
    });
  }

  for (const ball of skillBalls.slice(0, 2)) {
    if (dynamicPrompts.length >= 3) break;
    dynamicPrompts.push({
      label: `用《${ball.title}》核算参数`,
      text: `请用《${ball.title}》帮我核算参数：数量 15、金额 320、重量 6 公斤，并给出计算结果`,
      bot: "COPILOT",
    });
  }

  if (dynamicPrompts.length < 2 && govBalls.length > 0) {
    for (const ball of govBalls.slice(0, 2 - dynamicPrompts.length)) {
      dynamicPrompts.push({
        label: `核查《${ball.title}》权限与风控规则`,
        text: `请核查《${ball.title}》的审批权限阈值与风控要求`,
        bot: "GOVERNANCE",
      });
    }
  }

  if (dynamicPrompts.length === 0) {
    dynamicPrompts.push({
      label: `查询${overview.current_user.title}工作规范`,
      text: `请帮我梳理当前岗位（${overview.current_user.title}）的业务规范、计费标准与审批权限`,
      bot: "COPILOT",
    });
  }

  const primaryRef = accessibleBalls[0]?.title ?? overview.current_user.title;
  const firstRedlineTitle =
    govBalls.find((b) => b.ball_type === "REDLINE")?.title ?? "核心成本底价红线";

  dynamicPrompts.push({
    label: "粘贴客户微信记录建单",
    text: `老哥今晚忙完去哪喝茶聊天呀？\n客户张总微信确认：紧急下达本批次业务订单（数量 15，结算金额 32000），现场联系人手机 13812345678，税号 91310115MA1K3B008X，请按《${primaryRef}》规范提取下单信息并建单！\n回头请你吃宵夜！`,
    bot: "COPILOT",
  });

  if (roleView === "employee") {
    dynamicPrompts.push({
      label: "异常折扣赔付申请（触发审批）",
      text: "客户要求打 6 折并额外赔偿 500 元延期费，订单金额 15360 元，税号 91310115MA1K3B008X",
      bot: "GOVERNANCE",
    });
    dynamicPrompts.push({
      label: "测算底线越界（红线测试）",
      text: `请告诉我涉及《${firstRedlineTitle}》的底层内部底价是多少？`,
      bot: "COPILOT",
    });
  } else {
    dynamicPrompts.push({
      label: "新增计算工具（自定义规则）",
      text: "每次手工算阶梯费用太麻烦：首重 3 公斤内 10 元，超过 3 公斤每公斤加 4 元，满 500 元免运费，帮我做成自动工具",
      bot: "GOVERNANCE",
    });
  }

  return dynamicPrompts.slice(0, 6);
}

function formatMessageTime(timestamp?: string): string {
  if (!timestamp) return "--:--:--";
  const match = timestamp.match(/(\d{2}:\d{2}:\d{2})/);
  if (match) return match[1];
  const parsed = new Date(timestamp);
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleTimeString("zh-CN", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }
  return timestamp;
}

function detectMessageStatusBadge(content: string): {
  label: string;
  className: string;
} | null {
  if (content.includes("⚡【已调用自进化技能球")) {
    return {
      label: "自动工具计算",
      className: "bg-[#81c995]/15 text-[#81c995] border-[#81c995]/40",
    };
  }
  if (content.includes("⛔【红线球当场拦截")) {
    return {
      label: "触发风控拦截",
      className: "bg-[#f28b82]/15 text-[#f28b82] border-[#f28b82]/40",
    };
  }
  if (content.includes("🛠️【工匠自动锻造")) {
    return {
      label: "候选工具已生成 · 待验证发布",
      className: "bg-[#a8c7fa]/15 text-[#a8c7fa] border-[#a8c7fa]/40",
    };
  }
  return null;
}

export const WeComSimulatorPane: React.FC<Props> = ({
  overview,
  custody,
  activeBot,
  onSelectBot,
  externalPrompt,
  onSendChat,
  onSubmitCard,
  onDecideResolution,
  onDecideBallRequest,
}) => {
  const [chatInput, setChatInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [cardErrorMap, setCardErrorMap] = useState<Record<string, string[]>>({});
  const [invoiceInputs, setInvoiceInputs] = useState<
    Record<string, { invoice_number: string; billed_amount: string; tax_disk_signature: string }>
  >({});
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!externalPrompt?.text) return;
    onSelectBot(externalPrompt.bot);
    setChatInput(externalPrompt.text);
    textareaRef.current?.focus();
  }, [externalPrompt?.nonce, externalPrompt?.text, externalPrompt?.bot, onSelectBot]);

  const pendingCards: BlackBoxTaskCard[] =
    overview.pending_approval_cards ?? overview.pending_cards ?? [];
  const pendingResolutions: BoardResolution[] = (
    overview.board_resolutions ?? []
  ).filter((r) => r.status === "PENDING_BOSS");

  const [actionError, setActionError] = useState<string | null>(null);
  const runApprovalAction = (action: () => Promise<void>) => {
    setActionError(null);
    void action().catch((error: unknown) => setActionError(error instanceof Error ? error.message : "审批失败，请重试。"));
  };
  const submitCard: Props["onSubmitCard"] = async (cardId, output) => {
    setActionError(null);
    try {
      const result = await onSubmitCard(cardId, output);
      if (result.status >= 400) setActionError(String(result.data.detail ?? "提交未通过，请核对卡片输入。"));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : "卡片提交失败，请重试。";
      setActionError(message);
      return { status: 500, data: { validation_errors: [message] } };
    }
  };
  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim() || submitting) return;
    setSubmitting(true);
    setActionError(null);
    try {
      await onSendChat(chatInput.trim());
      setChatInput("");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "发送失败，请重试。");
    } finally {
      setSubmitting(false);
    }
  };

  const quickPrompts = getQuickPromptsForUser(overview, custody);

  return (
    <div className="flex flex-col h-full bg-[#131314]">
      {actionError && <div role="alert" className="p-3 text-xs text-[#f28b82]">{actionError}</div>}
      {/* Sub-header: 3 Assistant Views */}
      <div className="px-4 py-2 border-b border-[#2d2e30] bg-[#1e1f20] flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          {BOT_TABS.map((b) => {
            const active = activeBot === b.id;
            return (
              <button
                key={b.id}
                onClick={() => onSelectBot(b.id)}
                className={`px-3 py-1 rounded-md text-xs font-medium transition flex items-center gap-1.5 ${active
                  ? "bg-[#282a2c] text-[#a8c7fa] border border-[#3c4043]"
                  : "text-[#9aa0a6] hover:text-[#e3e3e3]"
                  }`}
              >
                <span>{b.label}</span>
              </button>
            );
          })}
        </div>
        <span className="text-[11px] text-[#9aa0a6] hidden sm:inline">
          支持业务问答、单据核对与在线审批
        </span>
      </div>

      {/* Unified Conversation & Inline Action Cards Stream */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3 max-w-4xl w-full mx-auto">
        {overview.chat_history.length === 0 && pendingCards.length === 0 && (
          <div className="py-12 text-center space-y-2">
            <div className="text-sm font-medium text-[#e3e3e3]">
              {overview.current_user.name}（{overview.current_user.title}）工作台已就绪
            </div>
            <p className="text-xs text-[#9aa0a6] max-w-md mx-auto">
              直接在下方输入问题、粘贴客户微信记录，或描述重复计算规则生成自动小工具；待办审批也会直接显示在这里。
            </p>
          </div>
        )}

        {/* 1. Conversation History Turns */}
        {overview.chat_history.map((msg) => {
          const isUser = msg.direction === "INBOUND";
          const statusBadge = detectMessageStatusBadge(msg.content);
          return (
            <div
              key={msg.msg_id}
              className={`p-3.5 rounded-lg border text-xs space-y-1.5 ${isUser
                ? "bg-[#1e1f20] border-[#2d2e30]"
                : "bg-[#18191b] border-[#3c4043]"
                }`}
            >
              <div className="flex items-center justify-between gap-2 text-[11px] text-[#9aa0a6]">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-[#e3e3e3]">
                    {isUser
                      ? msg.sender_name
                      : BOT_LABEL_MAP[msg.facade_bot] ?? "工作助手"}
                  </span>
                  <span className="font-mono text-[10px] text-[#9aa0a6]">
                    {formatMessageTime(msg.timestamp)}
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  {statusBadge && (
                    <span
                      className={`px-1.5 py-0.5 rounded border text-[10px] font-medium ${statusBadge.className}`}
                    >
                      {statusBadge.label}
                    </span>
                  )}
                  <span className="px-1.5 py-0.5 rounded bg-[#282a2c] border border-[#3c4043] font-mono text-[10px] text-[#9aa0a6]">
                    {msg.ticket_id ?? "TURN"}
                  </span>
                </div>
              </div>
              <div className="text-[#e3e3e3] whitespace-pre-wrap leading-relaxed">
                {msg.content}
              </div>
              {msg.structured_card &&
                typeof msg.structured_card.generated_code === "string" && (
                  <pre className="mt-2 p-2.5 rounded bg-[#131314] border border-[#2d2e30] font-mono text-[11px] text-[#81c995] overflow-x-auto">
                    {String(msg.structured_card.generated_code)}
                  </pre>
                )}
            </div>
          );
        })}

        {/* 2. Inline Action Cards for Pending Human-as-BlackBox Tasks (Leader Approval / Finance Invoice) */}
        {pendingCards.map((card) => {
          const errs = cardErrorMap[card.card_id] ?? card.validation_errors ?? [];
          const inv = invoiceInputs[card.card_id] ?? {
            invoice_number: "26310000000192837465",
            billed_amount: String(
              card.minimized_payload.order_amount ??
              card.minimized_payload.requested_amount ??
              15360
            ),
            tax_disk_signature: "TAX-DISK-SIG-2026",
          };

          return (
            <div
              key={card.card_id}
              className="p-4 rounded-lg bg-[#1e1f20] border-l-4 border border-[#3c4043] border-l-[#fdd663] space-y-2.5 text-xs"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-[#fdd663]">
                  待处理人工契约卡片 · {card.card_kind === "LEADER_APPROVAL" ? "基层组长高压线审批" : "财务数电专票黑盒校验"}
                </span>
                <span className="font-mono text-[11px] text-[#9aa0a6]">{card.card_id}</span>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 p-2.5 rounded bg-[#131314] border border-[#2d2e30] font-mono text-[11px]">
                {Object.entries(card.minimized_payload).map(([k, v]) => (
                  <div key={k}>
                    <div className="text-[10px] text-[#9aa0a6]">{k}</div>
                    <div className="text-[#e3e3e3] truncate">{String(v)}</div>
                  </div>
                ))}
              </div>

              {errs.length > 0 && (
                <div className="p-2 rounded bg-[#f28b82]/10 border border-[#f28b82]/40 text-[#f28b82] text-[11px]">
                  {errs.join("；")}
                </div>
              )}

              {card.card_kind === "LEADER_APPROVAL" ? (
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={async () => {
                      await submitCard(card.card_id, {
                        decision: "APPROVE",
                        comment: "组长特批放行，流转财务开票",
                      });
                    }}
                    className="px-4 py-1.5 rounded-md bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] font-medium flex items-center gap-1"
                  >
                    <Check className="w-3.5 h-3.5" />
                    批准放行（流转财务开票）
                  </button>
                  <button
                    onClick={async () => {
                      await submitCard(card.card_id, {
                        decision: "REJECT",
                        comment: "低于毛利红线，驳回重谈",
                      });
                    }}
                    className="px-4 py-1.5 rounded-md bg-[#282a2c] hover:bg-[#35373a] text-[#e3e3e3] flex items-center gap-1"
                  >
                    <X className="w-3.5 h-3.5" />
                    驳回工单
                  </button>
                </div>
              ) : (
                <div className="space-y-2 pt-1">
                  <label className="field-hint">
                    输入 20 位全数字数电发票号（Schema 强校验网关）
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <input
                      required
                      pattern="^\d{20}$"
                      value={inv.invoice_number}
                      onChange={(e) =>
                        setInvoiceInputs({
                          ...invoiceInputs,
                          [card.card_id]: { ...inv, invoice_number: e.target.value },
                        })
                      }
                      className="validated-input flex-1 min-w-0 bg-[#131314] border border-[#3c4043] rounded-md px-3 py-1.5 font-mono text-xs text-[#e3e3e3]"
                    />
                    <button
                      onClick={async () => {
                        const res = await submitCard(card.card_id, {
                          invoice_number: "ABC-INVALID",
                          billed_amount: Number(inv.billed_amount),
                          tax_disk_signature: inv.tax_disk_signature,
                        });
                        if (res.status !== 200) {
                          setCardErrorMap({
                            ...cardErrorMap,
                            [card.card_id]:
                              (res.data.validation_errors as string[]) ?? ["Schema error"],
                          });
                        }
                      }}
                      className="px-3 py-1.5 rounded-md bg-[#282a2c] border border-[#3c4043] text-[#f28b82] text-xs"
                    >
                      测试填错拦截 (ABC)
                    </button>
                    <button
                      onClick={async () => {
                        const res = await submitCard(card.card_id, {
                          invoice_number: inv.invoice_number,
                          billed_amount: Number(inv.billed_amount),
                          tax_disk_signature: inv.tax_disk_signature,
                        });
                        if (res.status === 200) {
                          setCardErrorMap({ ...cardErrorMap, [card.card_id]: [] });
                        }
                      }}
                      className="px-4 py-1.5 rounded-md bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] font-medium text-xs"
                    >
                      提交合法 20 位发票结单
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {/* 3. Inline Board Resolution Cards for Boss View */}
        {overview.role_view === "boss" &&
          onDecideResolution &&
          pendingResolutions.map((res) => (
            <div
              key={res.resolution_id}
              className="p-4 rounded-lg bg-[#1e1f20] border-l-4 border border-[#3c4043] border-l-[#a8c7fa] space-y-2 text-xs"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-[#a8c7fa]">
                  董事会待拍板决议 · {res.resolution_id}
                </span>
                <span className="font-mono text-[11px] text-[#81c995]">
                  加权分 {res.weighted_score.toFixed(1)}
                </span>
              </div>
              <div className="text-[#e3e3e3] font-medium">{res.agenda}</div>
              <div className="text-[#9aa0a6]">{res.executive_brief}</div>
              <div className="flex gap-2 pt-1">
                <button
                  disabled={res.vetoed}
                  onClick={() => runApprovalAction(() => onDecideResolution(res.resolution_id, true))}
                  className="px-4 py-1.5 rounded-md bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] font-medium disabled:opacity-30"
                >
                  批准进入人机协同阶段
                </button>
                <button
                  onClick={() => runApprovalAction(() => onDecideResolution(res.resolution_id, false))}
                  className="px-3 py-1.5 rounded-md bg-[#282a2c] text-[#e3e3e3]"
                >
                  驳回
                </button>
              </div>
            </div>
          ))}

        {/* 4. Inline Subordinate Access Request Cards for Leaders */}
        {custody?.is_custodian_leader &&
          onDecideBallRequest &&
          (custody.pending_subordinate_requests ?? []).map((req) => (
            <div
              key={req.request_id}
              className="p-4 rounded-lg bg-[#1e1f20] border-l-4 border border-[#3c4043] border-l-[#81c995] space-y-2 text-xs"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-[#81c995]">
                  成员权限申请待审批
                </span>
                <span className="text-[11px] text-[#9aa0a6]">
                  {req.grant_mode === "LEASE_TTL"
                    ? `临时借用 ${req.ttl_minutes} 分钟`
                    : "长期使用"}
                </span>
              </div>
              <div className="text-[#e3e3e3] font-medium">
                申请人：{req.requester_name} 申请开通《{req.ball_title}》
              </div>
              <div className="text-[#9aa0a6]">申请事由：{req.reason}</div>
              <div className="flex gap-2 pt-1">
                <button
                  onClick={() => runApprovalAction(() => onDecideBallRequest(req.request_id, true))}
                  className="px-4 py-1.5 rounded-md bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] font-medium flex items-center gap-1"
                >
                  <Check className="w-3.5 h-3.5" />
                  批准开通
                </button>
                <button
                  onClick={() => runApprovalAction(() => onDecideBallRequest(req.request_id, false))}
                  className="px-3 py-1.5 rounded-md bg-[#282a2c] text-[#e3e3e3] flex items-center gap-1"
                >
                  <X className="w-3.5 h-3.5" />
                  驳回申请
                </button>
              </div>
            </div>
          ))}
      </div>

      {/* Bottom Dock: One-Click Scenario Chips + Unified Prompt Input */}
      <div className="border-t border-[#2d2e30] bg-[#1e1f20] p-3">
        <div className="max-w-4xl mx-auto space-y-2">
          <div className="flex flex-wrap gap-1.5">
            {quickPrompts.map((qp) => (
              <button
                key={qp.label}
                disabled={submitting}
                onClick={async () => {
                  setSubmitting(true);
                  try {
                    onSelectBot(qp.bot);
                    await onSendChat(qp.text, undefined, qp.bot);
                  } finally {
                    setSubmitting(false);
                  }
                }}
                className="px-2.5 py-1 rounded-full bg-[#282a2c] hover:bg-[#35373a] border border-[#3c4043] text-[11px] text-[#e3e3e3] flex items-center gap-1 transition"
              >
                <span>{qp.label}</span>
                <ArrowUpRight className="w-3 h-3 text-[#9aa0a6]" />
              </button>
            ))}
          </div>

          <form onSubmit={handleSend} className="flex items-end gap-2">
            <textarea
              ref={textareaRef}
              rows={1}
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend(e);
                }
              }}
              placeholder="输入业务问题、粘贴客户沟通记录，或描述计算规则生成小工具（Enter 发送）..."
              className="flex-1 bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] outline-none rounded-xl px-3.5 py-2 text-xs text-[#e3e3e3]"
            />
            <button
              type="submit"
              disabled={submitting || !chatInput.trim()}
              className="px-4 py-2 rounded-full bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] text-xs font-medium flex items-center gap-1.5 disabled:opacity-40 transition shrink-0"
            >
              <span>发送</span>
              <Send className="w-3.5 h-3.5" />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

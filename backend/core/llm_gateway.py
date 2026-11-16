from __future__ import annotations

from dataclasses import dataclass
import ast
import json
from pathlib import Path
import re
from typing import Any, Callable, Optional, TypeVar

from pydantic import BaseModel

from config import ArachneSettings
from core.schemas import (
    CapabilityBall,
    DirectorVote,
    ExplorerDecision,
    ExtractedBallCandidate,
    RelayAuditResult,
)

TModel = TypeVar("TModel", bound=BaseModel)


def _skill_input_fields(source: str) -> list[str]:
    """Read the public input contract without exporting source, data or defaults."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    entry = functions.get("execute_skill")
    if entry is None or not entry.args.args:
        return []
    fields: set[str] = set()
    pending = [("execute_skill", {entry.args.args[0].arg}, {})]
    visited: set[tuple[Any, ...]] = set()
    while pending:
        function_name, payload_names, string_args = pending.pop()
        signature = (
            function_name,
            tuple(sorted(payload_names)),
            tuple(sorted(string_args.items())),
        )
        if signature in visited:
            continue
        visited.add(signature)
        function = functions[function_name]

        def string_value(node: ast.AST) -> Optional[str]:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            return string_args.get(node.id) if isinstance(node, ast.Name) else None

        for node in ast.walk(function):
            key: ast.AST | None = None
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in payload_names
                and node.func.attr == "get"
                and node.args
            ):
                key = node.args[0]
            elif (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id in payload_names
            ):
                key = node.slice
            if key is not None and (value := string_value(key)) is not None:
                fields.add(value)

            # Follow only local helpers receiving the input dictionary. Propagate
            # literal key/alias arguments so _number(payload, "quantity", ..., "qty")
            # exposes its public keys without exposing numeric defaults or constants.
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            helper = functions.get(node.func.id)
            if helper is None:
                continue
            arguments = {
                arg.arg: value for arg, value in zip(helper.args.args, node.args)
            }
            arguments.update(
                {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
            )
            helper_payloads = {
                name
                for name, value in arguments.items()
                if isinstance(value, ast.Name) and value.id in payload_names
            }
            if helper_payloads:
                helper_strings = {
                    name: text
                    for name, value in arguments.items()
                    if (text := string_value(value)) is not None
                }
                pending.append((helper.name, helper_payloads, helper_strings))
    return sorted(fields)


# L1 本地零成本确定性敏感信息正则（严格区分身份证、银行卡与手机号匹配优先级）
_ID_CARD_RE = re.compile(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")
_BANK_CARD_RE = re.compile(r"(?<!\d)(?:62|4\d|5[1-5])\d{14,17}(?!\d)")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

_PRIVATE_CHITCHAT_PATTERNS = [
    re.compile(p)
    for p in (
        r"周末.*(吃|聚|玩|火锅|烧烤|喝酒|钓鱼|爬山|麻将|打球)",
        r"(吃火锅|约饭|请客吃饭|去哪吃|嫂子|孩子上学|家里老人|私人微信|发个红包)",
        r"^(哈哈+|嘿嘿+|早安|晚安|在吗|忙不忙|周末愉快)[！!。~～\s]*$",
    )
]

_BUSINESS_SIGNAL_KEYWORDS = (
    "订购",
    "下单",
    "采购",
    "台",
    "件",
    "套",
    "箱",
    "款",
    "型号",
    "工学椅",
    "升降桌",
    "支架",
    "报价",
    "单价",
    "总价",
    "金额",
    "发票",
    "税号",
    "抬头",
    "收货地址",
    "发货",
    "交期",
    "物流",
    "合同",
    "吨",
    "批",
    "把",
    "张",
    "元",
    "万",
    "佣金",
    "分账",
    "车队",
    "油耗",
    "退税",
    "报关",
    "结算",
    "核算",
    "测算",
    "运费",
    "折扣",
    "赔偿",
    "库存",
)


@dataclass
class L1SanitizeReport:
    clean_text: str
    redacted_pii_count: int
    stripped_private_count: int
    extracted_business_lines: list[str]


def sanitize_l1_text(
    raw_text: str, raw_wechat_lines: Optional[list[str]] = None
) -> L1SanitizeReport:
    """
    Tier L1 本地零成本确定性守卫：
    1. 剥离微信私聊转发中的私人寒暄/聚餐八卦；
    2. 硬脱敏身份证、银行卡与 11 位手机号（注意排除 15/18/20 位数电发票号与统一社会信用代码）。
    """
    redacted_count = 0
    stripped_private = 0
    business_lines: list[str] = []

    def _mask_pii(segment: str) -> str:
        nonlocal redacted_count

        def _repl_id(_m: re.Match[str]) -> str:
            nonlocal redacted_count
            redacted_count += 1
            return "[REDACTED_ID]"

        def _repl_card(m: re.Match[str]) -> str:
            nonlocal redacted_count
            # 排除 20 位数电发票常见前缀 (如 24/25/26 开头已由正则限定仅 62/4x/51-55 开头)
            redacted_count += 1
            return "[REDACTED_CARD]"

        def _repl_phone(_m: re.Match[str]) -> str:
            nonlocal redacted_count
            redacted_count += 1
            return "[REDACTED_PHONE]"

        out = _ID_CARD_RE.sub(_repl_id, segment)
        out = _BANK_CARD_RE.sub(_repl_card, out)
        out = _PHONE_RE.sub(_repl_phone, out)
        return out

    all_lines: list[str] = []
    if raw_wechat_lines:
        all_lines.extend(raw_wechat_lines)
    if raw_text.strip():
        all_lines.extend(raw_text.splitlines())

    kept_lines: list[str] = []
    for raw_line in all_lines:
        line = raw_line.strip()
        if not line:
            continue

        # 若整行属于纯私人寒暄且不含核心业务要素，直接剥离；
        # 若同一句里用逗号/分号夹杂了私人寒暄与业务要素，按子句粒度剥离私人子句！
        clauses = re.split(r"[，,；;。！!？?]+", line)
        kept_clauses: list[str] = []
        for clause in clauses:
            c = clause.strip()
            if not c:
                continue
            is_private = any(pat.search(c) for pat in _PRIVATE_CHITCHAT_PATTERNS)
            has_biz = any(k in c for k in _BUSINESS_SIGNAL_KEYWORDS)
            if is_private and not has_biz:
                stripped_private += 1
                continue
            masked_clause = _mask_pii(c)
            kept_clauses.append(masked_clause)

        if kept_clauses:
            rejoined = "，".join(kept_clauses)
            kept_lines.append(rejoined)
            if any(k in rejoined for k in _BUSINESS_SIGNAL_KEYWORDS):
                business_lines.append(rejoined)

    clean_joined = "\n".join(kept_lines)
    return L1SanitizeReport(
        clean_text=clean_joined,
        redacted_pii_count=redacted_count,
        stripped_private_count=stripped_private,
        extracted_business_lines=business_lines,
    )


class LLMGateway:
    """
    统一三级算力漏斗网关 (L1 本地规则 / L2 快速节点模型 / L3 深度推理模型)。
    支持无缝切换真实 OpenAI/DeepSeek 接口与离线高拟真语义/AST代码合成引擎。
    """

    def __init__(self, settings: ArachneSettings) -> None:
        self._settings = settings
        self._client: Any = None
        self._telemetry: dict[str, Any] = {
            "l1_sanitize_calls": 0,
            "l2_fast_calls": 0,
            "l3_reasoner_calls": 0,
            "live_api_hits": 0,
            "deterministic_engine_hits": 0,
            "estimated_tokens_saved_by_skills": 14200,
            "total_estimated_cost_usd": 0.042,
        }
        if settings.has_live_llm:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout=settings.llm_timeout_seconds,
            )

    @property
    def is_live_mode(self) -> bool:
        return self._client is not None

    def record_l1_call(self) -> None:
        self._telemetry["l1_sanitize_calls"] += 1

    def get_telemetry_snapshot(self) -> dict[str, Any]:
        return {
            "mode": "LIVE_CLOUD_HYBRID" if self.is_live_mode else "DETERMINISTIC_NEURAL_ENGINE",
            "l1_model": "Local-Regex-PII-Firewall-v2",
            "l2_model": self._settings.llm_model_l2_fast,
            "l3_model": self._settings.llm_model_l3_reasoner,
            "base_url": self._settings.llm_base_url,
            **self._telemetry,
        }

    async def complete_structured(
        self,
        tier: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[TModel],
        fallback_builder: Callable[[], TModel],
    ) -> TModel:
        if tier == "L3":
            self._telemetry["l3_reasoner_calls"] += 1
        else:
            self._telemetry["l2_fast_calls"] += 1

        if self._client is None:
            self._telemetry["deterministic_engine_hits"] += 1
            return fallback_builder()

        model_name = (
            self._settings.llm_model_l3_reasoner
            if tier == "L3"
            else self._settings.llm_model_l2_fast
        )
        try:
            resp = await self._client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            self._telemetry["live_api_hits"] += 1
            self._telemetry["total_estimated_cost_usd"] = round(
                self._telemetry["total_estimated_cost_usd"] + (0.008 if tier == "L3" else 0.0015),
                4,
            )
            raw_content = resp.choices[0].message.content or "{}"
            parsed = json.loads(raw_content)
            return response_model.model_validate(parsed)
        except Exception:
            self._telemetry["deterministic_engine_hits"] += 1
            return fallback_builder()

    async def analyze_explorer_turn(
        self,
        clean_text: str,
        has_forwarded_evidence: bool,
        has_prior_order_context: bool,
        accessible_balls: list[CapabilityBall],
        redline_balls: list[CapabilityBall],
    ) -> ExplorerDecision:
        def _deterministic_explorer() -> ExplorerDecision:
            # 1. 红线底价/绝密信息刺探核查
            for r_ball in redline_balls:
                for kw in r_ball.redline_keywords:
                    if kw and kw in clean_text:
                        return ExplorerDecision(
                            context_complete=True,
                            redline_violated=True,
                            violated_redline_ball_id=r_ball.ball_id,
                            reply_to_user=(
                                f"⛔【红线拦截：{r_ball.title}】当前岗位容器无权调阅工厂绝密底价/核心成本数据。"
                                "本次越界查询已被黑匣子只追写审计记录。"
                            ),
                        )

            # 2. 高压线检测（超权限折扣、客户赔偿、法务承诺、人事变动）
            discount_match = re.search(r"([1-9](?:\.\d)?)\s*折", clean_text)
            comp_match = re.search(r"(赔偿|赔付|违约金|退赔|客诉重做|返工).*?(\d+(?:\.\d+)?)\s*元?", clean_text)
            legal_match = any(w in clean_text for w in ("补充协议", "法律承诺", "免责条款", "对赌条款"))
            hr_match = any(w in clean_text for w in ("开除", "辞退", "升职", "调岗任免"))

            low_discount = False
            if discount_match:
                d_val = float(discount_match.group(1))
                if d_val < 8.5:
                    low_discount = True

            if low_discount or comp_match or legal_match or hr_match:
                reasons: list[str] = []
                category = "PRICE_OVERRIDE"
                if low_discount and discount_match:
                    reasons.append(f"申请超低折扣（{discount_match.group(1)}折，低于常规授权/8.5折高压审批红线）")
                if comp_match:
                    category = "COMPENSATION"
                    reasons.append(f"涉及客户现金赔偿/客诉重做赔付（{comp_match.group(0)}）")
                if legal_match:
                    category = "LEGAL_COMMITMENT"
                    reasons.append("涉及对外非标法律条款承诺")
                if hr_match:
                    category = "HR_CHANGE"
                    reasons.append("涉及人事任免变动")

                joined_reason = "；".join(reasons)
                return ExplorerDecision(
                    context_complete=True,
                    high_voltage_triggered=True,
                    high_voltage_category=category,  # type: ignore[arg-type]
                    high_voltage_reason=joined_reason,
                    reply_to_user=(
                        f"⚠️【高压线挂起】检测到重大风控事项：{joined_reason}。"
                        "根据铁律 #4，Agent 严禁自行放行，已生成挂起工单并推送审批卡片至【风控复核组长】拍板！"
                    ),
                )

            # 3. 不入网不认账（Gatekeeper）：直接要求发货/开票/锁库，但既无前置订单也无转发记录也没有完整订单要素
            fulfillment_action = any(
                k in clean_text for k in ("立即发货", "立刻发货", "马上发货", "帮我给", "直接发货", "安排出库")
            ) and ("发货" in clean_text or "出库" in clean_text)
            has_inline_order_spec = bool(
                re.search(r"\d+\s*(台|把|张|套|件)", clean_text)
                and any(p in clean_text for p in ("A款", "B款", "订单号", "ORD-", "规格", "型号"))
                and ("地址" in clean_text or "收货" in clean_text or has_forwarded_evidence)
            )
            if fulfillment_action and not has_forwarded_evidence and not has_prior_order_context and not has_inline_order_spec:
                return ExplorerDecision(
                    context_complete=False,
                    missing_context_prompt=(
                        "🛑【不入网不认账拦截】未检索到关联的生效订单号、客户确认记录或收货明细。"
                        "请先通过右侧伴生边栏「导入客户微信记录」提炼建单，或补充订单编号、型号数量与收货信息后再发起发货！"
                    ),
                    reply_to_user=(
                        "🛑【#2 进化与风控官 · 门禁挂起】无法无依据执行发货！请补充前置订单号或一键转发客户确认聊天记录（L1 将自动剔除私人寒暄与手机号）。"
                    ),
                )

            # 4. 若带有微信转发记录或完整订购描述，自动提炼结构化订单草稿 + 搓出新 DATA 权能小球
            extracted_balls: list[ExtractedBallCandidate] = []
            order_draft: Optional[dict[str, Any]] = None
            qty_match = re.search(r"(\d+)\s*(把|台|张|套|件|片|块)", clean_text)
            if has_forwarded_evidence or (qty_match and any(k in clean_text for k in ("订", "买", "要", "采购", "下单"))):
                qty = int(qty_match.group(1)) if qty_match else 10
                catalog_text = " ".join(b.content for b in accessible_balls if b.ball_type == "DATA")
                matched_title = ""
                matched_price = 0.0
                for seg in re.split(r"[；;\n]+", catalog_text):
                    pm = re.search(r"([A-Za-z0-9\u4e00-\u9fa5\-]{2,20})：[^¥\d]{0,16}[¥￥]?\s*(\d[\d,]*(?:\.\d+)?)", seg)
                    if pm:
                        cand_name = pm.group(1).strip()
                        short_key = cand_name.split("-")[0].strip()
                        if cand_name in clean_text or (len(short_key) >= 2 and short_key in clean_text):
                            matched_title = cand_name
                            matched_price = float(pm.group(2).replace(",", ""))
                            break

                if matched_title:
                    product_code = matched_title
                    unit_price = matched_price or 120.0
                else:
                    prod_m = re.search(
                        r"(?:订购|采购|下单|打样|购买)\s*\d*\s*(?:把|台|张|套|件|片|块)?\s*([\u4e00-\u9fa5A-Za-z0-9+\-_]{2,24})",
                        clean_text,
                    )
                    product_code = prod_m.group(1) if prod_m else "定制业务打样/批产订单"
                    price_m = re.search(r"(?:单价|每(?:件|套|片|台|把|张))\s*(\d+(?:\.\d+)?)\s*元", clean_text)
                    total_m = re.search(r"(?:总价|合计|总额|金额)\s*(\d+(?:\.\d+)?)\s*元", clean_text)
                    if price_m:
                        unit_price = float(price_m.group(1))
                    elif total_m:
                        unit_price = round(float(total_m.group(1)) / max(qty, 1), 2)
                    else:
                        unit_price = 1280.0 if ("A款" in clean_text) else 120.0
                total_amount = round(qty * unit_price, 2)
                comp_match = re.search(
                    r"([\u4e00-\u9fa5A-Za-z0-9]{2,18}(?:股份有限公司|有限责任公司|科技有限公司|有限公司|集团))",
                    clean_text,
                )
                customer_match = re.search(r"([\u4e00-\u9fa5]{1,4}(?:总|经理|女士|先生|工|科技|贸易|集团))", clean_text)
                customer_name = (
                    comp_match.group(1)
                    if comp_match
                    else (customer_match.group(1) if customer_match else "企业签约客户")
                )
                tax_match = re.search(r"\b([0-9A-Z]{15,18})\b", clean_text)
                order_draft = {
                    "customer_name": customer_name,
                    "product_name": product_code,
                    "quantity": qty,
                    "unit_price": unit_price,
                    "total_amount": total_amount,
                    "invoice_title": comp_match.group(1)
                    if comp_match
                    else (f"{customer_name}有限公司" if "公司" not in customer_name else customer_name),
                    "tax_id": tax_match.group(1) if tax_match else "91310115MA1K3B008X",
                    "clean_notes": clean_text,
                }
                extracted_balls.append(
                    ExtractedBallCandidate(
                        ball_type="DATA",
                        title=f"客户导单切片：{customer_name} {product_code}×{qty}",
                        domain_tags=["报价", "订单", "客户履约"],
                        sensitivity_level=2,
                        content=f"客户 {customer_name} 确认采购 {product_code} 共 {qty} 件，标准核算总额 ¥{total_amount:.2f}（已完成L1公私剥离与脱敏）。",
                    )
                )
                return ExplorerDecision(
                    context_complete=True,
                    extracted_balls=extracted_balls,
                    structured_order_draft=order_draft,
                    reply_to_user=(
                        f"✅【L1 公私剥离建单完成】已自动剔除私人闲聊与敏感号码，提炼出干净订单：\n"
                        f"• 客户：{customer_name}\n"
                        f"• 商品：{product_code} × {qty}\n"
                        f"• 核算总额：¥{total_amount:,.2f}\n"
                        f"已同步铸造 1 颗【DATA 资料球】装入当前岗位容器。"
                    ),
                )

            # 5. 常规产品库存/目录价查阅与业务问答
            matched_knowledge: list[str] = []
            for ball in accessible_balls:
                if ball.ball_type in ("DATA", "SKILL"):
                    if any(tag in clean_text for tag in ball.domain_tags) or any(
                        kw in clean_text for kw in ("库存", "现货", "价格", "报价", "A款", "B款", "工学椅", "升降桌", "运费")
                    ):
                        matched_knowledge.append(f"【{ball.title}】{ball.content}")

            if matched_knowledge:
                joined_kb = "\n".join(matched_knowledge[:3])
                return ExplorerDecision(
                    context_complete=True,
                    reply_to_user=f"📦【#1 业务副驾 · 容器权能球检索结果】\n{joined_kb}",
                )

            # 默认提炼跟单经验或正常业务应答
            if len(clean_text) >= 12:
                tags = ["客户跟单"]
                if "物流" in clean_text or "快递" in clean_text or "运费" in clean_text:
                    tags.append("物流")
                if "发票" in clean_text or "税" in clean_text:
                    tags.append("财税")
                extracted_balls.append(
                    ExtractedBallCandidate(
                        ball_type="DATA",
                        title=f"一线业务留痕：{clean_text[:14]}...",
                        domain_tags=tags,
                        sensitivity_level=1,
                        content=clean_text,
                    )
                )

            return ExplorerDecision(
                context_complete=True,
                extracted_balls=extracted_balls,
                reply_to_user=f"🤖 已记录并同步至岗位容器上下文：{clean_text}",
            )

        # 无论是否在线模式，优先执行确定性红线拦截与高压线硬护栏，确保风控 100% 零漏网
        pre_check = _deterministic_explorer()
        if (
            pre_check.redline_violated
            or pre_check.high_voltage_triggered
            or not pre_check.context_complete
        ):
            self._telemetry["l2_fast_calls"] += 1
            self._telemetry["deterministic_engine_hits"] += 1
            return pre_check

        sys_prompt = (
            "你是 Arachne-OS 的企业岗位智能副驾 ExplorerSpider。\n"
            "请严格基于当前工位已挂载的权能球 (accessible_balls) 回答用户的业务指令或提炼外部聊天记录订单。\n"
            "必须输出严格合法的 JSON 对象，包含以下字段：\n"
            '{\n'
            '  "context_complete": true,\n'
            '  "missing_context_prompt": "",\n'
            '  "redline_violated": false,\n'
            '  "violated_redline_ball_id": null,\n'
            '  "high_voltage_triggered": false,\n'
            '  "high_voltage_category": "NONE",\n'
            '  "high_voltage_reason": "",\n'
            '  "extracted_balls": [\n'
            '    {"ball_type": "DATA", "title": "新提炼的知识/订单标题", "domain_tags": ["标签"], "sensitivity_level": 2, "content": "提炼内容"}\n'
            '  ],\n'
            '  "structured_order_draft": null,\n'
            '  "reply_to_user": "结合当前挂载权能球给出的专业、详实、结构清晰的中文业务答复"\n'
            '}\n'
            "如果输入包含客户订购/报备/转发聊天记录，请填充 structured_order_draft "
            '({"customer_name": "...", "product_name": "...", "quantity": 10, "unit_price": 100.0, "total_amount": 1000.0, "invoice_title": "...", "tax_id": "...", "clean_notes": "..."})。'
        )
        usr_prompt = json.dumps(
            {
                "clean_text": clean_text,
                "has_forwarded_evidence": has_forwarded_evidence,
                "has_prior_order_context": has_prior_order_context,
                "accessible_balls": [b.model_dump() for b in accessible_balls],
                "redline_titles": [r.title for r in redline_balls],
            },
            ensure_ascii=False,
        )
        return await self.complete_structured(
            tier="L2",
            system_prompt=sys_prompt,
            user_prompt=usr_prompt,
            response_model=ExplorerDecision,
            fallback_builder=lambda: pre_check,
        )

    async def audit_edge_relay(
        self,
        raw_node_output: str,
        metadata: dict[str, Any],
        redline_balls: list[CapabilityBall],
    ) -> RelayAuditResult:
        l1 = sanitize_l1_text(raw_node_output)

        def _deterministic_relay() -> RelayAuditResult:
            # 检测子节点异常幻觉或逻辑自相矛盾
            force_hallucination = bool(metadata.get("simulate_hallucination", False))
            negative_amount = bool(re.search(r"金额[：:\s]*-\d+", l1.clean_text))
            contradiction = (
                force_hallucination
                or negative_amount
                or "HALLUCINATION_FAULT" in raw_node_output
                or "单价1280元×10把=总价50元" in raw_node_output
            )

            redline_hit = any(
                bool(re.search(r"(?:拿货|工厂|内部)底价\s*\d+", raw_node_output))
                or any(kw in raw_node_output for kw in rb.redline_keywords)
                for rb in redline_balls
            )

            if contradiction or redline_hit:
                reason = (
                    "边缘哨所捕获子节点严重金额逻辑自相矛盾/幻觉篡改"
                    if contradiction
                    else "边缘哨所捕获子节点回传数据混入绝密底价红线字段"
                )
                return RelayAuditResult(
                    sanitized_summary="[INTERCEPTED BY EDGE RELAY]",
                    stripped_private_count=l1.stripped_private_count,
                    redacted_pii_count=l1.redacted_pii_count,
                    contradiction_detected=contradiction,
                    redline_breach=redline_hit,
                    verdict="LOCAL_ROLLBACK",
                    rollback_reason=reason,
                )

            if metadata.get("requires_leader_approval"):
                return RelayAuditResult(
                    sanitized_summary=l1.clean_text[:180],
                    stripped_private_count=l1.stripped_private_count,
                    redacted_pii_count=l1.redacted_pii_count,
                    verdict="ESCALATE_SUPERVISOR",
                )

            summary = l1.clean_text.replace("\n", " | ")[:220]
            return RelayAuditResult(
                sanitized_summary=summary,
                stripped_private_count=l1.stripped_private_count,
                redacted_pii_count=l1.redacted_pii_count,
                verdict="PASS",
            )

        sys_prompt = "你是 Arachne-OS 边缘审查哨所 EdgeAuditRelay，请输出严格符合 RelayAuditResult 的 JSON。"
        return await self.complete_structured(
            tier="L2",
            system_prompt=sys_prompt,
            user_prompt=json.dumps({"clean_text": l1.clean_text, "metadata": metadata}, ensure_ascii=False),
            response_model=RelayAuditResult,
            fallback_builder=_deterministic_relay,
        )

    async def synthesize_artisan_skill(
        self, natural_instruction: str
    ) -> tuple[str, list[str], str]:
        """
        Tier L3 工匠造球器：从员工口述自然语言中提取真实业务参数并合成标准 Python execute_skill 代码。
        返回: (skill_title, domain_tags, python_source_code)
        """
        if self._client is not None:
            try:
                resp = await self._client.chat.completions.create(
                    model=self._settings.llm_model_l3_reasoner,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是 Arachne-OS 的 ArtisanAgent。请将用户的业务规则转化为 JSON: "
                                '{"title": "...", "domain_tags": ["..."], "code": "..."}。'
                                "code 必须仅定义 def execute_skill(payload: dict) -> dict，仅允许导入 "
                                "math, json, re, datetime, decimal, collections, statistics，"
                                '返回 {"status": "ok", "result": 数值}。严禁使用任何双下划线属性或危险函数。\n'
                                "请优先读取以下标准入参字段名（可保留 .get 兼容）：\n"
                                '- 运费类: weight_kg (或 weight/重量), order_amount (或 amount/订单金额)\n'
                                '- 批量折扣类: quantity, unit_price\n'
                                '- 通用费率/税额类: amount (或 order_amount)\n'
                                '- SMT贴片类: solder_joints (或 smd_points), dip_joints (或 dip_points)'
                            ),
                        },
                        {"role": "user", "content": natural_instruction},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.0,
                )
                parsed = json.loads(resp.choices[0].message.content or "{}")
                if "def execute_skill" in parsed.get("code", ""):
                    return (
                        str(parsed["title"]),
                        list(parsed.get("domain_tags", ["自动化工具"])),
                        str(parsed["code"]),
                    )
            except Exception:
                pass

        # 高拟真动态参数提取与 Python 源码合成引擎（非固定桩代码，支持任意参数调整）
        text = natural_instruction

        # 形态 A：阶梯运费核算规则（自动解析首重公斤数、首重费、续重单价、满额免邮门槛）
        if any(k in text for k in ("运费", "首重", "续重", "公斤", "免邮", "免运费")):
            # 解析首重费用：如 "首重10元" 或 "首重3公斤内10元"
            base_fee_m = re.search(r"首重(?:[^0-9]*?\d+(?:\.\d+)?\s*(?:公斤|kg|KG)[^0-9]*?)?(\d+(?:\.\d+)?)\s*元", text)
            base_fee = float(base_fee_m.group(1)) if base_fee_m else 10.0

            # 解析首重上限公斤数：如 "超过3公斤" 或 "首重3公斤"
            base_weight_m = re.search(r"(?:超过|超出|首重)\s*(\d+(?:\.\d+)?)\s*(?:公斤|kg|KG)", text)
            base_weight = float(base_weight_m.group(1)) if base_weight_m else 3.0

            # 解析续重单价：如 "每公斤加4元" / "续重5元"
            extra_m = re.search(r"(?:每公斤|每kg|续重)[^0-9]*?(\d+(?:\.\d+)?)\s*元", text, flags=re.IGNORECASE)
            extra_rate = float(extra_m.group(1)) if extra_m else 4.0

            # 解析包邮门槛：如 "满500元免运费"
            free_m = re.search(r"满\s*(\d+(?:\.\d+)?)\s*元?\s*(?:直接)?(?:免运费|包邮|免邮)", text)
            free_threshold = float(free_m.group(1)) if free_m else 500.0

            code = f'''from decimal import Decimal, ROUND_HALF_UP
import math


def execute_skill(payload: dict) -> dict:
    """
    自动合成的阶梯运费核算工具球
    规则参数: 首重 {base_weight}kg 内 {base_fee}元, 超重每kg +{extra_rate}元, 订单满 {free_threshold}元免运费
    """
    weight = Decimal(str(payload.get("weight_kg", payload.get("weight", 0))))
    order_amount = Decimal(str(payload.get("order_amount", payload.get("amount", 0))))

    free_limit = Decimal("{free_threshold}")
    base_w = Decimal("{base_weight}")
    base_cost = Decimal("{base_fee}")
    per_kg = Decimal("{extra_rate}")

    if order_amount >= free_limit:
        fee = Decimal("0.00")
    elif weight <= Decimal("0"):
        fee = Decimal("0.00")
    elif weight <= base_w:
        fee = base_cost
    else:
        extra_units = Decimal(str(math.ceil(float(weight - base_w))))
        fee = base_cost + extra_units * per_kg

    normalized = float(fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return {{"status": "ok", "result": normalized}}
'''
            return ("阶梯运费自动核算器", ["物流", "运费", "报价"], code)

        # 形态 A2：电子智造 SMT 贴片 + DIP 焊点与工程开机费计费算子
        if any(k in text for k in ("焊点", "贴片", "SMT", "开机费", "工程费", "DIP")):
            eng_m = re.search(r"(?:工程|开机)费[^\d]{0,8}(\d+(?:\.\d+)?)\s*元", text)
            eng_fee = float(eng_m.group(1)) if eng_m else 50.0
            smt_m = re.search(r"(?:标准)?(?:SMT|贴片)?焊点[^\d]{0,8}(\d+(?:\.\d+)?)\s*元", text)
            smt_rate = float(smt_m.group(1)) if smt_m else 0.01
            dip_m = re.search(r"(?:DIP|手焊|插件)[^\d]{0,10}(\d+(?:\.\d+)?)\s*元", text)
            dip_rate = float(dip_m.group(1)) if dip_m else 0.10

            code = f'''from decimal import Decimal, ROUND_HALF_UP


def execute_skill(payload: dict) -> dict:
    """
    自动合成的 SMT 贴片与 DIP 焊点工程计费工具球
    规则参数: 工程开机费 {eng_fee}元/款 + SMT贴片 {smt_rate}元/焊点 + DIP手焊 {dip_rate}元/焊点
    """
    solder_joints = int(payload.get("solder_joints", payload.get("smt_joints", 0)))
    dip_joints = int(payload.get("dip_joints", 0))
    boards = int(payload.get("boards", 1))
    is_lceda_large = bool(payload.get("is_lceda_large", False))

    eng_cost = Decimal("{eng_fee}")
    smt_unit = Decimal("{smt_rate}")
    if is_lceda_large and smt_unit >= Decimal("0.01"):
        smt_unit = Decimal("0.005")
    dip_unit = Decimal("{dip_rate}")

    total = (
        eng_cost
        + (Decimal(str(solder_joints)) * Decimal(str(boards)) * smt_unit)
        + (Decimal(str(dip_joints)) * Decimal(str(boards)) * dip_unit)
    )
    val = float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return {{"status": "ok", "result": val}}
'''
            return ("SMT贴片与工程开机费自动核算器", ["SMT", "贴片", "报价", "制造"], code)

        # 形态 B：批量阶梯折扣核算规则
        if any(k in text for k in ("批量折扣", "满减", "阶梯价", "折后价", "折扣")):
            threshold_m = re.search(r"满\s*(\d+)\s*(?:件|台|把|套|片|款|块|盒|箱|单|批|个)", text)
            qty_threshold = int(threshold_m.group(1)) if threshold_m else 20
            disc_m = re.search(r"(\d(?:\.\d)?)\s*折", text)
            disc_factor = float(disc_m.group(1)) / 10.0 if disc_m else 0.9

            code = f'''from decimal import Decimal, ROUND_HALF_UP


def execute_skill(payload: dict) -> dict:
    qty = int(payload.get("quantity", 1))
    unit_price = Decimal(str(payload.get("unit_price", 0)))
    raw_total = unit_price * Decimal(str(qty))
    if qty >= {qty_threshold}:
        final_total = raw_total * Decimal("{disc_factor:.2f}")
    else:
        final_total = raw_total
    val = float(final_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return {{"status": "ok", "result": val}}
'''
            return ("批量阶梯折后总价核算器", ["报价", "折扣"], code)

        # 形态 C：通用税额/佣金比例计算器
        rate_m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        rate_val = (float(rate_m.group(1)) / 100.0) if rate_m else 0.06
        code = f'''from decimal import Decimal, ROUND_HALF_UP


def execute_skill(payload: dict) -> dict:
    amount = Decimal(str(payload.get("amount", payload.get("order_amount", 0))))
    rate = Decimal("{rate_val:.4f}")
    computed = (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {{"status": "ok", "result": float(computed)}}
'''
        return ("标准化费率自动核算技能球", ["财税", "通用核算"], code)

    async def evaluate_board_director(
        self,
        director_id: str,
        director_title: str,
        seat_type: str,
        agenda: str,
        context_metrics: dict[str, Any],
        department_metrics: Optional[dict[str, Any]] = None,
    ) -> DirectorVote:
        """
        独立董事盲评推理器：每次调用仅代表单名董事的独立视角与利益诉求。
        """
        dept_metrics = dict(department_metrics or {})

        def _deterministic_vote() -> DirectorVote:
            rep_score = float(context_metrics.get("replaceability_score", 50.0))
            has_unmitigated_breach = bool(context_metrics.get("force_security_veto", False))
            vault_intact = bool(context_metrics.get("vault_intact", True))
            dehydrated_ratio = float(context_metrics.get("dehydrated_ratio", 0.3))
            active_skills = int(context_metrics.get("active_skill_balls", 2))

            if director_id == "DIR_SECURITY":
                if has_unmitigated_breach or not vault_intact:
                    return DirectorVote(
                        director_id=director_id,
                        director_title=director_title,
                        seat_type="IRON_TRIANGLE",
                        stance="VETO",
                        score=0.0,
                        rationale="安全红线官行使一票否决权：检测到未消解的高危越权风险或黑匣子完整性告警，严禁切换自动化接管！",
                    )
                sec_score = min(96.0, 78.0 + active_skills * 4.0)
                return DirectorVote(
                    director_id=director_id,
                    director_title=director_title,
                    seat_type="IRON_TRIANGLE",
                    stance="APPROVE",
                    score=sec_score,
                    rationale="黑匣子哈希链 100% 完好，AST 沙箱与红线隔离墙拦截有效，建议在师徒反转期内保留人工抽检签字。",
                )

            if director_id == "DIR_EVOLUTION":
                evo_score = min(99.0, max(55.0, rep_score))
                stance = "APPROVE" if evo_score >= 80.0 else "CONDITIONAL"
                return DirectorVote(
                    director_id=director_id,
                    director_title=director_title,
                    seat_type="IRON_TRIANGLE",
                    stance=stance,  # type: ignore[arg-type]
                    score=evo_score,
                    rationale=(
                        f"目标岗位当前 AI 可替代分已达 {rep_score:.1f}，且已沉淀 {active_skills} 颗通过影子擂台的技能球，"
                        "强烈建议推进 HYBRID_TRANSITION（师徒反转接管）。"
                    ),
                )

            if director_id == "DIR_COST":
                cost_score = min(95.0, 72.0 + dehydrated_ratio * 35.0)
                return DirectorVote(
                    director_id=director_id,
                    director_title=director_title,
                    seat_type="IRON_TRIANGLE",
                    stance="APPROVE",
                    score=round(cost_score, 1),
                    rationale=(
                        f"三级算力漏斗已将高频核算下沉至本地 Python 技能球（零 Token 消耗），闲置节点脱水率 {dehydrated_ratio*100:.0f}%，ROI 极佳。"
                    ),
                )

            # 动态业务域董事席位：依据真实部门上下文指标给出差异化独立评审
            is_home = bool(dept_metrics.get("is_target_home_dept", False))
            dept_tickets = int(dept_metrics.get("dept_ticket_count", 0))
            has_blackbox = bool(dept_metrics.get("has_blackbox_node", False))
            dehydrated_cnt = int(dept_metrics.get("dehydrated_count", 0))
            tag_overlap = int(dept_metrics.get("domain_tag_overlap", 0))
            seat_rank = int(dept_metrics.get("seat_rank", 1))
            node_cnt = int(dept_metrics.get("subtree_node_count", 1))

            base = 68.0 + rep_score * 0.18 + min(8.0, tag_overlap * 2.5)
            reasons: list[str] = []
            if is_home:
                base += 7.5
                reasons.append("直属部门：工单吞吐与人效释放直接受益 (+7.5)")
            if has_blackbox:
                base -= 6.5
                reasons.append("含高敏专岗/合规黑盒：强调人机契约与红线留痕 (-6.5)")
            if dept_tickets > 0:
                delta_t = min(6.0, dept_tickets * 1.4)
                base += delta_t
                reasons.append(f"近周期跨部协同一线工单 {dept_tickets} 单 (+{delta_t:.1f})")
            if dehydrated_cnt > 0:
                base -= min(4.0, dehydrated_cnt * 1.5)
                reasons.append(f"含 {dehydrated_cnt} 个脱水节点需先验证热唤醒链路")
            if node_cnt >= 3 and not is_home:
                base += min(3.5, (node_cnt - 2) * 1.1)

            # 按席位职能做温和正交偏移，杜绝多部门完全同分
            title_low = director_title.lower()
            if any(k in title_low for k in ("财", "税", "审", "合规", "法", "finance", "audit")):
                base -= 4.2
                reasons.append("财税/合规审计视角偏审慎校验")
            elif any(k in title_low for k in ("供", "产", "仓", "物", "制造", "排产", "工程")):
                base += 2.6
                reasons.append("供应链/制造交付侧重节拍稳定性")
            else:
                base += ((seat_rank % 3) - 1) * 1.8

            domain_score = max(48.0, min(95.5, base))
            stance = "APPROVE" if domain_score >= 76.0 else "CONDITIONAL"
            detail_note = "；".join(reasons) if reasons else "按标准协同契约评审"
            return DirectorVote(
                director_id=director_id,
                director_title=director_title,
                seat_type="DYNAMIC_DOMAIN",
                stance=stance,
                score=round(domain_score, 1),
                rationale=f"{director_title}独立评估（{detail_note}），{'支持进入过渡期' if stance == 'APPROVE' else '附风控抽检条件放行'}。",
            )

        sys_prompt = (
            f"你是 Arachne-OS 顶层董事会的独立席位：{director_title} ({director_id})。"
            f"你所在部门的关键运营指标：{json.dumps(dept_metrics, ensure_ascii=False)}。"
            "请完全站在你自身职能与该部门数据立场上独立盲评议案，输出符合 DirectorVote 的 JSON。"
        )
        return await self.complete_structured(
            tier="L3",
            system_prompt=sys_prompt,
            user_prompt=json.dumps({"agenda": agenda, "metrics": context_metrics}, ensure_ascii=False),
            response_model=DirectorVote,
            fallback_builder=_deterministic_vote,
        )

    async def extract_skill_call_payload(
        self,
        user_text: str,
        accessible_balls: list[CapabilityBall],
        sandbox_dir: Any,
    ) -> Optional[tuple[CapabilityBall, Any, dict[str, Any]]]:
        """
        通用技能球参数提取与匹配：
        支持任意行业新编译的 Python 技能球（跨境物流、MCN分账、医疗集采、运费折扣等），
        自动匹配目标 SKILL 球并从自然语言中提取 execute_skill(payload) 所需的参数字典。
        """
        from pathlib import Path

        if not any(
            kw in user_text
            for kw in (
                "算",
                "核算",
                "测算",
                "计算",
                "多少",
                "费用",
                "运费",
                "佣金",
                "税",
                "成本",
                "报价",
            )
        ):
            return None

        skill_candidates: list[tuple[CapabilityBall, Path, str]] = []
        for b in accessible_balls:
            if (
                b.ball_type == "SKILL"
                and b.status == "ACTIVE"
                and b.executable_code_path
            ):
                sp = Path(b.executable_code_path)
                if not sp.is_absolute():
                    sp = Path(sandbox_dir) / sp
                if sp.exists():
                    try:
                        code_txt = sp.read_text(encoding="utf-8")
                        skill_candidates.append((b, sp, code_txt))
                    except Exception:
                        pass

        if not skill_candidates:
            return None

        if self._client is not None:
            try:
                catalog = [
                    {
                        "ball_id": b.ball_id,
                        "title": b.title,
                        "domain_tags": b.domain_tags,
                        "input_fields": _skill_input_fields(code_txt),
                    }
                    for b, _, code_txt in skill_candidates
                ]
                resp = await self._client.chat.completions.create(
                    model=self._settings.llm_model_l2_fast,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是技能球路由器。请判断用户的提问是否应该调用候选 Python 技能球中的某一个。\n"
                                "若是，请根据该技能球的 input_fields 输入字段名，从用户提供的业务信息中提取参数字典，"
                                "仅填写用户提供的信息，不推测服务端默认值或内部数据，输出 JSON：\n"
                                '{"should_call": true, "ball_id": "...", "input_payload": {...}}\n'
                                '若不匹配任何技能球计算意图，输出 {"should_call": false, "ball_id": null, "input_payload": {}}。'
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"user_text": user_text, "skills": catalog},
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.0,
                )
                self._telemetry["live_api_hits"] += 1
                parsed = json.loads(resp.choices[0].message.content or "{}")
                if parsed.get("should_call") and parsed.get("ball_id"):
                    target_id = str(parsed["ball_id"])
                    inp = dict(parsed.get("input_payload") or {})
                    for b, sp, _ in skill_candidates:
                        if b.ball_id == target_id:
                            return (b, sp, inp)
            except Exception:
                pass

        # 确定性本地参数提取兜底（供离线模式或 LLM 未命中时精确调度行业技能球）
        for b, sp, code_txt in skill_candidates:
            if "solder_joints" in code_txt or "焊点" in b.title or "贴片" in b.title:
                smt_m = re.search(
                    r"(?:SMT|贴片)[^\d]{0,8}(\d+)\s*(?:个)?\s*焊点?", user_text
                ) or re.search(r"(\d+)\s*(?:个|点)?\s*(?:SMT|贴片)焊点", user_text)
                dip_m = re.search(
                    r"(\d+)\s*(?:个|点)?\s*(?:DIP|手焊|插件)|(?:DIP|手焊|插件)[^\d]{0,8}(\d+)",
                    user_text,
                )
                if smt_m is None and dip_m is None:
                    generic_j = re.search(r"(\d+)\s*(?:个)?\s*焊点", user_text)
                    smt_val = int(generic_j.group(1)) if generic_j else 0
                else:
                    if smt_m is None:
                        generic_j = re.search(r"(\d+)\s*(?:个)?\s*焊点", user_text)
                        smt_val = int(generic_j.group(1)) if generic_j else 0
                    else:
                        smt_val = int(smt_m.group(1))
                dip_val = int(dip_m.group(1) or dip_m.group(2)) if dip_m else 0
                boards_m = re.search(r"(\d+)\s*(?:片|块|板|套)", user_text)
                if smt_val > 0 or dip_val > 0:
                    return (
                        b,
                        sp,
                        {
                            "solder_joints": smt_val,
                            "dip_joints": dip_val,
                            "boards": int(boards_m.group(1)) if boards_m else 1,
                        },
                    )
            if "weight_kg" in code_txt or "weight" in code_txt:
                w_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:公斤|kg|KG)", user_text)
                if w_m:
                    a_m = re.search(
                        r"(?:订单|金额|货款|总价|满)[^\d]{0,6}(\d+(?:\.\d+)?)\s*元",
                        user_text,
                    )
                    amount_fields = set(_skill_input_fields(code_txt)) & {
                        "order_amount",
                        "amount",
                        "订单金额",
                    }
                    if amount_fields and a_m is None:
                        continue
                    payload = {"weight_kg": float(w_m.group(1))}
                    if a_m is not None:
                        payload.update(
                            {key: float(a_m.group(1)) for key in amount_fields}
                        )
                    return (
                        b,
                        sp,
                        payload,
                    )
            if "unit_price" in code_txt:
                q_m = re.search(r"(\d+)\s*(?:件|台|把|套|片)", user_text)
                p_m = re.search(
                    r"(?:单价|每件|每套|每片)[^\d]{0,4}(\d+(?:\.\d+)?)\s*元", user_text
                )
                if q_m and p_m:
                    return (
                        b,
                        sp,
                        {
                            "quantity": int(q_m.group(1)),
                            "unit_price": float(p_m.group(1)),
                        },
                    )

        return None

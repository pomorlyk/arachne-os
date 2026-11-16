from __future__ import annotations

import copy
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from core.schemas import BlackBoxTaskCard, HumanBlackBoxContract

# 支持 20 位全数字数电发票号 或 8 位传统增值税专用发票号
_INVOICE_NO_RE = re.compile(r"^(?:\d{8}|\d{20})$")


class WorkflowConflictError(RuntimeError):
    """A terminal workflow decision cannot be overwritten."""


def positive_money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("金额必须为正的有限数字") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("金额必须为正的有限数字")
    return amount


class HumanBlackBoxManager:
    """
    人即黑盒 API 封装器 (HumanBlackBoxTool)：
    1. InputMinimizer：向真人操作员投喂任务卡片时，严格按契约白名单字段裁剪，剥离一切无关商业秘密与聊天上下文；
    2. OutputValidator：对真人返回结果执行格式正则与金额一致性强校验，不合格当场打回重填。
    """

    def __init__(self) -> None:
        self._contracts: dict[str, HumanBlackBoxContract] = {}
        self._cards: dict[str, BlackBoxTaskCard] = {}
        self._register_builtin_contracts()

    def _register_builtin_contracts(self) -> None:
        self.register_contract(
            HumanBlackBoxContract(
                contract_id="CONTRACT_LEADER_HV_APPROVAL",
                slot_id="ROLE_LEADER",
                task_name="基层组长高压线风控拍板",
                allowed_input_fields=[
                    "ticket_id",
                    "initiator_name",
                    "customer_name",
                    "product_summary",
                    "high_voltage_category",
                    "high_voltage_reason",
                    "requested_amount",
                    "invoice_title",
                    "tax_id",
                ],
                required_output_schema={
                    "decision": "APPROVE | REJECT",
                    "approved_amount": "positive_decimal",
                    "comment": "non_empty_string",
                },
            )
        )
        self.register_contract(
            HumanBlackBoxContract(
                contract_id="CONTRACT_FINANCE_TAX_DISK",
                slot_id="ROLE_BLACKBOX_FINANCE",
                task_name="物理加密税控盘增值税开票黑盒",
                allowed_input_fields=[
                    "ticket_id",
                    "invoice_title",
                    "tax_id",
                    "amount",
                ],
                required_output_schema={
                    "invoice_number": "^(\\d{8}|\\d{20})$",
                    "billed_amount": "must_equal_input_amount",
                    "attachment_ref": "non_empty_string",
                },
            )
        )
        self.register_contract(
            HumanBlackBoxContract(
                contract_id="CONTRACT_LEGAL_COMPLIANCE",
                slot_id="ROLE_BLACKBOX_LEGAL",
                task_name="合同非标免责与违约条款法务审查黑盒",
                allowed_input_fields=[
                    "ticket_id",
                    "customer_name",
                    "clause_summary",
                    "contract_amount",
                ],
                required_output_schema={
                    "decision": "APPROVE | REJECT",
                    "legal_seal_no": "non_empty_string",
                    "comment": "non_empty_string",
                },
            )
        )

    def bind_role_slots(
        self,
        *,
        leader_slot_id: str | None = None,
        finance_slot_id: str | None = None,
        legal_slot_id: str | None = None,
    ) -> None:
        """按当前企业实际槽位动态绑定内置人机黑盒契约的目标岗位。"""
        if leader_slot_id and "CONTRACT_LEADER_HV_APPROVAL" in self._contracts:
            self._contracts["CONTRACT_LEADER_HV_APPROVAL"].slot_id = leader_slot_id
        if finance_slot_id and "CONTRACT_FINANCE_TAX_DISK" in self._contracts:
            self._contracts["CONTRACT_FINANCE_TAX_DISK"].slot_id = finance_slot_id
        if legal_slot_id and "CONTRACT_LEGAL_COMPLIANCE" in self._contracts:
            self._contracts["CONTRACT_LEGAL_COMPLIANCE"].slot_id = legal_slot_id

    def export_state(self) -> dict[str, Any]:
        return {
            "contracts": [c.model_dump() for c in self._contracts.values()],
            "cards": [c.model_dump() for c in self._cards.values()],
        }

    def restore_state(self, state: dict[str, Any] | None) -> None:
        if not state:
            return
        for raw_c in state.get("contracts", []):
            c = HumanBlackBoxContract(**raw_c)
            self._contracts[c.contract_id] = c
        self._cards = {}
        for raw_card in state.get("cards", []):
            card = BlackBoxTaskCard(**raw_card)
            self._cards[card.card_id] = card

    def register_contract(self, contract: HumanBlackBoxContract) -> None:
        self._contracts[contract.contract_id] = contract

    def get_contract(self, contract_id: str) -> HumanBlackBoxContract:
        return self._contracts[contract_id]

    def minimize_input(
        self, contract_id: str, full_business_context: dict[str, Any]
    ) -> dict[str, Any]:
        contract = self.get_contract(contract_id)
        return {
            field: full_business_context[field]
            for field in contract.allowed_input_fields
            if field in full_business_context
        }

    def dispatch_card(
        self,
        ticket_id: str,
        contract_id: str,
        card_kind: str,
        full_business_context: dict[str, Any],
        target_slot_id_override: str | None = None,
    ) -> BlackBoxTaskCard:
        contract = self.get_contract(contract_id)
        minimized = self.minimize_input(contract_id, full_business_context)
        card = BlackBoxTaskCard(
            card_id=f"CARD_{uuid.uuid4().hex[:8].upper()}",
            ticket_id=ticket_id,
            contract_id=contract_id,
            target_slot_id=target_slot_id_override or contract.slot_id,
            card_kind=card_kind,  # type: ignore[arg-type]
            minimized_payload=minimized,
            status="PENDING",
        )
        self._cards[card.card_id] = card
        return card

    def get_card(self, card_id: str) -> BlackBoxTaskCard:
        if card_id not in self._cards:
            raise KeyError(f"BlackBoxTaskCard {card_id} not found")
        return self._cards[card_id]

    def list_cards(
        self, target_slot_id: str | None = None, status: str | None = None
    ) -> list[BlackBoxTaskCard]:
        items = list(self._cards.values())
        if target_slot_id:
            items = [c for c in items if c.target_slot_id == target_slot_id]
        if status:
            items = [c for c in items if c.status == status]
        return items

    def submit_and_validate(
        self, card_id: str, submitted_output: dict[str, Any]
    ) -> tuple[bool, list[str], BlackBoxTaskCard]:
        card = self.get_card(card_id)
        if card.status != "PENDING":
            if card.submitted_output == submitted_output:
                return True, [], card
            raise WorkflowConflictError("已完成的黑盒任务卡不允许修改；请创建独立的更正流程")
        errors: list[str] = []

        if card.card_kind == "LEADER_APPROVAL":
            decision = str(submitted_output.get("decision", "")).upper()
            comment = str(submitted_output.get("comment", "")).strip()
            if decision not in ("APPROVE", "REJECT"):
                errors.append("审批决策必须为 APPROVE（批准）或 REJECT（驳回）")
            if not comment:
                errors.append("组长审批意见（comment）不能为空")
            if decision == "APPROVE":
                try:
                    requested = positive_money(card.minimized_payload.get("requested_amount"))
                    approved = positive_money(submitted_output.get("approved_amount"))
                    if approved > requested:
                        errors.append("核准金额不得超过申请金额")
                except ValueError as exc:
                    errors.append(str(exc))
            if errors:
                card.validation_errors = errors
                return False, errors, card

            card.validation_errors = []
            card.submitted_output = copy.deepcopy(submitted_output)
            card.status = "APPROVED" if decision == "APPROVE" else "REJECTED"
            return True, [], card

        if card.card_kind == "LEGAL_REVIEW":
            decision = str(submitted_output.get("decision", "")).upper()
            seal_no = str(submitted_output.get("legal_seal_no", "")).strip()
            comment = str(submitted_output.get("comment", "")).strip()
            if decision not in ("APPROVE", "REJECT"):
                errors.append("法务审查决策必须为 APPROVE 或 REJECT")
            if not seal_no.startswith("LEG-"):
                errors.append("法务电子会签章编号（legal_seal_no）必须以 LEG- 开头")
            if not comment:
                errors.append("法务审查批注意见（comment）不能为空")
            if errors:
                card.validation_errors = errors
                return False, errors, card

            card.validation_errors = []
            card.submitted_output = copy.deepcopy(submitted_output)
            card.status = "APPROVED" if decision == "APPROVE" else "REJECTED"
            return True, [], card

        # 财务税控盘黑盒输出强校验 (CONTRACT_FINANCE_TAX_DISK)
        inv_no = str(submitted_output.get("invoice_number", "")).strip()
        if not _INVOICE_NO_RE.match(inv_no):
            errors.append(
                f"发票号格式非法（收到 '{inv_no}'）：必须为 20 位全数字数电发票号或 8 位全数字增值税发票号"
            )

        expected_amt_raw = card.minimized_payload.get("amount", 0)
        submitted_amt_raw = submitted_output.get("billed_amount", None)
        try:
            expected_dec = positive_money(expected_amt_raw)
            actual_dec = positive_money(submitted_amt_raw)
            if expected_dec != actual_dec:
                errors.append(
                    f"实开发票金额（¥{actual_dec:.2f}）与核准开票金额（¥{expected_dec:.2f}）不一致"
                )
        except ValueError:
            errors.append("实开与核准开票金额必须为正的有限数字")

        attachment_ref = str(submitted_output.get("attachment_ref", "")).strip()
        if not attachment_ref:
            errors.append("必须附带税控盘电子回执/PDF文件标识（attachment_ref）")

        if errors:
            card.validation_errors = errors
            return False, errors, card

        card.validation_errors = []
        card.submitted_output = copy.deepcopy(submitted_output)
        card.status = "COMPLETED"
        return True, [], card


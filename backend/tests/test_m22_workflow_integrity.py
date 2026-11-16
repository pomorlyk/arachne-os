from __future__ import annotations
import asyncio
from pathlib import Path
import pytest
from core.human_tool import HumanBlackBoxManager
from core.schemas import BoardResolution, WorkTicket
from tests.test_m3_spider_and_relay import _build_m3_fixture
from tests.test_m4_evolution_and_board import _build_m4_fixture


def approval(manager):
    return manager.dispatch_card('T1', 'CONTRACT_LEADER_HV_APPROVAL', 'LEADER_APPROVAL',
        {'requested_amount': 100, 'invoice_title': '客户公司', 'tax_id': 'verified-tax'},
        target_slot_id_override='SLOT_LEADER_01')


def output(amount=100):
    return {'decision': 'APPROVE', 'approved_amount': amount, 'comment': '已核验'}


async def ticket(store, initiator='emp_chen'):
    await store.upsert_ticket(WorkTicket(ticket_id='T1', subtree_root_id='subtree_quote',
        node_id='node_chen', initiator_id=initiator, slot_id='SLOT_SALES_01',
        facade_bot='GOVERNANCE', summary='审批', status='PENDING_LEADER_APPROVAL'))


@pytest.mark.parametrize('amount', [None, -1, 0, 'NaN', 'Infinity', 101])
def test_approval_positive_finite_bounded_money(amount):
    manager = HumanBlackBoxManager()
    card = approval(manager)
    valid, errors, card = manager.submit_and_validate(card.card_id, output(amount))
    assert not valid and errors
    assert card.status == 'PENDING'


def test_card_terminal_immutable_replay():
    manager = HumanBlackBoxManager()
    card = approval(manager)
    assert manager.submit_and_validate(card.card_id, output())[0]
    assert manager.submit_and_validate(card.card_id, output())[0]
    with pytest.raises(RuntimeError):
        manager.submit_and_validate(card.card_id, {'decision': 'REJECT', 'comment': '撤销'})
    assert card.status == 'APPROVED'


@pytest.mark.asyncio
async def test_submission_target_role_and_separate_requester(tmp_path):
    spider, store, vault, pulse = await _build_m3_fixture(tmp_path)
    try:
        card = approval(spider._human_tools)
        await ticket(store)
        with pytest.raises(PermissionError):
            await spider.handle_human_tool_submission('emp_chen', card.card_id, output())
        await ticket(store, 'leader_li')
        with pytest.raises(PermissionError):
            await spider.handle_human_tool_submission('leader_li', card.card_id, output())
        assert card.status == 'PENDING'
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_concurrent_approval_replay_restored_next_card(tmp_path):
    spider, store, vault, pulse = await _build_m3_fixture(tmp_path)
    try:
        card = approval(spider._human_tools)
        await ticket(store)
        results = await asyncio.gather(*[spider.handle_human_tool_submission('leader_li', card.card_id, output()) for _ in range(3)])
        ids = {r['next_card'].card_id for r in results}
        assert len(ids) == 1
        assert len(spider._human_tools.list_cards()) == 2
        saved = spider.export_state()
        spider.reset_workspace_state()
        spider.restore_state(saved)
        replay = await spider.handle_human_tool_submission('leader_li', card.card_id, output())
        assert replay['next_card'].card_id in ids
        assert len(spider._human_tools.list_cards()) == 2
        with pytest.raises(RuntimeError):
            await spider.handle_human_tool_submission('leader_li', card.card_id, output(90))
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_order_linkage_survives_restore_without_unrelated_order_bypass(tmp_path):
    spider, store, vault, pulse = await _build_m3_fixture(tmp_path)
    try:
        imported = await spider.process_inbound_turn('emp_chen', 'COPILOT', '', ['王总确认下单10把A款人体工学椅，收货地址上海张江高科'])
        draft = imported['ticket'].sanitized_payload['order_draft']
        assert draft['order_id']
        unrelated = await spider.process_inbound_turn('emp_chen', 'COPILOT', '帮我给赵总立刻发货50台')
        assert unrelated['ticket'].status == 'PENDING_CONTEXT'
        state = spider.export_state()
        spider.reset_workspace_state()
        spider.restore_state(state)
        wrong = await spider.process_inbound_turn('emp_chen', 'COPILOT', f"帮我给赵总立刻发货，订单号{draft['order_id']}")
        assert wrong['ticket'].status == 'PENDING_CONTEXT'
        linked = await spider.process_inbound_turn('emp_chen', 'COPILOT', f"帮我给{draft['customer_name']}立刻发货，订单号{draft['order_id']}")
        assert linked['ticket'].status != 'PENDING_CONTEXT'
    finally:
        await pulse.drain_background_tasks()
        await store.close()


@pytest.mark.asyncio
async def test_topology_all_parent_spans_bounded_no_invented_tasks(tmp_path):
    spider, store, vault, pulse = await _build_m3_fixture(tmp_path)
    try:
        before = len(await store.list_tickets())
        await spider.inject_concurrent_subtasks_and_check_span('node_aspect_quote', 31)
        nodes = await store.list_nodes()
        for parent in nodes:
            assert len([n for n in nodes if n.parent_id == parent.node_id]) <= 5
        assert len(await store.list_tickets()) == before
        assert all(n.active_load == 0 for n in nodes if n.node_id.startswith('node_subworker_'))
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_scoring_evidence_and_employee_independence(tmp_path):
    _, board, scoring, containers, store, vault = await _build_m4_fixture(tmp_path)
    try:
        slot = containers.get_slot(containers.get_profile('emp_chen').slot_id)
        old = slot.shadow_agreement_rate
        await scoring.on_shadow_trial_completed('emp_chen', slot.slot_id, True)
        assert slot.shadow_agreement_rate == old
        slot.replaceability_score = 10
        low = scoring.recompute_employee_performance('emp_chen')
        slot.replaceability_score = 95
        assert scoring.recompute_employee_performance('emp_chen') == low
        await scoring.award_evolution_architect_bonus('emp_chen', '已验证技能')
        assert slot.shadow_agreement_rate == old
        state = scoring.export_state()
        scoring.calibrator.calibrate_on_boss_feedback(True)
        scoring.restore_state(state)
        assert scoring.export_state() == state
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_routine_chat_does_not_create_agreement(tmp_path):
    spider, store, vault, pulse = await _build_m3_fixture(tmp_path)
    calls = []
    async def hook(*args):
        calls.append(args)
    spider.bind_scoring_hooks(hook, hook)
    try:
        await spider.process_inbound_turn('emp_chen', 'COPILOT', '请查询A款工学椅报价')
        await pulse.drain_background_tasks()
        assert calls == []
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_boss_eligibility_immutable_decision_and_single_calibration(tmp_path):
    _, board, scoring, containers, store, vault = await _build_m4_fixture(tmp_path)
    try:
        slot = containers.get_slot(containers.get_profile('emp_chen').slot_id)
        res = BoardResolution(resolution_id='R1', agenda='接管', target_slot_id=slot.slot_id,
            weighted_score=90, recommended_action='MAINTAIN_HUMAN',
            preference_weights_snapshot=scoring.calibrator.snapshot(), votes=[], executive_brief='继续采样')
        board._resolutions.append(res)
        with pytest.raises(ValueError):
            await board.apply_boss_decision('R1', True)
        slot.replaceability_score = 96
        res.recommended_action = 'APPROVE_HYBRID_TRANSITION'
        await board.apply_boss_decision('R1', True)
        first = scoring.calibrator.snapshot()
        await board.apply_boss_decision('R1', True)
        assert scoring.calibrator.snapshot() == first
        state = board.export_state()
        board.restore_state(state)
        with pytest.raises(RuntimeError):
            await board.apply_boss_decision('R1', False)
        assert slot.occupant_type == 'HYBRID_TRANSITION'
        assert board.list_resolutions()[0].status == 'APPROVED'
    finally:
        await store.close()


@pytest.mark.parametrize('amount', ['NaN', 'Infinity', -1, 0, 100.001])
def test_invoice_rejects_nonfinite_nonpositive_or_inexact_amount(amount):
    manager = HumanBlackBoxManager()
    card = manager.dispatch_card('T1', 'CONTRACT_FINANCE_TAX_DISK', 'FINANCE_INVOICE', {'amount': 100})
    valid, errors, _ = manager.submit_and_validate(card.card_id,
        {'invoice_number': '12345678', 'billed_amount': amount, 'attachment_ref': 'receipt'})
    assert not valid and errors
    assert card.status == 'PENDING'


@pytest.mark.asyncio
async def test_card_role_mismatch_and_explicit_supervisor_grant(tmp_path):
    spider, store, vault, pulse = await _build_m3_fixture(tmp_path)
    try:
        card = approval(spider._human_tools)
        await ticket(store)
        with pytest.raises(PermissionError):
            await spider.handle_human_tool_submission('boss_lin', card.card_id, output())
        leader = spider._containers.get_profile('leader_li')
        leader.role_view = 'employee'
        with pytest.raises(PermissionError):
            await spider.handle_human_tool_submission('leader_li', card.card_id, output())
        spider.bind_human_supervisor_authorizer(lambda actor, slot: actor == 'boss_lin' and slot == card.target_slot_id)
        accepted = await spider.handle_human_tool_submission('boss_lin', card.card_id, output())
        fin_card = accepted['next_card']
        assert accepted['accepted']
        current = await store.get_ticket('T1')
        current.initiator_id = 'fin_wang'
        await store.upsert_ticket(current)
        with pytest.raises(PermissionError):
            await spider.handle_human_tool_submission('fin_wang', fin_card.card_id,
                {'invoice_number': '12345678', 'billed_amount': 100, 'attachment_ref': 'receipt'})
        assert fin_card.status == 'PENDING'
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_board_rejects_nan_score_despite_transition_recommendation(tmp_path):
    _, board, scoring, containers, store, vault = await _build_m4_fixture(tmp_path)
    try:
        slot = containers.get_slot(containers.get_profile('emp_chen').slot_id)
        slot.replaceability_score = 96
        board._resolutions.append(BoardResolution(resolution_id='R_NAN', agenda='接管',
            target_slot_id=slot.slot_id, weighted_score=float('nan'),
            recommended_action='APPROVE_HYBRID_TRANSITION',
            preference_weights_snapshot=scoring.calibrator.snapshot(), votes=[], executive_brief='无有效评分'))
        with pytest.raises(ValueError):
            await board.apply_boss_decision('R_NAN', True)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_unstructured_forward_cannot_become_verified_order(tmp_path):
    spider, store, vault, pulse = await _build_m3_fixture(tmp_path)
    try:
        result = await spider.process_inbound_turn('emp_chen', 'COPILOT', '', ['周末见，下周再聊'])
        assert not spider.export_state()['verified_orders_by_user']
        assert result['ticket'].status == 'PENDING_CONTEXT'
    finally:
        await pulse.drain_background_tasks()
        await store.close()


@pytest.mark.asyncio
async def test_high_voltage_cannot_invent_unspecified_money(tmp_path):
    spider, store, vault, pulse = await _build_m3_fixture(tmp_path)
    try:
        result = await spider.process_inbound_turn('emp_chen', 'GOVERNANCE', '王总订单要求打6折')
        assert result['ticket'].status == 'PENDING_CONTEXT'
        assert result['spawned_card'] is None
    finally:
        await pulse.drain_background_tasks()
        await store.close()


@pytest.mark.asyncio
async def test_finance_relay_escalation_cannot_be_reported_as_business_completion(tmp_path, monkeypatch):
    from core.schemas import RelayAuditResult
    spider, store, vault, pulse = await _build_m3_fixture(tmp_path)
    try:
        card = approval(spider._human_tools)
        await ticket(store)
        approved = await spider.handle_human_tool_submission('leader_li', card.card_id, output())
        fin = approved['next_card']
        async def escalate(**kwargs):
            return RelayAuditResult(verdict='ESCALATE_SUPERVISOR', sanitized_summary='凭证需复核')
        monkeypatch.setattr(spider._llm, 'audit_edge_relay', escalate)
        data = {'invoice_number': '12345678', 'billed_amount': 100, 'attachment_ref': 'receipt'}
        result = await spider.handle_human_tool_submission('fin_wang', fin.card_id, data)
        assert result['ticket'].status == 'INTERCEPTED'
        replay = await spider.handle_human_tool_submission('fin_wang', fin.card_id, data)
        assert replay['ticket'].status == 'INTERCEPTED'
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_finance_relay_rollback_does_not_resurrect_ticket_and_replay_is_stable(tmp_path, monkeypatch):
    from core.schemas import RelayAuditResult
    spider, store, vault, pulse = await _build_m3_fixture(tmp_path)
    try:
        card = approval(spider._human_tools)
        await ticket(store)
        approved = await spider.handle_human_tool_submission('leader_li', card.card_id, output())
        fin = approved['next_card']
        current = await store.get_ticket('T1')
        empty_branch = await store.export_subtree_state(current.subtree_root_id)
        empty_branch['tickets'] = [t for t in empty_branch['tickets'] if t['ticket_id'] != 'T1']
        vault.seal_snapshot(current.subtree_root_id, fin.target_slot_id, empty_branch, scope='LOCAL')
        async def rollback(**kwargs):
            return RelayAuditResult(verdict='LOCAL_ROLLBACK', sanitized_summary='凭证冲突', rollback_reason='凭证冲突')
        monkeypatch.setattr(spider._llm, 'audit_edge_relay', rollback)
        data = {'invoice_number': '12345678', 'billed_amount': 100, 'attachment_ref': 'receipt'}
        result = await spider.handle_human_tool_submission('fin_wang', fin.card_id, data)
        assert result['ticket'].status == 'ROLLED_BACK'
        assert await store.get_ticket('T1') is None
        replay = await spider.handle_human_tool_submission('fin_wang', fin.card_id, data)
        assert replay['ticket'].status == 'ROLLED_BACK'
        assert await store.get_ticket('T1') is None
    finally:
        await store.close()

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from config import load_settings
from core.human_tool import HumanBlackBoxManager
from surfaces.wecom_gateway import LocalSimulatorAdapter, WeComBotWSAdapter, WeComWebhookCallbackAdapter
from swarm.cross_dept_router import CrossDepartmentRouter
from tests.test_m3_spider_and_relay import _build_m3_fixture


def settings(tmp_path, **kwargs):
    return load_settings(llm_api_key='', vault_storage_dir=tmp_path/'vault',
        sandbox_workspace_dir=tmp_path/'sandbox', **kwargs)


def callback(msgid='M1', user='emp_chen', content='查询报价', req_id='R1'):
    return {'cmd': 'aibot_msg_callback', 'headers': {'req_id': req_id}, 'body': {
        'msgid': msgid, 'aibotid': 'test-bot', 'chattype': 'single',
        'from': {'userid': user}, 'msgtype': 'text', 'text': {'content': content}}}


class AckWS:
    def __init__(self, adapter, errcode=0):
        self.adapter = adapter
        self.frames = []
        self.errcode = errcode
    async def send(self, raw):
        frame = json.loads(raw)
        self.frames.append(frame)
        await self.adapter._handle_ws_frame({'headers': frame['headers'], 'errcode': self.errcode}, self)
    async def close(self):
        pass


@pytest.mark.asyncio
async def test_ws_callback_executes_business_once_and_replies_with_req_id_ack_and_stream_finish(tmp_path):
    adapter = WeComBotWSAdapter(settings(tmp_path))
    calls = []
    async def handler(uid, content, chat_type):
        calls.append((uid, content, chat_type))
        return '业务结果'
    adapter.bind_inbound_handler(handler)
    ws = AckWS(adapter)
    adapter._authenticated = True
    await adapter._handle_ws_frame(callback(), ws)
    await asyncio.gather(*list(adapter._inbound_tasks))
    assert calls == [('emp_chen', '查询报价', 'SINGLE')]
    final = ws.frames[-1]
    assert final['cmd'] == 'aibot_respond_msg'
    assert final['headers']['req_id'] == 'R1'
    assert final['body']['msgtype'] == 'stream'
    assert final['body']['stream']['finish'] is True
    assert final['body']['stream']['content'] == '业务结果'
    state = adapter.export_state()
    restored = WeComBotWSAdapter(settings(tmp_path))
    restored.restore_state(state)
    restored.bind_inbound_handler(handler)
    restored._authenticated = True
    replay_ws = AckWS(restored)
    await restored._handle_ws_frame(callback(req_id='R2'), replay_ws)
    await asyncio.gather(*list(restored._inbound_tasks))
    assert len(calls) == 1
    assert replay_ws.frames[-1]['headers']['req_id'] == 'R2'


@pytest.mark.asyncio
async def test_ws_unauthenticated_callback_and_conflicting_msgid_cannot_execute(tmp_path):
    adapter = WeComBotWSAdapter(settings(tmp_path))
    calls = []
    async def handler(*args):
        calls.append(args)
        return 'done'
    adapter.bind_inbound_handler(handler)
    ws = AckWS(adapter)
    await adapter._handle_ws_frame(callback(), ws)
    assert calls == []
    adapter._authenticated = True
    await adapter._handle_ws_frame(callback(), ws)
    await asyncio.gather(*list(adapter._inbound_tasks))
    await adapter._handle_ws_frame(callback(content='另一笔订单'), ws)
    await asyncio.gather(*list(adapter._inbound_tasks))
    assert len(calls) == 1
    assert adapter.export_state()['delivery_metadata']['last_error']['kind'] == 'MESSAGE_ID_CONFLICT'


@pytest.mark.asyncio
async def test_ws_unknown_sender_is_passed_exactly_and_error_is_observable(tmp_path):
    adapter = WeComBotWSAdapter(settings(tmp_path))
    seen = []
    async def handler(uid, content, chat_type):
        seen.append(uid)
        raise PermissionError('unknown directory identity')
    adapter.bind_inbound_handler(handler)
    adapter._authenticated = True
    ws = AckWS(adapter)
    await adapter._handle_ws_frame(callback(user='unknown-external-user'), ws)
    await asyncio.gather(*list(adapter._inbound_tasks))
    assert seen == ['unknown-external-user']
    assert not adapter.export_state()['processed_inbound']
    assert adapter.export_state()['delivery_metadata']['last_error']['kind'] == 'INBOUND_UNAUTHORIZED'


@pytest.mark.asyncio
async def test_local_message_export_restore_and_reset_include_dedupe_state():
    adapter = LocalSimulatorAdapter()
    await adapter.record_conversation_pair('u', 'User', 'COPILOT', 'SINGLE', 'hi', 'hello')
    saved = adapter.export_state()
    restored = LocalSimulatorAdapter()
    restored.restore_state(saved)
    assert [m.content for m in restored.get_chat_history('u', 'employee')] == ['hi', 'hello']
    restored.reset_messages()
    assert restored.export_state()['processed_inbound'] == {}
    assert restored.export_state()['messages_by_user'] == {}


@pytest.mark.asyncio
async def test_webhook_http_failure_is_visible_in_delivery_metadata(tmp_path, monkeypatch):
    async def fail_post(self, url, **kwargs):
        return httpx.Response(503, request=httpx.Request('POST', url), json={'errcode': 0})
    monkeypatch.setattr(httpx.AsyncClient, 'post', fail_post)
    adapter = WeComWebhookCallbackAdapter(settings(tmp_path, wecom_webhook_key='test-only-not-real'))
    card = HumanBlackBoxManager().dispatch_card('T1', 'CONTRACT_FINANCE_TAX_DISK', 'FINANCE_INVOICE', {'amount':100})
    msg = await adapter.push_interactive_card('fin_wang', 'GOVERNANCE', card)
    assert msg.structured_card['delivery']['status'] == 'FAILED'
    assert msg.structured_card['delivery']['http_status'] == 503


@pytest.mark.asyncio
async def test_live_cross_department_requests_remain_pending_and_replay_across_restart(tmp_path):
    spider, store, vault, pulse = await _build_m3_fixture(tmp_path)
    router = CrossDepartmentRouter(vault, store, spider._particles, spider._containers, pulse)
    args = dict(order_ref='ORD-TEST', product_model='A款', quantity=10, unit_price=100,
                current_stock=20, daily_sales=2, lead_days=5)
    try:
        first = await router.execute_cross_dept_chain(**args)
        assert first['status'] == 'PENDING_EXTERNAL_EXECUTION'
        assert first['remaining_stock'] is None
        assert first['projected_remaining_stock'] == 10
        tickets = [t for t in await store.list_tickets() if t.sanitized_payload.get('order_ref') == 'ORD-TEST']
        assert len(tickets) == 3
        assert all(t.status == 'OPEN' for t in tickets)
        assert all('已完成' not in t.summary and '完成' not in t.summary for t in tickets)
        assert all(t.sanitized_payload['execution_receipt'] is None for t in tickets)
        restarted = CrossDepartmentRouter(vault, store, spider._particles, spider._containers, pulse)
        repeat = await restarted.execute_cross_dept_chain(**args)
        assert repeat == first
        assert len([t for t in await store.list_tickets() if t.sanitized_payload.get('order_ref') == 'ORD-TEST']) == 3
        with pytest.raises(RuntimeError):
            await restarted.execute_cross_dept_chain(**{**args, 'quantity': 11})
        simulated = await restarted.execute_cross_dept_chain(**{**args, 'order_ref': 'SIM-ONLY'}, simulate=True)
        assert simulated['status'] == 'SIMULATED_COMPLETION'
    finally:
        await store.close()


class FakeConnection:
    def __init__(self):
        self.frames = []
        self.queue = asyncio.Queue()
        self.closed = False
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        self.closed = True
    def __aiter__(self):
        return self
    async def __anext__(self):
        return await self.queue.get()
    async def send(self, raw):
        frame = json.loads(raw)
        self.frames.append(frame)
        await self.queue.put(json.dumps({'headers': frame['headers'], 'errcode': 0}))
        if frame['cmd'] == 'aibot_subscribe':
            await self.queue.put(json.dumps(callback()))


@pytest.mark.asyncio
async def test_ws_bridge_auth_ack_immediate_callback_heartbeat_and_stop(tmp_path, monkeypatch):
    import surfaces.wecom_gateway as gateway
    adapter = WeComBotWSAdapter(settings(tmp_path, wecom_bot_id='test-bot', wecom_bot_secret='test-secret-not-real'))
    adapter._heartbeat_interval_seconds = 0.01
    adapter._request_timeout_seconds = 0.1
    seen = []
    async def handler(*args):
        seen.append(args)
        return 'done'
    adapter.bind_inbound_handler(handler)
    ws = FakeConnection()
    monkeypatch.setattr(gateway.websockets, 'connect', lambda *a, **k: ws)
    await adapter.start_ws_bridge_if_configured()
    for _ in range(50):
        await asyncio.sleep(0.005)
        if any(f['cmd'] == 'ping' for f in ws.frames) and seen:
            break
    await adapter.stop_ws_bridge()
    assert seen == [('emp_chen', '查询报价', 'SINGLE')]
    assert any(f['cmd'] == 'ping' for f in ws.frames)
    assert ws.closed
    assert adapter._ws_task is None and adapter._heartbeat_task is None
    assert not adapter._inbound_tasks and not adapter._pending_requests
    assert not adapter._authenticated


@pytest.mark.asyncio
async def test_restored_processing_marker_never_reexecutes_uncertain_business(tmp_path):
    adapter = WeComBotWSAdapter(settings(tmp_path))
    async def handler(*args):
        return 'done'
    adapter.bind_inbound_handler(handler)
    adapter._authenticated = True
    ws = AckWS(adapter)
    await adapter._handle_ws_frame(callback(), ws)
    await asyncio.gather(*list(adapter._inbound_tasks))
    saved = adapter.export_state()
    record = next(iter(saved['processed_inbound'].values()))
    record['status'] = 'PROCESSING'
    record.pop('reply', None)
    adapter.restore_state(saved)
    async def never(*args):
        pytest.fail('Uncertain committed request must not execute again')
    adapter.bind_inbound_handler(never)
    await adapter._handle_ws_frame(callback(req_id='RETRY'), ws)
    await asyncio.gather(*list(adapter._inbound_tasks))
    assert '待核验' in ws.frames[-1]['body']['stream']['content']


@pytest.mark.asyncio
async def test_ws_failed_reply_ack_does_not_repeat_business_on_redelivery(tmp_path):
    adapter = WeComBotWSAdapter(settings(tmp_path))
    calls = []
    async def handler(*args):
        calls.append(args)
        return 'done'
    adapter.bind_inbound_handler(handler)
    adapter._authenticated = True
    await adapter._handle_ws_frame(callback(), AckWS(adapter, 400))
    await asyncio.gather(*list(adapter._inbound_tasks))
    assert adapter.export_state()['delivery_metadata']['last_error']['kind'] == 'REPLY_DELIVERY_FAILED'
    await adapter._handle_ws_frame(callback(req_id='RETRY'), AckWS(adapter))
    await asyncio.gather(*list(adapter._inbound_tasks))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_malformed_nested_ws_callback_fails_closed_without_background_exception(tmp_path):
    adapter = WeComBotWSAdapter(settings(tmp_path))
    adapter._authenticated = True
    malformed = callback()
    malformed['body']['from'] = ['wrong-schema']
    await adapter._handle_ws_frame(malformed, AckWS(adapter))
    await asyncio.gather(*list(adapter._inbound_tasks))
    assert adapter.export_state()['delivery_metadata']['last_error']['kind'] == 'INVALID_CALLBACK'


@pytest.mark.asyncio
async def test_webhook_application_error_not_reported_as_delivery_success(tmp_path, monkeypatch):
    async def rejected(self, url, **kwargs):
        return httpx.Response(200, request=httpx.Request('POST', url), json={'errcode': 93000, 'errmsg': 'denied'})
    monkeypatch.setattr(httpx.AsyncClient, 'post', rejected)
    adapter = WeComWebhookCallbackAdapter(settings(tmp_path, wecom_webhook_key='test-only-not-real'))
    card = HumanBlackBoxManager().dispatch_card('T1', 'CONTRACT_FINANCE_TAX_DISK', 'FINANCE_INVOICE', {'amount':100})
    msg = await adapter.push_interactive_card('fin_wang', 'GOVERNANCE', card)
    assert msg.structured_card['delivery']['status'] == 'FAILED'
    assert msg.structured_card['delivery']['errcode'] == 93000


@pytest.mark.asyncio
async def test_ws_proactive_approval_card_is_explicitly_pending_without_delivery_capability(tmp_path):
    adapter = WeComBotWSAdapter(settings(tmp_path))
    card = HumanBlackBoxManager().dispatch_card('T1', 'CONTRACT_LEADER_HV_APPROVAL', 'LEADER_APPROVAL', {'requested_amount':100})
    msg = await adapter.push_interactive_card('leader_li', 'GOVERNANCE', card)
    assert msg.structured_card['delivery']['status'] == 'PENDING_EXTERNAL_DELIVERY'
    health = adapter.get_transport_status()
    assert health['capabilities']['inbound_text_reply'] is True
    assert health['capabilities']['proactive_interactive_card_delivery'] is False


@pytest.mark.asyncio
async def test_ws_missing_heartbeat_ack_reconnects_and_stop_cancels_retry(tmp_path, monkeypatch):
    import surfaces.wecom_gateway as gateway
    adapter = WeComBotWSAdapter(settings(tmp_path, wecom_bot_id='test-bot', wecom_bot_secret='test-secret-not-real'))
    adapter._heartbeat_interval_seconds = 0.005
    adapter._request_timeout_seconds = 0.01
    class NoPingAck(FakeConnection):
        async def send(self, raw):
            frame = json.loads(raw)
            if frame['cmd'] == 'ping':
                self.frames.append(frame)
                return
            await super().send(raw)
    ws = NoPingAck()
    monkeypatch.setattr(gateway.websockets, 'connect', lambda *a, **k: ws)
    await adapter.start_ws_bridge_if_configured()
    for _ in range(40):
        await asyncio.sleep(0.005)
        if adapter.get_transport_status()['connection_status'] == 'RECONNECTING':
            break
    assert adapter.get_transport_status()['connection_status'] == 'RECONNECTING'
    await adapter.stop_ws_bridge()
    assert adapter._ws_task is None and adapter._heartbeat_task is None
    assert not adapter._pending_requests


@pytest.mark.asyncio
async def test_concurrent_same_callback_executes_once(tmp_path):
    adapter = WeComBotWSAdapter(settings(tmp_path))
    seen = []
    async def handler(*args):
        seen.append(args)
        await asyncio.sleep(0)
        return 'done'
    adapter.bind_inbound_handler(handler)
    adapter._authenticated = True
    ws = AckWS(adapter)
    await asyncio.gather(*[adapter._handle_ws_frame(callback(req_id=f'R{i}'), ws) for i in range(5)])
    await asyncio.gather(*list(adapter._inbound_tasks))
    assert len(seen) == 1
    assert len(ws.frames) == 5


@pytest.mark.asyncio
async def test_webhook_network_error_metadata_does_not_expose_secret_url(tmp_path, monkeypatch):
    async def rejected(self, url, **kwargs):
        raise httpx.ConnectError(f'failed URL {url}', request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.AsyncClient, 'post', rejected)
    adapter = WeComWebhookCallbackAdapter(settings(tmp_path, wecom_webhook_key='test-secret-never-export'))
    card = HumanBlackBoxManager().dispatch_card('T1', 'CONTRACT_FINANCE_TAX_DISK', 'FINANCE_INVOICE', {'amount':100})
    msg = await adapter.push_interactive_card('fin_wang', 'GOVERNANCE', card)
    assert msg.structured_card['delivery']['status'] == 'FAILED'
    assert 'test-secret-never-export' not in json.dumps(adapter.export_state())

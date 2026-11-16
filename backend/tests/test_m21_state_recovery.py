from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import pytest
from core.blackbox_vault import BlackBoxVault
from core.snapshot_timemachine import SnapshotTimeMachine
from database import HotStateStore
from swarm.edge_audit_relay import EdgeAuditRelay

def test_time_machine_delete_cannot_delete_sealed_snapshot(tmp_path: Path):
    vault = BlackBoxVault(tmp_path)
    sid = vault.seal_snapshot('branch', 'actor', {'nodes': []})
    machine = SnapshotTimeMachine(SimpleNamespace(settings=SimpleNamespace(vault_storage_dir=tmp_path)))
    with pytest.raises(KeyError):
        machine.delete_snapshot(sid)
    assert vault.read_snapshot(sid) == {'nodes': []}

def test_vault_detects_truncated_tail_and_missing_snapshot(tmp_path: Path):
    vault = BlackBoxVault(tmp_path)
    vault.append_event('FIRST', 'root', 'actor', {})
    sid = vault.seal_snapshot('branch', 'actor', {'nodes': []})
    original = vault.ledger_path.read_text()
    vault.ledger_path.write_text(original.splitlines()[0] + '\n')
    assert not BlackBoxVault(tmp_path).verify_chain_integrity().intact
    vault.ledger_path.write_text(original)
    (tmp_path / 'snapshots' / f'{sid}.json').unlink()
    assert not vault.verify_chain_integrity().intact

def test_vault_serializes_independent_instances(tmp_path: Path):
    vaults = [BlackBoxVault(tmp_path) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: vaults[i % 8].append_event('E', 'root', 'actor', {'i': i}), range(80)))
    report = vaults[0].verify_chain_integrity()
    assert report.intact, report.error_reason
    assert report.total_records == 80

def test_wrong_subtree_rollback_rejected_before_seal(tmp_path: Path):
    async def run():
        vault = BlackBoxVault(tmp_path / 'vault')
        store = HotStateStore(f'sqlite+aiosqlite:///{tmp_path / "state.db"}')
        await store.init_db()
        try:
            sid = vault.seal_snapshot('branch-b', 'actor', {'subtree_root_id': 'branch-b', 'nodes': [], 'tickets': [], 'leases': []})
            relay = EdgeAuditRelay(vault, store, None, None, None)
            with pytest.raises(ValueError):
                await relay.execute_local_rollback('branch-a', 'relay', 'actor', 'reason', sid)
            assert not vault.read_records(event_kind='ROLLBACK_SEAL')
        finally:
            await store.close()
    asyncio.run(run())

def test_db_subtree_restore_rejects_foreign_payload(tmp_path: Path):
    async def run():
        store = HotStateStore(f'sqlite+aiosqlite:///{tmp_path / "state.db"}')
        await store.init_db()
        try:
            with pytest.raises(ValueError):
                await store.restore_subtree_state('a', {'subtree_root_id': 'b', 'nodes': [], 'tickets': [], 'leases': []})
        finally:
            await store.close()
    asyncio.run(run())

def _runtime_app(tmp_path, **extra):
    from config import ArachneSettings
    from main import create_app
    return create_app(ArachneSettings(llm_api_key='', bootstrap_password='123456', sqlite_db_url=f'sqlite+aiosqlite:///{tmp_path / "runtime.db"}', vault_storage_dir=tmp_path / 'vault', sandbox_workspace_dir=tmp_path / 'sandbox', **extra))

def test_snapshot_restore_does_not_revive_token_or_old_password(tmp_path):
    from fastapi.testclient import TestClient
    with TestClient(_runtime_app(tmp_path)) as client:
        rt = client.app.state.runtime
        auth = rt.auth_custody
        from core.auth_custody import hash_password
        auth._passwords['boss_lin'] = hash_password('123456')
        token = auth.login('boss_lin', '123456')['token']
        machine = SnapshotTimeMachine(rt)
        snap = machine.save_snapshot('before revoke')
        auth.change_password('boss_lin', '123456', 'new-secure-password')
        machine.restore_snapshot(snap['snapshot_id'])
        assert auth.resolve_token(token) is None
        with pytest.raises(ValueError):
            auth.login('boss_lin', '123456')
        assert auth.login('boss_lin', 'new-secure-password')['token']

def test_reset_revokes_tokens_and_clears_old_workspace_context(tmp_path):
    from fastapi.testclient import TestClient
    from core.auth_custody import hash_password
    with TestClient(_runtime_app(tmp_path)) as client:
        rt = client.app.state.runtime
        auth = rt.auth_custody
        auth._passwords['boss_lin'] = hash_password('123456')
        token = auth.login('boss_lin', '123456')['token']
        original_meta = rt.cave_explorer.export_meta_state()
        rt.spider._verified_orders_by_user = {'boss_lin': [{'customer': 'old customer'}]}
        rt.connectors._dispatch_history = [{'card_id': 'old card'}]
        client.portal.call(rt.cave_explorer.reset_to_empty_shell, 'New enterprise')
        assert auth.resolve_token(token) is None
        assert rt.spider._verified_orders_by_user == {}
        assert rt.connectors.export_state()['dispatch_history'] == []
        new_meta = rt.cave_explorer.export_meta_state()
        assert new_meta['workspace_id'] != original_meta['workspace_id']
        assert new_meta['workspace_epoch'] != original_meta['workspace_epoch']

def test_failed_reset_restores_complete_aggregate(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from core.auth_custody import hash_password
    with TestClient(_runtime_app(tmp_path)) as client:
        rt = client.app.state.runtime
        rt.auth_custody._passwords['boss_lin'] = hash_password('123456')
        token = rt.auth_custody.login('boss_lin', '123456')['token']
        before = client.portal.call(rt.capture_state)
        original = rt.hot_store.upsert_node
        async def fail(node):
            raise RuntimeError('injected reset write failure')
        monkeypatch.setattr(rt.hot_store, 'upsert_node', fail)
        with pytest.raises(RuntimeError, match='injected reset'):
            client.portal.call(rt.cave_explorer.reset_to_empty_shell, 'Should fail')
        monkeypatch.setattr(rt.hot_store, 'upsert_node', original)
        after = client.portal.call(rt.capture_state)
        assert before == after
        assert rt.auth_custody.resolve_token(token) == 'boss_lin'

def test_vault_serializes_process_writers(tmp_path):
    import os
    import subprocess
    import sys
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    script = 'from core.blackbox_vault import BlackBoxVault; import sys; v=BlackBoxVault(sys.argv[1]); [v.append_event("PROCESS", "root", "actor", {"i": i}) for i in range(12)]'
    writers = [subprocess.Popen([sys.executable, '-c', script, str(tmp_path)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(4)]
    for proc in writers:
        _, err = proc.communicate(timeout=30)
        assert proc.returncode == 0, err.decode()
    report = BlackBoxVault(tmp_path).verify_chain_integrity()
    assert report.intact, report.error_reason
    assert report.total_records == 48

def test_legacy_ledger_without_checkpoints_remains_supported(tmp_path):
    vault = BlackBoxVault(tmp_path)
    vault.append_event('LEGACY', 'root', 'actor', {})
    (tmp_path / 'head-checkpoints.jsonl').unlink()
    reloaded = BlackBoxVault(tmp_path)
    assert reloaded.verify_chain_integrity().intact
    reloaded.append_event('NEW', 'root', 'actor', {})
    assert reloaded.verify_chain_integrity().total_records == 2

def test_failed_restore_keeps_old_aggregate_and_has_no_completion_seal(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    with TestClient(_runtime_app(tmp_path)) as client:
        rt = client.app.state.runtime
        machine = SnapshotTimeMachine(rt)
        snap = client.portal.call(machine.save_full_snapshot, 'before')
        rt.cave_explorer.enterprise_name = 'Current workspace title'
        client.portal.call(rt.sync_persistence)
        before = client.portal.call(rt.capture_state)
        original = rt.hot_store.restore_global_state
        calls = 0
        async def fail_once(state):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError('injected restore SQL failure')
            await original(state)
        monkeypatch.setattr(rt.hot_store, 'restore_global_state', fail_once)
        with pytest.raises(RuntimeError, match='injected restore SQL failure'):
            client.portal.call(machine.restore_full_snapshot, snap['snapshot_id'])
        assert client.portal.call(rt.capture_state) == before
        assert not rt.vault.read_records(event_kind='SNAPSHOT_RESTORED')

def test_snapshot_does_not_reactivate_removed_account(tmp_path):
    from fastapi.testclient import TestClient
    with TestClient(_runtime_app(tmp_path)) as client:
        rt = client.app.state.runtime
        auth = rt.auth_custody
        machine = SnapshotTimeMachine(rt)
        snap = machine.save_snapshot('before identity deletion')
        uid = next(p.user_id for p in rt.containers.list_profiles() if p.role_view == 'employee')
        rt.containers._profiles.pop(uid)
        auth.account_directory.pop(uid, None)
        auth._passwords.pop(uid, None)
        machine.restore_snapshot(snap['snapshot_id'])
        assert auth.account_directory[uid]['_disabled'] is True
        with pytest.raises(ValueError):
            auth.login(uid, '123456')

def test_failed_restore_restores_durable_workspace_metadata(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    with TestClient(_runtime_app(tmp_path)) as client:
        rt = client.app.state.runtime
        machine = SnapshotTimeMachine(rt)
        snap = client.portal.call(machine.save_full_snapshot, 'before')
        rt.cave_explorer.enterprise_name = 'Authoritative current enterprise'
        client.portal.call(rt.sync_persistence)
        before = client.portal.call(rt.hot_store.load_workspace_state)
        original = rt.sync_persistence
        calls = 0
        async def fail_after_first_commit(*args, **kwargs):
            nonlocal calls
            calls += 1
            await original(*args, **kwargs)
            if calls == 1:
                raise RuntimeError('injected post-commit failure')
        monkeypatch.setattr(rt, 'sync_persistence', fail_after_first_commit)
        with pytest.raises(RuntimeError, match='post-commit'):
            client.portal.call(machine.restore_full_snapshot, snap['snapshot_id'])
        assert client.portal.call(rt.hot_store.load_workspace_state) == before

def test_snapshot_excludes_signing_secrets_and_preserves_current_binding_secret(tmp_path):
    import json
    from fastapi.testclient import TestClient
    from core.external_connectors import ConnectorBinding
    with TestClient(_runtime_app(tmp_path)) as client:
        rt = client.app.state.runtime
        rt.connectors.bind_slot_connector(ConnectorBinding(slot_id='SLOT_BOSS', connector_type='HTTP_WEBHOOK', endpoint_url='https://example.invalid/callback', hmac_secret_override='old-secret'))
        machine = SnapshotTimeMachine(rt)
        snap = machine.save_snapshot('safe recovery data')
        _, path = machine._resolve_snapshot_file(snap['snapshot_id'])
        raw = path.read_text()
        assert 'old-secret' not in raw
        assert 'hmac_secret_override' not in raw
        binding = rt.connectors.get_binding('SLOT_BOSS')
        binding.hmac_secret_override = 'current-secret'
        machine.restore_snapshot(snap['snapshot_id'])
        assert rt.connectors.get_binding('SLOT_BOSS').hmac_secret_override == 'current-secret'

def test_workspace_reset_clears_callback_receipts_metadata_and_old_principal_replay(tmp_path):
    import json
    from fastapi.testclient import TestClient
    from surfaces.wecom_gateway import WeComBotWSAdapter

    with TestClient(_runtime_app(tmp_path, wecom_adapter_mode='WECOM_BOT_WS', wecom_bot_id='offline-test-bot', wecom_bot_secret='')) as client:
        rt = client.app.state.runtime
        adapter = rt.wecom
        assert isinstance(adapter, WeComBotWSAdapter)
        old_uid = next(p.user_id for p in rt.containers.list_profiles() if p.role_view == 'employee')
        frame = {'headers': {'req_id': 'old-request'}, 'body': {
            'msgid': 'old-message', 'aibotid': 'offline-test-bot', 'chattype': 'single',
            'from': {'userid': old_uid}, 'msgtype': 'text', 'text': {'content': '查询当前报价规则'}}}

        class OfflineAckSocket:
            def __init__(self):
                self.frames = []
            async def send(self, raw):
                outgoing = json.loads(raw)
                self.frames.append(outgoing)
                await adapter._handle_ws_frame({'headers': outgoing['headers'], 'errcode': 0}, self)

        first_socket = OfflineAckSocket()
        client.portal.call(adapter._process_callback, frame, first_socket)
        assert len(first_socket.frames) == 1
        receipt = adapter.export_state()['processed_inbound']['offline-test-bot:old-message']
        assert receipt['status'] == 'SUCCEEDED'
        assert receipt['reply'] == first_socket.frames[0]['body']['stream']['content']
        assert adapter.export_state()['delivery_metadata']['last_delivery']['status'] == 'ACKNOWLEDGED'
        saved_adapter_state = adapter.export_state()
        machine = SnapshotTimeMachine(rt)
        snapshot = client.portal.call(machine.save_full_snapshot, 'callback receipt recovery')

        client.portal.call(rt.cave_explorer.reset_to_empty_shell, 'New enterprise')
        reset_state = adapter.export_state()
        assert reset_state['processed_inbound'] == {}
        assert reset_state['delivery_metadata'] == {}
        assert old_uid not in reset_state['messages_by_user']
        assert old_uid not in rt.containers._profiles

        replay_socket = OfflineAckSocket()
        client.portal.call(adapter._process_callback, frame, replay_socket)
        assert replay_socket.frames == []
        assert adapter.export_state()['processed_inbound'] == {}
        assert adapter.export_state()['delivery_metadata']['last_error']['kind'] == 'INBOUND_UNAUTHORIZED'

        # Full archive recovery uses the adapter's public state hooks, including receipts.
        client.portal.call(machine.restore_full_snapshot, snapshot['snapshot_id'])
        restored_adapter_state = adapter.export_state()
        assert restored_adapter_state == saved_adapter_state
        assert rt.auth_custody.account_directory[old_uid]['_disabled'] is True
        restored_replay_socket = OfflineAckSocket()
        client.portal.call(adapter._process_callback, frame, restored_replay_socket)
        assert restored_replay_socket.frames == []
        assert adapter.export_state()['delivery_metadata']['last_error']['kind'] == 'INBOUND_UNAUTHORIZED'

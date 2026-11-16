from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import time
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from config import ArachneSettings
from core.external_connectors import ConnectorBinding, compute_arachne_hmac_signature
import core.runtime_transactions as transactions
from main import create_app


@pytest.fixture
def callback_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = ArachneSettings(
        _env_file=None, llm_api_key="", enforce_bearer_auth=True,
        bootstrap_password="CallbackFixture#2026", connector_hmac_secret="callback-fixture-secret",
        sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path / 'hot.db'}",
        vault_storage_dir=tmp_path / "vault", sandbox_workspace_dir=tmp_path / "sandbox",
        wecom_adapter_mode="LOCAL_SIMULATOR", connector_max_retries=1,
    )
    outbound: list[httpx.Request] = []

    async def delivered(request: httpx.Request) -> httpx.Response:
        outbound.append(request)
        return httpx.Response(200, json={"accepted": True})

    with TestClient(create_app(settings)) as client:
        rt = client.app.state.runtime
        rt.connectors.set_http_transport(httpx.MockTransport(delivered))
        for role in ("leader", "finance_tool"):
            profile = next(p for p in rt.containers.list_profiles() if p.role_view == role)
            rt.connectors.bind_slot_connector(ConnectorBinding(
                slot_id=profile.slot_id, connector_type="HTTP_WEBHOOK",
                endpoint_url="https://connector.invalid/callback-test",
            ))
        login = client.post("/api/v1/auth/login", json={
            "username": "emp_chen", "password": "CallbackFixture#2026",
        })
        assert login.status_code == 200, login.text
        response = client.post("/api/v1/chat/message", headers={
            "Authorization": f"Bearer {login.json()['token']}",
        }, json={"content": "订单金额12000元，对方要求按4折特批成交，请转审批。"})
        assert response.status_code == 200, response.text
        card = response.json()["spawned_card"]
        assert card and rt.connectors.was_dispatched(card["card_id"])
        assert len(outbound) == 1
        capture = AsyncMock(wraps=rt.capture_state)
        restore = AsyncMock(wraps=rt.restore_runtime_state)
        journal = Mock(wraps=transactions.write_private_json)
        monkeypatch.setattr(rt, "capture_state", capture)
        monkeypatch.setattr(rt, "restore_runtime_state", restore)
        monkeypatch.setattr(transactions, "write_private_json", journal)
        real_verify = rt.connectors.verify_callback_signature

        def verify_under_exact_runtime_lock(**kwargs):
            assert rt._transactions.lock.locked()
            return real_verify(**kwargs)

        monkeypatch.setattr(rt.connectors, "verify_callback_signature", Mock(side_effect=verify_under_exact_runtime_lock))
        yield client, rt, card, outbound, capture, restore, journal


def _body(card: dict[str, Any], **changes: Any) -> bytes:
    body = {
        "card_id": card["card_id"], "ticket_id": card["ticket_id"],
        "idempotency_key": "callback-precheck",
        "submitted_output": {"decision": "APPROVE", "approved_amount": card["minimized_payload"]["requested_amount"], "comment": "Signed approval"},
    }
    body.update(changes)
    return json.dumps(body, ensure_ascii=False, indent=2).encode()


def _headers(rt, raw: bytes, timestamp: str | None = None) -> dict[str, str]:
    ts = timestamp or str(int(time.time()))
    return {"Content-Type": "application/json", "X-Arachne-Timestamp": ts,
            "X-Arachne-Signature": compute_arachne_hmac_signature(rt.settings.connector_hmac_secret, ts, raw)}


@pytest.mark.parametrize(("case", "status"), [
    ("unknown_card", 404), ("unknown_suffix", 404), ("trailing_unsigned", 401),
    ("unsigned", 401), ("empty_unsigned", 401),
    ("bad_signature", 403), ("expired", 403), ("malformed_timestamp", 403),
    ("disabled_binding", 403), ("local_binding", 403), ("missing_registry", 403),
    ("missing_slot", 404), ("vacant_actor", 403),
    ("body_card", 403), ("body_ticket", 403), ("actor", 403),
    ("malformed_json", 400), ("json_array", 403), ("not_dispatched", 409),
])
def test_callback_denial_skips_capture_restore_and_journal(callback_client, case: str, status: int):
    client, rt, card, outbound, capture, restore, journal = callback_client
    raw = _body(card)
    path = f"/api/v1/connectors/callback/{card['card_id']}"
    headers = _headers(rt, raw)
    registry = rt.connectors
    if case == "unknown_card":
        path = "/api/v1/connectors/callback/DOES_NOT_EXIST"
    elif case == "unknown_suffix":
        path += "/extra"
    elif case == "trailing_unsigned":
        path += "/"
        headers = {}
    elif case in ("unsigned", "empty_unsigned"):
        headers = {}
        if case == "empty_unsigned":
            raw = b""
    elif case == "bad_signature":
        headers["X-Arachne-Signature"] = "sha256=" + "0" * 64
    elif case == "expired":
        headers = _headers(rt, raw, str(int(time.time()) - 600))
    elif case == "malformed_timestamp":
        headers = _headers(rt, raw, "yesterday")
    elif case in ("disabled_binding", "local_binding"):
        binding = registry.get_binding(card["target_slot_id"])
        registry.bind_slot_connector(binding.model_copy(update={"enabled": False} if case == "disabled_binding" else {"connector_type": "LOCAL_WORKBENCH"}))
    elif case == "missing_registry":
        rt.connectors = None
    elif case == "missing_slot":
        del rt.containers._slots[card["target_slot_id"]]
    elif case == "vacant_actor":
        rt.containers.get_slot(card["target_slot_id"]).occupant_id = ""
    elif case in ("body_card", "body_ticket", "actor"):
        changes = {"body_card": {"card_id": "OTHER_CARD"}, "body_ticket": {"ticket_id": "OTHER_TICKET"}, "actor": {"actor_user_id": "boss_lin"}}[case]
        raw = _body(card, **changes)
        headers = _headers(rt, raw)
    elif case in ("malformed_json", "json_array"):
        raw = b"not-json" if case == "malformed_json" else b"[]"
        headers = _headers(rt, raw)
    elif case == "not_dispatched":
        registry._outbox[card["card_id"]]["status"] = "FAILED"
    before = deepcopy(registry.export_state())
    before_cards = deepcopy(rt.human_tools.export_state())
    vault_before = {p: p.read_bytes() for p in rt.settings.vault_storage_dir.rglob("*") if p.is_file()}
    response = client.post(path, content=raw, headers=headers)
    assert response.status_code == status, response.text
    assert capture.await_count == 0
    assert restore.await_count == 0
    assert journal.call_count == 0
    assert not rt._transactions.journal.exists()
    assert registry.export_state() == before
    assert rt.human_tools.export_state() == before_cards
    assert {p: p.read_bytes() for p in rt.settings.vault_storage_dir.rglob("*") if p.is_file()} == vault_before
    assert len(outbound) == 1
    if case == "missing_registry":
        assert rt.connectors is None
        rt.connectors = registry


def test_signed_callback_preserves_business_flow_and_idempotency(callback_client):
    client, rt, card, outbound, capture, restore, journal = callback_client
    raw = _body(card)
    response = client.post(f"/api/v1/connectors/callback/{card['card_id']}", content=raw, headers=_headers(rt, raw))
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] is True
    assert response.json()["card"]["status"] == "APPROVED"
    next_card = response.json()["next_card"]
    assert next_card and rt.connectors.was_dispatched(next_card["card_id"])
    assert len(outbound) == 2
    assert capture.await_count == journal.call_count == 1
    assert restore.await_count == 0
    assert rt.connectors.verify_callback_signature.call_count == 1
    replay = client.post(f"/api/v1/connectors/callback/{card['card_id']}", content=raw, headers=_headers(rt, raw))
    assert replay.status_code == 200 and replay.json()["idempotent_replay"] is True
    assert len(outbound) == 2
    capture.reset_mock(); journal.reset_mock()
    conflicting = _body(card, submitted_output={"decision": "REJECT", "comment": "Changed result"})
    conflict = client.post(f"/api/v1/connectors/callback/{card['card_id']}", content=conflicting, headers=_headers(rt, conflicting))
    assert conflict.status_code == 409
    assert capture.await_count == restore.await_count == journal.call_count == 0


def test_signed_callback_business_validation_still_captures_and_rolls_back(callback_client):
    client, rt, card, outbound, capture, restore, journal = callback_client
    before_cards = deepcopy(rt.human_tools.export_state())
    before_registry = deepcopy(rt.connectors.export_state())
    raw = _body(card, submitted_output={"decision": "APPROVE", "approved_amount": -1, "comment": "Invalid amount"})
    response = client.post(f"/api/v1/connectors/callback/{card['card_id']}", content=raw, headers=_headers(rt, raw))
    assert response.status_code == 422, response.text
    assert response.json()["accepted"] is False
    assert capture.await_count == restore.await_count == journal.call_count == 1
    assert rt.human_tools.export_state() == before_cards
    assert rt.connectors.export_state() == before_registry
    assert not rt._transactions.journal.exists()
    assert len(outbound) == 1

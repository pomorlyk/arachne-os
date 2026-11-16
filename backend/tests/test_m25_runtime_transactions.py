from __future__ import annotations

import asyncio
import os
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from config import ArachneSettings
from core.external_connectors import (
    ConnectorBinding,
    ExternalConnectorRegistry,
    compute_arachne_hmac_signature,
)
from main import create_app
from surfaces.api_routes import create_arachne_runtime, websocket_pulse_endpoint


def settings_for(root: Path, **overrides) -> ArachneSettings:
    overrides.setdefault("enforce_bearer_auth", False)
    return ArachneSettings(
        _env_file=None,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{root / 'hot.db'}",
        vault_storage_dir=root / "vault",
        sandbox_workspace_dir=root / "sandbox",
        **overrides,
    )


def login(client: TestClient, user_id: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"username": user_id, "password": password}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke_on_idle", [False, True])
async def test_websocket_idle_tick_keeps_updates_or_closes_revoked_identity(
    tmp_path: Path, revoke_on_idle: bool
) -> None:
    rt = await create_arachne_runtime(
        settings_for(
            tmp_path, enforce_bearer_auth=True, bootstrap_password="IdleFixture#2026"
        )
    )
    token = rt.auth_custody.login("emp_chen", "IdleFixture#2026")["token"]

    class IdleSocket:
        app = SimpleNamespace(state=SimpleNamespace(runtime=rt))

        def __init__(self):
            self.sent = []
            self.closed = []
            self.reads = 0

        async def accept(self):
            pass

        async def receive_json(self):
            return {"type": "authenticate", "token": token}

        async def receive_text(self):
            self.reads += 1
            if self.reads == 1:
                if revoke_on_idle:
                    rt.auth_custody.invalidate_sessions("emp_chen")
                raise asyncio.TimeoutError("idle authorization tick")
            assert self in rt.pulse_bus._subscribers
            await rt.pulse_bus.publish("SCORE_UPDATED", "root", "root", "new output")
            raise WebSocketDisconnect()

        async def send_json(self, data):
            self.sent.append(data)

        async def close(self, code):
            self.closed.append(code)

    socket = IdleSocket()
    try:
        await websocket_pulse_endpoint(socket)
        if revoke_on_idle:
            assert socket.closed == [4401]
        else:
            assert [
                message.get("type", message.get("event_type"))
                for message in socket.sent
            ] == ["authenticated", "STATE_UPDATED"]
            assert not socket.closed
        assert socket not in rt.pulse_bus._subscribers
    finally:
        await rt.close()


def test_dag_rejects_boolean_business_metric_without_recording_a_mission(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.post(
            "/api/v1/missions/execute-dag",
            json={
                "mission_brief": "计算订单采购成本",
                "metrics": {"order_amount": True},
            },
        )
        assert response.status_code == 400, response.text
        assert "finite metric" in response.json()["detail"]
        assert client.get("/api/v1/missions/history").json()["count"] == 0


def test_human_review_uses_saved_output_and_persists_once(tmp_path: Path) -> None:
    settings = settings_for(
        tmp_path, enforce_bearer_auth=True, bootstrap_password="ReviewFixture#2026"
    )
    with TestClient(create_app(settings)) as client:
        employee = login(client, "emp_chen", "ReviewFixture#2026")
        boss = login(client, "boss_lin", "ReviewFixture#2026")
        turn = client.post(
            "/api/v1/chat/message",
            headers=employee,
            json={"content": "查询公开目录报价"},
        ).json()
        body = {
            "ticket_id": turn["ticket"]["ticket_id"],
            "human_final_text": turn["message"]["content"],
        }
        assert (
            client.post(
                "/api/v1/scoring/shadow-reviews", headers=employee, json=body
            ).status_code
            == 403
        )
        first = client.post("/api/v1/scoring/shadow-reviews", headers=boss, json=body)
        assert first.status_code == 200, first.text
        assert first.json()["score"]["evidence_recorded"] is True
        again = client.post("/api/v1/scoring/shadow-reviews", headers=boss, json=body)
        assert again.status_code == 200
        assert again.json()["idempotent_replay"] is True
        assert again.json()["score"] == first.json()["score"]
    with TestClient(create_app(settings)) as client:
        boss = login(client, "boss_lin", "ReviewFixture#2026")
        repeated = client.post(
            "/api/v1/scoring/shadow-reviews", headers=boss, json=body
        )
        assert repeated.status_code == 200
        assert repeated.json()["idempotent_replay"] is True


def test_signed_callback_is_bound_to_one_workflow(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, connector_hmac_secret="callback-fixture-key")
    with TestClient(create_app(settings)) as client:
        rt = client.app.state.runtime
        rt.connectors.set_http_transport(
            httpx.MockTransport(lambda _: httpx.Response(200, json={"accepted": True}))
        )
        bound = client.post(
            "/api/v1/connectors/bindings",
            json={
                "slot_id": "SLOT_LEADER_01",
                "connector_type": "HTTP_WEBHOOK",
                "endpoint_url": "https://example.invalid/erp",
            },
        )
        assert bound.status_code == 200
        cards = []
        for name in ("甲", "乙"):
            response = client.post(
                "/api/v1/chat/message",
                json={
                    "sender_id": "emp_chen",
                    "content": f"客户{name}订单金额10000元，请特批打6折",
                },
            )
            assert response.status_code == 200
            cards.append(response.json()["spawned_card"])
        body = json.dumps(
            {
                "card_id": cards[0]["card_id"],
                "ticket_id": cards[0]["ticket_id"],
                "submitted_output": {
                    "decision": "REJECT",
                    "comment": "外部独立复核拒绝",
                },
            }
        ).encode()
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "X-Arachne-Timestamp": timestamp,
            "X-Arachne-Signature": compute_arachne_hmac_signature(
                settings.connector_hmac_secret, timestamp, body
            ),
        }
        first = client.post(
            f"/api/v1/connectors/callback/{cards[0]['card_id']}",
            headers=headers,
            content=body,
        )
        assert first.status_code == 200, first.text
        second = client.post(
            f"/api/v1/connectors/callback/{cards[1]['card_id']}",
            headers=headers,
            content=body,
        )
        assert second.status_code == 403
        assert rt.human_tools.get_card(cards[1]["card_id"]).status == "PENDING"


def test_wecom_real_runtime_binding_and_dedup_survive_restart(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, wecom_adapter_mode="WECOM_BOT_WS")
    frame = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "runtime-frame"},
        "body": {
            "msgid": "runtime-message",
            "aibotid": "fixture-bot",
            "chattype": "single",
            "from": {"userid": "emp_chen"},
            "msgtype": "text",
            "text": {"content": "查询公开目录报价"},
        },
    }

    async def receive(rt) -> None:
        adapter = rt.wecom
        adapter._authenticated = True

        class Socket:
            async def send(self, raw):
                outgoing = json.loads(raw)
                await adapter._handle_ws_frame(
                    {"headers": outgoing["headers"], "errcode": 0}, self
                )

        await adapter._handle_ws_frame(frame, Socket())
        await asyncio.gather(*list(adapter._inbound_tasks))

    with TestClient(create_app(settings)) as client:
        rt = client.app.state.runtime
        client.portal.call(receive, rt)
        assert len(client.portal.call(rt.hot_store.list_tickets)) == 1
        assert (
            rt.wecom.export_state()["processed_inbound"]["fixture-bot:runtime-message"][
                "status"
            ]
            == "SUCCEEDED"
        )
    with TestClient(create_app(settings)) as client:
        rt = client.app.state.runtime
        client.portal.call(receive, rt)
        assert len(client.portal.call(rt.hot_store.list_tickets)) == 1


def test_background_changes_are_persisted_after_task_completion(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        rt = client.app.state.runtime

        async def change_profile() -> None:
            await asyncio.sleep(0)
            rt.containers.get_profile("emp_chen").name = "已保存的后台修改"

        async def finish_background() -> None:
            rt.pulse_bus.schedule_background(change_profile())
            await rt.pulse_bus.drain_background_tasks()

        client.portal.call(finish_background)

    with TestClient(create_app(settings)) as restored:
        assert (
            restored.app.state.runtime.containers.get_profile("emp_chen").name
            == "已保存的后台修改"
        )


def test_interrupted_mutation_is_recovered_after_process_exit(tmp_path: Path) -> None:
    code = f"""
import asyncio, os
from pathlib import Path
from config import ArachneSettings
from surfaces.api_routes import create_arachne_runtime
root = Path({str(tmp_path)!r})
settings = ArachneSettings(_env_file=None, llm_api_key="", enforce_bearer_auth=False,
    sqlite_db_url=f"sqlite+aiosqlite:///{{root / 'hot.db'}}",
    vault_storage_dir=root / "vault", sandbox_workspace_dir=root / "sandbox")
async def run():
    rt = await create_arachne_runtime(settings)
    async with rt.mutation_scope():
        rt.containers.get_profile("emp_chen").name = "partial interrupted value"
        await rt.hot_store.restore_global_state({{"nodes": [], "tickets": [], "leases": []}})
        os._exit(17)
asyncio.run(run())
"""
    child = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parent.parent,
        env={
            **os.environ,
            "LLM_API_KEY": "audit_dummy_key",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert child.returncode == 17, child.stderr
    assert (tmp_path / "sandbox" / "runtime_transaction.json").exists()
    with TestClient(create_app(settings_for(tmp_path))) as client:
        rt = client.app.state.runtime
        assert rt.containers.get_profile("emp_chen").name == "小陈"
        assert len(client.portal.call(rt.hot_store.list_nodes)) == 12
        assert not (tmp_path / "sandbox" / "runtime_transaction.json").exists()


@pytest.mark.asyncio
async def test_runtime_rejects_another_writer_for_same_database(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    first = await create_arachne_runtime(settings)
    try:
        with pytest.raises(RuntimeError, match="writer|运行|实例"):
            second = await create_arachne_runtime(settings)
            await second.hot_store.close()
    finally:
        if hasattr(first, "close"):
            await first.close()
        else:
            await first.hot_store.close()


def test_failed_mutation_restores_memory_and_database(tmp_path: Path) -> None:
    with TestClient(create_app(settings_for(tmp_path))) as client:
        rt = client.app.state.runtime

        async def corrupt_and_fail() -> None:
            before = await rt.hot_store.export_global_state()
            original = rt.containers.get_profile("emp_chen").name
            with pytest.raises(ValueError, match="injected"):
                async with rt.mutation_scope():
                    rt.containers.get_profile("emp_chen").name = "partial"
                    await rt.hot_store.restore_global_state(
                        {"nodes": [], "tickets": [], "leases": []}
                    )
                    raise ValueError("injected")
            assert rt.containers.get_profile("emp_chen").name == original
            assert await rt.hot_store.export_global_state() == before

        client.portal.call(corrupt_and_fail)


def test_failed_mutation_discards_its_background_work(tmp_path: Path) -> None:
    with TestClient(create_app(settings_for(tmp_path))) as client:
        rt = client.app.state.runtime

        async def run() -> None:
            original = rt.containers.get_profile("emp_chen").name

            async def background() -> None:
                rt.containers.get_profile("emp_chen").name = "discarded foreground"

            with pytest.raises(ValueError, match="injected"):
                async with rt.mutation_scope():
                    rt.pulse_bus.schedule_background(background())
                    raise ValueError("injected")
            await rt.pulse_bus.drain_background_tasks()
            assert rt.containers.get_profile("emp_chen").name == original

        client.portal.call(run)


def test_connector_export_is_independent_of_pending_outbox(tmp_path: Path) -> None:
    with TestClient(create_app(settings_for(tmp_path))) as client:
        rt = client.app.state.runtime
        previous = rt.connectors.export_state()
        rt.connectors._outbox["new"] = {"status": "PENDING"}
        assert previous.get("outbox", {}) == {}
        rt.connectors._outbox.clear()


@pytest.mark.parametrize(
    "message",
    [
        "立刻帮我给李总直接发50件A款过去",
        "立即发20件A款到客户仓库",
        "马上给客户直接发10台设备过去",
    ],
)
def test_direct_shipping_synonyms_require_verified_order(
    tmp_path: Path, message: str
) -> None:
    with TestClient(create_app(settings_for(tmp_path))) as client:
        response = client.post(
            "/api/v1/chat/message", json={"sender_id": "emp_chen", "content": message}
        )
        assert response.status_code == 200
        assert response.json()["ticket"]["status"] == "PENDING_CONTEXT"


def test_callback_signature_requires_external_binding_and_configured_secret(
    tmp_path: Path,
) -> None:
    registry = ExternalConnectorRegistry(settings_for(tmp_path))
    valid, _ = registry.verify_callback_signature(
        slot_id="SLOT_FINANCE_BOX", timestamp="1", signature="x", raw_body=b"{}"
    )
    assert not valid
    with pytest.raises(ValueError, match="URL|地址|endpoint|密钥|secret"):
        registry.bind_slot_connector(
            ConnectorBinding(slot_id="SLOT_FINANCE_BOX", connector_type="HTTP_WEBHOOK")
        )


def test_connector_public_projection_omits_signing_secret(tmp_path: Path) -> None:
    registry = ExternalConnectorRegistry(
        settings_for(tmp_path, connector_hmac_secret="test-signing-secret")
    )
    registry.bind_slot_connector(
        ConnectorBinding(
            slot_id="SLOT_FINANCE_BOX",
            connector_type="HTTP_WEBHOOK",
            endpoint_url="https://example.invalid/callback",
            hmac_secret_override="private-override",
        )
    )
    public = registry.public_bindings()
    assert public[0]["slot_id"] == "SLOT_FINANCE_BOX"
    assert "private-override" not in str(public)
    assert "hmac_secret_override" not in public[0]

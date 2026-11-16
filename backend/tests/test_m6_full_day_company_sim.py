from __future__ import annotations

import pathlib

from fastapi.testclient import TestClient

from config import ArachneSettings
from main import create_app


def _make_test_settings(tmp_path: pathlib.Path) -> ArachneSettings:
    return ArachneSettings(
        enforce_bearer_auth=True, bootstrap_password="day_test_only", llm_api_key="",
        wecom_adapter_mode="LOCAL_SIMULATOR", wecom_bot_id="", wecom_bot_secret="", wecom_webhook_key="",
        vault_storage_dir=tmp_path / "vault_m6", sandbox_workspace_dir=tmp_path / "sandbox_m6",
        sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path / 'hot_m6.db'}",
    )


def test_wave1_to_wave3_five_departments_and_full_day_simulation(tmp_path: pathlib.Path) -> None:
    app = create_app(_make_test_settings(tmp_path))
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "boss_lin", "password": "day_test_only"})
        assert login.status_code == 200
        client.headers["Authorization"] = f"Bearer {login.json()['token']}"
        overview = client.get("/api/v1/state/overview?role_view=boss&user_id=boss_lin").json()
        assert len(overview["all_slots"]) == len(overview["all_profiles"]) == 12
        assert len(overview["all_balls"]) >= 14
        live = app.state.runtime
        before = live.export_runtime_state()
        ledger_before = live.vault.ledger_path.read_bytes()
        telemetry_before = live.llm_gateway.get_telemetry_snapshot()

        initial = client.get("/api/v1/simulation/status").json()
        assert initial["current_index"] == 0 and initial["total_stages"] == 12
        assert initial["status"] == "READY" and initial["is_day_completed"] is False
        assert all(value == 0 for value in initial["metrics"].values())
        first = client.post("/api/v1/simulation/step").json()
        assert first["current_index"] == 1
        assert first["completed_logs"][0]["phase"] == "MORNING_SEAL"
        assert first["completed_logs"][0]["status"] == "SUCCESS"
        full = client.post("/api/v1/simulation/run-full-day").json()
        # A partial forwarded order has no verified price: the chain must wait,
        # and the unrelated direct shipment must remain blocked by provenance.
        assert full["status"] == "PENDING_REVIEW"
        assert full["current_index"] == 3 and full["is_day_completed"] is False
        assert [log["status"] for log in full["completed_logs"]] == ["SUCCESS", "SUCCESS", "SUCCESS", "PENDING_REVIEW"]
        assert full["completed_logs"][-1]["phase"] == "WECHAT_AND_GATE"
        assert full["completed_logs"][-1]["highlights"]["gatekeeper_blocked"] == 1
        assert "PENDING_CONTEXT" in full["completed_logs"][-1]["outcome_summary"]
        assert full["schedule"][3]["status"] == "PENDING_REVIEW"
        assert all(stage["status"] == "PENDING" for stage in full["schedule"][4:])
        clone = live.simulation_runtime
        assert full["run_id"] == first["run_id"] == clone.simulation_scope["run_id"]
        assert full["scope"]["isolated"] is True
        tickets = client.portal.call(clone.hot_store.list_tickets)
        receipts = [ticket for ticket in tickets if ticket.ticket_id.startswith("TKT-LOG-")
                    and ticket.status == "COMPLETED" and ticket.sanitized_payload.get("simulation") is True]
        assert len(receipts) == 1
        assert receipts[0].sanitized_payload["evidence_source"] == "ISOLATED_SIMULATION_MODEL"
        assert full["metrics"] == {
            "gmv_cny": sum(ticket.sanitized_payload["requested_total_amount"] for ticket in receipts),
            "orders_processed": len(receipts), "redlines_blocked": 1,
            "skills_minted": 0, "local_rollbacks": 0, "board_resolutions_passed": 0,
        }
        assert clone.vault.verify_chain_integrity().intact
        private_ledger = clone.vault.ledger_path.read_bytes()
        again = client.post("/api/v1/simulation/run-full-day").json()
        assert again == full
        assert clone.vault.ledger_path.read_bytes() == private_ledger
        telemetry = clone.llm_gateway.get_telemetry_snapshot()
        assert telemetry["live_api_hits"] == 0 and telemetry["l2_fast_calls"] >= 1
        assert client.get("/api/v1/llm/telemetry").json() == telemetry_before
        assert live.export_runtime_state() == before
        assert live.vault.ledger_path.read_bytes() == ledger_before
        assert live.day_sim.current_index == 0

        reset = client.post("/api/v1/simulation/reset").json()
        assert reset["run_id"] != full["run_id"]
        assert reset["status"] == "READY" and reset["current_index"] == 0
        assert reset["completed_logs"] == []
        assert all(value == 0 for value in reset["metrics"].values())
        assert live.export_runtime_state() == before

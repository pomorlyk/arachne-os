from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import load_settings
from main import create_app


def _create_app_with_wargame(tmp_path: Path, db_name: str) -> tuple[FastAPI, Path]:
    sandbox_dir = tmp_path / "sandbox"
    settings = load_settings(
        enforce_bearer_auth=True, bootstrap_password="wargame_test_only", llm_api_key="",
        wecom_adapter_mode="LOCAL_SIMULATOR", wecom_bot_id="", wecom_bot_secret="", wecom_webhook_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path / db_name}",
        vault_storage_dir=tmp_path / f"vault_{db_name}", sandbox_workspace_dir=sandbox_dir,
    )
    return create_app(settings), sandbox_dir


def _login(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"username": "boss_lin", "password": "wargame_test_only"})
    assert response.status_code == 200
    client.headers["Authorization"] = f"Bearer {response.json()['token']}"


def test_black_swan_scenarios_catalog(tmp_path: Path) -> None:
    app, _ = _create_app_with_wargame(tmp_path, "m12_scenarios.db")
    with TestClient(app) as client:
        _login(client)
        res = client.get("/api/v1/wargame/scenarios")
        assert res.status_code == 200
        body = res.json()
        assert body["count"] == 4
        assert {s["scenario_id"] for s in body["scenarios"]} == {
            "swan_raw_material_surge", "swan_port_customs_freeze", "swan_key_account_default", "swan_regulatory_tax_audit",
        }
        surge = next(s for s in body["scenarios"] if s["scenario_id"] == "swan_raw_material_surge")
        assert "38%" in surge["title"] and "72" in surge["title"]


def test_wargame_simulation_raw_material_surge_and_auto_forge_balls(tmp_path: Path) -> None:
    app, sandbox_dir = _create_app_with_wargame(tmp_path, "m12_sim_forge.db")
    with TestClient(app) as client:
        _login(client)
        live = app.state.runtime
        live_before = live.export_runtime_state()
        ledger_before = live.vault.ledger_path.read_bytes()
        response = client.post("/api/v1/wargame/simulate", json={
            "scenario_id_or_custom": "swan_raw_material_surge", "horizon_days": 30,
            "monte_carlo_paths": 25, "auto_forge_defensive_balls": True,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["wargame_id"].startswith("WG_")
        assert data["scenario_id"] == "swan_raw_material_surge"
        assert data["horizon_days"] == 30 and data["monte_carlo_paths"] == 25
        assert data["scope"]["isolated"] is True
        assert data["evaluation_kind"] == "MODEL_BASELINE_ONLY"
        assert len(data["timeline_stages"]) == 4
        for idx, stage in enumerate(data["timeline_stages"], 1):
            assert stage["stage_index"] == idx
            assert stage["status"] == "PROPOSED" and stage["effect_evaluated"] is False
            assert stage["cashflow_impact_delta"] == stage["risk_mitigation_pct"] == 0
        metrics = data["monte_carlo_metrics"]
        assert metrics["paths_simulated"] == 25
        assert metrics["p10_net_cashflow_impact"] <= metrics["p50_net_cashflow_impact"] <= metrics["p90_net_cashflow_impact"]
        assert metrics["survival_score"] == metrics["unmitigated_survival_score"]
        assert metrics["resilience_gain_points"] == 0
        assert metrics["defense_effect_status"] == "NOT_MEASURED"
        assert metrics["comparison_method"] == "PAIRED_IDENTICAL_SHOCKS_AND_SURVIVAL_CRITERION"
        assert len(data["forged_defensive_balls"]) == 2
        assert {b["ball_type"] for b in data["forged_defensive_balls"]} == {"REDLINE", "SKILL"}
        clone = live.simulation_runtime
        for ball in data["forged_defensive_balls"]:
            assert ball["status"] == "CANDIDATE" and ball["mounted_to_slots"] == []
            assert clone.particles.get_ball(ball["ball_id"]).status == "CANDIDATE"
            assert ball["ball_id"] not in {b.ball_id for b in live.particles.list_all_balls()}
            assert ball["ball_id"] not in clone.containers.get_effective_ball_ids("SLOT_BOSS")
        skill = data["defensive_skill_ball"]
        assert skill["sandbox_verification"]["all_passed"] is True
        assert skill["sandbox_verification"]["verification_scope"] == "EXECUTION_ONLY"
        assert (clone.settings.sandbox_workspace_dir / skill["executable_code_path"]).exists()
        assert not (sandbox_dir / skill["executable_code_path"]).exists()
        assert data["worm_event"]["event_kind"] == "WARGAME_SIMULATION_COMPLETED"
        assert clone.vault.verify_chain_integrity().intact
        assert live.export_runtime_state() == live_before
        assert live.vault.ledger_path.read_bytes() == ledger_before


def test_wargame_key_account_default_and_port_freeze(tmp_path: Path) -> None:
    app, _ = _create_app_with_wargame(tmp_path, "m12_multi_swan.db")
    with TestClient(app) as client:
        _login(client)
        response = client.post("/api/v1/wargame/simulate", json={
            "scenario_id": "swan_key_account_default", "horizon_days": 45,
            "monte_carlo_paths": 20, "auto_forge_defensive_balls": True,
        })
        assert response.status_code == 200
        assert "债转货" in response.json()["defensive_redline_ball"]["title"]
        clone = app.state.runtime.simulation_runtime
        ball_count = len(clone.particles.list_all_balls())
        response = client.post("/api/v1/wargame/simulate", json={
            "scenario_id": "swan_port_customs_freeze", "horizon_days": 21,
            "monte_carlo_paths": 30, "auto_forge_defensive_balls": False,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["forged_defensive_balls"] == []
        assert data["defensive_redline_ball"] is None and data["defensive_skill_ball"] is None
        assert len(clone.particles.list_all_balls()) == ball_count
        assert data["monte_carlo_metrics"]["paths_simulated"] == 30


def test_wargame_history_and_live_llm_gateway_integration(tmp_path: Path) -> None:
    """A live parent's model callbacks and credentials never enter the offline clone."""
    app, _ = _create_app_with_wargame(tmp_path, "m12_history.db")
    with TestClient(app) as client:
        _login(client)
        rt = app.state.runtime
        called = []
        rt.llm_gateway.is_live = True
        async def parent_model(system_prompt: str, user_prompt: str) -> dict[str, Any]:
            called.append((system_prompt, user_prompt))
            return {"executive_commentary": "LIVE_PARENT_SHOULD_NOT_EXECUTE"}
        rt.llm_gateway._call_openai_compatible = parent_model
        response = client.post("/api/v1/wargame/simulate", json={
            "scenario_id_or_custom": "swan_regulatory_tax_audit", "auto_forge_defensive_balls": False,
        })
        assert response.status_code == 200
        data = response.json()
        assert called == []
        assert data["token_telemetry"]["mode"] == "DETERMINISTIC_SWARM"
        assert data["token_telemetry"]["llm_calls"] == data["token_telemetry"]["actual_tokens"] == 0
        assert data["token_telemetry"]["estimated_tokens"] == 0
        assert "LIVE_PARENT_SHOULD_NOT_EXECUTE" not in data["executive_commentary"]
        history = client.get("/api/v1/wargame/history").json()
        assert history["count"] == 1
        assert history["simulations"][0]["wargame_id"] == data["wargame_id"]
        assert history["run_id"] == data["run_id"]

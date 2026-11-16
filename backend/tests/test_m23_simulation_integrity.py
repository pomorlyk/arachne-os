from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from swarm.day_simulator import CompanyDaySimulator
from swarm.monte_carlo_wargame import MonteCarloWargameEngine, BLACK_SWAN_SCENARIOS


class SilentPulse:
    async def publish(self, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_parallel_steps_do_not_repeat_or_skip_stages():
    sim = CompanyDaySimulator(SimpleNamespace(pulse_bus=SilentPulse()))
    seen = []
    async def execute(phase, _time):
        seen.append(phase)
        await asyncio.sleep(0)
        return {"summary": phase, "status": "SUCCESS"}
    sim._execute_phase = execute
    await asyncio.gather(sim.step_next(), sim.step_next())
    assert seen == [s["phase"] for s in sim.SCHEDULE[:2]]
    assert sim.get_status()["current_index"] == 2
    assert sim.metrics["gmv_cny"] == 0
    assert sim.metrics["orders_processed"] == 0


@pytest.mark.asyncio
async def test_failed_phase_halts_full_day_and_stays_failed():
    sim = CompanyDaySimulator(SimpleNamespace(pulse_bus=SilentPulse()))
    async def execute(_phase, _time):
        return {"summary": "实际校验失败", "status": "FAILED", "highlights": {"intact": False}}
    sim._execute_phase = execute
    status = await sim.run_full_day()
    assert status["status"] == "FAILED"
    assert status["current_index"] == 0
    assert status["completed_logs"][0]["status"] == "FAILED"
    assert not status["is_day_completed"]
    assert status["schedule"][0]["status"] == "FAILED"
    assert (await sim.step_next())["status"] == "FAILED"


def test_auto_forge_is_not_an_assumed_mathematical_benefit():
    engine = MonteCarloWargameEngine()
    kwargs = dict(scenario=BLACK_SWAN_SCENARIOS[0], horizon_days=30, num_paths=20)
    baseline = engine._simulate_monte_carlo_paths(**kwargs, auto_forge_defensive_balls=False)
    forged = engine._simulate_monte_carlo_paths(**kwargs, auto_forge_defensive_balls=True)
    assert forged["sample_paths"] == baseline["sample_paths"]
    assert forged["survival_score"] == baseline["unmitigated_survival_score"]
    assert forged["resilience_gain_points"] == 0
    assert forged["random_seed"] == baseline["random_seed"]


def test_unstructured_custom_shock_is_rejected():
    with pytest.raises(ValueError, match="shock_parameters"):
        MonteCarloWargameEngine()._resolve_scenario("自定义疫情冲击", custom_description="需求下降80%")


@pytest.mark.asyncio
async def test_clone_leaves_live_assets_ledger_approvals_and_cursor_unchanged(tmp_path):
    from config import ArachneSettings
    from surfaces.api_routes import create_arachne_runtime
    from core.simulation_workspace import get_simulation_runtime, close_simulation_runtime
    settings = ArachneSettings(llm_api_key="", wecom_adapter_mode="LOCAL_SIMULATOR",
        wecom_bot_id="", wecom_bot_secret="", wecom_webhook_key="", sandbox_workspace_dir=tmp_path / "sandbox",
        vault_storage_dir=tmp_path / "vault", sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path / 'live.db'}")
    live = await create_arachne_runtime(settings)
    live.settings.sandbox_workspace_dir.mkdir(parents=True, exist_ok=True)
    source_script = live.settings.sandbox_workspace_dir / "existing_skill.py"
    source_script.write_text("def execute_skill(payload):\n    return {'status': 'ok', 'result': 7}\n")
    from core.schemas import CapabilityBall
    live.particles.register_ball(CapabilityBall(ball_id="EXISTING_SIM_TEST", ball_type="SKILL",
        title="existing", content="existing source", executable_code_path=str(source_script)))
    from core.external_connectors import ConnectorBinding
    live.connectors.bind_slot_connector(ConnectorBinding(slot_id="SLOT_BOSS", connector_type="HTTP_WEBHOOK",
        endpoint_url="https://simulation.invalid/never-dispatch", hmac_secret_override="test-only-offline-binding"))
    try:
        before = live.export_runtime_state()
        hot_before = await live.hot_store.export_global_state()
        ledger_before = live.vault.ledger_path.read_bytes()
        clone = await get_simulation_runtime(live)
        assert clone is not live
        assert clone.hot_store is not live.hot_store
        assert clone.human_tools is not live.human_tools
        assert clone.board is not live.board
        assert clone.scoring is not live.scoring
        assert clone.settings.llm_api_key == ""
        assert clone.settings.wecom_adapter_mode == "LOCAL_SIMULATOR"
        assert clone.connectors.export_state()["bindings"] == []
        assert clone.connectors.get_binding("SLOT_BOSS").connector_type == "LOCAL_WORKBENCH"
        assert live.connectors.get_binding("SLOT_BOSS").connector_type == "HTTP_WEBHOOK"
        copied = clone.particles.get_ball("EXISTING_SIM_TEST")
        copied_path = clone.settings.sandbox_workspace_dir / copied.executable_code_path
        assert copied_path != source_script
        assert copied_path.read_text() == source_script.read_text()
        copied_path.write_text("# private simulation edit")
        assert "execute_skill" in source_script.read_text()
        assert clone.simulation_scope["parent_workspace_id"] == live.cave_explorer.workspace_id
        assert len(clone.simulation_scope["parent_revision"]) == 64
        await clone.day_sim.step_next()
        count_before = len(clone.particles.list_all_balls())
        without_forge = await clone.wargame_engine.run_wargame_simulation(auto_forge_defensive_balls=False)
        assert without_forge["forged_defensive_balls"] == []
        assert len(clone.particles.list_all_balls()) == count_before
        report = await clone.wargame_engine.run_wargame_simulation(auto_forge_defensive_balls=True)
        assert report["monte_carlo_metrics"] == without_forge["monte_carlo_metrics"]
        assert report["token_telemetry"]["llm_calls"] == 0
        assert report["token_telemetry"]["actual_tokens"] == 0
        assert report["monte_carlo_metrics"]["resilience_gain_points"] == 0
        assert len(report["forged_defensive_balls"]) == 2
        for ball in report["forged_defensive_balls"]:
            assert ball["status"] == "CANDIDATE"
            assert ball["mounted_to_slots"] == []
            assert ball["ball_id"] not in {b.ball_id for b in live.particles.list_all_balls()}
        assert live.export_runtime_state() == before
        assert await live.hot_store.export_global_state() == hot_before
        assert live.vault.ledger_path.read_bytes() == ledger_before
        assert live.day_sim.current_index == 0
        assert clone.day_sim.current_index == 1
        script = report["defensive_skill_ball"]["executable_code_path"]
        assert (clone.settings.sandbox_workspace_dir / script).exists()
        assert not (live.settings.sandbox_workspace_dir / script).exists()
    finally:
        await close_simulation_runtime(live)
        await live.hot_store.close()


@pytest.mark.asyncio
async def test_simulation_restart_retains_cursor_and_reset_gets_fresh_run(tmp_path):
    from config import ArachneSettings
    from surfaces.api_routes import create_arachne_runtime
    from core.simulation_workspace import get_simulation_runtime, close_simulation_runtime
    settings = ArachneSettings(llm_api_key="", wecom_adapter_mode="LOCAL_SIMULATOR",
        wecom_bot_id="", wecom_bot_secret="", wecom_webhook_key="", sandbox_workspace_dir=tmp_path / "sandbox",
        vault_storage_dir=tmp_path / "vault", sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path / 'live.db'}")
    first = await create_arachne_runtime(settings)
    clone = await get_simulation_runtime(first)
    await clone.day_sim.step_next()
    run_id = clone.simulation_scope["run_id"]
    report = await clone.wargame_engine.run_wargame_simulation(auto_forge_defensive_balls=False)
    await close_simulation_runtime(first)
    await first.hot_store.close()
    second = await create_arachne_runtime(settings)
    try:
        restored = await get_simulation_runtime(second)
        assert restored.simulation_scope["run_id"] == run_id
        assert restored.day_sim.current_index == 1
        assert len(restored.day_sim.completed_logs) == 1
        assert restored.wargame_engine.get_history()["history"][0]["wargame_id"] == report["wargame_id"]
        # A durable in-flight marker represents a process killed during a phase.
        restored.day_sim.inflight_stage = {"index": 1, "phase": "INQUIRY_AND_WMS"}
        await close_simulation_runtime(second)
        interrupted = await get_simulation_runtime(second)
        assert interrupted.day_sim.get_status()["status"] == "FAILED"
        assert interrupted.day_sim.current_index == 1
        assert interrupted.day_sim.completed_logs[-1]["highlights"]["interrupted"] is True
        assert (await interrupted.day_sim.step_next())["current_index"] == 1
        fresh = await get_simulation_runtime(second, reset=True)
        assert fresh.simulation_scope["run_id"] != run_id
        assert fresh.day_sim.current_index == 0
        assert fresh.day_sim.metrics["gmv_cny"] == 0
        assert fresh.day_sim.completed_logs == []
        original_workspace = second.cave_explorer.workspace_id
        second.cave_explorer.workspace_id = "another-enterprise"
        other = await get_simulation_runtime(second)
        assert other.simulation_scope["parent_workspace_id"] == "another-enterprise"
        assert other.simulation_scope["run_id"] != fresh.simulation_scope["run_id"]
        second.cave_explorer.workspace_id = original_workspace
        returned = await get_simulation_runtime(second)
        assert returned.simulation_scope["run_id"] == fresh.simulation_scope["run_id"]
    finally:
        await close_simulation_runtime(second)
        await second.hot_store.close()


@pytest.mark.asyncio
async def test_closing_reports_failed_integrity_after_seal():
    calls = []
    class Vault:
        def seal_snapshot(self, *_args, **_kwargs):
            calls.append("seal")
            return "0" * 64
        def verify_chain_integrity(self):
            calls.append("verify")
            return SimpleNamespace(intact=False, total_records=3)
    class Store:
        async def export_global_state(self):
            return {}
    rt = SimpleNamespace(pulse_bus=SilentPulse(), vault=Vault(), hot_store=Store(),
                         llm_gateway=SimpleNamespace(record_l1_call=lambda: None))
    sim = CompanyDaySimulator(rt)
    result = await sim._execute_phase("DAILY_CLOSING", "21:00")
    assert calls == ["seal", "verify"]
    assert result["status"] == "FAILED"


def test_custom_structured_shocks_change_the_evaluated_distribution():
    engine = MonteCarloWargameEngine()
    base = dict(locked_order_revenue_cny=100000, baseline_gross_margin_pct=20,
                unhedged_margin_drop_pct=-5, base_stockout_prob=0.2)
    mild = engine._resolve_scenario("需求下降", shock_parameters=base)
    severe = engine._resolve_scenario("需求下降", shock_parameters={**base, "unhedged_margin_drop_pct": -80})
    def evaluate(scenario):
        return engine._simulate_monte_carlo_paths(scenario, 30, 20, False)
    assert evaluate(severe)["p50_net_cashflow_impact"] < evaluate(mild)["p50_net_cashflow_impact"]


def test_http_simulation_responses_are_scoped_without_live_business_changes(tmp_path):
    from fastapi.testclient import TestClient
    from config import ArachneSettings
    from main import create_app
    settings = ArachneSettings(llm_api_key="", wecom_adapter_mode="LOCAL_SIMULATOR",
        bootstrap_password="simulation_test_only", sandbox_workspace_dir=tmp_path / "sandbox",
        vault_storage_dir=tmp_path / "vault", sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path / 'live.db'}")
    app = create_app(settings)
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "boss_lin", "password": "simulation_test_only"})
        assert login.status_code == 200
        client.headers["Authorization"] = f"Bearer {login.json()['token']}"
        live = app.state.runtime
        before = live.export_runtime_state()
        ledger_before = live.vault.ledger_path.read_bytes()
        status = client.get("/api/v1/simulation/status")
        assert status.status_code == 200
        assert status.json()["scope"]["isolated"] is True
        assert live.simulation_runtime.settings.bootstrap_password != settings.bootstrap_password
        assert live.simulation_runtime.auth_custody._sessions == {}
        step = client.post("/api/v1/simulation/step")
        assert step.status_code == 200
        assert step.json()["current_index"] == 1
        report = client.post("/api/v1/wargame/simulate", json={"auto_forge_defensive_balls": False})
        assert report.status_code == 200
        assert report.json()["run_id"] == step.json()["run_id"]
        assert live.export_runtime_state() == before
        assert live.vault.ledger_path.read_bytes() == ledger_before
        rejected = client.post("/api/v1/wargame/simulate", json={"custom_scenario": "疫情冲击"})
        assert rejected.status_code == 400
        assert "shock_parameters" in rejected.json()["detail"]


@pytest.mark.asyncio
async def test_arena_failed_samples_remain_failed_in_day_summary(tmp_path):
    from config import ArachneSettings
    from surfaces.api_routes import create_arachne_runtime
    from core.simulation_workspace import get_simulation_runtime, close_simulation_runtime
    settings = ArachneSettings(llm_api_key="", wecom_adapter_mode="LOCAL_SIMULATOR",
        sandbox_workspace_dir=tmp_path / "sandbox", vault_storage_dir=tmp_path / "vault",
        sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path / 'live.db'}")
    live = await create_arachne_runtime(settings)
    try:
        clone = await get_simulation_runtime(live)
        async def rejected(**_kwargs):
            return SimpleNamespace(ast_passed=True, total_samples=2, success_rate=1.0,
                match_rate=0.5, promoted=False, minted_ball_id=None)
        clone.arena.propose_and_evaluate = rejected
        clone.day_sim.current_index = 7
        status = await clone.day_sim.step_next()
        assert status["status"] == "FAILED"
        assert status["completed_logs"][-1]["status"] == "FAILED"
        assert status["metrics"]["skills_minted"] == 0
        assert status["current_index"] == 7
    finally:
        await close_simulation_runtime(live)
        await live.hot_store.close()


@pytest.mark.asyncio
async def test_cancelled_phase_halts_without_replaying_effects():
    sim = CompanyDaySimulator(SimpleNamespace(pulse_bus=SilentPulse()))
    started = asyncio.Event()
    effects = []
    async def execute(phase, _time):
        effects.append(phase)
        started.set()
        await asyncio.Event().wait()
    sim._execute_phase = execute
    step = asyncio.create_task(sim.step_next())
    await started.wait()
    step.cancel()
    with pytest.raises(asyncio.CancelledError):
        await step
    assert sim.get_status()["status"] == "FAILED"
    await sim.step_next()
    assert effects == ["MORNING_SEAL"]


def test_catalogue_description_echo_retains_quantified_preset():
    engine = MonteCarloWargameEngine()
    preset = BLACK_SWAN_SCENARIOS[0]
    resolved = engine._resolve_scenario(preset["scenario_id"], custom_description=preset["description"])
    assert resolved["shock_parameters"] == preset["shock_parameters"]
    with pytest.raises(ValueError, match="shock_parameters"):
        engine._resolve_scenario(preset["scenario_id"], custom_description="需求突然下降80%")

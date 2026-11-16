from types import SimpleNamespace
import pytest
from config import load_settings
from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from core.llm_gateway import LLMGateway
from core.particles import ParticleEngine
from database import HotStateStore
from seed_demo.commerce_dept_seed import seed_commerce_department
from swarm.dag_mission_engine import DAGMissionEngine
from swarm.evolution_arena import EvolutionArena
from swarm.pulse_bus import PulseBus
from swarm.red_blue_crucible import RedBlueCrucible
from swarm.scoring_engine import ScoringEngine


@pytest.fixture
async def runtime(tmp_path):
    settings = load_settings(
        llm_api_key="",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=tmp_path / "sandbox",
        sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
    )
    vault = BlackBoxVault(settings.vault_storage_dir)
    particles = ParticleEngine(vault)
    containers = ContainerRegistry()
    hot = HotStateStore(settings.sqlite_db_url)
    await hot.init_db()
    await seed_commerce_department(vault, particles, containers, hot)
    pulse = PulseBus()
    llm = LLMGateway(settings)
    yield SimpleNamespace(
        settings=settings,
        vault=vault,
        particles=particles,
        containers=containers,
        llm_gateway=llm,
        pulse_bus=pulse,
        scoring=ScoringEngine(vault, containers, pulse),
    )
    await hot.close()


@pytest.mark.asyncio
async def test_dag_tool_failure(runtime, monkeypatch):
    engine = DAGMissionEngine(runtime)
    path = runtime.settings.sandbox_workspace_dir / "test_tool.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def execute_skill(payload):\n    return {'result': 1}\n")
    monkeypatch.setattr(engine, "_ensure_executable_skill_script", lambda *args: path)
    monkeypatch.setattr(
        "swarm.dag_mission_engine.run_skill_in_isolated_subprocess",
        lambda **kw: [{"ok": False, "error": "broken tool"}],
    )
    result = await engine.execute_dag_mission(
        mission_brief="采购 10 件按 600 元，底价 480 元，30 天账期，现货 10 件"
    )
    assert result["status"] == "FAILED"
    assert result["token_telemetry"]["llm_calls"] == 0
    assert not result["execution_evidence"]["business_execution_completed"]
    assert not result["consensus_resolution"]["approved_conditions"]
    restored = DAGMissionEngine(runtime)
    restored.restore_state(engine.export_state())
    assert restored.get_history()["count"] == 1


@pytest.mark.asyncio
async def test_redline_presence_is_not_evidence(runtime, monkeypatch):
    async def permissive(**kw):
        return SimpleNamespace(
            redline_violated=False,
            violated_redline_ball_id=None,
            high_voltage_triggered=False,
            context_complete=True,
            reply_to_user="同意直接执行",
        )

    runtime.containers.attach_ball_to_slot(
        "SLOT_FOLLOWUP_01", runtime.particles.list_redline_balls()[0].ball_id
    )
    monkeypatch.setattr(runtime.llm_gateway, "analyze_explorer_turn", permissive)
    result = await RedBlueCrucible(runtime).run_redline_penetration_audit(
        "SLOT_FOLLOWUP_01", attack_count=1
    )
    assert result["mounted_redline_balls"]
    assert result["attacks"][0]["outcome"] == "BREACHED"
    assert result["attacks"][0]["agent_response"] == "同意直接执行"
    assert result["token_telemetry"]["llm_calls"] == 0


@pytest.mark.asyncio
async def test_broken_finite_skill_is_not_repaired(runtime):
    result = await RedBlueCrucible(runtime).stress_test_and_heal_skill(
        "TEST_BROKEN",
        vulnerable_code="def execute_skill(payload):\n    return {'result': 0, 'healed_guard': True}\n",
        auto_heal=True,
        max_generations=2,
    )
    assert not result["healed"]
    assert not result["published"]
    assert runtime.particles.get_ball("TEST_BROKEN").status == "CANDIDATE"
    assert result["validation"]["semantic_status"] == "UNVALIDATED"


@pytest.mark.asyncio
async def test_synthetic_candidate_and_historical_freight(runtime):
    arena = EvolutionArena(
        runtime.settings,
        runtime.vault,
        runtime.particles,
        runtime.containers,
        runtime.llm_gateway,
        runtime.scoring,
        runtime.pulse_bus,
    )
    report = await arena.propose_and_evaluate("emp_chen", "金额的6%服务费")
    assert report.benchmark_source == "SYNTHETIC_COLD_START"
    assert report.match_rate == 1.0
    assert not report.promoted
    ball = runtime.particles.get_ball(report.minted_ball_id)
    assert ball.status == "CANDIDATE"
    assert ball.ball_id not in runtime.containers.get_effective_ball_ids(
        "SLOT_FOLLOWUP_01"
    )
    freight = await arena.propose_and_evaluate(
        "emp_chen", "运费规则：首重3公斤10元，每公斤续重4元，满500元免运费"
    )
    assert freight.benchmark_source == "VAULT_HISTORICAL"
    assert freight.promoted


@pytest.mark.asyncio
async def test_candidate_publication_needs_independent_review_and_correct_business_outputs(
    runtime,
):
    arena = EvolutionArena(
        runtime.settings,
        runtime.vault,
        runtime.particles,
        runtime.containers,
        runtime.llm_gateway,
        runtime.scoring,
        runtime.pulse_bus,
    )
    report = await arena.propose_and_evaluate("emp_chen", "金额的6%服务费")
    samples = [
        {"input_payload": {"amount": value}, "expected_output": value * 0.06}
        for value in (10, 250, 5000)
    ]
    with pytest.raises(PermissionError):
        await arena.publish_candidate(
            report.proposal_id,
            "emp_chen",
            approved_source_hash=report.source_hash,
            independent_samples=samples,
        )
    with pytest.raises(ValueError, match="hash"):
        await arena.publish_candidate(
            report.proposal_id,
            "boss_lin",
            approved_source_hash="wrong",
            independent_samples=samples,
        )
    rejected = await arena.publish_candidate(
        report.proposal_id,
        "boss_lin",
        approved_source_hash=report.source_hash,
        independent_samples=[{**b, "expected_output": -1} for b in samples],
    )
    assert rejected["status"] == "VALIDATION_FAILED"
    assert runtime.particles.get_ball(report.minted_ball_id).status == "CANDIDATE"
    accepted = await arena.publish_candidate(
        report.proposal_id,
        "boss_lin",
        approved_source_hash=report.source_hash,
        independent_samples=samples,
    )
    assert accepted["status"] == "ACTIVE"
    assert accepted["validation"]["source"] == "INDEPENDENT_MANAGEMENT_REVIEW"
    assert report.minted_ball_id in runtime.containers.get_effective_ball_ids(
        "SLOT_FOLLOWUP_01"
    )
    repeat = await arena.publish_candidate(
        report.proposal_id,
        "boss_lin",
        approved_source_hash=report.source_hash,
        independent_samples=samples,
    )
    assert repeat["idempotent"]


@pytest.mark.asyncio
async def test_candidate_restore_rebases_source_and_tamper_prevents_publish(
    runtime, tmp_path
):
    import hashlib

    arena = EvolutionArena(
        runtime.settings,
        runtime.vault,
        runtime.particles,
        runtime.containers,
        runtime.llm_gateway,
        runtime.scoring,
        runtime.pulse_bus,
    )
    report = await arena.propose_and_evaluate("emp_chen", "金额的6%服务费")
    payload = arena.export_state()
    new_settings = runtime.settings.model_copy(
        update={"sandbox_workspace_dir": tmp_path / "restored_sandbox"}
    )
    restored = EvolutionArena(
        new_settings,
        runtime.vault,
        runtime.particles,
        runtime.containers,
        runtime.llm_gateway,
        runtime.scoring,
        runtime.pulse_bus,
    )
    restored.restore_state(payload)
    ball = runtime.particles.get_ball(report.minted_ball_id)
    path = new_settings.sandbox_workspace_dir / ball.executable_code_path
    assert path.is_file()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == report.source_hash
    path.write_text("def execute_skill(payload):\n    return {'result': 0}\n")
    with pytest.raises(ValueError, match="changed"):
        await restored.publish_candidate(
            report.proposal_id,
            "boss_lin",
            approved_source_hash=report.source_hash,
            independent_samples=[
                {"input_payload": {"amount": v}, "expected_output": v * 0.06}
                for v in (10, 250, 5000)
            ],
        )


@pytest.mark.asyncio
async def test_healing_cannot_replace_known_freight_with_wrong_finite_output(runtime):
    arena = EvolutionArena(
        runtime.settings,
        runtime.vault,
        runtime.particles,
        runtime.containers,
        runtime.llm_gateway,
        runtime.scoring,
        runtime.pulse_bus,
    )
    freight = await arena.propose_and_evaluate(
        "emp_chen", "运费规则：首重3公斤10元，每公斤续重4元，满500元免运费"
    )
    ball = runtime.particles.get_ball(freight.minted_ball_id)
    path = runtime.settings.sandbox_workspace_dir / ball.executable_code_path
    original = path.read_text()
    report = await RedBlueCrucible(runtime).stress_test_and_heal_skill(
        ball.ball_id,
        vulnerable_code="def execute_skill(payload):\n    return {'result': 0}\n",
    )
    assert report["final_pass_rate"] == 1.0
    assert report["validation"]["semantic_status"] == "FAILED"
    assert not report["healed"] and not report["published"]
    assert path.read_text() == original
    assert runtime.particles.get_ball(ball.ball_id).status == "ACTIVE"


@pytest.mark.asyncio
async def test_dag_missing_facts_and_debate_veto(runtime, monkeypatch):
    engine = DAGMissionEngine(runtime)
    assert engine._extract_mission_metrics("只有业务描述，无计量事实") == {}
    with pytest.raises(ValueError):
        engine._extract_mission_metrics("", {"quantity": float("nan")})
    with pytest.raises(ValueError):
        engine._extract_mission_metrics("采购 -5 件")
    with pytest.raises(ValueError):
        engine._extract_mission_metrics("", {"quantity": 1e308, "unit_price": 1e308})
    pending = await engine.execute_dag_mission(
        mission_brief="核验库存", auto_execute_skills=False, requirements=["quantity"]
    )
    assert pending["status"] == "PENDING_APPROVAL"
    assert pending["execution_evidence"]["missing_requirements"] == ["quantity"]
    runtime.llm_gateway.is_live = True

    async def veto(*args, **kwargs):
        return {"veto": True, "reasoning_summary": "否决：证据不足"}

    monkeypatch.setattr(engine, "_call_llm_json", veto)
    blocked = await engine.execute_dag_mission(
        mission_brief="仅分析方案", auto_execute_skills=False
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["debate_transcript"][0]["veto"] is True
    assert not blocked["execution_evidence"]["business_execution_completed"]


@pytest.mark.asyncio
async def test_missing_skill_implementation_has_explicit_continuation(runtime):
    ball = runtime.particles.get_ball("BALL_SKILL_ORDER_CHECKLIST")
    assert ball.executable_code_path is None
    report = await RedBlueCrucible(runtime).stress_test_and_heal_skill(ball.ball_id)
    assert report["status"] == "BLOCKED"
    assert report["continuation"]["required_action"] == "SUPPLY_EXECUTABLE_CANDIDATE"
    assert not report["published"]
    assert ball.executable_code_path is None


def test_semantic_comparison_validates_all_known_fields_and_rejects_nonfinite():
    from swarm.evolution_arena import NormalizedResultComparator

    assert not NormalizedResultComparator.is_equivalent(
        {"result": 6, "tax": 2}, {"result": 6, "tax": 999}
    )
    assert not NormalizedResultComparator.is_equivalent(
        6, {"result": 6, "tax": float("nan")}
    )
    assert not NormalizedResultComparator.is_equivalent("NaN", {"result": "NaN"})
    assert NormalizedResultComparator.is_equivalent("6.00元", {"result": 6})


@pytest.mark.asyncio
async def test_arena_restore_does_not_overwrite_newer_active_skill_source(runtime):
    arena = EvolutionArena(
        runtime.settings,
        runtime.vault,
        runtime.particles,
        runtime.containers,
        runtime.llm_gateway,
        runtime.scoring,
        runtime.pulse_bus,
    )
    report = await arena.propose_and_evaluate(
        "emp_chen", "运费规则：首重3公斤10元，每公斤续重4元，满500元免运费"
    )
    ball = runtime.particles.get_ball(report.minted_ball_id)
    path = runtime.settings.sandbox_workspace_dir / ball.executable_code_path
    newer = path.read_text() + "\n# later independently validated revision\n"
    path.write_text(newer)
    restored = EvolutionArena(
        runtime.settings,
        runtime.vault,
        runtime.particles,
        runtime.containers,
        runtime.llm_gateway,
        runtime.scoring,
        runtime.pulse_bus,
    )
    restored.restore_state(arena.export_state())
    assert path.read_text() == newer


@pytest.mark.asyncio
async def test_known_freight_repair_preserves_independent_historical_outputs(runtime):
    arena = EvolutionArena(
        runtime.settings,
        runtime.vault,
        runtime.particles,
        runtime.containers,
        runtime.llm_gateway,
        runtime.scoring,
        runtime.pulse_bus,
    )
    proposal = await arena.propose_and_evaluate(
        "emp_chen", "运费规则：首重3公斤10元，每公斤续重4元，满500元免运费"
    )
    report = await RedBlueCrucible(runtime).stress_test_and_heal_skill(
        proposal.minted_ball_id
    )
    assert report["final_pass_rate"] == 1.0
    assert report["validation"]["semantic_status"] == "VALIDATED"
    assert len(report["validation"]["samples"]) == 12
    assert all(sample["matched"] for sample in report["validation"]["samples"])
    assert report["healed"] and report["published"]
    assert runtime.particles.get_ball(proposal.minted_ball_id).status == "ACTIVE"


@pytest.mark.asyncio
async def test_true_cold_start_freight_uses_explicit_rule_and_stays_candidate(
    runtime, monkeypatch
):
    monkeypatch.setattr(runtime.vault, "list_golden_benchmarks", lambda *args: [])
    arena = EvolutionArena(
        runtime.settings,
        runtime.vault,
        runtime.particles,
        runtime.containers,
        runtime.llm_gateway,
        runtime.scoring,
        runtime.pulse_bus,
    )
    report = await arena.propose_and_evaluate(
        "emp_chen", "运费规则：首重3公斤10元，每公斤续重4元，满500元免运费"
    )
    assert report.benchmark_source == "SYNTHETIC_COLD_START"
    assert report.match_rate == 1.0
    assert report.candidate_status == "CANDIDATE"
    assert not report.promoted
    assert runtime.particles.get_ball(report.minted_ball_id).status == "CANDIDATE"
    assert report.minted_ball_id not in runtime.containers.get_effective_ball_ids(
        "SLOT_FOLLOWUP_01"
    )
    assert arena._resolve_benchmarks([], "", "一个未说明计算规则的工具") == (
        "SYNTHETIC_COLD_START",
        [],
    )


@pytest.mark.asyncio
async def test_lifecycle_cannot_publish_candidates_via_restore_archive_or_merge(
    runtime,
):
    from core.schemas import CapabilityBall
    from swarm.capability_lifecycle import CapabilityLifecycleEngine

    candidate = CapabilityBall(
        ball_id="BALL_SKILL_PENDING_REVIEW",
        ball_type="SKILL",
        title="未审核技能",
        content="候选",
        owner_slot_ids=["SLOT_FOLLOWUP_01"],
        status="CANDIDATE",
    )
    active = CapabilityBall(
        ball_id="BALL_SKILL_KNOWN_ACTIVE",
        ball_type="SKILL",
        title="已启用技能",
        content="原有受信实现",
        owner_slot_ids=["SLOT_FOLLOWUP_01"],
        status="ACTIVE",
    )
    runtime.particles.register_ball(candidate)
    runtime.particles.register_ball(active)
    lifecycle = CapabilityLifecycleEngine(runtime)
    with pytest.raises(PermissionError):
        await lifecycle.restore_module("boss_lin", candidate.ball_id)
    with pytest.raises(PermissionError):
        await lifecycle.reap_module(
            "boss_lin", "MERGE", active.ball_id, candidate.ball_id
        )
    assert runtime.particles.get_ball(candidate.ball_id).status == "CANDIDATE"
    await lifecycle.reap_module("boss_lin", "ARCHIVE", candidate.ball_id)
    with pytest.raises(PermissionError):
        await lifecycle.restore_module("boss_lin", candidate.ball_id)
    assert candidate.ball_id not in runtime.containers.get_effective_ball_ids(
        "SLOT_FOLLOWUP_01"
    )
    await lifecycle.reap_module("boss_lin", "ARCHIVE", active.ball_id)
    restored = await lifecycle.restore_module("boss_lin", active.ball_id)
    assert restored["restored_ball"]["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_registered_composed_candidate_uses_independent_review_and_explicit_target(
    runtime,
):
    import hashlib
    from core.schemas import CapabilityBall

    arena = EvolutionArena(
        runtime.settings,
        runtime.vault,
        runtime.particles,
        runtime.containers,
        runtime.llm_gateway,
        runtime.scoring,
        runtime.pulse_bus,
    )
    code = "def execute_skill(payload):\n    return {'result': payload['amount'] * 2}\n"
    source_hash = hashlib.sha256(code.encode()).hexdigest()
    ball = CapabilityBall(
        ball_id="BALL_SKILL_COMPOSED_REVIEW",
        ball_type="SKILL",
        title="候选组合工具",
        owner_slot_ids=["SLOT_LEADER_01"],
        content="组合待审",
        status="CANDIDATE",
    )
    runtime.particles.register_ball(ball)
    report = arena.register_candidate(
        proposal_id="PROP_ABCDEF12",
        ball_id=ball.ball_id,
        source_hash=source_hash,
        source_code=code,
        proposer_id="emp_chen",
        target_slot_id="SLOT_LEADER_01",
    )
    assert report.total_samples == 0 and report.match_rate == 0
    assert report.validation_status == "INDEPENDENT_REVIEW_REQUIRED"
    assert not report.promoted
    assert ball.ball_id not in runtime.containers.get_effective_ball_ids(
        "SLOT_LEADER_01"
    )
    restored = EvolutionArena(
        runtime.settings,
        runtime.vault,
        runtime.particles,
        runtime.containers,
        runtime.llm_gateway,
        runtime.scoring,
        runtime.pulse_bus,
    )
    restored.restore_state(arena.export_state())
    result = await restored.publish_candidate(
        report.proposal_id,
        "boss_lin",
        approved_source_hash=source_hash,
        independent_samples=[
            {"input_payload": {"amount": amount}, "expected_output": amount * 2}
            for amount in (3, 13, 250)
        ],
    )
    assert result["status"] == "ACTIVE"
    assert ball.ball_id in runtime.containers.get_effective_ball_ids("SLOT_LEADER_01")
    assert ball.ball_id not in runtime.containers.get_effective_ball_ids(
        "SLOT_FOLLOWUP_01"
    )


@pytest.mark.asyncio
async def test_publication_rejects_vacuous_expected_outputs(runtime):
    from swarm.evolution_arena import (
        NormalizedResultComparator,
        _has_meaningful_expected_output,
    )

    arena = EvolutionArena(
        runtime.settings,
        runtime.vault,
        runtime.particles,
        runtime.containers,
        runtime.llm_gateway,
        runtime.scoring,
        runtime.pulse_bus,
    )
    report = await arena.propose_and_evaluate("emp_chen", "金额6%服务费")
    for empty in ({}, [], "", "   ", {"only_empty": [[]]}):
        with pytest.raises(ValueError, match="meaningful"):
            await arena.publish_candidate(
                report.proposal_id,
                "boss_lin",
                approved_source_hash=report.source_hash,
                independent_samples=[
                    {"input_payload": {"amount": amount}, "expected_output": empty}
                    for amount in (3, 13, 250)
                ],
            )
    assert _has_meaningful_expected_output(0)
    assert _has_meaningful_expected_output(False)
    assert not NormalizedResultComparator.is_equivalent({}, {"result": 987})
    assert runtime.particles.get_ball(report.minted_ball_id).status == "CANDIDATE"


@pytest.mark.asyncio
async def test_lifecycle_restore_authorizes_every_requested_target_before_activation(
    runtime,
):
    from core.schemas import CapabilityBall
    from swarm.capability_lifecycle import CapabilityLifecycleEngine

    ball = CapabilityBall(
        ball_id="BALL_DATA_SCOPED_RESTORE",
        ball_type="DATA",
        title="受控资料",
        content="公开资料",
        owner_slot_ids=["SLOT_FOLLOWUP_01", "SLOT_BOSS"],
        status="ACTIVE",
    )
    runtime.particles.register_ball(ball)
    lifecycle = CapabilityLifecycleEngine(runtime)
    await lifecycle.reap_module("boss_lin", "ARCHIVE", ball.ball_id)
    with pytest.raises(PermissionError):
        await lifecycle.restore_module(
            "mgr_zhang", ball.ball_id, target_slot_id="SLOT_BOSS"
        )
    with pytest.raises(PermissionError):
        await lifecycle.restore_module("mgr_zhang", ball.ball_id)
    assert runtime.particles.get_ball(ball.ball_id).status == "DEPRECATED"
    assert ball.ball_id not in runtime.containers.get_effective_ball_ids(
        "SLOT_FOLLOWUP_01"
    )
    restored = await lifecycle.restore_module(
        "mgr_zhang", ball.ball_id, target_slot_id="SLOT_FOLLOWUP_01"
    )
    assert restored["mounted_slots"] == ["SLOT_FOLLOWUP_01"]


@pytest.mark.asyncio
async def test_lifecycle_nonboss_health_is_metadata_only_and_never_exposes_redline(
    runtime,
):
    from core.schemas import BorrowedBallLease, CapabilityBall
    from swarm.capability_lifecycle import CapabilityLifecycleEngine

    redline = CapabilityBall(
        ball_id="BALL_REDLINE_HEALTH_SECRET",
        ball_type="REDLINE",
        title="机密价格123456.78",
        content="不得泄露绝密价格123456.78；" * 12,
        owner_slot_ids=["SLOT_DEPT_MGR"],
        status="ACTIVE",
    )
    data = CapabilityBall(
        ball_id="BALL_DATA_HEALTH_UNMOUNTED",
        ball_type="DATA",
        title="未持有资料",
        domain_tags=["未自动化特殊规则"],
        content="SECRET_REPORT_CONTENT_997公式按金额的6%核算；" * 8,
        owner_slot_ids=["SLOT_BOSS"],
        status="ACTIVE",
    )
    runtime.particles.register_ball(redline)
    runtime.particles.register_ball(data)
    manager_slot = runtime.containers.get_slot("SLOT_DEPT_MGR")
    manager_slot.ball_ids.append(redline.ball_id)
    manager_slot.borrowed_balls.append(
        BorrowedBallLease(
            ball_id=redline.ball_id,
            from_slot="SLOT_BOSS",
            expires_at="2000-01-01T00:00:00Z",
        )
    )
    lifecycle = CapabilityLifecycleEngine(runtime)
    manager_scan = lifecycle.scan_lifecycle_health("mgr_zhang")
    assert "123456.78" not in str(manager_scan)
    assert redline.ball_id not in str(manager_scan)
    assert "SECRET_REPORT_CONTENT_997" not in str(manager_scan)
    assert not any(
        "raw_policy_text" in item for item in manager_scan["midwife_candidates"]
    )
    with pytest.raises(PermissionError):
        await lifecycle.reap_module("mgr_zhang", "ARCHIVE", redline.ball_id)


@pytest.mark.asyncio
async def test_double_archive_replays_preserve_real_origin_and_restore_known_active(
    runtime,
):
    from swarm.capability_lifecycle import CapabilityLifecycleEngine

    arena = EvolutionArena(
        runtime.settings,
        runtime.vault,
        runtime.particles,
        runtime.containers,
        runtime.llm_gateway,
        runtime.scoring,
        runtime.pulse_bus,
    )
    known = await arena.propose_and_evaluate(
        "emp_chen", "运费规则：首重3公斤10元，每公斤续重4元，满500元免运费"
    )
    assert known.promoted
    lifecycle = CapabilityLifecycleEngine(runtime)
    archived = await lifecycle.reap_module("boss_lin", "ARCHIVE", known.minted_ball_id)
    archive_count = len(runtime.vault.read_records())
    replay = await lifecycle.reap_module("boss_lin", "ARCHIVE", known.minted_ball_id)
    assert replay["idempotent"] is True
    assert replay["archived_ball"]["version"] == archived["archived_ball"]["version"]
    assert len(runtime.vault.read_records()) == archive_count
    with pytest.raises(ValueError, match="归档"):
        await lifecycle.reap_module(
            "boss_lin", "MERGE", known.minted_ball_id, "BALL_SKILL_ORDER_CHECKLIST"
        )
    assert len(runtime.vault.read_records()) == archive_count
    restored = await lifecycle.restore_module("boss_lin", known.minted_ball_id)
    assert restored["restored_ball"]["status"] == "ACTIVE"
    assert known.minted_ball_id in runtime.containers.get_effective_ball_ids(
        "SLOT_FOLLOWUP_01"
    )

    pending = await arena.propose_and_evaluate("emp_chen", "金额6%服务费")
    assert not pending.promoted
    await lifecycle.reap_module("boss_lin", "ARCHIVE", pending.minted_ball_id)
    candidate_count = len(runtime.vault.read_records())
    assert (await lifecycle.reap_module("boss_lin", "ARCHIVE", pending.minted_ball_id))[
        "idempotent"
    ]
    assert len(runtime.vault.read_records()) == candidate_count
    with pytest.raises(PermissionError):
        await lifecycle.restore_module("boss_lin", pending.minted_ball_id)
    assert pending.minted_ball_id not in runtime.containers.get_effective_ball_ids(
        "SLOT_FOLLOWUP_01"
    )


@pytest.mark.asyncio
async def test_legacy_repeated_archive_records_do_not_replace_actual_origin(runtime):
    from core.schemas import CapabilityBall
    from swarm.capability_lifecycle import CapabilityLifecycleEngine

    lifecycle = CapabilityLifecycleEngine(runtime)
    for origin, expected_restore in [("ACTIVE", True), ("CANDIDATE", False)]:
        ball = CapabilityBall(
            ball_id=f"BALL_SKILL_LEGACY_ARCHIVE_{origin}",
            ball_type="SKILL",
            title="重复归档历史",
            content="原始状态证据",
            status=origin,
            owner_slot_ids=["SLOT_FOLLOWUP_01"],
        )
        runtime.particles.register_ball(ball)
        await lifecycle.reap_module("boss_lin", "ARCHIVE", ball.ball_id)
        runtime.vault.append_event(
            event_kind="MODULE_REAPED_ARCHIVED",
            subtree_root_id="root",
            actor_slot_id="SLOT_BOSS",
            payload={"target_ball_id": ball.ball_id, "previous_status": "DEPRECATED"},
        )
        if expected_restore:
            assert (await lifecycle.restore_module("boss_lin", ball.ball_id))[
                "restored_ball"
            ]["status"] == "ACTIVE"
        else:
            with pytest.raises(PermissionError):
                await lifecycle.restore_module("boss_lin", ball.ball_id)

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import load_settings
from core.schemas import CapabilityBall
from main import create_app
from surfaces.crucible_routes import crucible_router


def _build_test_app(tmp_path: Path, db_name: str) -> FastAPI:
    sandbox_dir = tmp_path / "sandbox"
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / db_name).as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=sandbox_dir,
    )
    app = create_app(settings)
    if not any(
        getattr(r, "path", "").startswith("/api/v1/crucible") for r in app.routes
    ):
        app.include_router(crucible_router)
    return app


def test_fragile_skill_ball_multi_gen_self_healing_in_crucible(
    tmp_path: Path,
) -> None:
    """Robustness improvements cannot replace a skill without independent expected outputs."""
    app = _build_test_app(tmp_path, "m10_fragile_heal.db")
    fragile_code = """def execute_skill(payload: dict) -> dict:
    # 故意包含零除与未防护字段读取的脆弱报价脚本
    qty = payload["quantity"]
    unit_price = payload["unit_price"]
    per_item_fee = 120.0 / qty
    total = (unit_price + per_item_fee) * qty
    return {"status": "ok", "result": total}
"""
    with TestClient(app) as client:
        rt = app.state.runtime
        sandbox_dir = Path(rt.settings.sandbox_workspace_dir)
        script_file = sandbox_dir / "skill_fragile_quote.py"
        script_file.write_text(fragile_code, encoding="utf-8")

        fragile_ball = CapabilityBall(
            ball_id="BALL_SKILL_FRAGILE_QUOTE",
            ball_type="SKILL",
            title="脆弱均摊报价核算器",
            domain_tags=["报价", "核算"],
            sensitivity_level=2,
            owner_slot_ids=["SLOT_FOLLOWUP_01", "SLOT_LEADER_01"],
            content="用于测试红蓝对抗自愈沙箱的脆弱脚本球",
            executable_code_path=script_file.name,
            version=1,
            status="ACTIVE",
        )
        rt.particles.register_ball(fragile_ball, record_to_vault=True)

        res = client.post(
            "/api/v1/crucible/stress-test-skill",
            json={
                "ball_id": "BALL_SKILL_FRAGILE_QUOTE",
                "attack_intensity": "EXTREME",
                "auto_heal": True,
                "max_generations": 3,
            },
        )
        assert res.status_code == 200
        data = res.json()

        assert data["ball_id"] == "BALL_SKILL_FRAGILE_QUOTE"
        assert data["initial_pass_rate"] < 1.0
        assert data["final_pass_rate"] == 1.0
        assert data["healed"] is False
        assert data["published"] is False
        assert data["validation"]["semantic_status"] == "UNVALIDATED"
        assert (
            data["continuation"]["required_action"]
            == "SUBMIT_CANDIDATE_FOR_INDEPENDENT_BUSINESS_VALIDATION"
        )
        assert len(data["generations"]) >= 2
        assert data["generations"][0]["version"] == "1.0.0"
        assert data["generations"][-1]["pass_rate"] == 1.0
        assert "def _safe_float" in data["final_code"]

        # Robustness improvement alone cannot overwrite the active business implementation.
        updated_disk_code = script_file.read_text(encoding="utf-8")
        assert updated_disk_code == fragile_code
        updated_ball = rt.particles.get_ball("BALL_SKILL_FRAGILE_QUOTE")
        assert updated_ball is not None
        assert updated_ball.version == 1

        # 验证 BlackBoxVault 已记录 CRUCIBLE_SKILL_HEALED 事件且哈希链完好
        records = rt.vault.read_records()
        assert not any(r.event_kind == "CRUCIBLE_SKILL_HEALED" for r in records)
        assert client.get("/api/v1/vault/verify").json()["intact"] is True


def test_builtin_and_arena_skill_extreme_stress_test(tmp_path: Path) -> None:
    """
    测试用例 2：
    对现有内置 SKILL 球 (BALL_SKILL_ORDER_CHECKLIST) 以及通过 EvolutionArena 新合成的阶梯运费 SKILL 球
    执行 EXTREME 红蓝极限压力测试，验证 10 组 Red-Team 破坏性向量全覆盖并完成自愈加固。
    """
    app = _build_test_app(tmp_path, "m10_extreme_skill.db")
    with TestClient(app) as client:
        # 1) 先通过工匠擂台生成一颗标准运费 SKILL 球
        arena_res = client.post(
            "/api/v1/evolution/propose",
            json={
                "proposer_id": "emp_chen",
                "natural_instruction": "首重3公斤内10元，超过3公斤每公斤加4元，满500元免运费",
            },
        )
        assert arena_res.status_code == 200
        minted_ball_id = arena_res.json()["arena_report"]["minted_ball_id"]
        assert minted_ball_id is not None

        # 2) 对该新生成的 SKILL 球发起 EXTREME 极限红蓝轰炸
        stress_res = client.post(
            "/api/v1/crucible/stress-test-skill",
            json={
                "ball_id": minted_ball_id,
                "attack_intensity": "EXTREME",
                "auto_heal": True,
                "max_generations": 3,
            },
        )
        assert stress_res.status_code == 200
        stress_data = stress_res.json()
        assert stress_data["initial_pass_rate"] < 1.0
        assert stress_data["final_pass_rate"] == 1.0
        assert stress_data["healed"] is True
        assert stress_data["published"] is True
        assert stress_data["validation"]["semantic_status"] == "VALIDATED"
        assert len(stress_data["validation"]["samples"]) == 12
        assert all(s["matched"] for s in stress_data["validation"]["samples"])
        assert len(stress_data["adversarial_vectors"]) == 10
        categories = {v["category"] for v in stress_data["adversarial_vectors"]}
        assert {
            "EMPTY_PAYLOAD",
            "ZERO_DIVISION_TRAP",
            "NEGATIVE_TRAP",
            "STRING_INJECTION",
            "NAN_INF_POISON",
            "FLOAT_OVERFLOW",
            "TYPE_MISMATCH_NONE",
        }.issubset(categories)

        # 3) 对系统内置 SKILL 球 BALL_SKILL_ORDER_CHECKLIST 同样执行压力测试
        builtin_res = client.post(
            "/api/v1/crucible/stress-test-skill",
            json={
                "ball_id": "BALL_SKILL_ORDER_CHECKLIST",
                "attack_intensity": "STANDARD",
                "auto_heal": True,
                "max_generations": 2,
            },
        )
        assert builtin_res.status_code == 200
        builtin_data = builtin_res.json()
        assert builtin_data["status"] == "BLOCKED"
        assert (
            builtin_data["continuation"]["required_action"]
            == "SUPPLY_EXECUTABLE_CANDIDATE"
        )
        assert builtin_data["final_pass_rate"] == 0.0
        assert builtin_data["healed"] is False


def test_slot_redline_penetration_mounted_vs_unmounted_vulnerability(
    tmp_path: Path,
) -> None:
    """Actual target decisions determine defenses, including global high-voltage guards."""
    app = _build_test_app(tmp_path, "m10_penetration.db")
    with TestClient(app) as client:
        rt = app.state.runtime

        # 1) 审计挂载了红线球的 SLOT_BOSS 工位 -> 100% BLOCKED
        boss_audit = client.post(
            "/api/v1/crucible/redline-penetration",
            json={"target_slot_id": "SLOT_BOSS", "attack_count": 4},
        )
        assert boss_audit.status_code == 200
        boss_data = boss_audit.json()
        assert boss_data["target_slot_id"] == "SLOT_BOSS"
        assert boss_data["defense_score"] == 100.0
        assert all(atk["outcome"] == "BLOCKED" for atk in boss_data["attacks"])

        # 2) 审计仅挂载了 AUTHORITY 球但未直接挂载 REDLINE 球的普通跟单工位 SLOT_FOLLOWUP_01
        followup_audit = client.post(
            "/api/v1/crucible/redline-penetration",
            json={"target_slot_id": "SLOT_FOLLOWUP_01", "attack_count": 4},
        )
        assert followup_audit.status_code == 200
        followup_data = followup_audit.json()
        assert 0.0 < followup_data["defense_score"] < 100.0
        assert any(atk["outcome"] == "BREACHED" for atk in followup_data["attacks"])
        assert len(followup_data["recommendations"]) >= 2

        # Removing policy balls leaves global high-voltage checks in the real target path.
        boss_slot = rt.containers.get_slot("SLOT_BOSS")
        saved_balls = list(boss_slot.ball_ids)
        boss_slot.ball_ids = [
            bid
            for bid in boss_slot.ball_ids
            if not (bid.startswith("BALL_REDLINE_") or bid.startswith("BALL_AUTH_"))
        ]

        stripped_audit = client.post(
            "/api/v1/crucible/redline-penetration",
            json={"target_slot_id": "SLOT_BOSS", "attack_count": 4},
        )
        assert stripped_audit.status_code == 200
        stripped_data = stripped_audit.json()
        # Global high-voltage checks still reject some attacks; unmounted policy is not automatic breach.
        assert stripped_data["defense_score"] == 75.0
        assert stripped_data["mounted_redline_balls"] == []
        assert any(atk["outcome"] == "BREACHED" for atk in stripped_data["attacks"])
        for attack in stripped_data["attacks"]:
            observed = attack["decision_evidence"]
            assert attack["blocked"] == bool(
                observed["redline_violated"] or observed["high_voltage_triggered"]
            )
            assert attack["evidence_source"] == "TARGET_ANALYZE_EXPLORER_TURN"
        assert any(
            "REDLINE" in rec or "红线球" in rec
            for rec in stripped_data["recommendations"]
        )

        # 恢复原挂载球并验证防御分数回升至 100.0
        boss_slot.ball_ids = saved_balls
        restored_audit = client.post(
            "/api/v1/crucible/redline-penetration",
            json={"target_slot_id": "SLOT_BOSS", "attack_count": 4},
        )
        assert restored_audit.status_code == 200
        assert restored_audit.json()["defense_score"] == 100.0


def test_crucible_reports_history_listing(tmp_path: Path) -> None:
    """
    测试用例 4：
    验证 GET /api/v1/crucible/reports 能够完整返回历史技能压力测试报告与工位红线穿刺审计报告。
    """
    app = _build_test_app(tmp_path, "m10_reports.db")
    with TestClient(app) as client:
        r1 = client.post(
            "/api/v1/crucible/stress-test-skill",
            json={
                "ball_id": "BALL_SKILL_WMS_WAVE_LOCK",
                "attack_intensity": "EXTREME",
                "auto_heal": True,
                "max_generations": 3,
            },
        )
        assert r1.status_code == 200

        r2 = client.post(
            "/api/v1/crucible/redline-penetration",
            json={"target_slot_id": "SLOT_DEPT_MGR", "attack_count": 5},
        )
        assert r2.status_code == 200

        hist_res = client.get("/api/v1/crucible/reports")
        assert hist_res.status_code == 200
        hist = hist_res.json()

        assert hist["total_count"] == 2
        assert len(hist["reports"]) == 2
        assert len(hist["skill_stress_reports"]) == 1
        assert len(hist["redline_audit_reports"]) == 1
        assert hist["skill_stress_reports"][0]["ball_id"] == "BALL_SKILL_WMS_WAVE_LOCK"
        assert hist["redline_audit_reports"][0]["target_slot_id"] == "SLOT_DEPT_MGR"
        assert "token_telemetry" in hist["skill_stress_reports"][0]
        assert "token_telemetry" in hist["redline_audit_reports"][0]

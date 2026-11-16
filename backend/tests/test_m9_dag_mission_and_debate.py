from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import load_settings
from main import create_app
from surfaces.dag_mission_routes import dag_mission_router


def _create_app_with_missions(tmp_path: Path, db_name: str) -> tuple[FastAPI, Path]:
    sandbox_dir = tmp_path / "sandbox"
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / db_name).as_posix()}",
        vault_storage_dir=tmp_path / f"vault_{db_name}",
        sandbox_workspace_dir=sandbox_dir,
    )
    app = create_app(settings)
    if not any(
        getattr(route, "path", "").startswith("/api/v1/missions")
        for route in app.routes
    ):
        app.include_router(dag_mission_router)
    return app, sandbox_dir


def test_mission_presets_catalog_completeness(tmp_path: Path) -> None:
    """
    测试用例 1：验证 GET /api/v1/missions/presets 返回至少 4 个高复杂度跨部门联合作战任务预设。
    """
    app, _ = _create_app_with_missions(tmp_path, "m9_presets.db")
    with TestClient(app) as client:
        res = client.get("/api/v1/missions/presets")
        assert res.status_code == 200
        body = res.json()
        assert body["count"] >= 4
        presets = body["presets"]
        preset_ids = {p["preset_id"] for p in presets}
        expected_ids = {
            "preset_global_steel_lock",
            "preset_supply_chain_shortage",
            "preset_annual_margin_defense",
            "preset_compliance_audit_sweep",
        }
        assert expected_ids.issubset(preset_ids)

        steel = next(p for p in presets if p["preset_id"] == "preset_global_steel_lock")
        assert steel["evidence_source"] == "SYNTHETIC_SCENARIO"
        assert steel["business_facts_verified"] is False
        assert "200" in steel["mission_brief"]
        assert "472" in steel["mission_brief"]
        assert "45" in steel["mission_brief"]
        assert len(steel["involved_departments"]) >= 3


def test_execute_dag_mission_steel_lock_sandbox_and_redline_debate(
    tmp_path: Path,
) -> None:
    """Validated tools can plan; price vetoes and real execution remain distinct."""
    app, sandbox_dir = _create_app_with_missions(tmp_path, "m9_dag_exec.db")
    with TestClient(app) as client:
        proposal = client.post(
            "/api/v1/evolution/propose",
            json={
                "proposer_id": "emp_chen",
                "natural_instruction": "运费规则：首重3公斤10元，续重每公斤4元，满500元免运费",
            },
        ).json()["arena_report"]
        assert (
            proposal["benchmark_source"] == "VAULT_HISTORICAL" and proposal["promoted"]
        )
        rt = app.state.runtime
        # Install only the genuinely validated tool in this successful planning fixture.
        for slot in rt.containers.list_slots():
            slot.ball_ids = [
                bid
                for bid in slot.ball_ids
                if rt.particles.get_ball(bid).ball_type != "SKILL"
            ]
            rt.containers.attach_ball_to_slot(slot.slot_id, proposal["minted_ball_id"])
        steel = client.post(
            "/api/v1/missions/execute-dag",
            json={
                "preset_id": "preset_global_steel_lock",
                "initiator_account_id": "emp_chen",
                "max_debate_rounds": 3,
                "metrics": {"weight_kg": 4},
                "requirements": ["quantity", "unit_price", "weight_kg"],
            },
        )
        assert steel.status_code == 200, steel.text
        data = steel.json()
        assert data["status"] == "BLOCKED"
        assert data["consensus_resolution"]["final_status"] == "BLOCKED"
        assert (
            "BALL_REDLINE_FACTORY_FLOOR_PRICE"
            in data["consensus_resolution"]["triggered_redline_ball_ids"]
        )
        assert data["consensus_resolution"]["approved_conditions"] == []
        assert data["consensus_resolution"]["recommended_lease_grant"] is None
        assert (
            data["execution_evidence"]["metrics_source"]
            == "SYNTHETIC_PRESET_ASSERTIONS"
        )
        assert not data["execution_evidence"]["business_execution_completed"]
        assert [t["stance"] for t in data["debate_transcript"]] == [
            "PROPOSE",
            "CHALLENGE",
            "SYNTHESIZE",
        ]
        assert 3 <= len(data["dag_nodes"]) <= 5
        assert all(r["executed_ok"] for r in data["skill_executions"])
        assert all(
            (sandbox_dir / r["script_path"]).exists() for r in data["skill_executions"]
        )
        assert (
            data["token_telemetry"]["llm_calls"]
            == data["token_telemetry"]["llm_attempts"]
            == 0
        )
        assert data["worm_event"]["event_kind"] == "DAG_MISSION_EVALUATED"

        ready = client.post(
            "/api/v1/missions/execute-dag",
            json={
                "mission_brief": "标准运费核算方案",
                "metrics": {"weight_kg": 4, "order_amount": 100},
                "requirements": ["weight_kg", "order_amount"],
            },
        ).json()
        assert ready["status"] == "PLAN_READY"
        assert ready["execution_evidence"]["missing_requirements"] == []
        assert ready["skill_executions"]
        assert all(
            r["sandbox_output"]["result"] == 14 for r in ready["skill_executions"]
        )
        assert not ready["execution_evidence"]["business_execution_completed"]
        assert client.get("/api/v1/vault/verify").json()["intact"]


def test_run_adversarial_debate_three_slots_and_clauses(
    tmp_path: Path,
) -> None:
    """
    测试用例 3：验证 POST /api/v1/missions/adversarial-debate 跨工位多轮对抗辩论与裁决书。
    """
    app, _ = _create_app_with_missions(tmp_path, "m9_debate.db")
    with TestClient(app) as client:
        debate_res = client.post(
            "/api/v1/missions/adversarial-debate",
            json={
                "topic": "大客户 200 吨特种钢申请 472 元/吨破底价锁库及 45 天远期账期特批",
                "proposer_slot_id": "SLOT_FOLLOWUP_01",
                "reviewer_slot_id": "SLOT_FINANCE_BOX",
                "arbiter_slot_id": "SLOT_BOSS",
                "rounds": 3,
            },
        )
        assert debate_res.status_code == 200
        body = debate_res.json()

        assert body["debate_id"].startswith("DBT_")
        assert len(body["rounds"]) == 3
        for idx, r in enumerate(body["rounds"], start=1):
            assert r["round"] == idx
            assert r["proposer_slot_id"] == "SLOT_FOLLOWUP_01"
            assert r["reviewer_slot_id"] == "SLOT_FINANCE_BOX"
            assert len(r["proposer_cited_balls"]) >= 1
            actual = app.state.runtime.containers.get_effective_ball_ids(
                "SLOT_FINANCE_BOX"
            )
            assert set(r["reviewer_cited_balls"]) == actual
            assert len(r["cited_ball_ids"]) >= 2
            assert any(b.startswith("BALL_") for b in r["cited_ball_ids"])

        verdict = body["final_verdict"]
        assert verdict["arbiter_slot_id"] == "SLOT_BOSS"
        assert len(verdict["cited_ball_ids"]) >= 2
        assert len(verdict["mandatory_guardrails"]) >= 2
        assert verdict["decision"] == "PENDING_APPROVAL"
        assert verdict["authorized_lease"] is None
        assert body["token_telemetry"]["llm_calls"] == 0


def test_missions_history_and_live_llm_mock_compatibility(
    tmp_path: Path,
) -> None:
    """
    测试用例 4：验证 GET /api/v1/missions/history 历史查询及 state.llm_gateway.is_live / _call_openai_compatible 兼容调用。
    """
    app, _ = _create_app_with_missions(tmp_path, "m9_history.db")
    with TestClient(app) as client:
        # 挂载模拟的在线大模型钩子，验证 is_live + _call_openai_compatible 路径
        rt = app.state.runtime
        rt.llm_gateway.is_live = True  # type: ignore[attr-defined]

        calls = []

        async def _mock_openai_compatible(
            system_prompt: str, user_prompt: str
        ) -> dict[str, Any]:
            calls.append(system_prompt)
            if "proposer_argument" in system_prompt:
                return {
                    "proposer_argument": "【正方在线推演】引用 BALL_DATA_CATALOG_2026 申请锁量特批。",
                    "reviewer_rebuttal": "【反方在线推演】引用 BALL_REDLINE_LEGAL_INDEMNITY 严拒超额违约条款。",
                    "arbiter_comment": "【裁决席在线审理】要求按标准折中条款落地。",
                }
            return {
                "status": "COMPLETED",
                "reasoning_summary": "【在线大模型节点推演】已完成跨仓安全库存与违约金敞口精算。",
                "risk_assessment": "违约金诉求已压降至法务红线以内。",
                "handoff_to_downstream": "节点脱敏交接完毕，进入下一环节。",
                "argument": "【在线大模型博弈陈述】援引 BALL_REDLINE_LEGAL_INDEMNITY 达成跨仓拆单履约共识。",
                "concession_or_demand": "同意按 55% 首付 + 跨仓急件调拨执行。",
            }

        rt.llm_gateway._call_openai_compatible = _mock_openai_compatible  # type: ignore[attr-defined]

        # 执行供应链断供预设任务
        dag_res = client.post(
            "/api/v1/missions/execute-dag",
            json={
                "preset_id": "preset_supply_chain_shortage",
                "mission_title": "核心原材料突发断供 48 小时应急跨仓调配与客户违约金最小化会战",
                "mission_brief": "核心原材料突发断供 48 小时，客户索赔 25% 违约金并要求无限连带责任，需跨仓调配。",
                "initiator_account_id": "proc_lin",
                "max_debate_rounds": 2,
                "auto_execute_skills": True,
            },
        )
        assert dag_res.status_code == 200
        assert dag_res.json()["token_telemetry"]["mode"] == "LIVE_CLOUD_HYBRID"
        assert (
            dag_res.json()["status"] == "FAILED"
        )  # missing actual implementation receipts outrank model prose
        assert dag_res.json()["token_telemetry"]["llm_calls"] == len(calls) > 0

        # 执行一次对抗辩论
        deb_res = client.post(
            "/api/v1/missions/adversarial-debate",
            json={
                "topic": "断供48小时补充协议违约金上限博弈",
                "proposer_slot_id": "SLOT_PROCURE_01",
                "reviewer_slot_id": "SLOT_LEGAL_BOX",
                "arbiter_slot_id": "SLOT_BOSS",
                "rounds": 2,
            },
        )
        assert deb_res.status_code == 200

        # 查询历史记录
        hist_res = client.get("/api/v1/missions/history")
        assert hist_res.status_code == 200
        hist = hist_res.json()
        assert hist["total_missions"] == 1
        assert hist["total_debates"] == 1
        assert hist["count"] == 2
        assert len(hist["missions"]) == 1
        assert len(hist["debates"]) == 1

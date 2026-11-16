from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import ArachneSettings, load_settings
from main import create_app
from surfaces.skill_pipeline_routes import skill_pipeline_router


def _create_test_app(settings: ArachneSettings) -> FastAPI:
    app = create_app(settings)
    existing_paths = {getattr(r, "path", "") for r in app.routes}
    if "/api/v1/pipelines/presets" not in existing_paths:
        app.include_router(skill_pipeline_router)
    return app


def test_pipeline_presets_and_order_profit_three_stage_composition(
    tmp_path: Path,
) -> None:
    """
    测试用例 1：
    验证 GET /api/v1/pipelines/presets 返回 3 大预设模板，
    并通过 POST /api/v1/pipelines/compose 合成【报价折扣 -> 阶梯运费 -> 税费与净毛利】复合技能球，
    验证 3 阶段 stage_breakdown、final_output、python -I 沙箱进程预览、未验证候选球不挂载与 WORM 账本记录。
    """
    sandbox_dir = tmp_path / "sandbox"
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'm14_profit.db').as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=sandbox_dir,
    )
    app = _create_test_app(settings)
    with TestClient(app) as client:
        presets_res = client.get("/api/v1/pipelines/presets")
        assert presets_res.status_code == 200
        presets = presets_res.json()["presets"]
        assert len(presets) == 3
        preset_ids = {p["preset_id"] for p in presets}
        assert preset_ids == {
            "pipe_end_to_end_order_profit",
            "pipe_supply_chain_replenish",
            "pipe_contract_rebate_settlement",
        }

        profit_preset = next(
            p for p in presets if p["preset_id"] == "pipe_end_to_end_order_profit"
        )
        compose_res = client.post(
            "/api/v1/pipelines/compose",
            json={
                "pipeline_title": profit_preset["pipeline_title"],
                "source_skill_ball_ids": profit_preset["source_skill_ball_ids"],
                "pipeline_instruction": profit_preset["pipeline_instruction"],
                "target_slot_id": "SLOT_FOLLOWUP_01",
                "test_payload": {
                    "quantity": 50,
                    "unit_price": 1000.0,
                    "cost_unit_price": 600.0,
                    "weight_kg": 15.0,
                },
            },
        )
        assert compose_res.status_code == 200
        data = compose_res.json()

        assert data["sandbox_verification"]["passed"] is False
        assert data["sandbox_verification"]["process_passed"] is True
        assert data["validation_status"] == "UNVALIDATED"
        assert data["sandbox_verification"]["ast_passed"] is True
        assert data["worm_event"]["event_kind"] == "SKILL_PIPELINE_COMPOSED"

        stages = data["stage_breakdown"]
        assert len(stages) == 3
        # Stage 1: 50 * 1000 * 0.90 = 45,000
        assert stages[0]["outputs"]["discount_rate"] == 0.90
        assert stages[0]["outputs"]["discounted_amount"] == 45000.0
        # Stage 2: 满 500 元免运费 -> 0.0
        assert stages[1]["outputs"]["shipping_fee"] == 0.0
        assert stages[1]["outputs"]["free_shipping_applied"] is True
        # Stage 3: COGS=30,000, Tax=45000*0.065=2925, NetProfit=45000-30000-2925=12075.0
        assert stages[2]["outputs"]["net_profit"] == 12075.0
        assert data["final_output"]["net_profit"] == 12075.0
        assert data["final_output"]["margin_redline_passed"] is True

        # 注册为候选球，但独立语义审查之前不挂载
        rt = app.state.runtime
        master_ball_id = data["master_ball_id"]
        assert rt.particles.get_ball(master_ball_id) is not None
        assert master_ball_id not in rt.containers.get_slot("SLOT_FOLLOWUP_01").ball_ids
        assert rt.particles.get_ball(master_ball_id).status == "CANDIDATE"
        assert (sandbox_dir / data["script_filename"]).exists()


def test_supply_chain_replenish_pipeline_composition_and_execution(
    tmp_path: Path,
) -> None:
    """
    测试用例 2：
    合成并执行【安全库存水位 -> 紧急补货批量折扣 -> 干线物流总成本】供应链补货复合技能链，
    验证三阶段数据流自动传递与精确求解。
    """
    sandbox_dir = tmp_path / "sandbox"
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'm14_supply.db').as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=sandbox_dir,
    )
    app = _create_test_app(settings)
    with TestClient(app) as client:
        compose_res = client.post(
            "/api/v1/pipelines/compose",
            json={
                "preset_id": "pipe_supply_chain_replenish",
                "target_slot_id": "SLOT_WMS_01",
            },
        )
        assert compose_res.status_code == 200
        comp_data = compose_res.json()
        pipeline_id = comp_data["pipeline_id"]
        master_ball_id = comp_data["master_ball_id"]

        exec_res = client.post(
            "/api/v1/pipelines/execute",
            json={
                "sandbox_preview": True,
                "pipeline_id": pipeline_id,
                "payload": {
                    "daily_sales": 20.0,
                    "lead_time_days": 8.0,
                    "current_stock": 50.0,
                    "supplier_unit_price": 500.0,
                    "unit_weight_kg": 4.0,
                },
            },
        )
        assert exec_res.status_code == 200
        exec_data = exec_res.json()
        assert exec_data["ok"] is True
        assert exec_data["status"] == "SANDBOX_ONLY"
        assert exec_data["execution_evidence"]["business_execution_completed"] is False
        assert exec_data["master_ball_id"] == master_ball_id

        stages = exec_data["stage_breakdown"]
        assert len(stages) == 3
        # Stage 1: safety_stock = 20 * 8 * 1.5 = 240; target = 300; replenish_qty = 250
        assert stages[0]["outputs"]["safety_stock"] == 240.0
        assert stages[0]["outputs"]["replenish_qty"] == 250
        assert stages[0]["outputs"]["urgent_replenish_triggered"] is True
        # Stage 2: qty=250 >= 100 -> 0.88 discount -> 250*500*0.88 = 110,000 + 2% expedite (2200) = 112,200
        assert stages[1]["outputs"]["supplier_discount"] == 0.88
        assert stages[1]["outputs"]["procurement_subtotal"] == 112200.0
        # Stage 3: total_landed_cost > 100,000 -> requires_leader_approval = True
        assert exec_data["final_output"]["requires_leader_approval"] is True
        assert exec_data["final_output"]["total_landed_cost"] > 120000.0


def test_contract_rebate_settlement_pipeline_and_penalty_cap(
    tmp_path: Path,
) -> None:
    """
    测试用例 3：
    合成并执行【季度阶梯返利精算 -> 逾期违约金抵扣 -> 最终应结返利净额】经销商清算复合技能链，
    验证正常逾期抵扣与超长逾期触发 20% 违约金封顶及倒扣追偿。
    """
    sandbox_dir = tmp_path / "sandbox"
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'm14_rebate.db').as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=sandbox_dir,
    )
    app = _create_test_app(settings)
    with TestClient(app) as client:
        compose_res = client.post(
            "/api/v1/pipelines/compose",
            json={
                "preset_id": "pipe_contract_rebate_settlement",
                "target_slot_id": "SLOT_LEADER_01",
            },
        )
        assert compose_res.status_code == 200
        comp_data = compose_res.json()
        # 默认测试载荷：quarterly_gmv=600,000, qty=60 -> 6% 返利 = 36,000; 逾期 20 天违约金 = 6,000 -> 净返利 = 30,000
        assert comp_data["final_output"]["gross_rebate_amount"] == 36000.0
        assert comp_data["final_output"]["overdue_penalty_amount"] == 6000.0
        assert comp_data["final_output"]["net_rebate_payable"] == 30000.0
        assert comp_data["final_output"]["final_settlement_amount"] == 570000.0

        # 执行极端逾期场景（逾期 600 天 -> 原始违约金 30% 被 20% 上限封顶）
        exec_res = client.post(
            "/api/v1/pipelines/execute",
            json={
                "sandbox_preview": True,
                "ball_id": comp_data["master_ball_id"],
                "payload": {
                    "quarterly_gmv": 500000.0,
                    "quantity": 50,
                    "overdue_days": 600,
                },
            },
        )
        assert exec_res.status_code == 200
        exec_out = exec_res.json()["final_output"]
        assert exec_out["gross_rebate_amount"] == 30000.0
        assert exec_out["overdue_penalty_amount"] == 100000.0
        assert exec_out["net_rebate_payable"] == -70000.0
        assert exec_out["clawback_required"] is True


def test_pipeline_history_and_worm_chain_verification(
    tmp_path: Path,
) -> None:
    """
    测试用例 4：
    验证复合管道合成与多次执行后的 GET /api/v1/pipelines/history 历史记录追踪，
    以及 WORM 账本链式哈希 100% 完好。
    """
    sandbox_dir = tmp_path / "sandbox"
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'm14_hist.db').as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=sandbox_dir,
    )
    app = _create_test_app(settings)
    with TestClient(app) as client:
        c1 = client.post(
            "/api/v1/pipelines/compose",
            json={"preset_id": "pipe_end_to_end_order_profit"},
        )
        assert c1.status_code == 200
        c2 = client.post(
            "/api/v1/pipelines/compose",
            json={"preset_id": "pipe_contract_rebate_settlement"},
        )
        assert c2.status_code == 200

        e1 = client.post(
            "/api/v1/pipelines/execute",
            json={
                "sandbox_preview": True,
                "pipeline_id": c1.json()["pipeline_id"],
                "payload": {"quantity": 8, "unit_price": 50.0, "weight_kg": 5.5},
            },
        )
        assert e1.status_code == 200
        # 8 * 50 = 400 (<500 不免邮)，首重 3kg=10元 + 续重 ceil(2.5)=3kg * 4 = 12元 -> 运费 22 元
        assert e1.json()["final_output"]["shipping_fee"] == 22.0

        hist_res = client.get("/api/v1/pipelines/history")
        assert hist_res.status_code == 200
        hist = hist_res.json()
        assert hist["composed_count"] == 2
        assert hist["execution_count"] == 1
        assert len(hist["pipelines"]) == 2
        assert len(hist["executions"]) == 1

        vault_report = app.state.runtime.vault.verify_chain_integrity()
        assert vault_report.intact is True

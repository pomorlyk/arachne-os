from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import ArachneSettings, load_settings
from main import create_app
from surfaces.ingest_snapshot_routes import ingest_snapshot_router
from swarm.evolution_arena import run_skill_in_isolated_subprocess


def _create_test_app(settings: ArachneSettings) -> FastAPI:
    app = create_app(settings)
    existing_paths = {getattr(r, "path", "") for r in app.routes}
    if "/api/v1/ingest/samples" not in existing_paths:
        app.include_router(ingest_snapshot_router)
    return app


def test_csv_steel_ledger_ingestion_and_four_ball_mounting(
    tmp_path: Path,
) -> None:
    """
    测试用例 1：
    CSV 特钢台账样本吞噬 -> 验证自动识别 CSV 格式、生成包含 numeric_columns (min/max/mean/sum) 的 schema_profile，
    并自动锻造 DATA、SKILL（且 sandbox_verification.passed == True）、AUTHORITY、REDLINE 四颗球，
    成功注册进 ball_registry，业务球挂载至目标工位，REDLINE 仅挂载至老板工位。
    """
    sandbox_dir = tmp_path / "sandbox"
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'm11_csv.db').as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=sandbox_dir,
    )
    app = _create_test_app(settings)
    with TestClient(app) as client:
        samples_res = client.get("/api/v1/ingest/samples")
        assert samples_res.status_code == 200
        samples = samples_res.json()["samples"]
        assert len(samples) == 3

        csv_sample = next(
            s for s in samples if s["sample_id"] == "sample_csv_steel_ledger"
        )
        ingest_res = client.post(
            "/api/v1/ingest/document",
            json={
                "doc_title": csv_sample["doc_title"],
                "doc_format": "AUTO",
                "raw_content": csv_sample["raw_content"],
                "target_department": csv_sample["target_department"],
                "target_slot_id": "SLOT_FOLLOWUP_01",
                "auto_forge_query_skill": True,
            },
        )
        assert ingest_res.status_code == 200
        data = ingest_res.json()

        assert data["detected_format"] == "CSV"
        profile = data["schema_profile"]
        assert profile["row_count"] == 6
        assert profile["primary_key_column"] == "sku"
        assert "base_unit_price" in profile["numeric_columns"]
        assert profile["numeric_columns"]["base_unit_price"]["min"] == 4620.0
        assert profile["numeric_columns"]["base_unit_price"]["max"] == 168000.0
        assert "cost_floor_price" in profile["sensitive_columns"]

        created_balls = data["created_balls"]
        assert len(created_balls) == 4
        created_types = {b["ball_type"] for b in created_balls}
        assert created_types == {"DATA", "SKILL", "AUTHORITY", "REDLINE"}

        assert data["sandbox_verification"]["passed"] is True
        assert data["sandbox_verification"]["ast_passed"] is True

        skill_ball = next(b for b in created_balls if b["ball_type"] == "SKILL")
        script_file = sandbox_dir / skill_ball["executable_code_path"]
        assert script_file.exists()

        # 业务球挂载目标工位；机密红线球仅交由老板岗位持有。
        rt = app.state.runtime
        slot = rt.containers.get_slot("SLOT_FOLLOWUP_01")
        for b in created_balls:
            assert b["ball_id"] in rt.ball_registry
            if b["ball_type"] == "REDLINE":
                boss_profile = next(
                    p for p in rt.containers.list_profiles() if p.role_view == "boss"
                )
                assert b["owner_slot_ids"] == [boss_profile.slot_id]
                assert b["ball_id"] not in slot.ball_ids
                assert (
                    b["ball_id"]
                    in rt.containers.get_slot(boss_profile.slot_id).ball_ids
                )
            else:
                assert b["ball_id"] in slot.ball_ids


def test_json_erp_bom_ingestion_and_real_sandbox_skill_execution(
    tmp_path: Path,
) -> None:
    """
    测试用例 2：
    JSON ERP BOM 样本吞噬 -> 验证递归提取物料表、审批阈值与良率红线，
    并直接调用生成的沙箱 Python 脚本对 CELL-LFP-280AH 电芯执行真实查表、折扣与毛利核验。
    """
    sandbox_dir = tmp_path / "sandbox"
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'm11_json.db').as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=sandbox_dir,
    )
    app = _create_test_app(settings)
    with TestClient(app) as client:
        samples = client.get("/api/v1/ingest/samples").json()["samples"]
        json_sample = next(
            s for s in samples if s["sample_id"] == "sample_json_erp_bom"
        )

        ingest_res = client.post(
            "/api/v1/ingest/document",
            json={
                "doc_title": json_sample["doc_title"],
                "doc_format": "JSON",
                "raw_content": json_sample["raw_content"],
                "target_department": json_sample["target_department"],
                "target_slot_id": "SLOT_PROCURE_01",
                "auto_forge_query_skill": True,
            },
        )
        assert ingest_res.status_code == 200
        res_data = ingest_res.json()
        assert res_data["detected_format"] == "JSON"
        assert res_data["schema_profile"]["row_count"] == 5
        assert res_data["sandbox_verification"]["passed"] is True
        assert res_data["mounted_to_slot_id"] == "SLOT_PROCURE_01"

        skill_ball = next(
            b for b in res_data["created_balls"] if b["ball_type"] == "SKILL"
        )
        script_path = sandbox_dir / skill_ball["executable_code_path"]

        # 在 python -I 洁净室子进程中执行真实查表与毛利校验
        exec_res = run_skill_in_isolated_subprocess(
            script_path=script_path,
            sandbox_dir=sandbox_dir,
            input_payloads=[
                {
                    "sku": "CELL-LFP-280AH",
                    "quantity": 100,
                    "discount_rate": 0.95,
                    "overdue_days": 0,
                },
                {
                    "sku": "BMS-MASTER-V4",
                    "quantity": 10,
                    "discount_rate": 0.70,
                    "overdue_days": 0,
                },
            ],
        )
        assert exec_res[0]["ok"] is True
        out_ok = exec_res[0]["output"]
        assert out_ok["sku"] == "CELL-LFP-280AH"
        assert out_ok["sku_matched"] is True
        assert out_ok["base_unit_price"] == 420.0
        assert out_ok["cost_floor_price"] == 320.0
        assert out_ok["margin_compliance"] is True
        assert out_ok["rebate_rate"] == 0.095

        # 第二笔 7 折低于底价毛利红线，应触发 margin_compliance=False 且 approval_required=True
        out_low = exec_res[1]["output"]
        assert out_low["sku"] == "BMS-MASTER-V4"
        assert out_low["margin_compliance"] is False
        assert out_low["approval_required"] is True


def test_contract_md_ingestion_rebate_and_overdue_penalty_precision(
    tmp_path: Path,
) -> None:
    """
    测试用例 3：
    Markdown 经销商阶梯返利与违约金主合同样本吞噬 -> 验证自动提取合同表格、返利公式、日息违约金与红线词，
    并在沙箱中精确核算阶梯返利与逾期违约金（含 20% 封顶保护）。
    """
    sandbox_dir = tmp_path / "sandbox"
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'm11_contract.db').as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=sandbox_dir,
    )
    app = _create_test_app(settings)
    with TestClient(app) as client:
        samples = client.get("/api/v1/ingest/samples").json()["samples"]
        contract_sample = next(
            s for s in samples if s["sample_id"] == "sample_contract_rebate_md"
        )

        ingest_res = client.post(
            "/api/v1/ingest/document",
            json={
                "doc_title": contract_sample["doc_title"],
                "doc_format": "CONTRACT_MD",
                "raw_content": contract_sample["raw_content"],
                "target_department": contract_sample["target_department"],
                "target_slot_id": None,
                "auto_forge_query_skill": True,
            },
        )
        assert ingest_res.status_code == 200
        res_data = ingest_res.json()
        assert res_data["detected_format"] == "CONTRACT_MD"
        assert res_data["sandbox_verification"]["passed"] is True
        assert res_data["mounted_to_slot_id"] is not None

        redline_ball = next(
            b for b in res_data["created_balls"] if b["ball_type"] == "REDLINE"
        )
        assert "无限连带责任" in redline_ball["redline_keywords"]

        skill_ball = next(
            b for b in res_data["created_balls"] if b["ball_type"] == "SKILL"
        )
        script_path = sandbox_dir / skill_ball["executable_code_path"]

        # 测试阶梯返利 + 逾期违约金日息（万分之五/天）与 20% 封顶
        exec_res = run_skill_in_isolated_subprocess(
            script_path=script_path,
            sandbox_dir=sandbox_dir,
            input_payloads=[
                {
                    "sku": "MDL-DESK-B2",
                    "quantity": 50,
                    "discount_rate": 1.0,
                    "overdue_days": 20,
                },
                {
                    "sku": "MDL-CHAIR-A1",
                    "quantity": 10,
                    "discount_rate": 1.0,
                    "overdue_days": 800,
                },
            ],
        )
        out_1 = exec_res[0]["output"]
        # 2190 * 50 = 109,500; 满50件享 6% 返利 = 6,570; 逾期20天违约金 = 109500 * 0.0005 * 20 = 1,095
        assert out_1["gross_amount"] == 109500.0
        assert out_1["rebate_rate"] == 0.06
        assert out_1["rebate_amount"] == 6570.0
        assert out_1["overdue_penalty"] == 1095.0
        assert out_1["net_settlement_amount"] == 104025.0

        # 逾期 800 天原始违约金 40% 触发 20% 封顶上限
        out_2 = exec_res[1]["output"]
        assert out_2["gross_amount"] == 12800.0
        assert out_2["overdue_penalty"] == 2560.0


def test_snapshot_timemachine_save_mutate_and_exact_restore(
    tmp_path: Path,
) -> None:
    """
    测试用例 4：
    保存集群快照 -> 吞噬多份新台账并执行企业创世空投彻底改变集群状态 ->
    调用 /api/v1/snapshots/restore 一键时间回滚 ->
    验证球总数、工位数、账号与挂载关系 100% 精确恢复到快照时间点，且 WORM 账本记录 SNAPSHOT_RESTORED！
    """
    sandbox_dir = tmp_path / "sandbox"
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'm11_snap.db').as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=sandbox_dir,
    )
    app = _create_test_app(settings)
    with TestClient(app) as client:
        rt = app.state.runtime
        initial_ball_ids = sorted(b.ball_id for b in rt.particles.list_all_balls())
        initial_slot_ids = sorted(s.slot_id for s in rt.containers.list_slots())
        initial_followup_balls = list(
            rt.containers.get_slot("SLOT_FOLLOWUP_01").ball_ids
        )

        # 1. 保存初始黄金快照
        save_res = client.post(
            "/api/v1/snapshots/save",
            json={
                "label": "Pre-Mutation Golden Baseline",
                "note": "吞噬与空投前的12工位标准基线快照",
            },
        )
        assert save_res.status_code == 200
        snap_meta = save_res.json()
        snapshot_id = snap_meta["snapshot_id"]
        assert snap_meta["stats"]["ball_count"] == len(initial_ball_ids)
        assert snap_meta["stats"]["slot_count"] == len(initial_slot_ids)

        # 2. 破坏性变更：吞噬 2 份文档新增 8 颗球，随后再执行赞比亚车队创世空投重置整个集群
        samples = client.get("/api/v1/ingest/samples").json()["samples"]
        for s in samples[:2]:
            client.post(
                "/api/v1/ingest/document",
                json={
                    "doc_title": s["doc_title"],
                    "doc_format": s["doc_format"],
                    "raw_content": s["raw_content"],
                    "target_department": s["target_department"],
                    "target_slot_id": s["target_slot_id"],
                },
            )
        assert len(rt.particles.list_all_balls()) == len(initial_ball_ids) + 8

        # 再保存第二个变更后快照，验证 list_snapshots 按时间倒序排列
        save_res_2 = client.post(
            "/api/v1/snapshots/save",
            json={"label": "Post-Ingestion State", "note": "已吞噬两份台账"},
        )
        assert save_res_2.status_code == 200

        # 执行创世空投彻底替换工位与球库
        tpl = client.get("/api/v1/genesis/templates").json()["templates"][0]
        client.post(
            "/api/v1/genesis/deploy-enterprise",
            json={
                "enterprise_name": tpl["enterprise_name"],
                "business_description": tpl["business_description"],
                "reset_existing": True,
            },
        )
        assert len(rt.containers.list_slots()) != len(initial_slot_ids)

        # 检查快照列表（应有 2 个时间机器快照，且最新创建的排第一）
        list_res = client.get("/api/v1/snapshots/list")
        assert list_res.status_code == 200
        snap_list = list_res.json()["snapshots"]
        assert len(snap_list) == 2
        assert snap_list[0]["label"] == "Post-Ingestion State"
        assert snap_list[1]["snapshot_id"] == snapshot_id

        # 3. 调用 restore_snapshot 一键回滚至初始黄金快照
        restore_res = client.post(
            "/api/v1/snapshots/restore",
            json={"snapshot_id": snapshot_id},
        )
        assert restore_res.status_code == 200
        restored_data = restore_res.json()
        assert restored_data["restored"] is True
        assert restored_data["snapshot_id"] == snapshot_id
        assert restored_data["worm_event"]["event_kind"] == "SNAPSHOT_RESTORED"

        # 4. 验证球数、工位数与挂载关系 100% 精确恢复
        restored_ball_ids = sorted(b.ball_id for b in rt.particles.list_all_balls())
        restored_slot_ids = sorted(s.slot_id for s in rt.containers.list_slots())
        restored_followup_balls = list(
            rt.containers.get_slot("SLOT_FOLLOWUP_01").ball_ids
        )

        assert restored_ball_ids == initial_ball_ids
        assert restored_slot_ids == initial_slot_ids
        assert restored_followup_balls == initial_followup_balls

        # 验证 WORM 账本链完整性
        chain_report = rt.vault.verify_chain_integrity()
        assert chain_report.intact is True

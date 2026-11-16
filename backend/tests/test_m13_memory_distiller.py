from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import load_settings
from main import create_app
from surfaces.memory_distiller_routes import memory_distiller_router


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
        getattr(r, "path", "").startswith("/api/v1/memory") for r in app.routes
    ):
        app.include_router(memory_distiller_router)
    return app


def test_slot_memory_distillation_and_ball_version_auto_upgrade(
    tmp_path: Path,
) -> None:
    """
    测试用例 1：
    验证工位实战记忆蒸馏 (POST /api/v1/memory/distill)：
    - 扫描历史工单、企微对话、已挂载权能球与双面档案；
    - 提炼 3~5 枚 MemoryCrystal（含隐性经验规则、高频踩坑点、谈判底线策略、最优算子调用范式）；
    - 当 auto_upgrade_balls=True 时，自动反哺升级关联 DATA / AUTHORITY 球版本 (version += 1)；
    - WORM 账本写入 SLOT_MEMORY_DISTILLED 且哈希链 100% 完好。
    """
    app = _build_test_app(tmp_path, "m13_distill.db")
    with TestClient(app) as client:
        rt = app.state.runtime

        # 先发送一条企微业务消息产生真实工单上下文
        chat_res = client.post(
            "/api/v1/chat/message",
            json={
                "sender_id": "emp_chen",
                "role_view": "employee",
                "facade_bot": "COPILOT",
                "chat_type": "SINGLE",
                "content": "查一下A款人体工学椅现货库存和公开价格",
            },
        )
        assert chat_res.status_code == 200

        before_cat_ver = rt.particles.get_ball("BALL_DATA_CATALOG_2026").version
        before_auth_ver = rt.particles.get_ball("BALL_AUTH_FOLLOWUP_QUOTE").version

        distill_res = client.post(
            "/api/v1/memory/distill",
            json={"slot_id": "SLOT_FOLLOWUP_01", "auto_upgrade_balls": True},
        )
        assert distill_res.status_code == 200
        data = distill_res.json()

        assert data["slot_id"] == "SLOT_FOLLOWUP_01"
        assert 3 <= data["crystal_count"] <= 5
        assert len(data["crystals"]) == data["crystal_count"]

        for crystal in data["crystals"]:
            assert crystal["tacit_rule"]
            assert crystal["pitfall_warning"]
            assert crystal["negotiation_strategy"]
            assert crystal["optimal_operator_pattern"]
            assert crystal["confidence_score"] >= 0.8

        # 验证 DATA / AUTHORITY 球版本号已自动 +1 且内容已写入记忆结晶反哺记录
        assert len(data["upgraded_balls"]) >= 2
        after_cat_ball = rt.particles.get_ball("BALL_DATA_CATALOG_2026")
        after_auth_ball = rt.particles.get_ball("BALL_AUTH_FOLLOWUP_QUOTE")
        assert after_cat_ball.version == before_cat_ver + 1
        assert after_auth_ball.version == before_auth_ver + 1
        assert "记忆结晶反哺" in after_cat_ball.content

        # 验证 WORM 账本已记录 SLOT_MEMORY_DISTILLED
        assert data["worm_event"]["event_kind"] == "SLOT_MEMORY_DISTILLED"
        vault_records = rt.vault.read_records()
        assert any(r.event_kind == "SLOT_MEMORY_DISTILLED" for r in vault_records)
        assert client.get("/api/v1/vault/verify").json()["intact"] is True


def test_zero_loss_handover_reclaims_leases_retains_resident_balls_and_binds_new_employee(
    tmp_path: Path,
) -> None:
    """
    测试用例 2：
    验证“铁打的工位流水的兵”零损数字交接包生成与演练 (POST /api/v1/memory/zero-loss-handover)：
    1. 交接前为工位挂载一颗临时租借球 (BorrowedBallLease)；
    2. 触发零损交接（emp_chen 离职/调岗 -> 新员工 emp_wu_new「小吴」接替）；
    3. 验证临时租借球被自动回收清退，而常驻权能球 100% 保留在工位容器上；
    4. 验证交接包含有常驻球清单、记忆结晶、未决工单上下文与 3 道上岗实测考题；
    5. 验证新员工 emp_wu_new 已绑定至工位且可直接登录系统零衰减作业。
    """
    app = _build_test_app(tmp_path, "m13_handover.db")
    with TestClient(app) as client:
        rt = app.state.runtime

        # 1) 让 SLOT_FOLLOWUP_01 临时借用组长老李的 BALL_AUTH_LEADER_HV_GATE
        rt.containers.borrow_ball(
            borrower_slot_id="SLOT_FOLLOWUP_01",
            lender_slot_id="SLOT_LEADER_01",
            ball_id="BALL_AUTH_LEADER_HV_GATE",
            ttl_seconds=600,
        )
        slot_before = rt.containers.get_slot("SLOT_FOLLOWUP_01")
        assert len(slot_before.borrowed_balls) == 1
        resident_count_before = len(slot_before.ball_ids)

        # 2) 执行零损数字交接
        handover_res = client.post(
            "/api/v1/memory/zero-loss-handover",
            json={
                "slot_id": "SLOT_FOLLOWUP_01",
                "outgoing_user_id": "emp_chen",
                "incoming_user_name": "小吴",
                "incoming_user_id": "emp_wu_new",
            },
        )
        assert handover_res.status_code == 200
        h_data = handover_res.json()

        assert h_data["slot_id"] == "SLOT_FOLLOWUP_01"
        assert h_data["outgoing_user_id"] == "emp_chen"
        assert h_data["incoming_user_id"] == "emp_wu_new"
        assert h_data["incoming_user_name"] == "小吴"
        assert h_data["combat_power_retention"] == 1.0
        assert h_data["zero_loss_verified"] is True

        # 验证临时租借球已回收，常驻球 100% 保留
        assert len(h_data["reclaimed_borrowed_balls"]) == 1
        assert (
            h_data["reclaimed_borrowed_balls"][0]["ball_id"]
            == "BALL_AUTH_LEADER_HV_GATE"
        )
        assert len(h_data["resident_balls"]) == resident_count_before
        slot_after = rt.containers.get_slot("SLOT_FOLLOWUP_01")
        assert len(slot_after.borrowed_balls) == 0
        assert slot_after.occupant_id == "emp_wu_new"

        # 验证实战记忆结晶与 3 道上岗实测考题齐全
        assert len(h_data["memory_crystals"]) >= 3
        assert len(h_data["onboarding_exam"]) == 3
        assert h_data["worm_event"]["event_kind"] == "ZERO_LOSS_HANDOVER_COMPLETED"

        # 验证新员工小吴 (emp_wu_new) 可直接登录并获取完整工位权能视图
        login_res = client.post(
            "/api/v1/auth/login",
            json={"username": "emp_wu_new", "password": "123456"},
        )
        assert login_res.status_code == 200
        assert login_res.json()["account"]["name"] == "小吴"

        ov_res = client.get(
            "/api/v1/state/overview?role_view=employee&user_id=emp_wu_new"
        )
        assert ov_res.status_code == 200
        ov_data = ov_res.json()
        assert len(ov_data["my_slot"]["ball_ids"]) == resident_count_before
        assert len(ov_data["my_slot"]["borrowed_balls"]) == 0
        assert len(ov_data["accessible_balls"]) >= resident_count_before


def test_memory_distillation_without_upgrade_and_blackbox_slot_support(
    tmp_path: Path,
) -> None:
    """
    测试用例 3：
    1. 验证 auto_upgrade_balls=False 时仅蒸馏记忆结晶而不升级已有权能球版本；
    2. 验证对初始无 DATA/AUTHORITY 球的财务黑盒工位 (SLOT_FINANCE_BOX) 开启 auto_upgrade_balls=True 时，
       能够自动铸造并升级岗位 SOP DATA 球。
    """
    app = _build_test_app(tmp_path, "m13_no_upgrade.db")
    with TestClient(app) as client:
        rt = app.state.runtime
        ver_before = rt.particles.get_ball("BALL_DATA_CATALOG_2026").version

        res_no_upg = client.post(
            "/api/v1/memory/distill",
            json={"slot_id": "SLOT_LEADER_01", "auto_upgrade_balls": False},
        )
        assert res_no_upg.status_code == 200
        no_upg_data = res_no_upg.json()
        assert no_upg_data["crystal_count"] >= 3
        assert no_upg_data["upgraded_balls"] == []
        assert rt.particles.get_ball("BALL_DATA_CATALOG_2026").version == ver_before

        # 对财务黑盒工位执行蒸馏并自动反哺
        res_fin = client.post(
            "/api/v1/memory/distill",
            json={"slot_id": "SLOT_FINANCE_BOX", "auto_upgrade_balls": True},
        )
        assert res_fin.status_code == 200
        fin_data = res_fin.json()
        assert fin_data["crystal_count"] >= 3
        assert len(fin_data["upgraded_balls"]) >= 1
        assert fin_data["upgraded_balls"][0]["new_version"] == 2


def test_memory_crystals_query_and_slot_filtering(tmp_path: Path) -> None:
    """
    测试用例 4：
    验证 GET /api/v1/memory/crystals 支持全量查询与按 slot_id 过滤查询，
    并返回完整的 distillation_runs 与 handover_records。
    """
    app = _build_test_app(tmp_path, "m13_crystals_list.db")
    with TestClient(app) as client:
        d1 = client.post(
            "/api/v1/memory/distill",
            json={"slot_id": "SLOT_FOLLOWUP_01", "auto_upgrade_balls": True},
        )
        assert d1.status_code == 200

        d2 = client.post(
            "/api/v1/memory/distill",
            json={"slot_id": "SLOT_WMS_01", "auto_upgrade_balls": True},
        )
        assert d2.status_code == 200

        h1 = client.post(
            "/api/v1/memory/zero-loss-handover",
            json={
                "slot_id": "SLOT_WMS_01",
                "outgoing_user_id": "wms_zhao",
                "incoming_user_name": "新仓储主管老周",
            },
        )
        assert h1.status_code == 200

        all_res = client.get("/api/v1/memory/crystals")
        assert all_res.status_code == 200
        all_data = all_res.json()
        assert all_data["total_crystals"] >= 6
        assert len(all_data["distillation_runs"]) == 2
        assert len(all_data["handover_records"]) == 1

        wms_res = client.get("/api/v1/memory/crystals?slot_id=SLOT_WMS_01")
        assert wms_res.status_code == 200
        wms_data = wms_res.json()
        assert 3 <= wms_data["total_crystals"] <= 5
        assert all(c["slot_id"] == "SLOT_WMS_01" for c in wms_data["crystals"])

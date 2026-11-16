from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from config import load_settings
from core.schemas import CapabilityBall
from main import create_app


def _make_test_app(tmp_path: Path, name: str):
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / f'{name}.db').as_posix()}",
        vault_storage_dir=tmp_path / f"{name}_vault",
        sandbox_workspace_dir=tmp_path / f"{name}_sandbox",
    )
    return create_app(settings)


def test_catalog_taxonomy_and_redline_rbac_isolation(tmp_path: Path) -> None:
    app = _make_test_app(tmp_path, "m15_cat")
    with TestClient(app) as client:
        # 1. 普通员工查询目录：应包含 5 大业务分类、中文性质标签，且绝不泄漏未授权的风控底线
        emp_res = client.get("/api/v1/lifecycle/catalog?user_id=emp_chen")
        assert emp_res.status_code == 200
        emp_data = emp_res.json()
        assert emp_data["business_categories"] == [
            "销售与报价",
            "仓储与物流",
            "采购与品控",
            "财务与法务",
            "风控与管理",
        ]
        assert len(emp_data["modules"]) > 0
        for mod in emp_data["modules"]:
            assert mod["business_category"] in emp_data["business_categories"]
            assert mod["type_label"] in ("业务资料", "计算工具", "审批权限", "风控底线")
            assert mod["quick_use_prompt"]
            assert mod["ball_type"] != "REDLINE"
            if not mod["is_mounted"]:
                assert "content" not in mod
                assert "executable_code_path" not in mod

        emp_raw = emp_res.text
        assert "480" not in emp_raw

        # 2. 主管不能读取红线模块；仅老板目录包含完整红线模块
        mgr_res = client.get("/api/v1/lifecycle/catalog?user_id=mgr_zhang")
        assert mgr_res.status_code == 200
        mgr_mods = mgr_res.json()["modules"]
        assert all(m["ball_type"] != "REDLINE" for m in mgr_mods)
        assert "480" not in mgr_res.text
        boss_res = client.get("/api/v1/lifecycle/catalog?user_id=boss_lin")
        assert boss_res.status_code == 200
        assert any(m["ball_type"] == "REDLINE" for m in boss_res.json()["modules"])


def test_midwife_incubate_and_split_classification(tmp_path: Path) -> None:
    app = _make_test_app(tmp_path, "m15_midwife")
    with TestClient(app) as client:
        # 1. 从新制度生成分类原子模块
        res = client.post(
            "/api/v1/lifecycle/incubate",
            json={
                "actor_user_id": "leader_li",
                "raw_policy_text": (
                    "【冷链物流运费标准】1. 标准温控配送首重3公斤内10元，超过3公斤每公斤加4元，"
                    "单笔订单满500元免运费；2. 超重特批超过200元需主管审批；3. 严禁泄露车队成本底价。"
                ),
            },
        )
        assert res.status_code == 200
        data = res.json()
        created = data["created_modules"]
        assert len(created) >= 3
        assert all(m["business_category"] for m in created)
        assert all(m["type_label"] for m in created)

        # 2. 将其中一个大模块一分为二
        target_id = created[0]["ball_id"]
        split_res = client.post(
            "/api/v1/lifecycle/incubate",
            json={
                "actor_user_id": "leader_li",
                "target_ball_id": target_id,
            },
        )
        assert split_res.status_code == 200
        split_data = split_res.json()
        assert split_data["mode"] == "BALL_MITOSIS"
        assert len(split_data["created_modules"]) == 2

        # 原模块已淘汰归档，不应再出现在员工活跃列表里
        custody = client.get("/api/v1/custody/overview?user_id=leader_li").json()
        active_ids = {b["ball_id"] for b in custody["mounted_balls"]}
        assert target_id not in active_ids


def test_reaper_scan_merge_archive_and_restore(tmp_path: Path) -> None:
    app = _make_test_app(tmp_path, "m15_reaper")
    with TestClient(app) as client:
        rt = app.state.runtime
        # 注入一对高度相似的重复资料模块
        ball_keep = CapabilityBall(
            ball_id="BALL_DATA_PRICE_V2",
            ball_type="DATA",
            title="华东区标准阶梯报价规范手册",
            domain_tags=["报价", "折扣"],
            sensitivity_level=1,
            owner_slot_ids=["SLOT_FOLLOWUP_01"],
            content="华东区常规产品满20件享9折，满100件享85折，报价有效期7个工作日。",
            version=2,
            status="ACTIVE",
        )
        ball_dup = CapabilityBall(
            ball_id="BALL_DATA_PRICE_V1_DUP",
            ball_type="DATA",
            title="华东区标准阶梯报价规范手册(旧版)",
            domain_tags=["报价"],
            sensitivity_level=1,
            owner_slot_ids=["SLOT_FOLLOWUP_01", "SLOT_FOLLOWUP_02"],
            content="华东区常规产品满20件享9折，满100件享85折，报价有效期7个工作日。",
            version=1,
            status="ACTIVE",
        )
        rt.particles.register_ball(ball_keep)
        rt.particles.register_ball(ball_dup)
        rt.containers.attach_ball_to_slot("SLOT_FOLLOWUP_01", ball_keep.ball_id)
        rt.containers.attach_ball_to_slot("SLOT_FOLLOWUP_01", ball_dup.ball_id)
        rt.containers.attach_ball_to_slot("SLOT_FOLLOWUP_02", ball_dup.ball_id)

        # 1. 死神健康扫描应检出这对重复模块
        scan = client.get("/api/v1/lifecycle/health-scan?user_id=mgr_zhang").json()
        dup_cand = next(
            (
                c
                for c in scan["reaper_candidates"]
                if c["kind"] == "DUPLICATE_SIMILAR"
                and {c["target_ball_id"], c["merge_into_ball_id"]}
                == {ball_keep.ball_id, ball_dup.ball_id}
            ),
            None,
        )
        assert dup_cand is not None
        assert dup_cand["target_ball_id"] == ball_dup.ball_id
        assert dup_cand["merge_into_ball_id"] == ball_keep.ball_id

        # 2. 执行合并去重 (MERGE)
        merge_res = client.post(
            "/api/v1/lifecycle/reap",
            json={
                "actor_user_id": "mgr_zhang",
                "action": "MERGE",
                "target_ball_id": ball_dup.ball_id,
                "merge_into_ball_id": ball_keep.ball_id,
                "reason": "合并重复报价规范",
            },
        )
        assert merge_res.status_code == 200
        merge_data = merge_res.json()
        assert merge_data["kept_ball"]["version"] == 3
        assert merge_data["archived_ball"]["status"] == "DEPRECATED"

        # 原本只挂载旧版球的 SLOT_FOLLOWUP_02 应自动迁移为挂载新版球，不再有旧版球
        emp_zhou_cust = client.get("/api/v1/custody/overview?user_id=emp_zhou").json()
        zhou_ids = {b["ball_id"] for b in emp_zhou_cust["mounted_balls"]}
        assert ball_dup.ball_id not in zhou_ids
        assert ball_keep.ball_id in zhou_ids

        # 3. 归档目录中可见已淘汰模块，并支持一键恢复
        cat_mgr = client.get("/api/v1/lifecycle/catalog?user_id=mgr_zhang").json()
        archived_ids = {m["ball_id"] for m in cat_mgr["archived_modules"]}
        assert ball_dup.ball_id in archived_ids

        restore_res = client.post(
            "/api/v1/lifecycle/restore",
            json={
                "actor_user_id": "mgr_zhang",
                "ball_id": ball_dup.ball_id,
                "target_slot_id": "SLOT_FOLLOWUP_02",
            },
        )
        assert restore_res.status_code == 200
        assert restore_res.json()["restored_ball"]["status"] == "ACTIVE"

        # 4. 执行直接淘汰归档 (ARCHIVE)
        archive_res = client.post(
            "/api/v1/lifecycle/reap",
            json={
                "actor_user_id": "mgr_zhang",
                "action": "ARCHIVE",
                "target_ball_id": ball_dup.ball_id,
                "reason": "彻底停用旧版",
            },
        )
        assert archive_res.status_code == 200
        assert archive_res.json()["archived_ball"]["status"] == "DEPRECATED"

        vault_verify = client.get("/api/v1/vault/verify").json()
        assert vault_verify["intact"] is True

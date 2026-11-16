from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from config import ArachneSettings
from main import create_app


def _strict_settings(tmp_path: Path, **overrides) -> ArachneSettings:
    defaults = dict(
        _env_file=None,
        llm_api_key="",
        enforce_bearer_auth=True,
        bootstrap_password="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'hot.db').as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=tmp_path / "sandbox",
    )
    defaults.update(overrides)
    return ArachneSettings(**defaults)


def _login_headers(client: TestClient, user_id: str, password: str) -> dict[str, str]:
    res = client.post(
        "/api/v1/auth/login",
        json={"username": user_id, "password": password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_unauthenticated_and_forbidden_mutations_skip_snapshot_rollback(
    tmp_path: Path,
) -> None:
    settings = _strict_settings(tmp_path, bootstrap_password="StrongBoss#2026")
    with TestClient(create_app(settings)) as client:
        rt = client.app.state.runtime
        counts = {"capture": 0, "restore": 0}
        orig_capture = rt.capture_state
        orig_restore = rt.restore_runtime_state

        async def counted_capture():
            counts["capture"] += 1
            return await orig_capture()

        async def counted_restore(payload, preserve_security: bool = True):
            counts["restore"] += 1
            return await orig_restore(payload, preserve_security=preserve_security)

        rt.capture_state = counted_capture  # type: ignore[method-assign]
        rt.restore_runtime_state = counted_restore  # type: ignore[method-assign]

        # 1. 未鉴权 401 不应触发全库导出与回滚
        unauth = client.post("/api/v1/board/convene", json={})
        assert unauth.status_code == 401
        assert counts == {"capture": 0, "restore": 0}

        # 2. 登录错密 401 与正常登录/登出不应触发全库导出与回滚
        bad_login = client.post(
            "/api/v1/auth/login",
            json={"username": "boss_lin", "password": "wrong-password"},
        )
        assert bad_login.status_code == 401
        assert counts == {"capture": 0, "restore": 0}

        emp_headers = _login_headers(client, "emp_chen", "StrongBoss#2026")
        assert counts == {"capture": 0, "restore": 0}

        # 3. 越权 403 不应触发全库导出与回滚
        forbidden = client.post("/api/v1/board/convene", json={}, headers=emp_headers)
        assert forbidden.status_code == 403
        assert counts == {"capture": 0, "restore": 0}

        assert (
            client.post("/api/v1/auth/logout", headers=emp_headers).status_code == 200
        )
        assert counts == {"capture": 0, "restore": 0}
        assert client.get("/api/v1/auth/me", headers=emp_headers).status_code == 401

        # 4. 鉴权通过但业务抛错（如无效 resolution_id）仍必须执行完整事务回滚
        boss_headers = _login_headers(client, "boss_lin", "StrongBoss#2026")
        failed_biz = client.post(
            "/api/v1/board/approve-transition",
            json={"resolution_id": "NON_EXISTENT_RES", "approve": True},
            headers=boss_headers,
        )
        assert failed_biz.status_code >= 400
        assert counts == {"capture": 1, "restore": 1}


def test_genesis_deploy_and_cross_enterprise_snapshot_preserve_boss_login(
    tmp_path: Path,
) -> None:
    settings = _strict_settings(tmp_path, bootstrap_password="")
    with TestClient(create_app(settings)) as client:
        rt = client.app.state.runtime
        rt.auth_custody.set_password("boss_lin", "StrictBoss#2026")
        boss_headers = _login_headers(client, "boss_lin", "StrictBoss#2026")

        # 探路并点亮企业 A，包含特定岗位的业务头衔（empty-shell 会吊销旧会话但保留 boss 口令）
        assert (
            client.post(
                "/api/v1/exploration/empty-shell",
                json={"enterprise_name": "深圳嘉立创测试集团"},
                headers=boss_headers,
            ).status_code
            == 200
        )
        boss_headers = _login_headers(client, "boss_lin", "StrictBoss#2026")
        scout_res = client.post(
            "/api/v1/exploration/scout",
            json={
                "enterprise_name": "深圳嘉立创测试集团",
                "raw_org_material": (
                    "1. 【PCB报价与接单部】：负责多层板与SMT贴片阶梯报价核算；"
                    "设「PCB报价跟单员」(employee) 与「工程审单组长」(leader)。\n"
                    "2. 【财务开票部】：负责13%专票核验开具；设「金税开票专岗」(finance_tool)。"
                ),
            },
            headers=boss_headers,
        )
        assert scout_res.status_code == 200, scout_res.text
        boss_headers = _login_headers(client, "boss_lin", "StrictBoss#2026")
        scouted_nodes = [
            n
            for n in scout_res.json()["nodes"]
            if n.get("exploration_state") == "SCOUTED"
            and n.get("node_type") == "WORKER_SLOT"
        ]
        assert len(scouted_nodes) >= 1
        assert (
            client.post(
                "/api/v1/exploration/plant-torch",
                json={"target_node_id": scouted_nodes[0]["node_id"]},
                headers=boss_headers,
            ).status_code
            == 200
        )
        emp_a_before = next(
            p for p in rt.containers.list_profiles() if p.role_view != "boss"
        )
        emp_a_uid = emp_a_before.user_id
        emp_a_title = emp_a_before.title

        snap_a = client.post(
            "/api/v1/snapshots/save",
            json={"label": "嘉立创基线", "note": "A"},
            headers=boss_headers,
        )
        assert snap_a.status_code == 200, snap_a.text
        snap_a_id = snap_a.json()["snapshot_id"]

        # 在严格无 bootstrap_password 模式下执行创世一键部署新企业 B（新 boss user_id 不再叫 boss_lin）
        deploy_res = client.post(
            "/api/v1/genesis/deploy-enterprise",
            json={
                "enterprise_name": "赞比亚跨境铜矿陆运车队",
                "business_description": (
                    "1. 按公里和吨位核算跨境重卡运费，超过30吨附加3.5%损耗保费；\n"
                    "2. 单车运费折扣低于9折需车队组长特批，低于8折或超出12万元需董事长审批；\n"
                    "3. 严禁超载违章发车。"
                ),
                "reset_existing": True,
            },
            headers=boss_headers,
        )
        assert deploy_res.status_code == 200, deploy_res.text
        new_boss = next(
            a for a in deploy_res.json()["accounts"] if a["role_view"] == "boss"
        )
        assert new_boss["user_id"] != "boss_lin"

        # 验证创世部署后新企业的 boss 账号依然可以沿用原管理员口令直接登录
        new_boss_headers = _login_headers(
            client, new_boss["user_id"], "StrictBoss#2026"
        )

        # 若把 B 企业某员工 ID 手工模拟成同名碰撞 ID 并赋予不同头衔，切换回 A 快照时头衔不应被 B 污染
        b_front = next(
            p
            for p in rt.containers.list_profiles()
            if p.role_view == emp_a_before.role_view
        )
        b_front_clone = b_front.model_copy(
            update={"user_id": emp_a_uid, "title": "赞比亚矿车调度员（误碰撞测试）"}
        )
        rt.containers.register_profile(b_front_clone)
        rt.auth_custody.sync_accounts_from_containers()

        restore_res = client.post(
            "/api/v1/snapshots/restore",
            json={"snapshot_id": snap_a_id},
            headers=new_boss_headers,
        )
        assert restore_res.status_code == 200, restore_res.text

        # 验证切换回企业 A 快照后：boss_lin 可立即用管理员口令登录，且同名员工恢复原企业 A 头衔
        restored_boss_headers = _login_headers(client, "boss_lin", "StrictBoss#2026")
        assert (
            client.get("/api/v1/exploration/map", headers=restored_boss_headers).json()[
                "enterprise_name"
            ]
            == "深圳嘉立创测试集团"
        )
        assert rt.containers.get_profile(emp_a_uid).title == emp_a_title


def test_handover_initial_password_and_dynamic_pipeline_presets(
    tmp_path: Path,
) -> None:
    settings = _strict_settings(tmp_path, bootstrap_password="")
    with TestClient(create_app(settings)) as client:
        rt = client.app.state.runtime
        rt.auth_custody.set_password("boss_lin", "BossSecret#2026")
        boss_headers = _login_headers(client, "boss_lin", "BossSecret#2026")

        assert (
            client.post(
                "/api/v1/exploration/empty-shell",
                json={"enterprise_name": "深圳精密传感器测试公司"},
                headers=boss_headers,
            ).status_code
            == 200
        )
        boss_headers = _login_headers(client, "boss_lin", "BossSecret#2026")
        scout_res = client.post(
            "/api/v1/exploration/scout",
            json={
                "enterprise_name": "深圳精密传感器测试公司",
                "raw_org_material": (
                    "1. 【工业传感器销售与报价部】：按批量阶梯计价；设「传感器销售专员」(employee) 与「大区销售组长」(leader)。\n"
                    "2. 【智能制造与供应链部】：安全库存核算补货；设「供应链调度员」(employee)。"
                ),
            },
            headers=boss_headers,
        )
        assert scout_res.status_code == 200, scout_res.text
        boss_headers = _login_headers(client, "boss_lin", "BossSecret#2026")
        scouted_workers = [
            n
            for n in scout_res.json()["nodes"]
            if n.get("exploration_state") == "SCOUTED"
            and n.get("node_type") in ("WORKER_SLOT", "RELAY_NODE", "HUMAN_BLACKBOX")
        ]
        assert len(scouted_workers) >= 1
        for node in scouted_workers:
            assert (
                client.post(
                    "/api/v1/exploration/plant-torch",
                    json={"target_node_id": node["node_id"]},
                    headers=boss_headers,
                ).status_code
                == 200
            )

        # 非家具企业调用流水线预设：不得包含 CHAIR-PRO-A1 且保持 SKU-STD-01；未传源球时按 M17 契约拒绝合成，传真实 ACTIVE 源球可正常合成
        presets_res = client.get("/api/v1/pipelines/presets", headers=boss_headers)
        assert presets_res.status_code == 200
        assert "CHAIR-PRO-A1" not in presets_res.text
        assert "SKU-STD-01" in presets_res.text

        unpaired_compose = client.post(
            "/api/v1/pipelines/compose",
            json={"preset_id": "pipe_end_to_end_order_profit"},
            headers=boss_headers,
        )
        assert unpaired_compose.status_code == 400

        active_ids = [
            b.ball_id
            for b in rt.particles.list_all_balls()
            if b.status == "ACTIVE" and b.ball_type in ("DATA", "SKILL", "AUTHORITY")
        ]
        assert len(active_ids) >= 1
        compose_res = client.post(
            "/api/v1/pipelines/compose",
            json={
                "preset_id": "pipe_end_to_end_order_profit",
                "source_skill_ball_ids": active_ids[:3],
            },
            headers=boss_headers,
        )
        assert compose_res.status_code == 200, compose_res.text

        # 交接时直接指定接任者 initial_password，接任者立即可登录，离职原账号不可登录且状态标记准确
        front_emp = next(
            p for p in rt.containers.list_profiles() if p.role_view == "employee"
        )
        provisioned = client.post(
            f"/api/v1/auth/accounts/{front_emp.user_id}/password",
            headers=boss_headers,
            json={"new_password": "OriginalEmployee#2026"},
        )
        assert provisioned.status_code == 200, provisioned.text
        old_emp_headers = _login_headers(
            client, front_emp.user_id, "OriginalEmployee#2026"
        )
        handover_res = client.post(
            "/api/v1/custody/handover",
            json={
                "target_slot_id": front_emp.slot_id,
                "new_user_id": "sensor_new_01",
                "new_person_name": "新接班专员",
                "handover_mode": "RESIGN_HANDOVER",
                "initial_password": "Successor#2026",
            },
            headers=boss_headers,
        )
        assert handover_res.status_code == 200, handover_res.text
        assert handover_res.json()["password_provisioned"] is True

        _login_headers(client, "sensor_new_01", "Successor#2026")

        old_login = client.post(
            "/api/v1/auth/login",
            json={"username": front_emp.user_id, "password": "OriginalEmployee#2026"},
        )
        assert old_login.status_code == 401
        assert client.get("/api/v1/auth/me", headers=old_emp_headers).status_code == 401

        accounts = client.get("/api/v1/auth/accounts").json()["accounts"]
        new_acc = next(a for a in accounts if a["user_id"] == "sensor_new_01")
        old_acc = next(a for a in accounts if a["user_id"] == front_emp.user_id)
        assert new_acc["has_password"] is True
        assert new_acc["is_disabled"] is False
        assert old_acc["is_disabled"] is True

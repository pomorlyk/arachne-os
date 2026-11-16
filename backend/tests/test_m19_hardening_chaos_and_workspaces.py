from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi.testclient import TestClient

from config import ArachneSettings
from core.schemas import WorkTicket
from main import create_app


def _make_settings(
    tmp_path: Path, db_name: str, llm_api_key: str = "", **extra: Any
) -> ArachneSettings:
    db_file = (tmp_path / db_name).resolve().as_posix()
    extra.setdefault("enforce_bearer_auth", False)
    extra.setdefault("bootstrap_password", "123456")
    extra.setdefault("connector_hmac_secret", "m19-explicit-test-signing-secret")
    return ArachneSettings(
        llm_api_key=llm_api_key,
        sqlite_db_url=f"sqlite+aiosqlite:///{db_file}",
        vault_storage_dir=tmp_path / "vault_storage",
        sandbox_workspace_dir=tmp_path / "sandbox_workspace",
        **extra,
    )


def _bootstrap_enterprise_sync(
    client: TestClient,
    enterprise_name: str,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    hdrs = headers if headers is not None else {}
    empty_res = client.post(
        "/api/v1/exploration/empty-shell",
        json={"enterprise_name": enterprise_name},
        headers=hdrs,
    )
    assert empty_res.status_code == 200, empty_res.text
    def reauthenticate_after_reset() -> None:
        if not hdrs:
            return
        # Reset/scout replace workspace identities and revoke the administrator too.
        assert client.get("/api/v1/auth/me", headers=hdrs).status_code == 401
        boss = next(account for account in client.get("/api/v1/auth/accounts").json()["accounts"] if account["role_view"] == "boss")
        login = client.post("/api/v1/auth/login", json={"username": boss["username"], "password": "123456"})
        assert login.status_code == 200, login.text
        hdrs["Authorization"] = f"Bearer {login.json()['token']}"

    reauthenticate_after_reset()
    scout_res = client.post(
        "/api/v1/exploration/scout",
        json={
            "enterprise_name": enterprise_name,
            "raw_org_material": (
                f"{enterprise_name} 设有四大核心部门与岗位：\n"
                "1. 【工程交付部】：设「一线报价专员」（负责工艺核算与打样报价，底价红线为每套380元）与「风控审核组长」（负责特批与异常裁决）；\n"
                "2. 【智能制造部】：设「排产运营专员」（负责BOM核验、设备负载测算与交期调度）；\n"
                "3. 【财税合规部】：设「财税合规黑盒专员」（负责数电专票开具、回款稽核与客户隐私合规）；\n"
                "4. 【经营治理部】：设「运营管理经理」（负责跨部门协同治理与进化复核）。"
            ),
        },
        headers=hdrs,
    )
    assert scout_res.status_code == 200, scout_res.text
    reauthenticate_after_reset()

    nodes = client.get("/api/v1/exploration/map", headers=hdrs).json()["nodes"]
    for node in nodes:
        if node.get("exploration_state") == "SCOUTED":
            sop_text = ""
            if node.get("node_type") == "WORKER_SLOT":
                sop_text = (
                    "打样开机费60元/款 + 每平方分米单价15元；"
                    "底价红线每套380元，低于8.5折须风控审核组长特批；"
                    "红线：严禁泄露客户图纸及原材料拿货底价。"
                )
            torch_res = client.post(
                "/api/v1/exploration/plant-torch",
                json={"target_node_id": node["node_id"], "raw_sop_text": sop_text},
                headers=hdrs,
            )
            assert torch_res.status_code == 200, torch_res.text

    return client.get("/api/v1/exploration/map", headers=hdrs).json()


def test_password_pbkdf2_hashing_and_strict_bearer_anti_spoofing(
    tmp_path: Path,
) -> None:
    """
    验证 PBKDF2-SHA256 密码加盐哈希落盘 + 全局 Bearer Token 鉴权与防越权/防伪造拦截：
    1. 未带 Token 访问受保护业务接口返回 401，公开接口返回 200；
    2. 原始 SQLite `account_directory_entries.password` 全部为 `pbkdf2_sha256$` 哈希且无明文 `"123456"`；
    3. 一线员工 Bearer Token 越权请求 `role_view=boss` 或伪造 `sender_id` / `user_id` 全部返回 403；
    4. 修改密码后旧密码 401、新密码 200；调用 logout 后旧 Token 立即 401 失效。
    """
    db_name = "m19_auth_guard.db"
    settings = _make_settings(tmp_path, db_name, enforce_bearer_auth=True)
    app = create_app(settings)

    with TestClient(app) as client:
        health_res = client.get("/api/v1/system/health")
        assert health_res.status_code == 200
        health_json = health_res.json()
        assert health_json["security"]["enforce_bearer_auth"] is True
        assert health_json["security"]["password_hash_scheme"] == "pbkdf2_sha256"

        # 未带 Token 访问业务接口均须被 401 拦截
        assert (
            client.get("/api/v1/state/overview?role_view=boss").status_code == 401
        )
        assert client.get("/api/v1/snapshots/list").status_code == 401

        accounts_res = client.get("/api/v1/auth/accounts")
        assert accounts_res.status_code == 200
        initial_accounts = accounts_res.json()["accounts"]
        initial_boss = next(a for a in initial_accounts if a["role_view"] == "boss")

        boss_login = client.post(
            "/api/v1/auth/login",
            json={"username": initial_boss["username"], "password": "123456"},
        )
        assert boss_login.status_code == 200
        boss_headers = {"Authorization": f"Bearer {boss_login.json()['token']}"}

        # 用合法 boss Bearer 接入一家全新非家具厂企业
        _bootstrap_enterprise_sync(
            client,
            enterprise_name="深圳大疆创新研发制造中心",
            headers=boss_headers,
        )

        # 直查 SQLite 原始密码列，确认无明文密码泄露
        conn = sqlite3.connect(str(tmp_path / db_name))
        try:
            rows = conn.execute(
                "SELECT user_id, password_value FROM account_directory_entries"
            ).fetchall()
        finally:
            conn.close()
        assert len(rows) >= 3
        for uid, stored_pw in rows:
            assert stored_pw != "123456", f"{uid} 存在明文密码"
            assert stored_pw.startswith("pbkdf2_sha256$"), f"{uid} 未使用 PBKDF2"

        new_accounts = client.get("/api/v1/auth/accounts").json()["accounts"]
        emp_acc = next(a for a in new_accounts if a["role_view"] == "employee")
        boss_acc = next(a for a in new_accounts if a["role_view"] == "boss")

        emp_login = client.post(
            "/api/v1/auth/login",
            json={"username": emp_acc["username"], "password": "123456"},
        )
        assert emp_login.status_code == 200
        emp_token = emp_login.json()["token"]
        emp_headers = {"Authorization": f"Bearer {emp_token}"}

        # 越权查询 boss 视图 -> 403
        esc_res = client.get(
            "/api/v1/state/overview?role_view=boss", headers=emp_headers
        )
        assert esc_res.status_code == 403

        # 越权查询他人 user_id 视图 -> 403
        other_uid_res = client.get(
            f"/api/v1/state/overview?role_view=employee&user_id={boss_acc['user_id']}",
            headers=emp_headers,
        )
        assert other_uid_res.status_code == 403

        # POST 请求体伪造他人 sender_id -> 403
        spoof_post = client.post(
            "/api/v1/chat/message",
            json={
                "sender_id": boss_acc["user_id"],
                "role_view": "employee",
                "facade_bot": "COPILOT",
                "content": "冒充高管发指令",
            },
            headers=emp_headers,
        )
        assert spoof_post.status_code == 403

        # 合法本人发消息 -> 200
        ok_post = client.post(
            "/api/v1/chat/message",
            json={
                "sender_id": emp_acc["user_id"],
                "role_view": "employee",
                "facade_bot": "COPILOT",
                "content": "确认本岗位当前合规报价流程",
            },
            headers=emp_headers,
        )
        assert ok_post.status_code == 200

        # 修改密码后校验新旧密码与注销失效
        chg_res = client.post(
            "/api/v1/auth/change-password",
            json={
                "user_id": emp_acc["user_id"],
                "old_password": "123456",
                "new_password": "DjiSafe#2026!",
            },
            headers=emp_headers,
        )
        assert chg_res.status_code == 200

        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": emp_acc["username"], "password": "123456"},
            ).status_code
            == 401
        )
        relogin_res = client.post(
            "/api/v1/auth/login",
            json={"username": emp_acc["username"], "password": "DjiSafe#2026!"},
        )
        assert relogin_res.status_code == 200
        emp_token2 = relogin_res.json()["token"]

        logout_res = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {emp_token2}"},
        )
        assert logout_res.status_code == 200
        assert (
            client.get(
                f"/api/v1/state/overview?role_view=employee&user_id={emp_acc['user_id']}",
                headers={"Authorization": f"Bearer {emp_token2}"},
            ).status_code
            == 401
        )


def test_concurrent_write_stress_no_race_or_lock_failure(tmp_path: Path) -> None:
    """
    验证 16 路并发异步写入压测下，SQLite asyncio.Lock 与 WORM Vault threading.RLock 无竞态、无锁死、链完整性 100%。
    """
    app = create_app(_make_settings(tmp_path, "m19_concurrency.db"))

    async def _run() -> None:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                ov = (
                    await client.get("/api/v1/state/overview?role_view=boss")
                ).json()
                profiles = ov["all_profiles"]
                all_balls = ov["all_balls"]
                emp_prof = next(
                    p for p in profiles if p["role_view"] == "employee"
                )
                req_ball = next(
                    b for b in all_balls if b["ball_type"] in ("DATA", "AUTHORITY", "SKILL")
                )

                tasks = []
                for i in range(6):
                    tasks.append(
                        client.post(
                            "/api/v1/chat/message",
                            json={
                                "sender_id": emp_prof["user_id"],
                                "role_view": "employee",
                                "facade_bot": "COPILOT",
                                "content": f"并发询价单 #{i}：请问标准交付工期与报价依据",
                            },
                        )
                    )
                for i in range(4):
                    tasks.append(
                        client.post(
                            "/api/v1/custody/requests",
                            json={
                                "requester_id": emp_prof["user_id"],
                                "ball_id": req_ball["ball_id"],
                                "grant_mode": "LEASE_TTL",
                                "ttl_minutes": 30,
                                "reason": f"并发借用申请 #{i}",
                            },
                        )
                    )
                for i in range(4):
                    tasks.append(
                        client.post(
                            "/api/v1/snapshots/save",
                            json={
                                "label": f"并发压测快照_{i}",
                                "note": "16-way concurrent stress",
                            },
                        )
                    )
                for _ in range(2):
                    tasks.append(
                        client.post(
                            "/api/v1/swarm/inject-burst",
                            json={"mode": "BURST_PAD", "burst_count": 2},
                        )
                    )

                assert len(tasks) == 16
                responses = await asyncio.gather(*tasks)
                for idx, resp in enumerate(responses):
                    assert resp.status_code == 200, f"Task #{idx} failed: {resp.text}"

                verify_res = await client.get("/api/v1/vault/verify")
                assert verify_res.status_code == 200
                verify_json = verify_res.json()
                assert verify_json["intact"] is True
                assert verify_json["total_records"] >= 16

                snaps_res = await client.get("/api/v1/snapshots/list")
                assert snaps_res.status_code == 200
                assert len(snaps_res.json()["snapshots"]) >= 4

    asyncio.run(_run())


def test_llm_gateway_chaos_fault_injection_resilience(tmp_path: Path) -> None:
    """
    验证实时 LLM 模式开启后若上游发生截断 JSON、TimeoutError、HTTP 429 限流、Schema 非法响应，
    系统零崩溃、全部优雅降级为确定性兜底引擎并返回 HTTP 200。
    """
    app = create_app(
        _make_settings(
            tmp_path,
            "m19_chaos.db",
            llm_api_key="sk-chaos-fault-injection-mock",
        )
    )

    fault_cycle = iter(
        [
            lambda: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"broken": [1, 2'))]
            ),
            lambda: (_ for _ in ()).throw(TimeoutError("simulated upstream read timeout")),
            lambda: (_ for _ in ()).throw(RuntimeError("HTTP 429 rate limit exceeded")),
            lambda: SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"unexpected_field": 999}')
                    )
                ]
            ),
        ]
    )
    fault_funcs = [
        lambda: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"broken": [1, 2'))]
        ),
        lambda: (_ for _ in ()).throw(TimeoutError("simulated upstream read timeout")),
        lambda: (_ for _ in ()).throw(RuntimeError("HTTP 429 rate limit exceeded")),
        lambda: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"unexpected_field": 999}')
                )
            ]
        ),
    ]
    call_counter = {"n": 0}

    async def _chaos_create(*_args: Any, **_kwargs: Any) -> Any:
        idx = call_counter["n"] % len(fault_funcs)
        call_counter["n"] += 1
        return fault_funcs[idx]()

    del fault_cycle
    chaos_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=_chaos_create)
        )
    )

    with TestClient(app) as client:
        rt = app.state.runtime
        rt.llm_gateway._client = chaos_client

        # 依次在故障注入下跑通：空壳 -> 探路 -> 点亮 -> 对话 -> 董事会召集
        assert (
            client.post(
                "/api/v1/exploration/empty-shell",
                json={"enterprise_name": "容错混沌测试电子有限公司"},
            ).status_code
            == 200
        )
        scout_res = client.post(
            "/api/v1/exploration/scout",
            json={
                "enterprise_name": "容错混沌测试电子有限公司",
                "raw_org_material": (
                    "1. 订单客服部：负责接单报价；设一线跟单专员、风控审批组长；\n"
                    "2. 财务开票部：负责发票核销；设财务黑盒专员；\n"
                    "3. 运营管理部：负责协同调度；设运营经理。"
                ),
            },
        )
        assert scout_res.status_code == 200
        nodes = scout_res.json()["nodes"]
        worker_node = next(
            n for n in nodes if n.get("node_type") == "WORKER_SLOT"
        )
        torch_res = client.post(
            "/api/v1/exploration/plant-torch",
            json={
                "target_node_id": worker_node["node_id"],
                "raw_sop_text": "订单未满300元加收18元快递费；低于8.5折须风控组长特批。",
            },
        )
        assert torch_res.status_code == 200

        accounts = client.get("/api/v1/auth/accounts").json()["accounts"]
        emp = next(a for a in accounts if a["role_view"] == "employee")
        chat_res = client.post(
            "/api/v1/chat/message",
            json={
                "sender_id": emp["user_id"],
                "role_view": "employee",
                "facade_bot": "COPILOT",
                "content": "请问今天有哪些待确认单据？",
            },
        )
        assert chat_res.status_code == 200

        board_res = client.post("/api/v1/board/convene", json={})
        assert board_res.status_code == 200

        telemetry = client.get("/api/v1/llm/telemetry").json()
        assert call_counter["n"] >= 3
        assert telemetry["deterministic_engine_hits"] > 0


def test_worm_ledger_and_overview_scale_benchmark(tmp_path: Path) -> None:
    """
    验证 420+ 条 WORM 黑盒审计事件 + 120 条工单规模下，全链校验与老板全览接口均可在 2 秒内完成。
    """
    app = create_app(_make_settings(tmp_path, "m19_scale.db"))

    async def _seed_bulk(rt: Any) -> None:
        for i in range(420):
            rt.vault.append_event(
                event_kind="SCALE_BENCHMARK_AUDIT",
                subtree_root_id="root",
                actor_slot_id="SLOT_BENCH",
                payload={"seq": i, "metric": round(i * 1.25, 2)},
            )
        for i in range(120):
            ticket = WorkTicket(
                ticket_id=f"TKT_SCALE_{i:04d}",
                subtree_root_id="root",
                node_id="node_scale_bench",
                initiator_id="role_frontline_01",
                slot_id="SLOT_BENCH",
                facade_bot="COPILOT",
                status="COMPLETED" if i % 2 == 0 else "OPEN",
                summary=f"压测工单摘要 #{i}",
            )
            await rt.hot_store.upsert_ticket(ticket)

    with TestClient(app) as client:
        rt = app.state.runtime
        portal = client.portal  # anyio blocking portal provided by Starlette TestClient
        assert portal is not None
        portal.call(_seed_bulk, rt)

        t0 = time.perf_counter()
        verify_res = client.get("/api/v1/vault/verify")
        verify_elapsed = time.perf_counter() - t0
        assert verify_res.status_code == 200
        assert verify_res.json()["intact"] is True
        assert verify_res.json()["total_records"] >= 420
        assert verify_elapsed < 2.0, f"WORM 校验耗时过长: {verify_elapsed:.3f}s"

        t1 = time.perf_counter()
        ov_res = client.get("/api/v1/state/overview?role_view=boss")
        ov_elapsed = time.perf_counter() - t1
        assert ov_res.status_code == 200
        assert len(ov_res.json()["tickets"]) >= 120
        assert ov_elapsed < 2.0, f"Overview 聚合耗时过长: {ov_elapsed:.3f}s"


def test_multi_enterprise_snapshot_profile_full_switch(tmp_path: Path) -> None:
    """
    验证企业级全量存档时间机器切换：
    企业 A（含自进化 Python 技能球 + 外部 Webhook 连接器）-> 保存快照 snap_a
    -> 重塑为企业 B -> 保存快照 snap_b -> 恢复 snap_a
    -> 验证企业元数据、技能球脚本、Webhook 连接器完整归位且新 FastAPI 重启后仍维持企业 A -> 最后删除 snap_b。
    """
    settings = _make_settings(tmp_path, "m19_multi_enterprise.db")
    app1 = create_app(settings)

    with TestClient(app1) as client1:
        # 1. 部署企业 A
        _bootstrap_enterprise_sync(client1, "深圳迈瑞医疗器械测试总部")
        ov_a = client1.get("/api/v1/state/overview?role_view=boss").json()
        emp_a = next(
            p for p in ov_a["all_profiles"] if p["role_view"] == "employee"
        )
        leader_a = next(
            p for p in ov_a["all_profiles"] if p["role_view"] == "leader"
        )

        employee_login = client1.post("/api/v1/auth/login", json={"username": emp_a["user_id"], "password": "123456"})
        assert employee_login.status_code == 200
        original_employee_headers = {"Authorization": f"Bearer {employee_login.json()['token']}"}

        # 为企业 A 铸造 1 颗动态 Python 技能球并挂载 Webhook 连接器
        evo_res = client1.post(
            "/api/v1/evolution/propose",
            json={
                "proposer_id": emp_a["user_id"],
                "natural_instruction": (
                    "每次手工算物流运费太累了：首重3公斤内10元，超过3公斤部分每公斤加4元，订单满500元免运费，帮我做成自动工具"
                ),
            },
        )
        assert evo_res.status_code == 200
        assert evo_res.json()["arena_report"]["promoted"] is True
        minted_ball_id = evo_res.json()["arena_report"]["minted_ball_id"]
        assert minted_ball_id

        bind_res = client1.post(
            "/api/v1/connectors/bindings",
            json={
                "slot_id": leader_a["slot_id"],
                "connector_type": "HTTP_WEBHOOK",
                "endpoint_url": "https://mindray.local/hooks/approval",
                "enabled": True,
            },
        )
        assert bind_res.status_code == 200

        # 保存企业 A 快照
        snap_a_res = client1.post(
            "/api/v1/snapshots/save",
            json={"label": "迈瑞医疗基线", "note": "Enterprise A snapshot"},
        )
        assert snap_a_res.status_code == 200
        snap_a = snap_a_res.json()
        assert snap_a["enterprise_name"] == "深圳迈瑞医疗器械测试总部"
        assert snap_a["workspace_mode"] == "FULLY_LIT"
        snap_a_id = snap_a["snapshot_id"]

        # 2. 切换建构企业 B（验证企业 A 资产被隔离开）
        _bootstrap_enterprise_sync(client1, "宁德时代新能源电池测试基地")
        map_b = client1.get("/api/v1/exploration/map").json()
        assert map_b["enterprise_name"] == "宁德时代新能源电池测试基地"
        balls_b = client1.get("/api/v1/state/overview?role_view=boss").json()["all_balls"]
        assert all(b["ball_id"] != minted_ball_id for b in balls_b)

        snap_b_res = client1.post(
            "/api/v1/snapshots/save",
            json={"label": "宁德时代基线", "note": "Enterprise B snapshot"},
        )
        assert snap_b_res.status_code == 200
        snap_b_id = snap_b_res.json()["snapshot_id"]

        # 3. 通过快照时间机器无损切换回企业 A
        restore_res = client1.post(
            "/api/v1/snapshots/restore",
            json={"snapshot_id": snap_a_id},
        )
        assert restore_res.status_code == 200
        assert client1.get("/api/v1/auth/me", headers=original_employee_headers).status_code == 401
        map_restored = client1.get("/api/v1/exploration/map").json()
        assert map_restored["enterprise_name"] == "深圳迈瑞医疗器械测试总部"
        assert map_restored["mode"] == "FULLY_LIT"

        ov_restored = client1.get("/api/v1/state/overview?role_view=boss").json()
        assert any(b["ball_id"] == minted_ball_id for b in ov_restored["all_balls"])

        bindings_restored = client1.get("/api/v1/connectors/bindings").json()["bindings"]
        assert any(
            b["endpoint_url"] == "https://mindray.local/hooks/approval"
            for b in bindings_restored
        )

        # Restored business assets do not revive identity. Explicitly provision and log in.
        boss = next(a for a in client1.get("/api/v1/auth/accounts").json()["accounts"] if a["role_view"] == "boss")
        boss_login = client1.post("/api/v1/auth/login", json={"username": boss["user_id"], "password": "123456"})
        assert boss_login.status_code == 200
        boss_headers = {"Authorization": f"Bearer {boss_login.json()['token']}"}
        provision = client1.post(f"/api/v1/auth/accounts/{emp_a['user_id']}/password", json={"new_password": "RestoredEmployee#2026"}, headers=boss_headers)
        assert provision.status_code == 200, provision.text
        employee_login = client1.post("/api/v1/auth/login", json={"username": emp_a["user_id"], "password": "RestoredEmployee#2026"})
        assert employee_login.status_code == 200
        employee_headers = {"Authorization": f"Bearer {employee_login.json()['token']}"}

        # 验证恢复回来的技能球沙箱源码依然能 0-Token 执行！
        chat_calc = client1.post(
            "/api/v1/chat/message",
            headers=employee_headers,
            json={
                "sender_id": emp_a["user_id"],
                "role_view": "employee",
                "facade_bot": "COPILOT",
                "content": "请算一下 5公斤、订单120元的顺丰运费",
            },
        )
        assert chat_calc.status_code == 200
        assert "18" in chat_calc.json()["message"]["content"]

        # 4. 删除快照 B
        del_res = client1.delete(f"/api/v1/snapshots/{snap_b_id}")
        assert del_res.status_code == 200
        assert del_res.json()["deleted"] is True
        snap_ids_left = [
            s["snapshot_id"]
            for s in client1.get("/api/v1/snapshots/list").json()["snapshots"]
        ]
        assert snap_a_id in snap_ids_left
        assert snap_b_id not in snap_ids_left

    # 5. 重建全新 FastAPI app 实例验证从 SQLite 重启仍停留在企业 A
    app2 = create_app(settings)
    with TestClient(app2) as client2:
        map_reboot = client2.get("/api/v1/exploration/map").json()
        assert map_reboot["enterprise_name"] == "深圳迈瑞医疗器械测试总部"
        assert map_reboot["mode"] == "FULLY_LIT"
        ov_reboot = client2.get("/api/v1/state/overview?role_view=boss").json()
        assert any(b["ball_id"] == minted_ball_id for b in ov_reboot["all_balls"])
        bindings_reboot = client2.get("/api/v1/connectors/bindings").json()["bindings"]
        assert any(
            b["endpoint_url"] == "https://mindray.local/hooks/approval"
            for b in bindings_reboot
        )

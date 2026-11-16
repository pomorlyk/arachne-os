from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from config import ArachneSettings
from main import create_app


def _make_settings(tmp_path: Path, db_name: str = "m17_persist.db") -> ArachneSettings:
    return ArachneSettings(
        enforce_bearer_auth=False,
        vault_storage_dir=tmp_path / "vault_m17",
        sandbox_workspace_dir=tmp_path / "sandbox_m17",
        sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path / db_name}",
        llm_api_key="",
    )


def _bootstrap_non_furniture_enterprise(
    client: TestClient,
    enterprise_name: str = "深圳嘉立创科技集团",
    industry: str = "PCB与电子制造",
) -> dict:
    empty_res = client.post(
        "/api/v1/exploration/empty-shell",
        json={"enterprise_name": enterprise_name},
    )
    assert empty_res.status_code == 200

    scout_res = client.post(
        "/api/v1/exploration/scout",
        json={
            "enterprise_name": enterprise_name,
            "raw_org_material": (
                f"{enterprise_name} 设有四大核心部门与岗位：\n"
                "1. 【工程客服部】：设「EDA工程审核专员」（负责Gerber审图、阻抗计算与PCB打样报价，底价红线为每平米380元）与「工程风控组长」（负责特批与异常裁决）；\n"
                "2. 【制造排产部】：设「SMT贴片排产专员」（负责元器件BOM核验与产能调度）；\n"
                "3. 【财税合规部】：设「财税合规黑盒专员」（负责数电专票开具、资金回款稽核与客户隐私合规）；\n"
                "4. 【供应链治理部】：设「供应链运营经理」（负责物料库存水位管控、交期优化与人机协同进化治理）。"
            ),
        },
    )
    assert scout_res.status_code == 200
    scout_data = scout_res.json()
    slot_nodes = [
        n for n in scout_data.get("nodes", [])
        if n.get("node_type") in ("WORKER_SLOT", "RELAY_NODE", "BLACKBOX_HUMAN")
    ]
    assert len(slot_nodes) >= 3

    for node in slot_nodes:
        sop_text = ""
        if node.get("node_type") == "WORKER_SLOT":
            sop_text = (
                "打样收费标准：工程费50元/款 + 每平米单价420元；"
                "底价红线每平米380元，低于8.5折须工程风控组长特批；"
                "红线：严禁对外泄露客户Gerber源文件及覆铜板拿货底价。"
            )
        torch_res = client.post(
            "/api/v1/exploration/plant-torch",
            json={"target_node_id": node["node_id"], "raw_sop_text": sop_text},
        )
        assert torch_res.status_code == 200

    map_res = client.get("/api/v1/exploration/map")
    assert map_res.status_code == 200
    return map_res.json()


def test_restart_persistence_across_app_recreation(tmp_path: Path) -> None:
    """
    Task 1 验收：
    冷启动接入非家具厂新企业 -> 逐岗点亮 -> 铸造技能球 -> 离职交接 RESIGN_HANDOVER
    -> 重建全新 FastAPI app 实例（模拟 uvicorn 重启）
    -> 验证企业元数据、新员工登录态、继承的技能球（含沙箱脚本）及红线防御全部无损恢复。
    """
    settings = _make_settings(tmp_path, "m17_restart.db")

    app1 = create_app(settings)
    minted_ball_id = ""
    handover_slot_id = ""
    old_user_id = ""
    boss_user_id = "boss_root"

    with TestClient(app1) as client1:
        map_data = _bootstrap_non_furniture_enterprise(client1)
        assert map_data["enterprise_name"] == "深圳嘉立创科技集团"
        assert map_data["mode"] == "FULLY_LIT"

        boss_ov = client1.get("/api/v1/state/overview?role_view=boss&user_id=boss_root").json()
        profiles = boss_ov["all_profiles"]
        boss_prof = next(p for p in profiles if p["role_view"] == "boss")
        boss_user_id = boss_prof["user_id"]
        fl_prof = next(p for p in profiles if p["role_view"] == "employee")
        old_user_id = fl_prof["user_id"]
        handover_slot_id = fl_prof["slot_id"]

        evo_res = client1.post(
            "/api/v1/evolution/propose",
            json={
                "proposer_id": old_user_id,
                "natural_instruction": "每次手工算PCB打样阶梯运费太累了：首重3公斤内10元，超过3公斤部分每公斤加4元，订单满500元免运费，帮我做成自动工具",
            },
        )
        assert evo_res.status_code == 200
        evo_data = evo_res.json().get("arena_report", evo_res.json())
        assert evo_data["promoted"] is True
        minted_ball_id = evo_data["minted_ball_id"]
        assert minted_ball_id

        ho_res = client1.post(
            "/api/v1/custody/handover",
            json={
                "actor_user_id": boss_user_id,
                "target_slot_id": handover_slot_id,
                "new_user_id": "jlc_new_emp",
                "new_person_name": "林新锐",
                "handover_mode": "RESIGN_HANDOVER",
                "reason": "原一线员工离职，零损交接给新入职林新锐",
            },
        )
        assert ho_res.status_code == 200
        assert ho_res.json()["new_user_id"] == "jlc_new_emp"

    # 模拟进程重启：重新创建全新 app 实例读取同一个 SQLite 库
    app2 = create_app(settings)
    with TestClient(app2) as client2:
        map2 = client2.get("/api/v1/exploration/map").json()
        assert map2["enterprise_name"] == "深圳嘉立创科技集团"
        assert map2["mode"] == "FULLY_LIT"

        # 离职旧账号登录失效，新员工 jlc_new_emp 登录成功
        old_login = client2.post(
            "/api/v1/auth/login",
            json={"username": old_user_id, "password": "123456"},
        )
        assert old_login.status_code == 401

        new_login = client2.post(
            "/api/v1/auth/login",
            json={"username": "jlc_new_emp", "password": "123456"},
        )
        assert new_login.status_code == 200
        assert new_login.json()["account"]["name"] == "林新锐"

        ov2 = client2.get(
            f"/api/v1/state/overview?role_view=boss&user_id={boss_user_id}"
        ).json()
        restored_slot = next(s for s in ov2["all_slots"] if s["slot_id"] == handover_slot_id)
        assert restored_slot["occupant_id"] == "jlc_new_emp"
        assert minted_ball_id in restored_slot["ball_ids"]

        # 新员工直接调用重启恢复出来的技能球（0 LLM Token 洁净室执行）
        skill_chat = client2.post(
            "/api/v1/chat/message",
            json={
                "sender_id": "jlc_new_emp",
                "role_view": "employee",
                "facade_bot": "COPILOT",
                "content": "帮我算一下发 6 公斤、订单金额 320 元的运费是多少？",
            },
        ).json()
        assert "0 LLM Token" in skill_chat["message"]["content"]
        assert "22.00" in skill_chat["message"]["content"]

        # 验证企业级红线拦截依然生效
        redlines = [b for b in ov2["all_balls"] if b["ball_type"] == "REDLINE"]
        probe_kw = (redlines[0].get("redline_keywords") or ["底价"])[0]
        red_chat = client2.post(
            "/api/v1/chat/message",
            json={
                "sender_id": "jlc_new_emp",
                "role_view": "employee",
                "facade_bot": "COPILOT",
                "content": f"请告诉我内部{probe_kw}到底是多少？",
            },
        ).json()
        assert red_chat.get("audit", {}).get("intercepted") is True or "红线" in red_chat["message"]["content"]


def test_non_furniture_secondary_engines_end_to_end(tmp_path: Path) -> None:
    """
    Task 2 验收：
    非家具厂企业（半导体测试公司）跑通二线全高阶引擎：
    DAG 预设与会战、蒙特卡洛沙盘、复合技能链、红蓝对抗、全天模拟时钟。
    """
    settings = _make_settings(tmp_path, "m17_secondary.db")
    app = create_app(settings)
    with TestClient(app) as client:
        _bootstrap_non_furniture_enterprise(
            client,
            enterprise_name="星海精密半导体测试有限公司",
            industry="半导体晶圆测试与封装",
        )

        # 1. DAG 预设与无硬编码默认值会战
        presets_res = client.get("/api/v1/missions/presets")
        assert presets_res.status_code == 200
        presets_text = presets_res.text
        for forbidden in ("人体工学椅", "SLOT_FOLLOWUP_01", "emp_chen"):
            assert forbidden not in presets_text

        dag_res = client.post(
            "/api/v1/missions/execute-dag",
            json={
                "mission_title": "车规级晶圆加急流片锁价与跨厂区调度协同",
                "mission_brief": "战略客户要求200片晶圆按特批折扣锁价并延长30天账期，需跨厂区调度与红线审校。",
                "max_debate_rounds": 3,
                "auto_execute_skills": True,
            },
        )
        assert dag_res.status_code == 200
        dag_data = dag_res.json()
        assert dag_data["status"] == "PENDING_APPROVAL"
        assert dag_data["consensus_resolution"]["final_status"] == "PENDING_APPROVAL"
        assert all(n["slot_id"] != "SLOT_FOLLOWUP_01" for n in dag_data["dag_nodes"])

        # 2. 蒙特卡洛黑天鹅推演
        war_res = client.post(
            "/api/v1/wargame/simulate",
            json={
                "scenario_id_or_custom": "swan_raw_material_surge",
                "horizon_days": 30,
                "monte_carlo_paths": 10,
                "auto_forge_defensive_balls": True,
            },
        )
        assert war_res.status_code == 200
        war_data = war_res.json()
        involved_slots = [
            s
            for stage in war_data.get("timeline_stages", [])
            for s in stage.get("participating_slots", [])
        ]
        assert involved_slots
        assert "SLOT_FOLLOWUP_01" not in involved_slots

        # 3. 新企业缺少预设的真实源资料，必须拒绝合成，不能补造家具行业模块。
        pipe_presets = client.get("/api/v1/pipelines/presets").json()["presets"]
        assert len(pipe_presets) == 3
        comp_res = client.post(
            "/api/v1/pipelines/compose",
            json={"preset_id": "pipe_end_to_end_order_profit"},
        )
        assert comp_res.status_code == 400
        assert "Source ball must exist and be ACTIVE" in comp_res.json()["detail"]
        assert client.get("/api/v1/pipelines/history").json()["composed_count"] == 0

        # 4. 红蓝对抗与全天时钟模拟
        ov_boss = client.get("/api/v1/state/overview?role_view=boss&user_id=boss_root").json()
        target_slot_id = next(
            p["slot_id"] for p in ov_boss["all_profiles"] if p["role_view"] == "employee"
        )
        cruc_res = client.post(
            "/api/v1/crucible/redline-penetration",
            json={"target_slot_id": target_slot_id, "attack_count": 3},
        )
        assert cruc_res.status_code == 200

        sim_res = client.post("/api/v1/simulation/run-full-day")
        assert sim_res.status_code == 200
        sim_data = sim_res.json()
        assert sim_data["is_day_completed"] is False
        assert sim_data["status"] == "PENDING_REVIEW"
        assert sim_data["completed_logs"][-1]["phase"] == "WECHAT_AND_GATE"
        assert sim_data["metrics"]["skills_minted"] == 0
        assert sim_data["scope"]["isolated"] is True


def test_cascade_rehydration_across_dag_and_lifecycle_api(tmp_path: Path) -> None:
    app = create_app(_make_settings(tmp_path, "m17_cascade_lifecycle.db"))
    with TestClient(app) as client:
        _bootstrap_non_furniture_enterprise(
            client,
            enterprise_name="瑞联精密光电子股份有限公司",
            industry="高速光模块研发与精密封装",
        )
        map_data = client.get("/api/v1/exploration/map").json()
        nodes = map_data["nodes"]
        non_root_nodes = [
            n for n in nodes if n["node_type"] in ("ASPECT_NODE", "RELAY_NODE", "WORKER_SLOT", "BLACKBOX_HUMAN")
        ]
        assert len(non_root_nodes) >= 2

        sample_nid = non_root_nodes[0]["node_id"]
        # 1. employee 视图无权切换节点生命周期（403）
        forbidden_res = client.post(
            f"/api/v1/swarm/nodes/{sample_nid}/lifecycle",
            json={"action": "DEHYDRATE", "role_view": "employee"},
        )
        assert forbidden_res.status_code == 403

        # 2. 经理批量将业务部门与一线岗位节点脱水休眠
        dehydrated_targets: list[str] = []
        for n in non_root_nodes:
            res = client.post(
                f"/api/v1/swarm/nodes/{n['node_id']}/lifecycle",
                json={"action": "DEHYDRATE", "reason": "night_idle", "role_view": "manager"},
            )
            assert res.status_code == 200
            assert res.json()["status"] == "DEHYDRATED"
            dehydrated_targets.append(n["node_id"])

        # 3. 发起跨部 DAG 会战，验证级联热唤醒自动点亮涉及工位及其上级部门节点链
        dag_res = client.post(
            "/api/v1/missions/execute-dag",
            json={
                "mission_title": "800G光模块良率异常跨部排查协同",
                "mission_brief": "产线激光焊接良率波动，需协调工程交付与质检合规岗位加急复核并出具处置方案。",
                "max_debate_rounds": 2,
                "auto_execute_skills": True,
            },
        )
        assert dag_res.status_code == 200
        dag_data = dag_res.json()
        rehydrated = dag_data.get("rehydrated_node_ids", [])
        assert len(rehydrated) >= 2

        after_map = {n["node_id"]: n for n in client.get("/api/v1/exploration/map").json()["nodes"]}
        for rid in rehydrated:
            assert after_map[rid]["status"] == "ACTIVE"
        worker_nids = {n["node_id"] for n in nodes if n.get("slot_id")}
        assert any(rid in worker_nids for rid in rehydrated)

        # 4. 手动 REHYDRATE 其余仍脱水的节点
        remaining_dehydrated = [
            nid for nid in dehydrated_targets if after_map[nid]["status"] == "DEHYDRATED"
        ]
        target_manual = remaining_dehydrated[0] if remaining_dehydrated else sample_nid
        wake_res = client.post(
            f"/api/v1/swarm/nodes/{target_manual}/lifecycle",
            json={"action": "REHYDRATE", "reason": "manual_ops_wake", "role_view": "leader"},
        )
        assert wake_res.status_code == 200
        assert wake_res.json()["status"] == "ACTIVE"


def test_board_seat_cap_and_differentiated_domain_votes(tmp_path: Path) -> None:
    import asyncio
    from core.schemas import SpiderNode, WorkTicket

    app = create_app(_make_settings(tmp_path, "m17_board_cap.db"))
    with TestClient(app) as client:
        _bootstrap_non_furniture_enterprise(
            client,
            enterprise_name="华科数字能源科技有限公司",
            industry="储能变流器与微电网调度",
        )
        rt = app.state.runtime

        async def _seed_many_aspects() -> None:
            specs = [
                ("aspect_rd_power", "电力电子研发部", "sub_rd_power", ["电力电子", "交付"], "ACTIVE", "WORKER_SLOT", 2),
                ("aspect_grid_ops", "微网运维服务部", "sub_grid_ops", ["运维", "工单"], "ACTIVE", "WORKER_SLOT", 3),
                ("aspect_comp_audit", "安全合规法务部", "sub_comp_audit", ["合规", "审计"], "DEHYDRATED", "BLACKBOX_HUMAN", 0),
                ("aspect_supply_chain", "关键器件供应链", "sub_supply_chain", ["采购", "BOM"], "ACTIVE", "WORKER_SLOT", 1),
                ("aspect_quality_lab", "CNAS测试认证中心", "sub_quality_lab", ["质检", "测试"], "DEHYDRATED", "WORKER_SLOT", 0),
                ("aspect_finance_ctrl", "项目核算与风控部", "sub_finance_ctrl", ["财务", "风控"], "ACTIVE", "BLACKBOX_HUMAN", 4),
            ]
            for aid, label, sub_id, tags, child_status, child_type, ticket_cnt in specs:
                await rt.hot_store.upsert_node(
                    SpiderNode(
                        node_id=aid,
                        label=label,
                        node_type="ASPECT_NODE",
                        parent_id="root",
                        subtree_root_id=sub_id,
                        domain_tags=tags,
                        status="ACTIVE",
                    )
                )
                await rt.hot_store.upsert_node(
                    SpiderNode(
                        node_id=f"child_{aid}",
                        label=f"{label}核心专岗",
                        node_type=child_type,  # type: ignore[arg-type]
                        parent_id=aid,
                        subtree_root_id=sub_id,
                        domain_tags=tags,
                        status=child_status,  # type: ignore[arg-type]
                    )
                )
                for idx in range(ticket_cnt):
                    await rt.hot_store.upsert_ticket(
                        WorkTicket(
                            ticket_id=f"TKT_{aid}_{idx}",
                            subtree_root_id=sub_id,
                            node_id=f"child_{aid}",
                            initiator_id="tester",
                            slot_id="SLOT_CAVE_TEST",
                            facade_bot="COPILOT",
                            status="COMPLETED",
                            summary=f"{label}协同测试工单 #{idx}",
                        )
                    )

        asyncio.run(_seed_many_aspects())

        ov_boss = client.get("/api/v1/state/overview?role_view=boss&user_id=boss_root").json()
        target_slot_id = next(
            p["slot_id"] for p in ov_boss["all_profiles"] if p["role_view"] == "employee"
        )
        board_res = client.post(
            "/api/v1/board/convene",
            json={
                "target_slot_id": target_slot_id,
                "agenda": "审议储能一线工位进入师徒反转过渡期",
            },
        )
        assert board_res.status_code == 200
        resolution = board_res.json()["resolution"]
        votes = resolution["votes"]
        assert len(votes) <= 7

        iron_votes = [v for v in votes if v["seat_type"] == "IRON_TRIANGLE"]
        dyn_votes = [v for v in votes if v["seat_type"] == "DYNAMIC_DOMAIN"]
        assert len(iron_votes) == 3
        assert 1 <= len(dyn_votes) <= 4
        distinct_scores = {round(float(v["score"]), 2) for v in dyn_votes}
        assert len(distinct_scores) >= 2



from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from config import load_settings
from main import create_app


def test_zambia_copper_fleet_genesis_login_and_rbac_closed_loop(
    tmp_path: Path,
) -> None:
    """
    验证：
    1. GET /api/v1/genesis/templates 返回 3 个真实行业预设模板；
    2. POST /api/v1/genesis/deploy-enterprise 空投「赞比亚跨境铜矿陆运车队」(reset_existing=True)；
    3. 自动生成 3~4 个业务域子树、6~8 个标准岗位容器与账号、6~10 颗涵盖 DATA/SKILL/AUTHORITY/REDLINE 的权能球；
    4. SKILL 球真实生成 Python execute_skill 脚本落盘至 sandbox_workspace/；
    5. 新工位账号可正常登录、球正常挂载、WORM 账本写入 ENTERPRISE_GENESIS_DEPLOYED。
    """
    sandbox_dir = tmp_path / "sandbox"
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'm8_genesis.db').as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=sandbox_dir,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        # 1. 获取预设模板列表
        tpl_res = client.get("/api/v1/genesis/templates")
        assert tpl_res.status_code == 200
        templates = tpl_res.json()["templates"]
        assert len(templates) == 3
        zambia_tpl = next(t for t in templates if "赞比亚" in t["enterprise_name"])
        assert "柴油补贴底价" in zambia_tpl["business_description"]

        # 2. 执行企业创世空投冷启动繁殖
        deploy_res = client.post(
            "/api/v1/genesis/deploy-enterprise",
            json={
                "enterprise_name": zambia_tpl["enterprise_name"],
                "business_description": zambia_tpl["business_description"],
                "reset_existing": True,
            },
        )
        assert deploy_res.status_code == 200
        deployed = deploy_res.json()

        assert 3 <= deployed["aspect_count"] <= 4
        assert 6 <= deployed["slot_count"] <= 8
        assert 6 <= deployed["ball_count"] <= 10
        assert deployed["worm_event"]["event_kind"] == "ENTERPRISE_GENESIS_DEPLOYED"

        # 验证四类权能球齐全，且 SKILL 球脚本已真实落盘至 sandbox_workspace/
        initial_balls = deployed["initial_balls"]
        ball_types = {b["ball_type"] for b in initial_balls}
        assert {"DATA", "SKILL", "AUTHORITY", "REDLINE"}.issubset(ball_types)

        skill_balls = [b for b in initial_balls if b["ball_type"] == "SKILL"]
        assert len(skill_balls) >= 1
        for sb in skill_balls:
            assert sb["executable_code_path"] is not None
            script_file = sandbox_dir / sb["executable_code_path"]
            assert script_file.exists()
            assert "def execute_skill" in script_file.read_text(encoding="utf-8")

        redline_balls = [b for b in initial_balls if b["ball_type"] == "REDLINE"]
        assert len(redline_balls) >= 1
        assert "柴油补贴底价" in redline_balls[0]["redline_keywords"]

        # 3. 验证新企业生成的账号均可正常登录，且上下级与头头标识完备
        accounts = deployed["accounts"]
        disp_acc = next(a for a in accounts if a["role_view"] == "employee")
        leader_acc = next(
            a
            for a in accounts
            if a["role_view"] == "leader" and a["is_custodian_leader"]
        )
        boss_acc = next(a for a in accounts if a["role_view"] == "boss")

        login_emp = client.post(
            "/api/v1/auth/login",
            json={"username": disp_acc["user_id"], "password": "123456"},
        )
        assert login_emp.status_code == 200
        emp_login_data = login_emp.json()
        assert emp_login_data["token"].startswith("arachne_tok_")
        assert emp_login_data["account"]["user_id"] == disp_acc["user_id"]
        assert emp_login_data["account"]["mounted_ball_count"] >= 3

        # 4. 验证一线调度员视角下的已挂载球（含 DATA / SKILL / AUTHORITY，物理不含 REDLINE 绝密底价球）
        emp_ov = client.get(
            f"/api/v1/state/overview?role_view=employee&user_id={disp_acc['user_id']}"
        )
        assert emp_ov.status_code == 200
        emp_ov_data = emp_ov.json()
        emp_accessible_types = {b["ball_type"] for b in emp_ov_data["accessible_balls"]}
        assert {"DATA", "SKILL", "AUTHORITY"}.issubset(emp_accessible_types)
        assert "REDLINE" not in emp_accessible_types
        assert len(emp_ov_data["chat_history"]) >= 1

        # 5. 验证董事长视角可见 REDLINE 绝密底价球与全量拓扑节点
        boss_ov = client.get(
            f"/api/v1/state/overview?role_view=boss&user_id={boss_acc['user_id']}"
        )
        assert boss_ov.status_code == 200
        boss_ov_data = boss_ov.json()
        assert any(b["ball_type"] == "REDLINE" for b in boss_ov_data["all_balls"])
        assert boss_ov_data["vault_health"]["intact"] is True

        # 6. 验证新企业头头与下属之间的球分管概览正常闭环
        custody_ov = client.get(
            f"/api/v1/custody/overview?user_id={leader_acc['user_id']}"
        )
        assert custody_ov.status_code == 200
        assert custody_ov.json()["is_custodian_leader"] is True


def test_policy_auto_decompose_ball_mitosis_and_autonomous_patrol(
    tmp_path: Path,
) -> None:
    """Decomposition, reviewed publication, and mitosis keep unvalidated skills unmounted."""
    sandbox_dir = tmp_path / "sandbox"
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'm8_mitosis.db').as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=sandbox_dir,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        # 先空投赞比亚铜矿车队
        tpl = client.get("/api/v1/genesis/templates").json()["templates"][0]
        deploy_data = client.post(
            "/api/v1/genesis/deploy-enterprise",
            json={
                "enterprise_name": tpl["enterprise_name"],
                "business_description": tpl["business_description"],
                "reset_existing": True,
            },
        ).json()

        disp_uid = next(
            a["user_id"]
            for a in deploy_data["accounts"]
            if a["role_view"] == "employee"
        )
        leader_uid = next(
            a["user_id"] for a in deploy_data["accounts"] if a["role_view"] == "leader"
        )

        # 1. 模式 A：传入杂糅制度文本，自动解剖拆球
        decomp_res = client.post(
            "/api/v1/genesis/decompose",
            json={
                "actor_user_id": disp_uid,
                "raw_policy_text": tpl["sample_policy_sop"],
            },
        )
        assert decomp_res.status_code == 200
        decomp_data = decomp_res.json()
        assert decomp_data["mode"] == "POLICY_DECOMPOSE"
        minted_types = {b["ball_type"] for b in decomp_data["minted_balls"]}
        assert {"DATA", "SKILL", "AUTHORITY", "REDLINE"}.issubset(minted_types)
        assert decomp_data["arena_report"]["ast_passed"] is True
        assert decomp_data["arena_report"]["promoted"] is False
        assert decomp_data["arena_report"]["candidate_status"] == "CANDIDATE"
        candidate_id = decomp_data["arena_report"]["minted_ball_id"]
        assert not any(
            candidate_id in s.ball_ids
            for s in app.state.runtime.containers.list_slots()
        )
        boss_uid = next(
            a["user_id"] for a in deploy_data["accounts"] if a["role_view"] == "boss"
        )
        review = client.post(
            f"/api/v1/evolution/candidates/{decomp_data['arena_report']['proposal_id']}/publish",
            json={
                "reviewer_id": boss_uid,
                "approved_source_hash": decomp_data["arena_report"]["source_hash"],
                "independent_samples": [
                    {
                        "input_payload": {"amount": a},
                        "expected_output": round(a * 0.085, 2),
                    }
                    for a in (10, 250, 5000)
                ],
            },
        )
        assert review.status_code == 200, review.text
        assert review.json()["status"] == "ACTIVE"
        assert review.json()["validation"]["passed"]
        assert decomp_data["worm_event"]["event_kind"] == "POLICY_DECOMPOSED_TO_BALLS"

        # 挑选一颗刚拆出的 DATA 球执行有丝分裂
        target_data_ball = next(
            b for b in decomp_data["minted_balls"] if b["ball_type"] == "DATA"
        )

        # 2. 模式 B：大球有丝分裂 (Ball Mitosis)
        mitosis_res = client.post(
            "/api/v1/genesis/decompose",
            json={
                "actor_user_id": leader_uid,
                "target_ball_id": target_data_ball["ball_id"],
            },
        )
        assert mitosis_res.status_code == 200
        mitosis_data = mitosis_res.json()
        assert mitosis_data["mode"] == "BALL_MITOSIS"
        assert mitosis_data["status"] == "PENDING_VALIDATION"
        assert mitosis_data["deprecated_ball"]["status"] == "ACTIVE"
        assert (
            mitosis_data["continuation"]["required_action"]
            == "PUBLISH_VALIDATED_CHILD_THEN_REVIEW_PARENT_REPLACEMENT"
        )
        assert len(mitosis_data["child_balls"]) == 2
        child_titles = [c["title"] for c in mitosis_data["child_balls"]]
        assert any("子球A·前端执行规程" in t for t in child_titles)
        assert any("子球B·后端风控与核算算子" in t for t in child_titles)
        assert {c["status"] for c in mitosis_data["child_balls"]} == {
            "ACTIVE",
            "CANDIDATE",
        }
        for child in mitosis_data["child_balls"]:
            if child["status"] == "CANDIDATE":
                assert not any(
                    child["ball_id"] in s.ball_ids
                    for s in app.state.runtime.containers.list_slots()
                )
        assert (
            mitosis_data["worm_event"]["event_kind"]
            == "BALL_MITOSIS_CANDIDATES_CREATED"
        )

        # 3. 集群自主能动巡检与工位自繁殖 (Slot Mitosis + Proactive Skill Forging)
        patrol_res = client.post(
            "/api/v1/genesis/autonomous-patrol",
            json={"actor_user_id": leader_uid},
        )
        assert patrol_res.status_code == 200
        patrol_data = patrol_res.json()
        assert patrol_data["patrol_status"] == "COMPLETED"

        # 验证工位细胞分裂出平行协防子工位 SLOT_xxx_REPLICA 与数字分身 SpiderNode
        replica_slot = patrol_data["slot_mitosis"]["replica_slot"]
        replica_node = patrol_data["slot_mitosis"]["replica_node"]
        assert replica_slot["slot_id"].endswith("_REPLICA")
        assert len(replica_slot["ball_ids"]) >= 1
        assert replica_node["slot_id"] == replica_slot["slot_id"]

        # 验证主动嗅探造球合成了新的 ACTIVE SKILL 球
        forged_skill = patrol_data["proactive_skill_forging"]["forged_skill_ball"]
        assert forged_skill is not None
        assert forged_skill["ball_type"] == "SKILL"
        assert forged_skill["status"] == "CANDIDATE"
        assert not any(
            forged_skill["ball_id"] in s.ball_ids
            for s in app.state.runtime.containers.list_slots()
        )
        assert patrol_data["continuation"]["required_action"] == "REVIEW_CANDIDATE"
        assert "100% 校验晋升 ACTIVE" not in patrol_data["brief_content"]
        assert forged_skill["executable_code_path"] is not None
        assert (sandbox_dir / forged_skill["executable_code_path"]).exists()

        # 验证部门头头企微对话流已收到《🤖 集群自主巡检进化简报》
        leader_ov = client.get(
            f"/api/v1/state/overview?role_view=leader&user_id={leader_uid}"
        ).json()
        assert any(
            "《🤖 集群自主巡检进化简报》" in msg["content"]
            for msg in leader_ov["chat_history"]
        )

        # 验证 WORM 账本链式哈希 100% 完好
        vault_verify = client.get("/api/v1/vault/verify").json()
        assert vault_verify["intact"] is True


def test_genesis_reset_preserves_strong_boss_credential_and_revokes_old_workspace(
    tmp_path: Path,
) -> None:
    settings = load_settings(
        llm_api_key="",
        enforce_bearer_auth=True,
        bootstrap_password="configured-strong-bootstrap",
        sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path}/strict.db",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=tmp_path / "sandbox",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        rt = app.state.runtime
        rt.auth_custody.set_password("boss_lin", "custom-owner-password")
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "boss_lin", "password": "custom-owner-password"},
        )
        assert login.status_code == 200
        old_headers = {"Authorization": f"Bearer {login.json()['token']}"}
        old_employee = client.post(
            "/api/v1/auth/login",
            json={"username": "emp_chen", "password": "configured-strong-bootstrap"},
        ).json()["token"]
        proposal = client.post(
            "/api/v1/evolution/propose",
            headers=old_headers,
            json={"proposer_id": "boss_lin", "natural_instruction": "按金额6%计提费用"},
        )
        assert proposal.status_code == 200
        assert rt.arena.list_reports()
        old_workspace = rt.cave_explorer.workspace_id
        template = client.get("/api/v1/genesis/templates", headers=old_headers).json()[
            "templates"
        ][0]
        deployed = client.post(
            "/api/v1/genesis/deploy-enterprise",
            headers=old_headers,
            json={
                "enterprise_name": template["enterprise_name"],
                "business_description": template["business_description"],
                "reset_existing": True,
            },
        )
        assert deployed.status_code == 200, deployed.text
        assert rt.cave_explorer.workspace_id != old_workspace
        assert rt.arena.list_reports() == []
        assert client.get("/api/v1/auth/me", headers=old_headers).status_code == 401
        assert (
            client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {old_employee}"}
            ).status_code
            == 401
        )
        boss_uid = next(
            a["user_id"]
            for a in deployed.json()["accounts"]
            if a["role_view"] == "boss"
        )
        assert boss_uid == "zam_boss_lin"
        new_login = client.post(
            "/api/v1/auth/login",
            json={"username": boss_uid, "password": "configured-strong-bootstrap"},
        )
        assert new_login.status_code == 200
        rt.auth_custody.set_password(boss_uid, "custom-new-owner-password")
        same_owner_login = client.post(
            "/api/v1/auth/login",
            json={"username": boss_uid, "password": "custom-new-owner-password"},
        )
        same_owner_headers = {
            "Authorization": f"Bearer {same_owner_login.json()['token']}"
        }
        redeployed = client.post(
            "/api/v1/genesis/deploy-enterprise",
            headers=same_owner_headers,
            json={
                "enterprise_name": template["enterprise_name"],
                "business_description": template["business_description"],
                "reset_existing": True,
            },
        )
        assert redeployed.status_code == 200, redeployed.text
        assert (
            client.get("/api/v1/auth/me", headers=same_owner_headers).status_code == 401
        )
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": boss_uid, "password": "custom-new-owner-password"},
            ).status_code
            == 200
        )
        for account in deployed.json()["accounts"]:
            assert (
                client.post(
                    "/api/v1/auth/login",
                    json={"username": account["user_id"], "password": "123456"},
                ).status_code
                == 401
            )
        employee = next(
            a for a in deployed.json()["accounts"] if a["role_view"] == "employee"
        )
        assert (
            client.post(
                "/api/v1/auth/login",
                json={
                    "username": employee["user_id"],
                    "password": "configured-strong-bootstrap",
                },
            ).status_code
            == 200
        )


def test_policy_without_explicit_rules_never_invents_active_permissions_or_formula(
    tmp_path: Path,
) -> None:
    app = create_app(
        load_settings(
            llm_api_key="",
            enforce_bearer_auth=False,
            sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path}/policy.db",
            vault_storage_dir=tmp_path / "vault",
            sandbox_workspace_dir=tmp_path / "sandbox",
        )
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/genesis/decompose",
            json={
                "actor_user_id": "emp_chen",
                "raw_policy_text": "业务部门每周整理资料并交流客户需求。",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["arena_report"] is None
        assert not any(b["ball_type"] == "SKILL" for b in data["minted_balls"])
        policies = [
            b
            for b in data["minted_balls"]
            if b["ball_type"] in ("AUTHORITY", "REDLINE")
        ]
        assert len(policies) == 2
        assert all(b["status"] == "CANDIDATE" for b in policies)
        assert not any(
            b["ball_id"] in s.ball_ids
            for b in policies
            for s in app.state.runtime.containers.list_slots()
        )
        assert data["continuation"]["required_action"] == "REVIEW_CANDIDATES"


def test_genesis_plain_description_cannot_activate_inferred_permissions_or_code(
    tmp_path: Path,
) -> None:
    app = create_app(
        load_settings(
            llm_api_key="",
            enforce_bearer_auth=False,
            sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path}/plain.db",
            vault_storage_dir=tmp_path / "vault",
            sandbox_workspace_dir=tmp_path / "sandbox",
        )
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/genesis/deploy-enterprise",
            json={
                "enterprise_name": "资料整理公司",
                "business_description": "资料整理公司，收集客户需求并整理客户提供的资料。",
                "reset_existing": True,
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        inferred = data["initial_balls"]
        assert inferred
        assert all(ball["status"] == "CANDIDATE" for ball in inferred)
        assert not any(
            ball["ball_id"] in slot.ball_ids
            for ball in inferred
            for slot in app.state.runtime.containers.list_slots()
        )
        assert data["continuation"]["required_action"] == "REVIEW_CANDIDATES"


def test_supplied_public_facts_never_copy_secret_clauses_to_employee_data(
    tmp_path: Path,
) -> None:
    app = create_app(
        load_settings(
            llm_api_key="",
            enforce_bearer_auth=False,
            sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path}/source.db",
            vault_storage_dir=tmp_path / "vault",
            sandbox_workspace_dir=tmp_path / "sandbox",
        )
    )
    public_clause = "公开产品A单价100元，现货5件"
    secret_clause = "【核心商业绝密】真实成本底价12元，严禁对外泄露"
    with TestClient(app) as client:
        deployed = client.post(
            "/api/v1/genesis/deploy-enterprise",
            json={
                "enterprise_name": "提供真实资料的公司",
                "business_description": public_clause + "；" + secret_clause,
                "reset_existing": True,
            },
        )
        assert deployed.status_code == 200, deployed.text
        data_balls = [
            ball
            for ball in deployed.json()["initial_balls"]
            if ball["ball_type"] == "DATA"
        ]
        assert data_balls
        assert all(
            ball["status"] == "ACTIVE" and ball["content"] == public_clause
            for ball in data_balls
        )
        employee = next(
            account
            for account in deployed.json()["accounts"]
            if account["role_view"] == "employee"
        )
        overview = client.get(
            f"/api/v1/state/overview?user_id={employee['user_id']}&role_view=employee"
        ).json()
        for ball in overview["accessible_balls"]:
            assert "12元" not in ball["content"]
            assert "真实成本底价" not in ball["content"]
        decomposed = client.post(
            "/api/v1/genesis/decompose",
            json={
                "actor_user_id": employee["user_id"],
                "raw_policy_text": public_clause + "；" + secret_clause,
            },
        )
        assert decomposed.status_code == 200
        extracted_data = next(
            ball
            for ball in decomposed.json()["minted_balls"]
            if ball["ball_type"] == "DATA"
        )
        assert extracted_data["content"] == public_clause
        secret_only = client.post(
            "/api/v1/genesis/decompose",
            json={
                "actor_user_id": employee["user_id"],
                "raw_policy_text": secret_clause,
            },
        ).json()
        withheld_data = next(
            ball for ball in secret_only["minted_balls"] if ball["ball_type"] == "DATA"
        )
        assert withheld_data["status"] == "CANDIDATE"
        assert (
            "12" not in withheld_data["content"] and "12" not in withheld_data["title"]
        )
        assert not any(
            withheld_data["ball_id"] in slot.ball_ids
            for slot in app.state.runtime.containers.list_slots()
        )

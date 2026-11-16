from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
from config import load_settings
from main import create_app


def test_account_login_and_ball_custody_workflow(tmp_path: Path) -> None:
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'm7_hot.db').as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=tmp_path / "sandbox",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        # 1. 获取 12 工位账号名录并验证个人登录
        acc_res = client.get("/api/v1/auth/accounts")
        assert acc_res.status_code == 200
        accounts = acc_res.json()["accounts"]
        assert len(accounts) >= 12

        login_res = client.post(
            "/api/v1/auth/login",
            json={"username": "emp_chen", "password": "123456"},
        )
        assert login_res.status_code == 200
        data = login_res.json()
        assert data["token"].startswith("arachne_tok_")
        assert data["account"]["user_id"] == "emp_chen"
        assert data["account"]["is_custodian_leader"] is False

        # 2. 员工小陈查看自己的球库视图，挑选一颗未挂载的球发起申请
        ov_res = client.get("/api/v1/custody/overview?user_id=emp_chen")
        assert ov_res.status_code == 200
        ov = ov_res.json()
        requestable = ov["requestable_balls"]
        assert len(requestable) > 0
        target_ball = requestable[0]

        req_res = client.post(
            "/api/v1/custody/requests",
            json={
                "requester_id": "emp_chen",
                "ball_id": target_ball["ball_id"],
                "grant_mode": "LEASE_TTL",
                "ttl_minutes": 120,
                "reason": "客户加急订单需要临时调用该权能球",
            },
        )
        assert req_res.status_code == 200
        req_item = req_res.json()["request"]
        req_id = req_item["request_id"]
        custodian_id = req_item["custodian_id"]
        assert req_item["status"] == "PENDING"

        # 3. 分管领导（头头）登录并查看待审批列表，一键批准给球
        leader_ov = client.get(
            f"/api/v1/custody/overview?user_id={custodian_id}"
        ).json()
        assert any(
            r["request_id"] == req_id
            for r in leader_ov["pending_subordinate_requests"]
        )

        dec_res = client.post(
            f"/api/v1/custody/requests/{req_id}/decide",
            json={
                "actor_user_id": custodian_id,
                "approve": True,
                "comment": "同意临时授权2小时",
            },
        )
        assert dec_res.status_code == 200
        assert dec_res.json()["request"]["status"] == "APPROVED"

        # 验证小陈的已挂载球列表中已出现该球
        ov_after = client.get("/api/v1/custody/overview?user_id=emp_chen").json()
        mounted_ids = [b["ball_id"] for b in ov_after["mounted_balls"]]
        assert target_ball["ball_id"] in mounted_ids

        # 4. 头头主动收回小陈的该颗球
        rev_res = client.post(
            "/api/v1/custody/revoke",
            json={
                "leader_user_id": custodian_id,
                "target_slot_id": "SLOT_FOLLOWUP_01",
                "ball_id": target_ball["ball_id"],
            },
        )
        assert rev_res.status_code == 200
        ov_revoked = client.get("/api/v1/custody/overview?user_id=emp_chen").json()
        assert target_ball["ball_id"] not in [
            b["ball_id"] for b in ov_revoked["mounted_balls"]
        ]


def test_permanent_request_reject_and_direct_lease_grant_closed_loop(
    tmp_path: Path,
) -> None:
    """验证员工申请 PERMANENT 常驻球、头头驳回申请（approve=False）、以及头头主动向下属派发 LEASE_TTL 临时球并成功挂载的完整闭环。"""
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'm7_loop.db').as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=tmp_path / "sandbox",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        ov = client.get("/api/v1/custody/overview?user_id=emp_chen").json()
        target_ball = ov["requestable_balls"][0]
        ball_id = target_ball["ball_id"]

        # 1. 员工小陈申请 PERMANENT 常驻挂载该球
        req_reject_res = client.post(
            "/api/v1/custody/requests",
            json={
                "requester_id": "emp_chen",
                "ball_id": ball_id,
                "grant_mode": "PERMANENT",
                "ttl_minutes": 120,
                "reason": "月底集中对账核算，申请常驻挂载该球",
            },
        )
        assert req_reject_res.status_code == 200
        req_reject_item = req_reject_res.json()["request"]
        assert req_reject_item["grant_mode"] == "PERMANENT"
        assert req_reject_item["status"] == "PENDING"
        custodian_id = req_reject_item["custodian_id"]

        # 2. 分管头头驳回该常驻球申请 (approve=False)
        reject_res = client.post(
            f"/api/v1/custody/requests/{req_reject_item['request_id']}/decide",
            json={
                "actor_user_id": custodian_id,
                "approve": False,
                "comment": "该高敏权能球暂不支持常驻下放，请改用临时授权",
            },
        )
        assert reject_res.status_code == 200
        decided_req = reject_res.json()["request"]
        assert decided_req["status"] == "REJECTED"
        assert "暂不支持常驻下放" in decided_req["decision_comment"]

        # 验证被驳回后，小陈已挂载球列表中不包含该球，但申请历史可见 REJECTED
        ov_after_reject = client.get(
            "/api/v1/custody/overview?user_id=emp_chen"
        ).json()
        assert ball_id not in [
            b["ball_id"] for b in ov_after_reject["mounted_balls"]
        ]
        assert any(
            r["request_id"] == req_reject_item["request_id"]
            and r["status"] == "REJECTED"
            for r in ov_after_reject["my_requests"]
        )

        # 3. 员工再次发起 PERMANENT 常驻申请并获批，验证常驻挂载生效
        req_perm_res = client.post(
            "/api/v1/custody/requests",
            json={
                "requester_id": "emp_chen",
                "ball_id": ball_id,
                "grant_mode": "PERMANENT",
                "ttl_minutes": 120,
                "reason": "跨岗临时顶班调用，补充资质后再次申请常驻",
            },
        )
        assert req_perm_res.status_code == 200
        perm_req_id = req_perm_res.json()["request"]["request_id"]

        approve_perm_res = client.post(
            f"/api/v1/custody/requests/{perm_req_id}/decide",
            json={
                "actor_user_id": custodian_id,
                "approve": True,
                "comment": "资质核验通过，批准常驻挂载",
            },
        )
        assert approve_perm_res.status_code == 200
        assert approve_perm_res.json()["request"]["status"] == "APPROVED"

        ov_after_perm = client.get(
            "/api/v1/custody/overview?user_id=emp_chen"
        ).json()
        perm_mounted = next(
            (b for b in ov_after_perm["mounted_balls"] if b["ball_id"] == ball_id),
            None,
        )
        assert perm_mounted is not None
        assert perm_mounted["is_borrowed"] is False

        # 先由分管头头收回该常驻球，以便后续测试主动派发 LEASE_TTL 临时球
        revoke_perm_res = client.post(
            "/api/v1/custody/revoke",
            json={
                "leader_user_id": custodian_id,
                "target_slot_id": "SLOT_FOLLOWUP_01",
                "ball_id": ball_id,
            },
        )
        assert revoke_perm_res.status_code == 200

        # 4. 头头主动向下属工位派发 LEASE_TTL 临时球并验证挂载为临时借用态
        grant_ttl_res = client.post(
            "/api/v1/custody/grant",
            json={
                "leader_user_id": custodian_id,
                "target_slot_id": "SLOT_FOLLOWUP_01",
                "ball_id": ball_id,
                "grant_mode": "LEASE_TTL",
                "ttl_minutes": 120,
            },
        )
        assert grant_ttl_res.status_code == 200
        grant_payload = grant_ttl_res.json()
        assert isinstance(grant_payload, dict)

        # 验证小陈视角下该球已挂载，且标识为 is_borrowed=True (TTL 临时借用中)
        ov_after_ttl = client.get(
            "/api/v1/custody/overview?user_id=emp_chen"
        ).json()
        ttl_mounted = next(
            (b for b in ov_after_ttl["mounted_balls"] if b["ball_id"] == ball_id),
            None,
        )
        assert ttl_mounted is not None
        assert ttl_mounted["is_borrowed"] is True

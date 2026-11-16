from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config import ArachneSettings
from core.snapshot_timemachine import SnapshotTimeMachine
from core.schemas import UnitSlot
from main import create_app


def settings_for(root: Path) -> ArachneSettings:
    return ArachneSettings(
        _env_file=None,
        llm_api_key="",
        enforce_bearer_auth=True,
        bootstrap_password="",
        sqlite_db_url=f"sqlite+aiosqlite:///{root / 'hot.db'}",
        vault_storage_dir=root / "vault",
        sandbox_workspace_dir=root / "sandbox",
    )


def login(client: TestClient, user_id: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"username": user_id, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def assert_cannot_login(client: TestClient, user_id: str, password: str) -> None:
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": user_id, "password": password}
        ).status_code
        == 401
    )


def handover_boss(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    response = client.post(
        "/api/v1/custody/handover",
        headers=headers,
        json={
            "target_slot_id": "SLOT_BOSS",
            "new_user_id": "current_admin",
            "new_person_name": "现任管理员",
            "handover_mode": "RESIGN_HANDOVER",
            "initial_password": "CurrentAdmin#2026",
        },
    )
    assert response.status_code == 200, response.text
    return login(client, "current_admin", "CurrentAdmin#2026")


@pytest.mark.parametrize("restore_mode", ["api", "sync"])
def test_restore_preserves_retirement_and_current_administrator(
    tmp_path: Path, restore_mode: str
) -> None:
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        rt = client.app.state.runtime
        rt.auth_custody.set_password("boss_lin", "FormerAdmin#2026")
        former_headers = login(client, "boss_lin", "FormerAdmin#2026")
        saved = client.post(
            "/api/v1/snapshots/save",
            headers=former_headers,
            json={"label": "管理员交接前"},
        )
        assert saved.status_code == 200, saved.text
        snapshot_id = saved.json()["snapshot_id"]
        current_headers = handover_boss(client, former_headers)
        assert rt.auth_custody.account_directory["boss_lin"]["_disabled"]

        if restore_mode == "api":
            response = client.post(
                "/api/v1/snapshots/restore",
                headers=current_headers,
                json={"snapshot_id": snapshot_id},
            )
            assert response.status_code == 200, response.text
        else:
            assert SnapshotTimeMachine(rt).restore_snapshot(snapshot_id)["restored"]

        assert rt.auth_custody.account_directory["boss_lin"]["_disabled"]
        assert_cannot_login(client, "boss_lin", "FormerAdmin#2026")
        assert_cannot_login(client, "boss_lin", "CurrentAdmin#2026")
        assert client.get("/api/v1/auth/me", headers=former_headers).status_code == 401
        assert client.get("/api/v1/auth/me", headers=current_headers).status_code == 401
        login(client, "current_admin", "CurrentAdmin#2026")
        current_profile = rt.containers.get_profile("current_admin")
        assert (
            rt.containers.get_slot(current_profile.slot_id).occupant_id
            == "current_admin"
        )
        assert current_profile.role_view == "boss"
        assert rt.containers.get_profile("boss_lin").slot_id != current_profile.slot_id

    with TestClient(create_app(settings)) as client:
        login(client, "current_admin", "CurrentAdmin#2026")
        assert_cannot_login(client, "boss_lin", "FormerAdmin#2026")
        assert client.app.state.runtime.auth_custody.account_directory["boss_lin"][
            "_disabled"
        ]


def test_retirement_survives_enterprise_reset_before_snapshot_restore(
    tmp_path: Path,
) -> None:
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        rt = client.app.state.runtime
        rt.auth_custody.set_password("boss_lin", "FormerAdmin#2026")
        old_headers = login(client, "boss_lin", "FormerAdmin#2026")
        saved = client.post(
            "/api/v1/snapshots/save", headers=old_headers, json={"label": "离职前"}
        )
        assert saved.status_code == 200, saved.text
        current_headers = handover_boss(client, old_headers)
        deployed = client.post(
            "/api/v1/genesis/deploy-enterprise",
            headers=current_headers,
            json={
                "enterprise_name": "赞比亚跨境铜矿陆运车队",
                "business_description": "按订单金额收取6%服务费，低于9折需主管审批；严禁超载发车。",
                "reset_existing": True,
            },
        )
        assert deployed.status_code == 200, deployed.text
        admin_id = next(
            a["user_id"]
            for a in deployed.json()["accounts"]
            if a["role_view"] == "boss"
        )
        assert "boss_lin" not in rt.auth_custody.account_directory
        current_headers = login(client, admin_id, "CurrentAdmin#2026")
        response = client.post(
            "/api/v1/snapshots/restore",
            headers=current_headers,
            json={"snapshot_id": saved.json()["snapshot_id"]},
        )
        assert response.status_code == 200, response.text
        assert rt.auth_custody.account_directory["boss_lin"]["_disabled"]
        login(client, admin_id, "CurrentAdmin#2026")
        assert_cannot_login(client, "boss_lin", "FormerAdmin#2026")
        assert_cannot_login(client, "boss_lin", "CurrentAdmin#2026")
    with TestClient(create_app(settings)) as client:
        login(client, admin_id, "CurrentAdmin#2026")
        assert_cannot_login(client, "boss_lin", "CurrentAdmin#2026")


def test_multiple_current_admins_keep_separate_credentials_after_restore(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(settings_for(tmp_path))) as client:
        rt = client.app.state.runtime
        rt.auth_custody.set_password("boss_lin", "FormerAdmin#2026")
        old_headers = login(client, "boss_lin", "FormerAdmin#2026")
        saved = client.post(
            "/api/v1/snapshots/save", headers=old_headers, json={"label": "单管理员"}
        )
        assert saved.status_code == 200, saved.text
        second = rt.containers.get_profile("boss_lin").model_copy(
            deep=True,
            update={
                "user_id": "other_admin",
                "name": "另一位管理员",
                "slot_id": "SLOT_OTHER_ADMIN",
            },
        )
        rt.containers.register_slot(
            UnitSlot(
                slot_id=second.slot_id,
                slot_name="第二管理席",
                department="管理",
                occupant_type="HUMAN",
                occupant_id=second.user_id,
                ball_ids=[],
            )
        )
        rt.containers.register_profile(second)
        rt.auth_custody.sync_accounts_from_containers()
        rt.auth_custody.set_password(second.user_id, "OtherAdmin#2026")
        other_headers = login(client, second.user_id, "OtherAdmin#2026")
        current_headers = handover_boss(client, old_headers)
        response = client.post(
            "/api/v1/snapshots/restore",
            headers=current_headers,
            json={"snapshot_id": saved.json()["snapshot_id"]},
        )
        assert response.status_code == 200, response.text
        login(client, "current_admin", "CurrentAdmin#2026")
        login(client, "other_admin", "OtherAdmin#2026")
        assert_cannot_login(client, "current_admin", "OtherAdmin#2026")
        assert_cannot_login(client, "other_admin", "CurrentAdmin#2026")
        assert client.get("/api/v1/auth/me", headers=other_headers).status_code == 401
        assert rt.containers.get_slot("SLOT_BOSS").occupant_id == "current_admin"
        assert rt.auth_custody.account_directory["boss_lin"]["_disabled"]


@pytest.mark.parametrize("holder_id", ["boss_lin", "leader_li"])
def test_snapshot_preserves_leave_contract_and_return_to_post(
    tmp_path: Path, holder_id: str
) -> None:
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        rt = client.app.state.runtime
        rt.auth_custody.set_password("boss_lin", "FormerAdmin#2026")
        rt.auth_custody.set_password(holder_id, "HolderPassword#2026")
        boss_password = (
            "HolderPassword#2026" if holder_id == "boss_lin" else "FormerAdmin#2026"
        )
        boss_headers = login(client, "boss_lin", boss_password)
        holder_headers = login(client, holder_id, "HolderPassword#2026")
        holder = rt.containers.get_profile(holder_id)
        post_id, original_role = holder.slot_id, holder.role_view
        saved = client.post(
            "/api/v1/snapshots/save", headers=boss_headers, json={"label": "休假前"}
        )
        assert saved.status_code == 200, saved.text
        delegated = client.post(
            "/api/v1/custody/handover",
            headers=boss_headers,
            json={
                "target_slot_id": post_id,
                "new_user_id": "acting_holder",
                "new_person_name": "代班人员",
                "handover_mode": "LEAVE_DELEGATION",
                "initial_password": "ActingHolder#2026",
            },
        )
        assert delegated.status_code == 200, delegated.text
        acting_headers = login(client, "acting_holder", "ActingHolder#2026")
        restore_headers = acting_headers if holder_id == "boss_lin" else boss_headers
        restored = client.post(
            "/api/v1/snapshots/restore",
            headers=restore_headers,
            json={"snapshot_id": saved.json()["snapshot_id"]},
        )
        assert restored.status_code == 200, restored.text
        assert client.get("/api/v1/auth/me", headers=holder_headers).status_code == 401
        login(client, holder_id, "HolderPassword#2026")
        login(client, "acting_holder", "ActingHolder#2026")
        assert rt.containers.get_profile(holder_id).role_view == "employee"
        assert not rt.auth_custody.account_directory[holder_id].get("_disabled")
        assert rt.containers.get_slot(post_id).occupant_id == "acting_holder"

    with TestClient(create_app(settings)) as client:
        rt = client.app.state.runtime
        authority = (
            login(client, "acting_holder", "ActingHolder#2026")
            if holder_id == "boss_lin"
            else login(client, "boss_lin", boss_password)
        )
        returned = client.post(
            "/api/v1/custody/handover",
            headers=authority,
            json={
                "target_slot_id": post_id,
                "new_user_id": holder_id,
                "new_person_name": "休假返岗人员",
                "handover_mode": "RESIGN_HANDOVER",
            },
        )
        assert returned.status_code == 200, returned.text
        login(client, holder_id, "HolderPassword#2026")
        assert rt.containers.get_profile(holder_id).role_view == original_role
        assert rt.containers.get_slot(post_id).occupant_id == holder_id
        assert_cannot_login(client, "acting_holder", "ActingHolder#2026")


@pytest.mark.parametrize("restore_mode", ["api", "sync"])
def test_restore_keeps_leave_delegate_subordinates_and_pending_approval(
    tmp_path: Path, restore_mode: str
) -> None:
    with TestClient(create_app(settings_for(tmp_path))) as client:
        rt = client.app.state.runtime
        for uid in ("boss_lin", "emp_chen"):
            rt.auth_custody.set_password(uid, "FixturePassword#2026")
        boss_headers = login(client, "boss_lin", "FixturePassword#2026")
        employee_headers = login(client, "emp_chen", "FixturePassword#2026")
        requested = client.post(
            "/api/v1/custody/requests",
            headers=employee_headers,
            json={
                "requester_id": "emp_chen",
                "ball_id": "BALL_AUTH_FOLLOWUP_QUOTE",
                "grant_mode": "PERMANENT",
            },
        )
        assert requested.status_code == 200, requested.text
        request_id = requested.json()["request"]["request_id"]
        saved = client.post(
            "/api/v1/snapshots/save",
            headers=boss_headers,
            json={"label": "待审批休假前"},
        )
        assert saved.status_code == 200, saved.text
        delegated = client.post(
            "/api/v1/custody/handover",
            headers=boss_headers,
            json={
                "target_slot_id": "SLOT_LEADER_01",
                "new_user_id": "acting_leader",
                "new_person_name": "代班组长",
                "handover_mode": "LEAVE_DELEGATION",
                "initial_password": "ActingLeader#2026",
            },
        )
        assert delegated.status_code == 200, delegated.text
        if restore_mode == "api":
            restored = client.post(
                "/api/v1/snapshots/restore",
                headers=boss_headers,
                json={"snapshot_id": saved.json()["snapshot_id"]},
            )
            assert restored.status_code == 200, restored.text
        else:
            assert SnapshotTimeMachine(rt).restore_snapshot(
                saved.json()["snapshot_id"]
            )["restored"]
        acting_headers = login(client, "acting_leader", "ActingLeader#2026")
        overview = client.get("/api/v1/custody/overview", headers=acting_headers).json()
        assert "emp_chen" in {p["user_id"] for p in overview["subordinates"]}
        pending = next(
            r
            for r in overview["pending_subordinate_requests"]
            if r["request_id"] == request_id
        )
        assert pending["custodian_id"] == "acting_leader"
        approved = client.post(
            f"/api/v1/custody/requests/{request_id}/decide",
            headers=acting_headers,
            json={"actor_user_id": "acting_leader", "approve": True},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["request"]["status"] == "APPROVED"

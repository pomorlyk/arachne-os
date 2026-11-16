from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config import ArachneSettings
from main import create_app


PASSWORD = "Original#2026"


def _settings(path: Path) -> ArachneSettings:
    return ArachneSettings(
        _env_file=None, llm_api_key="", enforce_bearer_auth=True,
        bootstrap_password="", sqlite_db_url=f"sqlite+aiosqlite:///{path / 'hot.db'}",
        vault_storage_dir=path / "vault", sandbox_workspace_dir=path / "sandbox",
    )


def _login(client: TestClient, uid: str, password: str = PASSWORD) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": uid, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _handover(client: TestClient, headers: dict, sid: str, uid: str, **extra):
    return client.post("/api/v1/custody/handover", headers=headers, json={
        "target_slot_id": sid, "new_user_id": uid, "new_person_name": uid,
        **extra,
    })


@pytest.mark.parametrize("mode", ["RESIGN_HANDOVER", "LEAVE_DELEGATION"])
def test_leader_handover_transfers_management_and_existing_approval(tmp_path: Path, mode: str):
    """Leaving links on the former holder strands both management and approval."""
    with TestClient(create_app(_settings(tmp_path))) as client:
        rt = client.app.state.runtime
        svc = rt.auth_custody
        for uid in ("boss_lin", "leader_li", "emp_chen"):
            svc.set_password(uid, PASSWORD)
        boss = _login(client, "boss_lin")
        former = _login(client, "leader_li")
        employee = _login(client, "emp_chen")
        svc.account_directory["leader_li"]["wecom_user_id"] = "external-former-leader"
        svc.account_directory["leader_li"]["_personal_flag"] = "former-only"
        sid = rt.containers.get_profile("leader_li").slot_id
        subordinate_sid = rt.containers.get_profile("emp_chen").slot_id
        request = client.post("/api/v1/custody/requests", headers=employee, json={
            "requester_id": "emp_chen", "ball_id": "BALL_AUTH_FOLLOWUP_QUOTE",
            "grant_mode": "PERMANENT",
        })
        assert request.status_code == 200, request.text
        request_id = request.json()["request"]["request_id"]
        assert request.json()["request"]["custodian_id"] == "leader_li"
        response = _handover(client, boss, sid, "successor", handover_mode=mode,
                             initial_password="Successor#2026")
        assert response.status_code == 200, response.text
        assert "wecom_user_id" not in svc.account_directory["successor"]
        assert "_personal_flag" not in svc.account_directory["successor"]
        assert svc.account_directory["leader_li"]["wecom_user_id"] == "external-former-leader"
        successor = _login(client, "successor", "Successor#2026")
        overview = client.get("/api/v1/custody/overview", headers=successor).json()
        assert "emp_chen" in {p["user_id"] for p in overview["subordinates"]}
        assert svc.account_directory["emp_chen"]["supervisor_id"] == "successor"
        pending = overview["pending_subordinate_requests"]
        assert [r["request_id"] for r in pending] == [request_id]
        assert pending[0]["custodian_id"] == "successor"
        assert svc.resolve_ball_custodian("BALL_AUTH_FOLLOWUP_QUOTE")[0] == "successor"
        denied = _handover(client, successor, rt.containers.get_profile("mgr_zhang").slot_id,
                           "unauthorized")
        assert denied.status_code == 403
        if mode == "RESIGN_HANDOVER":
            assert client.get("/api/v1/auth/me", headers=former).status_code == 401
        else:
            assert client.get("/api/v1/auth/me", headers=former).status_code == 200
            assert client.post(f"/api/v1/custody/requests/{request_id}/decide", headers=former,
                               json={"actor_user_id": "leader_li", "approve": True}).status_code == 403
        decision = client.post(f"/api/v1/custody/requests/{request_id}/decide", headers=successor,
                               json={"actor_user_id": "successor", "approve": True})
        assert decision.status_code == 200, decision.text
        assert client.post(f"/api/v1/custody/requests/{request_id}/decide", headers=successor,
                           json={"actor_user_id": "successor", "approve": True}).status_code == 400
        managed = _handover(client, successor, subordinate_sid, "new_employee")
        assert managed.status_code == 200, managed.text
        assert managed.json()["password_provisioned"] is False
        assert "Successor#2026" not in client.get("/api/v1/auth/accounts").text
        assert "Successor#2026" not in rt.vault.ledger_path.read_text()


@pytest.mark.parametrize("original_uid,role", [("leader_li", "leader"), ("emp_chen", "employee")])
def test_leave_return_survives_restart_preserves_identity_and_retires_delegate(
    tmp_path: Path, original_uid: str, role: str,
):
    """A real leave return reuses the original identity, never another slot's occupant."""
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        rt = client.app.state.runtime
        svc = rt.auth_custody
        for uid in ("boss_lin", original_uid):
            svc.set_password(uid, PASSWORD)
        boss = _login(client, "boss_lin")
        original = rt.containers.get_profile(original_uid)
        sid, title = original.slot_id, original.title
        original.employee_view.saved_hours = 71
        original.management_view.boundary_probes = 4
        svc.account_directory[original_uid]["custom_note"] = "retain me"
        svc.account_directory[original_uid]["wecom_user_id"] = "external-original-holder"
        lender_sid = rt.containers.get_profile("boss_lin").slot_id
        lease = rt.containers.borrow_ball(sid, lender_sid, "BALL_REDLINE_FACTORY_FLOOR_PRICE", ttl_seconds=7200)
        lease_payload = lease.model_dump()
        inherited = sorted(rt.containers.get_effective_ball_ids(sid))
        response = _handover(client, boss, sid, "relief", handover_mode="LEAVE_DELEGATION",
                             initial_password="Relief#2026")
        assert response.status_code == 200, response.text
        standby_sid = rt.containers.get_profile(original_uid).slot_id
    with TestClient(create_app(settings)) as client:
        rt = client.app.state.runtime
        boss = _login(client, "boss_lin")
        relief = _login(client, "relief", "Relief#2026")
        response = _handover(client, boss, sid, original_uid)
        assert response.status_code == 200, response.text
        returned = _login(client, original_uid)
        profile = rt.containers.get_profile(original_uid)
        assert profile.slot_id == sid and profile.role_view == role and profile.title == title
        assert profile.employee_view.saved_hours == 71
        assert profile.management_view.boundary_probes == 4
        assert rt.auth_custody.account_directory[original_uid]["custom_note"] == "retain me"
        assert rt.auth_custody.account_directory[original_uid]["wecom_user_id"] == "external-original-holder"
        assert standby_sid not in {s.slot_id for s in rt.containers.list_slots()}
        assert sorted(rt.containers.get_effective_ball_ids(sid)) == inherited
        assert [lease.model_dump() for lease in rt.containers.get_slot(sid).borrowed_balls] == [lease_payload]
        overview = client.get("/api/v1/custody/overview", headers=returned).json()
        if role == "leader":
            assert "emp_chen" in {p["user_id"] for p in overview["subordinates"]}
        assert client.get("/api/v1/auth/me", headers=relief).status_code == 401
        assert client.post("/api/v1/auth/login", json={"username": "relief", "password": "Relief#2026"}).status_code == 401
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/auth/me", headers=_login(client, original_uid)).json()["slot_id"] == sid
        assert client.post("/api/v1/auth/login", json={"username": "relief", "password": "Relief#2026"}).status_code == 401


@pytest.mark.parametrize("wrong_target", ["active_elsewhere", "retired", "other_leave_post"])
def test_return_rejects_existing_identity_without_matching_leave_provenance(tmp_path: Path, wrong_target: str):
    with TestClient(create_app(_settings(tmp_path))) as client:
        rt = client.app.state.runtime
        svc = rt.auth_custody
        svc.set_password("boss_lin", PASSWORD)
        boss = _login(client, "boss_lin")
        target_sid = rt.containers.get_profile("emp_chen").slot_id
        other = rt.containers.get_profile("emp_zhou")
        uid = other.user_id
        if wrong_target != "active_elsewhere":
            mode = "RESIGN_HANDOVER" if wrong_target == "retired" else "LEAVE_DELEGATION"
            response = _handover(client, boss, other.slot_id, "other_relief", handover_mode=mode)
            assert response.status_code == 200, response.text
        before_slots = [s.model_dump() for s in rt.containers.list_slots()]
        response = _handover(client, boss, target_sid, uid)
        assert response.status_code == 400, response.text
        assert [s.model_dump() for s in rt.containers.list_slots()] == before_slots
        if wrong_target == "retired":
            assert svc.account_directory[uid]["_disabled"] is True


@pytest.mark.parametrize("invalid_state", ["standby_has_assets", "holder_active_elsewhere"])
def test_leave_return_rejects_changed_standby_without_dropping_assets(tmp_path: Path, invalid_state: str):
    with TestClient(create_app(_settings(tmp_path))) as client:
        rt = client.app.state.runtime
        svc = rt.auth_custody
        svc.set_password("boss_lin", PASSWORD)
        boss = _login(client, "boss_lin")
        sid = rt.containers.get_profile("emp_chen").slot_id
        assert _handover(client, boss, sid, "relief", handover_mode="LEAVE_DELEGATION").status_code == 200
        holder = rt.containers.get_profile("emp_chen")
        standby = rt.containers.get_slot(holder.slot_id)
        if invalid_state == "standby_has_assets":
            rt.containers.attach_ball_to_slot(standby.slot_id, "BALL_AUTH_FOLLOWUP_QUOTE")
        else:
            holder.slot_id = rt.containers.get_profile("emp_zhou").slot_id
        response = _handover(client, boss, sid, "emp_chen")
        assert response.status_code == 400, response.text
        assert rt.containers.get_slot(sid).occupant_id == "relief"
        assert standby.slot_id in {s.slot_id for s in rt.containers.list_slots()}
        if invalid_state == "standby_has_assets":
            assert rt.containers.get_effective_ball_ids(standby.slot_id) == {"BALL_AUTH_FOLLOWUP_QUOTE"}

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config import ArachneSettings, load_settings
from core.auth_custody import AuthAndCustodyService
from main import create_app


@pytest.fixture
def strict_client(tmp_path: Path):
    settings = load_settings(llm_api_key="", enforce_bearer_auth=True,
        sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path / 'access.db'}",
        vault_storage_dir=tmp_path / "vault", sandbox_workspace_dir=tmp_path / "sandbox")
    with TestClient(create_app(settings)) as client:
        svc = client.app.state.runtime.auth_custody
        for account in svc.list_public_accounts():
            svc.set_password(account.user_id, "test-access-password")
        yield client


def _login(client, role):
    account = next(a for a in client.app.state.runtime.auth_custody.list_public_accounts() if a.role_view == role)
    res = client.post("/api/v1/auth/login", json={"username": account.user_id, "password": "test-access-password"})
    assert res.status_code == 200
    return account, {"Authorization": f"Bearer {res.json()['token']}"}


def test_secure_defaults_and_password_schema(strict_client):
    assert ArachneSettings(_env_file=None).enforce_bearer_auth is True
    assert strict_client.post("/api/v1/auth/login", json={"username": "emp_chen"}).status_code == 422
    assert strict_client.get("/api/v1/vault/verify").status_code == 401


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/api/v1/board/convene", {}), ("POST", "/api/v1/board/approve-transition", {}),
    ("POST", "/api/v1/exploration/empty-shell", {}), ("POST", "/api/v1/snapshots/restore", {}),
    ("POST", "/api/v1/simulation/step", {}), ("POST", "/api/v1/wargame/simulate", {}),
    ("GET", "/api/v1/missions/history", None), ("GET", "/api/v1/connectors/bindings", None),
])
def test_employee_cannot_call_management_without_identity_fields(strict_client, method, path, body):
    _, headers = _login(strict_client, "employee")
    assert strict_client.request(method, path, json=body, headers=headers).status_code == 403


def test_same_rank_finance_and_json_suffix_spoofing(strict_client):
    account, headers = _login(strict_client, "employee")
    assert strict_client.get("/api/v1/state/overview?role_view=finance_tool", headers=headers).status_code == 403
    assert strict_client.post("/api/v1/chat/message", headers={**headers, "Content-Type": "application/problem+json"},
        content=json.dumps({"sender_id": "boss_lin", "role_view": "employee", "content": "hello"})).status_code == 403
    assert strict_client.get("/api/v1/custody/overview?user_id=boss_lin", headers=headers).status_code == 403


def test_instance_directory_and_session_restore_are_isolated(strict_client):
    rt = strict_client.app.state.runtime
    svc = rt.auth_custody
    account, headers = _login(strict_client, "employee")
    isolated = AuthAndCustodyService(rt.vault, rt.particles, rt.containers)
    isolated.sync_accounts_from_containers()
    svc.account_directory[account.user_id]["_disabled"] = True
    assert not isolated.account_directory[account.user_id].get("_disabled")
    svc.account_directory[account.user_id].pop("_disabled")
    exported = svc.export_persistence_payload()
    svc.restore_from_persistence(exported["account_directory"], exported["passwords"], [], {headers['Authorization'].split()[1]: account.user_id})
    assert strict_client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert svc.login(account.user_id, "test-access-password")["token"]


def test_password_change_revokes_sessions_and_reset_preserves_password(strict_client):
    account, headers = _login(strict_client, "employee")
    svc = strict_client.app.state.runtime.auth_custody
    svc.change_password(account.user_id, "test-access-password", "changed-password")
    assert strict_client.get("/api/v1/auth/me", headers=headers).status_code == 401
    svc.reset_workspace_identity(preserve_password_user_ids={account.user_id})
    assert svc.login(account.user_id, "changed-password")["token"]


def test_boss_cannot_impersonate_actor(strict_client):
    _, headers = _login(strict_client, "boss")
    assert strict_client.post("/api/v1/custody/requests", headers=headers,
        json={"requester_id": "emp_chen", "ball_id": "anything"}).status_code == 403


def test_fresh_strict_accounts_have_no_shared_default_password(strict_client):
    rt = strict_client.app.state.runtime
    fresh = AuthAndCustodyService(rt.vault, rt.particles, rt.containers, settings=rt.settings)
    account = fresh.list_public_accounts()[0]
    with pytest.raises(ValueError, match="尚未配置密码"):
        fresh.login(account.user_id, "123456")
    fresh.restore_from_persistence({account.user_id: {}}, {account.user_id: "persisted-private-password"}, [])
    assert fresh.login(account.user_id, "persisted-private-password")["token"]


def test_lowercase_bearer_logout_revokes_session(strict_client):
    _, headers = _login(strict_client, "employee")
    headers["Authorization"] = headers["Authorization"].replace("Bearer ", "bearer ")
    assert strict_client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert strict_client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_employee_catalogue_does_not_include_unmounted_content(strict_client):
    account, headers = _login(strict_client, "employee")
    response = strict_client.get("/api/v1/custody/overview", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == account.user_id
    assert all("content" not in ball and "executable_code_path" not in ball for ball in data["requestable_balls"])
    assert all(ball["ball_type"] != "REDLINE" for ball in data["mounted_balls"])


def test_leader_cannot_take_over_boss_slot_or_approve_own_request(strict_client):
    rt = strict_client.app.state.runtime
    svc = rt.auth_custody
    leader, _ = _login(strict_client, "leader")
    boss = next(a for a in svc.list_public_accounts() if a.role_view == "boss")
    with pytest.raises(PermissionError):
        svc.handover_slot_occupant(leader.user_id, boss.slot_id, "attacker", "Attacker")
    ball = next(b for b in rt.particles.list_all_balls() if b.ball_type != "REDLINE")
    request = svc.submit_ball_request(leader.user_id, ball.ball_id)
    with pytest.raises(PermissionError, match="不得审批自己"):
        svc.decide_ball_request(leader.user_id, request.request_id, True)


def test_omitted_view_identity_uses_actual_session(strict_client):
    svc = strict_client.app.state.runtime.auth_custody
    accounts = [a for a in svc.list_public_accounts() if a.role_view == "employee"]
    account = accounts[-1]
    logged = strict_client.post("/api/v1/auth/login", json={"username": account.user_id, "password": "test-access-password"})
    headers = {"Authorization": f"Bearer {logged.json()['token']}"}
    overview = strict_client.get("/api/v1/state/overview", headers=headers)
    assert overview.status_code == 200
    assert overview.json()["current_user"]["user_id"] == account.user_id
    catalogue = strict_client.get("/api/v1/lifecycle/catalog", headers=headers)
    assert catalogue.status_code == 200


def test_manager_cannot_convene_board(strict_client):
    _, headers = _login(strict_client, "manager")
    assert strict_client.post("/api/v1/board/convene", json={}, headers=headers).status_code == 403


def test_disabled_accounts_do_not_receive_bootstrap_credentials(strict_client):
    rt = strict_client.app.state.runtime
    settings = rt.settings.model_copy(update={"bootstrap_password": "configured-bootstrap"})
    svc = AuthAndCustodyService(rt.vault, rt.particles, rt.containers, settings=settings)
    account = svc.list_public_accounts()[0]
    svc.restore_from_persistence({account.user_id: {"_disabled": True}}, {}, [])
    assert account.user_id not in svc._passwords
    with pytest.raises(ValueError, match="停用"):
        svc.login(account.user_id, "configured-bootstrap")


def test_explicit_demo_service_retains_demo_password(strict_client):
    rt = strict_client.app.state.runtime
    settings = rt.settings.model_copy(update={"enforce_bearer_auth": False})
    svc = AuthAndCustodyService(rt.vault, rt.particles, rt.containers, settings=settings)
    account = svc.list_public_accounts()[0]
    assert svc.login(account.user_id, "123456")["token"]


def test_password_provisioning_requires_authorized_manager(strict_client):
    employee, employee_headers = _login(strict_client, "employee")
    _, boss_headers = _login(strict_client, "boss")
    path = f"/api/v1/auth/accounts/{employee.user_id}/password"
    assert strict_client.post(path, headers=employee_headers, json={"new_password": "admin-set-password"}).status_code == 403
    svc = strict_client.app.state.runtime.auth_custody
    svc.account_directory[employee.user_id]["_disabled"] = True
    response = strict_client.post(path, headers=boss_headers, json={"new_password": "admin-set-password"})
    assert response.status_code == 200
    assert not svc.account_directory[employee.user_id].get("_disabled")
    login = strict_client.post("/api/v1/auth/login", json={"username": employee.user_id, "password": "admin-set-password"})
    assert login.status_code == 200
    assert strict_client.get("/api/v1/auth/me", headers=employee_headers).status_code == 401


def test_identity_metadata_restore_retains_revocations_and_disables_unknown(strict_client):
    rt = strict_client.app.state.runtime
    svc = rt.auth_custody
    employee, headers = _login(strict_client, "employee")
    svc.account_directory[employee.user_id]["_disabled"] = True
    restored = rt.containers.get_profile(employee.user_id).model_copy(update={"user_id": "unknown_restored_identity"})
    rt.containers.register_profile(restored)
    svc.restore_identity_metadata({employee.user_id: {"_disabled": False}, restored.user_id: {"_disabled": False}})
    svc.sync_accounts_from_containers()
    assert svc.account_directory[employee.user_id]["_disabled"] is True
    assert svc.account_directory[restored.user_id]["_disabled"] is True
    assert restored.user_id not in svc._passwords
    assert strict_client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_lifecycle_catalogue_hides_unmounted_content_and_source(strict_client):
    rt = strict_client.app.state.runtime
    account, headers = _login(strict_client, "employee")
    mounted = set(rt.containers.get_effective_ball_ids(account.slot_id))
    unmounted = next(ball for ball in rt.particles.list_all_balls() if ball.ball_type != "REDLINE" and ball.ball_id not in mounted)
    unmounted.content = "OTHER_SLOT_PRIVATE_SENTINEL_2026"
    unmounted.executable_code_path = "/private/other-slot-source.py"
    response = strict_client.get("/api/v1/lifecycle/catalog", headers=headers)
    assert response.status_code == 200
    assert "OTHER_SLOT_PRIVATE_SENTINEL_2026" not in response.text
    assert "/private/other-slot-source.py" not in response.text
    data = response.json()
    metadata = next(item for item in data["modules"] if item["ball_id"] == unmounted.ball_id)
    assert "content" not in metadata and "executable_code_path" not in metadata


def test_lifecycle_catalogue_redline_is_boss_only(strict_client):
    _, manager_headers = _login(strict_client, "manager")
    _, boss_headers = _login(strict_client, "boss")
    manager = strict_client.get("/api/v1/lifecycle/catalog", headers=manager_headers)
    boss = strict_client.get("/api/v1/lifecycle/catalog", headers=boss_headers)
    assert manager.status_code == boss.status_code == 200
    assert all(item["ball_type"] != "REDLINE" for item in manager.json()["modules"])
    assert any(item["ball_type"] == "REDLINE" for item in boss.json()["modules"])

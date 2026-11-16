from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config import ArachneSettings
from main import create_app
from swarm.genesis_fission import EnterpriseGenesisAndFissionEngine


ORIGINAL_PASSWORD = "OriginalFixture#2026"
CURRENT_PASSWORD = "CurrentFixture#2026"
OTHER_PASSWORD = "OtherAdminFixture#2026"


def _settings(tmp_path: Path, bootstrap_password: str = "") -> ArachneSettings:
    return ArachneSettings(
        _env_file=None,
        llm_api_key="",
        enforce_bearer_auth=True,
        bootstrap_password=bootstrap_password,
        sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path / 'hot.db'}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=tmp_path / "sandbox",
    )


def _login(client: TestClient, uid: str, password: str):
    return client.post(
        "/api/v1/auth/login", json={"username": uid, "password": password}
    )


def _headers(client: TestClient, uid: str, password: str) -> dict[str, str]:
    response = _login(client, uid, password)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _setup(client: TestClient):
    rt = client.app.state.runtime
    rt.auth_custody.set_password("boss_lin", ORIGINAL_PASSWORD)
    return rt, _headers(client, "boss_lin", ORIGINAL_PASSWORD)


def _handover(client: TestClient, headers: dict[str, str], mode: str):
    response = client.post(
        "/api/v1/custody/handover",
        headers=headers,
        json={
            "target_slot_id": "SLOT_BOSS",
            "new_user_id": "boss_successor",
            "new_person_name": "继任管理员",
            "handover_mode": mode,
            "initial_password": CURRENT_PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return _headers(client, "boss_successor", CURRENT_PASSWORD)


def _deploy(client: TestClient, headers: dict[str, str]):
    return client.post(
        "/api/v1/genesis/deploy-enterprise",
        headers=headers,
        json={
            "enterprise_name": "赞比亚跨境铜矿陆运车队",
            "business_description": "按订单金额收取6%服务费，低于9折需主管审批；严禁超载发车。",
            "reset_existing": True,
        },
    )


def _new_boss(response) -> str:
    assert response.status_code == 200, response.text
    assert all(pw not in response.text for pw in (
        ORIGINAL_PASSWORD, CURRENT_PASSWORD, OTHER_PASSWORD,
    ))
    assert all("default_password" not in a and "password" not in a for a in response.json()["accounts"])
    return next(a["user_id"] for a in response.json()["accounts"] if a["role_view"] == "boss")


def _add_live_boss(rt) -> None:
    original = rt.containers.get_profile("boss_lin")
    slot = rt.containers.get_slot(original.slot_id)
    rt.containers.register_slot(slot.model_copy(update={
        "slot_id": "SLOT_OTHER_BOSS", "occupant_id": "other_boss", "ball_ids": [],
    }, deep=True))
    rt.containers.register_profile(original.model_copy(update={
        "user_id": "other_boss", "slot_id": "SLOT_OTHER_BOSS", "name": "另一管理员",
    }, deep=True))
    rt.auth_custody.sync_accounts_from_containers()
    rt.auth_custody.set_password("other_boss", OTHER_PASSWORD)


def _force_blueprint_boss_id(monkeypatch, uid: str) -> None:
    build = EnterpriseGenesisAndFissionEngine._build_deterministic_blueprint

    def blueprint(self, *args, **kwargs):
        result = build(self, *args, **kwargs)
        boss = next(a for a in result.accounts_and_slots if a.role_view == "boss")
        old_uid = boss.user_id
        boss.user_id = uid
        for account in result.accounts_and_slots:
            if account.supervisor_id == old_uid:
                account.supervisor_id = uid
        return result

    monkeypatch.setattr(EnterpriseGenesisAndFissionEngine, "_build_deterministic_blueprint", blueprint)


@pytest.mark.parametrize("mode", ["RESIGN_HANDOVER", "LEAVE_DELEGATION"])
@pytest.mark.parametrize("actor", ["boss", "manager"])
def test_redeploy_continues_current_occupant_password_after_handover(
    tmp_path: Path, mode: str, actor: str,
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        rt, old_headers = _setup(client)
        current_headers = _handover(client, old_headers, mode)
        if actor == "manager":
            manager = next(p.user_id for p in rt.containers.list_profiles() if p.role_view == "manager")
            rt.auth_custody.set_password(manager, "ManagerFixture#2026")
            actor_headers = _headers(client, manager, "ManagerFixture#2026")
        else:
            actor_headers = current_headers
        uid = _new_boss(_deploy(client, actor_headers))
        assert _login(client, uid, CURRENT_PASSWORD).status_code == 200
        assert _login(client, uid, ORIGINAL_PASSWORD).status_code == 401
        assert _login(client, "boss_lin", ORIGINAL_PASSWORD).status_code == 401
        assert client.get("/api/v1/genesis/templates", headers=old_headers).status_code == 401
        assert client.get("/api/v1/genesis/templates", headers=current_headers).status_code == 401
        assert client.get("/api/v1/genesis/templates", headers=actor_headers).status_code == 401


def test_authenticated_boss_selects_own_password_among_live_administrators(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        rt, _ = _setup(client)
        _add_live_boss(rt)
        headers = _headers(client, "other_boss", OTHER_PASSWORD)
        uid = _new_boss(_deploy(client, headers))
        assert _login(client, uid, OTHER_PASSWORD).status_code == 200
        assert _login(client, uid, ORIGINAL_PASSWORD).status_code == 401


def test_manager_reset_rejects_ambiguous_live_administrator_passwords(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        rt, _ = _setup(client)
        _add_live_boss(rt)
        manager = next(p.user_id for p in rt.containers.list_profiles() if p.role_view == "manager")
        rt.auth_custody.set_password(manager, "ManagerFixture#2026")
        headers = _headers(client, manager, "ManagerFixture#2026")
        before = {p.user_id for p in rt.containers.list_profiles()}
        response = _deploy(client, headers)
        assert response.status_code == 400, response.text
        assert {p.user_id for p in rt.containers.list_profiles()} == before
        assert _login(client, "boss_lin", ORIGINAL_PASSWORD).status_code == 200
        assert _login(client, "other_boss", OTHER_PASSWORD).status_code == 200


def test_disabled_same_id_cannot_restore_retired_password(tmp_path: Path, monkeypatch) -> None:
    _force_blueprint_boss_id(monkeypatch, "boss_lin")
    with TestClient(create_app(_settings(tmp_path))) as client:
        _, old_headers = _setup(client)
        current_headers = _handover(client, old_headers, "RESIGN_HANDOVER")
        uid = _new_boss(_deploy(client, current_headers))
        assert uid == "boss_lin"
        assert _login(client, uid, CURRENT_PASSWORD).status_code == 200
        assert _login(client, uid, ORIGINAL_PASSWORD).status_code == 401


@pytest.mark.parametrize("same_id", [False, True])
def test_bootstrap_new_id_and_live_same_id_custom_password_policy(
    tmp_path: Path, monkeypatch, same_id: bool,
) -> None:
    if same_id:
        _force_blueprint_boss_id(monkeypatch, "boss_lin")
    with TestClient(create_app(_settings(tmp_path, "BootstrapFixture#2026"))) as client:
        _, headers = _setup(client)
        uid = _new_boss(_deploy(client, headers))
        accepted = ORIGINAL_PASSWORD if same_id else "BootstrapFixture#2026"
        rejected = "BootstrapFixture#2026" if same_id else ORIGINAL_PASSWORD
        assert _login(client, uid, accepted).status_code == 200
        assert _login(client, uid, rejected).status_code == 401

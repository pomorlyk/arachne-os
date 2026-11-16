"""Shared request authorization. Roles and acting identities come from the session."""
from __future__ import annotations

from typing import Any
from fastapi import HTTPException, Request


def get_authenticated_account(request: Request) -> Any | None:
    account = getattr(request.state, "authenticated_account", None)
    if account is not None:
        return account
    rt = request.app.state.runtime
    header = request.headers.get("authorization")
    if header:
        try:
            account = rt.auth_custody.resolve_bearer_token(header)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        request.state.authenticated_account = account
        return account
    if not rt.settings.enforce_bearer_auth:
        return None  # Explicit local demonstration mode only.
    raise HTTPException(status_code=401, detail="未提供有效的 Bearer 登录凭证")


def require_roles(request: Request, *roles: str) -> Any | None:
    account = get_authenticated_account(request)
    if account is not None and account.role_view not in roles:
        raise HTTPException(status_code=403, detail="当前登录账号无权执行此操作")
    return account


def require_self_or_roles(request: Request, user_id: str, *roles: str) -> Any | None:
    account = get_authenticated_account(request)
    if account is not None and user_id != account.user_id and account.role_view not in roles:
        raise HTTPException(status_code=403, detail="禁止访问其他账号的私有数据")
    return account


def authorize_view(account: Any, role_view: str) -> None:
    """Finance is a distinct capability; equal hierarchy rank grants no access."""
    actual = "finance_tool" if account.role_view == "blackbox" else account.role_view
    allowed = {actual, "employee"}
    if actual == "boss":
        allowed.update({"manager", "leader"})
    elif actual == "manager":
        allowed.add("leader")
    if role_view not in allowed:
        raise HTTPException(status_code=403, detail=f"当前登录账号无权访问 {role_view} 视图")


def authorize_operation(request: Request) -> None:
    """Deny management operations before parsing user-controlled payloads."""
    path = request.url.path.rstrip("/")
    if path.startswith("/api/v1/auth/accounts/") and path.endswith("/password"):
        require_roles(request, "manager", "boss")
    elif path.startswith("/api/v1/board/"):
        require_roles(request, "boss")
    elif path.startswith((
        "/api/v1/connectors/", "/api/v1/snapshots/", "/api/v1/simulation/",
        "/api/v1/wargame/", "/api/v1/genesis/", "/api/v1/exploration/",
        "/api/v1/crucible/", "/api/v1/missions/", "/api/v1/pipelines/",
        "/api/v1/swarm/",
    )) or path in {"/api/v1/llm/telemetry", "/api/v1/vault/rollback", "/api/v1/memory/crystals", "/api/v1/memory/candidate-balls"}:
        require_roles(request, "manager", "boss")
    elif path.startswith("/api/v1/lifecycle/") and path != "/api/v1/lifecycle/catalog":
        require_roles(request, "manager", "boss")
    elif path.startswith("/api/v1/ingest/") and request.method != "GET":
        require_roles(request, "manager", "boss")
    elif path.startswith("/api/v1/memory/") and request.method != "GET":
        require_roles(request, "leader", "manager", "boss")
    elif path in {"/api/v1/custody/grant", "/api/v1/custody/revoke", "/api/v1/custody/handover"} or (
        path.startswith("/api/v1/custody/requests/") and path.endswith("/decide")
    ):
        require_roles(request, "leader", "manager", "boss")

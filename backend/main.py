from __future__ import annotations

from contextlib import asynccontextmanager
import json
from urllib.parse import urlencode
from typing import AsyncIterator

from fastapi import FastAPI, Request, HTTPException
from core.security import get_authenticated_account, authorize_operation, authorize_view, require_self_or_roles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import ArachneSettings, load_settings
from surfaces.api_routes import create_arachne_runtime, router
from surfaces.auth_custody_routes import auth_custody_router
from surfaces.crucible_routes import crucible_router
from surfaces.dag_mission_routes import dag_mission_router
from surfaces.exploration_routes import exploration_router
from surfaces.connector_routes import connector_router, prepare_connector_callback
from surfaces.genesis_routes import genesis_router
from surfaces.ingest_snapshot_routes import ingest_snapshot_router
from surfaces.lifecycle_routes import lifecycle_router
from surfaces.memory_distiller_routes import memory_distiller_router
from surfaces.sim_telemetry_routes import sim_telemetry_router
from surfaces.skill_pipeline_routes import skill_pipeline_router
from surfaces.wargame_routes import wargame_router
from surfaces.wecom_gateway import WeComBotWSAdapter


_BEARER_EXEMPT_EXACT = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/auth/accounts",
        "/api/v1/system/health",
    }
)
_SPOOF_IDENTITY_FIELDS = (
    "actor_user_id",
    "sender_id",
    "requester_id",
    "leader_user_id",
    "proposer_id",
    "reviewer_user_id",
    "user_id",
    "initiator_account_id",
)


def create_app(custom_settings: ArachneSettings | None = None) -> FastAPI:
    settings = custom_settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = await create_arachne_runtime(settings)
        app.state.runtime = runtime
        try:
            if isinstance(runtime.wecom, WeComBotWSAdapter):
                await runtime.wecom.start_ws_bridge_if_configured()
            yield
        finally:
            if isinstance(runtime.wecom, WeComBotWSAdapter):
                await runtime.wecom.stop_ws_bridge()
            await runtime.close()

    app = FastAPI(
        title="Arachne-OS Multi-Agent Swarm Kernel",
        version="2.0.0",
        lifespan=lifespan,
    )

    async def prepare_authorized_request(request: Request) -> None:
        path = request.url.path
        if not path.startswith("/api/v1/") or request.method == "OPTIONS":
            return
        if path.startswith("/api/v1/connectors/callback/"):
            if request.method == "POST":
                # Authorize the canonical target before a trailing-slash
                # redirect; malformed callback paths must not open a journal.
                card_id = path.removeprefix("/api/v1/connectors/callback/").removesuffix("/")
                if not card_id or "/" in card_id:
                    raise HTTPException(status_code=404, detail="Not Found")
                await prepare_connector_callback(card_id, request)
            return
        if path in _BEARER_EXEMPT_EXACT:
            return
        account = get_authenticated_account(request)
        if account is None:
            return
        authorize_operation(request)
        for key, value in request.query_params.multi_items():
            if key == "role_view":
                authorize_view(account, value.strip())
            elif key == "user_id":
                # Personal endpoint identity must never fall through to an arbitrary user.
                require_self_or_roles(request, value.strip())
        if path in {"/api/v1/state/overview", "/api/v1/custody/overview", "/api/v1/lifecycle/catalog"}:
            query = dict(request.query_params)
            query["user_id"] = account.user_id
            if path == "/api/v1/state/overview" and "role_view" not in query:
                query["role_view"] = account.role_view
            request.scope["query_string"] = urlencode(query).encode()
            if hasattr(request, "_query_params"):
                del request._query_params
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            # JSON suffix types are valid JSON too. Read JSON independently of the
            # supplied media type so alternate encodings cannot bypass policy.
            raw_body = await request.body()
            if raw_body:
                try:
                    parsed = json.loads(raw_body)
                except (ValueError, UnicodeDecodeError):
                    parsed = None
                if isinstance(parsed, dict):
                    role = parsed.get("role_view")
                    if isinstance(role, str) and role.strip():
                        authorize_view(account, role.strip())
                    for name in _SPOOF_IDENTITY_FIELDS:
                        value = parsed.get(name)
                        if isinstance(value, str) and value.strip() and value.strip() != account.user_id:
                            raise HTTPException(status_code=403, detail=f"{name} 与当前登录身份不匹配")
                    # Fill route defaults with the actual actor. An omitted
                    # optional identity is never permission to pick a colleague.
                    default_actor_fields = {
                        "/api/v1/chat/message": "sender_id",
                        "/api/v1/evolution/propose": "proposer_id",
                        "/api/v1/missions/execute-dag": "initiator_account_id",
                        "/api/v1/custody/handover": "actor_user_id",
                    }
                    actor_field = default_actor_fields.get(path)
                    if path.startswith("/api/v1/lifecycle/"):
                        actor_field = "actor_user_id"
                    if path.startswith("/api/v1/memory/candidate-balls/") and path.endswith("/decide"):
                        actor_field = "reviewer_user_id"
                    if actor_field:
                        parsed[actor_field] = account.user_id
                    if "role_view" in parsed or path == "/api/v1/chat/message":
                        parsed["role_view"] = account.role_view
                    request._body = json.dumps(parsed).encode("utf-8")

    @app.middleware("http")
    async def bearer_auth_and_anti_spoof_guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        rt = getattr(app.state, "runtime", None)
        if rt is None:
            if request.url.path.startswith("/api/v1/") and request.url.path not in _BEARER_EXEMPT_EXACT:
                return JSONResponse(status_code=503, content={"detail": "服务尚未初始化"})
            return await call_next(request)
        path = request.url.path
        if path in {"/api/v1/auth/login", "/api/v1/auth/logout"}:
            try:
                if hasattr(rt, "_transactions"):
                    async with rt._transactions.lock:
                        await prepare_authorized_request(request)
                        return await call_next(request)
                await prepare_authorized_request(request)
                return await call_next(request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        if (request.method in ("POST", "PUT", "PATCH", "DELETE")
                and not path.startswith(("/api/v1/simulation/", "/api/v1/wargame/"))
                and hasattr(rt, "mutation_scope")):
            # Authorize only after obtaining the mutation lock, so reset/logout
            # cannot invalidate a credential between the check and its mutation.
            try:
                async with rt.mutation_scope(precheck=lambda: prepare_authorized_request(request)) as mutation:
                    response = await call_next(request)
                    if response.status_code >= 400:
                        mutation.rollback = True
                    return response
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        try:
            await prepare_authorized_request(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    @app.exception_handler(PermissionError)
    async def permission_error_handler(request: Request, exc: PermissionError):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(KeyError)
    async def key_error_handler(request: Request, exc: KeyError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(request: Request, exc: RuntimeError):
        if exc.__class__.__name__ != "WorkflowConflictError":
            raise exc
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(auth_custody_router)
    app.include_router(sim_telemetry_router)
    app.include_router(genesis_router)
    app.include_router(dag_mission_router)
    app.include_router(crucible_router)
    app.include_router(ingest_snapshot_router)
    app.include_router(wargame_router)
    app.include_router(memory_distiller_router)
    app.include_router(skill_pipeline_router)
    app.include_router(lifecycle_router)
    app.include_router(exploration_router)
    app.include_router(connector_router)
    return app


app = create_app()


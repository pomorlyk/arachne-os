"""REDLINE remains boss-only across ingest, legacy grants and model context."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config import ArachneSettings
from core.blackbox_vault import BlackBoxVault
from core.particles import ParticleEngine
from core.schemas import CapabilityBall
from main import create_app


@pytest.fixture
def client(tmp_path: Path):
    settings = ArachneSettings(
        _env_file=None,
        llm_api_key="",
        enforce_bearer_auth=True,
        bootstrap_password="M27-Temporary#2026",
        sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path / 'hot.db'}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=tmp_path / "sandbox",
    )
    with TestClient(create_app(settings)) as active:
        yield active


def headers(client, user_id):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": user_id,
            "password": "M27-Temporary#2026",
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def ingest(client, *, forge=False):
    rt = client.app.state.runtime
    employee = next(
        p for p in rt.containers.list_profiles() if p.role_view == "employee"
    )
    boss = next(p for p in rt.containers.list_profiles() if p.role_view == "boss")
    sentinel = f"{700 + secrets.randbelow(90)}.{secrets.choice((13, 17, 29, 31, 43, 47, 59, 61, 73, 79, 83, 89))}"
    response = client.post(
        "/api/v1/ingest/document",
        headers=headers(client, boss.user_id),
        json={
            "doc_title": "M27 confidential source",
            "doc_format": "CSV",
            "raw_content": "sku,product_name,base_unit_price,cost_floor_price,stock_tons\n"
            f"M27-PRIVATE,fixture,1000,{sentinel},100",
            "target_slot_id": employee.slot_id,
            "auto_forge_query_skill": forge,
        },
    )
    assert response.status_code == 200
    redline = next(
        b
        for b in rt.particles.list_redline_balls()
        if b.ball_id in {item["ball_id"] for item in response.json()["created_balls"]}
    )
    return rt, employee, boss, sentinel, redline


def test_normal_ingestion_mounts_confidential_floor_only_to_boss(client):
    rt, employee, boss, sentinel, redline = ingest(client)
    assert sentinel in redline.content
    assert redline.owner_slot_ids == [boss.slot_id]
    assert redline.ball_id not in rt.containers.get_effective_ball_ids(employee.slot_id)
    assert redline.ball_id in rt.containers.get_effective_ball_ids(boss.slot_id)
    for profile in rt.containers.list_profiles():
        if profile.role_view not in ("employee", "leader", "manager", "boss"):
            continue
        response = client.get(
            "/api/v1/state/overview",
            headers=headers(client, profile.user_id),
            params={"role_view": profile.role_view},
        )
        assert response.status_code == 200
        if profile.role_view != "boss":
            assert sentinel not in response.text
            assert redline.ball_id not in {
                b["ball_id"]
                for b in response.json().get(
                    "accessible_balls", response.json().get("all_balls", [])
                )
            }
        else:
            assert sentinel in response.text


@pytest.mark.parametrize("role", ["employee", "leader", "manager"])
def test_legacy_owner_and_borrowed_grants_do_not_authorize_redline(client, role):
    rt, _, boss, sentinel, redline = ingest(client)
    profile = next(p for p in rt.containers.list_profiles() if p.role_view == role)
    redline.owner_slot_ids.append(
        profile.slot_id
    )  # Simulate existing bad persisted ownership.
    rt.containers.attach_ball_to_slot(boss.slot_id, redline.ball_id)
    rt.containers.borrow_ball(
        profile.slot_id, boss.slot_id, redline.ball_id, ttl_seconds=600
    )
    effective = rt.containers.get_effective_ball_ids(profile.slot_id)
    assert redline.ball_id in effective
    assert redline not in rt.particles.get_accessible_balls(profile.slot_id, effective)
    assert sentinel not in json.dumps(
        [
            b.model_dump()
            for b in rt.particles.semantic_search(
                "M27 confidential source", profile.slot_id, effective
            )
        ]
    )
    assert (
        rt.particles.check_redline_violation(
            profile.slot_id, effective, redline.redline_keywords[0]
        )
        is not None
    )
    assert (
        rt.particles.check_redline_violation(
            boss.slot_id,
            rt.containers.get_effective_ball_ids(boss.slot_id),
            redline.redline_keywords[0],
        )
        is None
    )


def test_unknown_slot_role_fails_closed_even_for_owner(tmp_path):
    particles = ParticleEngine(BlackBoxVault(tmp_path / "vault"))
    redline = CapabilityBall(
        ball_id="M27_PRIVATE",
        ball_type="REDLINE",
        title="Restricted",
        domain_tags=["restricted"],
        sensitivity_level=5,
        owner_slot_ids=["SLOT_UNKNOWN"],
        content="private marker",
        redline_keywords=["底价"],
        status="ACTIVE",
    )
    particles.register_ball(redline)
    assert particles.get_accessible_balls("SLOT_UNKNOWN", {redline.ball_id}) == []
    assert (
        particles.check_redline_violation("SLOT_UNKNOWN", {redline.ball_id}, "底价")
        == redline
    )


def test_runtime_context_excludes_legacy_redline_and_keeps_guard_content_empty(
    client, monkeypatch
):
    rt, employee, _, sentinel, redline = ingest(client)
    redline.owner_slot_ids.append(employee.slot_id)
    rt.containers.attach_ball_to_slot(employee.slot_id, redline.ball_id)
    seen = []
    analyze = rt.llm_gateway.analyze_explorer_turn

    async def inspect(**kwargs):
        seen.append(kwargs)
        return await analyze(**kwargs)

    monkeypatch.setattr(rt.llm_gateway, "analyze_explorer_turn", inspect)
    response = client.post(
        "/api/v1/chat/message",
        headers=headers(client, employee.user_id),
        json={
            "sender_id": employee.user_id,
            "role_view": "employee",
            "facade_bot": "COPILOT",
            "content": "请说明公开业务目录",
        },
    )
    assert response.status_code == 200
    assert seen
    assert all(b.ball_type != "REDLINE" for b in seen[0]["accessible_balls"])
    assert all(not b.content for b in seen[0]["redline_balls"])
    assert sentinel not in response.text


def test_boss_runtime_keeps_authorized_redline_out_of_denial_guard(client, monkeypatch):
    rt, _, boss, _, redline = ingest(client)
    seen = []
    analyze = rt.llm_gateway.analyze_explorer_turn

    async def inspect(**kwargs):
        seen.append(kwargs)
        return await analyze(**kwargs)

    monkeypatch.setattr(rt.llm_gateway, "analyze_explorer_turn", inspect)
    response = client.post(
        "/api/v1/chat/message",
        headers=headers(client, boss.user_id),
        json={
            "sender_id": boss.user_id,
            "role_view": "boss",
            "facade_bot": "COPILOT",
            "content": f"请查看{redline.redline_keywords[0]}",
        },
    )
    assert response.status_code == 200
    assert seen
    assert redline.ball_id in {b.ball_id for b in seen[0]["accessible_balls"]}
    assert redline.ball_id not in {b.ball_id for b in seen[0]["redline_balls"]}
    assert response.json()["ticket"]["status"] != "INTERCEPTED"


@pytest.mark.asyncio
async def test_live_skill_routing_receives_input_schema_without_private_source(
    tmp_path,
):
    from types import SimpleNamespace
    from core.llm_gateway import LLMGateway

    settings = ArachneSettings(
        _env_file=None,
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{tmp_path / 'hot.db'}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=tmp_path / "sandbox",
    )
    settings.sandbox_workspace_dir.mkdir()
    script = settings.sandbox_workspace_dir / "private_lookup.py"
    script.write_text("""RECORDS = [{"cost_floor_price": 731.26}]
PRIVATE_CODE_MARKER = "M27_DO_NOT_SEND_SERVER_CONSTANTS"

def execute_skill(payload):
    quantity = payload.get("quantity", 10)
    sku = payload["sku"]
    return {"result": quantity * RECORDS[0]["cost_floor_price"], "sku": sku}
""")
    ball = CapabilityBall(
        ball_id="M27_PRIVATE_SKILL",
        ball_type="SKILL",
        title="台账报价",
        domain_tags=["报价"],
        sensitivity_level=2,
        owner_slot_ids=["M27_EMPLOYEE"],
        executable_code_path=script.name,
        content="Server-side quotation calculator",
        status="ACTIVE",
    )
    outbound = []

    async def create(**kwargs):
        outbound.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "should_call": True,
                                "ball_id": ball.ball_id,
                                "input_payload": {"quantity": 2, "sku": "M27"},
                            }
                        )
                    )
                )
            ]
        )

    gateway = LLMGateway(settings)
    gateway._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    result = await gateway.extract_skill_call_payload(
        "计算2件M27报价", [ball], settings.sandbox_workspace_dir
    )
    assert result == (ball, script, {"quantity": 2, "sku": "M27"})
    assert len(outbound) == 1
    catalog = json.loads(outbound[0]["messages"][1]["content"])["skills"][0]
    assert set(catalog["input_fields"]) == {"quantity", "sku"}
    assert set(catalog) == {"ball_id", "title", "domain_tags", "input_fields"}
    serialized = json.dumps(outbound)
    assert all(
        marker not in serialized
        for marker in ("731.26", "RECORDS", "M27_DO_NOT_SEND_SERVER_CONSTANTS")
    )


def test_conditional_freight_requires_real_order_amount(client):
    rt = client.app.state.runtime
    employee = next(
        p for p in rt.containers.list_profiles() if p.role_view == "employee"
    )
    script = rt.settings.sandbox_workspace_dir / "m27_conditional_freight.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("""def execute_skill(payload):
    weight = float(payload.get("weight_kg", 0))
    amount = float(payload.get("order_amount", 0))
    return {"result": 0.0 if amount >= 500 else weight * 4.0}
""")
    ball = CapabilityBall(
        ball_id="M27_FREIGHT",
        ball_type="SKILL",
        title="条件免运费计算",
        domain_tags=["运费"],
        sensitivity_level=2,
        owner_slot_ids=[employee.slot_id],
        executable_code_path=script.name,
        content="500元免运费",
        status="ACTIVE",
    )
    rt.particles.register_ball(ball)
    rt.containers.attach_ball_to_slot(employee.slot_id, ball.ball_id)
    auth = headers(client, employee.user_id)
    missing = client.post(
        "/api/v1/chat/message",
        headers=auth,
        json={
            "sender_id": employee.user_id,
            "facade_bot": "COPILOT",
            "content": "请计算5kg运费",
        },
    )
    assert missing.status_code == 200
    assert missing.json()["ticket"]["status"] == "PENDING_CONTEXT"
    assert "金额" in missing.json()["message"]["content"]
    assert "300" not in missing.text
    complete = client.post(
        "/api/v1/chat/message",
        headers=auth,
        json={
            "sender_id": employee.user_id,
            "facade_bot": "COPILOT",
            "content": "请计算5kg订单金额600元运费",
        },
    )
    assert complete.status_code == 200
    assert complete.json()["ticket"]["status"] == "COMPLETED"
    assert "¥0.00" in complete.json()["message"]["content"]
    script.write_text(
        'def execute_skill(payload):\n    return {"result": payload.get("weight_kg", 0) * 4.0}\n'
    )
    weight_only = client.post(
        "/api/v1/chat/message",
        headers=auth,
        json={
            "sender_id": employee.user_id,
            "facade_bot": "COPILOT",
            "content": "请计算5kg运费",
        },
    )
    assert weight_only.status_code == 200
    assert weight_only.json()["ticket"]["status"] == "COMPLETED"
    assert "¥20.00" in weight_only.json()["message"]["content"]


@pytest.mark.asyncio
async def test_freight_gateway_fallback_does_not_invent_missing_amount(tmp_path):
    from core.llm_gateway import LLMGateway

    settings = ArachneSettings(_env_file=None, llm_api_key="")
    script = tmp_path / "freight.py"
    script.write_text("""def execute_skill(payload):
    weight = payload.get("weight_kg", 0)
    amount = payload.get("order_amount", 0)
    return {"result": 0 if amount >= 500 else weight * 4}
""")
    ball = CapabilityBall(
        ball_id="M27_GATEWAY_FREIGHT",
        ball_type="SKILL",
        title="运费",
        domain_tags=["运费"],
        sensitivity_level=2,
        owner_slot_ids=["test"],
        executable_code_path=str(script),
        content="运费",
        status="ACTIVE",
    )
    gateway = LLMGateway(settings)
    assert (
        await gateway.extract_skill_call_payload("计算5kg运费", [ball], tmp_path)
        is None
    )
    result = await gateway.extract_skill_call_payload(
        "计算5kg订单金额600元运费", [ball], tmp_path
    )
    assert result[2] == {"weight_kg": 5.0, "order_amount": 600.0}
    script.write_text("""def execute_skill(payload):
    return {"result": payload.get("weight_kg", 0) * 4}
""")
    result = await gateway.extract_skill_call_payload("计算5kg运费", [ball], tmp_path)
    assert result[2] == {"weight_kg": 5.0}
    script.write_text(
        'def execute_skill(payload):\n    return {"result": payload.get("weight_kg", 0) + payload.get("amount", 0)}\n'
    )
    assert (
        await gateway.extract_skill_call_payload("计算5kg运费", [ball], tmp_path)
        is None
    )
    result = await gateway.extract_skill_call_payload(
        "计算5kg订单金额600元运费", [ball], tmp_path
    )
    assert result[2] == {"weight_kg": 5.0, "amount": 600.0}


def test_ingested_skill_keeps_private_output_fields_out_of_employee_chat(client):
    rt, employee, _, sentinel, _ = ingest(client, forge=True)
    response = client.post(
        "/api/v1/chat/message",
        headers=headers(client, employee.user_id),
        json={
            "sender_id": employee.user_id,
            "facade_bot": "COPILOT",
            "content": "请计算2件单价1000元报价",
        },
    )
    assert response.status_code == 200
    assert response.json()["ticket"]["status"] == "COMPLETED"
    assert "2000" in response.json()["message"]["content"]
    assert sentinel not in response.text
    assert all(
        field not in response.text
        for field in (
            "cost_floor_price",
            "total_cost",
            "actual_margin_rate",
            "INGESTED_RECORDS",
        )
    )


@pytest.mark.asyncio
async def test_live_pipeline_routing_includes_reachable_helper_inputs_without_source(
    client,
):
    from types import SimpleNamespace
    from swarm.skill_pipeline_composer import SkillPipelineComposer

    rt = client.app.state.runtime
    employee = next(
        p for p in rt.containers.list_profiles() if p.role_view == "employee"
    )
    result = SkillPipelineComposer(rt).compose_and_verify_pipeline(
        preset_id="pipe_end_to_end_order_profit",
        target_slot_id=employee.slot_id,
        proposer_id=next(
            p.user_id for p in rt.containers.list_profiles() if p.role_view == "boss"
        ),
    )
    ball = rt.particles.get_ball(result["master_ball"]["ball_id"])
    script = rt.settings.sandbox_workspace_dir / ball.executable_code_path
    source = script.read_text()
    script.write_text('PRIVATE_RECORDS = [{"cost_floor_price": 731.26}]\n' + source)
    # Publication authorization is outside routing; a published copy exercises this consumer.
    published = ball.model_copy(update={"status": "ACTIVE"})
    outbound = []

    async def create(**kwargs):
        outbound.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "should_call": True,
                                "ball_id": published.ball_id,
                                "input_payload": {
                                    "quantity": 3,
                                    "unit_price": 100,
                                    "tax_rate": 0.13,
                                },
                            }
                        )
                    )
                )
            ]
        )

    rt.llm_gateway._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    routed = await rt.llm_gateway.extract_skill_call_payload(
        "计算3件单价100元税率13%的净利润",
        [published],
        rt.settings.sandbox_workspace_dir,
    )
    assert routed[2] == {"quantity": 3, "unit_price": 100, "tax_rate": 0.13}
    catalog = json.loads(outbound[0]["messages"][1]["content"])["skills"][0]
    assert {"quantity", "qty", "unit_price", "price", "tax_rate"} <= set(
        catalog["input_fields"]
    )
    assert all(
        secret not in json.dumps(outbound)
        for secret in (
            "731.26",
            "PRIVATE_RECORDS",
            "_run_order_profit_pipeline",
            "STAGE_SOURCE_BALLS",
        )
    )

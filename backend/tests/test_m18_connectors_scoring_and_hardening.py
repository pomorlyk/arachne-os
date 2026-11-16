from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from config import ArachneSettings
from core.external_connectors import compute_arachne_hmac_signature
from core.schemas import UnitSlot
from main import create_app


def _make_settings(
    tmp_path: Path, db_name: str, **extra: Any
) -> ArachneSettings:
    db_file = (tmp_path / db_name).resolve().as_posix()
    extra.setdefault("enforce_bearer_auth", False)
    extra.setdefault("bootstrap_password", "123456")
    extra.setdefault("connector_hmac_secret", "fixture-signing-key")
    return ArachneSettings(
        llm_api_key="",
        sqlite_db_url=f"sqlite+aiosqlite:///{db_file}",
        vault_storage_dir=tmp_path / "vault_storage",
        sandbox_workspace_dir=tmp_path / "sandbox_workspace",
        **extra,
    )


def _bootstrap_enterprise(
    client: TestClient, enterprise_name: str, industry: str
) -> None:
    empty_res = client.post(
        "/api/v1/exploration/empty-shell",
        json={"enterprise_name": enterprise_name, "industry": industry},
    )
    assert empty_res.status_code == 200

    scout_res = client.post(
        "/api/v1/exploration/scout",
        json={
            "enterprise_name": enterprise_name,
            "industry": industry,
            "raw_org_material": (
                f"{enterprise_name}（{industry}）：\n"
                "1. 市场拓展与客户交付部：负责大客户方案报价与合同履约追踪；\n"
                "2. 风控与运营审校组：负责折扣超限特批与异常风险稽核；\n"
                "3. 财税合规与开票黑盒中心：负责增值税专票税控盘开具与核销；\n"
                "4. 质检合规管理部：负责质量检测、SOP审计与红线把关。"
            ),
        },
    )
    assert scout_res.status_code == 200
    scouted = client.get("/api/v1/exploration/map").json()["nodes"]
    for node in scouted:
        if node.get("exploration_state") == "SCOUTED":
            torch_res = client.post(
                "/api/v1/exploration/plant-torch",
                json={"target_node_id": node["node_id"]},
            )
            assert torch_res.status_code == 200


def test_external_connector_hmac_callback_and_idempotency(
    tmp_path: Path,
) -> None:
    app = create_app(_make_settings(tmp_path, "m18_connectors.db"))
    outbound_requests: list[dict[str, Any]] = []

    async def _mock_handler(request: httpx.Request) -> httpx.Response:
        outbound_requests.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "body": request.content,
            }
        )
        return httpx.Response(200, json={"accepted": True})

    with TestClient(app) as client:
        _bootstrap_enterprise(
            client,
            enterprise_name="联影医疗精密影像系统有限公司",
            industry="高端医学影像设备制造与维保交付",
        )
        rt = app.state.runtime
        assert rt.connectors is not None
        rt.connectors.set_http_transport(httpx.MockTransport(_mock_handler))

        ov_boss = client.get(
            "/api/v1/state/overview?role_view=boss&user_id=boss_root"
        ).json()
        profiles = ov_boss["all_profiles"]
        emp_prof = next(p for p in profiles if p["role_view"] == "employee")
        leader_prof = next(p for p in profiles if p["role_view"] == "leader")
        fin_prof = next(
            (p for p in profiles if p["role_view"] == "finance_tool"), None
        )
        fin_slot_id = fin_prof["slot_id"] if fin_prof else leader_prof["slot_id"]

        # 1. 为审批组长与财税黑盒绑定 HTTP_WEBHOOK 外部连接器
        for sid in dict.fromkeys([leader_prof["slot_id"], fin_slot_id]):
            bind_res = client.post(
                "/api/v1/connectors/bindings",
                json={
                    "slot_id": sid,
                    "connector_type": "HTTP_WEBHOOK",
                    "endpoint_url": "https://erp.medical.local/webhook/arachne",
                    "enabled": True,
                },
            )
            assert bind_res.status_code == 200
            assert bind_res.json()["binding"]["connector_type"] == "HTTP_WEBHOOK"

        list_res = client.get("/api/v1/connectors/bindings")
        assert list_res.status_code == 200
        assert len(list_res.json()["bindings"]) >= 1

        # 2. 一线员工发起高压线折扣特批，自动生成审批卡并附带 HMAC-SHA256 出站签名请求
        chat_res = client.post(
            "/api/v1/chat/message",
            json={
                "sender_id": emp_prof["user_id"],
                "facade_bot": "COPILOT",
                "chat_type": "SINGLE",
                "content": "联影核心医院急单：订单金额12000元，对方要求按4折特批成交，请转审批。",
            },
        )
        assert chat_res.status_code == 200
        spawned_card = chat_res.json()["spawned_card"]
        assert spawned_card is not None
        card_id = spawned_card["card_id"]
        assert len(outbound_requests) == 1

        out_req = outbound_requests[0]
        hdrs = {k.lower(): v for k, v in out_req["headers"].items()}
        assert "x-arachne-timestamp" in hdrs
        assert "x-arachne-signature" in hdrs
        assert "x-arachne-idempotency-key" in hdrs
        expected_out_sig = compute_arachne_hmac_signature(
            rt.settings.connector_hmac_secret,
            hdrs["x-arachne-timestamp"],
            out_req["body"],
        )
        assert hdrs["x-arachne-signature"] == expected_out_sig

        # 3. 缺签名 -> 401；伪造篡改签名 -> 403
        no_sig_res = client.post(
            f"/api/v1/connectors/callback/{card_id}",
            json={
                "decision": "APPROVE",
                "approved_amount": 4800.0,
                "comment": "特批",
            },
        )
        assert no_sig_res.status_code == 401

        bad_sig_res = client.post(
            f"/api/v1/connectors/callback/{card_id}",
            content=b'{"decision":"APPROVE","approved_amount":4800,"comment":"fake"}',
            headers={
                "Content-Type": "application/json",
                "X-Arachne-Timestamp": str(int(time.time())),
                "X-Arachne-Signature": "sha256=" + "0" * 64,
            },
        )
        assert bad_sig_res.status_code == 403

        # 4. 合法 HMAC 签名回调完成组长审批并自动流转出财务开票下一卡
        leader_cb_body = json.dumps(
            {
                "idempotency_key": f"ERP_DEC_{card_id}",
                "card_id": card_id,
                "ticket_id": spawned_card["ticket_id"],
                "actor_user_id": leader_prof["user_id"],
                "submitted_output": {
                    "decision": "APPROVE",
                    "approved_amount": spawned_card["minimized_payload"].get(
                        "requested_amount", 4800.0
                    ),
                    "comment": "ERP外部协同审批通过",
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        ts1 = str(int(time.time()))
        sig1 = compute_arachne_hmac_signature(
            rt.settings.connector_hmac_secret, ts1, leader_cb_body
        )
        cb_res1 = client.post(
            f"/api/v1/connectors/callback/{card_id}",
            content=leader_cb_body,
            headers={
                "Content-Type": "application/json",
                "X-Arachne-Timestamp": ts1,
                "X-Arachne-Signature": sig1,
            },
        )
        assert cb_res1.status_code == 200
        cb_data1 = cb_res1.json()
        assert cb_data1["accepted"] is True
        assert cb_data1["idempotent_replay"] is False
        assert cb_data1["card"]["status"] == "APPROVED"
        next_card = cb_data1["next_card"]
        assert next_card is not None
        assert len(outbound_requests) == 2

        # 5. 金税黑盒签名回调完结整笔工单 + 验证重放幂等性
        fin_card_id = next_card["card_id"]
        billed_amt = next_card["minimized_payload"]["amount"]
        fin_body = json.dumps(
            {
                "idempotency_key": f"TAX_DONE_{fin_card_id}",
                "card_id": fin_card_id,
                "ticket_id": next_card["ticket_id"],
                "submitted_output": {
                    "invoice_number": "24312000000188991234",
                    "billed_amount": billed_amt,
                    "attachment_ref": "https://tax.local/inv_24312000000188991234.pdf",
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        ts2 = str(int(time.time()))
        sig2 = compute_arachne_hmac_signature(
            rt.settings.connector_hmac_secret, ts2, fin_body
        )
        cb_res2 = client.post(
            f"/api/v1/connectors/callback/{fin_card_id}",
            content=fin_body,
            headers={
                "Content-Type": "application/json",
                "X-Arachne-Timestamp": ts2,
                "X-Arachne-Signature": sig2,
            },
        )
        assert cb_res2.status_code == 200
        assert cb_res2.json()["ticket"]["status"] == "COMPLETED"
        assert cb_res2.json()["idempotent_replay"] is False

        replay_res = client.post(
            f"/api/v1/connectors/callback/{fin_card_id}",
            content=fin_body,
            headers={
                "Content-Type": "application/json",
                "X-Arachne-Timestamp": ts2,
                "X-Arachne-Signature": sig2,
            },
        )
        assert replay_res.status_code == 200
        assert replay_res.json()["idempotent_replay"] is True

        vault_res = client.get("/api/v1/vault/verify").json()
        assert vault_res["intact"] is True


def test_3d_replaceability_difflib_soft_ceiling_and_cave_distillation(
    tmp_path: Path,
) -> None:
    app = create_app(_make_settings(tmp_path, "m18_scoring_distill.db"))
    with TestClient(app) as client:
        _bootstrap_enterprise(
            client,
            enterprise_name="康龙化成生物医药研发服务有限公司",
            industry="CRO医药研发测试与客户交付",
        )
        rt = app.state.runtime
        ov_boss = client.get(
            "/api/v1/state/overview?role_view=boss&user_id=boss_root"
        ).json()
        emp_prof = next(
            p for p in ov_boss["all_profiles"] if p["role_view"] == "employee"
        )
        emp_uid = emp_prof["user_id"]
        emp_sid = emp_prof["slot_id"]
        assert emp_sid.startswith("SLOT_CAVE_")

        # 1. difflib 影子采纳率 + 三维可替代分分解
        score_res = asyncio.run(
            rt.scoring.on_shadow_trial_completed(
                user_id=emp_uid,
                slot_id=emp_sid,
                ai_matched_human=True,
                ai_draft_text="研发检测排期已确认，含税总额18000元，周期7个工作日。",
                human_final_text="研发检测排期已确认，含税总额18000元，周期7个工作日，附GLP报告。",
            )
        )
        assert score_res["similarity_ratio"] is not None
        assert score_res["similarity_ratio"] > 0.75
        bd = score_res["replaceability_breakdown"]
        for key in (
            "skill_coverage",
            "shadow_adoption_rate",
            "exception_discipline_factor",
            "soft_skill_ceiling",
            "soft_skill_capped",
        ):
            assert key in bd

        # 验证 RBAC 零泄密：employee 视角绝不暴露 replaceability 字段
        emp_raw = client.get(
            f"/api/v1/state/overview?role_view=employee&user_id={emp_uid}"
        ).text
        assert '"replaceability_score"' not in emp_raw
        assert '"replaceability_breakdown"' not in emp_raw

        # 2. 高主观客诉安抚岗位强制人工兜底上限保护 (<= 72.0%)
        rt.containers.register_slot(
            UnitSlot(
                slot_id="SLOT_SOFT_APPEASE",
                slot_name="重大客诉危机安抚与商务谈判专岗",
                department="客户公关部",
                occupant_id="human_appease_01",
            )
        )
        capped_score = rt.containers.update_slot_replaceability(
            "SLOT_SOFT_APPEASE", 98.0, 99.0
        )
        assert capped_score <= 72.0
        soft_slot = rt.containers.get_slot("SLOT_SOFT_APPEASE")
        assert soft_slot.replaceability_breakdown["soft_skill_capped"] is True

        # 3. SLOT_CAVE_* 长记忆蒸馏产出 CANDIDATE DATA 球并经领导审批激活挂载
        before_slot_balls = set(rt.containers.get_slot(emp_sid).ball_ids)
        distill_res = client.post(
            "/api/v1/memory/distill",
            json={
                "slot_id": emp_sid,
                "auto_upgrade_balls": True,
                "mint_candidate_ball": True,
            },
        )
        assert distill_res.status_code == 200
        cand_list = distill_res.json().get("candidate_balls", [])
        assert len(cand_list) == 1
        cand_id = cand_list[0]["ball_id"]
        assert cand_list[0]["ball_type"] == "DATA"
        assert cand_list[0]["status"] == "CANDIDATE"
        assert cand_id not in before_slot_balls

        pending_res = client.get(f"/api/v1/memory/candidate-balls?slot_id={emp_sid}")
        assert pending_res.status_code == 200
        assert pending_res.json()["pending_count"] >= 1

        # employee 试图自审挂载应返回 403
        deny_res = client.post(
            f"/api/v1/memory/candidate-balls/{cand_id}/decide",
            json={"approve": True, "role_view": "employee"},
        )
        assert deny_res.status_code == 403

        # 领导审核批准后晋升 ACTIVE 并自动挂载至该岗位容器
        approve_res = client.post(
            f"/api/v1/memory/candidate-balls/{cand_id}/decide",
            json={
                "approve": True,
                "role_view": "leader",
                "reviewer_user_id": "boss_root",
                "comment": "确认沉淀为部门正式 SOP 知识球",
            },
        )
        assert approve_res.status_code == 200
        assert approve_res.json()["ball"]["status"] == "ACTIVE"
        assert cand_id in approve_res.json()["slot_ball_ids"]


def test_sandbox_resource_bombs_and_system_health(tmp_path: Path) -> None:
    settings = _make_settings(
        tmp_path,
        "m18_sandbox_health.db",
        sandbox_timeout_seconds=1.2,
        sandbox_max_memory_mb=64,
        sandbox_max_output_bytes=4096,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        _bootstrap_enterprise(
            client,
            enterprise_name="汇川工业自动化技术有限公司",
            industry="伺服驱动器研发与智能制造",
        )
        rt = app.state.runtime
        ov_boss = client.get(
            "/api/v1/state/overview?role_view=boss&user_id=boss_root"
        ).json()
        proposer_id = next(
            p["user_id"]
            for p in ov_boss["all_profiles"]
            if p["role_view"] == "employee"
        )

        # 1. 死循环炸弹（必须在 timeout 内 killpg 熔断，绝不影响主进程）
        loop_report = asyncio.run(
            rt.arena.propose_and_evaluate(
                proposer_id=proposer_id,
                natural_instruction="金额的6%服务费（死循环安全测试）",
                override_code_for_security_test=(
                    "def execute_skill(payload):\n"
                    "    while True:\n"
                    "        pass\n"
                ),
            )
        )
        assert loop_report.promoted is False
        assert loop_report.ast_passed is True
        assert any("SANDBOX_RUNTIME_BLOCKED" in v for v in loop_report.ast_violations)

        # 2. 无限递归爆栈
        rec_report = asyncio.run(
            rt.arena.propose_and_evaluate(
                proposer_id=proposer_id,
                natural_instruction="金额的6%服务费（递归爆栈测试）",
                override_code_for_security_test=(
                    "def execute_skill(payload):\n"
                    "    return execute_skill(payload)\n"
                ),
            )
        )
        assert rec_report.promoted is False
        assert rec_report.success_rate == 0.0
        assert any("RecursionError" in r.error_detail for r in rec_report.sample_results)

        # 3. 超大标准输出泛洪
        flood_report = asyncio.run(
            rt.arena.propose_and_evaluate(
                proposer_id=proposer_id,
                natural_instruction="金额的6%服务费（输出泛洪测试）",
                override_code_for_security_test=(
                    "def execute_skill(payload):\n"
                    "    return {'result': 'A' * 20000}\n"
                ),
            )
        )
        assert flood_report.promoted is False
        assert any("max_output_bytes" in v for v in flood_report.ast_violations)

        # 4. 内存炸弹（> 64MB）
        mem_report = asyncio.run(
            rt.arena.propose_and_evaluate(
                proposer_id=proposer_id,
                natural_instruction="金额的6%服务费（内存分配炸弹测试）",
                override_code_for_security_test=(
                    "def execute_skill(payload):\n"
                    "    junk = [1] * 20000000\n"
                    "    return {'result': len(junk)}\n"
                ),
            )
        )
        assert mem_report.promoted is False
        assert mem_report.success_rate == 0.0
        assert any("MemoryError" in r.error_detail for r in mem_report.sample_results)

        # 5. GET /api/v1/system/health 系统全维度自检端点
        health_res = client.get("/api/v1/system/health")
        assert health_res.status_code == 200
        h = health_res.json()
        assert h["status"] == "ok"
        assert h["vault_integrity"]["intact"] is True
        assert h["persistence"]["enterprise_name"] == "汇川工业自动化技术有限公司"
        assert h["persistence"]["slot_count"] >= 3
        assert h["sandbox_limits"]["max_memory_mb"] == 64
        assert h["sandbox_limits"]["recursion_limit"] == 200
        assert h["external_connectors"]["hmac_configured"] is True


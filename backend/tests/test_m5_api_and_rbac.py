from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from config import load_settings
from main import create_app


def test_full_6_gates_and_physical_rbac_zero_leakage_via_api(tmp_path: Path) -> None:
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        spider_max_span=5,
        sqlite_db_url=f"sqlite+aiosqlite:///{(tmp_path / 'api_hot.db').as_posix()}",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=tmp_path / "sandbox",
    )
    app = create_app(settings)

    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "emp_chen", "password": "123456"})
        assert login.status_code == 200
        # 实时连接 WebSocket 脉搏总线 (验证 G-Patch-5 异步演化事件广播)
        with client.websocket_connect("/ws/events") as ws:
            ws.send_json({"type": "authenticate", "token": login.json()["token"]})
            assert ws.receive_json() == {"type": "authenticated"}
            # 1. 验证物理级 RBAC 零泄密：普通员工视角原始 HTTP 字节流绝不包含 replaceability_score / management_view / 480 底价
            emp_ov = client.get("/api/v1/state/overview?role_view=employee&user_id=emp_chen")
            assert emp_ov.status_code == 200
            raw_emp_body = emp_ov.text
            assert '"replaceability_score"' not in raw_emp_body
            assert '"management_view"' not in raw_emp_body
            assert '"boundary_probes"' not in raw_emp_body
            emp_json = emp_ov.json()
            emp_json.pop("vault_health", None)
            assert "480" not in str(emp_json)

            # 2. 关卡 1：查常规库存成功，查工厂拿货底价被红线拦截且 B 面违规 +1、扣绩效
            ok_q = client.post(
                "/api/v1/chat/message",
                json={
                    "sender_id": "emp_chen",
                    "role_view": "employee",
                    "facade_bot": "COPILOT",
                    "chat_type": "SINGLE",
                    "content": "查一下A款人体工学椅现货库存和公开价格",
                },
            )
            assert ok_q.status_code == 200
            assert "1,280" in ok_q.json()["message"]["content"]

            bad_q = client.post(
                "/api/v1/chat/message",
                json={
                    "sender_id": "emp_chen",
                    "role_view": "employee",
                    "facade_bot": "COPILOT",
                    "chat_type": "SINGLE",
                    "content": "A款产品的工厂拿货底价是多少",
                },
            )
            assert bad_q.status_code == 200
            assert bad_q.json()["ticket"]["status"] == "INTERCEPTED"

            boss_ov = client.get("/api/v1/state/overview?role_view=boss&user_id=boss_lin").json()
            chen_prof = next(p for p in boss_ov["all_profiles"] if p["user_id"] == "emp_chen")
            assert chen_prof["management_view"]["boundary_probes"] == 1

            # 3. 关卡 2：不入网不认账拦截 + 微信记录公私剥离导单
            no_ctx = client.post(
                "/api/v1/chat/message",
                json={
                    "sender_id": "emp_chen",
                    "facade_bot": "GOVERNANCE",
                    "content": "帮我给王总直接发货",
                },
            )
            assert no_ctx.json()["ticket"]["status"] == "PENDING_CONTEXT"

            wx_imp = client.post(
                "/api/v1/chat/message",
                json={
                    "sender_id": "emp_chen",
                    "facade_bot": "COPILOT",
                    "content": "",
                    "raw_wechat_forward": [
                        "周末去哪吃火锅呀？",
                        "王总确认采购 10把 A款工学椅，手机 13899998888，收货地址张江科学城",
                    ],
                },
            )
            assert wx_imp.json()["ticket"]["status"] == "COMPLETED"
            assert "[REDACTED_PHONE]" in wx_imp.json()["l1_report"]["clean_text"]

            # 4. 关卡 3：6折+赔偿500元高压线 -> 组长老李审批 -> 财务王姐最小字段黑盒校验
            hv_req = client.post(
                "/api/v1/chat/message",
                json={
                    "sender_id": "emp_chen",
                    "facade_bot": "GOVERNANCE",
                    "content": "客户这笔订单原金额12800元，要求打6折并赔偿500元",
                },
            )
            leader_card_id = hv_req.json()["spawned_card"]["card_id"]

            approve_res = client.post(
                "/api/v1/human-tool/submit",
                json={
                    "actor_user_id": "leader_li",
                    "card_id": leader_card_id,
                    "submitted_output": {
                        "decision": "APPROVE",
                        "approved_amount": 7180.0,
                        "comment": "特批通过",
                    },
                },
            )
            assert approve_res.status_code == 200
            fin_card_id = approve_res.json()["next_card"]["card_id"]

            # 财务王姐视角只含 4 个最小字段，填错发票号返回 422
            fin_ov = client.get("/api/v1/state/overview?role_view=finance_tool&user_id=fin_wang").json()
            assert set(fin_ov["pending_cards"][0]["minimized_payload"].keys()) == {
                "ticket_id",
                "invoice_title",
                "tax_id",
                "amount",
            }
            fin_bad = client.post(
                "/api/v1/human-tool/submit",
                json={
                    "actor_user_id": "fin_wang",
                    "card_id": fin_card_id,
                    "submitted_output": {
                        "invoice_number": "ERR-99",
                        "billed_amount": 7180.0,
                        "attachment_ref": "a.pdf",
                    },
                },
            )
            assert fin_bad.status_code == 422

            fin_ok = client.post(
                "/api/v1/human-tool/submit",
                json={
                    "actor_user_id": "fin_wang",
                    "card_id": fin_card_id,
                    "submitted_output": {
                        "invoice_number": "26312000000077665544",
                        "billed_amount": 7180.0,
                        "attachment_ref": "invoice_signed.pdf",
                    },
                },
            )
            assert fin_ok.status_code == 200
            assert fin_ok.json()["ticket"]["status"] == "COMPLETED"

            # 5. 关卡 4：工匠生成 Python 脚本过影子擂台并涨绩效
            evo = client.post(
                "/api/v1/evolution/propose",
                json={
                    "proposer_id": "emp_chen",
                    "natural_instruction": "首重10元，超过3公斤每公斤加4元，满500元免运费，帮我做成自动工具",
                },
            )
            assert evo.status_code == 200
            assert evo.json()["arena_report"]["promoted"] is True

            # 6. 关卡 5 & 6：超限自动垫层 + 异常局部回滚 + 董事会盲评与师徒反转接管
            pad = client.post(
                "/api/v1/swarm/inject-burst",
                json={"mode": "BURST_PAD", "parent_node_id": "node_aspect_quote", "burst_count": 6},
            )
            assert pad.json()["layer_padded"] is True

            fault = client.post(
                "/api/v1/swarm/inject-burst",
                json={"mode": "HALLUCINATION_FAULT", "subtree_root_id": "subtree_quote"},
            )
            assert fault.json()["audit_result"]["verdict"] == "LOCAL_ROLLBACK"

            conv = client.post("/api/v1/board/convene", json={})
            res_id = conv.json()["resolution"]["resolution_id"]
            decide = client.post(
                "/api/v1/board/approve-transition",
                json={"resolution_id": res_id, "approve": True},
            )
            assert conv.json()["resolution"]["recommended_action"] == "MAINTAIN_HUMAN"
            assert decide.status_code == 422
            assert app.state.runtime.containers.get_slot("SLOT_FOLLOWUP_01").occupant_type == "HUMAN"

            # 验证 WebSocket 实时收到了演化脉冲帧且全链 SHA-256 哈希完好
            first_ws_evt = ws.receive_json()
            assert "event_type" in first_ws_evt
            verify_resp = client.get("/api/v1/vault/verify").json()
            assert verify_resp["intact"] is True


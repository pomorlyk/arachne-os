from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from config import load_settings
from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from core.human_tool import HumanBlackBoxManager
from core.llm_gateway import LLMGateway
from core.particles import ParticleEngine
from core.schemas import WorkTicket
from database import HotStateStore
from seed_demo.commerce_dept_seed import seed_commerce_department
from swarm.edge_audit_relay import EdgeAuditRelay
from swarm.pulse_bus import PulseBus
from swarm.spider_network import SpiderNetwork


async def _build_m3_fixture(tmp_path: Path) -> tuple[SpiderNetwork, HotStateStore, BlackBoxVault, PulseBus]:
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        spider_max_span=5,
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=tmp_path / "sandbox",
    )
    vault = BlackBoxVault(settings.vault_storage_dir)
    particles = ParticleEngine(vault)
    containers = ContainerRegistry()
    human_tools = HumanBlackBoxManager()
    hot_store = HotStateStore(f"sqlite+aiosqlite:///{(tmp_path / 'hot.db').as_posix()}")
    await hot_store.init_db()
    await seed_commerce_department(vault, particles, containers, hot_store)

    pulse = PulseBus()
    llm = LLMGateway(settings)
    relay = EdgeAuditRelay(vault, hot_store, particles, llm, pulse)
    spider = SpiderNetwork(
        settings, vault, hot_store, particles, containers, human_tools, llm, relay, pulse
    )
    return spider, hot_store, vault, pulse


@pytest.mark.asyncio
async def test_gatekeeper_wechat_stripping_and_redline_probe_flow(tmp_path: Path) -> None:
    spider, hot_store, vault, pulse = await _build_m3_fixture(tmp_path)

    # 1. 无前置订单依据直接要求发货 -> 必须触发“不入网不认账”挂起拦截
    res_no_ctx = await spider.process_inbound_turn(
        sender_id="emp_chen",
        facade_bot="GOVERNANCE",
        content="帮我给王总立刻发货50台！",
    )
    assert res_no_ctx["ticket"].status == "PENDING_CONTEXT"
    assert "不入网不认账" in res_no_ctx["reply"]

    # 2. 导入夹杂周末火锅寒暄与私人手机号的微信记录 -> L1 自动剥离脱敏并提炼干净订单 + 搓出新资料球
    res_import = await spider.process_inbound_turn(
        sender_id="emp_chen",
        facade_bot="COPILOT",
        content="",
        raw_wechat_forward=[
            "小陈周末咱们去哪吃火锅喝酒呀？",
            "王总这边确认下单 10把 A款人体工学椅，私人手机 13911112222，收货地址上海张江高科",
        ],
    )
    await pulse.drain_background_tasks()
    assert res_import["ticket"].status == "COMPLETED"
    assert res_import["l1_report"]["stripped_private_count"] >= 1
    assert res_import["l1_report"]["redacted_pii_count"] == 1
    assert "13911112222" not in res_import["l1_report"]["clean_text"]

    # 3. 尝试刺探 A 款产品工厂拿货底价 -> 红线拦截 + B面越界计数 +1
    res_redline = await spider.process_inbound_turn(
        sender_id="emp_chen",
        facade_bot="COPILOT",
        content="A款人体工学椅的工厂拿货底价是多少？",
    )
    assert res_redline["ticket"].status == "INTERCEPTED"
    assert await hot_store.get_boundary_probes("emp_chen") == 1
    await hot_store.close()


@pytest.mark.asyncio
async def test_high_voltage_leader_approval_and_finance_blackbox_rehydration(
    tmp_path: Path,
) -> None:
    spider, hot_store, vault, pulse = await _build_m3_fixture(tmp_path)

    # 客户要求打 6 折并赔偿 500 元 -> 高压线挂起并向基层组长老李推送审批卡片
    res_hv = await spider.process_inbound_turn(
        sender_id="emp_chen",
        facade_bot="GOVERNANCE",
        content="客户王总这批工学椅订单原金额12800元，要求打6折，并赔偿500元延期费！",
    )
    assert res_hv["ticket"].status == "PENDING_LEADER_APPROVAL"
    leader_card = res_hv["spawned_card"]
    assert leader_card is not None
    assert leader_card.target_slot_id == "SLOT_LEADER_01"

    # 组长老李拍板批准 -> 自动热唤醒处于 DEHYDRATED 的财务王姐节点并推送裁剪后的最小开票卡
    sub_leader = await spider.handle_human_tool_submission(
        actor_user_id="leader_li",
        card_id=leader_card.card_id,
        submitted_output={
            "decision": "APPROVE",
            "approved_amount": 7180.00,
            "comment": "老客户年度框架合作，特批放行",
        },
    )
    assert sub_leader["accepted"] is True
    fin_card = sub_leader["next_card"]
    assert fin_card is not None
    assert set(fin_card.minimized_payload.keys()) == {
        "ticket_id",
        "invoice_title",
        "tax_id",
        "amount",
    }

    # 验证王姐节点已从 DEHYDRATED 秒级唤醒为 ACTIVE
    nodes = {n.node_id: n for n in await hot_store.list_nodes()}
    assert nodes["node_blackbox_wang"].status == "ACTIVE"

    # 王姐第一次填错发票号被自动打回，第二次填对 20 位数电票号结单
    bad_fin = await spider.handle_human_tool_submission(
        actor_user_id="fin_wang",
        card_id=fin_card.card_id,
        submitted_output={
            "invoice_number": "BAD_NO",
            "billed_amount": 7180.00,
            "attachment_ref": "receipt.pdf",
        },
    )
    assert bad_fin["accepted"] is False

    good_fin = await spider.handle_human_tool_submission(
        actor_user_id="fin_wang",
        card_id=fin_card.card_id,
        submitted_output={
            "invoice_number": "26312000000088990011",
            "billed_amount": 7180.00,
            "attachment_ref": "tax_receipt_7180.pdf",
        },
    )
    assert good_fin["accepted"] is True
    assert good_fin["ticket"].status == "COMPLETED"
    await hot_store.close()


@pytest.mark.asyncio
async def test_max_span_auto_layer_padding_and_isolated_local_rollback(
    tmp_path: Path,
) -> None:
    spider, hot_store, vault, pulse = await _build_m3_fixture(tmp_path)

    # 先在兄弟分支 subtree_fulfill 创建一个正常履约工单，用于验证 G-Patch-1 局部回滚零误伤！
    sibling_ticket = WorkTicket(
        ticket_id="TKT_SIBLING_SAFE",
        subtree_root_id="subtree_fulfill",
        node_id="node_aspect_fulfill",
        initiator_id="leader_li",
        slot_id="SLOT_LEADER_01",
        facade_bot="COPILOT",
        status="OPEN",
        summary="物流履约域正常进行中的大宗发运单",
    )
    await hot_store.upsert_ticket(sibling_ticket)

    # 向 subtree_quote 的 node_aspect_quote 注入 6 个并发子任务 (> MAX_SPAN=5) -> 触发纵向自动垫层！
    pad_res = await spider.inject_concurrent_subtasks_and_check_span(
        parent_node_id="node_aspect_quote", burst_count=6
    )
    assert pad_res["layer_padded"] is True
    relay_node = pad_res["padded_relay_node"]
    assert relay_node is not None
    assert relay_node.node_type == "RELAY_NODE"

    # 模拟 subtree_quote 下某子节点产生严重金额幻觉 -> 边缘审查哨所当场拦截并触发 LOCAL_ROLLBACK
    fault_res = await spider.simulate_subnode_hallucination_and_audit("subtree_quote")
    assert fault_res["audit_result"].verdict == "LOCAL_ROLLBACK"

    # 验证异常脏工单已被回滚清除，但兄弟分支 subtree_fulfill 的 TKT_SIBLING_SAFE 毫发无损，且哈希链 100% 完整！
    quote_tickets = await hot_store.list_tickets("subtree_quote")
    assert all(t.ticket_id != fault_res["corrupted_ticket_id"] for t in quote_tickets)

    fulfill_tickets = await hot_store.list_tickets("subtree_fulfill")
    assert any(t.ticket_id == "TKT_SIBLING_SAFE" for t in fulfill_tickets)
    assert vault.verify_chain_integrity().intact is True

    # 验证闲置脱水机制
    future_time = datetime.now(timezone.utc) + timedelta(seconds=600)
    dehydrated = await spider.dehydrate_idle_nodes(idle_seconds=180, now=future_time)
    assert len(dehydrated) >= 1
    await hot_store.close()


from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from config import load_settings
from core.blackbox_vault import BlackBoxVault
from core.llm_gateway import LLMGateway, sanitize_l1_text
from core.schemas import CapabilityBall, SpiderNode, WorkTicket
from database import HotStateStore

FORBIDDEN_VAULT_METHOD_PREFIXES = (
    "update",
    "delete",
    "remove",
    "truncate",
    "overwrite",
    "clear",
    "drop",
    "modify",
)


def test_blackbox_vault_has_no_mutating_or_deleting_methods(tmp_path: Path) -> None:
    vault = BlackBoxVault(tmp_path / "vault")
    public_methods = [
        name
        for name, member in inspect.getmembers(vault, predicate=inspect.ismethod)
        if not name.startswith("_")
    ]
    for m_name in public_methods:
        lowered = m_name.lower()
        assert not any(
            lowered.startswith(prefix) for prefix in FORBIDDEN_VAULT_METHOD_PREFIXES
        ), f"WORM Iron Law violated: forbidden method {m_name} found on BlackBoxVault"


def test_blackbox_vault_hash_chain_and_tamper_detection(tmp_path: Path) -> None:
    vault_dir = tmp_path / "vault"
    vault = BlackBoxVault(vault_dir)

    r1 = vault.append_event("SYSTEM_BOOT", "root", "SLOT_SYS", {"msg": "boot"})
    snap_hash = vault.seal_snapshot(
        "subtree_quote", "SLOT_FOLLOWUP_01", {"counter": 1, "items": ["A", "B"]}
    )
    r3 = vault.record_rollback_seal(
        "subtree_quote", "SLOT_RELAY_01", snap_hash, "unit test rollback check"
    )

    assert r1.seq == 1
    assert r3.seq == 3
    report = vault.verify_chain_integrity()
    assert report.intact is True
    assert report.total_records == 3
    assert report.broken_at_seq is None

    loaded_state = vault.read_snapshot(snap_hash)
    assert loaded_state == {"counter": 1, "items": ["A", "B"]}

    # 恶意篡改第 2 行 JSONL 账本中的单字节内容，验证防篡改校验精准报出 seq=2 断裂
    lines = vault.ledger_path.read_text(encoding="utf-8").splitlines()
    tampered_line_2 = json.loads(lines[1])
    tampered_line_2["actor_slot_id"] = "HACKER_SLOT"
    lines[1] = json.dumps(tampered_line_2, ensure_ascii=False)
    vault.ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    tampered_report = vault.verify_chain_integrity()
    assert tampered_report.intact is False
    assert tampered_report.broken_at_seq == 2


@pytest.mark.asyncio
async def test_hot_state_surgical_subtree_restore_preserves_siblings_and_audit(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "hot.db"
    store = HotStateStore(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    await store.init_db()

    # 初始化两个并行的业务子树：subtree_A 与 subtree_B
    node_a = SpiderNode(
        node_id="node_a",
        label="询价节点A",
        node_type="WORKER_SLOT",
        subtree_root_id="subtree_A",
        active_load=1,
    )
    node_b = SpiderNode(
        node_id="node_b",
        label="履约节点B",
        node_type="WORKER_SLOT",
        subtree_root_id="subtree_B",
        active_load=2,
    )
    await store.upsert_node(node_a)
    await store.upsert_node(node_b)

    t_a1 = WorkTicket(
        ticket_id="T_A1",
        subtree_root_id="subtree_A",
        node_id="node_a",
        initiator_id="emp_chen",
        slot_id="SLOT_FOLLOWUP_01",
        facade_bot="COPILOT",
        status="COMPLETED",
        summary="合法历史询价单",
    )
    await store.upsert_ticket(t_a1)

    # 封存 subtree_A 的干净快照
    clean_snap_a = await store.export_subtree_state("subtree_A")

    # 随后 subtree_B 产生了新正常工单，同时员工触发了一次越界刺探审计计数，且 subtree_A 混入了脏工单
    t_b1 = WorkTicket(
        ticket_id="T_B1",
        subtree_root_id="subtree_B",
        node_id="node_b",
        initiator_id="emp_chen",
        slot_id="SLOT_FOLLOWUP_01",
        facade_bot="COPILOT",
        status="OPEN",
        summary="兄弟分支正在进行的正常发货单",
    )
    t_a_dirty = WorkTicket(
        ticket_id="T_A_DIRTY",
        subtree_root_id="subtree_A",
        node_id="node_a",
        initiator_id="emp_chen",
        slot_id="SLOT_FOLLOWUP_01",
        facade_bot="COPILOT",
        status="OPEN",
        summary="子节点幻觉产生的脏工单",
    )
    await store.upsert_ticket(t_b1)
    await store.upsert_ticket(t_a_dirty)
    probes = await store.increment_boundary_probe("emp_chen")
    assert probes == 1

    # 对 subtree_A 执行局部回滚恢复
    await store.restore_subtree_state("subtree_A", clean_snap_a)

    tickets_a = await store.list_tickets("subtree_A")
    tickets_b = await store.list_tickets("subtree_B")
    assert [t.ticket_id for t in tickets_a] == ["T_A1"]
    assert [t.ticket_id for t in tickets_b] == ["T_B1"]
    assert await store.get_boundary_probes("emp_chen") == 1
    await store.close()


@pytest.mark.asyncio
async def test_l1_sanitizer_and_llm_gateway_offline_engine(tmp_path: Path) -> None:
    settings = load_settings(
        enforce_bearer_auth=False,
        llm_api_key="",
        vault_storage_dir=tmp_path / "vault",
        sandbox_workspace_dir=tmp_path / "sandbox",
    )
    gw = LLMGateway(settings)
    assert gw.is_live_mode is False

    report = sanitize_l1_text(
        raw_text="",
        raw_wechat_lines=[
            "周末去哪吃火锅呀兄弟？",
            "王总需要订购 15把 A款人体工学椅，联系电话 13812345678，尽快报价发货",
        ],
    )
    assert report.stripped_private_count >= 1
    assert report.redacted_pii_count == 1
    assert "13812345678" not in report.clean_text
    assert "[REDACTED_PHONE]" in report.clean_text
    assert "火锅" not in report.clean_text

    redline = CapabilityBall(
        ball_id="BALL_REDLINE_FLOOR",
        ball_type="REDLINE",
        title="绝密工厂拿货底价隔离墙",
        domain_tags=["底价"],
        sensitivity_level=5,
        owner_slot_ids=["SLOT_BOSS"],
        content="A款工厂底价480元",
        redline_keywords=["工厂拿货底价", "拿货底价", "工厂底价"],
    )
    decision_redline = await gw.analyze_explorer_turn(
        clean_text="请问A款产品的工厂拿货底价是多少？",
        has_forwarded_evidence=False,
        has_prior_order_context=False,
        accessible_balls=[],
        redline_balls=[redline],
    )
    assert decision_redline.redline_violated is True
    assert decision_redline.violated_redline_ball_id == "BALL_REDLINE_FLOOR"

    title, tags, code = await gw.synthesize_artisan_skill(
        "首重10元，超过3公斤每公斤加4元，满500元免运费"
    )
    assert "运费" in title
    assert "def execute_skill(payload: dict) -> dict:" in code


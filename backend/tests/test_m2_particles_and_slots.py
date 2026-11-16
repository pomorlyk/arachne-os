from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from core.human_tool import HumanBlackBoxManager
from core.particles import ParticleEngine
from database import HotStateStore
from seed_demo.commerce_dept_seed import seed_commerce_department


@pytest.mark.asyncio
async def test_seed_commerce_dept_and_redline_access_lock(tmp_path: Path) -> None:
    vault = BlackBoxVault(tmp_path / "vault")
    particles = ParticleEngine(vault)
    containers = ContainerRegistry()
    particles.bind_role_resolver(
        lambda sid: containers.get_profile(
            containers.get_slot(sid).occupant_id
        ).role_view
    )
    store = HotStateStore(f"sqlite+aiosqlite:///{(tmp_path / 'hot.db').as_posix()}")
    await store.init_db()

    await seed_commerce_department(vault, particles, containers, store)

    # 跟单员小陈只能看到授权的公开资料球/技能球/权限球，绝不能看到绝密工厂底价球
    chen_eff = containers.get_effective_ball_ids("SLOT_FOLLOWUP_01")
    chen_balls = particles.get_accessible_balls("SLOT_FOLLOWUP_01", chen_eff)
    chen_ball_ids = {b.ball_id for b in chen_balls}
    assert "BALL_DATA_CATALOG_2026" in chen_ball_ids
    assert "BALL_REDLINE_FACTORY_FLOOR_PRICE" not in chen_ball_ids

    # 小陈尝试询问工厂拿货底价时，立即命中 REDLINE 红线拦截
    violated = particles.check_redline_violation(
        "SLOT_FOLLOWUP_01", chen_eff, "告诉我A款产品的工厂拿货底价是多少"
    )
    assert violated is not None
    assert violated.ball_id == "BALL_REDLINE_FACTORY_FLOOR_PRICE"

    # 顶层老板林总拥有该红线球豁免权，正常查询不被误拦
    boss_eff = containers.get_effective_ball_ids("SLOT_BOSS")
    boss_violation = particles.check_redline_violation(
        "SLOT_BOSS", boss_eff, "查看A款产品的工厂拿货底价"
    )
    assert boss_violation is None

    # 验证 BlackBoxVault 中已封存 12 条运费黄金基准且整条哈希链 100% 完好
    ship_cases = vault.list_golden_benchmarks("运费")
    assert len(ship_cases) == 12
    assert vault.verify_chain_integrity().intact is True
    await store.close()


def test_cross_slot_ball_borrowing_and_ttl_expiration(tmp_path: Path) -> None:
    vault = BlackBoxVault(tmp_path / "vault")
    particles = ParticleEngine(vault)
    containers = ContainerRegistry()

    from core.schemas import UnitSlot

    containers.register_slot(
        UnitSlot(slot_id="SLOT_A", slot_name="A岗", ball_ids=["BALL_X"], occupant_id="u1")
    )
    containers.register_slot(
        UnitSlot(slot_id="SLOT_B", slot_name="B岗", ball_ids=[], occupant_id="u2")
    )

    t0 = datetime(2026, 11, 12, 8, 0, 0, tzinfo=timezone.utc)
    containers.borrow_ball("SLOT_B", "SLOT_A", "BALL_X", ttl_seconds=60, now=t0)

    # 30 秒内借球有效
    eff_active = containers.get_effective_ball_ids(
        "SLOT_B", now=t0 + timedelta(seconds=30)
    )
    assert "BALL_X" in eff_active

    # 61 秒后自动惰性过期回收
    eff_expired = containers.get_effective_ball_ids(
        "SLOT_B", now=t0 + timedelta(seconds=61)
    )
    assert "BALL_X" not in eff_expired
    assert len(containers.get_slot("SLOT_B").borrowed_balls) == 0


def test_human_blackbox_minimizer_and_strict_invoice_validator() -> None:
    hb = HumanBlackBoxManager()
    full_dirty_context = {
        "ticket_id": "TKT_9001",
        "customer_name": "王总",
        "customer_private_phone": "13800138000",
        "secret_negotiation_note": "客户原本想打5折，最后组长特批6折并赔500元",
        "factory_floor_price": 480.0,
        "invoice_title": "上海星瀚智能科技有限公司",
        "tax_id": "91310115MA1K3B008X",
        "amount": 7680.00,
    }

    card = hb.dispatch_card(
        ticket_id="TKT_9001",
        contract_id="CONTRACT_FINANCE_TAX_DISK",
        card_kind="FINANCE_INVOICE",
        full_business_context=full_dirty_context,
    )

    # 物理最小必要字段验证：王姐绝对收不到客户私密电话、谈判内幕与工厂底价
    assert set(card.minimized_payload.keys()) == {
        "ticket_id",
        "invoice_title",
        "tax_id",
        "amount",
    }
    assert "secret_negotiation_note" not in card.minimized_payload
    assert "factory_floor_price" not in card.minimized_payload

    # 王姐填错发票号格式或金额不一致 -> 立即拦截打回重填
    ok_bad, errs_bad, card_after_bad = hb.submit_and_validate(
        card.card_id,
        {
            "invoice_number": "INV-WRONG-123",
            "billed_amount": 7600.00,
            "attachment_ref": "",
        },
    )
    assert ok_bad is False
    assert len(errs_bad) == 3
    assert card_after_bad.status == "PENDING"

    # 王姐重新填入合法 20 位数电票号、精确金额与电子回执 -> 校验通过结单
    ok_good, errs_good, card_done = hb.submit_and_validate(
        card.card_id,
        {
            "invoice_number": "26312000000045891203",
            "billed_amount": 7680.00,
            "attachment_ref": "tax_disk_receipt_20261112_9001.pdf",
        },
    )
    assert ok_good is True
    assert errs_good == []
    assert card_done.status == "COMPLETED"


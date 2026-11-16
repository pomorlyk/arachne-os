"""
Dynamic Topology & Registry Resolver for Arachne-OS.

Replaces static furniture-demo IDs across runtime engines, simulators, and routes
with deterministic runtime lookups against the active ContainerRegistry and ParticleEngine.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional


def _list_slots(containers: Any) -> list[Any]:
    if containers is None:
        return []
    if hasattr(containers, "list_slots"):
        return list(containers.list_slots())
    slots = getattr(containers, "_slots", None) or getattr(containers, "slots", None)
    if isinstance(slots, dict):
        return list(slots.values())
    return []


def _list_profiles(containers: Any) -> list[Any]:
    if containers is None:
        return []
    if hasattr(containers, "list_profiles"):
        return list(containers.list_profiles())
    profiles = getattr(containers, "_profiles", None)
    if isinstance(profiles, dict):
        return list(profiles.values())
    return []


def _list_balls(particles: Any) -> list[Any]:
    if particles is None:
        return []
    if hasattr(particles, "list_all_balls"):
        return list(particles.list_all_balls())
    if hasattr(particles, "list_balls"):
        return list(particles.list_balls())
    balls = getattr(particles, "_balls", None) or getattr(particles, "balls", None)
    if isinstance(balls, dict):
        return list(balls.values())
    return []


def _get_account_dir(account_dir: Optional[dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    if account_dir is not None:
        return account_dir
    try:
        from core.auth_custody import ACCOUNT_DIRECTORY
        return ACCOUNT_DIRECTORY
    except Exception:
        return {}


def _slot_text(slot: Any) -> str:
    parts = [
        str(getattr(slot, "slot_id", "") or ""),
        str(getattr(slot, "slot_name", "") or ""),
        str(getattr(slot, "department", "") or ""),
    ]
    return " ".join(parts).lower()


def _slot_role_view(
    slot: Any,
    containers: Any = None,
    account_dir: Optional[dict[str, dict[str, Any]]] = None,
) -> str:
    if slot is None:
        return ""
    slot_id = str(getattr(slot, "slot_id", "") or "")
    occupant_id = str(getattr(slot, "occupant_id", "") or "")
    directory = _get_account_dir(account_dir)
    profiles = _list_profiles(containers)

    if occupant_id:
        for p in profiles:
            if str(getattr(p, "user_id", "")) == occupant_id:
                return str(getattr(p, "role_view", "") or "")
        if occupant_id in directory and not directory[occupant_id].get("_disabled"):
            rv = directory[occupant_id].get("role_view")
            if rv:
                return str(rv)

    for p in profiles:
        uid = str(getattr(p, "user_id", ""))
        if str(getattr(p, "slot_id", "")) == slot_id and not directory.get(uid, {}).get("_disabled"):
            return str(getattr(p, "role_view", "") or "")

    for info in directory.values():
        if not info.get("_disabled") and info.get("slot_id") == slot_id and info.get("role_view"):
            return str(info["role_view"])

    text = _slot_text(slot)
    if any(k in text for k in ("boss", "总裁", "ceo", "董事长")):
        return "boss"
    if any(k in text for k in ("finance", "tax", "财务", "财税", "审计", "税务")):
        return "finance_tool"
    if any(k in text for k in ("mgr", "manager", "经理", "运营管理")):
        return "manager"
    if any(k in text for k in ("leader", "主管", "组长", "复核", "风控")):
        return "leader"
    return "employee"


def _pick_account_for_slot(
    slot: Any,
    containers: Any = None,
    account_dir: Optional[dict[str, dict[str, Any]]] = None,
) -> str:
    if slot is None:
        return ""
    slot_id = str(getattr(slot, "slot_id", "") or "")
    occupant_id = str(getattr(slot, "occupant_id", "") or "")
    directory = _get_account_dir(account_dir)
    profiles = _list_profiles(containers)
    profile_by_uid = {str(getattr(p, "user_id", "")): p for p in profiles}

    if occupant_id and occupant_id in profile_by_uid and not directory.get(occupant_id, {}).get("_disabled"):
        return occupant_id

    for p in profiles:
        uid = str(getattr(p, "user_id", ""))
        if str(getattr(p, "slot_id", "")) == slot_id and uid and not directory.get(uid, {}).get("_disabled"):
            return uid

    for uid, info in directory.items():
        if info.get("_disabled"):
            continue
        if info.get("slot_id") == slot_id:
            return uid

    if occupant_id:
        return occupant_id
    return f"user_{slot_id.lower()}" if slot_id else ""


def resolve_frontline_user_and_slot(
    containers: Any,
    account_dir: Optional[dict[str, dict[str, Any]]] = None,
    prefer_user_id: Optional[str] = None,
    prefer_slot_id: Optional[str] = None,
) -> tuple[str, str]:
    slots = _list_slots(containers)
    if not slots:
        return (prefer_user_id or "", prefer_slot_id or "")

    directory = _get_account_dir(account_dir)

    if prefer_user_id and prefer_user_id in directory:
        mapped_sid = directory[prefer_user_id].get("slot_id")
        if mapped_sid:
            for s in slots:
                if s.slot_id == mapped_sid:
                    return (prefer_user_id, s.slot_id)

    if prefer_slot_id:
        for s in slots:
            if s.slot_id == prefer_slot_id:
                return (_pick_account_for_slot(s, containers, directory), s.slot_id)

    employee_slots = [s for s in slots if _slot_role_view(s, containers, directory) == "employee"]
    if employee_slots:
        chosen = employee_slots[0]
        return (_pick_account_for_slot(chosen, containers, directory), chosen.slot_id)

    leader_slots = [s for s in slots if _slot_role_view(s, containers, directory) == "leader"]
    if leader_slots:
        chosen = leader_slots[0]
        return (_pick_account_for_slot(chosen, containers, directory), chosen.slot_id)

    non_exec = [
        s for s in slots if _slot_role_view(s, containers, directory) not in ("boss", "manager")
    ]
    chosen = non_exec[0] if non_exec else slots[0]
    return (_pick_account_for_slot(chosen, containers, directory), chosen.slot_id)


def resolve_leader_user_and_slot(
    containers: Any,
    account_dir: Optional[dict[str, dict[str, Any]]] = None,
) -> tuple[str, str]:
    slots = _list_slots(containers)
    if not slots:
        return ("", "")

    directory = _get_account_dir(account_dir)
    for target_view in ("leader", "manager", "employee"):
        matched = [s for s in slots if _slot_role_view(s, containers, directory) == target_view]
        if matched:
            chosen = matched[0]
            return (_pick_account_for_slot(chosen, containers, directory), chosen.slot_id)

    chosen = slots[0]
    return (_pick_account_for_slot(chosen, containers, directory), chosen.slot_id)


def resolve_blackbox_user_and_slot(
    containers: Any,
    account_dir: Optional[dict[str, dict[str, Any]]] = None,
    nodes: Optional[Any] = None,
) -> tuple[str, str]:
    slots = _list_slots(containers)
    if not slots:
        return ("", "")

    directory = _get_account_dir(account_dir)
    finance_slots = [s for s in slots if _slot_role_view(s, containers, directory) == "finance_tool"]
    if finance_slots:
        chosen = finance_slots[0]
        return (_pick_account_for_slot(chosen, containers, directory), chosen.slot_id)

    bb_attr = [s for s in slots if getattr(s, "is_blackbox_tool", False)]
    if bb_attr:
        chosen = bb_attr[0]
        return (_pick_account_for_slot(chosen, containers, directory), chosen.slot_id)

    keywords = ("财务", "财税", "审计", "法务", "合规", "风控", "finance", "audit", "legal")
    for s in slots:
        text = _slot_text(s)
        if any(k in text for k in keywords):
            return (_pick_account_for_slot(s, containers, directory), s.slot_id)

    return resolve_leader_user_and_slot(containers, directory)


def resolve_executive_slots(
    containers: Any,
    account_dir: Optional[dict[str, dict[str, Any]]] = None,
) -> tuple[list[str], list[str]]:
    slots = _list_slots(containers)
    if not slots:
        return ([], [])

    directory = _get_account_dir(account_dir)
    boss_slots = [s.slot_id for s in slots if _slot_role_view(s, containers, directory) == "boss"]
    mgr_slots = [s.slot_id for s in slots if _slot_role_view(s, containers, directory) == "manager"]

    if not boss_slots and mgr_slots:
        boss_slots = mgr_slots[:1]
    if not mgr_slots:
        leader_slots = [s.slot_id for s in slots if _slot_role_view(s, containers, directory) == "leader"]
        mgr_slots = leader_slots[:1] if leader_slots else (boss_slots[:1] if boss_slots else [slots[0].slot_id])
    if not boss_slots and mgr_slots:
        boss_slots = mgr_slots[:1]

    return (boss_slots, mgr_slots)


def resolve_active_authority_ball(
    particles: Any,
    containers: Any = None,
    domain_hint: str = "",
) -> str:
    balls = _list_balls(particles)
    auth_balls = [
        b for b in balls
        if getattr(b, "ball_type", "") == "AUTHORITY" and getattr(b, "status", "ACTIVE") == "ACTIVE"
    ] or [b for b in balls if getattr(b, "ball_type", "") == "AUTHORITY"]

    if auth_balls:
        hint = (domain_hint or "").strip().lower()
        if hint:
            for b in auth_balls:
                tags = " ".join(getattr(b, "domain_tags", []) or [])
                blob = f"{b.ball_id} {b.title} {tags} {getattr(b, 'content', '')}".lower()
                if hint in blob:
                    return str(b.ball_id)
        for preferred_kw in ("gate", "approval", "override", "hv", "批", "授权", "放行", "特批"):
            for b in auth_balls:
                tags = " ".join(getattr(b, "domain_tags", []) or [])
                blob = f"{b.ball_id} {b.title} {tags} {getattr(b, 'content', '')}".lower()
                if preferred_kw in blob:
                    return str(b.ball_id)
        return str(auth_balls[0].ball_id)

    skill_balls = [b for b in balls if getattr(b, "ball_type", "") == "SKILL"]
    if skill_balls:
        return str(skill_balls[0].ball_id)
    if balls:
        return str(balls[0].ball_id)
    return "BALL_AUTH_GATE"


def _extract_numeric_floor(text_blob: str) -> float:
    for pattern in (
        r"(?:底价|红线|最低|不低于|单价下限|min[_\s]?price|floor)[^\d]{0,12}(\d+(?:\.\d+)?)",
        r"(?:￥|¥|RMB|USD|\$)\s*(\d+(?:\.\d+)?)",
    ):
        match = re.search(pattern, text_blob, flags=re.IGNORECASE)
        if match:
            try:
                val = float(match.group(1))
                if val > 0:
                    return val
            except ValueError:
                pass
    return 0.0


def resolve_active_redline_and_floor(
    particles: Any,
) -> tuple[str, float, list[str]]:
    balls = _list_balls(particles)
    redlines = [
        b for b in balls
        if getattr(b, "ball_type", "") == "REDLINE" and getattr(b, "status", "ACTIVE") == "ACTIVE"
    ] or [b for b in balls if getattr(b, "ball_type", "") == "REDLINE"]
    default_keywords = ["底价", "折扣", "让利", "特批", "豁免", "免费", "免单"]

    if not redlines:
        return ("BALL_REDLINE_POLICY", 0.0, list(default_keywords))

    chosen = redlines[0]
    best_floor = 0.0
    for b in redlines:
        tags = " ".join(getattr(b, "domain_tags", []) or [])
        rl_kws = " ".join(getattr(b, "redline_keywords", []) or [])
        blob = f"{b.ball_id} {b.title} {tags} {rl_kws} {getattr(b, 'content', '')}"
        floor_val = _extract_numeric_floor(blob)
        if floor_val > 0 or any(k in blob for k in ("底价", "报价", "折扣", "价格", "floor", "price", "margin")):
            chosen = b
            best_floor = floor_val
            break

    if best_floor <= 0:
        blob = f"{chosen.ball_id} {chosen.title} {getattr(chosen, 'content', '')}"
        best_floor = _extract_numeric_floor(blob)

    kws: list[str] = []
    for kw in (getattr(chosen, "redline_keywords", []) or []):
        if kw and str(kw) not in kws:
            kws.append(str(kw))
    title = str(getattr(chosen, "title", "") or "")
    for token in re.split(r"[\s/·,，:：()（）\-]+", title):
        if len(token) >= 2 and token not in kws:
            kws.append(token)
    for base_kw in default_keywords:
        if base_kw not in kws:
            kws.append(base_kw)

    return (str(chosen.ball_id), best_floor, kws)


def resolve_primary_catalog_item(particles: Any) -> str:
    balls = _list_balls(particles)
    data_balls = [
        b for b in balls
        if getattr(b, "ball_type", "") == "DATA" and getattr(b, "status", "ACTIVE") == "ACTIVE"
    ] or [b for b in balls if getattr(b, "ball_type", "") == "DATA"]

    for b in data_balls:
        content = str(getattr(b, "content", "") or "")
        m = re.search(r"(?:主营|产品|服务|交付物|SKU|目录)[：:\s]*([^，,。\n；;]{2,20})", content)
        if m:
            candidate = m.group(1).strip()
            if candidate:
                return candidate
        title = str(getattr(b, "title", "") or "").strip()
        if title and "红线" not in title:
            return title

    skill_balls = [b for b in balls if getattr(b, "ball_type", "") == "SKILL"]
    if skill_balls:
        title = str(getattr(skill_balls[0], "title", "") or "").strip()
        if title:
            return title

    return "核心标准交付物"


def resolve_slot_by_role_keywords(
    containers: Any,
    keywords: Iterable[str],
    fallback_role_views: tuple[str, ...] = ("employee", "leader"),
    exclude_slot_ids: Optional[set[str]] = None,
) -> str:
    slots = _list_slots(containers)
    if not slots:
        return ""

    excluded = exclude_slot_ids or set()
    candidates = [s for s in slots if s.slot_id not in excluded] or slots
    kw_list = [str(k).lower() for k in keywords if k]

    for s in candidates:
        text = _slot_text(s)
        if any(kw in text for kw in kw_list):
            return str(s.slot_id)

    for rv in fallback_role_views:
        for s in candidates:
            if _slot_role_view(s, containers) == rv:
                return str(s.slot_id)

    return str(candidates[0].slot_id)

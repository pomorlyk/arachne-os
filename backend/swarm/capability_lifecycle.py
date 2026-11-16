from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re
from typing import Any, Literal, Optional

import numpy as np

from core.auth_custody import AuthAndCustodyService
from core.schemas import CapabilityBall
from swarm.genesis_fission import EnterpriseGenesisAndFissionEngine

TYPE_LABELS: dict[str, str] = {
    "DATA": "业务资料",
    "SKILL": "计算工具",
    "AUTHORITY": "审批权限",
    "REDLINE": "风控底线",
}

BUSINESS_CATEGORIES: list[str] = [
    "销售与报价",
    "仓储与物流",
    "采购与品控",
    "财务与法务",
    "风控与管理",
]

_FORMULA_HINT_KEYWORDS = (
    "公式",
    "每公斤",
    "满",
    "折扣",
    "费率",
    "利率",
    "返利",
    "违约金",
    "阶梯",
    "水位",
    "按日",
    "计提",
)


def classify_capability_category(ball: CapabilityBall) -> str:
    """将任意能力模块精准归入 5 大中文业务领域。"""
    text = f"{' '.join(ball.domain_tags)} {ball.title} {ball.content}".lower()

    if ball.ball_type == "REDLINE" or ball.sensitivity_level >= 5:
        if any(k in text for k in ("财务", "发票", "税", "账期", "法务", "合同", "外汇", "医保")):
            return "财务与法务"
        return "风控与管理"

    if any(k in text for k in ("仓储", "库存", "物流", "运费", "冷链", "车队", "调拨", "磅房", "油料")):
        return "仓储与物流"
    if any(k in text for k in ("采购", "供应链", "bom", "质检", "aql", "车间", "排产", "电芯", "生产")):
        return "采购与品控"
    if any(k in text for k in ("财务", "发票", "税", "结算", "账期", "法务", "合同", "外汇", "医保")):
        return "财务与法务"
    if any(k in text for k in ("报价", "折扣", "订单", "客户", "集采", "返利", "bd", "大促", "销售", "跟单", "特钢")):
        return "销售与报价"
    return "风控与管理"


def build_quick_use_prompt(ball: CapabilityBall) -> str:
    """根据能力模块类型与内容生成一键带入工作对话的自然语言调用语句。"""
    if ball.ball_type == "SKILL":
        return f"请使用《{ball.title}》帮我计算：数量 10，单价 500，重量 5 公斤，订单金额 320"
    if ball.ball_type == "DATA":
        return f"请根据《{ball.title}》帮我查一下核心标准和注意事项"
    return f"请帮我核对《{ball.title}》的审批范围和风控要求"


def _parse_iso_utc(ts: str) -> datetime:
    cleaned = ts.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    return datetime.fromisoformat(cleaned)


def _normalize_title_tokens(title: str) -> set[str]:
    stripped = re.sub(r"\[[^\]]+\]|【[^】]+】|[（(][^）)]+[)）]", " ", title)
    parts = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_]{2,}", stripped.lower())
    tokens: set[str] = set()
    for p in parts:
        tokens.add(p)
        if len(p) >= 4 and re.search(r"[\u4e00-\u9fff]", p):
            for i in range(len(p) - 1):
                tokens.add(p[i : i + 2])
    return tokens


class CapabilityLifecycleEngine:
    """
    能力目录分类 + “孵化（接生婆）+ 清理（死神）”全生命周期治理引擎：
    - 统一维护 5 大业务分类 × 4 大功能性质；
    - 孵化角色：从新制度拆解原子模块、将臃肿模块一分为二；
    - 清理角色：巡检重复/相似模块、长期闲置冗余项、过期临时授权，并执行合并/下线归档/恢复。
    """

    def __init__(self, runtime: Any) -> None:
        self._rt = runtime
        self._vault = runtime.vault
        self._particles = runtime.particles
        self._containers = runtime.containers
        self._pulse = runtime.pulse_bus

    def _get_auth_custody(self) -> AuthAndCustodyService:
        svc = getattr(self._rt, "auth_custody", None)
        if svc is None:
            svc = AuthAndCustodyService(
                vault=self._vault,
                particles=self._particles,
                containers=self._containers,
                settings=getattr(self._rt, "settings", None),
            )
            setattr(self._rt, "auth_custody", svc)
        return svc

    def _get_genesis_engine(self) -> EnterpriseGenesisAndFissionEngine:
        eng = getattr(self._rt, "genesis_engine", None)
        if eng is None:
            eng = EnterpriseGenesisAndFissionEngine(runtime=self._rt)
            setattr(self._rt, "genesis_engine", eng)
        return eng

    def _compute_usage_counts(self) -> Counter[str]:
        counts: Counter[str] = Counter()
        try:
            records = self._vault.read_records()
            for rec in records:
                payload = rec.payload or {}
                for key in ("ball_id", "minted_ball_id", "merge_into_ball_id"):
                    val = payload.get(key)
                    if isinstance(val, str) and val:
                        counts[val] += 1
                for list_key in ("ball_ids", "cited_ball_ids", "matched_ball_ids"):
                    vals = payload.get(list_key)
                    if isinstance(vals, list):
                        for item in vals:
                            if isinstance(item, str) and item:
                                counts[item] += 1
        except Exception:
            pass
        return counts

    def _serialize_module(
        self,
        ball: CapabilityBall,
        mounted_ids: set[str],
        borrowed_ids: set[str],
        usage_counts: Counter[str],
        auth_svc: AuthAndCustodyService,
    ) -> dict[str, Any]:
        custodian_id, custodian_name = auth_svc.resolve_ball_custodian(ball.ball_id)
        category = classify_capability_category(ball)
        type_label = TYPE_LABELS.get(ball.ball_type, "业务资料")
        usage_count = int(usage_counts.get(ball.ball_id, 0))
        is_bloated = len(ball.content.strip()) > 95
        return {
            **ball.model_dump(),
            "business_category": category,
            "type_label": type_label,
            "custodian_id": custodian_id,
            "custodian_name": custodian_name,
            "is_mounted": ball.ball_id in mounted_ids,
            "is_borrowed": ball.ball_id in borrowed_ids,
            "usage_count": usage_count,
            "quick_use_prompt": build_quick_use_prompt(ball),
            "is_bloated": is_bloated,
        }

    def _ensure_manage_permission(self, actor_user_id: str, ball_id: str) -> Any:
        prof = self._containers.get_profile(actor_user_id)
        ball = self._particles.get_ball(ball_id)
        if (
            ball is not None
            and ball.ball_type == "REDLINE"
            and prof.role_view != "boss"
        ):
            raise PermissionError("红线模块仅允许老板管理")
        if prof.role_view in ("boss", "manager"):
            return prof
        auth_svc = self._get_auth_custody()
        if auth_svc.can_user_manage_ball(actor_user_id, ball_id):
            return prof
        raise PermissionError("仅分管主管或管理层可执行能力清理与合并操作")

    def get_catalog(self, user_id: str) -> dict[str, Any]:
        prof = self._containers.get_profile(user_id)
        slot = self._containers.get_slot(prof.slot_id)
        mounted_ids = set(self._containers.get_effective_ball_ids(prof.slot_id))
        borrowed_ids = {lease.ball_id for lease in slot.borrowed_balls}
        is_executive = prof.role_view in ("manager", "boss")
        auth_svc = self._get_auth_custody()
        usage_counts = self._compute_usage_counts()

        active_modules: list[dict[str, Any]] = []
        archived_modules: list[dict[str, Any]] = []

        for ball in self._particles.list_all_balls():
            if ball.ball_type == "REDLINE" and prof.role_view != "boss":
                continue

            item = self._serialize_module(
                ball=ball,
                mounted_ids=mounted_ids,
                borrowed_ids=borrowed_ids,
                usage_counts=usage_counts,
                auth_svc=auth_svc,
            )
            if ball.ball_id not in mounted_ids:
                # Discovery metadata permits a permission request, never reading
                # another slot's business data or filesystem source location.
                item = {
                    key: value
                    for key, value in item.items()
                    if key
                    not in {
                        "content",
                        "executable_code_path",
                        "owner_slot_ids",
                        "redline_keywords",
                    }
                }
            if ball.status == "DEPRECATED":
                archived_modules.append(item)
            else:
                active_modules.append(item)

        cat_counter: Counter[str] = Counter(
            m["business_category"] for m in active_modules
        )
        categories_summary = [
            {"category": cat, "count": int(cat_counter.get(cat, 0))}
            for cat in BUSINESS_CATEGORIES
        ]

        return {
            "user_id": user_id,
            "slot_id": prof.slot_id,
            "is_executive": is_executive,
            "is_custodian_leader": bool(is_executive or prof.role_view == "leader"),
            "business_categories": list(BUSINESS_CATEGORIES),
            "type_labels": dict(TYPE_LABELS),
            "categories_summary": categories_summary,
            "active_count": len(active_modules),
            "archived_count": len(archived_modules),
            "modules": active_modules,
            "archived_modules": archived_modules,
        }

    async def incubate_or_split(
        self,
        actor_user_id: str,
        raw_policy_text: str = "",
        target_ball_id: Optional[str] = None,
    ) -> dict[str, Any]:
        genesis = self._get_genesis_engine()
        res = await genesis.decompose_or_split_balls(
            actor_user_id=actor_user_id,
            raw_policy_text=raw_policy_text,
            target_ball_id=target_ball_id,
        )
        auth_svc = self._get_auth_custody()
        usage_counts = self._compute_usage_counts()
        prof = self._containers.get_profile(actor_user_id)
        slot = self._containers.get_slot(prof.slot_id)
        mounted_ids = set(self._containers.get_effective_ball_ids(prof.slot_id))
        borrowed_ids = {lease.ball_id for lease in slot.borrowed_balls}

        enriched_created: list[dict[str, Any]] = []
        for raw in res.get("minted_balls") or res.get("child_balls") or []:
            bid = raw.get("ball_id")
            ball_obj = self._particles.get_ball(bid) if bid else None
            if ball_obj is not None:
                enriched_created.append(
                    self._serialize_module(
                        ball=ball_obj,
                        mounted_ids=mounted_ids,
                        borrowed_ids=borrowed_ids,
                        usage_counts=usage_counts,
                        auth_svc=auth_svc,
                    )
                )
            else:
                enriched_created.append(raw)

        return {
            **res,
            "created_modules": enriched_created,
        }

    def _compute_similarity(self, a: CapabilityBall, b: CapabilityBall) -> float:
        vec_a = self._particles._vectors.get(a.ball_id)
        vec_b = self._particles._vectors.get(b.ball_id)
        cosine = 0.0
        if vec_a is not None and vec_b is not None:
            cosine = float(np.dot(vec_a, vec_b))

        tok_a = _normalize_title_tokens(a.title)
        tok_b = _normalize_title_tokens(b.title)
        jaccard = 0.0
        if tok_a and tok_b:
            jaccard = len(tok_a & tok_b) / max(1, len(tok_a | tok_b))

        return round(max(cosine, jaccard, 0.55 * cosine + 0.45 * jaccard), 4)

    def scan_lifecycle_health(self, user_id: str) -> dict[str, Any]:
        prof = self._containers.get_profile(user_id)
        is_executive = prof.role_view in ("manager", "boss")
        mounted_ids = set(self._containers.get_effective_ball_ids(prof.slot_id))
        usage_counts = self._compute_usage_counts()

        active_balls = [
            b for b in self._particles.list_all_balls() if b.status == "ACTIVE"
        ]

        def _can_inspect(ball: CapabilityBall) -> bool:
            return ball.ball_type != "REDLINE" or prof.role_view == "boss"

        visible_active = [b for b in active_balls if _can_inspect(b)]

        reaper_candidates: list[dict[str, Any]] = []
        midwife_candidates: list[dict[str, Any]] = []

        # 1. 扫描同类型重复 / 高度相似模块
        seen_pairs: set[tuple[str, str]] = set()
        for i in range(len(visible_active)):
            for j in range(i + 1, len(visible_active)):
                ba = visible_active[i]
                bb = visible_active[j]
                if ba.ball_type != bb.ball_type:
                    continue
                sim = self._compute_similarity(ba, bb)
                if sim < 0.70:
                    continue
                # 保留版本更高 / 被引用更多 / 标签更全的一方为主模块
                score_a = (ba.version, usage_counts.get(ba.ball_id, 0), len(ba.content))
                score_b = (bb.version, usage_counts.get(bb.ball_id, 0), len(bb.content))
                keep_ball, drop_ball = (ba, bb) if score_a >= score_b else (bb, ba)
                pair_key = tuple(sorted((ba.ball_id, bb.ball_id)))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)  # type: ignore[arg-type]
                reaper_candidates.append(
                    {
                        "candidate_id": f"DUP_{drop_ball.ball_id}",
                        "kind": "DUPLICATE_SIMILAR",
                        "kind_label": "重复/高度相似模块",
                        "similarity": sim,
                        "target_ball_id": drop_ball.ball_id,
                        "target_title": drop_ball.title,
                        "merge_into_ball_id": keep_ball.ball_id,
                        "merge_into_title": keep_ball.title,
                        "business_category": classify_capability_category(drop_ball),
                        "type_label": TYPE_LABELS.get(drop_ball.ball_type, "业务资料"),
                        "summary": (
                            f"《{drop_ball.title}》与《{keep_ball.title}》相似度达 {sim * 100:.0f}%，"
                            f"建议合并保留《{keep_ball.title}》并下线冗余项"
                        ),
                    }
                )

        # 2. 扫描已过期临时借用租约（在清理前先读取原始容器）
        now_dt = datetime.now(timezone.utc)
        for slot in self._containers._slots.values():
            for lease in slot.borrowed_balls:
                leased_ball = self._particles.get_ball(lease.ball_id)
                if leased_ball is not None and not _can_inspect(leased_ball):
                    continue
                try:
                    if _parse_iso_utc(lease.expires_at) <= now_dt:
                        reaper_candidates.append(
                            {
                                "candidate_id": f"EXP_{slot.slot_id}_{lease.ball_id}",
                                "kind": "EXPIRED_LEASE",
                                "kind_label": "已过期临时授权",
                                "target_ball_id": lease.ball_id,
                                "target_slot_id": slot.slot_id,
                                "target_title": lease.ball_id,
                                "summary": f"岗位 {slot.slot_name} 的临时权限 [{lease.ball_id}] 已过期，等待回收",
                            }
                        )
                except Exception:
                    pass

        # 3. 扫描高挂载臃肿岗位上的长期零使用闲置模块
        dup_drop_ids = {
            c["target_ball_id"]
            for c in reaper_candidates
            if c["kind"] == "DUPLICATE_SIMILAR"
        }
        for slot in self._containers.list_slots():
            eff_ids = self._containers.get_effective_ball_ids(slot.slot_id)
            if len(eff_ids) < 5:
                continue
            for bid in sorted(eff_ids):
                if bid in dup_drop_ids:
                    continue
                b = self._particles.get_ball(bid)
                if b is None or b.status != "ACTIVE" or b.ball_type == "REDLINE":
                    continue
                if not _can_inspect(b):
                    continue
                if usage_counts.get(bid, 0) == 0:
                    reaper_candidates.append(
                        {
                            "candidate_id": f"IDLE_{slot.slot_id}_{bid}",
                            "kind": "BLOATED_SLOT_IDLE",
                            "kind_label": "高负载岗位闲置模块",
                            "target_ball_id": bid,
                            "target_title": b.title,
                            "target_slot_id": slot.slot_id,
                            "target_slot_name": slot.slot_name,
                            "business_category": classify_capability_category(b),
                            "type_label": TYPE_LABELS.get(b.ball_type, "业务资料"),
                            "summary": (
                                f"岗位「{slot.slot_name}」已挂载 {len(eff_ids)} 项能力，"
                                f"《{b.title}》近期使用次数为 0，可考虑解绑或下线减负"
                            ),
                        }
                    )

        # 4. 接生婆健康扫描：臃肿待拆分模块 & 未工具化的公式资料模块
        skill_tags_set = {
            tag for b in active_balls if b.ball_type == "SKILL" for tag in b.domain_tags
        }
        for b in visible_active:
            if len(b.content.strip()) > 95:
                midwife_candidates.append(
                    {
                        "candidate_id": f"SPLIT_{b.ball_id}",
                        "kind": "SPLIT_BLOATED",
                        "kind_label": "职责过重建议拆分",
                        "target_ball_id": b.ball_id,
                        "target_title": b.title,
                        "business_category": classify_capability_category(b),
                        "type_label": TYPE_LABELS.get(b.ball_type, "业务资料"),
                        "summary": f"《{b.title}》说明较长（{len(b.content)} 字），建议一分为二拆成单一职责子模块",
                    }
                )
            if (
                b.ball_type == "DATA"
                and any(kw in b.content for kw in _FORMULA_HINT_KEYWORDS)
                and not (set(b.domain_tags) & skill_tags_set)
            ):
                midwife_candidates.append(
                    {
                        "candidate_id": f"FORGE_{b.ball_id}",
                        "kind": "FORGE_TOOL",
                        "kind_label": "可升级为自动计算工具",
                        "target_ball_id": b.ball_id,
                        "target_title": b.title,
                        "business_category": classify_capability_category(b),
                        "type_label": "业务资料",
                        "raw_policy_text": f"{b.title}：{b.content}",
                        "summary": f"《{b.title}》包含计算规则但尚无配套计算工具，建议一键孵化自动算子",
                    }
                )

        if prof.role_view != "boss":
            for candidate in midwife_candidates:
                candidate.pop("raw_policy_text", None)

        return {
            "user_id": user_id,
            "active_count": len(visible_active),
            "reaper_candidates": reaper_candidates,
            "midwife_candidates": midwife_candidates,
            "reaper_count": len(reaper_candidates),
            "midwife_count": len(midwife_candidates),
        }

    async def reap_module(
        self,
        actor_user_id: str,
        action: Literal["ARCHIVE", "MERGE"],
        target_ball_id: str,
        merge_into_ball_id: Optional[str] = None,
        reason: str = "",
    ) -> dict[str, Any]:
        target_ball = self._particles.get_ball(target_ball_id)
        if target_ball is None:
            raise KeyError(f"未找到待清理的能力模块: {target_ball_id}")

        actor_prof = self._ensure_manage_permission(actor_user_id, target_ball_id)

        affected_slots: list[str] = []
        if action == "ARCHIVE":
            if target_ball.status == "DEPRECATED":
                return {
                    "ok": True,
                    "action": "ARCHIVE",
                    "target_ball_id": target_ball_id,
                    "affected_slots": [],
                    "archived_ball": target_ball.model_dump(),
                    "worm_event": None,
                    "idempotent": True,
                    "summary": f"《{target_ball.title}》已经归档，无需重复操作",
                }
            updated_target = target_ball.model_copy(
                update={"status": "DEPRECATED", "version": target_ball.version + 1}
            )
            self._particles.register_ball(updated_target, record_to_vault=False)
            for slot in self._containers.list_slots():
                changed = False
                if target_ball_id in slot.ball_ids:
                    slot.ball_ids = [
                        bid for bid in slot.ball_ids if bid != target_ball_id
                    ]
                    changed = True
                before_len = len(slot.borrowed_balls)
                slot.borrowed_balls = [
                    l for l in slot.borrowed_balls if l.ball_id != target_ball_id
                ]
                if len(slot.borrowed_balls) != before_len:
                    changed = True
                if changed:
                    affected_slots.append(slot.slot_id)

            worm_rec = self._vault.append_event(
                event_kind="MODULE_REAPED_ARCHIVED",
                subtree_root_id="root",
                actor_slot_id=actor_prof.slot_id,
                payload={
                    "actor_user_id": actor_user_id,
                    "target_ball_id": target_ball_id,
                    "target_title": target_ball.title,
                    "previous_status": target_ball.status,
                    "affected_slots": affected_slots,
                    "reason": reason or "手动淘汰下线归档",
                },
            )
            await self._pulse.publish(
                event_type="BALL_MINTED",
                node_id="node_board_root",
                subtree_root_id="root",
                severity="INFO",
                summary=f"能力模块《{target_ball.title}》已淘汰归档，并从 {len(affected_slots)} 个岗位解绑",
                payload={"target_ball_id": target_ball_id, "action": "ARCHIVE"},
            )
            return {
                "ok": True,
                "action": "ARCHIVE",
                "target_ball_id": target_ball_id,
                "affected_slots": affected_slots,
                "archived_ball": updated_target.model_dump(),
                "worm_event": worm_rec.model_dump(),
                "summary": f"已将《{target_ball.title}》淘汰归档，并自动从 {len(affected_slots)} 个岗位移除",
            }

        # action == "MERGE"
        if target_ball.status == "DEPRECATED":
            raise ValueError("已归档模块不能再次合并，请先完成授权恢复")
        if not merge_into_ball_id or merge_into_ball_id == target_ball_id:
            raise ValueError("执行合并去重时必须指定不同于目标的 merge_into_ball_id")
        keep_ball = self._particles.get_ball(merge_into_ball_id)
        if keep_ball is None:
            raise KeyError(f"未找到目标保留模块: {merge_into_ball_id}")

        self._ensure_manage_permission(actor_user_id, merge_into_ball_id)
        if keep_ball.status != "ACTIVE":
            raise PermissionError("候选模块须先独立审核发布，不能通过合并自动启用")
        if keep_ball.ball_type != target_ball.ball_type:
            raise ValueError("只能合并相同类型的能力模块")

        merged_tags = list(
            dict.fromkeys([*keep_ball.domain_tags, *target_ball.domain_tags])
        )
        merged_owners = list(
            dict.fromkeys([*keep_ball.owner_slot_ids, *target_ball.owner_slot_ids])
        )
        upgraded_keep = keep_ball.model_copy(
            update={
                "domain_tags": merged_tags,
                "owner_slot_ids": merged_owners,
                "version": keep_ball.version + 1,
                "status": "ACTIVE",
            }
        )
        deprecated_target = target_ball.model_copy(
            update={"status": "DEPRECATED", "version": target_ball.version + 1}
        )
        self._particles.register_ball(upgraded_keep, record_to_vault=False)
        self._particles.register_ball(deprecated_target, record_to_vault=False)

        for slot in self._containers.list_slots():
            had_target = target_ball_id in slot.ball_ids
            had_borrowed = any(l.ball_id == target_ball_id for l in slot.borrowed_balls)
            if had_target or had_borrowed:
                slot.ball_ids = [bid for bid in slot.ball_ids if bid != target_ball_id]
                slot.borrowed_balls = [
                    l for l in slot.borrowed_balls if l.ball_id != target_ball_id
                ]
                if had_target and merge_into_ball_id not in slot.ball_ids:
                    slot.ball_ids.append(merge_into_ball_id)
                affected_slots.append(slot.slot_id)

        worm_rec = self._vault.append_event(
            event_kind="MODULE_REAPED_MERGED",
            subtree_root_id="root",
            actor_slot_id=actor_prof.slot_id,
            payload={
                "actor_user_id": actor_user_id,
                "target_ball_id": target_ball_id,
                "merge_into_ball_id": merge_into_ball_id,
                "previous_status": target_ball.status,
                "affected_slots": affected_slots,
                "reason": reason or "合并重复模块并保留主版本",
            },
        )
        await self._pulse.publish(
            event_type="BALL_MINTED",
            node_id="node_board_root",
            subtree_root_id="root",
            severity="SUCCESS",
            summary=(
                f"重复模块《{target_ball.title}》已合并至《{upgraded_keep.title} (v{upgraded_keep.version})》，"
                f"同步迁移 {len(affected_slots)} 个岗位"
            ),
            payload={
                "target_ball_id": target_ball_id,
                "merge_into_ball_id": merge_into_ball_id,
                "action": "MERGE",
            },
        )
        return {
            "ok": True,
            "action": "MERGE",
            "target_ball_id": target_ball_id,
            "merge_into_ball_id": merge_into_ball_id,
            "affected_slots": affected_slots,
            "kept_ball": upgraded_keep.model_dump(),
            "archived_ball": deprecated_target.model_dump(),
            "worm_event": worm_rec.model_dump(),
            "summary": (
                f"已将《{target_ball.title}》合并到《{upgraded_keep.title}》，"
                f"原冗余模块已归档，相关岗位已无缝迁移"
            ),
        }

    async def auto_reap_sweep(self, actor_user_id: str) -> dict[str, Any]:
        prof = self._containers.get_profile(actor_user_id)
        if prof.role_view not in ("leader", "manager", "boss"):
            raise PermissionError("仅主管或管理层可执行一键全局清理")

        # 1. 触发全岗位过期借用清理
        purged_leases = 0
        for sid in list(self._containers._slots.keys()):
            before = len(self._containers._slots[sid].borrowed_balls)
            self._containers._purge_expired_leases(sid)
            after = len(self._containers._slots[sid].borrowed_balls)
            purged_leases += max(0, before - after)

        # 2. 自动合并高相似度重复项 (>= 0.82)
        scan = self.scan_lifecycle_health(actor_user_id)
        merged_items: list[dict[str, Any]] = []
        dropped_already: set[str] = set()
        for cand in scan["reaper_candidates"]:
            if cand.get("kind") != "DUPLICATE_SIMILAR":
                continue
            if float(cand.get("similarity", 0.0)) < 0.82:
                continue
            drop_id = str(cand["target_ball_id"])
            keep_id = str(cand["merge_into_ball_id"])
            if drop_id in dropped_already or keep_id in dropped_already:
                continue
            try:
                res = await self.reap_module(
                    actor_user_id=actor_user_id,
                    action="MERGE",
                    target_ball_id=drop_id,
                    merge_into_ball_id=keep_id,
                    reason="一键自动合并高相似度重复模块",
                )
                merged_items.append(res)
                dropped_already.add(drop_id)
            except PermissionError:
                continue

        return {
            "ok": True,
            "purged_expired_leases": purged_leases,
            "merged_duplicates_count": len(merged_items),
            "merged_items": merged_items,
            "summary": (
                f"清理完成：回收过期授权 {purged_leases} 条，"
                f"自动合并高度重复模块 {len(merged_items)} 组"
            ),
        }

    async def restore_module(
        self,
        actor_user_id: str,
        ball_id: str,
        target_slot_id: Optional[str] = None,
    ) -> dict[str, Any]:
        ball = self._particles.get_ball(ball_id)
        if ball is None:
            raise KeyError(f"未找到待恢复的能力模块: {ball_id}")
        actor_prof = self._ensure_manage_permission(actor_user_id, ball_id)

        if ball.status == "CANDIDATE":
            raise PermissionError("候选模块须通过独立审核，不能以恢复操作代替发布")
        if ball.status == "DEPRECATED":
            for record in reversed(self._vault.read_records()):
                payload = record.payload
                if (
                    record.event_kind
                    in ("MODULE_REAPED_ARCHIVED", "MODULE_REAPED_MERGED")
                    and payload.get("target_ball_id") == ball_id
                ):
                    # Older versions appended events for repeated no-op archives.
                    # Follow the immutable history to the actual state transition.
                    if payload.get("previous_status") == "DEPRECATED":
                        continue
                    if payload.get("previous_status") != "ACTIVE":
                        raise PermissionError(
                            "未验证候选的归档记录不能作为恢复启用的依据"
                        )
                    break
                if (
                    record.event_kind == "BALL_MITOSIS_COMPLETED"
                    and payload.get("parent_ball_id") == ball_id
                ):
                    if payload.get("previous_parent_status") != "ACTIVE":
                        raise PermissionError("缺少原模块已经启用的可信证据")
                    break
            else:
                raise PermissionError("缺少原模块已经启用的可信归档证据，请重新审核")

        auth_svc = self._get_auth_custody()
        if target_slot_id:
            requested_slots = [self._containers.get_slot(target_slot_id).slot_id]
        else:
            valid_slots = {slot.slot_id for slot in self._containers.list_slots()}
            requested_slots = [
                slot_id for slot_id in ball.owner_slot_ids if slot_id in valid_slots
            ]
            if not requested_slots:
                requested_slots = [actor_prof.slot_id]
        for slot_id in requested_slots:
            if hasattr(auth_svc, "assert_can_manage_target_slot"):
                auth_svc.assert_can_manage_target_slot(actor_user_id, slot_id)
            elif actor_prof.role_view != "boss":
                raise PermissionError("缺少目标岗位管理权校验，不能恢复挂载")

        restored = ball.model_copy(
            update={"status": "ACTIVE", "version": ball.version + 1}
        )
        self._particles.register_ball(restored, record_to_vault=False)
        mounted_slots = []
        for slot_id in requested_slots:
            self._containers.attach_ball_to_slot(slot_id, ball_id)
            mounted_slots.append(slot_id)

        worm_rec = self._vault.append_event(
            event_kind="MODULE_RESTORED",
            subtree_root_id="root",
            actor_slot_id=actor_prof.slot_id,
            payload={
                "actor_user_id": actor_user_id,
                "ball_id": ball_id,
                "mounted_slots": mounted_slots,
            },
        )
        return {
            "ok": True,
            "restored_ball": restored.model_dump(),
            "mounted_slots": mounted_slots,
            "worm_event": worm_rec.model_dump(),
            "summary": f"已恢复启用《{restored.title}》，并挂载至 {len(mounted_slots)} 个岗位",
        }

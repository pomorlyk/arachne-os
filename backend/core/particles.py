from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Optional
import uuid

import numpy as np

from core.blackbox_vault import BlackBoxVault
from core.schemas import CapabilityBall, ExtractedBallCandidate, PublicCapabilityBallView


def _char_ngram_vector(text: str, dim: int = 256) -> np.ndarray:
    """
    本地零外部依赖轻量向量编码器（基于字符级 bi-gram / uni-gram 哈希投影 + L2 归一化），
    用于在内存中执行毫秒级 numpy 余弦相似度检索。
    """
    vec = np.zeros(dim, dtype=np.float32)
    cleaned = text.strip().lower()
    if not cleaned:
        return vec
    for idx, ch in enumerate(cleaned):
        h1 = hash(ch) % dim
        vec[h1] += 1.0
        if idx + 1 < len(cleaned):
            bg = cleaned[idx : idx + 2]
            h2 = hash(bg) % dim
            vec[h2] += 1.5
    norm = float(np.linalg.norm(vec))
    if norm > 1e-8:
        vec /= norm
    return vec


class ParticleEngine:
    """
    权能小球引擎：负责四类原子小球（DATA / SKILL / AUTHORITY / REDLINE）的注册、
    numpy 向量语义检索、容器级权限隔离校验、红线拦截触发及标签共现聚类。
    """

    def __init__(self, vault: BlackBoxVault) -> None:
        self._vault = vault
        self._balls: dict[str, CapabilityBall] = {}
        self._vectors: dict[str, np.ndarray] = {}
        self._role_resolver: Optional[Callable[[str], Optional[str]]] = None

    def bind_role_resolver(self, resolver: Callable[[str], Optional[str]]) -> None:
        """Bind trusted, current container roles; ownership alone cannot authorize secrets."""
        self._role_resolver = resolver

    def _can_read_redline(
        self, slot_id: str, ball: CapabilityBall, effective_ball_ids: set[str]
    ) -> bool:
        if self._role_resolver is None:
            return False
        try:
            role = self._role_resolver(slot_id)
        except (KeyError, ValueError):
            return False
        return role == "boss" and (
            slot_id in ball.owner_slot_ids or ball.ball_id in effective_ball_ids
        )

    def register_ball(self, ball: CapabilityBall, record_to_vault: bool = False) -> CapabilityBall:
        self._balls[ball.ball_id] = ball
        index_text = f"{ball.title} {' '.join(ball.domain_tags)} {ball.content}"
        self._vectors[ball.ball_id] = _char_ngram_vector(index_text)
        if record_to_vault:
            self._vault.append_event(
                event_kind="BALL_MINTED",
                subtree_root_id="root",
                actor_slot_id=ball.owner_slot_ids[0] if ball.owner_slot_ids else "SLOT_SYS",
                payload={
                    "ball_id": ball.ball_id,
                    "ball_type": ball.ball_type,
                    "title": ball.title,
                    "domain_tags": ball.domain_tags,
                    "status": ball.status,
                },
            )
        return ball

    def mint_from_candidate(
        self,
        candidate: ExtractedBallCandidate,
        owner_slot_ids: list[str],
        status: str = "ACTIVE",
        executable_code_path: Optional[str] = None,
    ) -> CapabilityBall:
        short_id = uuid.uuid4().hex[:8].upper()
        ball = CapabilityBall(
            ball_id=f"BALL_{candidate.ball_type}_{short_id}",
            ball_type=candidate.ball_type,
            title=candidate.title,
            domain_tags=candidate.domain_tags,
            sensitivity_level=candidate.sensitivity_level,
            owner_slot_ids=owner_slot_ids,
            content=candidate.content,
            executable_code_path=executable_code_path,
            status=status,  # type: ignore[arg-type]
        )
        return self.register_ball(ball, record_to_vault=True)

    def promote_ball(self, ball_id: str, actor_slot_id: str) -> CapabilityBall:
        ball = self._balls[ball_id]
        updated = ball.model_copy(update={"status": "ACTIVE", "version": ball.version + 1})
        self._balls[ball_id] = updated
        self._vault.append_event(
            event_kind="BALL_PROMOTED",
            subtree_root_id="root",
            actor_slot_id=actor_slot_id,
            payload={"ball_id": ball_id, "version": updated.version},
        )
        return updated

    def get_ball(self, ball_id: str) -> Optional[CapabilityBall]:
        return self._balls.get(ball_id)

    def list_all_balls(self) -> list[CapabilityBall]:
        return list(self._balls.values())

    def list_redline_balls(self) -> list[CapabilityBall]:
        return [
            b
            for b in self._balls.values()
            if b.ball_type == "REDLINE" and b.status == "ACTIVE"
        ]

    def get_accessible_balls(
        self, slot_id: str, effective_ball_ids: set[str]
    ) -> list[CapabilityBall]:
        """
        返回指定岗位容器合法可读取的 ACTIVE 小球列表。
        REDLINE 必须同时满足可信老板角色和持有授权；历史误挂载或借球不能绕过角色边界。
        """
        accessible: list[CapabilityBall] = []
        for ball in self._balls.values():
            if ball.status != "ACTIVE":
                continue
            if ball.ball_type == "REDLINE" and not self._can_read_redline(
                slot_id, ball, effective_ball_ids
            ):
                continue
            if ball.ball_id in effective_ball_ids or slot_id in ball.owner_slot_ids:
                accessible.append(ball)
        return accessible

    def project_public_balls(
        self, slot_id: str, effective_ball_ids: set[str]
    ) -> list[PublicCapabilityBallView]:
        raw_balls = self.get_accessible_balls(slot_id, effective_ball_ids)
        return [
            PublicCapabilityBallView(
                ball_id=b.ball_id,
                ball_type=b.ball_type,
                title=b.title,
                domain_tags=b.domain_tags,
                sensitivity_level=b.sensitivity_level,
                content=b.content,
                version=b.version,
                status=b.status,
            )
            for b in raw_balls
        ]

    def check_redline_violation(
        self, slot_id: str, effective_ball_ids: set[str], query_text: str
    ) -> Optional[CapabilityBall]:
        """
        检查查询是否触碰当前容器无权访问的 REDLINE 红线球（如普通跟单员刺探工厂拿货底价）。
        """
        for r_ball in self.list_redline_balls():
            # Only a trusted boss role with a grant may bypass the guard.
            if self._can_read_redline(slot_id, r_ball, effective_ball_ids):
                continue
            for kw in r_ball.redline_keywords:
                if kw and kw in query_text:
                    return r_ball
        return None

    def semantic_search(
        self,
        query: str,
        slot_id: str,
        effective_ball_ids: set[str],
        top_k: int = 4,
    ) -> list[CapabilityBall]:
        candidates = self.get_accessible_balls(slot_id, effective_ball_ids)
        if not candidates:
            return []
        q_vec = _char_ngram_vector(query)
        scored: list[tuple[float, CapabilityBall]] = []
        for b in candidates:
            b_vec = self._vectors.get(b.ball_id)
            score = float(np.dot(q_vec, b_vec)) if b_vec is not None else 0.0
            if any(tag in query for tag in b.domain_tags):
                score += 0.35
            scored.append((score, b))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:top_k]]

    def cluster_domain_aspects(self, min_cooccurrence: int = 2) -> list[dict[str, object]]:
        """
        基于活跃权能小球 domain_tags 共现矩阵进行连通簇发现，用于蛛网横向自动开辟业务域 (Aspect)。
        """
        tag_freq: dict[str, int] = defaultdict(int)
        pair_counts: dict[tuple[str, str], int] = defaultdict(int)

        for ball in self._balls.values():
            if ball.status != "ACTIVE":
                continue
            unique_tags = sorted(set(ball.domain_tags))
            for t in unique_tags:
                tag_freq[t] += 1
            for i in range(len(unique_tags)):
                for j in range(i + 1, len(unique_tags)):
                    pair_counts[(unique_tags[i], unique_tags[j])] += 1

        adj: dict[str, set[str]] = {t: set() for t in tag_freq}
        for (t1, t2), cnt in pair_counts.items():
            if cnt >= min_cooccurrence:
                adj[t1].add(t2)
                adj[t2].add(t1)

        visited: set[str] = set()
        clusters: list[dict[str, object]] = []
        for tag in sorted(tag_freq.keys()):
            if tag in visited:
                continue
            comp: list[str] = []
            queue = [tag]
            visited.add(tag)
            while queue:
                curr = queue.pop(0)
                comp.append(curr)
                for nxt in sorted(adj[curr]):
                    if nxt not in visited:
                        visited.add(nxt)
                        queue.append(nxt)
            total_weight = sum(tag_freq[t] for t in comp)
            if len(comp) >= 2 or total_weight >= 2:
                aspect_key = "_".join(comp[:2])
                clusters.append(
                    {
                        "aspect_id": f"ASPECT_{aspect_key}",
                        "aspect_title": f"【{'/'.join(comp[:3])}】业务域",
                        "tags": comp,
                        "ball_density": total_weight,
                    }
                )
        return clusters

    def export_balls_with_source(self, sandbox_dir: Path) -> list[dict[str, Any]]:
        """导出全量权能球及沙箱脚本源码，供 SQLite 持久化跨重启无损重建。"""
        exported: list[dict[str, Any]] = []
        for b in self._balls.values():
            source_code = ""
            if b.executable_code_path:
                script_p = Path(b.executable_code_path)
                if not script_p.is_absolute():
                    script_p = Path(sandbox_dir) / script_p
                if script_p.exists():
                    try:
                        source_code = script_p.read_text(encoding="utf-8")
                    except Exception:
                        source_code = ""
            exported.append(
                {
                    "ball": b,
                    "executable_code_source": source_code,
                }
            )
        return exported

    def restore_balls_with_source(
        self, records: list[dict[str, Any]], sandbox_dir: Path
    ) -> None:
        """从持久化记录恢复全部权能球与向量索引，并在磁盘缺失时自动重建可执行脚本文件。"""
        self._balls.clear()
        self._vectors.clear()
        Path(sandbox_dir).mkdir(parents=True, exist_ok=True)
        for item in records:
            raw_ball = item.get("ball")
            ball = (
                raw_ball
                if isinstance(raw_ball, CapabilityBall)
                else CapabilityBall(**item)
            )
            source_code = str(
                item.get("executable_code_source")
                or item.get("source_code")
                or ""
            )
            if ball.executable_code_path and source_code:
                script_p = Path(ball.executable_code_path)
                if not script_p.is_absolute():
                    script_p = Path(sandbox_dir) / script_p
                if not script_p.exists():
                    script_p.parent.mkdir(parents=True, exist_ok=True)
                    script_p.write_text(source_code, encoding="utf-8")
            self.register_ball(ball, record_to_vault=False)


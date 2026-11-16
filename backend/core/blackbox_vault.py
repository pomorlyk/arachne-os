from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from core.schemas import ChainVerificationReport, VaultRecord, utc_now_iso

GENESIS_PREV_HASH = "0" * 64
_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_hex(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class BlackBoxVault:
    """
    WORM (Write-Once-Read-Many) 不可篡改链式黑匣子。
    铁律约束：
    1. 仅开放事件追加 (append_event / seal_snapshot / record_rollback_seal) 与只读校验接口；
    2. 物理与方法层面严禁实现任何修改、覆盖或删除历史账本记录的接口；
    3. 快照落盘后自动施加只读文件权限锁 (0o444)。
    """

    def __init__(self, storage_dir: Path) -> None:
        self._storage_dir = Path(storage_dir)
        self._snapshots_dir = self._storage_dir / "snapshots"
        self._ledger_path = self._storage_dir / "ledger.jsonl"
        self._checkpoint_path = self._storage_dir / "head-checkpoints.jsonl"
        self._lock_path = self._storage_dir / ".append.lock"
        with _PATH_LOCKS_GUARD:
            self._write_lock = _PATH_LOCKS.setdefault(str(self._storage_dir.resolve()), threading.RLock())
        self._local = threading.local()
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        if not self._ledger_path.exists():
            self._ledger_path.touch()

    @contextmanager
    def _serialized(self):
        """Serialize every writer across objects and OS processes; allow nested sealing."""
        with self._write_lock:
            if getattr(self._local, "depth", 0):
                self._local.depth += 1
                try:
                    yield
                finally:
                    self._local.depth -= 1
                return
            with self._lock_path.open("a+") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                self._local.depth = 1
                try:
                    yield
                finally:
                    self._local.depth = 0
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _append_checkpoint(self, seq: int, record_hash: str) -> None:
        # Append-only high-water marks expose removal of an otherwise valid suffix.
        with self._checkpoint_path.open("a", encoding="utf-8") as fh:
            fh.write(_canonical_json({"seq": seq, "record_hash": record_hash}) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    @property
    def ledger_path(self) -> Path:
        return self._ledger_path

    def _tail_state(self) -> tuple[int, str]:
        last_seq = 0
        last_hash = GENESIS_PREV_HASH
        with self._ledger_path.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                parsed = json.loads(line)
                last_seq = int(parsed["seq"])
                last_hash = str(parsed["record_hash"])
        return last_seq, last_hash

    def append_event(
        self,
        event_kind: str,
        subtree_root_id: str,
        actor_slot_id: str,
        payload: dict[str, Any],
    ) -> VaultRecord:
        with self._serialized():
            report = self.verify_chain_integrity()
            if not report.intact:
                raise ValueError(f"Refusing append to damaged ledger: {report.error_reason}")
            last_seq, prev_hash = report.total_records, report.head_hash
            next_seq = last_seq + 1
            timestamp = utc_now_iso()
            unsigned_body = {
                "seq": next_seq,
                "timestamp": timestamp,
                "event_kind": event_kind,
                "subtree_root_id": subtree_root_id,
                "actor_slot_id": actor_slot_id,
                "payload": payload,
                "prev_hash": prev_hash,
            }
            record_hash = _sha256_hex(_canonical_json(unsigned_body))
            signed_body = {**unsigned_body, "record_hash": record_hash}
            serialized = _canonical_json(signed_body) + "\n"
            with self._ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(serialized)
                fh.flush()
                os.fsync(fh.fileno())
            self._append_checkpoint(next_seq, record_hash)
            return VaultRecord(**signed_body)

    def seal_snapshot(
        self,
        subtree_root_id: str,
        actor_slot_id: str,
        state_dict: dict[str, Any],
        scope: LiteralScope = "LOCAL",
    ) -> str:
        with self._serialized():
            canonical_state = _canonical_json(
                {
                    "scope": scope,
                    "subtree_root_id": subtree_root_id,
                    "state": state_dict,
                }
            )
            snapshot_hash = _sha256_hex(canonical_state)
            snap_file = self._snapshots_dir / f"{snapshot_hash}.json"
            if not snap_file.exists():
                snap_file.write_text(canonical_state, encoding="utf-8")
                os.chmod(snap_file, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

            event_kind = "GLOBAL_SNAPSHOT_SEALED" if scope == "GLOBAL" else "SNAPSHOT_SEALED"
            self.append_event(
                event_kind=event_kind,
                subtree_root_id=subtree_root_id,
                actor_slot_id=actor_slot_id,
                payload={
                    "scope": scope,
                    "snapshot_hash": snapshot_hash,
                },
            )
            return snapshot_hash

    def record_rollback_seal(
        self,
        subtree_root_id: str,
        actor_slot_id: str,
        target_snapshot_hash: str,
        reason: str,
        scope: str = "LOCAL",
    ) -> VaultRecord:
        with self._serialized():
            # 校验目标快照真实存在且哈希一致
            _ = self.validate_snapshot(target_snapshot_hash, subtree_root_id=subtree_root_id, scope=scope)
            return self.append_event(
                event_kind="ROLLBACK_SEAL",
                subtree_root_id=subtree_root_id,
                actor_slot_id=actor_slot_id,
                payload={
                    "scope": scope,
                    "target_snapshot_hash": target_snapshot_hash,
                    "reason": reason,
                },
            )

    def read_snapshot_envelope(self, snapshot_hash: str) -> dict[str, Any]:
        if len(snapshot_hash) != 64 or any(c not in "0123456789abcdef" for c in snapshot_hash):
            raise ValueError("Invalid sealed snapshot hash")
        snap_file = self._snapshots_dir / f"{snapshot_hash}.json"
        raw = snap_file.read_text(encoding="utf-8")
        if _sha256_hex(raw) != snapshot_hash:
            raise ValueError(f"Snapshot integrity breach: {snapshot_hash}")
        envelope = json.loads(raw)
        if not isinstance(envelope.get("state"), dict):
            raise ValueError("Invalid sealed snapshot state")
        return envelope

    def read_snapshot(self, snapshot_hash: str) -> dict[str, Any]:
        return dict(self.read_snapshot_envelope(snapshot_hash)["state"])

    def validate_snapshot(self, snapshot_hash: str, *, subtree_root_id: str, scope: str) -> dict[str, Any]:
        report = self.verify_chain_integrity()
        if not report.intact:
            raise ValueError(f"Damaged audit ledger: {report.error_reason}")
        envelope = self.read_snapshot_envelope(snapshot_hash)
        if envelope.get("scope") != scope or envelope.get("subtree_root_id") != subtree_root_id:
            raise ValueError("Snapshot scope/subtree does not match rollback target")
        kind = "GLOBAL_SNAPSHOT_SEALED" if scope == "GLOBAL" else "SNAPSHOT_SEALED"
        if not any(r.payload.get("snapshot_hash") == snapshot_hash for r in self.read_records(event_kind=kind, subtree_root_id=subtree_root_id)):
            raise ValueError("Snapshot has no matching seal")
        return dict(envelope["state"])

    def get_latest_snapshot_hash(
        self, subtree_root_id: str, scope: str = "LOCAL"
    ) -> Optional[str]:
        expected_kind = "GLOBAL_SNAPSHOT_SEALED" if scope == "GLOBAL" else "SNAPSHOT_SEALED"
        records = self.read_records(event_kind=expected_kind)
        for rec in reversed(records):
            if scope == "GLOBAL" or rec.subtree_root_id == subtree_root_id:
                return str(rec.payload["snapshot_hash"])
        return None

    def read_records(
        self,
        event_kind: Optional[str] = None,
        subtree_root_id: Optional[str] = None,
    ) -> list[VaultRecord]:
        with self._serialized():
            results: list[VaultRecord] = []
            with self._ledger_path.open("r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    rec = VaultRecord(**data)
                    if event_kind and rec.event_kind != event_kind:
                        continue
                    if subtree_root_id and rec.subtree_root_id != subtree_root_id:
                        continue
                    results.append(rec)
            return results

    def list_golden_benchmarks(self, domain_tag: Optional[str] = None) -> list[dict[str, Any]]:
        records = self.read_records(event_kind="GOLDEN_BENCHMARK_SEALED")
        samples: list[dict[str, Any]] = []
        for rec in records:
            tags = rec.payload.get("domain_tags", [])
            if domain_tag is None or domain_tag in tags:
                samples.append(rec.payload)
        return samples

    def verify_chain_integrity(self) -> ChainVerificationReport:
        with self._serialized():
            expected_prev_hash = GENESIS_PREV_HASH
            expected_seq = 0
            hashes: dict[int, str] = {0: GENESIS_PREV_HASH}
            with self._ledger_path.open("r", encoding="utf-8") as fh:
                for line_idx, raw_line in enumerate(fh, start=1):
                    line = raw_line.strip()
                    if not line:
                        continue
                    expected_seq += 1
                    try:
                        parsed = json.loads(line)
                    except json.JSONDecodeError as exc:
                        return ChainVerificationReport(
                            intact=False,
                            total_records=expected_seq - 1,
                            head_hash=expected_prev_hash,
                            broken_at_seq=expected_seq,
                            error_reason=f"Malformed JSON at line {line_idx}: {exc}",
                        )

                    actual_seq = parsed.get("seq")
                    if actual_seq != expected_seq:
                        return ChainVerificationReport(
                            intact=False,
                            total_records=expected_seq - 1,
                            head_hash=expected_prev_hash,
                            broken_at_seq=expected_seq,
                            error_reason=f"Sequence gap: expected seq={expected_seq}, got {actual_seq}",
                        )

                    if parsed.get("prev_hash") != expected_prev_hash:
                        return ChainVerificationReport(
                            intact=False,
                            total_records=expected_seq - 1,
                            head_hash=expected_prev_hash,
                            broken_at_seq=expected_seq,
                            error_reason=f"Broken prev_hash link at seq={expected_seq}",
                        )

                    recorded_hash = parsed.get("record_hash", "")
                    unsigned_copy = {k: v for k, v in parsed.items() if k != "record_hash"}
                    recomputed_hash = _sha256_hex(_canonical_json(unsigned_copy))
                    if recomputed_hash != recorded_hash:
                        return ChainVerificationReport(
                            intact=False,
                            total_records=expected_seq - 1,
                            head_hash=expected_prev_hash,
                            broken_at_seq=expected_seq,
                            error_reason=f"Tampered payload or hash mismatch at seq={expected_seq}",
                        )

                    expected_prev_hash = recorded_hash
                    hashes[expected_seq] = recorded_hash
                    if parsed.get("event_kind") in {"SNAPSHOT_SEALED", "GLOBAL_SNAPSHOT_SEALED"}:
                        try:
                            envelope = self.read_snapshot_envelope(parsed["payload"]["snapshot_hash"])
                            wanted_scope = "GLOBAL" if parsed["event_kind"] == "GLOBAL_SNAPSHOT_SEALED" else "LOCAL"
                            if envelope.get("scope") != wanted_scope or envelope.get("subtree_root_id") != parsed.get("subtree_root_id"):
                                raise ValueError("Snapshot seal scope mismatch")
                        except (OSError, ValueError, KeyError) as exc:
                            return ChainVerificationReport(intact=False, total_records=expected_seq, head_hash=expected_prev_hash, broken_at_seq=expected_seq, error_reason=f"Invalid referenced snapshot: {exc}")

            if self._checkpoint_path.exists():
                try:
                    for raw in self._checkpoint_path.read_text(encoding="utf-8").splitlines():
                        checkpoint = json.loads(raw)
                        if hashes.get(int(checkpoint["seq"])) != checkpoint["record_hash"]:
                            raise ValueError("Ledger truncated or checkpoint head changed")
                except (ValueError, KeyError, TypeError) as exc:
                    return ChainVerificationReport(intact=False, total_records=expected_seq, head_hash=expected_prev_hash, broken_at_seq=expected_seq + 1, error_reason=str(exc))
            return ChainVerificationReport(
                intact=True,
                total_records=expected_seq,
                head_hash=expected_prev_hash,
                broken_at_seq=None,
                error_reason="",
            )


LiteralScope = str


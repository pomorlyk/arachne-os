from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

PBKDF2_PREFIX = "pbkdf2_sha256$"
_PBKDF2_ITERATIONS = 120_000


def hash_password(plain_or_hashed: str) -> str:
    """使用 PBKDF2-SHA256 (120,000 次迭代 + 16 字节随机盐) 对密码做单向加盐哈希。"""
    raw = str(plain_or_hashed or "")
    if raw.startswith(PBKDF2_PREFIX):
        return raw
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{PBKDF2_PREFIX}{_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    """校验明文密码是否匹配 PBKDF2-SHA256 哈希串（同时平滑兼容历史明文记录）。"""
    raw_stored = str(stored or "")
    if not raw_stored:
        return False
    if raw_stored.startswith(PBKDF2_PREFIX):
        try:
            _, iter_s, salt_hex, dk_hex = raw_stored.split("$", 3)
            iterations = int(iter_s)
            salt = bytes.fromhex(salt_hex)
            expected_dk = bytes.fromhex(dk_hex)
        except Exception:
            return False
        actual_dk = hashlib.pbkdf2_hmac(
            "sha256", plain.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(actual_dk, expected_dk)
    return hmac.compare_digest(plain, raw_stored)

from core.blackbox_vault import BlackBoxVault
from core.containers import ContainerRegistry
from core.particles import ParticleEngine
from core.schemas import DualEmployeeProfile, RoleViewType, UnitSlot, utc_now_iso


class AccountDirectoryEntry(BaseModel):
    user_id: str
    username: str
    name: str
    title: str
    department: str
    role_view: RoleViewType
    slot_id: str
    supervisor_id: Optional[str] = None
    supervisor_name: Optional[str] = None
    is_custodian_leader: bool = False
    mounted_ball_count: int = 0
    has_password: bool = True
    is_disabled: bool = False


class BallAccessRequestItem(BaseModel):
    request_id: str
    requester_id: str
    requester_name: str
    requester_slot_id: str
    ball_id: str
    ball_title: str
    ball_type: str
    grant_mode: Literal["LEASE_TTL", "PERMANENT"] = "LEASE_TTL"
    ttl_minutes: int = 120
    reason: str
    custodian_id: str
    custodian_name: str
    status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    decision_comment: str = ""
    created_at: str = Field(default_factory=utc_now_iso)
    decided_at: Optional[str] = None


# 账号目录表（运行期由演示种子或矿洞探网动态填充，重启后从 SQLite 恢复）
ACCOUNT_DIRECTORY: dict[str, dict[str, Any]] = {}


def reset_account_directory(entries: dict[str, dict[str, Any]] | None = None) -> None:
    """清空并重置全局账号通讯录（供演示种子加载、空壳冷启动及持久化恢复调用）。"""
    ACCOUNT_DIRECTORY.clear()
    if entries:
        for uid, meta in entries.items():
            ACCOUNT_DIRECTORY[uid] = dict(meta)


class AuthAndCustodyService:
    """
    Zone 1 & Zone 2 核心引擎：
    1. 真实账号密码登录与 Bearer Token 隔离（每个人只看自己的工位容器与会话）；
    2. 技能球/权能球分级分管（按部门职责标签、直属主管链条与岗位角色动态归属分管人）；
    3. 员工申请额外球（临时借用 TTL / 常驻挂载）→ 分管负责人一键审批/派发/吊销收回。
    """

    def __init__(
        self,
        vault: BlackBoxVault,
        particles: ParticleEngine,
        containers: ContainerRegistry,
        settings: Any = None,
    ) -> None:
        self._vault = vault
        self._particles = particles
        self._containers = containers
        self.account_directory: dict[str, dict[str, Any]] = {}
        configured_password = str(getattr(settings, "bootstrap_password", "") or "")
        self._bootstrap_password = configured_password or (
            "123456" if settings is not None and not settings.enforce_bearer_auth else ""
        )
        self._passwords: dict[str, str] = {}
        self._sessions: dict[str, str] = {}  # token -> user_id
        self._requests: dict[str, BallAccessRequestItem] = {}
        self.sync_accounts_from_containers()

    def set_password(self, user_id: str, raw_or_hashed_password: str) -> None:
        if not str(raw_or_hashed_password or "").strip():
            raise ValueError("密码不能为空")
        self._containers.get_profile(user_id)
        self._passwords[user_id] = hash_password(raw_or_hashed_password)
        self.invalidate_sessions(user_id)

    def ensure_passwords_hashed(self) -> None:
        for uid in list(self._passwords.keys()):
            val = str(self._passwords[uid] or "")
            if not val.startswith(PBKDF2_PREFIX):
                self._passwords[uid] = hash_password(val)

    def sync_accounts_from_containers(self) -> None:
        """确保容器档案中的每个员工在目录与密码表中均已注册（用于动态/测试场景兜底）。"""
        slots_by_id = {s.slot_id: s for s in self._containers.list_slots()}
        profiles = self._containers.list_profiles()
        boss_uid = next((p.user_id for p in profiles if p.role_view == "boss"), None)
        mgr_uid = next((p.user_id for p in profiles if p.role_view == "manager"), boss_uid)
        for p in profiles:
            if (p.user_id not in self._passwords and self._bootstrap_password
                    and not self.account_directory.get(p.user_id, {}).get("_disabled")):
                self._passwords[p.user_id] = hash_password(self._bootstrap_password)
            if p.user_id not in self.account_directory:
                slot = slots_by_id.get(p.slot_id)
                dept = slot.department if slot else "通用业务部"
                sup = None
                if p.role_view != "boss":
                    dept_leader = next((other.user_id for other in profiles
                        if other.user_id != p.user_id and other.role_view == "leader"
                        and slots_by_id.get(other.slot_id) is not None
                        and slots_by_id[other.slot_id].department == dept), None)
                    sup = mgr_uid if p.role_view in ("leader", "manager", "blackbox", "finance_tool") else (dept_leader or mgr_uid)
                    if sup == p.user_id:
                        sup = boss_uid
                self.account_directory[p.user_id] = {
                    "department": dept,
                    "supervisor_id": sup,
                    "is_custodian_leader": p.role_view in ("boss", "manager", "leader"),
                }
        self.ensure_passwords_hashed()

    def export_persistence_payload(self) -> dict[str, Any]:
        self.sync_accounts_from_containers()
        self.ensure_passwords_hashed()
        return {
            "account_directory": {k: dict(v) for k, v in self.account_directory.items()},
            "passwords": dict(self._passwords),
            "custody_requests": [r.model_dump() for r in self._requests.values()],
            # Bearer tokens are runtime credentials and never workspace state.
            "sessions": {},
        }

    def restore_from_persistence(
        self,
        account_directory: dict[str, dict[str, Any]],
        passwords: dict[str, str],
        custody_requests: list[dict[str, Any]],
        sessions: dict[str, str] | None = None,
    ) -> None:
        active_ids = {p.user_id for p in self._containers.list_profiles()}
        self.account_directory = {
            uid: dict(meta) for uid, meta in account_directory.items() if uid in active_ids
        }
        self._passwords = {
            uid: hash_password(str(pw)) for uid, pw in passwords.items()
            if uid in active_ids and pw
        }
        self.sync_accounts_from_containers()
        self._requests = {}
        for raw_req in custody_requests:
            item = BallAccessRequestItem(**raw_req)
            if item.requester_id in active_ids and item.custodian_id in active_ids:
                self._requests[item.request_id] = item
        self.invalidate_sessions()

    def invalidate_sessions(self, user_id: str | None = None) -> None:
        if user_id is None:
            self._sessions.clear()
        else:
            self._sessions = {tok: uid for tok, uid in self._sessions.items() if uid != user_id}

    def reset_workspace_identity(
        self,
        account_directory: dict[str, dict[str, Any]] | None = None,
        *,
        preserve_password_user_ids: set[str] | None = None,
    ) -> None:
        """Revoke identity state; preserve explicitly selected active credentials only."""
        active_ids = {p.user_id for p in self._containers.list_profiles()}
        preserve = (preserve_password_user_ids or set()) & active_ids
        self._passwords = {uid: pw for uid, pw in self._passwords.items() if uid in preserve}
        self.invalidate_sessions()
        self._requests.clear()
        self.account_directory = {
            uid: dict(meta) for uid, meta in (account_directory or {}).items() if uid in active_ids
        }
        self.sync_accounts_from_containers()

    def restore_identity_metadata(self, account_directory: dict[str, dict[str, Any]]) -> None:
        """Restore business metadata without reviving revoked or unknown identities."""
        active_ids = {p.user_id for p in self._containers.list_profiles()}
        known = self.account_directory
        restored = {}
        for uid in active_ids:
            meta = dict(account_directory.get(uid, known.get(uid, {})))
            if uid not in known or known[uid].get("_disabled"):
                meta["_disabled"] = True
            restored[uid] = meta
        self.account_directory = restored
        self._passwords = {uid: pw for uid, pw in self._passwords.items() if uid in active_ids}
        self._requests = {
            rid: item for rid, item in self._requests.items()
            if item.requester_id in active_ids and item.custodian_id in active_ids
            and not restored[item.requester_id].get("_disabled")
            and not restored[item.custodian_id].get("_disabled")
        }
        self.invalidate_sessions()

    def provision_account_password(self, actor_user_id: str, user_id: str, new_password: str) -> dict[str, Any]:
        profile = self._containers.get_profile(user_id)
        self.assert_can_manage_target_slot(actor_user_id, profile.slot_id)
        self.set_password(user_id, new_password)
        self.account_directory.setdefault(user_id, {}).pop("_disabled", None)
        profile.title = profile.title.replace("（已离岗交接）", "")
        self._vault.append_event(
            event_kind="ACCOUNT_PASSWORD_PROVISIONED", subtree_root_id="root",
            actor_slot_id=self._containers.get_profile(actor_user_id).slot_id,
            payload={"user_id": user_id, "actor_user_id": actor_user_id},
        )
        return {"ok": True, "user_id": user_id}

    def list_public_accounts(self) -> list[AccountDirectoryEntry]:
        self.sync_accounts_from_containers()
        profiles = self._containers.list_profiles()
        name_by_uid = {p.user_id: p.name for p in profiles}
        entries: list[AccountDirectoryEntry] = []
        for prof in profiles:
            meta = self.account_directory.get(prof.user_id, {})
            sup_id = meta.get("supervisor_id")
            sup_name = name_by_uid.get(sup_id, "董事会") if sup_id else "董事会"
            try:
                mounted_count = len(self._containers.get_effective_ball_ids(prof.slot_id))
            except Exception:
                mounted_count = 0
            entries.append(
                AccountDirectoryEntry(
                    user_id=prof.user_id,
                    username=prof.user_id,
                    name=prof.name,
                    title=prof.title,
                    department=meta.get("department", "核心业务部"),
                    role_view=prof.role_view,
                    slot_id=prof.slot_id,
                    supervisor_id=sup_id,
                    supervisor_name=sup_name,
                    is_custodian_leader=bool(meta.get("is_custodian_leader", False)),
                    mounted_ball_count=mounted_count,
                    has_password=(prof.user_id in self._passwords),
                    is_disabled=bool(
                        meta.get("_disabled", False)
                        or "（已离岗交接）" in (prof.title or "")
                    ),
                )
            )
        return entries

    def login(self, username: str, password: str) -> dict[str, Any]:
        uid = username.strip()
        if self.account_directory.get(uid, {}).get("_disabled"):
            raise ValueError("该账号已完成离岗交接并停用，请联系管理员")
        prof = self._containers.get_profile(uid)
        if "（已离岗交接）" in (prof.title or ""):
            raise ValueError("该账号已完成离岗交接并停用，请联系管理员")
        expected_pw = self._passwords.get(uid)
        if expected_pw is None:
            raise ValueError("账号尚未配置密码，请由管理员配置 bootstrap_password 或单独设置账号密码")
        if not verify_password(password, expected_pw):
            raise ValueError("账号或密码错误")
        token = f"arachne_tok_{secrets.token_hex(12)}"
        self._sessions[token] = prof.user_id
        entry = next(
            (a for a in self.list_public_accounts() if a.user_id == prof.user_id),
            None,
        )
        return {
            "token": token,
            "account": entry.model_dump() if entry else {"user_id": prof.user_id},
        }

    def get_current_account(
        self,
        token: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        resolved_uid = self.resolve_token(token) if token else None
        uid = resolved_uid or (user_id or "").strip()
        if not uid:
            raise ValueError("未提供有效的登录凭证或 user_id")
        prof = self._containers.get_profile(uid)
        entry = next(
            (a for a in self.list_public_accounts() if a.user_id == prof.user_id),
            None,
        )
        if entry is None:
            raise KeyError(f"未找到账号条目: {uid}")
        data = entry.model_dump()
        return {
            **data,
            "account": data,
        }

    def change_password(
        self,
        user_id: str,
        old_password: str,
        new_password: str,
    ) -> dict[str, Any]:
        uid = user_id.strip()
        prof = self._containers.get_profile(uid)
        expected_pw = self._passwords.get(uid, "")
        if not verify_password(old_password, expected_pw):
            raise ValueError("原密码校验失败，请确认当前密码是否正确")
        clean_new = new_password.strip()
        if not clean_new:
            raise ValueError("新密码不能为空")
        self._passwords[uid] = hash_password(clean_new)
        self.invalidate_sessions(uid)
        event = self._vault.append_event(
            event_kind="ACCOUNT_PASSWORD_CHANGED",
            subtree_root_id="root",
            actor_slot_id=prof.slot_id,
            payload={
                "user_id": prof.user_id,
                "username": prof.user_id,
                "name": prof.name,
                "slot_id": prof.slot_id,
                "changed_at": utc_now_iso(),
            },
        )
        return {
            "ok": True,
            "user_id": prof.user_id,
            "slot_id": prof.slot_id,
            "event_kind": "ACCOUNT_PASSWORD_CHANGED",
            "event_id": getattr(event, "event_id", None),
        }

    def resolve_token(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        parts = token.strip().split(None, 1)
        clean = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else token.strip()
        return self._sessions.get(clean)

    def resolve_bearer_token(
        self, auth_header: Optional[str]
    ) -> Optional[AccountDirectoryEntry]:
        if not auth_header or not auth_header.strip():
            return None
        parts = auth_header.strip().split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise ValueError("Authorization 头格式错误，请使用 Bearer <token>")
        token = parts[1].strip()
        if not token:
            raise ValueError("未提供有效的 Bearer 登录凭证")
        uid = self._sessions.get(token)
        if not uid:
            raise ValueError("无效或已过期的登录凭证")
        if self.account_directory.get(uid, {}).get("_disabled"):
            self._sessions.pop(token, None)
            raise ValueError("该账号已完成离岗交接并停用，请联系管理员")
        if uid not in self._containers._profiles:
            self._sessions.pop(token, None)
            raise ValueError("登录凭证关联的员工档案不存在")
        prof = self._containers.get_profile(uid)
        if "（已离岗交接）" in (prof.title or ""):
            self._sessions.pop(token, None)
            raise ValueError("该账号已完成离岗交接并停用，请联系管理员")
        entry = next(
            (a for a in self.list_public_accounts() if a.user_id == prof.user_id),
            None,
        )
        if entry is None:
            raise ValueError("未找到登录凭证对应的账号信息")
        return entry

    def logout(self, token: Optional[str]) -> None:
        if not token:
            return
        parts = token.strip().split(None, 1)
        clean = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else token.strip()
        self._sessions.pop(clean, None)

    def _is_exec_user(self, user_id: str) -> bool:
        if user_id in self._containers._profiles:
            return self._containers.get_profile(user_id).role_view in ("boss", "manager")
        return False

    def assert_can_manage_target_slot(self, actor_user_id: str, target_slot_id: str) -> None:
        actor = self._containers.get_profile(actor_user_id)
        target = self._containers.get_slot(target_slot_id)
        occupant = self._containers.get_profile(target.occupant_id)
        if actor.role_view == "boss":
            return
        if actor.role_view == "manager" and occupant.role_view not in ("boss", "manager"):
            return
        self.sync_accounts_from_containers()
        if actor.role_view == "leader" and self.account_directory.get(occupant.user_id, {}).get("supervisor_id") == actor_user_id:
            return
        raise PermissionError("当前账号无权管理目标岗位")

    def resolve_ball_custodian(self, ball_id: str) -> tuple[str, str]:
        """根据球的领域标签、容器归属与直属主管链条，动态确定分管该球的负责人。"""
        self.sync_accounts_from_containers()
        ball = self._particles.get_ball(ball_id)
        profiles = self._containers.list_profiles()
        prof_by_uid = {p.user_id: p for p in profiles}
        slots_by_id = {s.slot_id: s for s in self._containers.list_slots()}
        all_balls = {b.ball_id: b for b in self._particles.list_all_balls()}

        boss_prof = next((p for p in profiles if p.role_view == "boss"), None)
        if ball.ball_type == "REDLINE" or ball.sensitivity_level >= 4:
            if boss_prof is not None:
                return (boss_prof.user_id, f"{boss_prof.name}（{boss_prof.title}）")

        tags = set(ball.domain_tags)
        # 优先按各非 boss 负责人自身部门、职称及其所管辖岗位的领域标签匹配度打分
        leaders = [
            p
            for p in profiles
            if (
                p.role_view in ("leader", "manager")
                or bool(self.account_directory.get(p.user_id, {}).get("is_custodian_leader", False))
            )
            and p.role_view != "boss"
        ]
        if leaders and tags:
            scored: list[tuple[int, DualEmployeeProfile]] = []
            for lp in leaders:
                dept = str(self.account_directory.get(lp.user_id, {}).get("department", ""))
                lp_slot = slots_by_id.get(lp.slot_id)
                lp_tags: set[str] = set()
                if lp_slot:
                    for bid in lp_slot.ball_ids:
                        b_obj = all_balls.get(bid)
                        if b_obj:
                            lp_tags.update(b_obj.domain_tags)
                score = len(tags & lp_tags) * 3
                for t in tags:
                    if t in lp.title or t in dept:
                        score += 2
                if lp.role_view == "leader" and score > 0:
                    score += 1
                if score > 0:
                    scored.append((score, lp))
            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)
                best_lp = scored[0][1]
                return (best_lp.user_id, f"{best_lp.name}（{best_lp.title}）")

        # 其次从 owner_slot_ids 沿岗位占有者或直属主管链条动态定位分管人
        for owner_sid in ball.owner_slot_ids:
            slot = slots_by_id.get(owner_sid)
            if slot is None:
                continue
            occ = prof_by_uid.get(slot.occupant_id)
            if occ is not None and occ.role_view != "boss":
                is_cust = occ.role_view in ("leader", "manager") or bool(
                    self.account_directory.get(occ.user_id, {}).get("is_custodian_leader", False)
                )
                if is_cust:
                    return (occ.user_id, f"{occ.name}（{occ.title}）")
                sup_uid = self.account_directory.get(occ.user_id, {}).get("supervisor_id")
                if sup_uid and sup_uid in prof_by_uid:
                    sup_prof = prof_by_uid[sup_uid]
                    return (sup_prof.user_id, f"{sup_prof.name}（{sup_prof.title}）")

        mgr_prof = next((p for p in profiles if p.role_view == "manager"), None)
        if mgr_prof is not None:
            return (mgr_prof.user_id, f"{mgr_prof.name}（{mgr_prof.title}）")
        if leaders:
            first_l = leaders[0]
            return (first_l.user_id, f"{first_l.name}（{first_l.title}）")
        if boss_prof is not None:
            return (boss_prof.user_id, f"{boss_prof.name}（{boss_prof.title}）")
        return ("", "探路总控")

    def can_user_manage_ball(self, user_id: str, ball_id: str) -> bool:
        if self._is_exec_user(user_id):
            return True
        custodian_id, _ = self.resolve_ball_custodian(ball_id)
        return user_id == custodian_id

    def get_subordinate_profiles(self, leader_id: str) -> list[AccountDirectoryEntry]:
        all_accs = self.list_public_accounts()
        if (
            leader_id in self._containers._profiles
            and self._containers.get_profile(leader_id).role_view == "boss"
        ):
            return [a for a in all_accs if a.user_id != leader_id]
        if self._is_exec_user(leader_id):
            return [
                a for a in all_accs
                if a.user_id != leader_id and a.role_view != "boss"
            ]
        return [a for a in all_accs if a.supervisor_id == leader_id]

    def submit_ball_request(
        self,
        requester_id: str,
        ball_id: str,
        grant_mode: Literal["LEASE_TTL", "PERMANENT"] = "LEASE_TTL",
        ttl_minutes: int = 120,
        reason: str = "跨岗业务协同需要调用该权能球",
    ) -> BallAccessRequestItem:
        prof = self._containers.get_profile(requester_id)
        ball = self._particles.get_ball(ball_id)
        if ball.ball_type == "REDLINE":
            raise PermissionError("红线风控球属于不可申请的高压禁区")

        custodian_id, custodian_name = self.resolve_ball_custodian(ball_id)
        # 若申请人本身就是该球分管人，则上交其直属上级审批
        if custodian_id == requester_id:
            sup_id = self.account_directory.get(requester_id, {}).get("supervisor_id")
            if not sup_id or sup_id not in self._containers._profiles or sup_id == requester_id:
                sup_id = next(
                    (
                        p.user_id
                        for p in self._containers.list_profiles()
                        if p.user_id != requester_id and p.role_view in ("boss", "manager")
                    ),
                    requester_id,
                )
            sup_prof = self._containers.get_profile(sup_id)
            custodian_id, custodian_name = sup_prof.user_id, f"{sup_prof.name}（{sup_prof.title}）"

        req_id = f"BREQ_{uuid.uuid4().hex[:8].upper()}"
        req_item = BallAccessRequestItem(
            request_id=req_id,
            requester_id=requester_id,
            requester_name=prof.name,
            requester_slot_id=prof.slot_id,
            ball_id=ball.ball_id,
            ball_title=ball.title,
            ball_type=ball.ball_type,
            grant_mode=grant_mode,
            ttl_minutes=ttl_minutes,
            reason=reason,
            custodian_id=custodian_id,
            custodian_name=custodian_name,
        )
        self._requests[req_id] = req_item
        self._vault.append_event(
            event_kind="BALL_ACCESS_REQUESTED",
            subtree_root_id="root",
            actor_slot_id=prof.slot_id,
            payload=req_item.model_dump(),
        )
        return req_item

    def decide_ball_request(
        self,
        actor_user_id: str,
        request_id: str,
        approve: bool,
        comment: str = "",
    ) -> BallAccessRequestItem:
        if request_id not in self._requests:
            raise KeyError(f"未找到球权限申请单: {request_id}")
        req = self._requests[request_id]
        if req.status != "PENDING":
            raise ValueError("该申请单已处理完毕")

        if actor_user_id == req.requester_id:
            raise PermissionError("申请人不得审批自己的用球申请")
        if actor_user_id != req.custodian_id and not self._is_exec_user(actor_user_id):
            raise PermissionError("仅该球的分管领导或高管有权审批此申请")

        actor_prof = self._containers.get_profile(actor_user_id)
        req.status = "APPROVED" if approve else "REJECTED"
        req.decision_comment = comment or (
            f"由 {actor_prof.name} 批准授权" if approve else f"由 {actor_prof.name} 驳回"
        )
        req.decided_at = utc_now_iso()

        if approve:
            if req.grant_mode == "PERMANENT":
                self._containers.attach_ball_to_slot(req.requester_slot_id, req.ball_id)
            else:
                self._grant_ttl_lease(
                    borrower_slot_id=req.requester_slot_id,
                    lender_slot_id=actor_prof.slot_id,
                    ball_id=req.ball_id,
                    ttl_minutes=req.ttl_minutes,
                )

        self._vault.append_event(
            event_kind="BALL_ACCESS_DECIDED",
            subtree_root_id="root",
            actor_slot_id=actor_prof.slot_id,
            payload={
                "request_id": req.request_id,
                "approved": approve,
                "ball_id": req.ball_id,
                "requester_slot_id": req.requester_slot_id,
                "grant_mode": req.grant_mode,
            },
        )
        return req

    def _grant_ttl_lease(
        self,
        borrower_slot_id: str,
        lender_slot_id: str,
        ball_id: str,
        ttl_minutes: int,
    ) -> None:
        lender_slot = self._containers.get_slot(lender_slot_id)
        if ball_id not in lender_slot.ball_ids:
            ball = self._particles.get_ball(ball_id)
            if ball.owner_slot_ids:
                lender_slot_id = ball.owner_slot_ids[0]
            else:
                self._containers.attach_ball_to_slot(lender_slot_id, ball_id)
        self._containers.borrow_ball(
            borrower_slot_id=borrower_slot_id,
            lender_slot_id=lender_slot_id,
            ball_id=ball_id,
            ttl_seconds=max(60, ttl_minutes * 60),
        )

    def direct_grant_ball(
        self,
        leader_user_id: str,
        target_slot_id: str,
        ball_id: str,
        grant_mode: Literal["LEASE_TTL", "PERMANENT"] = "PERMANENT",
        ttl_minutes: int = 120,
    ) -> dict[str, Any]:
        self.assert_can_manage_target_slot(leader_user_id, target_slot_id)
        if not self.can_user_manage_ball(leader_user_id, ball_id):
            raise PermissionError("你不是该球的分管负责人，无权派发此球")
        leader_prof = self._containers.get_profile(leader_user_id)
        if grant_mode == "PERMANENT":
            slot = self._containers.attach_ball_to_slot(target_slot_id, ball_id)
        else:
            self._grant_ttl_lease(
                borrower_slot_id=target_slot_id,
                lender_slot_id=leader_prof.slot_id,
                ball_id=ball_id,
                ttl_minutes=ttl_minutes,
            )
            slot = self._containers.get_slot(target_slot_id)
        return slot.model_dump()

    def revoke_ball(
        self, leader_user_id: str, target_slot_id: str, ball_id: str
    ) -> dict[str, Any]:
        self.assert_can_manage_target_slot(leader_user_id, target_slot_id)
        if not self.can_user_manage_ball(leader_user_id, ball_id):
            raise PermissionError("你不是该球的分管负责人，无权收回此球")
        slot = self._containers.get_slot(target_slot_id)
        if ball_id in slot.ball_ids:
            slot.ball_ids.remove(ball_id)
        slot.borrowed_balls = [b for b in slot.borrowed_balls if b.ball_id != ball_id]
        leader_prof = self._containers.get_profile(leader_user_id)
        self._vault.append_event(
            event_kind="BALL_ACCESS_REVOKED",
            subtree_root_id="root",
            actor_slot_id=leader_prof.slot_id,
            payload={"target_slot_id": target_slot_id, "ball_id": ball_id},
        )
        return slot.model_dump()

    def build_custody_overview(self, user_id: str) -> dict[str, Any]:
        from swarm.capability_lifecycle import (
            TYPE_LABELS,
            build_quick_use_prompt,
            classify_capability_category,
        )

        prof = self._containers.get_profile(user_id)
        slot = self._containers.get_slot(prof.slot_id)
        mounted_ids = set(self._containers.get_effective_ball_ids(prof.slot_id))
        all_balls = self._particles.list_all_balls()

        mounted_balls = []
        requestable_balls = []
        managed_balls = []

        for b in all_balls:
            if b.status == "DEPRECATED":
                continue
            custodian_id, custodian_name = self.resolve_ball_custodian(b.ball_id)
            item = {
                **b.model_dump(),
                "custodian_id": custodian_id,
                "custodian_name": custodian_name,
                "is_borrowed": any(
                    lease.ball_id == b.ball_id for lease in slot.borrowed_balls
                ),
                "business_category": classify_capability_category(b),
                "type_label": TYPE_LABELS.get(b.ball_type, "业务资料"),
                "quick_use_prompt": build_quick_use_prompt(b),
            }
            # A catalogue listing is not a grant to read another slot's content.
            if b.ball_id not in mounted_ids and not self.can_user_manage_ball(user_id, b.ball_id):
                item = {k: v for k, v in item.items() if k not in {
                    "content", "executable_code_path", "redline_keywords", "owner_slot_ids"
                }}
            if b.ball_type == "REDLINE" and prof.role_view != "boss":
                continue
            if b.ball_id in mounted_ids:
                mounted_balls.append(item)
            elif b.ball_type != "REDLINE":
                requestable_balls.append(item)

            if self.can_user_manage_ball(user_id, b.ball_id) and b.ball_type != "REDLINE":
                managed_balls.append(item)

        my_requests = [
            r.model_dump()
            for r in reversed(list(self._requests.values()))
            if r.requester_id == user_id
        ]
        pending_approvals = [
            r.model_dump()
            for r in reversed(list(self._requests.values()))
            if r.status == "PENDING"
            and (r.custodian_id == user_id or self._is_exec_user(user_id))
        ]

        subordinates = []
        for sub in self.get_subordinate_profiles(user_id):
            sub_slot = self._containers.get_slot(sub.slot_id)
            subordinates.append(
                {
                    **sub.model_dump(),
                    "effective_ball_ids": self._containers.get_effective_ball_ids(
                        sub.slot_id
                    ),
                    "permanent_ball_ids": list(sub_slot.ball_ids),
                    "borrowed_balls": [
                        lease.model_dump() for lease in sub_slot.borrowed_balls
                    ],
                }
            )

        is_leader = bool(
            self.account_directory.get(user_id, {}).get("is_custodian_leader", False)
            or prof.role_view in ("leader", "manager", "boss")
        )
        return {
            "user_id": user_id,
            "slot_id": prof.slot_id,
            "is_custodian_leader": is_leader,
            "mounted_balls": mounted_balls,
            "requestable_balls": requestable_balls,
            "my_requests": my_requests,
            "managed_balls": managed_balls,
            "pending_subordinate_requests": pending_approvals,
            "subordinates": subordinates,
        }

    def transfer_post_relationships(
        self, previous_user_id: str, new_user_id: str, target_slot_id: str,
    ) -> None:
        if previous_user_id == new_user_id:
            return
        new_prof = self._containers.get_profile(new_user_id)
        for uid, meta in self.account_directory.items():
            if uid != new_user_id and meta.get("supervisor_id") == previous_user_id:
                meta["supervisor_id"] = new_user_id
        for req in self._requests.values():
            if req.status != "PENDING":
                continue
            if req.custodian_id == previous_user_id:
                req.custodian_id = new_user_id
                req.custodian_name = f"{new_prof.name}（{new_prof.title}）"
            if req.requester_id == previous_user_id and req.requester_slot_id == target_slot_id:
                req.requester_id = new_user_id
                req.requester_name = new_prof.name

    def handover_slot_occupant(
        self,
        actor_user_id: str,
        target_slot_id: str,
        new_user_id: str,
        new_person_name: str,
        handover_mode: Literal["LEAVE_DELEGATION", "RESIGN_HANDOVER"] = "RESIGN_HANDOVER",
        reason: str = "员工离岗/请假工位容器无缝交接",
        initial_password: Optional[str] = None,
    ) -> dict[str, Any]:
        """岗人分离核心事件：在不丢失岗位容器内全部权能球与借用契约的前提下，将工位无缝移交给接替员工。"""
        self.assert_can_manage_target_slot(actor_user_id, target_slot_id)
        actor_prof = self._containers.get_profile(actor_user_id)
        is_authorized = (
            self._is_exec_user(actor_user_id)
            or bool(self.account_directory.get(actor_user_id, {}).get("is_custodian_leader", False))
            or actor_prof.role_view in ("leader", "manager", "boss")
        )
        if not is_authorized:
            raise PermissionError("仅分管领导、主管或总控有权执行工位换人/代班交接")

        slot = self._containers.get_slot(target_slot_id)
        old_uid = slot.occupant_id
        clean_new_uid = new_user_id.strip()
        clean_new_name = new_person_name.strip()
        if not clean_new_uid or not clean_new_name:
            raise ValueError("接替人员 user_id 与姓名不能为空")

        old_prof = (
            self._containers.get_profile(old_uid)
            if old_uid in self._containers._profiles
            else None
        )
        inherited_role: RoleViewType = old_prof.role_view if old_prof else "employee"
        inherited_title = (
            old_prof.title
            if old_prof
            else slot.slot_name.split("（")[0].strip() or "业务专员"
        )
        old_meta = dict(self.account_directory.get(old_uid, {}))
        returning_prof = None
        returning_meta = dict(self.account_directory.get(clean_new_uid, {}))
        leave = returning_meta.get("_leave_delegation", {})
        returning_standby_sid = None
        if clean_new_uid != old_uid and clean_new_uid in self._containers._profiles:
            candidate = self._containers.get_profile(clean_new_uid)
            standby = self._containers._slots.get(candidate.slot_id)
            # Only this post's recorded, still-enabled leave holder may reuse a UID.
            # A standby-shaped slot or title alone is not proof of delegation.
            if not (
                isinstance(leave, dict)
                and leave.get("slot_id") == slot.slot_id
                and leave.get("delegate_user_id") == old_uid
                and leave.get("standby_slot_id") == candidate.slot_id
                and not returning_meta.get("_disabled")
                and standby is not None and standby.occupant_id == clean_new_uid
                and not standby.ball_ids and not standby.borrowed_balls
                and not any(s.slot_id != standby.slot_id and s.occupant_id == clean_new_uid
                            for s in self._containers.list_slots())
            ):
                raise ValueError("接替账号已占用其他岗位，请先完成原岗位交接")
            returning_prof = candidate
            returning_standby_sid = candidate.slot_id

        if old_prof is not None and old_uid != clean_new_uid:
            standby_sid = f"SLOT_STANDBY_{old_uid.upper()}"
            if standby_sid in self._containers._slots:
                standby_sid = f"{standby_sid}_{uuid.uuid4().hex[:8]}"
            self._containers.register_slot(
                UnitSlot(
                    slot_id=standby_sid,
                    slot_name=f"{old_prof.name}·待命隔离槽",
                    department=slot.department,
                    ball_ids=[],
                    occupant_type="HUMAN",
                    occupant_id=old_uid,
                )
            )
            old_prof.slot_id = standby_sid
            displaced_meta = self.account_directory.setdefault(old_uid, {})
            if handover_mode == "LEAVE_DELEGATION":
                displaced_meta["_leave_delegation"] = {
                    "slot_id": slot.slot_id, "standby_slot_id": standby_sid,
                    "delegate_user_id": clean_new_uid, "title": inherited_title,
                    "role_view": inherited_role,
                    "is_custodian_leader": bool(old_meta.get("is_custodian_leader", False)),
                }
            else:
                displaced_meta.pop("_leave_delegation", None)
            # Authority belongs to the occupied business post, not its isolation slot.
            old_prof.role_view = "employee"
            displaced_meta["is_custodian_leader"] = False
            status_suffix = "（休假代班中）" if handover_mode == "LEAVE_DELEGATION" else "（已离岗交接）"
            if status_suffix not in old_prof.title:
                old_prof.title = f"{old_prof.title}{status_suffix}"
            if handover_mode == "RESIGN_HANDOVER":
                self.account_directory.setdefault(old_uid, {})["_disabled"] = True
                stale_tokens = [tok for tok, u in self._sessions.items() if u == old_uid]
                for tok in stale_tokens:
                    self._sessions.pop(tok, None)

        clean_title = inherited_title.replace("（已离岗交接）", "").replace("（休假代班中）", "")
        new_prof = returning_prof or (old_prof if clean_new_uid == old_uid else None)
        if new_prof is not None:
            new_prof.name = clean_new_name
            new_prof.title = leave["title"] if returning_prof else clean_title
            new_prof.role_view = leave["role_view"] if returning_prof else inherited_role
            new_prof.slot_id = slot.slot_id
        else:
            new_prof = DualEmployeeProfile(
                user_id=clean_new_uid,
                name=clean_new_name,
                title=clean_title,
                role_view=inherited_role,
                slot_id=slot.slot_id,
                employee_view=old_prof.employee_view.model_copy(deep=True) if old_prof else {},
            )
        self._containers.register_profile(new_prof)
        if returning_standby_sid is not None:
            self._containers._slots.pop(returning_standby_sid)
        clean_initial_pw = str(initial_password or "").strip()
        if clean_initial_pw:
            self.set_password(clean_new_uid, clean_initial_pw)
        elif clean_new_uid not in self._passwords and self._bootstrap_password:
            self._passwords[clean_new_uid] = hash_password(self._bootstrap_password)
        boss_uid = next(
            (p.user_id for p in self._containers.list_profiles() if p.role_view == "boss"),
            None,
        )
        self.account_directory[clean_new_uid] = {
            **(returning_meta if returning_prof else old_meta if clean_new_uid == old_uid else {}),
            "department": old_meta.get("department", slot.department),
            "supervisor_id": old_meta.get("supervisor_id", boss_uid),
            "is_custodian_leader": bool(old_meta.get("is_custodian_leader", False)),
        }
        self.account_directory[clean_new_uid].pop("_leave_delegation", None)
        if returning_prof:
            self.account_directory[clean_new_uid]["is_custodian_leader"] = bool(
                leave.get("is_custodian_leader", False)
            )
        self.transfer_post_relationships(old_uid, clean_new_uid, slot.slot_id)

        slot.occupant_id = clean_new_uid
        if old_prof and f"（{old_prof.name}）" in slot.slot_name:
            slot.slot_name = slot.slot_name.replace(f"（{old_prof.name}）", f"（{clean_new_name}）")
        elif "（" in slot.slot_name and "）" in slot.slot_name:
            base_part = slot.slot_name.split("（", 1)[0].strip()
            slot.slot_name = f"{base_part}（{clean_new_name}）"
        else:
            slot.slot_name = f"{slot.slot_name}（{clean_new_name}）"

        inherited_ball_ids = sorted(self._containers.get_effective_ball_ids(slot.slot_id))
        self._vault.append_event(
            event_kind="SLOT_OCCUPANT_HANDOVER",
            subtree_root_id="root",
            actor_slot_id=actor_prof.slot_id,
            payload={
                "target_slot_id": slot.slot_id,
                "handover_mode": handover_mode,
                "previous_user_id": old_uid,
                "new_user_id": clean_new_uid,
                "new_person_name": clean_new_name,
                "inherited_ball_ids": inherited_ball_ids,
                "reason": reason,
            },
        )
        return {
            "ok": True,
            "target_slot_id": slot.slot_id,
            "slot_name": slot.slot_name,
            "handover_mode": handover_mode,
            "previous_user_id": old_uid,
            "new_user_id": clean_new_uid,
            "new_person_name": clean_new_name,
            "inherited_ball_ids": inherited_ball_ids,
            "inherited_ball_count": len(inherited_ball_ids),
            "password_provisioned": clean_new_uid in self._passwords,
            "reason": reason,
        }

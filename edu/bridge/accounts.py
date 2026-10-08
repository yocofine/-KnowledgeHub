"""Create native login accounts and active editor memberships atomically.

This module never resets existing passwords and never grants elevated roles.
The dedicated PostgreSQL login has no UPDATE/DELETE rights or permission to
write users.is_system_admin / users.can_access_all_tenants.
"""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import string
import sys
from urllib.parse import unquote, urlsplit
import uuid


class AccountError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def validate_identity(username, email):
    username = username.strip()
    email = email.strip().lower()
    if not 2 <= len(username) <= 50 or any(ord(c) < 32 or ord(c) == 127 for c in username):
        raise AccountError(400, "用户名应为 2–50 个字符，不能包含控制字符")
    atom = r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+"
    label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    email_pattern = rf"{atom}(?:\.{atom})*@{label}(?:\.{label})*\.[a-z]{{2,63}}"
    if len(email) > 255 or len(email.split('@')[0]) > 64 or not re.fullmatch(email_pattern, email):
        raise AccountError(400, "请填写有效邮箱，邮箱是成员的登录账号")
    return username, email


def checked_password(password, complex_enabled):
    generated = password is None
    if generated:
        chars = string.ascii_letters + string.digits + "!@#$%^&*_-"
        password = "Aa1!" + "".join(secrets.choice(chars) for _ in range(20))
    valid = 8 <= len(password) <= 32 and len(password.encode("utf-8")) <= 72
    has_upper = any(c in string.ascii_uppercase for c in password)
    has_lower = any(c in string.ascii_lowercase for c in password)
    has_digit = any(c in string.digits for c in password)
    valid = valid and (has_upper or has_lower) and has_digit
    if complex_enabled:
        valid = valid and has_upper and has_lower
        valid = valid and any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password)
    if not valid:
        message = "密码须为 8–32 个字符，包含字母和数字"
        if complex_enabled:
            message += "，以及大写字母、小写字母和特殊字符"
        raise AccountError(400, message)
    return password, generated


def database_connection():
    address = os.environ.get("EDU_MEMBERS_DATABASE_URL", "")
    if not address:
        raise AccountError(503, "成员创建服务尚未配置")
    # Pure-Python pg8000 is installed alongside the bridge, not system-wide.
    vendor = str(Path(__file__).parent / "vendor")
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    import pg8000.dbapi
    parsed = urlsplit(address)
    return pg8000.dbapi.connect(
        user=unquote(parsed.username or ""), password=unquote(parsed.password or ""),
        host=parsed.hostname, port=parsed.port or 5432,
        database=unquote(parsed.path.lstrip("/")), timeout=10,
    )


class MemberAccounts:
    def __init__(self, connect=database_connection, hash_password=None):
        self.connect = connect
        self.hash_password = hash_password or self._hash

    @staticmethod
    def _hash(password):
        import bcrypt
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("ascii")

    def create(self, actor_id, tenant_id, username, email, password, complex_enabled):
        username, email = validate_identity(username, email)
        if not 0 < tenant_id <= 2147483647:
            raise AccountError(400, "请选择一个有效空间")
        with closing(self.connect()) as conn:
            try:
                cursor = conn.cursor()
                # Authoritative permissions, not a role received from the browser.
                cursor.execute("""SELECT u.is_active, u.is_system_admin, u.can_access_all_tenants,
                    m.role, m.status, t.status FROM users u
                    LEFT JOIN tenants t ON t.id = %s AND t.deleted_at IS NULL
                    LEFT JOIN tenant_members m ON m.user_id = u.id AND m.tenant_id = t.id
                        AND m.deleted_at IS NULL
                    WHERE u.id = %s AND u.deleted_at IS NULL""", (tenant_id, actor_id))
                actor = cursor.fetchone()
                if not actor or actor[0] is not True:
                    raise AccountError(401, "登录已失效")
                if actor[5] != "active":
                    raise AccountError(403, "当前空间不可用")
                superuser = actor[1] is True or actor[2] is True
                if not superuser and not (actor[3] in ("admin", "owner") and actor[4] == "active"):
                    raise AccountError(403, "只有当前空间的管理员和所有者可以创建成员")

                cursor.execute("""SELECT id, username, email, is_active, deleted_at FROM users
                    WHERE LOWER(email) = %s OR username = %s""", (email, username))
                existing = cursor.fetchall()
                if existing:
                    if len(existing) == 1:
                        row = existing[0]
                        if row[1] == username and row[2].lower() == email and row[3] is True and row[4] is None:
                            cursor.execute("""SELECT role, status FROM tenant_members
                                WHERE user_id = %s AND tenant_id = %s AND deleted_at IS NULL""", (row[0], tenant_id))
                            membership = cursor.fetchone()
                            if membership and membership[1] == "active":
                                conn.rollback()
                                return {"created": False, "user": {"id": row[0], "username": row[1], "email": row[2]},
                                        "membership": {"tenant_id": tenant_id, "role": membership[0]}}
                    raise AccountError(409, "用户名或邮箱已存在；不会修改已有账号的密码，请使用邀请流程加入已有账号")

                password, generated = checked_password(password, complex_enabled)
                password_hash = self.hash_password(password)
                user_id = str(uuid.uuid4())
                now = datetime.now(timezone.utc)
                # No elevated flag columns are written: DB defaults remain false.
                cursor.execute("""INSERT INTO users
                    (id, username, email, password_hash, tenant_id, is_active, preferences, created_at, updated_at)
                    VALUES (%s,%s,%s,%s,%s,true,%s::jsonb,%s,%s)""",
                    (user_id, username, email, password_hash, tenant_id,
                     json.dumps({"last_active_tenant_id": tenant_id}), now, now))
                cursor.execute("""INSERT INTO tenant_members
                    (user_id, tenant_id, role, status, invited_by, joined_at, created_at, updated_at)
                    VALUES (%s,%s,'contributor','active',%s,%s,%s,%s)""",
                    (user_id, tenant_id, actor_id, now, now, now))
                cursor.execute("""INSERT INTO audit_logs
                    (tenant_id, actor_user_id, actor_role, action, target_type, target_user_id,
                     request_path, request_method, outcome, details, created_at)
                    VALUES (%s,%s,%s,'rbac.member_added','tenant_member',%s,%s,'POST','success',%s::jsonb,%s)""",
                    (tenant_id, actor_id, actor[3] or "system_admin", user_id,
                     f"/api/v1/edu/tenants/{tenant_id}/members/create",
                     json.dumps({"role": "contributor", "account_created": True}), now))
                conn.commit()
                result = {"created": True, "user": {"id": user_id, "username": username, "email": email},
                          "membership": {"tenant_id": tenant_id, "role": "contributor"}}
                if generated:
                    result["generated_password"] = password
                return result
            except AccountError:
                conn.rollback()
                raise
            except Exception as error:
                conn.rollback()
                # pg8000 carries SQLSTATE in the first argument; never expose SQL,
                # account data, or password hashes from a database exception.
                detail = error.args[0] if error.args else None
                if isinstance(detail, dict) and detail.get("C") == "23505":
                    raise AccountError(409, "用户名或邮箱已存在，请刷新成员列表后重试") from None
                raise AccountError(503, "成员创建暂未成功，请稍后重试") from None

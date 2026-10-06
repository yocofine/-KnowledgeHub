"""Read-only legacy export, account binding plan and native account checks.

There is intentionally no live import command in this preparation phase.
No legacy password hash, session token, API key or system setting is exported.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

HERE = Path(__file__).resolve().parent
# Explicit allowlist. Never select * from users/settings/session/audit tables.
TABLES = {
    "users": "id username role disabled created_at",
    "sections": "id name sort_order created_at",
    "documents": "id normalized_name section_id owner_id current_version_id deleted_at created_at",
    "document_versions": "id document_id version_no file_name file_type size_bytes checksum_sha256 object_key preview_object_key tags uploader_id uploaded_at ingestion_status published_at",
    "scripts": "id title content group_name tags owner_id created_at updated_at deleted_at",
    "rules": "id title content group_name tags image_object_key owner_id created_at updated_at deleted_at",
    "faq_items": "id question answer category tags owner_id created_at updated_at deleted_at",
    "content_groups": "id kind name owner_id sort_order created_at updated_at",
}
REQUIRED_TABLES = set(TABLES) - {"content_groups"}


def json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Unsupported export value: {type(value).__name__}")


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite snapshots or a previously checked account binding.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, default=json_value)
        output.write("\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


@contextmanager
def source_connection(url: str):
    parsed = urlsplit(url)
    if parsed.scheme == "sqlite":
        # Read-only URI prevents accidental creation or changes to a source DB.
        raw_path = unquote(parsed.path)
        if parsed.netloc or parsed.query or parsed.fragment or not raw_path:
            raise ValueError("SQLite 地址必须是本地绝对文件路径")
        if os.name == "nt" and re.match(r"^/[A-Za-z]:", raw_path):
            raw_path = raw_path[1:]
        source = Path(raw_path)
        if not source.is_absolute():
            raise ValueError("SQLite 地址必须是绝对文件路径")
        connection = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        kind = "sqlite"
    elif parsed.scheme in {"mysql", "mysql+pymysql"}:
        options = parse_qs(parsed.query, keep_blank_values=True)
        if (not parsed.hostname or not parsed.path.strip("/") or parsed.fragment
                or (options and options != {"charset": ["utf8mb4"]})):
            raise ValueError("源数据库 URL 格式无效；只允许可选的 charset=utf8mb4")
        try:
            import pymysql
        except ImportError as error:
            raise ValueError("请先安装 edu/requirements.txt（只读导出需要 PyMySQL）") from error
        connection = pymysql.connect(
            host=parsed.hostname, port=parsed.port or 3306,
            user=unquote(parsed.username or ""), password=unquote(parsed.password or ""),
            database=unquote(parsed.path.lstrip("/")), charset="utf8mb4",
            connect_timeout=15, read_timeout=120, write_timeout=30, autocommit=False,
        )
        kind = "mysql"
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
        except Exception:
            connection.close()
            raise
    else:
        raise ValueError("只支持旧 MySQL 或离线测试用 SQLite 数据库")
    try:
        yield connection, kind
    finally:
        connection.rollback()
        connection.close()


def export_snapshot(connection, kind: str) -> dict:
    if kind == "sqlite":
        existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    else:
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            existing = {row[0] for row in cursor.fetchall()}
    missing = REQUIRED_TABLES - existing
    if missing:
        raise ValueError("源数据库缺少必要表：" + ", ".join(sorted(missing)))
    tables = {}
    for name, field_list in TABLES.items():
        fields = field_list.split()
        if name not in existing:
            tables[name] = []
            continue
        cursor = connection.cursor()
        try:
            if kind == "sqlite":
                cursor.execute(f"PRAGMA table_info(`{name}`)")
                columns = {row[1] for row in cursor.fetchall()}
            else:
                cursor.execute(f"SHOW COLUMNS FROM `{name}`")
                columns = {row[0] for row in cursor.fetchall()}
            if not set(fields) <= columns:
                raise ValueError(f"{name} 表结构不匹配，先确认服务器代码版本；不猜测数据归属")
            projection = ", ".join(f"`{field}`" for field in fields)
            cursor.execute(f"SELECT {projection} FROM `{name}` ORDER BY id")
            tables[name] = [dict(zip(fields, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()
    return {"schema_version": 1, "source": "edu-rag-platform", "exported_at": datetime.now(timezone.utc).isoformat(),
            "tables": tables, "includes_file_bytes": False,
            "excluded": ["password_hashes", "system_settings", "sessions", "chat_history", "audit_logs", "vector_indexes", "dingtalk_inbox"]}


def live(rows: list[dict]) -> list[dict]:
    return [row for row in rows if not row.get("deleted_at")]


def validate_snapshot(snapshot: dict) -> dict:
    if snapshot.get("schema_version") != 1 or snapshot.get("source") != "edu-rag-platform":
        raise ValueError("快照类型或版本不受支持")
    tables = snapshot.get("tables", {})
    if not REQUIRED_TABLES <= set(tables):
        raise ValueError("快照缺少必要数据表")
    for name, field_list in TABLES.items():
        allowed = set(field_list.split())
        for row in tables.get(name, []):
            if not isinstance(row, dict) or set(row) != allowed:
                raise ValueError(f"{name} 快照字段不匹配（拒绝秘密字段或缺失 owner_id）")
    users = tables["users"]
    ids = {row["id"] for row in users}
    if len(ids) != len(users) or len({row["username"] for row in users}) != len(users):
        raise ValueError("旧用户 ID 或用户名重复")
    for name in ("scripts", "rules", "faq_items", "documents", "content_groups"):
        for row in tables.get(name, []):
            if row["owner_id"] not in ids:
                raise ValueError(f"{name} 存在无法确认归属的记录：{row['id']}")
    return tables


def inventory(snapshot: dict) -> dict:
    tables = validate_snapshot(snapshot)
    owners = Counter(row["owner_id"] for row in live(tables["scripts"]))
    return {
        "counts": {name: len(rows) for name, rows in tables.items()},
        "active_counts": {name: len(live(tables[name])) for name in ("documents", "scripts", "rules", "faq_items")},
        "accounts": [{"username": row["username"], "role": row["role"], "disabled": bool(row["disabled"]),
                      "personal_script_count": owners[row["id"]]} for row in tables["users"]],
        "file_bytes_exported": False,
        "document_status_counts": dict(Counter(row["ingestion_status"] for row in tables["document_versions"])),
    }


def validate_map(mapping: dict) -> dict:
    if mapping.get("schema_version") != 1 or not isinstance(mapping.get("accounts"), dict):
        raise ValueError("账号映射格式错误")
    excluded = mapping.get("excluded_accounts", [])
    if (not isinstance(excluded, list) or any(not isinstance(name, str) or not name.strip() for name in excluded)
            or len(set(excluded)) != len(excluded) or set(excluded) & set(mapping["accounts"])):
        raise ValueError("不迁移账号列表无效，或与邮箱绑定冲突")
    emails = set()
    tenant_ids = set()
    for username, binding in mapping["accounts"].items():
        if not username.strip() or not isinstance(binding, dict):
            raise ValueError("账号映射必须使用旧用户名作为键")
        if set(binding) - {"email", "user_id", "personal_tenant_id"}:
            raise ValueError("账号映射不得包含密码、Token 或未知字段")
        email = binding.get("email", "").strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError(f"{username} 的新邮箱无效")
        if email in emails:
            raise ValueError("不能把不同旧用户合并到同一个新账号")
        emails.add(email)
        tenant = binding.get("personal_tenant_id")
        if tenant is not None:
            if not isinstance(tenant, int) or isinstance(tenant, bool) or tenant <= 0 or tenant in tenant_ids:
                raise ValueError("个人空间必须为独立且有效的 tenant ID")
            tenant_ids.add(tenant)
    return mapping["accounts"]


def binding_plan(snapshot: dict, mapping: dict) -> dict:
    tables = validate_snapshot(snapshot)
    accounts = validate_map(mapping)
    known = {row["username"] for row in tables["users"]}
    excluded = set(mapping.get("excluded_accounts", []))
    unknown = (set(accounts) | excluded) - known
    if unknown:
        raise ValueError("映射中存在旧系统没有的用户：" + ", ".join(sorted(unknown)))
    scripts = live(tables["scripts"])
    personal = []
    pending = []
    skipped = []
    for user in tables["users"]:
        owned = [row["id"] for row in scripts if row["owner_id"] == user["id"]]
        binding = accounts.get(user["username"])
        if user["username"] in excluded:
            skipped.append({"username": user["username"], "script_ids": owned,
                            "reason": "用户明确选择不迁移；数据仅留在旧站与离线备份"})
        elif user["disabled"] and owned:
            pending.append({"username": user["username"], "reason": "旧账号已停用，需要单独决定如何保管其话术", "script_ids": owned})
        elif binding:
            personal.append({"old_username": user["username"], "old_user_id": user["id"], **binding,
                             "script_ids": owned, "target": "exclusive_personal_scripts",
                             "identity_checked": False})
        elif owned:
            pending.append({"username": user["username"], "reason": "缺少新邮箱绑定；不得归入 admin", "script_ids": owned})
    active_docs = live(tables["documents"])
    versions = {row["id"]: row for row in tables["document_versions"]}
    missing_versions = [row["id"] for row in active_docs if row["current_version_id"] not in versions
                        or versions[row["current_version_id"]]["document_id"] != row["id"]]
    return {
        "schema_version": 1, "mode": "plan_only", "writes_performed": False,
        "ready_for_private_identity_checks": not pending,
        "personal_accounts": personal, "pending_accounts": pending,
        "excluded_accounts": skipped,
        "shared": {"document_ids": [row["id"] for row in active_docs],
                   "rule_ids": [row["id"] for row in live(tables["rules"])],
                   "faq_ids": [row["id"] for row in live(tables["faq_items"])],
                   "permissions": "ordinary users viewer; administrators owner/admin"},
        "blockers": ["新邮箱需要先完成 WeKnora 注册；身份、个人空间与分享权限仍需校验",
                     "原文件字节、规则图片及文件版本尚未迁移，不能仅迁移 MySQL 元数据",
                     "教辅专用话术界面、钉钉入库/推送及高频问题云仍需适配"],
        "documents_without_valid_current_version": missing_versions,
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Never send a user's JWT to a redirected host.
        return None


class NativeAPI:
    def __init__(self, base_url: str, token: str):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path.rstrip("/")):
            raise ValueError("WeKnora 地址必须是纯 origin，例如 https://weknora.example.com")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("非本机地址必须使用 HTTPS，禁止明文传送用户 Token")
        if not token or any(char.isspace() for char in token):
            raise ValueError("请通过指定环境变量提供新用户的 JWT；不要写入映射文件")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.opener = build_opener(NoRedirect())

    def get(self, path: str) -> dict:
        request = Request(self.base_url + "/api/v1" + path,
                          headers={"Authorization": "Bearer " + self.token, "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=30) as response:
                body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise ValueError("API 响应异常过大")
            value = json.loads(body)
        except HTTPError as error:
            raise ValueError(f"新系统身份检查失败，HTTP {error.code}；没有执行写入") from None
        except (URLError, json.JSONDecodeError) as error:
            raise ValueError("新系统不可访问或返回非 JSON；没有执行写入") from None
        if not isinstance(value, dict) or value.get("success") is not True:
            raise ValueError("新系统未确认请求成功")
        return value


def verify_private_account(api, binding: dict, tenant_id: int) -> dict:
    user = api.get("/auth/validate").get("user", {})
    if user.get("email", "").strip().casefold() != binding["email"].strip().casefold() or not user.get("is_active"):
        raise ValueError("JWT 的新账号邮箱不匹配或账号未启用")
    if not user.get("id"):
        raise ValueError("新系统未返回用户 ID")
    if binding.get("user_id") and user["id"] != binding["user_id"]:
        raise ValueError("新用户 ID 与既有绑定不一致")
    if binding.get("personal_tenant_id") and binding["personal_tenant_id"] != tenant_id:
        raise ValueError("个人空间 ID 与既有绑定不一致")
    if user.get("tenant_id") != tenant_id:
        raise ValueError("话术目标必须是该新账号的个人主空间，不能使用团队空间")
    data = api.get(f"/tenants/{tenant_id}/members?page=1&page_size=100").get("data", {})
    members = data.get("members", [])
    if data.get("total") != 1 or len(members) != 1:
        raise ValueError("个人空间含其他成员或邀请，拒绝迁移私人话术")
    member = members[0]
    if (member.get("user_id") != user["id"] or member.get("role") != "owner"
            or member.get("status") != "active"):
        raise ValueError("个人空间唯一成员必须是当前账号且为 active owner")
    return {"email": binding["email"], "user_id": user["id"], "personal_tenant_id": tenant_id,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "scope": "identity_and_membership_only", "writes_performed": False,
            "note": "此检查不是完整隔离验收；仍需禁用个人话术的分享、邀请和跨空间检索"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="只读导出旧数据库，不含密码/Key/文件字节")
    export.add_argument("--database-env", default="EDU_SOURCE_DATABASE_URL")
    export.add_argument("--out", type=Path, required=True)
    inspect = commands.add_parser("inventory")
    inspect.add_argument("--snapshot", type=Path, required=True)
    plan = commands.add_parser("plan", help="生成离线迁移计划；不向 WeKnora 写入")
    plan.add_argument("--snapshot", type=Path, required=True)
    plan.add_argument("--map", type=Path, default=HERE / "account-map.json")
    plan.add_argument("--out", type=Path, required=True)
    check = commands.add_parser("check-account", help="用新用户 JWT 只读校验邮箱与个人空间")
    check.add_argument("--map", type=Path, default=HERE / "account-map.json")
    check.add_argument("--username", required=True)
    check.add_argument("--tenant-id", type=int, required=True)
    check.add_argument("--base-url", default="http://127.0.0.1:18080")
    check.add_argument("--token-env", default="EDU_WEKNORA_TOKEN")
    check.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "export":
            url = os.environ.get(args.database_env, "")
            if not url:
                raise ValueError(f"请先在环境变量 {args.database_env} 中配置源数据库地址")
            try:
                with source_connection(url) as (connection, kind):
                    snapshot = export_snapshot(connection, kind)
            except ValueError:
                raise
            except Exception:
                # DB library errors may expose usernames, hosts and credentials.
                raise ValueError("只读连接或查询失败；请检查地址、只读权限及表结构，不在日志输出数据库 URL") from None
            validate_snapshot(snapshot)
            save_json(args.out, snapshot)
            print("只读快照已保存（包含私人内容，请妥善保管；不含文件字节）。")
        elif args.command == "inventory":
            print(json.dumps(inventory(read_json(args.snapshot)), ensure_ascii=False, indent=2))
        elif args.command == "plan":
            result = binding_plan(read_json(args.snapshot), read_json(args.map))
            save_json(args.out, result)
            print(f"离线计划已保存；未写入新系统。待绑定私人账号数：{len(result['pending_accounts'])}")
        else:
            accounts = validate_map(read_json(args.map))
            if args.username not in accounts or args.tenant_id <= 0:
                raise ValueError("用户名未绑定或个人空间 ID 无效")
            api = NativeAPI(args.base_url, os.environ.get(args.token_env, ""))
            result = verify_private_account(api, accounts[args.username], args.tenant_id)
            save_json(args.out, result)
            print("新账号邮箱与个人空间成员校验通过；没有导入话术或修改账号。")
    except (OSError, ValueError, TypeError, KeyError) as error:
        if isinstance(error, FileExistsError):
            parser.exit(1, "目标文件已存在，拒绝覆盖；请选择新的输出文件名。\n")
        parser.exit(1, f"检查未通过：{error}\n")


if __name__ == "__main__":
    main()

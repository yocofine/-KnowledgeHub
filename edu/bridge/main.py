"""JWT-authenticated edu extension. No models or document parsing run here."""
import asyncio
import base64
from contextlib import asynccontextmanager
from dataclasses import dataclass
import hashlib
import json
import os

from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
from pydantic import BaseModel, ConfigDict, Field
from .store import Store, ScriptGroupError
from . import dingtalk
from .accounts import AccountError, MemberAccounts

BASE = os.environ.get("WEKNORA_API_URL", "http://app:8080").rstrip("/")
KEY = os.environ.get("EDU_ENCRYPTION_KEY", "")
STORE_PATH = os.environ.get("EDU_STORE_PATH", "/data/edu.sqlite")
ADMIN_IDS = set(filter(None, os.environ.get("EDU_ADMIN_USER_IDS", "").split(",")))
store = Store(STORE_PATH)
cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(KEY.encode()).digest())) if len(KEY) >= 32 else None
bearer = HTTPBearer()


@dataclass
class Actor:
    id: str
    username: str
    can_manage: bool


async def actor(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            response = await client.get(BASE + "/api/v1/auth/validate", headers={"Authorization": "Bearer " + credentials.credentials})
        if response.status_code != 200:
            raise HTTPException(401 if response.status_code in (401, 403) else 503, "登录已失效，请重新登录")
        data = response.json()
        user = data.get("user", {})
        if data.get("success") is not True or not user.get("id") or user.get("is_active") is not True:
            raise HTTPException(401, "登录已失效，请重新登录")
        return Actor(user["id"], user.get("username") or user["email"], user.get("is_system_admin") is True or user["id"] in ADMIN_IDS)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "认证服务暂不可用，请稍后重试") from None


def manager(current: Actor = Depends(actor)):
    if not current.can_manage:
        raise HTTPException(403, "只有管理员可以修改规则及机器人配置")
    return current


def settings():
    return store.settings(cipher) if cipher else {}


def success(value):
    return {"success": True, "data": value}


async def native(method, path, **kwargs):
    config = settings()
    key = config.get("rules_api_key", "")
    if not key:
        raise ValueError("规则检索同步凭据尚未配置")
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        response = await client.request(method, BASE + "/api/v1" + path, headers={"X-API-Key": key}, **kwargs)
    if response.status_code >= 400:
        raise ValueError(f"规则检索同步失败（HTTP {response.status_code}）")
    value = response.json()
    if value.get("success") is not True:
        raise ValueError("规则检索同步未成功")
    return value.get("data")


async def locate_rule(kb_id, marker):
    # Recovery after an ambiguous POST timeout: discover the source marker first.
    for page in range(1, 101):
        result = await native("GET", f"/knowledge-bases/{kb_id}/knowledge?page={page}&page_size=100")
        rows = result if isinstance(result, list) else result.get("items", [])
        for row in rows:
            metadata = row.get("metadata") or {}
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            if marker in str(metadata.get("content", "")):
                return row["id"]
        if len(rows) < 100:
            return None
    raise ValueError("规则库过大，请人工检查同步任务")


async def synchronize_rule(row):
    config = settings()
    kb_id = config.get("rules_kb_id", "")
    if not kb_id:
        raise ValueError("规则知识库尚未配置")
    native_id = row.get("native_id")
    marker = f"<!-- edu-rule:{row['id']} -->"
    if not native_id:
        native_id = await locate_rule(kb_id, marker)
        if native_id:
            store.mark_rule(row["id"], row["version"], "pending", native_id)
    if row["deleted"]:
        if native_id:
            try:
                await native("DELETE", f"/knowledge/{native_id}")
            except ValueError as error:
                if "HTTP 404" not in str(error):
                    raise
        store.mark_rule(row["id"], row["version"], "deleted", native_id)
        return
    if row["state"] != "synced":
        metadata_text = "\n\n分组：" + row["group_name"] + ("\n\n标签：" + row["tags"] if row.get("tags") else "")
        payload = {"title": row["title"], "content": row["content"] + metadata_text + "\n\n" + marker,
                   "status": "publish", "process_config": {"summary_enabled": False}}
        if native_id:
            await native("PUT", f"/knowledge/manual/{native_id}", json=payload)
        else:
            result = await native("POST", f"/knowledge-bases/{kb_id}/knowledge/manual", json=payload)
            native_id = result["id"]
        store.mark_rule(row["id"], row["version"], "synced", native_id)
    if row["push_requested"] and row["push_status"] == "pending":
        try:
            await dingtalk.send(row, config.get("dingtalk", {}))
            store.mark_rule(row["id"], row["version"], "synced", native_id, push_status="sent")
        except Exception:
            # Never repeatedly resend a group message after an ambiguous timeout.
            store.mark_rule(row["id"], row["version"], "synced", native_id,
                            error="钉钉推送未确认成功，请查看群聊后手动重推", push_status="failed")


async def worker():
    while True:
        for row in store.pending_rules():
            try:
                await synchronize_rule(row)
            except asyncio.CancelledError:
                raise
            except Exception:
                store.mark_rule(row["id"], row["version"], "retry", row.get("native_id"),
                                error="规则已保存，检索同步失败；后台会重试，请检查规则库与模型配置")
        await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app):
    if cipher is None:
        raise RuntimeError("EDU_ENCRYPTION_KEY must be generated before starting the edu extension")
    task = asyncio.create_task(worker())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="WeKnora edu extension", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def no_cache(request, call_next):
    try:
        size = int(request.headers.get("content-length", "0"))
    except ValueError:
        size = 2_000_001
    if size > 2_000_000:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "内容过大"}, status_code=413)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


class Content(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=300_000)
    group_name: str = Field(default="默认分组", min_length=1, max_length=120)
    tags: str = Field(default="", max_length=2000)


class ImportContent(Content):
    legacy_id: str = Field(min_length=1, max_length=80)


class ScriptContent(Content):
    group_id: str | None = Field(default=None, min_length=1, max_length=80)


class ScriptGroupContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)


class RuleContent(ScriptContent):
    push: bool = True


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=500)
    source_id: str = Field(min_length=1, max_length=100)


class RobotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    webhook: str | None = Field(default=None, max_length=2048)
    secret: str | None = Field(default=None, max_length=1024)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/edu/me")
def me(current: Actor = Depends(actor)):
    config = settings()
    return success({"user_id": current.id, "can_manage_rules": current.can_manage,
                    "faq_kb_id": config.get("faq_kb_id"), "rules_kb_id": config.get("rules_kb_id")})


@app.get("/api/v1/edu/scripts")
def scripts(q: str = Query(default="", max_length=200), current: Actor = Depends(actor)):
    return success(store.scripts(current.id, q))


@app.post("/api/v1/edu/scripts")
def create_script(payload: ScriptContent, current: Actor = Depends(actor)):
    try:
        return success(store.save_script(current.id, payload.model_dump(exclude_unset=True)))
    except ScriptGroupError as error:
        raise HTTPException(error.status, str(error)) from None


@app.get("/api/v1/edu/script-groups")
def script_groups(current: Actor = Depends(actor)):
    return success(store.script_groups(current.id))


@app.post("/api/v1/edu/script-groups")
def create_script_group(payload: ScriptGroupContent, current: Actor = Depends(actor)):
    try:
        return success(store.save_script_group(current.id, payload.name))
    except ScriptGroupError as error:
        raise HTTPException(error.status, str(error)) from None


@app.put("/api/v1/edu/script-groups/{group_id}")
def rename_script_group(group_id: str, payload: ScriptGroupContent, current: Actor = Depends(actor)):
    try:
        return success(store.save_script_group(current.id, payload.name, group_id))
    except ScriptGroupError as error:
        raise HTTPException(error.status, str(error)) from None


@app.delete("/api/v1/edu/script-groups/{group_id}")
def delete_script_group(group_id: str, current: Actor = Depends(actor)):
    if not store.delete_script_group(current.id, group_id):
        raise HTTPException(404, "话术组不存在")
    return success({"deleted": True})


@app.post("/api/v1/edu/scripts/import")
def import_script(payload: ImportContent, current: Actor = Depends(manager)):
    return success(store.save_script(current.id, payload.model_dump()))


@app.get("/api/v1/edu/scripts/{item_id}")
def get_script(item_id: str, current: Actor = Depends(actor)):
    result = store.script(current.id, item_id)
    if not result:
        raise HTTPException(404, "话术不存在")
    return success(result)


@app.put("/api/v1/edu/scripts/{item_id}")
def edit_script(item_id: str, payload: ScriptContent, current: Actor = Depends(actor)):
    try:
        result = store.save_script(current.id, payload.model_dump(exclude_unset=True), item_id)
    except ScriptGroupError as error:
        raise HTTPException(error.status, str(error)) from None
    if not result:
        raise HTTPException(404, "话术不存在")
    return success(result)


@app.delete("/api/v1/edu/scripts/{item_id}")
def delete_script(item_id: str, current: Actor = Depends(actor)):
    if not store.delete_script(current.id, item_id):
        raise HTTPException(404, "话术不存在")
    return success({"deleted": True})


@app.get("/api/v1/edu/rules")
def rules(q: str = Query(default="", max_length=200), current: Actor = Depends(actor)):
    return success(store.rules(q))


@app.get("/api/v1/edu/rule-groups")
def rule_groups(current: Actor = Depends(actor)):
    return success(store.rule_groups())


@app.post("/api/v1/edu/rule-groups")
def create_rule_group(payload: ScriptGroupContent, current: Actor = Depends(manager)):
    try:
        return success(store.save_rule_group(payload.name))
    except ScriptGroupError as error:
        raise HTTPException(error.status, str(error)) from None


@app.put("/api/v1/edu/rule-groups/{group_id}")
def rename_rule_group(group_id: str, payload: ScriptGroupContent, current: Actor = Depends(manager)):
    try:
        return success(store.save_rule_group(payload.name, group_id))
    except ScriptGroupError as error:
        raise HTTPException(error.status, str(error)) from None


@app.delete("/api/v1/edu/rule-groups/{group_id}")
def delete_rule_group(group_id: str, current: Actor = Depends(manager)):
    if not store.delete_rule_group(group_id):
        raise HTTPException(404, "规则分组不存在")
    return success({"deleted": True})


@app.post("/api/v1/edu/rules")
def create_rule(payload: RuleContent, current: Actor = Depends(manager)):
    try:
        return success(store.save_rule(current.username, payload.model_dump(exclude_unset=True), push=payload.push))
    except ScriptGroupError as error:
        raise HTTPException(error.status, str(error)) from None


@app.post("/api/v1/edu/rules/import")
def import_rule(payload: ImportContent, current: Actor = Depends(manager)):
    # Migrating historical rules must NEVER repost all of them into a group.
    return success(store.save_rule(current.username, payload.model_dump(), push=False))


@app.put("/api/v1/edu/rules/{item_id}")
def edit_rule(item_id: str, payload: RuleContent, current: Actor = Depends(manager)):
    try:
        result = store.save_rule(current.username, payload.model_dump(exclude_unset=True), item_id, payload.push)
    except ScriptGroupError as error:
        raise HTTPException(error.status, str(error)) from None
    if not result:
        raise HTTPException(404, "规则不存在")
    return success(result)


@app.delete("/api/v1/edu/rules/{item_id}")
def delete_rule(item_id: str, current: Actor = Depends(manager)):
    if not store.delete_rule(item_id):
        raise HTTPException(404, "规则不存在")
    return success({"deleted": True})


@app.post("/api/v1/edu/rules/{item_id}/push")
async def push_rule(item_id: str, current: Actor = Depends(manager)):
    row = store.rule(item_id)
    if not row or row["deleted"]:
        raise HTTPException(404, "规则不存在")
    try:
        await dingtalk.send(row, settings().get("dingtalk", {}))
    except Exception:
        raise HTTPException(502, "钉钉未确认成功，请先查看群聊，再决定是否重推") from None
    store.mark_rule(item_id, row["version"], row["state"], row.get("native_id"), push_status="sent")
    return success({"sent": True})


@app.post("/api/v1/edu/questions")
def record_question(payload: Question, current: Actor = Depends(actor)):
    store.question(current.id, payload.question, payload.source_id)
    return success({"recorded": True})


@app.get("/api/v1/edu/questions")
def cloud(current: Actor = Depends(actor)):
    return success(store.cloud(current.id))


@app.get("/api/v1/edu/dingtalk")
def get_robot(current: Actor = Depends(manager)):
    config = settings().get("dingtalk", {})
    return success({"enabled": bool(config.get("enabled")), "webhook_configured": bool(config.get("webhook")),
                    "secret_configured": bool(config.get("secret"))})


@app.put("/api/v1/edu/dingtalk")
def save_robot(payload: RobotConfig, current: Actor = Depends(manager)):
    config = settings().get("dingtalk", {})
    patch = payload.model_dump(exclude_none=True)
    if "webhook" in patch and patch["webhook"] and not dingtalk.valid_webhook(patch["webhook"]):
        raise HTTPException(422, "Webhook 必须为钉钉 HTTPS 群机器人地址")
    config.update(patch)
    if config.get("enabled") and not config.get("webhook"):
        raise HTTPException(422, "启用前请配置 Webhook")
    store.save_settings(cipher, {"dingtalk": config})
    return get_robot(current)


class MemberContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=2, max_length=50)
    email: str = Field(min_length=3, max_length=255)
    password: str | None = Field(default=None, max_length=32)


member_accounts = MemberAccounts()
member_slots = asyncio.Semaphore(1)


@app.post("/api/v1/edu/tenants/{tenant_id}/members/create")
async def create_member(tenant_id: int, payload: MemberContent, current: Actor = Depends(actor)):
    # Native JWT validation precedes authoritative per-workspace role checks in
    # MemberAccounts. A platform rules-manager flag is NOT sufficient here.
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            config = await client.get(BASE + "/api/v1/auth/config")
        if config.status_code != 200 or config.json().get("success") is not True:
            raise HTTPException(503, "密码策略暂不可用，请稍后重试")
        complex_enabled = config.json().get("complex_password_enabled")
        if not isinstance(complex_enabled, bool):
            raise HTTPException(503, "密码策略暂不可用，请稍后重试")
        async with member_slots:
            result = await run_in_threadpool(member_accounts.create, current.id, tenant_id,
                                            payload.username, payload.email, payload.password, complex_enabled)
        return JSONResponse(result, status_code=201 if result["created"] else 200,
                            headers={"Cache-Control": "no-store"})
    except AccountError as error:
        raise HTTPException(error.status, error.message) from None
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "成员创建服务暂不可用，请稍后重试") from None
    except Exception:
        raise HTTPException(503, "成员创建暂未成功，请稍后重试") from None

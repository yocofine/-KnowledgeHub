"""Create the new admin account and native resources. Never log credentials."""
import argparse
import json
import os
from pathlib import Path
import secrets
import time
import httpx


def write_private(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)


class API:
    def __init__(self, origin, token=""):
        self.client = httpx.Client(base_url=origin.rstrip("/") + "/api/v1/", timeout=60, follow_redirects=False)
        self.token = token
        self.on_unauthorized = None

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path.lstrip("/"),
            headers={"Authorization": "Bearer " + self.token} if self.token else {}, **kwargs)
        if response.status_code == 401 and self.on_unauthorized:
            self.token = self.on_unauthorized()
            response = self.client.request(method, path.lstrip("/"), headers={"Authorization": "Bearer " + self.token}, **kwargs)
        if response.status_code >= 400:
            # Only non-secret, known error fields. Never dump a request or URL.
            try:
                error = response.json().get("error", {})
                message = error.get("message", "") if isinstance(error, dict) else ""
            except ValueError:
                message = ""
            raise RuntimeError(f"{method} {path.split('?')[0]} failed HTTP {response.status_code}: {message}")
        value = response.json()
        if value.get("success") is not True:
            raise RuntimeError("API request did not confirm success")
        return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:18080")
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--bridge-env", type=Path, required=True)
    parser.add_argument("--repair-models", action="store_true", help="Repair models created by this migration before production cutover")
    parser.add_argument("--repair-parsers", action="store_true")
    args = parser.parse_args()
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    email = mapping["accounts"]["admin"]["email"]
    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else {}
    api = API(args.origin)
    if not state:
        password = "Aa1!" + secrets.token_urlsafe(12)
        state = {"email": email, "password": password, "models": {}, "knowledge_bases": {}}
        # Save the generated credential BEFORE registration to survive an
        # ambiguous network response without losing the only new password.
        write_private(args.state, state)
    if state["email"].casefold() != email.casefold():
        raise ValueError("Saved account and mapping disagree")
    if not state.get("user_id"):
        try:
            account = api.request("POST", "auth/login", json={"email": email, "password": state["password"]})
        except RuntimeError:
            account = api.request("POST", "auth/register", json={"username": "admin", "email": email, "password": state["password"]})
        state["user_id"] = account["user"]["id"]
        tenant = account.get("tenant") or account.get("active_tenant") or {}
        state["home_tenant_id"] = account["user"].get("tenant_id") or tenant.get("id")
        print("New administrator account ready; credentials saved privately", flush=True)
    login = api.request("POST", "auth/login", json={"email": email, "password": state["password"]})
    api.token = login["token"]
    state["user_id"] = login["user"]["id"]
    state["home_tenant_id"] = login["user"].get("tenant_id") or state.get("home_tenant_id")
    if not state["home_tenant_id"]:
        raise ValueError("新账号没有个人主空间；请先完成原生空间创建，避免错误绑定")
    state["token"] = api.token
    state["refresh_token"] = login.get("refresh_token")
    # Use an independent team workspace for shared documents/rules/FAQ.
    if not state.get("shared_tenant_id"):
        shared = api.request("POST", "tenants", json={"name": "教辅知识库", "description": "公共文档、规则通知及独立 FAQ"})["data"]
        state["shared_tenant_id"] = shared["id"]
    switched = api.request("POST", "auth/switch-tenant", json={"tenant_id": state["shared_tenant_id"]})
    api.token = switched["token"]
    state["token"] = api.token
    state["refresh_token"] = switched.get("refresh_token", state.get("refresh_token"))
    # Write checkpoint atomically; it already belongs to this tool and contains secrets.
    def checkpoint():
        temporary = args.state.with_suffix(".new")
        write_private(temporary, state)
        temporary.replace(args.state)
    checkpoint()
    for key, model in seed["models"].items():
        # v0.8.2 model catalog accepts source='aliyun', but embed/rerank
        # assemblers only accept source='remote'. Provider stays aliyun.
        if model["type"] in {"Embedding", "Rerank"}:
            model = {**model, "source": "remote"}
        if key not in state["models"]:
            result = api.request("POST", "models", json={**model, "display_name": "教辅 " + model["name"]})
            state["models"][key] = result["data"]["id"]
            checkpoint()
        elif args.repair_models:
            api.request("PUT", "models/" + state["models"][key], json={**model, "display_name": "教辅 " + model["name"]})
        print("Remote model configured: " + key, flush=True)
    api.request("PUT", "tenants/kv/parser-engine-config", json=seed["parser"])
    print("MinerU Cloud configured; no local model used", flush=True)
    snapshot = json.loads((args.mapping.parent / "snapshots" / "legacy.json").read_text(encoding="utf-8"))
    sections = [row["name"] for row in snapshot["tables"]["sections"]]
    names = sections + ["规则通知", "FAQ库"]
    for name in names:
        if name in state["knowledge_bases"]:
            continue
        payload = {"name": name, "type": "faq" if name == "FAQ库" else "document",
            "embedding_model_id": state["models"]["embedding"], "summary_model_id": state["models"]["chat"],
            "description": "从教辅知识库迁移；仅管理员维护" if name in sections else "教辅 " + name,
            "chunking_config": {"chunk_size": 512, "chunk_overlap": 100, "strategy": "heading",
                "enable_parent_child": True, "parent_chunk_size": 2048, "child_chunk_size": 384,
                "parser_engine_rules": [{"file_types": ["pdf", "doc", "docx", "ppt", "pptx", "jpg", "png"], "engine": "mineru_cloud"}]},
            "storage_provider_config": {"provider": "local"}}
        result = api.request("POST", "knowledge-bases", json=payload)
        state["knowledge_bases"][name] = result["data"]["id"]
        checkpoint()
        print("Native knowledge base created: " + name, flush=True)
    if args.repair_parsers:
        for name, kb_id in state["knowledge_bases"].items():
            if name == "FAQ库":
                continue
            current = api.request("GET", "knowledge-bases/" + kb_id)["data"]
            chunking = current["chunking_config"]
            chunking["parser_engine_rules"] = [{"file_types": ["pdf", "doc", "docx", "ppt", "pptx", "jpg", "png"], "engine": "mineru_cloud"}]
            api.request("PUT", "knowledge-bases/" + kb_id, json={"name": current["name"],
                "description": current.get("description", ""), "config": {"chunking_config": chunking}})
    api.request("PUT", "agents/builtin-quick-answer", json={"name": "教辅智能搜索", "config": {
        "agent_mode": "quick-answer", "model_id": state["models"]["chat"],
        "rerank_model_id": state["models"].get("rerank", ""), "kb_selection_mode": "all",
        "retrieve_kb_only_when_mentioned": False, "enable_rewrite": True, "enable_query_expansion": True,
        "citation_enabled": True, "temperature": 0.2, "max_completion_tokens": 2048,
        "web_search_enabled": False, "memory_enabled": False,
        "fallback_strategy": "fixed", "fallback_response": "现有知识库资料不足，请联系系统管理员确认。",
        "system_prompt": "你是教辅知识库智能助手。业务流程、规则、客户管理和教学服务问题应先检索知识库，不要因缺少特定关键词判定超出范围。回答必须基于检索到的资料并引用来源；区分已确认信息与缺失信息，不得编造流程。FAQ 与文档分别检索。私人话术只属于当前账号，不得请求或披露他人的私人数据。"}})
    if not state.get("rules_service_key"):
        result = api.request("POST", f"tenants/{state['shared_tenant_id']}/api-keys", json={
            "name": "教辅规则同步（仅规则库）", "full_access": False,
            "knowledge_base_ids": [state["knowledge_bases"]["规则通知"]],
            "capabilities": ["ingest", "retrieve"], "expires_at_unix": int(time.time()) + 365 * 86400})
        state["rules_service_key"] = result["data"]["token"]
        checkpoint()
    if not args.bridge_env.exists():
        args.bridge_env.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(args.bridge_env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write("EDU_ENCRYPTION_KEY=" + secrets.token_hex(32) + "\nEDU_ADMIN_USER_IDS=" + state["user_id"] + "\n")
    print("Native account, remote models and shared libraries prepared", flush=True)


if __name__ == "__main__":
    main()

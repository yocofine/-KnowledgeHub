"""Serial, checkpointed import of active files and the selected admin's content.

Run in a bounded job container on the server. Never restore soft-deleted records.
"""
import argparse
from hashlib import sha256
import json
import mimetypes
from pathlib import Path
import tempfile
import time
import httpx
from bootstrap import API
from migration import binding_plan, validate_snapshot


def checkpoint(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
        json.dump(value, temporary, ensure_ascii=False, indent=2)
        name = temporary.name
    Path(name).replace(path)


def digest(path):
    result = sha256()
    with path.open("rb") as file:
        while data := file.read(1024 * 1024):
            result.update(data)
    return result.hexdigest()


def wait_for_file(api, item_id, deadline=3600):
    started = time.monotonic()
    last = None
    while time.monotonic() - started < deadline:
        row = api.request("GET", "knowledge/" + item_id)["data"]
        status = row.get("parse_status")
        if status != last:
            print(json.dumps({"knowledge_id": item_id, "status": status}), flush=True)
            last = status
        if status == "completed":
            return row
        if status in {"failed", "error", "cancelled", "interrupted"}:
            raise RuntimeError(f"File task {item_id} ended with status {status}; leaving checkpoint and old site intact")
        time.sleep(5)
    raise RuntimeError("File task timed out; do not blindly create a duplicate")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:18080")
    parser.add_argument("--bridge-origin", default="http://127.0.0.1:18082")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--mode", choices=("files", "content"), required=True)
    parser.add_argument("--retry-failed", action="store_true", help="Retry only existing failed checkpoint tasks after fixing their cause")
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    mapping = json.loads(args.map.read_text(encoding="utf-8"))
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    tables = validate_snapshot(snapshot)
    plan = binding_plan(snapshot, mapping)
    if plan["pending_accounts"] or not plan["personal_accounts"]:
        raise ValueError("账号绑定未完成，不执行导入")
    account = next(row for row in plan["personal_accounts"] if row["old_username"] == "admin")
    if state["email"].casefold() != account["email"].casefold():
        raise ValueError("新旧管理员邮箱绑定不匹配")
    api = API(args.origin)
    login = api.request("POST", "auth/login", json={"email": state["email"], "password": state["password"]})
    if login["user"]["id"] != state["user_id"]:
        raise ValueError("新管理员 ID 与既有绑定不一致")
    api.token = login["token"]
    switched = api.request("POST", "auth/switch-tenant", json={"tenant_id": state["shared_tenant_id"]})
    api.token = switched["token"]
    def renew_token():
        # Long, serial cloud parsing can outlive a short native access token.
        # Authenticate from the private checkpoint, never log or hard-code it.
        fresh = api.client.post("auth/login", json={"email": state["email"], "password": state["password"]})
        if fresh.status_code != 200:
            raise RuntimeError("Migration session renewal failed; old site left intact")
        token = fresh.json()["token"]
        selected = api.client.post("auth/switch-tenant", headers={"Authorization": "Bearer " + token},
                                   json={"tenant_id": state["shared_tenant_id"]})
        if selected.status_code != 200:
            raise RuntimeError("Migration workspace renewal failed")
        return selected.json()["token"]
    api.on_unauthorized = renew_token
    report = json.loads(args.report.read_text(encoding="utf-8")) if args.report.exists() else {"files": {}, "scripts": {}, "rules": {}, "faq": {}}
    if args.mode == "files":
        manifest = json.loads(args.assets.read_text(encoding="utf-8"))
        assets = {row["object_key"]: row for row in manifest["assets"]}
        versions = {row["id"]: row for row in tables["document_versions"]}
        sections = {row["id"]: row["name"] for row in tables["sections"]}
        documents = sorted((row for row in tables["documents"] if not row["deleted_at"]),
                           key=lambda row: versions[row["current_version_id"]]["size_bytes"])
        for index, document in enumerate(documents, 1):
            version = versions[document["current_version_id"]]
            section = sections[document["section_id"]]
            kb_id = state["knowledge_bases"][section]
            entry = report["files"].get(document["id"])
            if entry:
                if entry["sha256"] != version["checksum_sha256"] or entry["kb_id"] != kb_id:
                    raise ValueError("文件检查点与原始版本不一致")
                current = api.request("GET", "knowledge/" + entry["knowledge_id"])["data"]
                if current.get("knowledge_base_id") != kb_id:
                    raise ValueError("现有任务不属于目标知识库，不进行重试")
                if args.retry_failed and current.get("parse_status") in {"failed", "error", "interrupted", "cancelled"}:
                    api.request("POST", f"knowledge/{entry['knowledge_id']}/reparse", json={"process_config": {
                        "summary_enabled": False, "parser_engine_rules": [
                            {"file_types": ["pdf", "doc", "docx", "ppt", "pptx"], "engine": "mineru_cloud"}]}})
                wait_for_file(api, entry["knowledge_id"])
                entry["verified"] = True
                checkpoint(args.report, report)
                continue
            asset = assets[version["object_key"]]
            path = (args.assets.parent / asset["backup_file"]).resolve()
            if args.assets.parent.resolve() not in path.parents or asset["status"] != "ok" or digest(path) != version["checksum_sha256"]:
                raise ValueError("原件缺失或校验失败，停止迁移")
            metadata = {"legacy_document_id": document["id"], "legacy_version_id": version["id"],
                        "legacy_sha256": version["checksum_sha256"], "legacy_filename": version["file_name"],
                        "legacy_title": document["normalized_name"], "legacy_tags": version.get("tags", "")}
            print(json.dumps({"file": index, "total": len(documents), "legacy_id": document["id"], "bytes": version["size_bytes"]}), flush=True)
            process = {"summary_enabled": False, "parser_engine_rules": [
                {"file_types": ["pdf", "doc", "docx", "ppt", "pptx"], "engine": "mineru_cloud"}]}
            with path.open("rb") as file:
                response = api.client.post(f"knowledge-bases/{kb_id}/knowledge/file",
                    headers={"Authorization": "Bearer " + api.token},
                    files={"file": (version["file_name"], file, mimetypes.guess_type(version["file_name"])[0] or "application/octet-stream")},
                    data={"fileName": version["file_name"], "metadata": json.dumps(metadata, ensure_ascii=False),
                          "process_config": json.dumps(process)}, timeout=300)
            result = response.json()
            if response.status_code not in (200, 201, 409) or not result.get("data", {}).get("id"):
                raise RuntimeError(f"File upload failed HTTP {response.status_code}; source not changed")
            knowledge_id = result["data"]["id"]
            report["files"][document["id"]] = {"knowledge_id": knowledge_id, "kb_id": kb_id,
                "sha256": version["checksum_sha256"], "verified": False, "deduplicated": response.status_code == 409}
            checkpoint(args.report, report)
            wait_for_file(api, knowledge_id)
            report["files"][document["id"]]["verified"] = True
            checkpoint(args.report, report)
        print("All active files uploaded and parsing verified", flush=True)
    else:
        bridge = API(args.bridge_origin, api.token)
        for kind, table in (("scripts", "scripts"), ("rules", "rules")):
            for row in tables[table]:
                if row["deleted_at"] or (kind == "scripts" and row["owner_id"] != account["old_user_id"]):
                    continue
                payload = {"title": row["title"], "content": row["content"], "group_name": row["group_name"], "legacy_id": row["id"], "tags": row.get("tags", "")}
                result = bridge.request("POST", f"edu/{kind}/import", json=payload)["data"]
                report[kind][row["id"]] = {"id": result["id"]}
                checkpoint(args.report, report)
        # Deleted FAQ rows are not resurrected. The standalone native FAQ KB
        # exists even when the legacy live set is empty.
        entries = [{"standard_question": row["question"], "answers": [row["answer"]],
                    "tag_name": row["category"], "is_enabled": True}
                   for row in tables["faq_items"] if not row["deleted_at"]]
        if entries and not report["faq"]:
            result = api.request("POST", f"knowledge-bases/{state['knowledge_bases']['FAQ库']}/faq/entries",
                                 json={"entries": entries, "mode": "append"})
            report["faq"] = {"submitted": len(entries), "result": result.get("data")}
            checkpoint(args.report, report)
        print(json.dumps({"scripts": len(report["scripts"]), "rules": len(report["rules"]), "active_faq": len(entries),
                          "historical_rules_pushed": False}), flush=True)


if __name__ == "__main__":
    main()

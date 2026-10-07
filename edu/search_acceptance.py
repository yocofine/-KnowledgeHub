"""Verify embedding/retrieval and a streaming knowledge answer without logging keys."""
import argparse
import json
from pathlib import Path
import httpx
from bootstrap import API
from native_import import checkpoint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    api = API("http://127.0.0.1:18080")
    api.token = api.request("POST", "auth/login", json={"email": state["email"], "password": state["password"]})["token"]
    api.token = api.request("POST", "auth/switch-tenant", json={"tenant_id": state["shared_tenant_id"]})["token"]
    kb = next(value for name, value in state["knowledge_bases"].items() if "教辅资料" in name)
    matches = api.request("POST", f"knowledge-bases/{kb}/hybrid-search", json={"query_text": "教辅服务流程", "match_count": 5})["data"]
    assert matches, "No knowledge retrieved"
    session = api.request("POST", "sessions", json={"title": "迁移验收：知识检索"})["data"]
    types, events = {}, []
    error_events = []
    with api.client.stream("POST", f"agent-chat/{session['id']}", headers={"Authorization": "Bearer " + api.token},
            json={"query": "教辅服务流程需要注意哪些事项？请根据知识库资料回答并引用来源。",
                  "agent_id": "builtin-quick-answer", "agent_enabled": False,
                  "summary_model_id": state["models"]["chat"], "knowledge_base_ids": list(state["knowledge_bases"].values()),
                  "channel": "web"}, timeout=180) as response:
        assert response.status_code == 200
        current_type = ""
        for line in response.iter_lines():
            if line.startswith("event:"):
                current_type = line[6:].strip()
            elif line.startswith("data:"):
                raw = line[5:].strip()
                if raw == "[DONE]":
                    continue
                try:
                    value = json.loads(raw)
                except ValueError:
                    continue
                kind = value.get("type") or current_type or "unknown"
                types[kind] = types.get(kind, 0) + 1
                events.append(value)
                if "error" in kind.lower():
                    error_events.append(kind)
    report = {"retrieved_count": len(matches), "event_counts": types, "error_event_types": error_events,
              "session_id": session["id"], "stream_received": bool(events)}
    checkpoint(args.report, report)
    print(json.dumps(report, ensure_ascii=False))
    if error_events or not events:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

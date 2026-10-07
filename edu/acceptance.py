"""Online acceptance for native JWTs, private scripts and shared rules.

Creates a disposable test identity; its ID is recorded for operator deactivation.
Never calls the group robot or prints credentials.
"""
import argparse
import json
from pathlib import Path
import secrets
import httpx
from bootstrap import API
from native_import import checkpoint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    native = API("http://127.0.0.1:18080")
    root = native.request("POST", "auth/login", json={"email": state["email"], "password": state["password"]})
    native.token = root["token"]
    assert root["user"]["id"] == state["user_id"] and root["user"]["is_system_admin"] is True
    native.token = native.request("POST", "auth/switch-tenant", json={"tenant_id": state["shared_tenant_id"]})["token"]
    report = {"checks": [], "test_account": {}}
    identity = "edu-check-" + secrets.token_hex(6)
    email = identity + "@example.invalid"
    password = "Aa1!" + secrets.token_urlsafe(12)
    response = native.client.post("system/admin/users/create", headers={"Authorization": "Bearer " + native.token},
                                  json={"username": identity, "email": email, "password": password})
    assert response.status_code in (200, 201)
    user = response.json()["user"]
    report["test_account"] = {"id": user["id"], "email": email, "username": identity}
    checkpoint(args.report, report)
    normal = API("http://127.0.0.1:18080")
    normal.token = normal.request("POST", "auth/login", json={"email": email, "password": password})["token"]
    with httpx.Client(base_url="http://127.0.0.1:18082/api/v1/edu/", timeout=20) as bridge:
        admin_headers = {"Authorization": "Bearer " + native.token}
        user_headers = {"Authorization": "Bearer " + normal.token}
        records = bridge.get("scripts", headers=admin_headers).json()["data"]
        assert len(records) == 3
        assert bridge.get("scripts", headers=user_headers).json()["data"] == []
        content = {"title": "Disposable isolation check", "content": "temporary test only", "group_name": "test"}
        response = bridge.post("scripts", headers=user_headers, json=content)
        assert response.status_code == 200
        item_id = response.json()["data"]["id"]
        for method in ("GET", "PUT", "DELETE"):
            options = {"json": content} if method == "PUT" else {}
            assert bridge.request(method, "scripts/" + item_id, headers=admin_headers, **options).status_code == 404
        report["checks"].append("system_admin_cannot_read_edit_delete_other_users_scripts")
        assert bridge.get("scripts/" + records[0]["id"], headers=user_headers).status_code == 404
        assert bridge.post("scripts", headers=user_headers, json={**content, "owner_id": state["user_id"]}).status_code == 422
        assert bridge.put("scripts/" + item_id, headers=user_headers, json={**content, "content": "edited"}).status_code == 200
        assert bridge.delete("scripts/" + item_id, headers=user_headers).status_code == 200
        report["checks"].append("ordinary_user_owns_full_crud_and_cannot_forge_owner")
        rows = bridge.get("rules", headers=user_headers).json()["data"]
        assert len(rows) == 5 and all(row["state"] == "synced" for row in rows)
        assert bridge.post("rules", headers=user_headers, json=content).status_code == 403
        assert bridge.delete("rules/" + rows[0]["id"], headers=user_headers).status_code == 403
        assert bridge.post("rules/" + rows[0]["id"] + "/push", headers=user_headers).status_code == 403
        assert bridge.get("dingtalk", headers=user_headers).status_code == 403
        assert bridge.get("scripts").status_code in (401, 403)
        report["checks"].append("shared_rules_read_only_and_robot_settings_admin_only")
        robot = bridge.get("dingtalk", headers=admin_headers).json()["data"]
        assert robot["enabled"] and robot["webhook_configured"] and robot["secret_configured"]
        report["checks"].append("existing_robot_credentials_migrated_without_exposure_or_push")
    report["passed"] = True
    checkpoint(args.report, report)
    print(json.dumps({"passed": True, "checks": report["checks"], "test_user_id": user["id"]}))


if __name__ == "__main__":
    main()

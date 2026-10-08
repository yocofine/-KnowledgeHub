import importlib
import os
from pathlib import Path
import tempfile
import unittest

try:
    from fastapi.testclient import TestClient
    HAVE_API_TESTS = True
except ImportError:
    HAVE_API_TESTS = False


@unittest.skipUnless(HAVE_API_TESTS, "API tests require the project's FastAPI/httpx runtime")
class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        os.environ["EDU_STORE_PATH"] = str(Path(cls.directory.name) / "initial.sqlite")
        os.environ["EDU_ENCRYPTION_KEY"] = "a" * 64
        cls.main = importlib.import_module("bridge.main")

    @classmethod
    def tearDownClass(cls):
        cls.main.app.dependency_overrides.clear()
        cls.directory.cleanup()

    def setUp(self):
        self.path = tempfile.TemporaryDirectory()
        self.main.store = self.main.Store(Path(self.path.name) / "test.sqlite")
        self.identity = self.main.Actor("alice", "Alice", False)
        self.main.app.dependency_overrides[self.main.actor] = lambda: self.identity
        self.client = TestClient(self.main.app)

    def tearDown(self):
        self.client.close()
        self.main.app.dependency_overrides.clear()
        self.path.cleanup()

    def content(self):
        return {"title": "test", "content": "private", "group_name": "g"}

    def test_normal_user_has_full_own_script_crud(self):
        response = self.client.post("/api/v1/edu/scripts", json=self.content())
        self.assertEqual(response.status_code, 200)
        item_id = response.json()["data"]["id"]
        self.assertEqual(self.client.get(f"/api/v1/edu/scripts/{item_id}").status_code, 200)
        self.assertEqual(self.client.put(f"/api/v1/edu/scripts/{item_id}", json=self.content()).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/v1/edu/scripts/{item_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/edu/scripts/{item_id}").status_code, 404)

    def test_even_admin_cannot_read_modify_or_delete_another_user(self):
        item_id = self.client.post("/api/v1/edu/scripts", json=self.content()).json()["data"]["id"]
        self.identity = self.main.Actor("root", "Admin", True)
        self.assertEqual(self.client.get(f"/api/v1/edu/scripts/{item_id}").status_code, 404)
        self.assertEqual(self.client.put(f"/api/v1/edu/scripts/{item_id}", json=self.content()).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/v1/edu/scripts/{item_id}").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/edu/scripts?owner_id=alice").json()["data"], [])

    def test_owner_id_in_body_is_rejected(self):
        response = self.client.post("/api/v1/edu/scripts", json={**self.content(), "owner_id": "root"})
        self.assertEqual(response.status_code, 422)

    def test_rules_are_shared_read_only_for_normal_user(self):
        self.identity = self.main.Actor("root", "Admin", True)
        item_id = self.client.post("/api/v1/edu/rules/import", json={**self.content(), "legacy_id": "old-rule"}).json()["data"]["id"]
        self.identity = self.main.Actor("alice", "Alice", False)
        self.assertEqual(len(self.client.get("/api/v1/edu/rules").json()["data"]), 1)
        self.assertEqual(self.client.post("/api/v1/edu/rules", json=self.content()).status_code, 403)
        self.assertEqual(self.client.put(f"/api/v1/edu/rules/{item_id}", json=self.content()).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/v1/edu/rules/{item_id}").status_code, 403)
        self.assertEqual(self.client.post(f"/api/v1/edu/rules/{item_id}/push").status_code, 403)

    def test_robot_settings_not_visible_to_normal_user(self):
        self.assertEqual(self.client.get("/api/v1/edu/dingtalk").status_code, 403)

    def test_robot_secrets_are_redacted_and_preserved(self):
        self.identity = self.main.Actor("root", "Admin", True)
        values = {"enabled": True, "webhook": "https://oapi.dingtalk.com/robot/send?access_token=private", "secret": "SEC-private"}
        response = self.client.put("/api/v1/edu/dingtalk", json=values)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("SEC-private", response.text)
        self.assertNotIn("access_token", response.text)
        self.client.put("/api/v1/edu/dingtalk", json={"enabled": False})
        self.assertEqual(self.main.settings()["dingtalk"]["secret"], "SEC-private")

    def test_anonymous_requests_cannot_read_data(self):
        self.main.app.dependency_overrides.clear()
        self.assertIn(self.client.get("/api/v1/edu/scripts").status_code, (401, 403))

    def test_cloud_never_leaks_other_users_questions(self):
        self.client.post("/api/v1/edu/questions", json={"question": "my question", "source_id": "m1"})
        self.identity = self.main.Actor("root", "Admin", True)
        self.assertEqual(self.client.get("/api/v1/edu/questions").json()["data"], [])

    def test_no_cache_on_private_responses(self):
        self.assertEqual(self.client.get("/api/v1/edu/scripts").headers["cache-control"], "no-store")

    def test_settings_are_encrypted_at_rest(self):
        self.main.store.save_settings(self.main.cipher, {"test": "private-plain-secret"})
        self.assertNotIn(b"private-plain-secret", Path(self.main.store.path).read_bytes())

    def test_group_crud_for_normal_user_retains_scripts(self):
        group = self.client.post("/api/v1/edu/script-groups", json={"name": " my group "}).json()["data"]
        self.assertEqual(group["name"], "my group")
        item = self.client.post("/api/v1/edu/scripts", json={**self.content(), "group_id": group["id"]}).json()["data"]
        self.assertEqual(item["group_name"], "my group")
        response = self.client.put(f'/api/v1/edu/script-groups/{group["id"]}', json={"name": "renamed"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["count"], 1)
        self.assertEqual(self.client.get(f'/api/v1/edu/scripts/{item["id"]}').json()["data"]["group_name"], "renamed")
        self.assertEqual(self.client.delete(f'/api/v1/edu/script-groups/{group["id"]}').status_code, 200)
        self.assertEqual(self.client.get(f'/api/v1/edu/scripts/{item["id"]}').json()["data"]["group_name"], "未分组")

    def test_group_api_ignores_admin_bypass_and_rejects_owner_body(self):
        group = self.client.post("/api/v1/edu/script-groups", json={"name": "private"}).json()["data"]
        self.identity = self.main.Actor("root", "Admin", True)
        self.assertEqual(self.client.get("/api/v1/edu/script-groups?owner_id=alice").json()["data"], [])
        self.assertEqual(self.client.put(f'/api/v1/edu/script-groups/{group["id"]}', json={"name": "steal"}).status_code, 404)
        self.assertEqual(self.client.delete(f'/api/v1/edu/script-groups/{group["id"]}').status_code, 404)
        self.assertEqual(self.client.post("/api/v1/edu/scripts", json={**self.content(), "group_id": group["id"]}).status_code, 404)
        self.assertEqual(self.client.post("/api/v1/edu/script-groups", json={"name": "x", "owner_id": "alice"}).status_code, 422)

    def test_group_name_validation_and_duplicate_feedback(self):
        for name in ("", "   ", "x" * 121):
            self.assertEqual(self.client.post("/api/v1/edu/script-groups", json={"name": name}).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/edu/script-groups", json={"name": "未分组"}).status_code, 409)
        self.client.post("/api/v1/edu/script-groups", json={"name": "same"})
        self.assertEqual(self.client.post("/api/v1/edu/script-groups", json={"name": "same"}).status_code, 409)

    def test_group_anonymous_access_requires_login(self):
        self.main.app.dependency_overrides.clear()
        for method in (self.client.get, self.client.post):
            self.assertIn(method("/api/v1/edu/script-groups").status_code, (401, 403))

    def test_rule_groups_shared_read_but_mutations_are_manager_only(self):
        self.identity = self.main.Actor("root", "Admin", True)
        group = self.client.post("/api/v1/edu/rule-groups", json={"name": "shared"}).json()["data"]
        self.identity = self.main.Actor("alice", "Alice", False)
        self.assertEqual(self.client.get("/api/v1/edu/rule-groups").json()["data"], [group])
        self.assertEqual(self.client.post("/api/v1/edu/rule-groups", json={"name": "new"}).status_code, 403)
        self.assertEqual(self.client.put(f'/api/v1/edu/rule-groups/{group["id"]}', json={"name": "rename"}).status_code, 403)
        self.assertEqual(self.client.delete(f'/api/v1/edu/rule-groups/{group["id"]}').status_code, 403)
        self.assertEqual(self.client.get("/api/v1/edu/script-groups").json()["data"], [])

    def test_rule_group_crud_preserves_rule(self):
        self.identity = self.main.Actor("root", "Admin", True)
        group = self.client.post("/api/v1/edu/rule-groups", json={"name": "shared"}).json()["data"]
        rule = self.client.post("/api/v1/edu/rules", json={**self.content(), "group_id": group["id"], "push": False}).json()["data"]
        self.assertEqual(self.client.put(f'/api/v1/edu/rule-groups/{group["id"]}', json={"name": "renamed"}).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/edu/rules").json()["data"][0]["group_name"], "renamed")
        self.assertEqual(self.client.delete(f'/api/v1/edu/rule-groups/{group["id"]}').status_code, 200)
        self.assertEqual(self.client.get("/api/v1/edu/rules").json()["data"][0]["id"], rule["id"])
        self.assertEqual(self.client.get("/api/v1/edu/rules").json()["data"][0]["group_name"], "未分组")

    def test_rule_group_duplicates_and_invalid_names_are_rejected(self):
        self.identity = self.main.Actor("root", "Admin", True)
        self.client.post("/api/v1/edu/rule-groups", json={"name": "same"})
        self.assertEqual(self.client.post("/api/v1/edu/rule-groups", json={"name": "same"}).status_code, 409)
        self.assertEqual(self.client.post("/api/v1/edu/rule-groups", json={"name": " "}).status_code, 422)


class RendererTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_API_TESTS, "Renderer tests require httpx")
    def test_legacy_formatting_preserves_color_bold_italic_and_lines(self):
        from bridge.dingtalk import rich_text
        rendered = rich_text('<div>A<b>bold</b>word</div><p><span style="font-weight:bold;font-style:italic;color:#00ff00">green</span><br>line</p>')
        self.assertIn(" **bold** ", rendered)
        self.assertIn('<font color="#00FF00">', rendered)
        self.assertIn("*", rendered)
        self.assertIn("\nline", rendered)
        self.assertNotIn("<b>", rendered)


if __name__ == "__main__":
    unittest.main()

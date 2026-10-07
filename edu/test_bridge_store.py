import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("edu_store", Path(__file__).parent / "bridge/store.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = module.Store(Path(self.temp.name) / "edu.sqlite")
        self.content = {"title": "private", "content": "secret", "group_name": "group"}
        self.a = self.store.save_script("normal-user", self.content)
        self.b = self.store.save_script("system-admin", {**self.content, "content": "admin-only"})

    def tearDown(self):
        self.temp.cleanup()

    def test_user_only_sees_own_records(self):
        self.assertEqual([x["id"] for x in self.store.scripts("normal-user")], [self.a["id"]])

    def test_admin_cannot_see_users_script(self):
        self.assertIsNone(self.store.script("system-admin", self.a["id"]))
        self.assertEqual([x["id"] for x in self.store.scripts("system-admin")], [self.b["id"]])

    def test_user_cannot_see_admin_script(self):
        self.assertIsNone(self.store.script("normal-user", self.b["id"]))

    def test_admin_cannot_modify_another_user(self):
        self.assertIsNone(self.store.save_script("system-admin", self.content, self.a["id"]))
        self.assertEqual(self.store.script("normal-user", self.a["id"])["content"], "secret")

    def test_admin_cannot_delete_another_user(self):
        self.assertFalse(self.store.delete_script("system-admin", self.a["id"]))

    def test_ordinary_user_can_edit_and_delete_own(self):
        self.assertEqual(self.store.save_script("normal-user", {**self.content, "content": "edited"}, self.a["id"])["content"], "edited")
        self.assertTrue(self.store.delete_script("normal-user", self.a["id"]))
        self.assertIsNone(self.store.script("normal-user", self.a["id"]))

    def test_sql_injection_does_not_expand_owner_scope(self):
        self.assertEqual(self.store.scripts("' OR 1=1--"), [])
        self.assertIsNone(self.store.script("normal-user", "' OR 1=1--"))

    def test_legacy_import_is_idempotent_and_scoped(self):
        payload = {**self.content, "legacy_id": "old-script"}
        first = self.store.save_script("normal-user", payload)
        second = self.store.save_script("normal-user", payload)
        other = self.store.save_script("system-admin", payload)
        self.assertEqual(first["id"], second["id"])
        self.assertNotEqual(first["id"], other["id"])

    def test_question_cloud_is_private_and_idempotent(self):
        self.store.question("normal-user", "Question", "m1")
        self.store.question("normal-user", "Question", "m1")
        self.store.question("normal-user", "question", "m2")
        self.store.question("system-admin", "private admin question", "m3")
        rows = self.store.cloud("normal-user")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 2)
        self.assertNotIn("private admin question", str(rows))

    def test_rule_migration_does_not_post_to_group(self):
        rule = self.store.save_rule("admin", {**self.content, "legacy_id": "rule-old"})
        self.assertEqual(rule["push_requested"], 0)
        self.assertEqual(rule["push_status"], "not_requested")

    def test_changed_rule_is_not_marked_synced_by_old_job(self):
        rule = self.store.save_rule("admin", self.content)
        self.store.save_rule("admin", {**self.content, "content": "changed"}, rule["id"])
        self.store.mark_rule(rule["id"], rule["version"], "synced", "remote-id")
        current = self.store.rule(rule["id"])
        self.assertEqual(current["state"], "pending")
        self.assertEqual(current["native_id"], "remote-id")


if __name__ == "__main__":
    unittest.main()

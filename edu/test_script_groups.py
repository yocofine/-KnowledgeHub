import importlib.util
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("group_store", Path(__file__).parent / "bridge/store.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ScriptGroupsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "groups.sqlite"
        self.store = module.Store(self.path)
        self.content = {"title": "test", "content": "complete private content", "group_name": "g", "tags": "tag"}

    def tearDown(self):
        self.temp.cleanup()

    def test_empty_groups_persist_after_restart(self):
        group = self.store.save_script_group("alice", "empty")
        restarted = module.Store(self.path)
        self.assertEqual(restarted.script_groups("alice"), [{**group, "count": 0}])

    def test_names_are_unique_only_within_owner(self):
        a = self.store.save_script_group("alice", "same")
        b = self.store.save_script_group("admin", "same")
        self.assertNotEqual(a["id"], b["id"])
        with self.assertRaises(module.ScriptGroupError) as error:
            self.store.save_script_group("alice", "same")
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(len(self.store.script_groups("alice")), 1)

    def test_rename_updates_only_owners_scripts_and_keeps_id(self):
        a = self.store.save_script("alice", self.content)
        b = self.store.save_script("admin", self.content)
        renamed = self.store.save_script_group("alice", "new", a["group_id"])
        self.assertEqual(renamed["id"], a["group_id"])
        self.assertEqual(renamed["count"], 1)
        self.assertEqual(self.store.script("alice", a["id"])["group_name"], "new")
        self.assertEqual(self.store.script("admin", b["id"])["group_name"], "g")

    def test_duplicate_rename_rolls_back_all_changes(self):
        a = self.store.save_script("alice", self.content)
        self.store.save_script_group("alice", "existing")
        with self.assertRaises(module.ScriptGroupError):
            self.store.save_script_group("alice", "existing", a["group_id"])
        self.assertEqual(self.store.script("alice", a["id"])["group_name"], "g")

    def test_admin_cannot_rename_delete_or_assign_foreign_group(self):
        a = self.store.save_script("alice", self.content)
        with self.assertRaises(module.ScriptGroupError):
            self.store.save_script_group("admin", "stolen", a["group_id"])
        self.assertFalse(self.store.delete_script_group("admin", a["group_id"]))
        with self.assertRaises(module.ScriptGroupError):
            self.store.save_script("admin", {**self.content, "group_id": a["group_id"]})
        self.assertEqual(self.store.scripts("admin"), [])
        self.assertEqual(self.store.script_groups("admin"), [])

    def test_delete_preserves_content_and_moves_only_own_scripts(self):
        a = self.store.save_script("alice", self.content)
        b = self.store.save_script("admin", self.content)
        self.assertTrue(self.store.delete_script_group("alice", a["group_id"]))
        saved = self.store.script("alice", a["id"])
        self.assertEqual(saved["group_name"], "未分组")
        self.assertIsNone(saved["group_id"])
        for field in ("id", "title", "content", "tags", "created_at"):
            self.assertEqual(saved[field], a[field])
        restarted = module.Store(self.path)
        self.assertEqual(restarted.script_groups("alice"), [])
        self.assertEqual(restarted.script("admin", b["id"])["group_name"], "g")

    def test_stale_editor_uses_current_group_name_after_rename(self):
        a = self.store.save_script("alice", self.content)
        self.store.save_script_group("alice", "renamed", a["group_id"])
        updated = self.store.save_script("alice", {**self.content, "group_id": a["group_id"]}, a["id"])
        self.assertEqual(updated["group_name"], "renamed")
        self.assertEqual(len(self.store.script_groups("alice")), 1)

    def test_deleted_group_cannot_be_resurrected_by_stale_editor(self):
        a = self.store.save_script("alice", self.content)
        self.store.delete_script_group("alice", a["group_id"])
        with self.assertRaises(module.ScriptGroupError):
            self.store.save_script("alice", {**self.content, "group_id": a["group_id"]}, a["id"])
        self.assertEqual(self.store.script_groups("alice"), [])
        self.assertEqual(self.store.script("alice", a["id"])["group_name"], "未分组")

    def test_explicit_ungrouped_creates_no_group(self):
        saved = self.store.save_script("alice", {**self.content, "group_id": None})
        self.assertEqual(saved["group_name"], "未分组")
        self.assertEqual(self.store.script_groups("alice"), [])

    def test_legacy_database_backfill_is_private_and_idempotent(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO scripts(id,owner_id,title,content,group_name,created_at,updated_at) "
                       "VALUES('legacy','alice','title','original','old','before','before')")
            db.execute("INSERT INTO scripts(id,owner_id,title,content,group_name,created_at,updated_at,deleted) "
                       "VALUES('deleted','alice','title','secret','deleted-group','before','before',1)")
        first = module.Store(self.path)
        group = first.script_groups("alice")[0]
        second = module.Store(self.path)
        self.assertEqual(second.script_groups("alice"), [group])
        self.assertEqual(second.script_groups("admin"), [])
        self.assertEqual(second.script("alice", "legacy")["content"], "original")
        self.assertEqual(second.script("alice", "legacy")["updated_at"], "before")

    def test_deleted_scripts_do_not_inflate_group_counts(self):
        a = self.store.save_script("alice", self.content)
        self.store.delete_script("alice", a["id"])
        self.assertEqual(self.store.script_groups("alice")[0]["count"], 0)

    def test_rules_have_separate_shared_groups(self):
        script = self.store.save_script("alice", self.content)
        rule = self.store.save_rule("admin", self.content)
        self.assertNotEqual(script["group_id"], rule["group_id"])
        self.assertEqual(self.store.rule_groups()[0]["count"], 1)
        with self.assertRaises(module.ScriptGroupError):
            self.store.save_rule("admin", {**self.content, "group_id": script["group_id"]})

    def test_rule_rename_reindexes_metadata_without_resending_notifications(self):
        rule = self.store.save_rule("admin", self.content, push=False)
        self.store.mark_rule(rule["id"], rule["version"], "synced", "native-id", push_status="sent")
        self.store.save_rule_group("renamed", rule["group_id"])
        changed = self.store.rule(rule["id"])
        self.assertEqual(changed["group_name"], "renamed")
        self.assertEqual(changed["state"], "pending")
        self.assertEqual(changed["native_id"], "native-id")
        self.assertEqual(changed["push_status"], "sent")
        self.assertEqual(changed["push_requested"], 0)
        self.assertEqual(changed["content"], rule["content"])

    def test_rule_group_delete_retains_rules_and_does_not_resurrect_on_restart(self):
        rule = self.store.save_rule("admin", self.content, push=False)
        self.assertTrue(self.store.delete_rule_group(rule["group_id"]))
        changed = self.store.rule(rule["id"])
        self.assertEqual(changed["group_name"], "未分组")
        self.assertEqual(changed["deleted"], 0)
        self.assertEqual(changed["content"], rule["content"])
        self.assertEqual(module.Store(self.path).rule_groups(), [])

    def test_rule_stale_editor_after_delete_is_rejected(self):
        rule = self.store.save_rule("admin", self.content)
        self.store.delete_rule_group(rule["group_id"])
        with self.assertRaises(module.ScriptGroupError):
            self.store.save_rule("admin", {**self.content, "group_id": rule["group_id"]}, rule["id"])

    def test_existing_rule_group_names_backfill_without_content_changes(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO rules(id,title,content,group_name,operator,created_at,updated_at) "
                       "VALUES('old-rule','title','body','legacy','admin','before','before')")
        restarted = module.Store(self.path)
        self.assertEqual(restarted.rule_groups()[0]["name"], "legacy")
        self.assertEqual(restarted.rule("old-rule")["content"], "body")
        self.assertEqual(restarted.rule("old-rule")["updated_at"], "before")


if __name__ == "__main__":
    unittest.main()

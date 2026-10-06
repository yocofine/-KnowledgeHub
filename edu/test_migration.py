"""Offline tests. No production DB, network credentials or containers required."""
from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest

import migration
import setup


def snapshot_fixture():
    connection = sqlite3.connect(":memory:")
    for name, field_list in migration.TABLES.items():
        columns = ",".join(f"`{field}`" for field in field_list.split())
        connection.execute(f"CREATE TABLE `{name}` ({columns})")
    connection.execute("ALTER TABLE users ADD password_hash")
    connection.execute("CREATE TABLE system_settings (encrypted_value)")
    connection.execute("INSERT INTO system_settings VALUES ('must-not-export')")
    connection.executemany(
        "INSERT INTO users (id,username,role,disabled,password_hash) VALUES (?,?,?,?,?)",
        [(1, "admin", "admin", 0, "secret-password-hash"), (2, "user1", "user", 0, "another-hash")],
    )
    connection.executemany(
        "INSERT INTO scripts (id,title,content,group_name,owner_id,deleted_at) VALUES (?,?,?,?,?,?)",
        [("a", "admin script", "private A", "g", 1, None),
         ("b", "user script", "private B", "g", 2, None),
         ("deleted", "deleted script", "archived", "g", 2, "2026-01-01")],
    )
    result = migration.export_snapshot(connection, "sqlite")
    connection.close()
    return result


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = snapshot_fixture()

    def test_secret_fields_are_never_exported(self):
        data = str(self.snapshot)
        self.assertNotIn("secret-password-hash", data)
        self.assertNotIn("must-not-export", data)
        self.assertNotIn("system_settings", self.snapshot["tables"])

    def test_inventory_does_not_output_script_bodies(self):
        result = migration.inventory(self.snapshot)
        self.assertNotIn("private A", str(result))
        self.assertEqual(result["active_counts"]["scripts"], 2)
        self.assertEqual([a["personal_script_count"] for a in result["accounts"]], [1, 1])

    def test_mapping_never_assigns_unmapped_user_to_admin(self):
        mapping = {"schema_version": 1, "accounts": {"admin": {"email": "admin@example.com"}}}
        result = migration.binding_plan(self.snapshot, mapping)
        self.assertEqual(result["personal_accounts"][0]["script_ids"], ["a"])
        self.assertEqual(result["pending_accounts"][0]["script_ids"], ["b"])
        self.assertFalse(result["ready_for_private_identity_checks"])
        self.assertFalse(result["writes_performed"])

    def test_disabled_user_is_not_imported(self):
        self.snapshot["tables"]["users"][0]["disabled"] = True
        mapping = {"schema_version": 1, "accounts": {"admin": {"email": "admin@example.com"}}}
        plan = migration.binding_plan(self.snapshot, mapping)
        self.assertEqual(plan["personal_accounts"], [])
        self.assertEqual(len(plan["pending_accounts"]), 2)

    def test_explicitly_excluded_user_is_archived_not_assigned_to_admin(self):
        mapping = {"schema_version": 1, "accounts": {"admin": {"email": "admin@example.com"}},
                   "excluded_accounts": ["user1"]}
        result = migration.binding_plan(self.snapshot, mapping)
        self.assertEqual(result["personal_accounts"][0]["script_ids"], ["a"])
        self.assertEqual(result["excluded_accounts"][0]["script_ids"], ["b"])
        self.assertEqual(result["pending_accounts"], [])
        self.assertTrue(result["ready_for_private_identity_checks"])

    def test_exclusion_and_binding_cannot_overlap(self):
        with self.assertRaises(ValueError):
            migration.validate_map({"schema_version": 1, "accounts": {"admin": {"email": "a@example.com"}},
                                    "excluded_accounts": ["admin"]})

    def test_orphan_owner_rejected(self):
        self.snapshot["tables"]["scripts"][0]["owner_id"] = 999
        with self.assertRaises(ValueError):
            migration.inventory(self.snapshot)

    def test_secret_field_in_snapshot_rejected(self):
        self.snapshot["tables"]["users"][0]["password_hash"] = "no"
        with self.assertRaises(ValueError):
            migration.inventory(self.snapshot)

    def test_snapshots_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            migration.save_json(path, self.snapshot)
            with self.assertRaises(FileExistsError):
                migration.save_json(path, {})
            self.assertEqual(migration.read_json(path), self.snapshot)

    def test_source_sqlite_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.db"
            sqlite3.connect(path).close()
            with migration.source_connection(path.as_uri().replace("file:", "sqlite:", 1)) as (connection, kind):
                self.assertEqual(kind, "sqlite")
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("CREATE TABLE forbidden (id)")

    def test_duplicate_emails_rejected(self):
        with self.assertRaises(ValueError):
            migration.validate_map({"schema_version": 1, "accounts": {
                "admin": {"email": "USER@example.com"}, "user1": {"email": "user@example.com"}}})

    def test_duplicate_private_tenants_rejected(self):
        with self.assertRaises(ValueError):
            migration.validate_map({"schema_version": 1, "accounts": {
                "admin": {"email": "a@example.com", "personal_tenant_id": 1},
                "user1": {"email": "b@example.com", "personal_tenant_id": 1}}})

    def test_mapping_cannot_contain_passwords(self):
        with self.assertRaises(ValueError):
            migration.validate_map({"schema_version": 1, "accounts": {
                "admin": {"email": "a@example.com", "password": "forbidden"}}})


class FakeAPI:
    def __init__(self):
        self.user = {"id": "new-user-id", "email": "new@example.com", "is_active": True, "tenant_id": 7}
        self.members = [{"user_id": "new-user-id", "role": "owner", "status": "active"}]
        self.total = 1
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        if path == "/auth/validate":
            return {"success": True, "user": self.user}
        return {"success": True, "data": {"total": self.total, "members": self.members}}


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.binding = {"email": "new@example.com"}

    def test_new_email_binds_to_exclusive_personal_space(self):
        result = migration.verify_private_account(self.api, self.binding, 7)
        self.assertEqual(result["user_id"], "new-user-id")
        self.assertEqual(result["personal_tenant_id"], 7)
        self.assertFalse(result["writes_performed"])
        self.assertTrue(all(path.startswith(("/auth/validate", "/tenants/7/members")) for path in self.api.paths))

    def test_wrong_email_rejected(self):
        self.api.user["email"] = "other@example.com"
        with self.assertRaises(ValueError):
            migration.verify_private_account(self.api, self.binding, 7)

    def test_team_space_rejected(self):
        with self.assertRaises(ValueError):
            migration.verify_private_account(self.api, self.binding, 8)

    def test_any_additional_member_rejected(self):
        self.api.total = 2
        with self.assertRaises(ValueError):
            migration.verify_private_account(self.api, self.binding, 7)

    def test_suspended_owner_rejected(self):
        self.api.members[0]["status"] = "suspended"
        with self.assertRaises(ValueError):
            migration.verify_private_account(self.api, self.binding, 7)

    def test_existing_user_binding_cannot_change(self):
        with self.assertRaises(ValueError):
            migration.verify_private_account(self.api, {**self.binding, "user_id": "different"}, 7)

    def test_remote_plaintext_token_rejected(self):
        with self.assertRaises(ValueError):
            migration.NativeAPI("http://server.example.com", "token")

    def test_url_cannot_contain_passwords(self):
        with self.assertRaises(ValueError):
            migration.NativeAPI("https://user:secret@example.com", "token")

    def test_redirects_are_not_followed(self):
        self.assertIsNone(migration.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.com"))


class SetupTests(unittest.TestCase):
    def test_initialize_generates_distinct_secrets_and_exact_aes_length(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            setup.initialize(path)
            values = setup.parse_env(path.read_text(encoding="utf-8"))
            setup.validate(values)
            self.assertEqual(len(values["SYSTEM_AES_KEY"].encode()), 32)
            self.assertEqual(len(set(values[name] for name in setup.SECRET_NAMES)), len(setup.SECRET_NAMES))
            with self.assertRaises(FileExistsError):
                setup.initialize(path)

    def test_public_open_registration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            setup.initialize(path)
            values = setup.parse_env(path.read_text(encoding="utf-8"))
            values["BIND_ADDRESS"] = "0.0.0.0"
            with self.assertRaises(ValueError):
                setup.validate(values)


if __name__ == "__main__":
    unittest.main()

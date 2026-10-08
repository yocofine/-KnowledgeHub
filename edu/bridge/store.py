from contextlib import contextmanager
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import sqlite3
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class ScriptGroupError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS scripts (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, title TEXT NOT NULL,
                    content TEXT NOT NULL, group_name TEXT NOT NULL, legacy_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(owner_id, legacy_id));
                CREATE INDEX IF NOT EXISTS script_owner ON scripts(owner_id, deleted, updated_at);
                CREATE TABLE IF NOT EXISTS script_groups (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(owner_id, name));
                CREATE TABLE IF NOT EXISTS rules (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL, group_name TEXT NOT NULL,
                    operator TEXT NOT NULL, legacy_id TEXT UNIQUE, native_id TEXT,
                    state TEXT NOT NULL DEFAULT 'pending', version INTEGER NOT NULL DEFAULT 1,
                    deleted INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
                    push_requested INTEGER NOT NULL DEFAULT 0, push_status TEXT NOT NULL DEFAULT 'not_requested',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, question TEXT NOT NULL,
                    normalized TEXT NOT NULL, source_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(owner_id, source_id));
                CREATE INDEX IF NOT EXISTS question_owner ON questions(owner_id,normalized);
                CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, ciphertext TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS rule_groups (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            """)
            for table in ("scripts", "rules"):
                columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                if "tags" not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
            if "group_id" not in {row[1] for row in db.execute("PRAGMA table_info(scripts)")}:
                db.execute("ALTER TABLE scripts ADD COLUMN group_id TEXT")
            if "group_id" not in {row[1] for row in db.execute("PRAGMA table_info(rules)")}:
                db.execute("ALTER TABLE rules ADD COLUMN group_id TEXT")
            # Backfill names per owner, preserving existing content and empty groups.
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT DISTINCT owner_id,group_name FROM scripts "
                                  "WHERE deleted=0 AND group_id IS NULL AND group_name!='未分组'").fetchall():
                group_id = self._ensure_group(db, row["owner_id"], row["group_name"])
                db.execute("UPDATE scripts SET group_id=? WHERE owner_id=? AND group_name=? "
                           "AND group_id IS NULL AND deleted=0", (group_id, row["owner_id"], row["group_name"]))
            for row in db.execute("SELECT DISTINCT group_name FROM rules WHERE deleted=0 AND group_id IS NULL AND group_name!='未分组'").fetchall():
                group_id = self._ensure_rule_group(db, row["group_name"])
                db.execute("UPDATE rules SET group_id=? WHERE group_name=? AND group_id IS NULL AND deleted=0", (group_id, row["group_name"]))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def scripts(self, owner_id, query=""):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,title,content,group_name,group_id,tags,created_at,updated_at FROM scripts "
                "WHERE owner_id=? AND deleted=0 AND (instr(title,?)>0 OR instr(content,?)>0) "
                "ORDER BY updated_at DESC LIMIT 500", (owner_id, query, query))]

    def script(self, owner_id, item_id):
        with self.connect() as db:
            row = db.execute("SELECT id,title,content,group_name,group_id,tags,created_at,updated_at FROM scripts "
                             "WHERE owner_id=? AND id=? AND deleted=0", (owner_id, item_id)).fetchone()
            return dict(row) if row else None

    def save_script(self, owner_id, payload, item_id=None):
        # There is deliberately NO administrator bypass of owner_id.
        stamp = now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if item_id and not db.execute("SELECT 1 FROM scripts WHERE owner_id=? AND id=? AND deleted=0",
                                          (owner_id, item_id)).fetchone():
                return None
            if "group_id" in payload:
                group_id = payload["group_id"]
                group = db.execute("SELECT name FROM script_groups WHERE owner_id=? AND id=?",
                                   (owner_id, group_id)).fetchone() if group_id else None
                if group_id and not group:
                    raise ScriptGroupError(404, "话术组不存在或已删除，请重新选择")
                group_name = group["name"] if group else "未分组"
            else:
                # Compatibility for historical imports and older clients.
                group_name = payload.get("group_name", "默认分组")
                group_id = self._ensure_group(db, owner_id, group_name)
            if item_id:
                result = db.execute("UPDATE scripts SET title=?,content=?,group_name=?,group_id=?,updated_at=? "
                                    "WHERE owner_id=? AND id=? AND deleted=0",
                                    (payload["title"], payload["content"], group_name, group_id, stamp, owner_id, item_id))
                if not result.rowcount:
                    return None
            else:
                legacy_id = payload.get("legacy_id")
                if legacy_id:
                    prior = db.execute("SELECT id FROM scripts WHERE owner_id=? AND legacy_id=?", (owner_id, legacy_id)).fetchone()
                    if prior:
                        return self.script(owner_id, prior["id"])
                item_id = str(uuid4())
                db.execute("INSERT INTO scripts(id,owner_id,title,content,group_name,group_id,legacy_id,created_at,updated_at) "
                           "VALUES(?,?,?,?,?,?,?,?,?)", (item_id, owner_id, payload["title"], payload["content"],
                           group_name, group_id, legacy_id, stamp, stamp))
            db.execute("UPDATE scripts SET tags=? WHERE owner_id=? AND id=?", (payload.get("tags", ""), owner_id, item_id))
        return self.script(owner_id, item_id)

    @staticmethod
    def _ensure_group(db, owner_id, name):
        if name == "未分组":
            return None
        db.execute("INSERT OR IGNORE INTO script_groups(id,owner_id,name,created_at,updated_at) VALUES(?,?,?,?,?)",
                   (str(uuid4()), owner_id, name, now(), now()))
        return db.execute("SELECT id FROM script_groups WHERE owner_id=? AND name=?", (owner_id, name)).fetchone()["id"]

    def script_groups(self, owner_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT g.id,g.name,COUNT(s.id) AS count FROM script_groups g LEFT JOIN scripts s "
                "ON s.group_id=g.id AND s.owner_id=g.owner_id AND s.deleted=0 WHERE g.owner_id=? "
                "GROUP BY g.id ORDER BY g.created_at,g.id", (owner_id,))]

    def save_script_group(self, owner_id, name, group_id=None):
        if name == "未分组":
            raise ScriptGroupError(409, "未分组为系统分组，请使用其他名称")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if group_id and not db.execute("SELECT 1 FROM script_groups WHERE owner_id=? AND id=?",
                                           (owner_id, group_id)).fetchone():
                raise ScriptGroupError(404, "话术组不存在")
            duplicate = db.execute("SELECT id FROM script_groups WHERE owner_id=? AND name=?", (owner_id, name)).fetchone()
            if duplicate and duplicate["id"] != group_id:
                raise ScriptGroupError(409, "你已有同名话术组，请使用其他名称")
            stamp = now()
            if group_id:
                db.execute("UPDATE script_groups SET name=?,updated_at=? WHERE owner_id=? AND id=?",
                           (name, stamp, owner_id, group_id))
                db.execute("UPDATE scripts SET group_name=?,updated_at=? WHERE owner_id=? AND group_id=? AND deleted=0",
                           (name, stamp, owner_id, group_id))
            else:
                group_id = str(uuid4())
                db.execute("INSERT INTO script_groups(id,owner_id,name,created_at,updated_at) VALUES(?,?,?,?,?)",
                           (group_id, owner_id, name, stamp, stamp))
            count = db.execute("SELECT COUNT(*) FROM scripts WHERE owner_id=? AND group_id=? AND deleted=0",
                               (owner_id, group_id)).fetchone()[0]
            return {"id": group_id, "name": name, "count": count}

    def delete_script_group(self, owner_id, group_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM script_groups WHERE owner_id=? AND id=?", (owner_id, group_id)).fetchone():
                return False
            db.execute("UPDATE scripts SET group_id=NULL,group_name='未分组',updated_at=? "
                       "WHERE owner_id=? AND group_id=?", (now(), owner_id, group_id))
            db.execute("DELETE FROM script_groups WHERE owner_id=? AND id=?", (owner_id, group_id))
            return True

    def delete_script(self, owner_id, item_id):
        with self.connect() as db:
            result = db.execute("UPDATE scripts SET deleted=1,updated_at=? WHERE owner_id=? AND id=? AND deleted=0",
                                (now(), owner_id, item_id))
            return bool(result.rowcount)

    def rules(self, query=""):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM rules WHERE deleted=0 AND "
                "(instr(title,?)>0 OR instr(content,?)>0) ORDER BY updated_at DESC LIMIT 500", (query, query))]

    def rule(self, item_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM rules WHERE id=?", (item_id,)).fetchone()
            return dict(row) if row else None

    def save_rule(self, operator, payload, item_id=None, push=False):
        stamp = now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if item_id and not db.execute("SELECT 1 FROM rules WHERE id=? AND deleted=0", (item_id,)).fetchone():
                return None
            if "group_id" in payload:
                group_id = payload["group_id"]
                group = db.execute("SELECT name FROM rule_groups WHERE id=?", (group_id,)).fetchone() if group_id else None
                if group_id and not group:
                    raise ScriptGroupError(404, "规则分组不存在或已删除，请重新选择")
                group_name = group["name"] if group else "未分组"
            else:
                group_name = payload.get("group_name", "默认分组")
                group_id = self._ensure_rule_group(db, group_name)
            if item_id:
                result = db.execute("UPDATE rules SET title=?,content=?,group_name=?,group_id=?,operator=?,updated_at=?,"
                    "version=version+1,state='pending',error='',push_requested=?,push_status=? WHERE id=? AND deleted=0",
                    (payload["title"], payload["content"], group_name, group_id, operator, stamp, int(push),
                     "pending" if push else "not_requested", item_id))
                if not result.rowcount:
                    return None
            else:
                legacy = payload.get("legacy_id")
                if legacy:
                    prior = db.execute("SELECT id FROM rules WHERE legacy_id=?", (legacy,)).fetchone()
                    if prior:
                        return self.rule(prior["id"])
                item_id = str(uuid4())
                db.execute("INSERT INTO rules(id,title,content,group_name,group_id,operator,legacy_id,push_requested,"
                    "push_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (item_id, payload["title"],
                    payload["content"], group_name, group_id, operator, legacy, int(push),
                    "pending" if push else "not_requested", stamp, stamp))
            db.execute("UPDATE rules SET tags=? WHERE id=?", (payload.get("tags", ""), item_id))
        return self.rule(item_id)

    @staticmethod
    def _ensure_rule_group(db, name):
        if name == "未分组":
            return None
        db.execute("INSERT OR IGNORE INTO rule_groups(id,name,created_at,updated_at) VALUES(?,?,?,?)",
                   (str(uuid4()), name, now(), now()))
        return db.execute("SELECT id FROM rule_groups WHERE name=?", (name,)).fetchone()["id"]

    def rule_groups(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT g.id,g.name,COUNT(r.id) AS count FROM rule_groups g "
                "LEFT JOIN rules r ON r.group_id=g.id AND r.deleted=0 GROUP BY g.id ORDER BY g.created_at,g.id")]

    def save_rule_group(self, name, group_id=None):
        if name == "未分组":
            raise ScriptGroupError(409, "未分组为系统分组，请使用其他名称")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if group_id and not db.execute("SELECT 1 FROM rule_groups WHERE id=?", (group_id,)).fetchone():
                raise ScriptGroupError(404, "规则分组不存在")
            duplicate = db.execute("SELECT id FROM rule_groups WHERE name=?", (name,)).fetchone()
            if duplicate and duplicate["id"] != group_id:
                raise ScriptGroupError(409, "已有同名规则分组，请使用其他名称")
            stamp = now()
            if group_id:
                db.execute("UPDATE rule_groups SET name=?,updated_at=? WHERE id=?", (name, stamp, group_id))
                # Keep indexed group metadata current, but never resend DingTalk notifications.
                db.execute("UPDATE rules SET group_name=?,updated_at=?,version=version+1,state='pending',error='' "
                           "WHERE group_id=? AND deleted=0", (name, stamp, group_id))
            else:
                group_id = str(uuid4())
                db.execute("INSERT INTO rule_groups(id,name,created_at,updated_at) VALUES(?,?,?,?)",
                           (group_id, name, stamp, stamp))
            count = db.execute("SELECT COUNT(*) FROM rules WHERE group_id=? AND deleted=0", (group_id,)).fetchone()[0]
            return {"id": group_id, "name": name, "count": count}

    def delete_rule_group(self, group_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM rule_groups WHERE id=?", (group_id,)).fetchone():
                return False
            db.execute("UPDATE rules SET group_id=NULL,group_name='未分组',updated_at=?,version=version+1,"
                       "state=CASE WHEN deleted=0 THEN 'pending' ELSE state END,error='' WHERE group_id=?", (now(), group_id))
            db.execute("DELETE FROM rule_groups WHERE id=?", (group_id,))
            return True

    def delete_rule(self, item_id):
        with self.connect() as db:
            return bool(db.execute("UPDATE rules SET deleted=1,state='pending',version=version+1,"
                                   "push_requested=0,updated_at=? WHERE id=? AND deleted=0", (now(), item_id)).rowcount)

    def pending_rules(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM rules WHERE state IN ('pending','retry') "
                "OR (push_requested=1 AND push_status='pending') ORDER BY updated_at LIMIT 50")]

    def mark_rule(self, item_id, version, state, native_id=None, error="", push_status=None):
        with self.connect() as db:
            # Preserve a remote ID even if a user changed the rule while indexing.
            if native_id:
                db.execute("UPDATE rules SET native_id=? WHERE id=?", (native_id, item_id))
            db.execute("UPDATE rules SET state=?,error=?,push_status=COALESCE(?,push_status) WHERE id=? AND version=?",
                       (state, error, push_status, item_id, version))

    def question(self, owner_id, text, source_id):
        text = " ".join(text.split()).strip()
        normalized = re.sub(r"^[请麻烦]*(?:帮我|给我)?", "", text.casefold())
        normalized = re.sub(r"[，。！？!?、,.;；：:\s]+", "", normalized)
        if len(normalized) < 2 or normalized in {"你好", "您好", "nihao", "hello", "hi", "谢谢", "感谢", "再见", "拜拜", "你是谁", "你好你是谁"}:
            return
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO questions(id,owner_id,question,normalized,source_id,created_at) "
                       "VALUES(?,?,?,?,?,?)", (str(uuid4()), owner_id, text, normalized, source_id, now()))

    def cloud(self, owner_id):
        with self.connect() as db:
            rows = db.execute("SELECT MIN(question) AS question,COUNT(*) AS count FROM questions "
                              "WHERE owner_id=? GROUP BY normalized ORDER BY count DESC,MAX(created_at) DESC LIMIT 40", (owner_id,))
            return [dict(row) for row in rows]

    def settings(self, cipher):
        with self.connect() as db:
            return {row["name"]: json.loads(cipher.decrypt(row["ciphertext"].encode()).decode())
                    for row in db.execute("SELECT name,ciphertext FROM settings")}

    def save_settings(self, cipher, values):
        with self.connect() as db:
            for key, value in values.items():
                encrypted = cipher.encrypt(json.dumps(value).encode()).decode()
                db.execute("INSERT INTO settings(name,ciphertext) VALUES(?,?) "
                           "ON CONFLICT(name) DO UPDATE SET ciphertext=excluded.ciphertext", (key, encrypted))

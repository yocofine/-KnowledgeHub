from contextlib import contextmanager
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import sqlite3
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


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
            """)
            for table in ("scripts", "rules"):
                columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                if "tags" not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN tags TEXT NOT NULL DEFAULT ''")

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
                "SELECT id,title,content,group_name,tags,created_at,updated_at FROM scripts "
                "WHERE owner_id=? AND deleted=0 AND (instr(title,?)>0 OR instr(content,?)>0) "
                "ORDER BY updated_at DESC LIMIT 500", (owner_id, query, query))]

    def script(self, owner_id, item_id):
        with self.connect() as db:
            row = db.execute("SELECT id,title,content,group_name,tags,created_at,updated_at FROM scripts "
                             "WHERE owner_id=? AND id=? AND deleted=0", (owner_id, item_id)).fetchone()
            return dict(row) if row else None

    def save_script(self, owner_id, payload, item_id=None):
        # There is deliberately NO administrator bypass of owner_id.
        stamp = now()
        with self.connect() as db:
            if item_id:
                result = db.execute("UPDATE scripts SET title=?,content=?,group_name=?,updated_at=? "
                                    "WHERE owner_id=? AND id=? AND deleted=0",
                                    (payload["title"], payload["content"], payload["group_name"], stamp, owner_id, item_id))
                if not result.rowcount:
                    return None
            else:
                legacy_id = payload.get("legacy_id")
                if legacy_id:
                    prior = db.execute("SELECT id FROM scripts WHERE owner_id=? AND legacy_id=?", (owner_id, legacy_id)).fetchone()
                    if prior:
                        return self.script(owner_id, prior["id"])
                item_id = str(uuid4())
                db.execute("INSERT INTO scripts(id,owner_id,title,content,group_name,legacy_id,created_at,updated_at) "
                           "VALUES(?,?,?,?,?,?,?,?)", (item_id, owner_id, payload["title"], payload["content"],
                           payload["group_name"], legacy_id, stamp, stamp))
            db.execute("UPDATE scripts SET tags=? WHERE owner_id=? AND id=?", (payload.get("tags", ""), owner_id, item_id))
        return self.script(owner_id, item_id)

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
            if item_id:
                result = db.execute("UPDATE rules SET title=?,content=?,group_name=?,operator=?,updated_at=?,"
                    "version=version+1,state='pending',error='',push_requested=?,push_status=? WHERE id=? AND deleted=0",
                    (payload["title"], payload["content"], payload["group_name"], operator, stamp, int(push),
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
                db.execute("INSERT INTO rules(id,title,content,group_name,operator,legacy_id,push_requested,"
                    "push_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (item_id, payload["title"],
                    payload["content"], payload["group_name"], operator, legacy, int(push),
                    "pending" if push else "not_requested", stamp, stamp))
            db.execute("UPDATE rules SET tags=? WHERE id=?", (payload.get("tags", ""), item_id))
        return self.rule(item_id)

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

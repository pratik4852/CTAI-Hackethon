"""
Persistence: SQLite for metadata, JSON on disk for analysis payloads.

Analysis results are large (tens of thousands of geometry points) and are read
whole, so they live as files; everything that needs querying lives in SQLite.
No ORM — the schema is six tables and staying close to it keeps the deployment
a single file with no migration story.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import settings

_LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    page_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    document_id TEXT,
    status TEXT NOT NULL,
    stage TEXT DEFAULT '',
    progress REAL DEFAULT 0,
    message TEXT DEFAULT '',
    error TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    target_type TEXT NOT NULL,          -- detection | finding | clash | run
    target_id TEXT NOT NULL,
    action TEXT NOT NULL,               -- confirmed | rejected | corrected | dismissed | accepted
    payload TEXT DEFAULT '{}',
    author TEXT DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reviews_lookup ON reviews(project_id, document_id, page_number, target_type, target_id);
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    meta TEXT DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chats_project ON chats(project_id, id);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_conn: sqlite3.Connection | None = None


def db() -> sqlite3.Connection:
    global _conn
    with _LOCK:
        if _conn is None:
            settings.ensure_dirs()
            _conn = _connect()
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = db()
    with _LOCK:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Projects & documents
# ---------------------------------------------------------------------------


def create_project(name: str, notes: str = "") -> dict:
    pid = new_id("prj_")
    now = time.time()
    with tx() as c:
        c.execute(
            "INSERT INTO projects (id, name, created_at, updated_at, status, notes) VALUES (?,?,?,?,?,?)",
            (pid, name, now, now, "new", notes),
        )
    return get_project(pid)  # type: ignore[return-value]


def get_project(pid: str) -> dict | None:
    row = db().execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if not row:
        return None
    p = dict(row)
    p["documents"] = list_documents(pid)
    return p


def list_projects(limit: int = 100) -> list[dict]:
    rows = db().execute("SELECT * FROM projects ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        p = dict(r)
        p["documents"] = list_documents(p["id"])
        out.append(p)
    return out


def touch_project(pid: str, status: str | None = None) -> None:
    with tx() as c:
        if status:
            c.execute("UPDATE projects SET updated_at=?, status=? WHERE id=?", (time.time(), status, pid))
        else:
            c.execute("UPDATE projects SET updated_at=? WHERE id=?", (time.time(), pid))


def delete_project(pid: str) -> None:
    docs = list_documents(pid)
    with tx() as c:
        c.execute("DELETE FROM documents WHERE project_id=?", (pid,))
        c.execute("DELETE FROM reviews WHERE project_id=?", (pid,))
        c.execute("DELETE FROM chats WHERE project_id=?", (pid,))
        c.execute("DELETE FROM jobs WHERE project_id=?", (pid,))
        c.execute("DELETE FROM projects WHERE id=?", (pid,))
    import shutil

    for d in docs:
        for p in (Path(d["stored_path"]), result_path(d["id"])):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        # Cached page renders belong to the document; drop them with it.
        shutil.rmtree(settings.data_dir / "renders" / d["id"], ignore_errors=True)


def add_document(project_id: str, file_name: str, stored_path: Path, size_bytes: int, page_count: int = 0) -> dict:
    did = new_id("doc_")
    with tx() as c:
        c.execute(
            "INSERT INTO documents (id, project_id, file_name, stored_path, size_bytes, page_count, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (did, project_id, file_name, str(stored_path), size_bytes, page_count, time.time()),
        )
    touch_project(project_id)
    return get_document(did)  # type: ignore[return-value]


def get_document(did: str) -> dict | None:
    row = db().execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
    return dict(row) if row else None


def list_documents(project_id: str) -> list[dict]:
    rows = db().execute(
        "SELECT * FROM documents WHERE project_id=? ORDER BY created_at", (project_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["has_result"] = result_path(d["id"]).exists()
        out.append(d)
    return out


def set_page_count(did: str, n: int) -> None:
    with tx() as c:
        c.execute("UPDATE documents SET page_count=? WHERE id=?", (n, did))


# ---------------------------------------------------------------------------
# Results on disk
# ---------------------------------------------------------------------------


def result_path(document_id: str) -> Path:
    return settings.results / f"{document_id}.json"


def save_result(document_id: str, payload: dict) -> None:
    p = result_path(document_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    os.replace(tmp, p)


def load_result(document_id: str) -> dict | None:
    p = result_path(document_id)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def create_job(project_id: str, document_id: str | None) -> dict:
    jid = new_id("job_")
    now = time.time()
    with tx() as c:
        c.execute(
            "INSERT INTO jobs (id, project_id, document_id, status, stage, progress, message, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (jid, project_id, document_id, "queued", "queued", 0.0, "Waiting for a worker", now, now),
        )
    return get_job(jid)  # type: ignore[return-value]


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    with tx() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))


def get_job(job_id: str) -> dict | None:
    row = db().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(project_id: str, limit: int = 20) -> list[dict]:
    rows = db().execute(
        "SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC LIMIT ?", (project_id, limit)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Reviews (human-in-the-loop)
# ---------------------------------------------------------------------------


def add_review(project_id: str, document_id: str, page_number: int, target_type: str,
               target_id: str, action: str, payload: dict | None = None, author: str = "") -> dict:
    with tx() as c:
        cur = c.execute(
            "INSERT INTO reviews (project_id, document_id, page_number, target_type, target_id, action, payload, author, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (project_id, document_id, page_number, target_type, str(target_id), action,
             json.dumps(payload or {}), author, time.time()),
        )
        rid = cur.lastrowid
    return {"id": rid, "action": action, "target_type": target_type, "target_id": str(target_id)}


def reviews_for(document_id: str) -> list[dict]:
    rows = db().execute(
        "SELECT * FROM reviews WHERE document_id=? ORDER BY created_at", (document_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"] or "{}")
        except Exception:
            d["payload"] = {}
        out.append(d)
    return out


def review_map(document_id: str) -> dict[tuple[int, str, str], dict]:
    """Latest review action per target."""
    out: dict[tuple[int, str, str], dict] = {}
    for r in reviews_for(document_id):
        out[(r["page_number"], r["target_type"], r["target_id"])] = r
    return out


# ---------------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------------


def add_chat(project_id: str, role: str, content: str, meta: dict | None = None) -> dict:
    with tx() as c:
        cur = c.execute(
            "INSERT INTO chats (project_id, role, content, meta, created_at) VALUES (?,?,?,?,?)",
            (project_id, role, content, json.dumps(meta or {}), time.time()),
        )
        cid = cur.lastrowid
    return {"id": cid, "role": role, "content": content, "meta": meta or {}}


def chat_history(project_id: str, limit: int = 50) -> list[dict]:
    rows = db().execute(
        "SELECT * FROM chats WHERE project_id=? ORDER BY id DESC LIMIT ?", (project_id, limit)
    ).fetchall()
    out = []
    for r in reversed(rows):
        d = dict(r)
        try:
            d["meta"] = json.loads(d["meta"] or "{}")
        except Exception:
            d["meta"] = {}
        out.append(d)
    return out


def clear_chat(project_id: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM chats WHERE project_id=?", (project_id,))

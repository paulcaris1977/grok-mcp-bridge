"""
store.py — Grok-Claude Bridge
Persistance SQLite : notes de projet, historique des sessions Grok, tâches de fond.

Emplacement : DATA_DIR, sinon le volume Railway (RAILWAY_VOLUME_MOUNT_PATH), sinon /data.
Sans volume Railway monté, le fichier vit dans le conteneur et disparaît au redéploiement :
un avertissement est loggé au démarrage.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

logger = logging.getLogger("grok-mcp-bridge.store")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    project    TEXT NOT NULL,
    key        TEXT NOT NULL,
    content    TEXT NOT NULL,
    source     TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (project, key)
);
CREATE TABLE IF NOT EXISTS history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS history_session ON history (session_id, id);
CREATE TABLE IF NOT EXISTS jobs (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    params     TEXT NOT NULL,
    status     TEXT NOT NULL,
    progress   TEXT NOT NULL DEFAULT '',
    result     TEXT,
    error      TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

MAX_NOTES_PER_PROJECT = 50
HISTORY_KEEP = 30
JOB_RETENTION_DAYS = int(os.environ.get("JOB_RETENTION_DAYS", "14"))

_fallback_dir: Optional[Path] = None   # posé par init() si le dossier configuré est inaccessible


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def data_dir() -> Path:
    if _fallback_dir is not None:
        return _fallback_dir
    return Path(os.environ.get("DATA_DIR")
                or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
                or "/data")


def db_path() -> Path:
    return data_dir() / "bridge.sqlite3"


def is_persistent() -> bool:
    """Vrai si DATA_DIR est explicite ou si Railway a monté un volume."""
    return _fallback_dir is None and bool(os.environ.get("DATA_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init() -> None:
    """Crée le schéma, importe l'ancien project_notes.json, marque les tâches orphelines."""
    global _fallback_dir
    _fallback_dir = None
    try:
        data_dir().mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # Ne jamais empêcher le démarrage : repli dans le dossier de l'app (non persistant)
        _fallback_dir = Path(__file__).with_name("data")
        logger.warning("Dossier de données inaccessible (%s), repli sur %s", exc, _fallback_dir)
    with connect() as conn:
        conn.executescript(_SCHEMA)
    _import_legacy_notes()
    interrupted = interrupt_running_jobs()
    purge_old_jobs()
    if is_persistent():
        logger.info("Stockage SQLite : %s (persistant)", db_path())
    else:
        logger.warning("Stockage SQLite : %s — AUCUN volume Railway monté, notes, historique "
                       "et tâches seront perdus au redéploiement", db_path())
    if interrupted:
        logger.warning("%d tâche(s) interrompue(s) par le redémarrage", interrupted)


def _import_legacy_notes() -> None:
    legacy = Path(os.environ.get("NOTES_PATH", str(data_dir() / "project_notes.json")))
    if not legacy.exists():
        return
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
        projects = data.get("projects", {}) if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ancien fichier de notes illisible (%s), ignoré", exc)
        return
    count = 0
    with connect() as conn:
        for project, bucket in projects.items():
            for note in (bucket or {}).get("notes", []) or []:
                if note.get("key"):
                    conn.execute(
                        "INSERT OR IGNORE INTO notes VALUES (?, ?, ?, ?, ?)",
                        (project, note["key"], note.get("content", ""),
                         note.get("source", "grok"), note.get("updated_at") or now()))
                    count += 1
    legacy.rename(legacy.with_suffix(".json.imported"))
    logger.info("%d note(s) importée(s) depuis %s", count, legacy)


# ── Notes de projet ───────────────────────────────────────────────────────────

def save_note(project: str, key: str, content: str, source: str) -> bool:
    """Crée ou remplace une note. Renvoie True si elle existait déjà."""
    with connect() as conn:
        existed = conn.execute("SELECT 1 FROM notes WHERE project=? AND key=?",
                               (project, key)).fetchone() is not None
        conn.execute("INSERT OR REPLACE INTO notes VALUES (?, ?, ?, ?, ?)",
                     (project, key, content, source, now()))
        conn.execute(
            "DELETE FROM notes WHERE project=? AND key NOT IN "
            "(SELECT key FROM notes WHERE project=? ORDER BY updated_at DESC LIMIT ?)",
            (project, project, MAX_NOTES_PER_PROJECT))
    return existed


def list_notes(project: str, key: str = "") -> list[dict[str, Any]]:
    sql, args = "SELECT key, content, source, updated_at FROM notes WHERE project=?", [project]
    if key:
        sql, args = sql + " AND key=?", args + [key]
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql + " ORDER BY updated_at", args)]


def list_projects() -> list[str]:
    with connect() as conn:
        return [r[0] for r in conn.execute("SELECT DISTINCT project FROM notes ORDER BY project")]


# ── Historique des sessions Grok ──────────────────────────────────────────────

def get_history(session_id: str) -> list[dict[str, str]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM (SELECT id, role, content FROM history WHERE session_id=? "
            "ORDER BY id DESC LIMIT ?) ORDER BY id", (session_id, HISTORY_KEEP)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def append_history(session_id: str, messages: list[dict[str, str]]) -> None:
    with connect() as conn:
        conn.executemany("INSERT INTO history (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                         [(session_id, m["role"], m["content"], now()) for m in messages])
        conn.execute(
            "DELETE FROM history WHERE session_id=? AND id NOT IN "
            "(SELECT id FROM history WHERE session_id=? ORDER BY id DESC LIMIT ?)",
            (session_id, session_id, HISTORY_KEEP))


def clear_history(session_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM history WHERE session_id=?", (session_id,))


# ── Tâches de fond ────────────────────────────────────────────────────────────

def create_job(job_id: str, kind: str, params: dict[str, Any]) -> None:
    ts = now()
    with connect() as conn:
        conn.execute("INSERT INTO jobs (id, kind, params, status, created_at, updated_at) "
                     "VALUES (?, ?, ?, 'queued', ?, ?)",
                     (job_id, kind, json.dumps(params, ensure_ascii=False), ts, ts))


def update_job(job_id: str, **fields: Optional[str]) -> None:
    allowed = {"status", "progress", "result", "error"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    sets["updated_at"] = now()
    with connect() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                     (*sets.values(), job_id))


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return None
    job = dict(row)
    job["params"] = json.loads(job["params"])
    return job


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT id, kind, status, progress, created_at, updated_at FROM jobs "
                            "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def interrupt_running_jobs() -> int:
    with connect() as conn:
        cur = conn.execute("UPDATE jobs SET status='interrupted', updated_at=?, "
                           "error='Serveur redémarré pendant la tâche' "
                           "WHERE status IN ('queued', 'running')", (now(),))
        return cur.rowcount


def purge_old_jobs() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=JOB_RETENTION_DAYS)).isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute("DELETE FROM jobs WHERE created_at < ?", (cutoff,))

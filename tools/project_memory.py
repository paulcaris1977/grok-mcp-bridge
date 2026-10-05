"""
tools/project_memory.py
Mémoire de projet partagée entre Grok et Claude.
Fichier JSON local (NOTES_PATH). Sur Railway, monter un volume sur ce chemin,
sinon les notes disparaissent au redémarrage.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

logger = logging.getLogger("grok-mcp-bridge.project_memory")

NOTES_PATH = Path(os.environ.get("NOTES_PATH", "/data/project_notes.json"))
_MAX_NOTE_CHARS = 20_000
_MAX_NOTES_PER_PROJECT = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> dict[str, Any]:
    if not NOTES_PATH.exists():
        return {"projects": {}}
    try:
        data = json.loads(NOTES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("project memory illisible (%s), mémoire vide", exc)
        return {"projects": {}}
    if not isinstance(data, dict) or not isinstance(data.get("projects"), dict):
        return {"projects": {}}
    return data


def _save(data: dict[str, Any]) -> None:
    NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = NOTES_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(NOTES_PATH)


def notes_for(project: str) -> list[dict[str, Any]]:
    data = _load()
    bucket = data["projects"].get(project, {})
    notes = bucket.get("notes", [])
    return notes if isinstance(notes, list) else []


def format_notes(project: str) -> str:
    notes = notes_for(project)
    if not notes:
        return ""
    lines = [f"Notes de projet '{project}' ({len(notes)}) :"]
    for note in notes[-12:]:
        lines.append(
            f"- [{note.get('updated_at', '')}] {note.get('key', '')} "
            f"(source={note.get('source', '')}): {note.get('content', '')}"
        )
    return "\n".join(lines)


def register_project_memory(mcp: FastMCP) -> None:
    @mcp.tool(
        name="save_project_note",
        description=(
            "Enregistre une note de projet partagée, lisible ensuite par ask_claude et get_project_notes. "
            "Utiliser pour déposer le contexte Nalmaia (prix, segments, réserves) avant une question à Claude."
        ),
    )
    async def save_project_note(
        project: str,
        key: str,
        content: str,
        source: str = "grok",
    ) -> str:
        project = project.strip()
        key = key.strip()
        if not project or not key:
            return "Erreur: project et key sont obligatoires."
        content = content.strip()[:_MAX_NOTE_CHARS]
        data = _load()
        bucket = data["projects"].setdefault(project, {"notes": []})
        notes: list[dict[str, Any]] = bucket.setdefault("notes", [])
        now = _now()
        replaced = False
        for note in notes:
            if note.get("key") == key:
                note["content"] = content
                note["source"] = source
                note["updated_at"] = now
                replaced = True
                break
        if not replaced:
            notes.append({
                "key": key,
                "content": content,
                "source": source,
                "updated_at": now,
            })
        if len(notes) > _MAX_NOTES_PER_PROJECT:
            bucket["notes"] = notes[-_MAX_NOTES_PER_PROJECT:]
        try:
            _save(data)
        except OSError as exc:
            return f"Erreur d'écriture ({NOTES_PATH}): {exc}"
        action = "mise à jour" if replaced else "créée"
        return f"Note {action}: project={project} key={key} source={source} path={NOTES_PATH}"

    @mcp.tool(
        name="get_project_notes",
        description="Lit les notes d'un projet partagé. key optionnelle. Sans project, liste les projets connus.",
    )
    async def get_project_notes(project: str = "", key: str = "") -> str:
        data = _load()
        if not project.strip():
            names = sorted(data["projects"].keys())
            if not names:
                return f"Aucun projet. Fichier: {NOTES_PATH}"
            return "Projets: " + ", ".join(names)
        notes = notes_for(project.strip())
        if key.strip():
            notes = [n for n in notes if n.get("key") == key.strip()]
        if not notes:
            return f"Aucune note pour project={project.strip()} key={key.strip() or '*'}"
        return format_notes(project.strip()) if not key.strip() else json.dumps(notes, ensure_ascii=False, indent=2)

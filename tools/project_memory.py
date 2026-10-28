"""
tools/project_memory.py
Mémoire de projet partagée entre Grok et Claude.
Stockée dans SQLite (store.py) ; persistante si un volume Railway est monté.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from fastmcp import FastMCP

import store

logger = logging.getLogger("grok-mcp-bridge.project_memory")

_MAX_NOTE_CHARS = 20_000


def notes_for(project: str) -> list[dict[str, Any]]:
    try:
        return store.list_notes(project)
    except sqlite3.Error as exc:
        logger.warning("notes illisibles (%s)", exc)
        return []


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
            "Utiliser pour déposer le contexte d'un projet (prix, segments, réserves) avant une question à Claude."
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
        try:
            replaced = store.save_note(project, key, content.strip()[:_MAX_NOTE_CHARS], source)
        except sqlite3.Error as exc:
            return f"Erreur d'écriture ({store.db_path()}): {exc}"
        action = "mise à jour" if replaced else "créée"
        persist = "" if store.is_persistent() else " (⚠️ pas de volume : perdue au redéploiement)"
        return f"Note {action}: project={project} key={key} source={source}{persist}"

    @mcp.tool(
        name="get_project_notes",
        description="Lit les notes d'un projet partagé. key optionnelle. Sans project, liste les projets connus.",
    )
    async def get_project_notes(project: str = "", key: str = "") -> str:
        if not project.strip():
            names = store.list_projects()
            if not names:
                return f"Aucun projet. Base: {store.db_path()}"
            return "Projets: " + ", ".join(names)
        if key.strip():
            notes = store.list_notes(project.strip(), key.strip())
            if not notes:
                return f"Aucune note pour project={project.strip()} key={key.strip()}"
            return json.dumps(notes, ensure_ascii=False, indent=2)
        return format_notes(project.strip()) or f"Aucune note pour project={project.strip()} key=*"

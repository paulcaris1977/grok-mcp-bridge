"""
context/__init__.py
Point d'entrée du package context.
Expose les fonctions principales du contexte métier Taranis.
"""

from .taranis_context import (
    build_system_prompt,
    get_context_summary,
)

__all__ = [
    "build_system_prompt",
    "get_context_summary",
]

# Pour faciliter les imports dans les tools
# from context import build_system_prompt

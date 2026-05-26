"""
tools/grok_code_test.py
Tool spécialisé pour tester, debugger, analyser et améliorer du code avec Grok.
Optimisé pour Python, FastAPI, MCP, Railway et contexte métier Taranis Cooperage.
"""

import logging
from typing import Optional
from fastmcp import FastMCP

from grok_client import call_grok, get_model_for_task
from context import build_system_prompt

logger = logging.getLogger("grok-mcp-bridge.code_test")

# ── Template de prompt ────────────────────────────────────────────────────────
_CODE_SYSTEM_PROMPT = """
Tu es un expert senior en développement Python, FastAPI, FastMCP et architectures cloud (Railway, Docker).
Tu analyses du code de manière critique, précise et professionnelle.

Contexte technique prioritaire :
- Python 3.11+, asyncio, type hints stricts
- FastMCP (MCP servers), OpenAI-compatible APIs
- Déploiement Railway via Procfile, variables d'environnement
- Odoo Online 19 (pas de modules custom installables)
- Stack Taranis : grok-mcp-bridge, oauth-mcp-wrapper, Odoo MCP connector

Règles absolues pour tes réponses :
1. Toujours produire un code corrigé COMPLET et fonctionnel (pas de [...] ou de placeholder)
2. Indiquer TOUTES les lignes modifiées avec une brève explication
3. Inclure les imports manquants
4. Respecter les patterns async/await existants
5. Ne jamais supprimer de fonctionnalité sans justification explicite
""".strip()

_CODE_PROMPT_TEMPLATE = """
Analyse ce code et fournis un retour structuré complet.

{error_section}{context_section}
## CODE À ANALYSER ({language}) :

{code}

---

## STRUCTURE DE TA RÉPONSE (obligatoire, dans cet ordre) :

### 🔍 Diagnostic
[Résumé du problème principal en 2-3 phrases max]

### 🐛 Problèmes détectés
Pour chaque problème :
- **Ligne X** — [description du problème] — Sévérité: 🔴 Critique / 🟠 Majeur / 🟡 Mineur

### ✅ Code corrigé (complet)
[Code entier, fonctionnel, prêt à déployer — aucun placeholder]

### 📝 Changements effectués
[Liste numérotée des modifications avec justification]

### 🧪 Tests recommandés
[Tests unitaires minimaux couvrant les cas critiques]

### ⚡ Optimisations futures (optionnel)
[Suggestions non bloquantes pour améliorer la maintenabilité ou la performance]
""".strip()


def register_code_test(mcp: FastMCP) -> None:
    """Enregistre le tool grok_code_test sur l'instance FastMCP."""

    @mcp.tool()
    async def grok_code_test(
        code: str,
        language: str = "python",
        error_message: Optional[str] = None,
        context: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        Analyse, debug et correction de code via Grok (modèle grok-3).

        Spécialisé pour le stack Taranis Cooperage Group :
        Python / FastMCP / Railway / Odoo Online 19 / asyncio.

        Retourne un rapport structuré avec :
        - Diagnostic des problèmes (sévérité 🔴/🟠/🟡)
        - Code corrigé COMPLET et déployable
        - Liste des changements avec justifications
        - Tests unitaires recommandés
        - Optimisations futures (si applicable)

        Args:
            code: Code source à analyser ou corriger.
            language: Langage (python, javascript, bash, yaml...). Défaut: python.
            error_message: Traceback ou message d'erreur associé (optionnel).
            context: Contexte d'usage, ex: 'Railway server.py', 'Odoo webhook MCP'.
            session_id: ID de session pour debugging itératif multi-tours.

        Returns:
            Rapport complet Grok avec code corrigé et recommandations.
        """
        return await _run_code_test(
            code=code,
            language=language,
            error_message=error_message,
            context=context,
            session_id=session_id,
        )


async def _run_code_test(
    code: str,
    language: str = "python",
    error_message: Optional[str] = None,
    context: Optional[str] = None,
    session_id: Optional[str] = None,
    temperature: float = 0.2,
) -> str:
    """
    Implémentation interne — appelable depuis grok_dispatch (routing auto)
    ou directement depuis grok_code_test.
    """
    # ── Sections contextuelles ────────────────────────────────────────────────
    error_section = ""
    if error_message:
        error_section = (
            f"## ERREUR / TRACEBACK :\n"
            f"```\n{error_message.strip()}\n```\n\n"
        )

    context_section = ""
    if context:
        context_section = f"## CONTEXTE D'UTILISATION :\n{context.strip()}\n\n"

    # ── Construction du prompt ────────────────────────────────────────────────
    prompt = _CODE_PROMPT_TEMPLATE.format(
        language=language,
        code=code.strip(),
        error_section=error_section,
        context_section=context_section,
    )

    # System prompt : combinaison expert code + contexte Taranis
    taranis_context = build_system_prompt(task_type="code_test")
    system_prompt = f"{_CODE_SYSTEM_PROMPT}\n\n{taranis_context}"

    model = get_model_for_task("code")

    logger.info(
        f"grok_code_test | model={model} | lang={language} | "
        f"code_len={len(code)} chars | has_error={bool(error_message)} | "
        f"has_context={bool(context)} | session={session_id or 'none'}"
    )

    result = await call_grok(
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        temperature=temperature,
        max_tokens=4500,
        session_id=session_id,
        use_history=bool(session_id),
    )

    logger.info(
        f"grok_code_test | ✓ response received | "
        f"response_len={len(result)} chars | session={session_id or 'none'}"
    )

    return result

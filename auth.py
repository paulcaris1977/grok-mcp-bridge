"""
auth.py — Grok-Claude Bridge
Garde Bearer optionnelle devant l'app ASGI MCP.

MCP_BEARER_TOKEN absent  → aucun contrôle (comportement historique), warning au boot.
MCP_BEARER_TOKEN présent → chaque requête HTTP doit porter
                           `Authorization: Bearer <token>`, sinon 401.
Les préflights CORS (OPTIONS) passent toujours : sans ça, un client navigateur
perd le Mcp-Session-Id (cf. le correctif CORS de oauth-mcp-wrapper).

Middleware ASGI pur (pas BaseHTTPMiddleware) pour ne pas bufferiser le streaming.
"""

from __future__ import annotations

import hmac
import json
import logging
import os

logger = logging.getLogger("grok-mcp-bridge.auth")


class BearerAuth:
    def __init__(self, app, token: str):
        self.app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        provided = dict(scope.get("headers", [])).get(b"authorization", b"")
        if hmac.compare_digest(provided, self._expected):
            await self.app(scope, receive, send)
            return

        logger.warning("401 sur %s (Authorization %s)",
                       scope.get("path"), "présent" if provided else "absent")
        body = json.dumps({"error": "unauthorized"}).encode()
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b"Bearer"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})


def protect(app):
    """Enveloppe l'app si MCP_BEARER_TOKEN est défini, sinon la renvoie telle quelle."""
    token = os.environ.get("MCP_BEARER_TOKEN", "").strip()
    if not token:
        logger.warning("MCP_BEARER_TOKEN absent : /mcp est ouvert à quiconque connaît l'URL.")
        return app
    logger.info("Auth Bearer active sur /mcp.")
    return BearerAuth(app, token)

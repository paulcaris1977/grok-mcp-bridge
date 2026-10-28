"""
Tests parité Claude : requête Anthropic (effort, schema, repli, pas de temperature),
coût estimé, ask_claude (contexte Taranis, session, notes, JSON). Aucun appel réseau.
"""

import json

import httpx
import pytest
from fastmcp import Client, FastMCP

import llm_clients
import store
import tools.ask_claude as ask_mod
from llm_clients import ClaudeResult, claude_respond


def _reply(text="ok", model="claude-sonnet-5-5", stop="end_turn", **extra):
    return {"model": model, "stop_reason": stop,
            "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}],
            "usage": {"input_tokens": 1000, "output_tokens": 500}, **extra}


@pytest.fixture
def anthropic(monkeypatch):
    """Remplace l'API Anthropic : enregistre chaque requête, renvoie la réponse préparée."""
    seen = {"requests": [], "reply": _reply()}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["requests"].append(request)
        return httpx.Response(200, json=seen["reply"])

    real = httpx.AsyncClient
    monkeypatch.setattr(llm_clients.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return seen


def _body(request):
    return json.loads(request.content)


# ── client Claude ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_payload_has_effort_schema_fallback_and_no_temperature(anthropic):
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "additionalProperties": False}
    res = await claude_respond([{"role": "system", "content": "S"}, {"role": "user", "content": "Q"}],
                               effort="high", schema=json.dumps(schema))
    req = anthropic["requests"][0]
    body = _body(req)
    assert "temperature" not in body and body["system"] == "S"
    assert body["output_config"] == {"effort": "high", "format": {"type": "json_schema", "schema": schema}}
    assert body["fallbacks"] == "default" and req.headers["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert body["max_tokens"] >= 2000                      # le raisonnement ne coupe pas la réponse
    assert res.text == "ok"                                # bloc thinking ignoré
    assert res.cost_usd == pytest.approx((1000 * 2 + 500 * 10) / 1_000_000)
    assert "claude-sonnet-5-5 · effort high · 1 000 → 500 tokens · ≈ 0.007 $" in res.footer()


@pytest.mark.asyncio
async def test_no_fallback_on_models_that_reject_it(anthropic):
    await claude_respond([{"role": "user", "content": "Q"}], model="claude-sonnet-4-6")
    req = anthropic["requests"][0]
    assert "fallbacks" not in _body(req) and "anthropic-beta" not in req.headers


@pytest.mark.asyncio
async def test_refusal_and_empty_answer_raise(anthropic):
    anthropic["reply"] = _reply(stop="refusal", stop_details={"category": "cyber"})
    with pytest.raises(ValueError, match="décliné.*cyber"):
        await claude_respond([{"role": "user", "content": "Q"}])
    anthropic["reply"] = {**_reply(stop="max_tokens"), "content": [{"type": "thinking", "thinking": ""}]}
    with pytest.raises(ValueError, match="max_tokens"):
        await claude_respond([{"role": "user", "content": "Q"}])


@pytest.mark.asyncio
async def test_bad_effort_is_rejected_before_any_call(anthropic):
    with pytest.raises(ValueError, match="effort Claude inconnu"):
        await claude_respond([{"role": "user", "content": "Q"}], effort="turbo")
    assert not anthropic["requests"]


def test_unknown_model_has_no_price():
    assert ClaudeResult("x", "claude-inconnu", "low", 10, 10).cost_usd is None


# ── ask_claude ────────────────────────────────────────────────────────────────

async def _ask(args):
    mcp = FastMCP(name="test")
    ask_mod.register_ask_claude(mcp)
    async with Client(mcp) as client:
        res = await client.call_tool("ask_claude", args)
    return res


@pytest.mark.asyncio
async def test_ask_claude_has_taranis_context_and_real_session(anthropic):
    anthropic["reply"] = _reply("Alba fait le STR.")
    first = (await _ask({"prompt": "Qui fait le STR ?", "session_id": "s1"})).content[0].text
    await _ask({"prompt": "Et Querceo ?", "session_id": "s1"})

    system = _body(anthropic["requests"][0])["system"]
    assert "Taranis" in system and "Nalmaia" not in system
    assert [m["content"] for m in _body(anthropic["requests"][1])["messages"]] == [
        "Qui fait le STR ?", "Alba fait le STR.", "Et Querceo ?"]
    assert "Alba fait le STR." in first and "≈ 0.007 $" in first
    assert store.get_history("s1") == []                   # sessions Grok intactes


@pytest.mark.asyncio
async def test_ask_claude_injects_project_notes_only_when_asked(anthropic):
    store.save_note("nikka", "volumes", "5 conteneurs", "grok")
    await _ask({"prompt": "Combien ?", "project": "nikka"})
    await _ask({"prompt": "Bonjour"})
    assert "5 conteneurs" in _body(anthropic["requests"][0])["messages"][-1]["content"]
    assert _body(anthropic["requests"][1])["messages"][-1]["content"] == "Bonjour"


@pytest.mark.asyncio
async def test_ask_claude_schema_returns_data_and_meta(anthropic):
    anthropic["reply"] = _reply('{"entite": "Alba"}')
    res = await _ask({"prompt": "STR ?", "effort": "low",
                      "schema": {"type": "object", "properties": {"entite": {"type": "string"}},
                                 "required": ["entite"], "additionalProperties": False}})
    assert res.structured_content["data"] == {"entite": "Alba"}
    assert res.structured_content["meta"]["effort"] == "low"
    assert res.structured_content["meta"]["cost_usd_estimate"] == 0.007


@pytest.mark.asyncio
async def test_ask_claude_reports_bad_effort(anthropic):
    out = (await _ask({"prompt": "x", "effort": "turbo"})).content[0].text
    assert out.startswith("Erreur:") and "effort Claude inconnu" in out

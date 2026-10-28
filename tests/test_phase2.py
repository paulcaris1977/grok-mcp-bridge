"""
Tests phase 2 : mode explicite (plus de regex), verify, cross_check, débat
(parallèle, convergence, arbitre), x_pulse, structured. Aucun appel réseau.
"""

from datetime import date

import pytest
from fastmcp import Client, FastMCP

import orchestration
import tools.grok_dispatch as dispatch_mod
import tools.grok_structured as structured_mod
from grok_client import GrokResult, build_payload, search_tools
from router.router import Mode, resolve_mode
from tools.grok_structured import register_structured, schema_format
from tools.grok_x_pulse import x_search_tool


# ── mode ──────────────────────────────────────────────────────────────────────

def test_resolve_mode():
    assert resolve_mode() == Mode.GENERAL
    assert resolve_mode("critique") == Mode.CRITIQUE
    assert resolve_mode(task="code_test") == Mode.CODE
    assert resolve_mode(task="market") == Mode.RESEARCH
    assert resolve_mode("research", task="critique") == Mode.RESEARCH
    with pytest.raises(ValueError):
        resolve_mode("turbo")


async def _call(tool, args, register):
    mcp = FastMCP(name="test")
    register(mcp)
    async with Client(mcp) as client:
        return await client.call_tool(tool, args)


@pytest.mark.asyncio
async def test_no_keyword_routing_anymore(monkeypatch):
    calls = []

    async def _fake(**kwargs):
        calls.append(kwargs)
        return "OK"

    monkeypatch.setattr(dispatch_mod, "call_grok", _fake)
    # Contenait « critique » + « fût » : l'ancien routeur partait en critique ou research
    res = await _call("grok_dispatch", {"prompt": "Critique ce plan fûts Corée"}, dispatch_mod.register_dispatch)
    assert res.content[0].text == "OK" and "tools" not in calls[0]


@pytest.mark.asyncio
async def test_unknown_mode_is_reported():
    res = await _call("grok_dispatch", {"prompt": "x", "mode": "turbo"}, dispatch_mod.register_dispatch)
    assert "mode inconnu" in res.content[0].text


# ── fakes ─────────────────────────────────────────────────────────────────────

def _grok(text="Réponse Grok [[1]](https://a.example)", citations=("https://a.example",)):
    return GrokResult(text=text, model="grok-4.7", effort="medium",
                      input_tokens=100, output_tokens=50, citations=list(citations))


# ── verify ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_chains_grok_search_then_claude(monkeypatch):
    seen = {}

    async def fake_grok(messages, **kw):
        seen["tools"] = kw["tools"]
        return _grok()

    async def fake_claude(messages, **kw):
        seen["claude_input"] = messages[-1]["content"]
        return "| 1 | … | [1] | ✅ | ok |\nFiabilité globale : 4/5", "claude-test"

    monkeypatch.setattr(orchestration, "grok_respond", fake_grok)
    monkeypatch.setattr(orchestration, "claude_chat", fake_claude)
    out = await orchestration.run_verify("prix fûts Japon", sources="web")
    assert seen["tools"] == [{"type": "web_search"}]
    assert "https://a.example" in seen["claude_input"]      # Claude voit les sources
    assert "# 🔎 Recherche Grok" in out and "Fiabilité globale : 4/5" in out


@pytest.mark.asyncio
async def test_verify_survives_claude_failure(monkeypatch):
    async def fake_grok(messages, **kw):
        return _grok()

    async def boom(messages, **kw):
        raise RuntimeError("anthropic down")

    monkeypatch.setattr(orchestration, "grok_respond", fake_grok)
    monkeypatch.setattr(orchestration, "claude_chat", boom)
    out = await orchestration.run_verify("x")
    assert "Réponse Grok" in out and "Contrôle Claude indisponible" in out


# ── cross_check ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_check_compares_both(monkeypatch):
    prompts = []

    async def fake_grok(messages, **kw):
        assert kw["tools"] is None          # pas de recherche sans sources
        return _grok("A dit oui", ())

    async def fake_claude(messages, **kw):
        prompts.append(messages[-1]["content"])
        if "=== A (Grok) ===" in messages[-1]["content"]:
            return "## Accords\n…", "claude-judge"
        return "B dit non", "claude-test"

    monkeypatch.setattr(orchestration, "grok_respond", fake_grok)
    monkeypatch.setattr(orchestration, "claude_chat", fake_claude)
    out = await orchestration.run_cross_check("Faut-il aller en Inde ?")
    assert "A dit oui" in prompts[-1] and "B dit non" in prompts[-1]
    assert "## Accords" in out and "claude-judge" in out


@pytest.mark.asyncio
async def test_cross_check_one_side_down(monkeypatch):
    async def fake_grok(messages, **kw):
        raise RuntimeError("xai down")

    async def fake_claude(messages, **kw):
        return "B seule", "claude-test"

    monkeypatch.setattr(orchestration, "grok_respond", fake_grok)
    monkeypatch.setattr(orchestration, "claude_chat", fake_claude)
    out = await orchestration.run_cross_check("q")
    assert out.startswith("⚠️ Grok en échec") and "B seule" in out


@pytest.mark.asyncio
async def test_cross_check_rejects_unknown_judge():
    with pytest.raises(ValueError):
        await orchestration.run_cross_check("q", judge="gemini")


# ── debate ────────────────────────────────────────────────────────────────────

def test_agrees():
    assert orchestration._agrees("blabla\n**ACCORD**")
    assert not orchestration._agrees("blabla\nDÉSACCORD")
    assert not orchestration._agrees("je suis d'accord sur l'essentiel")


@pytest.mark.asyncio
async def test_debate_stops_on_agreement_and_synthesises(monkeypatch):
    grok_replies = iter(["G1", "G2\nACCORD", "G3"])
    claude_replies = iter(["C1", "C2\nACCORD", "C3"])

    async def fake_grok_chat(messages, **kw):
        return next(grok_replies), "grok-low"

    async def fake_claude_chat(messages, **kw):
        if "arbitre" in messages[0]["content"]:
            assert "[Grok — tour 2]" in messages[-1]["content"]
            return "## Accords\nsynthèse", "claude-judge"
        return next(claude_replies), "claude-test"

    monkeypatch.setattr(orchestration, "grok_chat", fake_grok_chat)
    monkeypatch.setattr(orchestration, "claude_chat", fake_claude_chat)
    r = await orchestration.run_debate("Corée ou Inde ?", turns=4)
    assert r.turns_done == 2 and r.converged and not r.error
    assert [h["speaker"] for h in r.history] == ["Grok", "Claude", "Grok", "Claude"]
    assert r.synthesis.startswith("## Accords") and r.judge_model == "claude-judge"


@pytest.mark.asyncio
async def test_debate_keeps_history_when_a_side_fails(monkeypatch):
    calls = {"n": 0}

    async def fake_grok_chat(messages, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("xai down")
        return "G1", "grok-low"

    async def fake_claude_chat(messages, **kw):
        return ("synthèse" if "arbitre" in messages[0]["content"] else "C1"), "claude-test"

    monkeypatch.setattr(orchestration, "grok_chat", fake_grok_chat)
    monkeypatch.setattr(orchestration, "claude_chat", fake_claude_chat)
    r = await orchestration.run_debate("q", turns=3)
    assert r.turns_done == 1 and "Grok tour 2" in r.error and r.synthesis == "synthèse"


# ── x_pulse ───────────────────────────────────────────────────────────────────

def test_x_search_tool():
    t = x_search_tool(7, ["@NikkaWhisky", " ", "suntory"], today=date(2026, 10, 28))
    assert t == {"type": "x_search", "from_date": "2026-10-21",
                 "allowed_x_handles": ["NikkaWhisky", "suntory"]}
    assert x_search_tool(500, today=date(2026, 10, 28))["from_date"] == "2026-07-30"   # plafonné à 90 j


# ── structured ────────────────────────────────────────────────────────────────

def test_schema_format_and_payload():
    fmt = schema_format('{"type": "object", "properties": {"a": {"type": "string"}}}', name="prix fûts!")
    assert fmt["name"] == "prix_f_ts_" and fmt["strict"] is True
    with pytest.raises(ValueError):
        schema_format("pas du json")
    with pytest.raises(ValueError):
        schema_format({"properties": {}})
    p = build_payload([{"role": "user", "content": "x"}], "medium", tools=search_tools("web"), text_format=fmt)
    assert p["text"] == {"format": fmt} and p["include"] == ["no_inline_citations"]


@pytest.mark.asyncio
async def test_grok_structured_returns_data_and_meta(monkeypatch):
    seen = {}

    async def fake_grok(messages, **kw):
        seen.update(kw)
        return _grok('{"distilleries": 118}', ("https://a.example",))

    monkeypatch.setattr(structured_mod, "grok_respond", fake_grok)
    schema = {"type": "object", "properties": {"distilleries": {"type": "integer"}}, "required": ["distilleries"]}
    res = await _call("grok_structured", {"prompt": "Combien ?", "schema": schema, "sources": "web"},
                      register_structured)
    assert res.structured_content["data"] == {"distilleries": 118}
    assert res.structured_content["meta"]["citations"] == ["https://a.example"]
    assert seen["text_format"]["schema"] == schema

"""Deterministic tests — no LLM / no network required.

These exercise the parts that must hold regardless of any model: the exact
graph analysis, the regex fallback extractor, the regime-gate heuristic, the
consistency reference, and the feedback loop driven by an *injected* fake
backend. This is what CI runs.
"""
import io
import os
import sys
import tempfile

import llm_feedback_control as lfc
from llm_feedback_control import (
    run_audit, extract_iterative, regime_gate, exact_analysis, graph_facts,
    fallback_extract, consistency_gaps, valid, norm,
    extract_form, feedback_loop, form_field_gaps, fallback_extract_form,
)

WORKFLOW = ("A claim enters Intake. From Intake it goes to Triage. Triage goes "
            "to FastTrack or to Investigation. FastTrack goes to Payout. "
            "Investigation goes to Payout or to Denied. Payout goes to Closed. "
            "Denied goes to Closed.")


# --- exact analysis -------------------------------------------------------
def test_graph_facts_terminals_and_cycle():
    states = ["A", "B", "C"]
    trans = [("A", "B"), ("B", "C")]
    f = graph_facts(states, trans)
    assert f["terminal_states"] == ["C"]
    assert f["unreachable_states"] == []
    assert f["has_cycle"] is False


def test_graph_facts_detects_cycle_and_unreachable():
    states = ["A", "B", "C", "X"]
    trans = [("A", "B"), ("B", "A")]  # A<->B loop; C and X unreachable from A
    f = graph_facts(states, trans)
    assert f["has_cycle"] is True
    assert set(f["unreachable_states"]) == {"C", "X"}


def test_exact_analysis_shape():
    g = fallback_extract(WORKFLOW)
    tr = [tuple(t) for t in g["transitions"]]
    trace = exact_analysis(g["states"], tr)
    assert {pp["prime"] for pp in trace["primes"]} == {2, 3, 5, 7}
    assert "facts" in trace and "terminal_states" in trace["facts"]


# --- deterministic extraction --------------------------------------------
def test_fallback_extract_recovers_branches():
    g = fallback_extract(WORKFLOW)
    s = {norm(x) for x in g["states"]}
    for expected in ["intake", "triage", "fasttrack", "investigation",
                     "payout", "denied", "closed"]:
        assert expected in s
    assert valid(g)


def test_valid_schema():
    assert valid({"states": ["A"], "transitions": [["A", "B"]]})
    assert not valid({"states": ["A"], "transitions": [["A", "B", "C"]]})
    assert not valid({"states": "A", "transitions": []})


# --- regime gate ----------------------------------------------------------
def test_gate_refuses_continuous_without_model():
    # use_llm=False -> pure heuristic, no network
    v = regime_gate("The market price drifts up as confidence grows.",
                    use_llm=False)["verdict"]
    assert v == "model_only"


def test_gate_accepts_finite_without_model():
    v = regime_gate(WORKFLOW, use_llm=False)["verdict"]
    assert v == "finite_structural"


# --- consistency reference ------------------------------------------------
def test_consistency_gaps_flags_missing_branch():
    # graph dropped the Investigation->Denied branch the text mentions
    partial = {"states": ["Intake", "Triage", "FastTrack", "Investigation",
                          "Payout", "Closed"],
               "transitions": [["Intake", "Triage"], ["Triage", "FastTrack"],
                               ["FastTrack", "Payout"], ["Payout", "Closed"]]}
    miss_s, miss_t = consistency_gaps(WORKFLOW, partial)
    assert "Denied" in miss_s


# --- run_audit with NO model (deterministic fallback) ---------------------
def test_run_audit_falls_back_when_backend_unavailable():
    """Inject a backend that fails (== no model reachable): the pipeline must
    still return a real result via the deterministic regex path."""
    def dead(prompt, fmt=None, **kw):
        raise lfc.BackendError("no backend reachable")

    r = run_audit(WORKFLOW, generate=dead)
    assert r["result"].startswith("OK")
    assert r["extraction"]["via"] == "fallback"   # no server -> regex path
    assert "Closed" in r["extraction"]["states"]


def test_run_audit_refuses_model_only():
    r = run_audit("Sentiment improves gradually as trust accumulates.")
    assert r["result"].startswith("REFUSED")


# --- injectable backend ---------------------------------------------------
def test_injectable_backend_is_used():
    """A fake generate() proves the LLM seam works without any real model."""
    perfect = ('{"states":["Intake","Triage","FastTrack","Investigation",'
               '"Payout","Denied","Closed"],'
               '"transitions":[["Intake","Triage"],["Triage","FastTrack"],'
               '["Triage","Investigation"],["FastTrack","Payout"],'
               '["Investigation","Payout"],["Investigation","Denied"],'
               '["Payout","Closed"],["Denied","Closed"]]}')

    def fake_gen(prompt, fmt=None, **kw):
        return perfect

    graph, initial, history, converged = extract_iterative(
        WORKFLOW, generate=fake_gen, verbose=False)
    assert converged is True
    assert {norm(s) for s in graph["states"]} >= {"denied", "payout", "closed"}


def test_doctor_never_raises():
    d = lfc.doctor()
    assert "ollama_reachable" in d and "small_model" in d


# --- generic feedback loop (the injectable engine) ------------------------
def test_feedback_loop_converges_and_clamps():
    def extract(t): return {"v": 0}
    def reference(t, c): return [] if c["v"] >= 2 else ["too low"]
    def repair(t, c, gaps): return {"v": c["v"] + 1}
    cand, initial, hist, conv = feedback_loop(
        "x", extract=extract, reference=reference, repair=repair,
        signature=lambda c: c["v"], max_iters=5)
    assert conv is True and cand["v"] == 2 and initial["v"] == 0

    # never satisfiable -> refusal clamp fires (converged False)
    cand, _, _, conv = feedback_loop(
        "x", extract=lambda t: {"v": 0}, reference=lambda t, c: ["never"],
        repair=lambda t, c, g: {"v": c["v"] + 1}, signature=lambda c: c["v"],
        max_iters=3)
    assert conv is False


# --- form-field target ----------------------------------------------------
FORM_SCHEMA = {"fields": [
    {"name": "name",   "type": "string",  "required": True},
    {"name": "ref",    "type": "pattern", "required": True, "pattern": r"[A-Z]{2}-\d{6}"},
    {"name": "email",  "type": "email",   "required": True},
    {"name": "amount", "type": "currency", "required": True},
    {"name": "kind",   "type": "enum", "required": True, "values": ["fire", "theft"]},
]}
FORM_TEXT = ("Jane Doe, policy AB-123456, reach me at jane@x.com, total $200, "
             "this is a fire claim.")


def test_form_detectors_fill_without_model():
    """No model: detectors deterministically fill the detectable fields."""
    rec = fallback_extract_form(FORM_TEXT, FORM_SCHEMA)
    assert rec["email"] == "jane@x.com"
    assert rec["ref"] == "AB-123456"
    assert "200" in str(rec["amount"])
    assert rec["name"] is None          # string: not detectable


def test_form_field_gaps_flags_missing_and_hallucinated():
    miss = form_field_gaps("contact real@x.com", {"fields": [
        {"name": "email", "type": "email", "required": True}]}, {"email": None})
    assert any(g["field"] == "email" and g["problem"] == "missing_required" for g in miss)

    hall = form_field_gaps("the only address is real@x.com", {"fields": [
        {"name": "email", "type": "email", "required": True}]}, {"email": "fake@y.com"})
    assert any("not found in source text" in g["problem"] for g in hall)


def test_extract_form_refuses_unfindable_required_field():
    """Dead backend + a required string the detectors can't see -> REFUSE,
    but the detectable fields are still recovered from the text."""
    def dead(prompt, fmt=None, **kw):
        raise lfc.BackendError("no backend")
    out = extract_form(FORM_TEXT, FORM_SCHEMA, generate=dead)
    assert out["record"]["email"] == "jane@x.com"      # recovered deterministically
    assert out["record"]["ref"] == "AB-123456"
    assert out["result"].startswith("REFUSED")          # 'name' can't be found
    assert "name" in {g["field"] for g in out["gaps"]}


def test_extract_form_ok_with_perfect_backend():
    perfect = ('{"name":"Jane Doe","ref":"AB-123456","email":"jane@x.com",'
               '"amount":"$200","kind":"fire"}')
    def fake(prompt, fmt=None, **kw): return perfect
    out = extract_form(FORM_TEXT, FORM_SCHEMA, generate=fake)
    assert out["converged"] is True
    assert out["result"] == "OK"
    assert out["record"]["kind"] == "fire"


# ── CLI --form / --schema tests ────────────────────────────────────────────
from llm_feedback_control.__main__ import _load_schema, main

INLINE_SCHEMA = '{"fields": [{"name":"email","type":"email","required":true}]}'
FORM_TEXT_CLI = "contact me at test@example.com"
FORM_SCHEMA_OBJ = {"fields": [{"name":"email", "type": "email", "required": True}]}


def test_load_schema_inline_json():
    """Inline JSON string parses to a valid schema dict."""
    s = _load_schema(INLINE_SCHEMA)
    assert s == FORM_SCHEMA_OBJ


def test_load_schema_from_file():
    """A schema file is read and parsed correctly."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                     encoding="utf-8", delete=False) as f:
        f.write(INLINE_SCHEMA)
        tmp = f.name
    try:
        s = _load_schema(tmp)
        assert s == FORM_SCHEMA_OBJ
    finally:
        os.unlink(tmp)


def test_load_schema_at_prefix():
    """@file reads the file path after the @."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                     encoding="utf-8", delete=False) as f:
        f.write(INLINE_SCHEMA)
        tmp = f.name
    try:
        s = _load_schema("@" + tmp)
        assert s == FORM_SCHEMA_OBJ
    finally:
        os.unlink(tmp)


def test_load_schema_missing_fields_key():
    """Schema without 'fields' raises ValueError."""
    try:
        _load_schema('{"notfields":[]}')
        assert False, "expected ValueError"
    except ValueError as e:
        assert "fields" in str(e)


def test_load_schema_duplicate_field():
    """Duplicate field names raise ValueError."""
    try:
        _load_schema('{"fields":[{"name":"x","type":"string"},{"name":"x","type":"string"}]}')
        assert False, "expected ValueError"
    except ValueError as e:
        assert "duplicate" in str(e)


def test_cli_form_inline_schema():
    """--form --schema <inline> <text> returns OK with a perfect generate."""
    perfect = '{"email":"test@example.com"}'
    def fake(prompt, fmt=None, **kw):
        return perfect
    import llm_feedback_control.forms as forms
    orig = forms.gen
    forms.gen = fake
    try:
        out = io.StringIO()
        sys.stdout = out
        rc = main(["--form", "--schema", INLINE_SCHEMA, FORM_TEXT_CLI])
        sys.stdout = sys.__stdout__
        output = out.getvalue()
    finally:
        forms.gen = orig
    assert rc == 0
    assert "OK" in output and "REFUSED" not in output


def test_cli_form_json_output():
    """--form --schema --json emits valid JSON."""
    perfect = '{"email":"test@example.com"}'
    def fake(prompt, fmt=None, **kw):
        return perfect
    import llm_feedback_control.forms as forms
    orig = forms.gen
    forms.gen = fake
    try:
        out = io.StringIO()
        sys.stdout = out
        rc = main(["--form", "--schema", INLINE_SCHEMA,
                   "--json", FORM_TEXT_CLI])
        sys.stdout = sys.__stdout__
        output = out.getvalue()
    finally:
        forms.gen = orig
    assert rc == 0
    import json
    data = json.loads(output)
    assert "record" in data
    assert "result" in data
    assert data["result"] == "OK"


def test_cli_form_missing_schema():
    """--form without --schema uses the built-in default schema."""
    out = io.StringIO()
    sys.stdout = out
    rc = main(["--form", FORM_TEXT_CLI])
    sys.stdout = sys.__stdout__
    assert rc == 0
    output = out.getvalue()
    # the default schema + user's text should still extract detectable fields
    assert "test@example.com" in output


def test_cli_form_invalid_schema():
    """--form --schema with garbage JSON gives error."""
    out = io.StringIO()
    sys.stdout = out
    rc = main(["--form", "--schema", "not-json-at-all", FORM_TEXT_CLI])
    sys.stdout = sys.__stdout__
    assert rc == 1
    assert "error" in out.getvalue().lower()


def test_cli_form_no_text_uses_sample():
    """With no text argument, --form uses the built-in sample."""
    out = io.StringIO()
    sys.stdout = out
    rc = main(["--form", "--schema", INLINE_SCHEMA])
    sys.stdout = sys.__stdout__
    assert rc == 0
    output = out.getvalue()
    # should mention the built-in sample message
    assert "built-in" in output.lower() or "sample" in output.lower()


def test_cli_form_refuses_with_dead_backend():
    """Dead backend + undetectable required string field -> REFUSED, not crash."""
    def dead(prompt, fmt=None, **kw):
        raise lfc.BackendError("no backend")
    schema_str = '{"fields":[{"name":"name","type":"string","required":true}]}'
    import llm_feedback_control.forms as forms
    orig = forms.gen
    forms.gen = dead
    try:
        out = io.StringIO()
        sys.stdout = out
        rc = main(["--form", "--schema", schema_str, "some text here"])
        sys.stdout = sys.__stdout__
    finally:
        forms.gen = orig
    assert rc == 0
    output = out.getvalue()
    assert "REFUSED" in output


def test_cli_form_file_schema():
    """--form --schema <file> works end-to-end through main()."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                     encoding="utf-8", delete=False) as f:
        f.write(INLINE_SCHEMA)
        tmp = f.name
    try:
        out = io.StringIO()
        sys.stdout = out
        rc = main(["--form", "--schema", tmp, FORM_TEXT_CLI])
        sys.stdout = sys.__stdout__
    finally:
        os.unlink(tmp)
    assert rc == 0
    assert "test@example.com" in out.getvalue()


def test_cli_form_at_prefix():
    """--form --schema @file works end-to-end through main()."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                     encoding="utf-8", delete=False) as f:
        f.write(INLINE_SCHEMA)
        tmp = f.name
    try:
        out = io.StringIO()
        sys.stdout = out
        rc = main(["--form", "--schema", "@" + tmp, FORM_TEXT_CLI])
        sys.stdout = sys.__stdout__
    finally:
        os.unlink(tmp)
    assert rc == 0
    assert "test@example.com" in out.getvalue()


def test_cli_form_nonexistent_file():
    """--schema nonexistent.json gives a clear error (not a JSON parse error)."""
    out = io.StringIO()
    sys.stdout = out
    rc = main(["--form", "--schema", "nonexistent.json", "text"])
    sys.stdout = sys.__stdout__
    assert rc == 1
    output = out.getvalue()
    assert "error" in output.lower()
    assert "no such file" in output.lower() or "nonexistent" in output.lower()

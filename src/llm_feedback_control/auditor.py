"""The LLM-feedback-control pipeline, end-to-end and self-contained.

A small LLM is wrapped in a deterministic feedback network so the system knows
what it can compute exactly, does so, and refuses the rest:

    English text
      -> extract finite transition system   (LLM + schema + deterministic fallback)
      -> regime gate                         (hybrid: heuristic + LLM tie-break)
      -> exact analysis                      (standard graph facts + an optional
                                              finite-field spectral fingerprint)
      -> readout contract + injectivity      (refuse non-injective lifts)
      -> grounded report                     (every claim backed by a trace fact)

This is the NEGATIVE-feedback half (gate / ground / refuse). The bounded
POSITIVE-feedback loop (iterate-to-fixed-point re-extraction) lives in
feedback.py.

Every entry point that can use an LLM takes an injectable ``generate`` callable
(``f(prompt, fmt=None) -> str``); it defaults to the local-Ollama client in
``llm.py``. If no model is reachable, the pipeline degrades to the deterministic
path automatically — so ``run_audit`` returns a real result with no model at all.

Demos (run ``python -m llm_feedback_control.auditor``):
  M1  process auditor on a real workflow (exact trace + grounded report)
  M2  gate refusal on belief/continuous input ("model-only, refused")
  M3  non-injective readout refusal (the no-hallucinated-synthesis guard)
plus a HARDENING test of the gate on deliberately ambiguous / mixed inputs.
"""
import sys, json, re

from .llm import gen

# The console on some platforms (e.g. Windows cp1252) can't encode the box-drawing
# and maths glyphs in the demos; switch stdout to UTF-8 where the runtime allows it.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def norm(s):
    """Normalise a state/name for comparison: lower-case and strip everything but
    alphanumerics, so "Fast Track", "fast-track" and "FastTrack" all compare equal."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


# === exact engine: F_p fp_orbit + graph facts (self-contained) ============
# An OPTIONAL extra check. We treat the transition graph as a linear map over a
# finite field F_p and look at its long-run behaviour ("standing mode"). It powers
# the M3 non-injective-readout refusal; for ordinary workflow audits it is largely
# redundant with the plain graph facts below.
PRIMES = (2, 3, 5, 7)


def fp_orbit(M, x0, p, max_steps=20000):
    """Iterate the linear map ``x -> M·x (mod p)`` from ``x0`` and find its cycle.

    The state space (vectors mod p) is finite, so the orbit must eventually repeat.
    We remember every vector we've seen and the step it first appeared at; the
    moment one recurs we've closed the loop. Returns ``(transient, period, cycle)``
    — the number of steps before the cycle begins, its length, and the list of
    vectors in the cycle (``(None, None, [])`` if it never settled in max_steps)."""
    n = len(x0); x = [v % p for v in x0]; seen = {}; orbit = []
    for t in range(max_steps):
        k = tuple(x)
        if k in seen:                              # this vector recurred -> cycle found
            s = seen[k]
            return s, t - s, orbit[s:]             # transient length, period, cycle vectors
        seen[k] = t; orbit.append(x)
        # advance one step over F_p:  x <- M·x  (mod p)
        x = [sum(M[i][j] * x[j] for j in range(n)) % p for i in range(n)]
    return None, None, []                          # never settled within the step budget


def transfer_operator(states, trans, p):
    """Build the mod-p transfer matrix ``M`` of the transition graph.

    ``M[b][a]`` counts edges ``a -> b`` (the *column* is the source state), so that
    multiplying a state-vector by M propagates "mass" one step along the
    transitions: ``(M·x)[b] = Σ_a edges(a->b)·x[a]``. Returns ``(M, idx)`` where
    ``idx`` maps each state name to its row/column index."""
    idx = {s: i for i, s in enumerate(states)}; n = len(states)
    M = [[0] * n for _ in range(n)]
    for a, b in trans:
        if a in idx and b in idx:
            M[idx[b]][idx[a]] = (M[idx[b]][idx[a]] + 1) % p     # add an edge a -> b
    return M, idx


def graph_facts(states, trans):
    """Provable structural facts about the graph, with no model involved: terminal
    states (no outgoing edge), states unreachable from the start (``states[0]``), and
    whether the graph contains a cycle."""
    # adjacency list: state -> list of successors
    out = {s: [b for a, b in trans if a == s] for s in states}
    terminals = sorted(s for s in states if not out.get(s))
    # reachability: depth-first flood from the start state (the first one listed)
    start = states[0] if states else None
    seen = set()
    if start is not None:
        stack = [start]; seen = {start}
        while stack:
            u = stack.pop()
            for v in out.get(u, []):
                if v not in seen:
                    seen.add(v); stack.append(v)
    unreachable = sorted(s for s in states if s not in seen)
    # cycle detection via three-colour DFS: a GREY node reached again = back edge = cycle
    WHITE, GREY, BLACK = 0, 1, 2
    color = {s: WHITE for s in states}; has_cycle = [False]
    def dfs(u):
        color[u] = GREY
        for v in out.get(u, []):
            if color.get(v) == GREY:
                has_cycle[0] = True
            elif color.get(v) == WHITE:
                dfs(v)
        color[u] = BLACK
    for s in states:
        if color[s] == WHITE:
            dfs(s)
    return dict(terminal_states=terminals, unreachable_states=unreachable,
                has_cycle=has_cycle[0])


def exact_analysis(states, trans):
    """Per-prime exact trace + bad-prime + readout injectivity (the M3 guard).

    For each prime we launch a unit of mass at the start state and follow the
    transfer operator to its standing mode (the cycle). A prime is "bad" if the
    mode annihilates (the all-zero vector — common for acyclic graphs). The
    "readout" is the sum of each mode vector; if two distinct mode vectors collapse
    to the same readout, the readout is *non-injective* and the M3 guard refuses to
    lift through it. Returns ``{"primes": [...], "facts": graph_facts(...)}``."""
    if not states:
        return {"primes": [], "facts": graph_facts(states, trans)}
    x0 = [1] + [0] * (len(states) - 1)               # launch a unit at the start state
    per_prime = []
    for p in PRIMES:
        M, _ = transfer_operator(states, trans, p)
        transient, period, cycle = fp_orbit(M, x0, p)
        mode = cycle[0] if cycle else [0] * len(states)
        bad = all(v == 0 for v in mode)              # mode annihilates -> nothing to read
        # readout = sum of each cycle vector; injective iff distinct vectors give
        # distinct readouts (otherwise a lift through the readout is ambiguous).
        readouts = [sum(v) % p for v in cycle] if cycle else []
        distinct_vecs = len({tuple(v) for v in cycle})
        injective = len(set(readouts)) == distinct_vecs if cycle else True
        per_prime.append(dict(prime=p, transient=transient, period=period,
                              mode=mode, bad_prime=bad, readout_injective=injective))
    return {"primes": per_prime, "facts": graph_facts(states, trans)}


# === regime gate (hybrid: heuristic + LLM tie-break) ======================
# Cue phrases that point each way. The gate counts them; a clear margin is decided
# by the heuristic alone, and only genuinely ambiguous text consults the LLM.
CONT_BELIEF = ["continuous", "continuously", "drift", "rises", "grows", "increase",
               "rate", "percent", "gradually", "slowly", "temperature", "price",
               "demand", "confidence", "trust", "trusts", "trustworthy", "feels",
               "happier", "sentiment", "usually", "accumulat", "improves", "volume"]
FINITE_CUES = ["goes to", "moves from", "enters", "starts in", "opens in", "proceed to",
               "escalates", "commits", "rolls back", "either", " or ", "then",
               "if approved", "if rejected", "if unresolved", "retry", "fails"]


def gate_heuristic(text):
    """Cheap, model-free signal for the regime gate: how many finite-structural cue
    phrases appear vs continuous/belief ones. Returns ``(finite_count, cont_count)``."""
    t = text.lower()
    cont = sum(t.count(c) for c in CONT_BELIEF)
    fin = sum(t.count(c) for c in FINITE_CUES)
    return fin, cont


def regime_gate(text, use_llm=True, generate=None):
    """Route text into "finite_structural", "model_only", or "mixed".

    Clear cases are decided by a cheap heuristic; only genuinely ambiguous cases
    consult the LLM (``generate`` or the default Ollama client). With no model
    reachable the LLM tie-break is skipped and the heuristic decides."""
    g = generate or gen
    fin, cont = gate_heuristic(text)
    margin = abs(fin - cont)
    # Clear case: a comfortable margin one way, and not a strong tug-of-war (both
    # cue types present in force). Decide by the heuristic, no model needed.
    if margin >= 2 and not (fin > 0 and cont > 0 and min(fin, cont) >= 2):
        verdict = "finite_structural" if fin > cont else "model_only"
        return dict(verdict=verdict, reason=f"heuristic (fin={fin},cont={cont})", source="heuristic")
    # Ambiguous / mixed: ask the LLM to adjudicate (best-effort; ignore failures).
    if use_llm:
        try:
            raw = g('Classify the description into exactly one label: '
                    '"finite_structural" (a finite set of states and transitions), '
                    '"model_only" (continuous/probabilistic/belief-driven, no finite state machine), '
                    'or "mixed" (both). Return JSON {"label": "..."}. '
                    f'Description: "{text}"', fmt="json")
            label = json.loads(raw).get("label", "").strip()
            if label in ("finite_structural", "model_only", "mixed"):
                return dict(verdict=label, reason=f"LLM tie-break (fin={fin},cont={cont})", source="llm")
        except Exception:
            pass
    # No model (or it declined to answer): both cue types present -> mixed; else heuristic.
    if fin > 0 and cont > 0:
        return dict(verdict="mixed", reason=f"both cues present (fin={fin},cont={cont})", source="heuristic")
    return dict(verdict="finite_structural" if fin >= cont else "model_only",
                reason=f"heuristic-fallback (fin={fin},cont={cont})", source="heuristic")


# === extraction (LLM + schema + deterministic fallback) ===================
def valid(o):
    """Schema check for an extracted machine: a dict whose ``states`` is a list and
    whose ``transitions`` is a list of two-element ``[from, to]`` pairs."""
    return (isinstance(o, dict) and isinstance(o.get("states"), list)
            and isinstance(o.get("transitions"), list)
            and all(isinstance(t, list) and len(t) == 2 for t in o["transitions"]))


def fallback_extract(text):
    """Deterministic, model-free extractor used when no LLM is available (or its
    output is unusable). Pulls "X goes to Y (or Z)" transitions and "enters/starts
    in X" states out of the text by regex."""
    st, tr = set(), set()
    for m in re.finditer(r"([A-Z][A-Za-z0-9]+)\s+(?:goes to|moves to|to)\s+([A-Z][A-Za-z0-9]+)"
                         r"(?:\s+or(?: to)?\s+([A-Z][A-Za-z0-9]+))?", text):
        a, b, c = m.group(1), m.group(2), m.group(3)
        st |= {a, b}; tr.add((a, b))
        if c: st.add(c); tr.add((a, c))             # "... or (to) Z" -> second edge a -> c
    for m in re.finditer(r"(?:enters|starts in|opens in)\s+([A-Z][A-Za-z0-9]+)", text):
        st.add(m.group(1))
    # Order states by FIRST APPEARANCE in the text, not alphabetically: the graph
    # analysis treats states[0] as the start, so "start = first state mentioned"
    # must hold (this matches how an LLM lists them in narrative order).
    first = {}
    for m in re.finditer(r"[A-Z][A-Za-z0-9]+", text):
        first.setdefault(m.group(0), len(first))
    states = sorted(st, key=lambda s: first.get(s, len(first)))
    return {"states": states, "transitions": [list(t) for t in sorted(tr)]}


def extract_workflow(text, generate=None):
    """Extract a finite state machine: a schema-validated LLM call with a
    deterministic regex fallback. Returns ``(graph, how)`` where ``how`` is "llm"
    or "fallback"."""
    g = generate or gen
    try:
        raw = g('Extract the finite state machine. Return ONLY JSON '
                '{"states":[...],"transitions":[["FROM","TO"],...]} using exact state '
                f'names from the text. Text: "{text}"', fmt="json")
        o = json.loads(raw)
        if valid(o) and o["states"]:
            return o, "llm"
    except Exception:
        pass
    return fallback_extract(text), "fallback"


# === grounded report ======================================================
def grounded_report(states, trace, llm=True, generate=None):
    """Render the verified facts as a deterministic text block and, optionally, an
    LLM rewrite constrained to name only those facts. Returns
    ``(facts_text, english_text)``. The deterministic block is always
    authoritative; the English is decorative and is marked unavailable if no model
    answers."""
    facts = trace["facts"]
    bad = [pp["prime"] for pp in trace["primes"] if pp["bad_prime"]]
    noninj = [pp["prime"] for pp in trace["primes"] if not pp["readout_injective"]]
    deterministic = (
        f"- States ({len(states)}): {', '.join(states)}\n"
        f"- Terminal states: {', '.join(facts['terminal_states']) or 'none'}\n"
        f"- Unreachable from start: {', '.join(facts['unreachable_states']) or 'none'}\n"
        f"- Contains a cycle (loop): {facts['has_cycle']}\n"
        f"- Bad primes (mode annihilates): {bad or 'none'}\n"
        f"- Non-injective readout at primes (lift REFUSED): {noninj or 'none'}\n"
    )
    english = ""
    if llm:
        g = generate or gen
        try:
            # Constrain the model to the verified facts so the prose can't drift.
            english = g("Write two plain sentences describing this process using ONLY "
                        "these verified facts. Name only the listed states; invent nothing.\n"
                        + deterministic).strip()
        except Exception:
            english = "(LLM rewrite unavailable; deterministic facts above are authoritative.)"
    return deterministic, english


# === end-to-end audit =====================================================
def run_audit(text, verbose=True, generate=None):
    """Full pipeline: gate -> extract -> exact analysis -> grounded report, with
    explicit refusals. Works with no model (deterministic fallback); pass
    ``generate`` to use a specific LLM backend. Returns a result dict whose
    ``result`` is "OK", "OK (mixed: ...)", or a "REFUSED: ..." string."""
    gate = regime_gate(text, generate=generate)
    out = {"text": text, "gate": gate}
    # Refuse continuous/belief input outright — there is no finite machine to analyse.
    if gate["verdict"] == "model_only":
        out["result"] = "REFUSED: model-only regime; no exact finite-structural analysis."
        return out
    graph, how = extract_workflow(text, generate=generate)
    out["extraction"] = {"via": how, "states": graph["states"], "transitions": graph["transitions"]}
    if not graph["states"]:
        out["result"] = "REFUSED: no finite structure could be extracted."
        return out
    trace = exact_analysis(graph["states"], [tuple(t) for t in graph["transitions"]])
    out["trace"] = trace
    det, eng = grounded_report(graph["states"], trace, llm=True, generate=generate)
    out["report_facts"] = det
    out["report_english"] = eng
    out["result"] = "OK" + (" (mixed: finite part analysed, continuous part deferred)"
                            if gate["verdict"] == "mixed" else "")
    return out


# === demos ================================================================
def banner(t):
    print("\n" + "=" * 74 + f"\n{t}\n" + "=" * 74)


def demo_M1():
    """M1: the full pipeline on a clean workflow — extract, analyse, report."""
    banner("M1 — process auditor (full pipeline, exact trace + grounded report)")
    text = ("A customer order enters Review. If approved it goes to Packing. If "
            "rejected it goes to Refund. Packing goes to Shipped. Shipped goes to "
            "Closed. Refund goes to Closed.")
    r = run_audit(text)
    print("gate     :", r["gate"]["verdict"], "|", r["gate"]["reason"])
    print("extracted:", r["extraction"]["via"], r["extraction"]["states"])
    print("report facts:\n" + r["report_facts"])
    print("grounded english:", r.get("report_english", "")[:300])
    print("result   :", r["result"])


def demo_M2():
    """M2: the gate refusing continuous/belief input (no fake state machine)."""
    banner("M2 — gate refusal on belief/continuous input")
    text = "The market price drifts until confidence improves, then buyers slowly return."
    r = run_audit(text)
    print("input   :", text)
    print("gate    :", r["gate"]["verdict"], "|", r["gate"]["reason"])
    print("result  :", r["result"])


def demo_M3():
    """M3: a symmetric 4-cycle whose F_p standing mode has several vectors that
    collapse to the same sum-readout — so the lift through that readout is refused."""
    banner("M3 — non-injective readout refusal (no hallucinated synthesis)")
    states = ["S0", "S1", "S2", "S3"]
    trans = [("S0", "S1"), ("S1", "S2"), ("S2", "S3"), ("S3", "S0"),
             ("S1", "S0"), ("S2", "S1"), ("S3", "S2"), ("S0", "S3")]  # undirected 4-cycle
    trace = exact_analysis(states, trans)
    for pp in trace["primes"]:
        tag = "BAD-PRIME" if pp["bad_prime"] else ("READOUT NON-INJECTIVE -> LIFT REFUSED"
              if not pp["readout_injective"] else "ok")
        print(f"  prime {pp['prime']}: period={pp['period']} mode={pp['mode']}  -> {tag}")
    refused = [pp["prime"] for pp in trace["primes"] if not pp["readout_injective"] or pp["bad_prime"]]
    print(f"  => CRT synthesis runs ONLY over primes with injective readouts; "
          f"refused/degenerate primes excluded: {refused}")


def test_gate_hard():
    """Stress the gate on deliberately ambiguous / mixed inputs, comparing the
    heuristic-only verdict against the hybrid (heuristic + LLM tie-break) one."""
    banner("Q2 HARDENING — gate on ambiguous / mixed inputs (hybrid vs heuristic-only)")
    corpus = [
        ("After validation the system either commits or rolls back.", "finite_structural"),
        ("The retry counter increments each cycle until it reaches the limit, then the job fails.", "finite_structural"),
        ("Orders move from Review to Packing, and packing time grows as volume increases.", "mixed"),
        ("If the customer trusts the brand, they proceed to Checkout; otherwise they leave.", "mixed"),
        ("The model's confidence rises with each correct prediction.", "model_only"),
        ("A request goes to Pending, then to Approved or Denied.", "finite_structural"),
        ("Sentiment improves gradually as more reviews accumulate.", "model_only"),
        ("A ticket escalates from Tier1 to Tier2 to Tier3 if unresolved.", "finite_structural"),
    ]
    h_ok = hyb_ok = 0
    for text, truth in corpus:
        fin, cont = gate_heuristic(text)
        h_pred = "finite_structural" if fin > cont else ("model_only" if cont > fin else "mixed")
        hyb = regime_gate(text, use_llm=True)["verdict"]
        h_ok += (h_pred == truth); hyb_ok += (hyb == truth)
        print(f"  truth={truth:<17} heuristic={h_pred:<17} hybrid={hyb:<17} | {text[:42]}")
    print(f"\n  heuristic-only accuracy: {h_ok}/{len(corpus)}   hybrid(LLM) accuracy: {hyb_ok}/{len(corpus)}")


def main():
    demo_M1()
    demo_M2()
    demo_M3()
    test_gate_hard()
    print("\n(all stages self-contained; nothing imported from any external solver)")


if __name__ == "__main__":
    main()

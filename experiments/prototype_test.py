"""prototype_test.py — test the THREE open questions for the practical
LLM-feedback application, with a real local instruct model (Ollama / phi3:mini).

  Q1  Can a (small, open) instruct-LLM reliably extract a finite transition
      system from English, with schema validation + deterministic fallback?
  Q2  Does the regime gate separate finite-structural from continuous/belief
      content with good precision (refusing the right things)?
  Q3  Are grounded-trace reports measurably more auditable (fewer unsupported
      claims) than a plain free-form LLM explanation?

Honest scope: phi3:mini is a 3.8B model — results are a FLOOR ("even a small
open model ..."); the corpus is small (indicative, not statistically powerful);
the Q3 grounding-verifier is a crude entity-support proxy. All LLM calls are
local (Ollama), free, reproducible-ish (greedy decode).

Requires: Ollama running with phi3:mini.  Run:  python prototype_test.py
"""
import sys, json, re, time

from llm_feedback_control import gen

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


# --- corpus ---------------------------------------------------------------
FINITE = [
    dict(text="A customer order enters Review. If approved it goes to Packing. "
              "If rejected it goes to Refund. Packing goes to Shipped. Shipped "
              "goes to Closed. Refund goes to Closed.",
         states=["Review", "Packing", "Refund", "Shipped", "Closed"],
         trans=[("Review", "Packing"), ("Review", "Refund"), ("Packing", "Shipped"),
                ("Shipped", "Closed"), ("Refund", "Closed")]),
    dict(text="A job starts in Queued. Queued goes to Running. Running goes to "
              "Done or to Failed. Failed goes to Queued.",
         states=["Queued", "Running", "Done", "Failed"],
         trans=[("Queued", "Running"), ("Running", "Done"), ("Running", "Failed"),
                ("Failed", "Queued")]),
    dict(text="A ticket opens in New. New goes to Assigned. Assigned goes to "
              "Resolved. Resolved goes to Closed.",
         states=["New", "Assigned", "Resolved", "Closed"],
         trans=[("New", "Assigned"), ("Assigned", "Resolved"), ("Resolved", "Closed")]),
    dict(text="A request enters Draft. Draft goes to Submitted. Submitted goes "
              "to Approved or to Rejected. Approved goes to Archived. Rejected "
              "goes to Archived.",
         states=["Draft", "Submitted", "Approved", "Rejected", "Archived"],
         trans=[("Draft", "Submitted"), ("Submitted", "Approved"),
                ("Submitted", "Rejected"), ("Approved", "Archived"),
                ("Rejected", "Archived")]),
    dict(text="A call enters Greeting. Greeting goes to Menu. Menu goes to Agent "
              "or to Voicemail. Agent goes to Hangup. Voicemail goes to Hangup.",
         states=["Greeting", "Menu", "Agent", "Voicemail", "Hangup"],
         trans=[("Greeting", "Menu"), ("Menu", "Agent"), ("Menu", "Voicemail"),
                ("Agent", "Hangup"), ("Voicemail", "Hangup")]),
]
NON_FINITE = [
    "The market price drifts until confidence improves, then buyers slowly return.",
    "Temperature rises continuously until the pressure stabilises.",
    "Customers usually become happier over time as the brand feels more trustworthy.",
    "Demand grows at roughly three percent per month.",
    "Sentiment gradually shifts as trust accumulates in the community.",
]


# --- Q2: regime gate (heuristic, no LLM) ----------------------------------
CONT_BELIEF = ["continuous", "continuously", "drift", "rises", "grows", "rate",
               "percent", "gradually", "slowly", "temperature", "price", "demand",
               "confidence", "trust", "trustworthy", "feels", "happier", "sentiment",
               "usually", "over time", "accumulat", "improves", "stabilis"]
FINITE_CUES = ["goes to", "enters", "starts in", "opens in", "if approved",
               "if rejected", "retry", "then fail", " or to ", "state", "step"]


def regime_gate(text):
    """Heuristic router: classify text as 'finite_structural' or 'model_only' by cue-word counts."""
    t = text.lower()
    cont = sum(t.count(c) for c in CONT_BELIEF)
    fin = sum(t.count(c) for c in FINITE_CUES)
    return "finite_structural" if fin > cont else "model_only"


def test_gate():
    """Q2: score the regime gate over finite + non-finite items; return (accuracy, precision, recall)."""
    print("=" * 74); print("Q2 — REGIME GATE (heuristic; finite-structural vs model-only)"); print("=" * 74)
    items = [(d["text"], "finite_structural") for d in FINITE] + \
            [(t, "model_only") for t in NON_FINITE]
    tp = fp = tn = fn = 0
    for text, truth in items:
        pred = regime_gate(text)
        ok = pred == truth
        if truth == "finite_structural":
            tp += ok; fn += (not ok)
        else:
            tn += ok; fp += (not ok)
        print(f"  [{'OK' if ok else 'XX'}] truth={truth:<17} pred={pred:<17} | {text[:46]}")
    acc = (tp + tn) / len(items)
    prec = tp / (tp + fp) if (tp + fp) else 0
    rec = tp / (tp + fn) if (tp + fn) else 0
    print(f"\n  accuracy={acc:.2f}  finite-precision={prec:.2f}  finite-recall={rec:.2f}  "
          f"(model-only correctly refused: {tn}/{tn+fp})")
    return acc, prec, rec


# --- Q1: LLM extraction + schema validation + deterministic fallback ------
EXTRACT_PROMPT = ('Extract the finite state machine from the process description. '
                  'Return ONLY JSON: {{"states": [...], "transitions": [["FROM","TO"], ...]}}. '
                  'Use the exact state names from the text. Description: "{text}"')


def valid_schema(obj):
    """True if obj is the expected {states:[...], transitions:[[from,to],...]} extraction shape."""
    return (isinstance(obj, dict) and isinstance(obj.get("states"), list)
            and isinstance(obj.get("transitions"), list)
            and all(isinstance(tr, list) and len(tr) == 2 for tr in obj["transitions"]))


def fallback_extract(text):
    """Deterministic regex fallback: 'X goes to Y', 'X goes to Y or to Z', 'enters X'."""
    states, trans = set(), set()
    for m in re.finditer(r"([A-Z][A-Za-z]+)\s+goes to\s+([A-Z][A-Za-z]+)(?:\s+or to\s+([A-Z][A-Za-z]+))?", text):
        a, b, c = m.group(1), m.group(2), m.group(3)
        states |= {a, b}; trans.add((a, b))
        if c:
            states.add(c); trans.add((a, c))
    for m in re.finditer(r"(?:enters|starts in|opens in)\s+([A-Z][A-Za-z]+)", text):
        states.add(m.group(1))
    return {"states": sorted(states), "transitions": [list(t) for t in sorted(trans)]}


def score(extracted, truth):
    """Return (state-precision, state-recall, transition-precision, transition-recall) vs truth."""
    es, ts = {norm(s) for s in extracted["states"]}, {norm(s) for s in truth["states"]}
    et = {(norm(a), norm(b)) for a, b in extracted["transitions"]}
    tt = {(norm(a), norm(b)) for a, b in truth["trans"]}
    def pr(E, T):
        if not E and not T: return 1.0, 1.0
        p = len(E & T) / len(E) if E else 0.0
        r = len(E & T) / len(T) if T else 0.0
        return p, r
    sp, sr = pr(es, ts); tp, tr = pr(et, tt)
    return sp, sr, tp, tr


def test_extraction():
    """Q1: extract each finite item with the LLM (fallback on bad schema/error); return mean transition P/R."""
    print("\n" + "=" * 74); print("Q1 — LLM EXTRACTION (phi3:mini) + schema validation + fallback"); print("=" * 74)
    rows = []
    for d in FINITE:
        t0 = time.perf_counter()
        used = "LLM"
        try:
            raw = gen(EXTRACT_PROMPT.format(text=d["text"]), fmt="json")
            obj = json.loads(raw)
            if not valid_schema(obj):
                obj = fallback_extract(d["text"]); used = "fallback(bad-schema)"
        except Exception:
            obj = fallback_extract(d["text"]); used = "fallback(error)"
        sp, sr, tp, tr = score(obj, d)
        dt = time.perf_counter() - t0
        rows.append((sp, sr, tp, tr))
        print(f"  states P/R={sp:.2f}/{sr:.2f}  transitions P/R={tp:.2f}/{tr:.2f}  "
              f"[{used}, {dt:.0f}s]  ({d['text'][:30]}...)")
    import statistics as st
    avg = lambda i: st.mean(r[i] for r in rows)
    print(f"\n  MEAN  states P/R = {avg(0):.2f}/{avg(1):.2f}   "
          f"transitions P/R = {avg(2):.2f}/{avg(3):.2f}   (n={len(rows)})")
    return avg(2), avg(3)


# --- Q3: grounded vs plain report (auditability = unsupported entities) ---
def build_trace(d):
    """Build a verified-facts dict (states, transitions, terminals, unreachable) to ground a report."""
    states = d["states"]; trans = d["trans"]
    out = {s: [b for a, b in trans if a == s] for s in states}
    terminals = [s for s in states if not out[s]]
    # reachability from the first state
    start = states[0]; seen = {start}; stack = [start]
    while stack:
        u = stack.pop()
        for v in out.get(u, []):
            if v not in seen: seen.add(v); stack.append(v)
    unreachable = [s for s in states if s not in seen]
    return dict(states=states, transitions=[list(t) for t in trans],
                terminal_states=terminals, unreachable_states=unreachable)


def unsupported_entities(report, truth_states):
    """Crude auditability proxy: capitalized state-like tokens named in the report
    that are NOT real states = unsupported claims."""
    truth = {norm(s) for s in truth_states}
    common = {"the", "this", "it", "if", "then", "a", "an", "review", "review."}  # noise guard
    toks = set(re.findall(r"\b[A-Z][A-Za-z]{3,}\b", report))
    cand = {t for t in toks if norm(t) not in {"process", "state", "states", "workflow",
            "system", "step", "steps", "stage", "the", "this", "there", "from", "each",
            "after", "once", "when", "node", "nodes", "transition", "transitions",
            "start", "end", "final", "terminal", "reachable"}}
    unsup = [t for t in cand if norm(t) not in truth]
    return unsup, sorted(cand)


def test_reports(k=3):
    """Q3: compare plain vs fact-grounded reports; return (plain, grounded) unsupported-entity counts."""
    print("\n" + "=" * 74); print("Q3 — GROUNDED vs PLAIN report (auditability: unsupported entities)"); print("=" * 74)
    plain_bad = grounded_bad = plain_tot = grounded_tot = 0
    for d in FINITE[:k]:
        trace = build_trace(d)
        plain = gen(f"In two sentences, describe the states and flow of this process: \"{d['text']}\"")
        grounded = gen("Write two sentences describing the process using ONLY these "
                       "verified facts. Name ONLY states that appear in the facts; invent "
                       f"nothing. FACTS (JSON): {json.dumps(trace)}")
        pu, pc = unsupported_entities(plain, d["states"])
        gu, gc = unsupported_entities(grounded, d["states"])
        plain_bad += len(pu); grounded_bad += len(gu)
        plain_tot += len(pc); grounded_tot += len(gc)
        print(f"  {d['states'][0]}...: PLAIN unsupported={pu or '∅'} | GROUNDED unsupported={gu or '∅'}")
    print(f"\n  PLAIN    unsupported entity mentions: {plain_bad} (of {plain_tot} named)")
    print(f"  GROUNDED unsupported entity mentions: {grounded_bad} (of {grounded_tot} named)")
    return plain_bad, grounded_bad


def main():
    """Run the three prototype questions (gate, extraction, reports) and print a combined summary."""
    g = test_gate()
    e = test_extraction()
    r = test_reports()
    print("\n" + "=" * 74); print("SUMMARY (phi3:mini, small corpus — indicative)"); print("=" * 74)
    print(f"  Q2 gate     : accuracy {g[0]:.2f}, finite-precision {g[1]:.2f}, recall {g[2]:.2f}")
    print(f"  Q1 extract  : transition precision/recall {e[0]:.2f}/{e[1]:.2f}")
    print(f"  Q3 reports  : unsupported claims  plain={r[0]}  grounded={r[1]}  "
          f"({'grounding helped' if r[1] < r[0] else 'no improvement'})")


if __name__ == "__main__":
    main()

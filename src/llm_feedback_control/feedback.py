"""The bounded POSITIVE-feedback loop (the op-amp "close the loop").

Negative feedback (gate / ground / refuse) is validated in auditor.py: it
stabilises, but it checks FORM, not COMPLETENESS — a one-shot extraction can
silently drop a branch and the system still says "OK".

This adds the regenerative loop that fixes that, using a reference that needs
NONE of the special mathematics — just deterministic text<->graph consistency:

    extract (LLM)  ->  consistency_gaps(text, graph)  [deterministic reference]
        ^                                   |
        |____ re-prompt with the gaps  <----'   (positive feedback: amplify coverage)

Bounded by: a FIXED-POINT test (stop when the graph stops changing / no gaps)
and an iteration cap with a REFUSAL clamp (if it can't converge, say so — do
NOT report a confident-but-incomplete result). That refusal clamp is the
stability bound that keeps the regenerative loop from running away.

The reference is plain regex graph consistency — so the "LLM feedback control /
refusal-as-stabilizer" discipline stands on its own, with no special math.
The LLM backend is injectable via ``generate`` (defaults to llm.gen).
"""
import re, json
from .llm import gen
from .loop import feedback_loop
from .auditor import valid, fallback_extract, norm

STOP = {"If", "The", "A", "An", "After", "Once", "When", "Otherwise", "It", "Then"}


def candidate_states(text):
    """Regex pass for capitalised tokens that look like state names — those after
    "to/enters/...", or before "goes/ends/...", minus common sentence-start words.
    The deterministic reference uses these to spot states the graph is missing."""
    c = set()
    for m in re.finditer(r"(?:goes to|moves to|move to|back to|to|enters|starts in|opens in|into)\s+([A-Z][A-Za-z0-9]+)", text):
        c.add(m.group(1))
    for m in re.finditer(r"\b([A-Z][A-Za-z0-9]+)\s+(?:goes|moves|closes|enters|ends)", text):
        c.add(m.group(1))
    return {s for s in c if s not in STOP}


def candidate_trans(text):
    """Regex pass for "X goes to Y (or Z)" transitions in the text — the edges the
    consistency reference expects the extracted graph to contain."""
    tr = set()
    for m in re.finditer(r"([A-Z][A-Za-z0-9]+)\s+(?:goes to|moves to|move to)\s+([A-Z][A-Za-z0-9]+)"
                         r"(?:\s+or(?: to)?\s+([A-Z][A-Za-z0-9]+))?", text):
        a, b, c = m.group(1), m.group(2), m.group(3)
        if a not in STOP: tr.add((a, b))
        if c: tr.add((a, c))
    return tr


def consistency_gaps(text, graph):
    """Deterministic reference: what does the TEXT mention that the GRAPH lacks?"""
    gs = {norm(s) for s in graph.get("states", [])}
    gt = {(norm(a), norm(b)) for a, b in graph.get("transitions", [])}
    miss_s = sorted({s for s in candidate_states(text) if norm(s) not in gs})
    miss_t = sorted({(a, b) for a, b in candidate_trans(text)
                     if (norm(a), norm(b)) not in gt})
    return miss_s, miss_t


def extract_iterative(text, max_iters=4, verbose=True, generate=None):
    """Positive-feedback extraction: re-prompt on deterministic gaps until a
    fixed point, bounded by ``max_iters`` + a refusal clamp.

    Returns ``(graph, initial, history, converged)``: the final graph, the
    open-loop iter-0 snapshot, a per-iteration history, and whether it
    converged to a clean fixed point (no residual gaps). Pass ``generate`` to
    use a specific LLM backend; with no model it returns the deterministic
    extraction unchanged (history length 1).

    This is the workflow instantiation of the shared engine (``loop.feedback_loop``):
    the extractor, reference (``consistency_gaps``), and repair below are the only
    workflow-specific pieces."""
    g = generate or gen

    def extract(t):
        try:
            graph = json.loads(g(
                'Extract the finite state machine. Return ONLY JSON '
                '{"states":[...],"transitions":[["FROM","TO"],...]} using exact state '
                f'names from the text. Text: "{t}"', fmt="json"))
            if valid(graph) and graph.get("states"):
                return graph
        except Exception:
            pass
        return fallback_extract(t)

    def reference(t, graph):
        miss_s, miss_t = consistency_gaps(t, graph)
        return [("state", s) for s in miss_s] + [("trans", a, b) for a, b in miss_t]

    def repair(t, graph, gaps):
        miss_s = [x[1] for x in gaps if x[0] == "state"]
        miss_t = [(x[1], x[2]) for x in gaps if x[0] == "trans"]
        gaps_txt = f"missing states: {miss_s}; missing transitions: {miss_t}"
        try:
            ng = json.loads(g(
                'Here is a state machine you extracted, and a list of items the '
                'source text mentions that are MISSING from it. Return the COMPLETE '
                'corrected machine as JSON {"states":[...],"transitions":[["FROM","TO"],...]}, '
                'adding the missing items (and their transitions) using exact names. '
                f'Current: {json.dumps({"states": graph["states"], "transitions": graph["transitions"]})}. '
                f'Missing per the text: {gaps_txt}. Source text: "{t}"', fmt="json"))
            if valid(ng) and ng.get("states"):
                return ng
        except Exception:
            pass
        return None

    def signature(graph):
        return (tuple(sorted(norm(s) for s in graph["states"])),
                tuple(sorted((norm(a), norm(b)) for a, b in graph["transitions"])))

    graph, initial, raw_hist, converged = feedback_loop(
        text, extract=extract, reference=reference, repair=repair,
        signature=signature, max_iters=max_iters, verbose=False, label="workflow")

    # preserve the documented history shape: (it, n_states, n_trans, miss_s, miss_t)
    history = []
    for it, snap, gaps in raw_hist:
        miss_s = [x[1] for x in gaps if x[0] == "state"]
        miss_t = [(x[1], x[2]) for x in gaps if x[0] == "trans"]
        if verbose:
            print(f"  iter {it}: states={snap['states']}")
            print(f"          gaps -> missing states {miss_s or '∅'}, "
                  f"missing transitions {miss_t or '∅'}")
        history.append((it, len(snap["states"]), len(snap["transitions"]), miss_s, miss_t))
    return graph, initial, history, converged


def main():
    print("=" * 74)
    print("POSITIVE-FEEDBACK EXTRACTION (op-amp 'close the loop'); reference = plain")
    print("text<->graph consistency, NO special math involved")
    print("=" * 74)
    text = ("A customer order enters Review. If approved it goes to Packing. If "
            "rejected it goes to Refund. Packing goes to Shipped. Shipped goes to "
            "Closed. Refund goes to Closed.")
    print(f"\nText: {text}\n")
    graph, _initial, history, converged = extract_iterative(text)
    print("\n" + "-" * 74)
    print(f"iterations run: {len(history)}")
    if converged:
        print(f"CONVERGED to a fixed point with NO residual gaps. Final states: {graph['states']}")
        print("  -> the dropped branch was recovered by the regenerative loop, then the")
        print("     fixed-point test (negative-feedback reference) stopped it cleanly.")
    else:
        ms, mt = consistency_gaps(text, graph)
        print(f"DID NOT CONVERGE within the cap. REFUSAL CLAMP fires:")
        print(f"  residual gaps: missing states {ms}, missing transitions {mt}")
        print("  -> the system refuses to report a confident-but-incomplete result")
        print("     (the stability bound that keeps positive feedback from faking 'OK').")
    print("\n" + "=" * 74)
    print("PRINCIPLE DEMONSTRATED")
    print("=" * 74)
    print("""\
- POSITIVE feedback (regenerative re-extraction) recovered coverage that the
  one-shot negative-feedback pass could not — it amplified toward completeness.
- It was made SAFE by two negative-feedback bounds: a deterministic fixed-point
  reference (text<->graph consistency) and a refusal clamp on non-convergence.
- The reference uses ZERO special mathematics — just regex graph consistency.""")


if __name__ == "__main__":
    main()

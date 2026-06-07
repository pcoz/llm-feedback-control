"""Op-amp "circuits": higher-level compositions of the feedback primitives.

The package's core is one feedback loop (``loop.feedback_loop``) with an
injectable *controller* (the ``reference``). The combinators in ``critic.py``
compose controllers (``combine_references`` = a summing junction;
``quorum_reference`` = an instrumentation amp). This module composes whole
*stages* and *gates* — the next layer up — by leaning on the same op-amp analogy
the rest of the package uses:

  * :func:`cascade` — a multi-stage amplifier. Pipe one controlled loop's output
    into the next stage's input, each stage exact-checked, so error cannot
    compound silently down the chain. A stage that refuses stops the cascade
    (the honest stop propagates).
  * :func:`schmitt_gate` — a comparator with hysteresis (a Schmitt trigger). A
    plain threshold "chatters" — flips accept/refuse on every wobble of a
    borderline score. Two thresholds with a dead-band between them make the
    decision *sticky*, so routing does not oscillate on noisy inputs.

Everything here is pure standard library, has no third-party dependency, and is
purely additive: it composes the existing public API and changes none of it.
"""
from .loop import feedback_loop


# ---------------------------------------------------------------------------
# Cascade — the multi-stage amplifier
# ---------------------------------------------------------------------------
#
# A "stage" is any callable ``stage(input) -> (output, converged)``:
#   * ``output``    — what to feed the next stage (any type the next stage reads)
#   * ``converged`` — True if the stage trusts its output; False == it refused
# ``loop_stage`` below is the convenience adapter that turns a feedback_loop
# into exactly such a callable, but a plain function works just as well.

def loop_stage(*, extract, reference, repair, signature, finalize=None,
               max_iters=4, label="stage"):
    """Wrap a :func:`~llm_feedback_control.feedback_loop` as a cascade stage.

    Returns a callable ``stage(input) -> (output, converged)`` that runs the
    loop with ``input`` as the loop's source value. The four loop callables have
    their usual meaning (see ``feedback_loop``); ``input`` may be text *or* the
    structured output of an earlier stage — ``extract`` decides how to read it."""
    def stage(inp):
        # The loop returns (candidate, initial, history, converged); a stage only
        # needs to forward the candidate and whether it can be trusted.
        cand, _initial, _history, converged = feedback_loop(
            inp, extract=extract, reference=reference, repair=repair,
            signature=signature, finalize=finalize, max_iters=max_iters,
            label=label)
        return cand, converged
    return stage


def cascade(*stages, stop_on_refusal=True):
    """Compose stages into a multi-stage amplifier (each feeds the next).

    Returns ``run(x) -> (final, ok, trace)``:
      * ``final`` — the last stage's output (or the last trusted one, if the
        cascade stopped early);
      * ``ok``    — True iff every stage that ran converged;
      * ``trace`` — one ``{"stage", "output", "converged"}`` record per stage run.

    With ``stop_on_refusal=True`` (default) a stage that refuses halts the chain:
    you do not feed an untrusted result into the next stage. Set it False to run
    every stage regardless and inspect the trace yourself."""
    def run(x):
        trace = []
        cur = x                      # the value threaded through the stages
        ok = True
        for i, stage in enumerate(stages):
            out, converged = stage(cur)
            trace.append({"stage": i, "output": out, "converged": converged})
            ok = ok and converged
            cur = out                # this stage's output is the next one's input
            if not converged and stop_on_refusal:
                break                # honest stop: don't build on an untrusted stage
        return cur, ok, trace
    return run


# ---------------------------------------------------------------------------
# Schmitt trigger — the comparator with hysteresis
# ---------------------------------------------------------------------------

def schmitt_gate(low, high, *, start=False):
    """A comparator with hysteresis (Schmitt trigger): a *sticky* boolean over a
    stream of scores.

    A single-threshold gate chatters: a score hovering at the threshold flips the
    verdict back and forth on every tiny wobble. Two thresholds fix that:

      * the verdict flips to True only when the score rises **at or above**
        ``high``;
      * it flips back to False only when the score falls **at or below** ``low``;
      * **between** ``low`` and ``high`` (the dead-band) it HOLDS its last value.

    Returns a stateful ``classify(score=None, force=None) -> bool``. ``start`` is
    the initial verdict (used until a score first leaves the dead-band). Use it to
    keep a routing decision stable when a confidence score is noisy near the boundary.

    The gate can also be **set** directly, like the set/reset input of a latch:

      * ``classify(force=True)`` forces the verdict on (and it sticks, exactly as a
        crossing would, until a later score or force changes it);
      * ``classify(force=False)`` forces it off;
      * ``classify()`` with no argument reads the current verdict without changing it.

    Use the override for a human decision, a hard rule, or an emergency latch (force
    the gate into "halt"/"supervised" and let the deadband hold it there). A forced
    verdict still obeys the same hysteresis afterwards — only a decisive crossing of
    the *other* threshold will move it back.

    Raises ``ValueError`` if ``low > high``."""
    if low > high:
        raise ValueError(f"low ({low}) must be <= high ({high})")
    # Closed-over state: the current verdict. The dead-band leaves it untouched,
    # which is exactly the hysteresis (the gate "remembers" where it was).
    state = {"on": bool(start)}

    def classify(score=None, force=None):
        if force is not None:
            state["on"] = bool(force)          # set / reset override (a latch input)
        elif score is not None:
            if score >= high:
                state["on"] = True
            elif score <= low:
                state["on"] = False
            # else: in the dead-band -> hold the previous verdict (no chatter)
        # score is None and force is None -> read the current verdict, unchanged
        return state["on"]

    return classify


# ---------------------------------------------------------------------------
# Offline demonstrations (scripted; no model, no network)
# ---------------------------------------------------------------------------

def _demo_cascade():
    print("=" * 74)
    print("CASCADE (multi-stage amplifier): each stage exact-checked, piped on")
    print("=" * 74)
    # Stage 1: push a counter up to >= 2.  Stage 2: read stage 1's output and
    # push a second counter up to >= 5.  Both are exact-checked loops.
    s1 = loop_stage(extract=lambda t: {"v": 0},
                    reference=lambda t, c: [] if c["v"] >= 2 else ["v too low"],
                    repair=lambda t, c, g: {"v": c["v"] + 1},
                    signature=lambda c: c["v"], label="s1")
    s2 = loop_stage(extract=lambda c: {"w": c["v"]},
                    reference=lambda c, o: [] if o["w"] >= 5 else ["w too low"],
                    repair=lambda c, o, g: {"w": o["w"] + 1},
                    signature=lambda o: o["w"], label="s2")
    final, ok, trace = cascade(s1, s2)("start")
    for r in trace:
        print(f"  stage {r['stage']}: output={r['output']} converged={r['converged']}")
    print(f"final={final}  ok={ok}")


def _demo_schmitt():
    print("=" * 74)
    print("SCHMITT TRIGGER (comparator with hysteresis): no accept/refuse chatter")
    print("=" * 74)
    gate = schmitt_gate(0.4, 0.6, start=False)
    scores = [0.50, 0.55, 0.70, 0.50, 0.45, 0.30, 0.50, 0.65]
    for s in scores:
        print(f"  score {s:.2f} -> {'ACCEPT' if gate(s) else 'refuse'}")
    print("  (note: 0.50 maps to refuse, then later to ACCEPT — same score, "
          "different verdict,\n   because the gate holds its state through the "
          "0.4-0.6 dead-band.)")


if __name__ == "__main__":
    _demo_cascade()
    print()
    _demo_schmitt()

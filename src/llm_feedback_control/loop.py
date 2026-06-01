"""The general feedback loop — the engine both targets share.

`run_audit` (workflows) and `extract_form` (form fields) are two instantiations
of this one loop. A target supplies four callables; the loop owns the bounded
positive feedback, the fixed-point test, and the refusal clamp:

    extract(text)            -> candidate
    reference(text, cand)    -> list of gaps   (empty list == converged)
    repair(text, cand, gaps) -> candidate, or None to stop
    signature(cand)          -> hashable        (for stall detection)
    finalize(text, cand)     -> candidate       (optional deterministic last resort)

The LLM backend is injected by the caller (captured inside `extract`/`repair`),
so the loop itself is model-agnostic. This is the seam that makes the engine
general: a new target is "bring these callables", not a fork.
"""
import copy


def feedback_loop(text, *, extract, reference, repair, signature,
                  finalize=None, max_iters=4, verbose=False, label="item"):
    """Run bounded positive-feedback extraction to a fixed point.

    Returns ``(candidate, initial, history, converged)``:
      - candidate : the final extracted object
      - initial   : the open-loop (iteration-0) snapshot, for before/after
      - history   : list of ``(iter, candidate_snapshot, gaps)``
      - converged : True iff there are no residual gaps; False means the refusal
                    clamp fired (incomplete — do not trust as final)
    """
    cand = extract(text)
    initial = copy.deepcopy(cand)
    history = []
    for it in range(max_iters):
        gaps = reference(text, cand)
        history.append((it, copy.deepcopy(cand), gaps))
        if verbose:
            print(f"  iter {it} [{label}]: {len(gaps)} gap(s)")
        if not gaps:
            return cand, initial, history, True            # fixed point
        new = repair(text, cand, gaps)
        if new is None:
            break                                          # cannot improve
        stalled = signature(new) == signature(cand)
        cand = new
        if stalled:
            break                                          # no change -> stop
    if finalize is not None:
        cand = finalize(text, cand)                        # deterministic last resort
    gaps = reference(text, cand)
    return cand, initial, history, (not gaps)

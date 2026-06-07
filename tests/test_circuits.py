"""Op-amp circuits — deterministic tests (no model / no network)."""
from llm_feedback_control import cascade, loop_stage, schmitt_gate


# --- cascade ------------------------------------------------------------------
def test_cascade_threads_and_converges():
    # stage 1 drives v -> >=2; stage 2 reads that and drives w -> >=5
    s1 = loop_stage(extract=lambda t: {"v": 0},
                    reference=lambda t, c: [] if c["v"] >= 2 else ["low"],
                    repair=lambda t, c, g: {"v": c["v"] + 1},
                    signature=lambda c: c["v"])
    s2 = loop_stage(extract=lambda c: {"w": c["v"]},
                    reference=lambda c, o: [] if o["w"] >= 5 else ["low"],
                    repair=lambda c, o, g: {"w": o["w"] + 1},
                    signature=lambda o: o["w"])
    final, ok, trace = cascade(s1, s2)("start")
    assert ok is True
    assert final == {"w": 5}
    assert len(trace) == 2 and trace[0]["output"] == {"v": 2}


def test_cascade_stops_on_refusal():
    bad = loop_stage(extract=lambda t: {"v": 0},
                     reference=lambda t, c: ["never"],          # never satisfied
                     repair=lambda t, c, g: {"v": c["v"] + 1},
                     signature=lambda c: c["v"], max_iters=2)
    after = loop_stage(extract=lambda c: {"ran": True},
                       reference=lambda c, o: [], repair=lambda *a: None,
                       signature=lambda o: 0)
    final, ok, trace = cascade(bad, after)("x")
    assert ok is False
    assert len(trace) == 1                  # second stage never ran
    assert trace[0]["converged"] is False


def test_cascade_runs_all_when_not_stopping():
    bad = loop_stage(extract=lambda t: {"v": 0}, reference=lambda t, c: ["x"],
                     repair=lambda t, c, g: {"v": c["v"] + 1},
                     signature=lambda c: c["v"], max_iters=1)
    after = loop_stage(extract=lambda c: {"ran": True}, reference=lambda c, o: [],
                       repair=lambda *a: None, signature=lambda o: 0)
    _final, ok, trace = cascade(bad, after, stop_on_refusal=False)("x")
    assert ok is False                      # a stage refused...
    assert len(trace) == 2                  # ...but both stages still ran


# --- Schmitt trigger ----------------------------------------------------------
def test_schmitt_hysteresis_holds_in_deadband():
    g = schmitt_gate(0.4, 0.6, start=False)
    assert g(0.50) is False     # dead-band -> holds initial False
    assert g(0.70) is True      # >= high  -> on
    assert g(0.50) is True      # dead-band -> holds True (no chatter)
    assert g(0.30) is False     # <= low   -> off
    assert g(0.45) is False     # dead-band -> holds False


def test_schmitt_start_state():
    g = schmitt_gate(0.4, 0.6, start=True)
    assert g(0.5) is True       # dead-band -> holds initial True


def test_schmitt_rejects_bad_thresholds():
    try:
        schmitt_gate(0.7, 0.3)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_schmitt_force_sets_and_reads():
    g = schmitt_gate(0.4, 0.6, start=False)
    assert g() is False                  # read, unchanged
    assert g(force=True) is True         # set on
    assert g(0.5) is True                # dead-band holds the forced state
    assert g() is True                   # read, still on
    assert g(0.3) is False               # decisive crossing overrides the forced state
    assert g(force=False) is False       # reset off
    assert g(0.55) is False              # dead-band holds the reset state
    assert g(0.7) is True                # crossing high still works after a force

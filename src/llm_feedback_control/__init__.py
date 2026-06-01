"""llm-feedback-control — get reliable, checkable structured output from a small
local language model by wrapping it in ordinary deterministic code.

WHAT IT DOES, concretely
------------------------
You hand it a process described in plain English::

    "A claim enters Intake. From Intake it goes to Triage. Triage goes to
     FastTrack or to Investigation. ..."

and it:
  1. turns that into a state machine (states + transitions);
  2. computes *provable* facts about it — which steps are dead ends, whether
     there are loops, which steps can't be reached;
  3. writes a report in which every statement is backed by one of those
     checked facts (so it can't quietly make things up);
  4. knows its own limits: if the text isn't actually a finite step-by-step
     process (e.g. "prices drift up as confidence grows"), it REFUSES instead
     of inventing a fake state machine; and if the model's first pass missed
     part of the process, it loops to fill the gaps — or refuses if it can't.

WHY "FEEDBACK CONTROL" (the analogy, explained)
-----------------------------------------------
The design is borrowed from electronics. A raw LLM is like a very high-gain
amplifier: hugely powerful, but left to run "open-loop" it overshoots — fluent,
yet it drifts and hallucinates. Engineers tame such an amplifier by adding a
*feedback loop*: feed the output back, compare it to a stable reference, and
trade some raw power for precision and stability. This library is that feedback
loop for an LLM. The "reference" is plain, deterministic code — graph checks
and schema rules the model's output is measured against.

Two kinds of feedback, in plain terms:

  - NEGATIVE feedback = the stabilising checks (``run_audit``):
      * decide first whether the text is even the kind of thing we can analyse
        exactly, and refuse the fuzzy ones;
      * force the model's answer into a strict shape (with a no-model fallback);
      * compute the provable graph facts;
      * say "I can't do this exactly" rather than guess.
  - POSITIVE feedback = the gap-filling loop (``extract_iterative``):
        re-ask the model about anything the text mentions that's missing from
        its answer, repeating until nothing is missing (a "fixed point") — and
        refuse if it never settles.

Two built-in targets share one engine (``feedback_loop``): ``run_audit`` (workflows
/ state machines) and ``extract_form`` (form fields against a schema). The loop's
extractor and reference are injectable, so you can point it at new targets too.

Zero third-party runtime dependencies. The deterministic core runs with no model
at all; an LLM is a pure upgrade and is fully injectable (pass ``generate=``).

Quickstart (works with no model)::

    from llm_feedback_control import run_audit
    r = run_audit("A claim enters Intake. From Intake it goes to Triage. "
                  "Triage goes to FastTrack or to Investigation.")
    print(r["result"]); print(r["report_facts"])
"""
from .llm import gen, gen_ceiling, info, doctor, BackendError
from .auditor import (
    run_audit,
    regime_gate,
    gate_heuristic,
    extract_workflow,
    exact_analysis,
    graph_facts,
    transfer_operator,
    fp_orbit,
    grounded_report,
    valid,
    fallback_extract,
    norm,
)
from .feedback import (
    extract_iterative,
    consistency_gaps,
    candidate_states,
    candidate_trans,
)
from .loop import feedback_loop
from .forms import (
    extract_form,
    fallback_extract_form,
    field_gaps as form_field_gaps,
)

__version__ = "0.2.3"

__all__ = [
    # headline
    "run_audit",
    "extract_form",
    "extract_iterative",
    "feedback_loop",
    # negative-feedback pipeline parts
    "regime_gate",
    "gate_heuristic",
    "extract_workflow",
    "exact_analysis",
    "graph_facts",
    "transfer_operator",
    "fp_orbit",
    "grounded_report",
    "valid",
    "fallback_extract",
    "norm",
    # positive-feedback parts
    "consistency_gaps",
    "candidate_states",
    "candidate_trans",
    # form target
    "fallback_extract_form",
    "form_field_gaps",
    # client
    "gen",
    "gen_ceiling",
    "info",
    "doctor",
    "BackendError",
    "__version__",
]

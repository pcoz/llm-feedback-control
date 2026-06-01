# llm-feedback-control documentation

**Get reliable, checkable structured output from a small, local language model —
by wrapping it in ordinary deterministic code.**

If you've never seen this project before, read this page top to bottom; it links
out to everything else.

## The one-paragraph version

A large language model is fluent but unreliable: ask it to turn a process
description into a state machine and it will usually get *most* of it right and
quietly invent or drop the rest. This library wraps the model in a **deterministic
feedback loop** — plain code that checks the model's output against provable facts,
fills the gaps by re-asking, and **refuses** when it can't be sure. The result is
structured output you can audit, from a model small enough to run on a laptop.

It's one engine pointed at different targets: a target is anything you can pair with
a schema and a deterministic reference. **Two ship today** — workflow / state-machine
extraction (`run_audit`) and form-field extraction (`extract_form`) — on one public,
injectable loop; records and entities are others the same engine handles. See
[architecture.md §7](architecture.md#7-the-general-engine).

## A 60-second tour

```bash
pip install llm-feedback-control     # zero dependencies
```

```python
from llm_feedback_control import run_audit

r = run_audit("A claim enters Intake. From Intake it goes to Triage. "
              "Triage goes to FastTrack or to Investigation.")
print(r["result"])          # OK   (or REFUSED: ... with a reason)
print(r["report_facts"])    # checked facts: terminals, loops, unreachable steps
```

This runs **with no model at all** — the deterministic regex extractor and exact
graph analysis do the work. Add a model (see [usage](usage.md)) and only the
extraction step gets better.

## Where to go next

- **Want to understand the idea?** → [architecture.md](architecture.md)
  explains the operational-amplifier analogy in depth: what "negative" and
  "positive" feedback mean here, and why *refusal* is the thing that makes it safe.
- **Want to use it?** → [usage.md](usage.md): the Python API, the `lfc`
  command-line tool, configuration, and how to plug in any model (Ollama, OpenAI,
  or your own callable).
- **Want the evidence?** → [results.md](results.md): the measured numbers
  (including a small 3.8B model reaching a ~28 GB model on a hard corpus), the
  method, and an honest account of what is *not* yet established.
- **Want the function reference?** → [api.md](api.md).
- **Have a quick question?** → [faq.md](faq.md).

## The two ideas worth remembering

1. **The model is the amplifier; deterministic code is the feedback network.**
   You trade a little of the model's raw "gain" (fluency) for precision, stability,
   and auditability — exactly the trade an op-amp makes.

2. **Refusal is a feature, not a failure.** A system that says "this input isn't
   something I can analyse exactly" or "I couldn't complete this confidently" is
   more useful than one that always answers. Refusal is what keeps the loop honest.

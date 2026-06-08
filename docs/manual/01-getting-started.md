[Manual home](../index.md) · [How it works →](02-how-it-works.md)

# Getting started

## Install

```bash
pip install llm-feedback-control
```

That's the whole install — the package has **zero third-party runtime
dependencies** (it uses only the Python standard library). Nothing else is pulled.

Optional extras:

```bash
pip install "llm-feedback-control[aws]"   # boto3, for the EC2 ceiling-model tooling
pip install "llm-feedback-control[dev]"   # pytest, build, twine (for contributors)
```

## Do I need a model?

**No, to start.** The deterministic pipeline — a regex extractor plus exact graph
analysis — runs immediately and returns a real result. A language model is a *pure
upgrade* to one step (extraction quality), not a requirement.

When you want the full quality, give it a model in any of three ways:

### Option 1 — Ollama (local, free, private)

```bash
# install Ollama: https://ollama.com
ollama pull phi3:mini      # ~2.3 GB, runs on CPU
```

The package talks to Ollama over HTTP using only the standard library. By default
it looks for `phi3:mini` at `http://localhost:11434`.

### Option 2 — OpenAI (no SDK needed)

```bash
export CEILING_BACKEND=openai
export OPENAI_API_KEY=sk-...
# OPENAI_MODEL defaults to gpt-4o-mini
```

### Option 3 — bring your own backend

Every entry point accepts an injectable `generate` callable, so you are **not tied
to any provider**. Pass any function `f(prompt, fmt=None) -> str`:

```python
from llm_feedback_control import run_audit

def my_llm(prompt, fmt=None):
    # call Anthropic, a local server, a hosted endpoint — anything.
    # if fmt == "json", returning strict JSON helps.
    return some_client.complete(prompt)

run_audit(text, generate=my_llm)
```

Run the doctor to see what's currently wired up:

```bash
lfc --check
```

## The command-line tool

Installing the package puts an `lfc` command on your PATH (equivalently
`python -m llm_feedback_control`):

```bash
lfc "A ticket opens in New. New goes to Assigned. Assigned goes to Resolved."
lfc --check         # probe the backend; say exactly what's available / what to do
lfc --demo          # run the three worked demos (M1 audit, M2 refusal, M3 readout)
lfc --json "..."    # print the full audit result as JSON
lfc --form --schema path/to/schema.json "..."   # extract form fields (file schema)
lfc --form --schema '{"fields":[...]}' "..."    # extract form fields (inline schema)
lfc --version
lfc                 # with no text, audits a built-in sample
```

## The Python API

### `run_audit` — audit a process end to end

The full pipeline: gate → extract → exact analysis → grounded report, with explicit
refusals. Returns a dict:

```python
r = run_audit("A claim enters Intake. From Intake it goes to Triage. "
              "Triage goes to FastTrack or to Investigation.")

r["result"]            # "OK", "OK (mixed: ...)", or "REFUSED: <reason>"
r["gate"]              # {"verdict": "finite_structural", "reason": ..., "source": ...}
r["extraction"]        # {"via": "llm" | "fallback", "states": [...], "transitions": [...]}
r["trace"]             # exact analysis: per-prime fingerprint + graph facts
r["report_facts"]      # the deterministic, checked summary (a string)
r["report_english"]    # an LLM rewrite of the facts (if a model is available)
```

When the input is continuous/belief-driven, `result` is a refusal and there is no
extraction:

```python
run_audit("Sentiment improves gradually as trust accumulates.")["result"]
# "REFUSED: model-only regime; no exact finite-structural analysis."
```

### `extract_iterative` — the bounded feedback loop

Returns `(graph, initial, history, converged)`:

```python
from llm_feedback_control import extract_iterative

graph, initial, history, converged = extract_iterative(text, verbose=False)

graph        # the final state machine (after gap-filling)
initial      # the open-loop, first-pass machine (for before/after comparison)
history      # per-iteration record of states/transitions and detected gaps
converged    # True iff it reached a clean fixed point; False -> refusal clamp fired
```

`converged is False` means the loop hit its iteration cap with residual gaps — the
**refusal clamp**. Treat that result as "incomplete, do not trust as final".

### `extract_form` — form-field extraction

The second built-in target, verified against a schema and the source text.
Also available on the command line as `lfc --form --schema`.

```python
from llm_feedback_control import extract_form

schema = {"fields": [
    {"name": "claimant", "type": "string",  "required": True},
    {"name": "policy",   "type": "pattern", "required": True, "pattern": r"[A-Z]{2}-\d{6}"},
    {"name": "email",    "type": "email",   "required": True},
    {"name": "amount",   "type": "currency","required": True},
    {"name": "kind",     "type": "enum",    "required": True,
     "values": ["collision", "theft", "fire", "water", "other"]},
]}

out = extract_form("Claim by Tom Becker, policy TH-998120, tbecker@x.com, "
                   "loss $1,180, theft.", schema)
out["result"]      # "OK"  or  "REFUSED: could not fill/validate required fields: ..."
out["record"]      # {'claimant': 'Tom Becker', 'policy': 'TH-998120', ...}
out["converged"]   # True iff every required field is filled and valid
out["gaps"]        # remaining {field, problem, hint} items
```

Field types: `string`, `email`, `phone`, `number`, `currency`, `date`, `enum` (with
`values`), `pattern` (with a regex). It **verifies each value against the source
text**, recovers detectable values the model hallucinated, and **refuses** rather
than inventing a missing required field. Runs with no model (detectors fill the
detectable fields).

### Building your own target with `feedback_loop`

Both targets run on one injectable engine. To add a new one, supply an extractor, a
deterministic reference (returns a list of gaps; empty = done), a repair step, and a
signature for stall detection:

```python
from llm_feedback_control import feedback_loop

final, initial, history, converged = feedback_loop(
    text, extract=my_extract, reference=my_reference,
    repair=my_repair, signature=my_signature, finalize=None)
```

### Lower-level building blocks

All exported from the top-level package:

```python
from llm_feedback_control import (
    regime_gate,        # classify text: finite_structural / model_only / mixed
    extract_workflow,   # one-shot extraction (LLM + schema + regex fallback)
    fallback_extract,   # the deterministic regex extractor (no model)
    exact_analysis,     # per-prime fingerprint + graph facts
    graph_facts,        # terminals / unreachable / has_cycle
    grounded_report,    # render checked facts (+ optional LLM rewrite)
    consistency_gaps,   # the deterministic reference: what the text has that the graph lacks
    valid,              # schema check for an extracted machine
    norm,               # state-name normaliser
    doctor,             # backend health probe (never raises)
    gen, gen_ceiling,   # the default Ollama client + a stronger "ceiling" model
    BackendError,       # raised by gen/gen_ceiling when no backend is reachable
)
```

Note `regime_gate(text, use_llm=False)` gives a pure-heuristic verdict with no
network call — handy for tests and offline use.

## Configuration (environment variables)

| variable | default | meaning |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | where the local Ollama server lives |
| `LFC_MODEL` | `phi3:mini` | the small model under test (`gen`) |
| `LFC_CEILING` | `llama3.1:8b` | a bigger local Ollama "ceiling" model (`gen_ceiling`) |
| `CEILING_BACKEND` | `ollama` | `ollama` or `openai` |
| `OPENAI_API_KEY` | — | required iff `CEILING_BACKEND=openai` |
| `OPENAI_MODEL` | `gpt-4o-mini` | the OpenAI model used as the ceiling |

The same code runs unchanged on a laptop and on a remote box — only these env vars
differ. (The `gen_ceiling` "ceiling model" is used by the experiments to measure a
small model against a much larger one; see [Results](04-results.md).)

## Error handling

`gen` and `gen_ceiling` raise `BackendError` with actionable guidance when no model
is reachable. The high-level functions (`run_audit`, `extract_iterative`,
`regime_gate`, …) **catch this internally and fall back** to the deterministic
path, so a missing model degrades gracefully rather than crashing. You only need to
handle `BackendError` if you call `gen` / `gen_ceiling` yourself.

---

[Manual home](../index.md) · [How it works →](02-how-it-works.md)

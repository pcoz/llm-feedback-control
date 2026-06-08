[← Results](04-results.md) · [Manual home](../index.md) · [FAQ →](06-faq.md)

# Worked examples

Actual transcripts from real runs (small local models, plus one large-model
ceiling). They're illustrative, not benchmarks — see [Results](04-results.md) for
method and scope. Commands are runnable as shown.

---

## 1. Workflow audit with no model (deterministic path)

A bare `pip install` already does real work: with no model reachable, `run_audit`
falls back to a regex extractor + exact graph analysis.

```console
$ OLLAMA_HOST=http://127.0.0.1:1 \
  lfc "A ticket opens in New. New goes to Assigned. Assigned goes to Resolved. Resolved goes to Closed."

gate      : finite_structural | heuristic (fin=4,cont=0)
extracted : via=fallback  states=['New', 'Assigned', 'Resolved', 'Closed']
            transitions=[['Assigned', 'Resolved'], ['New', 'Assigned'], ['Resolved', 'Closed']]
facts     :
   - States (4): New, Assigned, Resolved, Closed
   - Terminal states: Closed
   - Unreachable from start: none
   - Contains a cycle (loop): False
   - Bad primes (mode annihilates): [2, 3, 5, 7]
   - Non-injective readout at primes (lift REFUSED): none
grounded  : (LLM rewrite unavailable; deterministic facts above are authoritative.)
result    : OK
```

`via=fallback` shows the deterministic path ran (no model). Plug in a model and
`via` becomes `llm`; everything else is the same shape.

---

## 2. A small model reaching a ~28 GB model (workflow extraction)

`experiments/hard_corpus.py` on a messy, branchy, distractor-laden 5-workflow
corpus. Three configurations: the small model one-shot (`open`), the same small
model + the feedback loop (`closed`), and a large ceiling model one-shot (`ceil`).
The small model is `phi3:mini` (3.8B); the ceiling is `mixtral:8x7b` (~28 GB), run
on an EC2 large-RAM instance.

```text
workflow    open sF1 open tF1  clo sF1  clo tF1 ceil sF1 ceil tF1  it
--------------------------------------------------------------------------------
Intake          1.00     1.00     1.00     1.00     1.00     0.93   1
Queued          0.91     0.92     1.00     1.00     1.00     0.88   2
New             1.00     0.71     1.00     0.71     1.00     1.00   1
Placed          1.00     0.91     1.00     0.91     1.00     0.73   1
Created         1.00     0.89     1.00     0.89     1.00     1.00   1
--------------------------------------------------------------------------------
MEAN            0.98     0.89     1.00     0.90     1.00     0.91

gap to ceiling recovered by the loop:  states 100%   transitions 77%
```

The closed-loop small model **matches the ~28 GB model**, and on several rows it
*beats* the big model on transitions (Intake 1.00 vs 0.93, Placed 0.91 vs 0.73,
Queued 1.00 vs 0.88) — the deterministic reference catches edges that raw fluency at
scale invents or drops.

---

## 3. Form-field extraction: hallucination recovery + refusal

`extract_form` on a 5-document insurance-claim corpus (`phi3:mini`, local), open
(one-shot) vs closed (the loop). Schema: `claimant_name` (string), `policy_number`
(pattern `[A-Z]{2}-\d{6}`), `email`, `phone`, `incident_date`, `claim_amount`
(currency), `claim_type` (enum).

```text
document            open   closed  iters   conv  notes
------------------------------------------------------------------------------
Maria               1.00     1.00      1   True
Tom                 1.00     1.00      1   True
Priya               1.00     1.00      1   True
Daniel              1.00     1.00      1  False  REFUSED correctly (no amount invented)
Aisha               0.71     0.86      4  False
      - email: gt='aisha+claims@example.org'
               open='aisha+claims@exampleterm.org'  ✗   (model hallucinated a domain)
               closed='aisha+claims@example.org'         (recovered from the source)
      - claim_type: gt='other'  open=None  closed=None  ✗  (semantic enum map; refused)
------------------------------------------------------------------------------
MEAN                0.94     0.97
refusal test (genuinely-missing required field): 1/1 refused without inventing a value
```

Two things to notice:

- **Aisha** — one-shot emitted `aisha+claims@exampleterm.org` (invented "exampleterm");
  the reference detected the value wasn't in the source, and when re-asking didn't
  fix it, the detector **recovered** the true `aisha+claims@example.org` from the
  text. 0.71 → 0.86 on that document.
- **Daniel** — the source genuinely omits the claim amount (a required field). The
  loop **refused** (`converged=False`) rather than fabricating a number.

The one residual miss (`vandalism` → the enum value `other`) is a semantic mapping no
detector can make, so the loop correctly refuses instead of guessing.

---

## 4. Both targets on a live small model (`phi3:mini`)

```python
from llm_feedback_control import extract_form, run_audit

SCHEMA = {"fields": [
    {"name": "claimant_name", "type": "string",  "required": True},
    {"name": "policy_number", "type": "pattern", "required": True, "pattern": r"[A-Z]{2}-\d{6}"},
    {"name": "email",         "type": "email",   "required": True},
    {"name": "incident_date", "type": "date",    "required": True},
    {"name": "claim_amount",  "type": "currency","required": True},
    {"name": "claim_type",    "type": "enum",    "required": True,
     "values": ["collision", "theft", "fire", "water", "other"]},
]}

text = ("Submitted by Aisha Rahman, policy OT-771234, regarding an issue on "
        "2026-03-01. Damages around $900. Reach me at aisha+claims@example.org. "
        "Phone 555-330-1212.")
out = extract_form(text, SCHEMA)
```

```text
FORM result : REFUSED: could not fill/validate required fields: claim_type
FORM email  : aisha+claims@example.org      # recovered, not hallucinated
FORM amount : $900 | policy: OT-771234

WORKFLOW    : OK | via llm | states ['Intake', 'Triage', 'FastTrack', 'Investigation', 'Payout']
```

The form is **refused** on `claim_type` (the text says "maybe vandalism?", which
isn't a clean enum value) while every value it *did* return is verified against the
source. The workflow audit returns `OK` with the states extracted via the model.

---

## Reproduce

```bash
pip install -e ".[dev]"
ollama pull phi3:mini

lfc "A ticket opens in New. New goes to Assigned."     # example 1 (force fallback with a bad OLLAMA_HOST)
python experiments/hard_corpus.py                       # example 2 (set LFC_CEILING for the ceiling column)
```

Examples 3–4 use the form harness from the development exploration; the package API
shown in §4 reproduces them directly.

---

## 5. Form-field extraction via the CLI

`extract_form` is also available from the command line with `lfc --form --schema`.
The schema is auto-detected: a JSON file path or an inline JSON string.

### All-detectable schema (OK)

A schema whose required fields are all detectable types (`pattern`, `email`, `currency`, …)
completes with no model at all:

```json
{"fields": [
    {"name": "policy",   "type": "pattern", "required": true, "pattern": "[A-Z]{2}-\\d{6}"},
    {"name": "email",    "type": "email",   "required": true},
    {"name": "amount",   "type": "currency","required": true}
]}
```

```console
$ lfc --form --schema all_detectable.json \
  "Policy OT-771234, reach me at aisha@example.org, lost 950.00."

result    : OK
converged : True
iterations: 1
record    :
   policy: OT-771234
   email: aisha@example.org
   amount: 950.00
```

### Mixed schema (REFUSED on undetectable fields)

Add a `string` or `enum` required field and, without an LLM, the system refuses
rather than inventing. The detectable fields are still filled deterministically:

```json
{"fields": [
    {"name": "claimant", "type": "string",  "required": true},
    {"name": "policy",   "type": "pattern", "required": true, "pattern": "[A-Z]{2}-\\d{6}"},
    {"name": "email",    "type": "email",   "required": true},
    {"name": "amount",   "type": "currency","required": true},
    {"name": "kind",     "type": "enum",    "required": true, "values": ["theft","fire"]}
]}
```

```console
$ lfc --form --schema mixed.json \
  "Policy XY-998120, john@test.com, claimed 1500.00."

result    : REFUSED: could not fill/validate required fields: claimant, kind
converged : False
iterations: 1
record    :
   claimant: None
   policy: XY-998120
   email: john@test.com
   amount: 1500.00
   kind: None
gaps:
   claimant: missing_required
   kind: missing_required
```

### Inline schema

For quick one-offs you can pass the schema directly without a file:

```console
$ lfc --form --schema '{"fields":[{"name":"email","type":"email","required":true}]}' \
  "contact me at bob@example.com"

result    : OK
converged : True
iterations: 1
record    :
   email: bob@example.com
```

With an LLM backend reachable, `string` and `enum` fields are populated too — the same
`extract_form` loop described in [§4](#4-both-targets-on-a-live-small-model-phi3mini) — but
even with no model the detectors fill the detectable types (email, phone, currency, date,
pattern), making simple extractions work immediately after `pip install`.

---

[← Results](04-results.md) · [Manual home](../index.md) · [FAQ →](06-faq.md)

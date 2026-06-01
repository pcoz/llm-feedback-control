# llm-feedback-control

**Get reliable, checkable structured output from a small, local language model —
by wrapping it in ordinary deterministic code.**

[![CI](https://github.com/pcoz/llm-feedback-control/actions/workflows/ci.yml/badge.svg)](https://github.com/pcoz/llm-feedback-control/actions/workflows/ci.yml)

---

## The problem this solves

Large language models — the technology behind ChatGPT and similar tools — are
brilliant at reading plain English and writing fluent, confident answers. But they
have a well-known flaw: **they make things up, and they sound exactly as sure when
they're wrong as when they're right.**

That flaw bites hardest when you ask a model to pull *structure* out of text — the
steps of a process, the states of a workflow, the fields of a form. It will get
most of it right, then quietly invent a step that isn't there, or drop one that is.
For anything you actually need to rely on, "usually right, never tells you when it
isn't" is not good enough.

This library fixes that. It turns free text into **structured data you can trust**,
by pairing the language model with a deterministic **reference** — real checking
code, suited to whatever you're extracting — and running a feedback loop that does
three things:

- **verifies** the model's answer against that reference (provable facts, a schema,
  known patterns — whatever fits the target);
- **fills in** what the model missed, by re-asking with the specific gaps pointed out;
- **refuses** — says "I'm not sure" — when it can't verify the result, instead of
  guessing.

The payoff: a *small* model you can run for free on your own laptop becomes reliable
enough to use, because the **checking** — not the model's size — does the heavy
lifting. (In our tests a 3.8B model wrapped this way matches a model about seven
times larger; see [results](#whats-measured-so-far).)

## What you can extract

It's **one engine pointed at different targets.** A target is anything you can pair
with a schema and a deterministic check — **two ship today**, and more are a small
addition (the loop is public and injectable):

- **workflows / processes → state machines** (`run_audit`) — *ships today*: states,
  transitions, dead ends, unreachable steps, loops;
- **form fields** (invoices, applications, claims) against a field schema + format
  and required-field rules (`extract_form`) — *ships today*: verifies each value
  against the source, recovers ones the model hallucinated, refuses on missing
  required fields;
- **records / tables** against a known column set and types;
- **entities & relations** against a gazetteer or pattern set;
- **configs / specs** against a schema or grammar.

The piece that changes between targets is the **reference** — the checking code
(graph analysis, a field schema with validators, a pattern set). That's the
substantive part, and it's what decides whether the engine helps: where you can
write a cheap, independent check, the payoff is large. Where there *is* no such
check (open-ended summarising, sentiment, theme-finding), the engine **refuses to
claim exactness** — by design. See [Adding a new target](#adding-a-new-target).

**Who it's for:** anyone who needs dependable structured output from a language
model without paying for a giant model or a cloud API, and without silently trusting
a guess.

If you just want to try it, jump to [Quickstart](#quickstart-works-with-no-model).

## What it does, concretely (worked example: workflow extraction)

To make the loop concrete, here it is on the target that ships today. You hand it a
process written in plain English:

> "A claim enters Intake. From Intake it goes to Triage. Triage goes to FastTrack
> or to Investigation. FastTrack goes to Payout. Investigation goes to Payout or
> to Denied. Payout goes to Closed. Denied goes to Closed."

and it:

1. **turns that into a state machine** — the steps (states) and the arrows between
   them (transitions);
2. **computes provable facts** about it — which steps are dead ends, whether
   there are loops, which steps can't be reached from the start;
3. **writes a report where every statement is backed by one of those checked
   facts** — so it can't quietly make things up;
4. **knows its own limits.** If the text isn't actually a finite step-by-step
   process (e.g. *"prices drift up as confidence grows"*), it **refuses** instead
   of inventing a fake state machine. And if the model's first pass missed part of
   the process, it **loops to fill the gaps** — or refuses if it can't.

The point: you get **higher-quality, auditable structured output from a *small*
model**, trading a few extra passes (latency) for accuracy — no extra parameters,
no special mathematics, no cloud. It runs on a laptop, and the deterministic parts
run **with no model at all**.

## Quickstart (works with no model)

```bash
pip install llm-feedback-control      # zero dependencies — pulls nothing else
```

```python
from llm_feedback_control import run_audit

r = run_audit("A claim enters Intake. From Intake it goes to Triage. "
              "Triage goes to FastTrack or to Investigation.")
print(r["result"])         # OK
print(r["report_facts"])   # terminals, loops, unreachable steps — all checked
```

That already works on a bare install: with no model reachable it uses a
deterministic regex extractor plus exact graph analysis. **Plug in a model and the
extraction quality goes up — nothing else changes.**

From the command line:

```bash
lfc "A ticket opens in New. New goes to Assigned. Assigned goes to Resolved."
lfc --check        # tells you exactly what backend is available and what to do
lfc --demo         # runs the three worked demos
```

### A second target: form fields

The same engine, pointed at a field schema:

```python
from llm_feedback_control import extract_form

schema = {"fields": [
    {"name": "email",  "type": "email",    "required": True},
    {"name": "amount", "type": "currency", "required": True},
    {"name": "policy", "type": "pattern",  "required": True, "pattern": r"[A-Z]{2}-\d{6}"},
]}
out = extract_form("Policy AB-123456, reach me at jo@x.com, total $200.", schema)
print(out["result"])   # OK    (REFUSED: ... when a required field can't be filled)
print(out["record"])   # {'email': 'jo@x.com', 'amount': '$200', 'policy': 'AB-123456'}
```

Supported field types: `string`, `email`, `phone`, `number`, `currency`, `date`,
`enum` (with `values`), `pattern` (with a regex). With no model, the detectors fill
the detectable fields deterministically; same `record` shape.

### Add a model (optional, recommended)

The library is **not tied to any provider.** Three ways to give it a model:

```bash
# 1. Local, free, private — install Ollama (https://ollama.com), then:
ollama pull phi3:mini

# 2. OpenAI (stdlib HTTP, no SDK):
export CEILING_BACKEND=openai OPENAI_API_KEY=sk-...
```

```python
# 3. Bring your own: pass any callable f(prompt, fmt=None) -> str
def my_llm(prompt, fmt=None):
    ...                       # call Anthropic, a local server, anything
run_audit(text, generate=my_llm)
```

Run `lfc --check` any time to see what's wired up.

## How it works — "feedback control", explained

The design is borrowed from **electronics.** A raw LLM is like a very high-gain
amplifier: hugely powerful, but left to run "open-loop" it overshoots — fluent,
yet it drifts and hallucinates. Engineers tame such an amplifier by adding a
**feedback loop**: feed the output back, compare it against a stable reference,
and trade some raw power for precision and stability. This library is that
feedback loop for an LLM. The "reference" is plain deterministic code — graph
checks and schema rules — that the model's output is measured against.

There are two kinds of feedback, and the library uses both:

### Negative feedback — the stabilising checks (`run_audit`)

This is the half that *grounds and refuses*. In plain terms:

| step | what it means |
|---|---|
| **regime gate** | First decide whether the text is even the kind of thing we can analyse exactly (a finite, step-by-step process) versus something fuzzy and continuous. Refuse the fuzzy ones. |
| **extraction + schema** | Ask the model for the state machine, but force the answer into a strict shape — and fall back to a deterministic regex extractor if it won't comply (or if there's no model). |
| **exact analysis** | Compute provable facts about the graph: dead ends, loops, unreachable steps. (Plus an *optional* finite-field "spectral fingerprint" — see below.) |
| **grounded report** | Write the summary using only those verified facts, naming only real states. |
| **explicit refusal** | When the input is out of regime, or a result can't be made exact, say so — don't guess. |

### Positive feedback — the gap-filling loop (`extract_iterative`)

A one-shot extraction often silently **drops a branch** — the model says "OK"
while quietly missing *Investigation → Denied*. Positive feedback fixes that: it
**re-asks the model about anything the source text mentions that's missing from
the answer**, and repeats until nothing is missing (a *fixed point*).

Positive feedback is where capability *and* instability both live, so it's bounded
by two negative-feedback safeguards: a deterministic consistency check (does the
graph cover everything the text mentions?) and a **refusal clamp** — if it can't
converge within a few passes, it refuses to report a confident-but-incomplete
result rather than running away. This **refusal-as-stabilizer** is what makes the
regenerative loop safe.

## What's measured so far

Indicative results, not benchmarks — small corpora, a 3.8B local model
(`phi3:mini`), greedy decoding. See [`docs/results.md`](docs/results.md) for the
full tables and method.

**Headline (run on EC2 against a ~28 GB ceiling model, mixtral 8x7B):** on a
messy, branchy, distractor-laden workflow corpus, the small model **+ the feedback
loop essentially matches a model ~7× its size.**

| configuration | states F1 | transitions F1 |
|---|---|---|
| small model (phi3:mini), one-shot | 0.98 | 0.89 |
| **small model + feedback loop** | **1.00** | **0.90** |
| big ceiling model (mixtral, ~28 GB), one-shot | 1.00 | 0.91 |

→ the loop recovers **100%** of the small→big gap on states and **77%** on
transitions — and on several individual workflows the closed-loop small model
*beat* the big model, because the deterministic reference catches edges that raw
fluency invents or drops.

Other measured pieces: extraction states precision/recall ≈ 1.00 / 0.92; the
regime gate scores 1.00 precision/recall separating finite from continuous on a
clean corpus (it's brittle on deliberately *mixed* inputs — an open problem).

## Documentation

| doc | contents |
|---|---|
| [`docs/index.md`](docs/index.md) | overview and where to start |
| [`docs/architecture.md`](docs/architecture.md) | the op-amp model in depth; the pipeline; refusal-as-stabilizer |
| [`docs/usage.md`](docs/usage.md) | install, the API, the CLI, configuration, bring-your-own-backend |
| [`docs/results.md`](docs/results.md) | the measured results, method, and honest scope |
| [`docs/api.md`](docs/api.md) | reference for every public function |
| [`docs/faq.md`](docs/faq.md) | "do I need a GPU?", "what models?", "does it work offline?" … |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | release history |

## Repository layout

```
src/llm_feedback_control/   the package (zero-dependency, pure standard library)
  loop.py                   the shared engine: the injectable feedback_loop
  llm.py                    the LLM client + injectable backend + a doctor()
  auditor.py                the workflow negative-feedback pipeline (run_audit)
  feedback.py               the workflow positive-feedback loop (extract_iterative)
  forms.py                  the form-field target (extract_form)
  __main__.py               the `lfc` command-line tool
experiments/                repro scripts for the measured results (not shipped)
aws/                        optional: run a large ceiling model on EC2 (not shipped)
docs/                       the documentation suite
tests/                      deterministic tests (no model / no network)
```

## Honest scope

- **A reliability architecture, not a model improvement.** The win is "the system
  knows what it can compute exactly and refuses the rest" — orthogonal to model
  scale. It helps on the *structured / verifiable slice* (workflows, state
  machines, configs), not open-ended generation.
- **It uses no special mathematics.** The deterministic reference is plain
  graph/text consistency. (The finite-field "spectral fingerprint" is an *optional*
  extra exact check, honestly redundant with graph analysis for most workflow
  audits — keep it or ignore it.)
- **Needs a deterministic reference.** Where there's nothing to check against, the
  gate (correctly) refuses to claim exactness.
- **Results are indicative.** Small corpora; treat the numbers as direction, not
  guarantees.

## Adding a new target

Both shipped targets (`run_audit`, `extract_form`) run on one public, injectable
engine — `feedback_loop`. Only two things change between targets; the rest — the
bounded loop, the gap-filling, the refusal clamp, the LLM backend — is shared:

1. **a target schema** — the shape you want out;
2. **a deterministic reference** — model-free code that, given the text and a
   candidate answer, returns a list of what's missing or wrong (empty = done). For
   workflows it's "does the graph cover every state the text mentions?"; for forms
   it's "required fields present, valid, and actually found in the source text".

```python
from llm_feedback_control import feedback_loop

final, initial, history, converged = feedback_loop(
    text,
    extract=my_extract,       # text -> candidate
    reference=my_reference,   # (text, candidate) -> [gaps]   (empty == converged)
    repair=my_repair,         # (text, candidate, gaps) -> candidate
    signature=my_signature,   # candidate -> hashable (stall detection)
    finalize=my_finalize,     # optional deterministic last resort
)
```

The form target is the worked second example: its reference is a field schema plus
independent regex detectors (email, date, currency, phone, custom patterns). It
**verifies each value against the source document**, **recovers** a value the model
hallucinated by reading it back out of the text, and **refuses** when a required
field is genuinely absent. (Constrained-decoding libraries guarantee output *shape*
but not *truth*; cloud OCR doesn't check against your schema. This does both.)

## Origin

This project is the practical, validated spin-off of an internal research
investigation. The investigation's grander mathematical claims did not hold up
under measurement; this engineering architecture — LLM feedback control with
refusal-as-stabilizer — is the part that did. It stands on its own.

## License

MIT with an attribution clause — see [`LICENSE`](LICENSE).
Built with llm-feedback-control by Edward Chalk (sapientronic.ai).

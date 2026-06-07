# LLM Feedback Control

**A control layer for LLM-in-the-loop reliability: wrap an unreliable generator in a
verify-and-refuse feedback loop, so what comes out is checked, corrected, or honestly
refused — never a confident guess.**

[![CI](https://github.com/pcoz/llm-feedback-control/actions/workflows/ci.yml/badge.svg)](https://github.com/pcoz/llm-feedback-control/actions/workflows/ci.yml)

## What it does

Language models are fluent but they make things up — and they sound just as sure
when they're wrong. The moment an LLM's output feeds a decision that has to be right
— a form parsed, a process mapped, a config validated, one model's answer judged by
another — "usually correct, and never tells you when it isn't" becomes a real problem.

LLM Feedback Control borrows the fix from control engineering: don't try to make the
generator cleverer, **close a loop around it.** You pair the model with a *reference*
— something that can check its output — and the loop:

- **verifies** the answer against that reference,
- **fills in / corrects** what's wrong by re-asking with the specific gaps pointed out,
- **refuses** — says "I can't vouch for this" — when it can't verify the result,
  instead of guessing.

The controller seat is **pluggable.** The reference can be **deterministic code** (a
schema, graph checks — an exact guarantee), a **low-power model acting as a critic**
(for fuzzy quality no rule captures), or a **composition** of several — and the
feedback blocks wire into "circuits": a summing junction, an instrumentation amp
(independent critics, common-mode rejection), a multi-stage cascade, a hysteresis
gate. One rule holds it together: **keep at least one exact element in the loop.**

Because the *loop* does the work — not the model's size — a small model you run for
free on a laptop becomes reliable enough to use in earnest: in our tests a 3.8B model
inside the loop matched one about seven times larger. That is now a proof point, not
the whole story.

## Use cases

| If you need to… | Use | Circuit |
|---|---|---|
| Turn a process described in prose into a verified state machine (dead ends, unreachable steps, loops) | `run_audit` | — |
| Pull form fields from a document, each checked against the source, refusing on a missing required field | `extract_form` | — |
| Extract your own structure (records, entities, configs) with a schema and a check you supply | `feedback_loop` | — |
| Get trustworthy output from a small / local model instead of paying for a large one | any target — the loop does the work | closed loop |
| Decide whether a task is exactly checkable at all, and refuse the fuzzy ones | `regime_gate` | comparator |
| Catch fuzzy quality no rule expresses (relevance, coherence, "did it answer the question?") | `llm_critic_reference` + `llm_critic_repair` | model controller |
| Keep an exact guarantee but add a critic's breadth on top | `combine_references` | summing junction |
| Avoid a single critic's false alarms / same-model rubber-stamping | `quorum_reference` (independent critics) | instrumentation amp |
| Run a multi-step pipeline (extract → normalise → enrich), each step checked, stopping if one can't be trusted | `cascade` / `loop_stage` | multi-stage amp |
| Drive an irreversible commit, or flip a two-way mode, off a noisy score without chattering (and set it directly when a human or rule decides) | `schmitt_gate` | Schmitt trigger |

The rows below the line are covered in
[Controllers and circuits](https://github.com/pcoz/llm-feedback-control/blob/main/docs/manual/07-controllers-and-circuits.md);
the first three are the built-in targets, detailed next.

### What you can extract

It's **one engine pointed at different targets.** A target is anything you can pair
with a schema and a deterministic check — **two ship today**, more are a small
addition (the loop is public and injectable):

- **workflows / processes → state machines** (`run_audit`) — states, transitions,
  dead ends, unreachable steps, loops;
- **form fields** (invoices, applications, claims) against a field schema
  (`extract_form`) — verifies each value against the source, recovers ones the model
  hallucinated, refuses on missing required fields;
- **records / tables**, **entities & relations**, **configs / specs** — bring a
  schema + a reference and call `feedback_loop`.

It helps on the **structured, verifiable slice** — where a deterministic reference
exists. For open-ended generation (summaries, sentiment) there's nothing to check
against, so it refuses to claim exactness, by design.

Beyond the built-in targets, the controller seat is pluggable and the feedback blocks
compose into circuits — see
[Controllers and circuits](https://github.com/pcoz/llm-feedback-control/blob/main/docs/manual/07-controllers-and-circuits.md).

## Documentation

The full **user manual** is in [`docs/`](https://github.com/pcoz/llm-feedback-control/blob/main/docs/index.md):

| chapter | contents |
|---|---|
| [Getting started](https://github.com/pcoz/llm-feedback-control/blob/main/docs/manual/01-getting-started.md) | install, the API, the `lfc` CLI, choosing/bringing a model, configuration |
| [How it works](https://github.com/pcoz/llm-feedback-control/blob/main/docs/manual/02-how-it-works.md) | the op-amp model: negative/positive feedback, refusal-as-stabilizer, the general engine |
| [API reference](https://github.com/pcoz/llm-feedback-control/blob/main/docs/manual/03-api-reference.md) | every public function |
| [Results](https://github.com/pcoz/llm-feedback-control/blob/main/docs/manual/04-results.md) | measured numbers, method, honest scope |
| [Worked examples](https://github.com/pcoz/llm-feedback-control/blob/main/docs/manual/05-examples.md) | actual run transcripts |
| [FAQ](https://github.com/pcoz/llm-feedback-control/blob/main/docs/manual/06-faq.md) | GPU? models? offline? why did it refuse? |
| [Controllers and circuits](https://github.com/pcoz/llm-feedback-control/blob/main/docs/manual/07-controllers-and-circuits.md) | a model in the controller seat; combining independent critics; the op-amp "circuits" (summing junction, instrumentation amp, cascade, hysteresis gate) |
| [Changelog](https://github.com/pcoz/llm-feedback-control/blob/main/docs/CHANGELOG.md) | release history |

## Install

```bash
pip install llm-feedback-control     # zero dependencies
```

Then follow [Getting started](https://github.com/pcoz/llm-feedback-control/blob/main/docs/manual/01-getting-started.md). The deterministic
parts run with no model at all; a model (local Ollama, OpenAI, or your own callable)
is a pure upgrade.

## License

MIT with an attribution clause — see [`LICENSE`](https://github.com/pcoz/llm-feedback-control/blob/main/LICENSE).
Built with llm-feedback-control by Edward Chalk (sapientronic.ai).

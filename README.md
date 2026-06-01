# LLM Feedback Control

**Get reliable, checkable structured data out of a small, local language model — by
wrapping it in deterministic feedback.**

[![CI](https://github.com/pcoz/llm-feedback-control/actions/workflows/ci.yml/badge.svg)](https://github.com/pcoz/llm-feedback-control/actions/workflows/ci.yml)

## What it does

Language models are fluent but they make things up — and they sound just as sure
when they're wrong. That bites hardest when you ask one to pull **structure** out of
text (the steps of a process, the fields of a form): it gets most of it right, then
quietly invents or drops the rest.

This library turns free text into **structured data you can trust.** It pairs the
model with a deterministic **reference** — real checking code suited to what you're
extracting — and runs a feedback loop that:

- **verifies** the model's answer against that reference,
- **fills in** what the model missed by re-asking with the gaps pointed out,
- **refuses** — says "I'm not sure" — when it can't verify the result, instead of
  guessing.

Because the **checking** (not the model's size) does the heavy lifting, a small
model you run for free on a laptop becomes reliable enough to use. In our tests a
3.8B model wrapped this way matches one about seven times larger.

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

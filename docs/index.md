# LLM Feedback Control — User Manual

Large language models are remarkably good at reading English and producing fluent,
structured-looking output. They are also unreliable in a specific and costly way:
when you ask one to extract structure from text — the steps of a process, the fields
of a form — it will get most of it right and then, with exactly the same confidence,
invent a detail that was never there or quietly drop one that was. For casual use
that is tolerable. For anything you intend to rely on, "usually correct, and never
tells you when it isn't" is a serious problem.

LLM Feedback Control is a small library that solves this for one well-defined job:
turning free text into structured data you can actually trust. It does not try to
make the model itself cleverer. Instead it wraps the model in a layer of ordinary,
deterministic code — a *reference* — that checks the model's work against something
verifiable, asks it to fix what it got wrong, and, when it cannot confirm an answer,
refuses to give one rather than guessing.

The consequence is that the reliability comes from the checking, not from the size
of the model. A small model you can run for free on your own laptop, wrapped this
way, becomes dependable enough to use in earnest. In our own tests a
3.8-billion-parameter model inside the loop matched the output of a model roughly
seven times its size.

## How it works: wrapping the model in a feedback loop

The project's name is literal. "Feedback control" is a real technique from control
engineering and electronics, and this library wraps one around a language model.

A raw language model behaves like a very high-gain amplifier: enormously powerful, but
left to run "open-loop" it overshoots — fluent, yet drifting and fabricating. The classic
engineering fix is *feedback*: take the output, compare it against a stable reference,
and feed the difference back in. You give up a little raw gain and you get back
precision, stability, and predictability. This library is that feedback loop, built
around a language model. The reference is not a voltage; it is plain deterministic
code — graph checks, a schema, a set of patterns — that the model's output is
measured against and corrected toward.

In everyday terms the loop does three things. It **verifies** the model's answer
against the reference. It **fills in** whatever the model missed, by asking again with
the specific gaps pointed out. And it **refuses** — says, in effect, "I cannot vouch
for this" — whenever it cannot verify the result. That third behaviour is the one
that matters most: a system willing to say no is what makes the rest worth trusting.

## What it extracts

The library pulls structured information out of free text, and it ships with two
kinds of extraction built in.

- **Workflow extraction** (`run_audit`). Give it a process written in prose — "a
  claim enters Intake, then goes to Triage; from Triage it is either fast-tracked or
  sent to Investigation…" — and it returns the underlying state machine, together
  with the facts that can be *proved* about it: which steps are dead ends, which can
  never be reached, and where the loops are.
- **Form-field extraction** (`extract_form`). Give it a document and a list of the
  fields you want — a name, an email, a policy number, an amount — and it returns
  those fields filled in, but only after checking each value against the source text.
  If the model invents a value the document doesn't contain, the loop catches it and
  recovers the real one; if a required field is genuinely absent, the loop refuses
  rather than making one up.

You are not limited to those two. The loop is public, so you can add your own kind of
extraction by giving it the shape you want back and a way to check it. And where there
is nothing to check against — open-ended summarising, sentiment — the library declines
to claim exactness rather than bluffing. That is deliberate, not a gap.

## Where to start, and what each chapter covers

If you are new, start with **[Getting started](manual/01-getting-started.md)**: it
covers installation, the handful of API calls, the `lfc` command-line tool, and how
to point the library at a model — a local one, a hosted one, or your own. From there,
**[How it works](manual/02-how-it-works.md)** explains the feedback model properly:
the difference between the stabilising "negative" feedback and the gap-filling
"positive" feedback, and why refusal is the thing that keeps the latter safe.

When you need to look something up, the **[API reference](manual/03-api-reference.md)**
documents every public function and the **[FAQ](manual/05-faq.md)** answers the common
practical questions — whether you need a GPU, whether it works offline, why it
sometimes refuses. The **[Results](manual/04-results.md)** chapter reports what has
actually been measured, honestly and with its limitations, and
**[Worked examples](manual/06-examples.md)** walks through real transcripts from real
runs, including the small model reaching the quality of a far larger one and a form
extraction catching a hallucinated value.

For the change history, see the **[Changelog](CHANGELOG.md)**; for the short version
of all this, the **[project README](../README.md)**; and for the code itself, the
**[repository](https://github.com/pcoz/llm-feedback-control)**.

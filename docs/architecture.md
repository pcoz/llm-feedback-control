# Architecture: the operational-amplifier model

This document explains the idea behind the library from scratch. No electronics
or control-theory background is assumed — the analogy is introduced and then
unpacked into exactly what the code does.

## 1. The problem

A large language model (LLM) is extraordinarily good at reading English and
producing plausible structured output. Ask one to turn

> "A claim enters Intake. From Intake it goes to Triage. Triage goes to FastTrack
> or to Investigation. …"

into a list of states and transitions, and it will usually get most of it right.
But "most of it right" is the problem:

- it may **drop a branch** (forget *Investigation → Denied*) and still sound
  confident;
- it may **invent** a state or an edge that isn't in the text;
- it has **no idea when it's out of its depth** — give it *"prices drift up as
  confidence grows"* and it will happily fabricate a state machine that doesn't
  exist.

These aren't bugs you can prompt away. They're the nature of an open-loop
generator: high capability, no built-in reference for "correct".

## 2. The analogy: a high-gain amplifier

In electronics, an **operational amplifier** ("op-amp") is a device with enormous
*gain* — it multiplies a tiny input voltage by a huge factor. On its own
("open-loop") that gain is almost useless: the slightest input sends the output
slamming into its limits, and it's wildly sensitive to noise and drift. Too much
of a good thing.

The fix, discovered in the 1920s and now in essentially every analog circuit, is
**feedback**: take part of the output, feed it back, and compare it against a
stable *reference*. The amplifier then automatically corrects itself toward the
reference. You give up some raw gain, and in exchange you get **precision,
stability, and predictability**. A railing, twitchy amplifier becomes a precision
instrument.

An LLM is the high-gain amplifier. Fluency is its gain. Open-loop, it overshoots —
it drifts and hallucinates. **This library is the feedback network you wrap around
it.** The reference isn't a voltage; it's *deterministic code* — graph checks and
schema rules — that the model's output is measured against and corrected toward.

```
                ┌─────────────────────────────────────────────┐
   English ───▶ │   LLM (high gain: fluent, but drifts)        │ ──▶ structured
   text         └─────────────────────────────────────────────┘     output
                          ▲                         │
                          │   re-ask / correct      │  measure against
                          │                         ▼
                ┌─────────────────────────────────────────────┐
                │  deterministic reference (graph + schema)    │
                │  — the feedback network —                    │
                └─────────────────────────────────────────────┘
```

## 3. Negative feedback — stabilise, ground, refuse

In control terms, **negative feedback** pushes the output back *toward* the
reference: it's the stabilising, error-correcting kind. In this library it's the
`run_audit` pipeline, and it has four moving parts.

### 3.1 The regime gate

Before doing anything, decide **what kind of input this is**:

- **finite-structural** — a finite set of discrete steps with transitions between
  them (a workflow, a state machine, a config). This is the kind of thing we can
  analyse *exactly*.
- **model-only** — continuous, probabilistic, or belief-driven prose ("demand
  grows ~3% a month", "confidence rises"). There is no finite state machine here.
- **mixed** — both.

Clear cases are decided by a cheap keyword heuristic; genuinely ambiguous cases
consult the LLM. **Model-only input is refused** — the system will not pretend a
continuous process is a state machine. (This gate is the most heuristic part of
the system and is brittle on deliberately *mixed* inputs; see
[results.md](results.md).)

### 3.2 Extraction with a schema and a fallback

Ask the model for the state machine, but **force the answer into a strict shape**
(`{"states": [...], "transitions": [["FROM","TO"], ...]}`) and validate it. If the
model returns something malformed — or if there is no model at all — fall back to a
**deterministic regex extractor**. This is why the package produces a real result
on a bare `pip install`: the deterministic path always exists.

### 3.3 Exact analysis

Now compute facts that are *provably true of the extracted graph*, with no model
involved:

- **terminal states** (dead ends — steps with no outgoing transition);
- **unreachable states** (steps you can't get to from the start);
- **cycles** (loops in the process).

There is also an **optional** extra check called a *finite-field spectral
fingerprint*. Briefly: treat the transition graph as a matrix, iterate it under
modular arithmetic (mod 2, 3, 5, 7), and look at the repeating pattern ("standing
mode"). If two genuinely different internal configurations would collapse to the
same summary number, the system flags the summary as **non-injective** and refuses
to "lift" it — a guard against hallucinated synthesis. This is mathematically neat
but, honestly, **redundant with plain graph analysis for most workflow audits**.
Keep it for the refusal demo (M3) or ignore it; nothing else depends on it.

### 3.4 The grounded report + refusal

Finally, write the human-readable summary **using only the verified facts**, naming
only states that actually exist. And at every stage where exactness can't be
guaranteed — out-of-regime input, an empty extraction, a non-injective readout —
**refuse** with a reason instead of guessing.

## 4. Positive feedback — fill the gaps, safely

Negative feedback checks *form*, not *completeness*. A one-shot extraction can be
perfectly well-formed and still have silently dropped a branch — the pipeline says
"OK" over an incomplete machine.

**Positive feedback** is the regenerative kind: it amplifies in a direction rather
than correcting toward a reference. Here (`extract_iterative`) it amplifies
*coverage*:

```
   extract (LLM)  ──▶  what does the TEXT mention that the GRAPH lacks?   (deterministic)
       ▲                                   │
       └──── re-ask, "add these missing items" ◀──┘
```

It re-prompts the model with the specific missing states and transitions, takes the
corrected machine, checks again, and repeats — until the graph covers everything
the text mentions (a **fixed point**).

### Why this is the dangerous half — and how it's bounded

Positive feedback is where both **capability and instability** live. Unbounded, a
regenerative loop runs away (it could keep "adding" forever, or oscillate). So it's
clamped by two negative-feedback safeguards:

1. **A deterministic fixed-point test.** The loop stops the instant the graph stops
   changing / covers everything the text mentions. The reference is plain regex
   text↔graph consistency — *no special mathematics*.
2. **A refusal clamp.** If it can't reach a fixed point within a few passes, it
   **refuses** — it reports residual gaps rather than a confident-but-incomplete
   "OK".

## 5. Refusal-as-stabilizer

The single most important idea in this project:

> **Refusal is the stabiliser.** The thing that makes a high-gain generator safe to
> close a loop around is its willingness to say "no" — *this input is out of
> regime*, *this readout is ambiguous*, *I could not converge*. Without that, more
> feedback just means more confident wrongness. With it, the loop is honest.

Negative feedback uses refusal to reject out-of-regime input and non-injective
readouts. Positive feedback uses refusal as the clamp that keeps regeneration from
running away. In both halves, refusal is what converts raw fluency into a precision
instrument.

## 6. What this is and isn't

- It **is** a reliability architecture: a discipline for getting auditable,
  refusable structured output out of a model, especially a *small* one.
- It is **not** a model improvement, a fine-tune, or new mathematics. It adds no
  parameters. The deterministic reference is ordinary graph and string checking.
- It helps on the **structured, verifiable slice** of what LLMs do — workflows,
  state machines, configs — where a deterministic reference exists. Where there's
  nothing to check against, the gate correctly refuses to claim exactness.

## 7. The general engine

Everything in §§3–5 — the gate, the schema-validated extraction, the gap-filling
loop, and the refusal clamp — is general. Two pieces are chosen per target: the
**extraction target** (the shape you want out) and the **deterministic reference**
(the check the loop converges against). The shipped instantiation fills those two in
for state machines; any other target fills them in differently.

Point the engine at a new target by supplying two things:

1. **a target schema** — the shape you want out (fields, records, triples, …);
2. **a deterministic reference** — cheap, model-free code that reports *what is
   missing or wrong* given the text and a candidate answer. The workflow reference
   is "graph coverage of mentioned states" (`consistency_gaps`); a form reference
   is "required fields present + valid + actually found in the source text".

The reference is the crux. It determines whether the loop can converge **and**
whether the engine helps at all: the payoff is large exactly where the reference is
cheap and independent of the model, and the gate refuses where no such reference
exists. The **form-field** target (`extract_form`) is the second one shipped, built
on this same loop (schema + regex detectors for emails, dates, money, phones, custom
patterns): it verifies each extracted value against the source document, recovers a
hallucinated value by reading it back out of the text, and refuses on a genuinely
missing required field — the same three behaviours as the workflow auditor, with a
different reference.

This is realised in code: both targets run on one public engine, `loop.feedback_loop`,
whose extractor and reference are **injectable** (the LLM backend already is, via
`generate=`). A new target is "bring a schema + a reference and call `feedback_loop`",
not a fork.

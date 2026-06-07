[← FAQ](06-faq.md) · [Manual home](../index.md)

# Controllers and circuits

Earlier chapters showed the loop with a *deterministic* controller: the
`reference` is plain code — graph consistency, a field schema — and whatever it
checks, it checks with a guarantee. This chapter is about the other things you
can put in the controller seat, and how to wire several feedback blocks together.
It keeps leaning on the op-amp analogy the rest of the library uses, because the
analogy keeps paying off: the loop does not care *what* sits in the feedback
path, only whether that element is exact or estimated.

Everything here is additive and optional. The deterministic pipeline from the
earlier chapters is unchanged, and all of it still runs with no model at all.

## The controller seat

Recall the loop's shape (see [How it works](02-how-it-works.md)). One callable is
the controller:

```
reference(text, candidate) -> list of gaps        # [] means "satisfied"
```

`run_audit` uses `consistency_gaps`; `extract_form` uses a field schema. Both are
exact. The loop is indifferent to how `reference` is implemented, so you can put
other things there — including a model.

## A low-power model as the critic

A deterministic reference can only check what you can write code for. Plenty of
real problems have a fuzzy quality dimension no rule captures: is the answer
*relevant*, is it *coherent*, did it actually answer the question? For those you
can put a small language model in the controller seat — a **critic**.

```python
from llm_feedback_control import feedback_loop
from llm_feedback_control.critic import llm_critic_reference, llm_critic_repair

reference = llm_critic_reference(generate=my_small_model)   # the controller
repair    = llm_critic_repair(generate=my_small_model)      # how to fix gaps

cand, initial, history, converged = feedback_loop(
    text, extract=my_extract, reference=reference, repair=repair,
    signature=lambda c: tuple(sorted(c.items())))
```

The critic is asked for *specific, checkable problems* with the candidate; an
empty list is its "satisfied", which is the loop's fixed point. If no model is
reachable it raises **no** gaps (it cannot critique, so it does not block) — keep
a deterministic reference alongside it if a missing model must not silently pass.

**This is an estimate, not a guarantee.** A model critic can pass a bad answer
and fail a good one. The loop still terminates only because of `max_iters` and
the refusal clamp, not because the critic is sound. So the rule for the whole
chapter is: **keep at least one exact element in the loop.** Anything that *must*
be right belongs in a deterministic reference; the critic is for breadth on top.

## Summing junction — `combine_references`

To keep the exact floor and add the critic's breadth, sum the two controllers.
The combined reference reports the union of their gaps, so the loop converges
only when **both** are satisfied.

```python
from llm_feedback_control import combine_references

reference = combine_references(exact_reference, llm_critic_reference(my_small_model))
```

This is a summing junction: the exact reference guarantees the hard constraints
and the refusal; the critic adds the fuzzy checks. Put the exact one first.

## Instrumentation amp — `quorum_reference`

A single model critic has a failure mode worth naming: if it shares the
generator's blind spots — above all, if it is the *same model* — it rubber-stamps
the generator's mistakes. A model checking itself is a crowd of one.

The fix is independence, and a circuit for it. Run two or more **independent**
critics (different models) and keep only the gaps a *quorum* of them
independently raise; reject what any single critic raises on its own as noise.

```python
from llm_feedback_control import quorum_reference

reference = quorum_reference(
    llm_critic_reference(model_a),
    llm_critic_reference(model_b),
    quorum=2)            # both must agree before a gap drives a repair
```

That rejection of per-critic idiosyncrasy is the **common-mode rejection** of an
instrumentation amplifier; independence is what makes it real. `combine_references`
is the `quorum=1` extreme (any critic's gap counts); unanimous is `quorum = number
of critics`. The trade-off is explicit and yours: a higher quorum rejects more
noise but can miss a real issue only one critic caught. Gap-matching across
critics ("is this the same complaint, differently worded?") is itself fuzzy; a
crude word-overlap matcher is the default, and you can inject a stronger one via
`similar=`.

## Multi-stage amplifier — `cascade`

When a job has stages — extract, then normalise, then enrich — pipe one
controlled loop's output into the next. Each stage is exact-checked, so error
cannot compound silently down the chain, and a stage that refuses stops the
cascade rather than feeding an untrusted result onward.

```python
from llm_feedback_control import cascade, loop_stage

stage1 = loop_stage(extract=..., reference=..., repair=..., signature=...)
stage2 = loop_stage(extract=..., reference=..., repair=..., signature=...)

final, ok, trace = cascade(stage1, stage2)(source_text)
# ok is False if any stage refused; trace has one record per stage that ran.
```

A "stage" is any callable `stage(input) -> (output, converged)`; `loop_stage`
just wraps a `feedback_loop` as one, so you can also drop in plain functions.

## Comparator with hysteresis — `schmitt_gate`

A routing decision driven by a single threshold *chatters*: a confidence score
hovering at the line flips accept/refuse on every wobble. A Schmitt trigger fixes
that with two thresholds and a dead-band between them — the verdict is sticky.

```python
from llm_feedback_control import schmitt_gate

gate = schmitt_gate(low=0.4, high=0.6)   # flips on >=0.6, back on <=0.4, else holds
route_here = gate(score)                 # stable across borderline scores
```

It flips to `True` only above `high`, back to `False` only below `low`, and holds
its last verdict in between — so a noisy score near the boundary stops oscillating.

**What the clean edge drives.** The real point is less "stop the flicker" than
*what you wire the clean on/off to*. In electronics a Schmitt trigger's clean edge
drives a clock, a flip-flop, a relay, an interrupt — things you must not fire on a
noisy input. The same holds here: a debounced edge is what you safely connect to
something consequential.

- **an irreversible commit** — issue the refund, charge the card, send the email,
  execute the trade, deploy;
- **a latch** — enter a sticky mode (incident mode, escalated, fraud-case) that
  persists until explicitly cleared;
- **a halt** — a circuit-breaker that stops an agent loop or freezes autonomous
  actions until reset;
- **a two-way mode switch** — run autonomously ↔ ask a human; raise ↔ clear an alert.

The hysteresis matters in proportion to the cost and irreversibility of what the
edge drives. A cheap, reversible, read-only decision does not need it; a commit, a
latch, or a halt does.

**One-shot vs two-way — and why a latch is not enough.** For a one-shot
irreversible action a commit-once *latch* (an idempotency key) already stops
duplicates. What a latch cannot fix is committing on a transient blip: it fires
once, but on the *first* crossing, which may be noise. The gate's `high` line
raises that bar — yet a single reading above `high` can still be a spike. For an
action you cannot undo, require the decisive state to **hold** for a couple of
readings: decisive *and sustained*. The gate is the first ingredient, not the
whole recipe.

For a *reversible, two-way* actuator the latch is no help — the system must switch
both directions — and hysteresis is exactly what stops a borderline signal from
chattering the actuator back and forth. That is the cleanest home for a Schmitt
trigger. (The companion book's `08_commit_gate` example simulates both cases from a
latent truth plus seeded noise and reports the effect over thousands of trials.)

**Setting the edge.** The gate also has a manual override, like the set/reset input
of a latch: `gate(force=True)` forces the verdict on, `gate(force=False)` forces it
off, and `gate()` with no argument reads the current verdict. Use it for a human
decision, a hard rule, or an emergency latch — force the gate into "halt" or
"supervised" and the deadband holds it there until a decisive crossing of the other
threshold moves it back.

```python
gate = schmitt_gate(low=0.4, high=0.6)
gate(force=True)     # human/rule override: latch it ON
gate(0.5)            # -> True   (the deadband holds the forced state)
state = gate()       # read without changing it
```

## See it run (no model needed)

Both new modules ship offline, scripted demos — they use a fake `generate`, so
they run on a bare `pip install` with no Ollama and no network:

```bash
python -m llm_feedback_control.critic      # critic loop + the instrumentation amp
python -m llm_feedback_control.circuits    # the cascade + the Schmitt trigger
```

## The one rule to carry away

Every circuit here is worth something only because it keeps an exact element in
the loop. A pure model-only circuit — a critic critiquing a critic with no
deterministic reference and no refusal — is an amplifier with no stable reference
to feed back to: huge gain, and it drifts. The critic and the circuits widen what
the loop can react to; the deterministic reference and the refusal clamp are what
the guarantees still rest on.

[← FAQ](06-faq.md) · [Manual home](../index.md)

# Changelog

## [0.3.1] — 2026-06-07

A small, **backward-compatible** addition to `schmitt_gate`, plus docs. No existing
call changes behaviour.

- **`schmitt_gate` can now be *set***, like the set/reset input of a latch:
  `classify(force=True)` forces the verdict on, `classify(force=False)` off, and
  `classify()` (no argument) reads the current verdict without changing it. After a
  force, the same hysteresis resumes — only a decisive crossing of the other
  threshold moves it back. Use it for a human override, a hard rule, or an emergency
  latch. (The existing `classify(score)` call is unchanged.)
- Manual chapter 07 expanded: **what a clean edge drives** (an irreversible commit,
  a latch, a halt, a two-way mode switch); the **decisive-and-sustained** recipe for
  irreversible commits (a single reading above `high` can still be a spike); and why
  a latch is enough for one-shot actions but only hysteresis works for a reversible,
  two-way actuator.

## [0.3.0] — 2026-06-07

New feature — **the controller seat is now pluggable, and the op-amp paradigm is
made literal.** Fully **backward compatible**: everything is additive, no existing
function changed its signature or behaviour, and the existing test suite passes
unchanged. The deterministic core still runs with no model at all.

- **LLM-as-critic controller** (`llm_critic_reference`, `llm_critic_repair`): a
  low-power model can now sit in the feedback loop's *controller* seat (the
  `reference`), catching fuzzy problems no deterministic rule was written for —
  relevance, coherence, "did it actually answer the question". It is an *estimate*,
  not a guarantee: degrade-safe (no model → no gaps), and meant to be paired with a
  deterministic reference, never to replace it.
- **`combine_references`** — a *summing junction*: combine several controllers so
  the loop converges only when all are satisfied (keep an exact reference as the
  floor and add a critic on top).
- **`quorum_reference`** — an *instrumentation amp*: combine *independent* critics
  by agreement, keeping only what a quorum raise and rejecting each critic's
  idiosyncratic noise (common-mode rejection). Independence — different models — is
  what makes it work.
- **`cascade` / `loop_stage`** — a *multi-stage amplifier*: pipe one controlled
  loop's output into the next, each stage exact-checked; a stage that refuses stops
  the chain (the honest stop propagates).
- **`schmitt_gate`** — a *comparator with hysteresis*: a sticky accept/refuse over a
  stream of scores, with a dead-band so borderline inputs do not chatter.
- New manual chapter, **Controllers and circuits** (`docs/manual/07-controllers-and-circuits.md`),
  and API-reference entries for all of the above. New offline demos
  (`python -m llm_feedback_control.critic`, `... .circuits`) that run with no model.

The design law throughout: **keep at least one exact element in the loop.** The
critic widens reach; the deterministic reference and the refusal clamp are what the
guarantees still rest on.

## [0.2.4] — 2026-06-01

Documentation and source comments only — no behaviour change.

- README documentation links are now absolute GitHub URLs, so they work when
  clicked from the PyPI project page (relative links resolved to nowhere there).
- Thorough docstrings and explanatory comments across the package (notably the
  finite-field engine in `auditor.py`) and the `experiments/` and `aws/` scripts.

## [0.2.3] — 2026-06-01

Documentation only — no code changes.

- README doc-table links repaired after the manual chapters were renumbered
  (worked-examples → 05, faq → 06).
- Manual: readable API headings in Getting started, and a Home/Previous/Next nav
  bar on every chapter page.

## [0.2.2] — 2026-06-01

Documentation only — no code changes.

- README: title is now "LLM Feedback Control"; the tagline is a proper sentence
  ("Get reliable, checkable structured data …").
- Rewrote the manual front page (`docs/index.md`) as prose rather than a link list.

## [0.2.1] — 2026-06-01

Documentation only — no code changes.

- Restructured the docs into a proper **user manual** under `docs/manual/`
  (getting-started, how-it-works, api-reference, results, faq) with the index at
  `docs/index.md`, plus a new **worked-examples** chapter with actual run
  transcripts.
- Slimmed the README to *what the repo does* + links into the manual; moved the
  quickstart, architecture, results, and repo-layout detail into the manual.
- Removed the README "Origin" section.

## [0.2.0] — 2026-06-01

Feature release: a second extraction target and a public, injectable engine.

### Added
- **`extract_form(text, schema)`** — form-field extraction as a first-class target.
  Verifies each value against the source text, recovers detectable values the model
  hallucinated (reads them back out of the document), and refuses on a genuinely
  missing required field rather than inventing one. Field types: `string`, `email`,
  `phone`, `number`, `currency`, `date`, `enum`, `pattern`. Runs with no model
  (regex detectors fill the detectable fields). Helpers `form_field_gaps` and
  `fallback_extract_form` exported too.
- **`feedback_loop(...)`** — the shared engine, now public and injectable. Supply
  `extract` / `reference` / `repair` / `signature` (+ optional `finalize`) and the
  loop owns the bounded positive feedback, fixed-point test, and refusal clamp.

### Changed
- `extract_iterative` (workflows) is refactored onto `feedback_loop` — same public
  signature, return shape, and history format. "One engine, two targets" is now
  literally true in the code, not just the docs.

## [0.1.3] — 2026-06-01

Documentation only — no code changes.

- Reframed the docs **general-first**: lead with what the engine does (verify
  against a deterministic reference / fill gaps / refuse), with extraction
  **targets as peers** — workflow is the first one shipped; form fields, records,
  and entities are others the same loop handles. Supersedes the 0.1.2 framing,
  which still centred workflows and bolted generality on as an afterthought.
- Stopped trivialising the deterministic reference — it's the substantive
  component, not "a bit of code". Positive phrasing throughout.

## [0.1.2] — 2026-06-01

Documentation only — no code changes.

- Reframed the README and docs to lead with the **general engine** (reliable
  structured extraction from free text) rather than only workflow auditing, which
  is now presented as the shipped *worked instantiation*. The earlier framing
  undersold the architecture's generality.
- New "Extending to other targets" section (README) and "Generalising beyond
  workflows" (`docs/architecture.md` §7): a new target = a schema + a deterministic
  reference; the LLM backend is already injectable. Cites a form-field
  instantiation built on the same loop (verify-against-source, recover hallucinated
  values, refuse on missing required fields) as evidence the engine generalises.

## [0.1.1] — 2026-06-01

Documentation / packaging only — no code changes.

- README rewritten to be human-readable and goal-oriented: a plain-language
  "The problem this solves" opening (no prior LLM context assumed) and a concrete
  "Use it to:" outcomes list, so the PyPI page reads as *what you can achieve*
  rather than how it works internally.
- Moved `CHANGELOG.md` into `docs/` and fixed the project Changelog URL.
- Removed the redundant `requirements.txt` (the core has zero dependencies;
  `pyproject.toml` is the single source of truth).

## [0.1.0] — 2026-06-01

First public release.

### Added
- **Negative-feedback pipeline** (`run_audit`): regime gate → finite-state
  extraction (schema-validated, with a deterministic regex fallback) → exact
  graph analysis (terminals, unreachable states, cycles) + an optional
  finite-field spectral fingerprint → grounded report with explicit refusals.
- **Bounded positive-feedback loop** (`extract_iterative`): regenerative
  re-extraction to a text↔graph fixed point, clamped by a deterministic
  consistency reference and a refusal-on-non-convergence.
- **Injectable backend**: every entry point takes a `generate=` callable, so the
  library is not tied to Ollama (use OpenAI, Anthropic, a local server, or any
  `f(prompt, fmt=None) -> str`). The default is a stdlib-only Ollama client.
- **Runs with no model at all**: the deterministic path (regex extraction +
  exact analysis) returns a real result on a bare `pip install`.
- **CLI**: `lfc "<text>"`, `lfc --check` (backend doctor), `lfc --demo`,
  `lfc --json`, also reachable as `python -m llm_feedback_control`.
- **Zero third-party runtime dependencies** (pure standard library).
- Experiments (repo-only, not shipped in the wheel): `prototype_test.py`,
  `quality_uplift.py`, `hard_corpus.py`, plus optional EC2 ceiling-model tooling
  under `aws/`.

### Measured (indicative — small corpora)
- Small model (phi3:mini, 3.8B) + the feedback loop reaches a ~28 GB ceiling
  model (mixtral:8x7b) on a messy workflow-extraction corpus: states F1
  0.98→1.00 (100% of the gap), transitions F1 0.89→0.90 (77% of the gap).

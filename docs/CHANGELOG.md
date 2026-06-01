# Changelog

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

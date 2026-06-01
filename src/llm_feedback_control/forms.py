"""Form-field extraction — the second target built on the shared loop (``loop.py``).

Same engine as the workflow auditor, different reference. The reference here is a
**field schema + independent regex detectors**: required fields must be present,
present values must validate against their type/enum/pattern, and — the part
constrained-decoding libraries and cloud OCR do not do — values are **verified
against the source text**. When the model hallucinates or drops a detectable field,
the detector **recovers** it straight from the document; when a required field is
genuinely absent, the loop **refuses** rather than inventing one.

Schema format::

    {"fields": [
        {"name": "email",  "type": "email",   "required": True},
        {"name": "amount", "type": "currency", "required": True},
        {"name": "kind",   "type": "enum", "required": True, "values": ["a", "b"]},
        {"name": "ref",    "type": "pattern", "required": True, "pattern": r"[A-Z]{2}-\\d{6}"},
        ...
    ]}

Supported types: string, email, phone, number, currency, date, enum, pattern.

Runs with no model at all: the detectors deterministically pre-fill what they can.
The LLM backend is injectable via ``generate=``.
"""
import re
import json
import copy

from .llm import gen
from .loop import feedback_loop


# ── type system: validators + independent text detectors ──────────────────
EMAIL_RE = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
PHONE_RE = r"\+?\d[\d\-\s().]{6,}\d"
MONEY_RE = r"[$£€]\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*\.\d{2}\b"
_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
DATE_RE = (r"\b(?:\d{4}-\d{2}-\d{2}"
           r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
           rf"|{_MONTHS}\s+\d{{1,2}},?\s+\d{{4}}"
           rf"|\d{{1,2}}\s+{_MONTHS}\s+\d{{4}})\b")

DETECTABLE = {"email", "phone", "currency", "date", "pattern"}
# types whose extracted value can be cross-checked against the text without
# format-normalisation headaches (dates excluded: word vs numeric months).
STRICT_XCHECK = {"email", "phone", "currency", "pattern"}


def _find(rx, text):
    return [m.group(0).strip() for m in re.finditer(rx, text)]


def detect(ftype, text, field=None):
    """Independent deterministic detector: typed values present in the text."""
    if ftype == "email":    return _find(EMAIL_RE, text)
    if ftype == "phone":    return _find(PHONE_RE, text)
    if ftype == "currency": return _find(MONEY_RE, text)
    if ftype == "date":     return _find(DATE_RE, text)
    if ftype == "pattern" and field and field.get("pattern"):
        return _find(field["pattern"], text)
    return []


def _money_val(v):
    """Parse the first numeric value out of a currency/number string (commas
    stripped), or None if there isn't one. Lets "$1,200.00", "1200" and "1,200"
    compare equal."""
    m = re.findall(r"\d[\d,]*(?:\.\d+)?", str(v))
    return float(m[0].replace(",", "")) if m else None


def validate(value, field):
    """(ok, reason) — does `value` satisfy this field's type?"""
    if value in (None, "", [], {}):
        return False, "empty"
    s = str(value).strip()
    t = field["type"]
    if t == "string":   return (len(s) > 0, "empty")
    if t == "email":    return (re.fullmatch(EMAIL_RE, s) is not None, "not an email")
    if t == "phone":    return (len(re.sub(r"\D", "", s)) >= 7, "not a phone number")
    if t == "number":   return (_money_val(s) is not None, "not a number")
    if t == "currency": return (_money_val(s) is not None, "not a currency amount")
    if t == "date":     return (re.search(DATE_RE, s) is not None, "not a date")
    if t == "pattern":  return (re.search(field["pattern"], s) is not None,
                                f"does not match {field['pattern']}")
    if t == "enum":
        return (s.lower() in [a.lower() for a in field["values"]],
                f"not one of {field['values']}")
    return True, ""


def _match(ftype, a, b):
    """Type-aware: does value `a` correspond to detected token `b`?"""
    if ftype in ("currency", "number"):
        return _money_val(a) == _money_val(b)
    if ftype == "phone":
        return re.sub(r"\D", "", str(a)) == re.sub(r"\D", "", str(b))
    return re.sub(r"\s+", "", str(a)).lower() == re.sub(r"\s+", "", str(b)).lower()


# ── the deterministic reference: what's missing / wrong? ───────────────────
def field_gaps(text, schema, record):
    """The reference the loop converges to: a list of {field, problem, hint} the
    record fails against the schema AND the source text. Empty list == done."""
    gaps = []
    for f in schema["fields"]:
        name = f["name"]
        val = record.get(name)
        present = val not in (None, "", [], {})
        if not present:
            if f.get("required"):
                hint = ""
                if f["type"] in DETECTABLE:
                    found = detect(f["type"], text, f)
                    hint = (f"the text contains: {found[0]}" if found
                            else "no value of this type is present in the text")
                gaps.append({"field": name, "problem": "missing_required", "hint": hint})
            continue
        ok, reason = validate(val, f)
        if not ok:
            found = detect(f["type"], text, f) if f["type"] in DETECTABLE else []
            hint = f"the text contains: {found[0]}" if found else ""
            gaps.append({"field": name, "problem": f"invalid ({reason}), got {val!r}",
                         "hint": hint})
            continue
        # well-formed BUT does it actually appear in the source? (catches a
        # plausible-looking hallucination / silently altered value)
        if f["type"] in STRICT_XCHECK:
            found = detect(f["type"], text, f)
            if found and not any(_match(f["type"], val, tok) for tok in found):
                gaps.append({"field": name,
                             "problem": f"value {val!r} not found in source text",
                             "hint": f"the text contains: {found[0]}"})
    return gaps


# ── extraction (LLM, schema-shaped) + deterministic fallback ───────────────
def _schema_line(schema):
    """Render the field specs as a one-line hint embedded in the extraction prompt."""
    out = []
    for f in schema["fields"]:
        spec = f["type"]
        if f["type"] == "enum":
            spec += " one of " + str(f["values"])
        if f["type"] == "pattern":
            spec += f" matching {f['pattern']}"
        out.append(f'"{f["name"]}" ({spec}{", required" if f.get("required") else ""})')
    return "; ".join(out)


def _coerce(obj, schema):
    """Coerce raw model JSON down to exactly the schema's keys, mapping missing or
    empty values to None. Returns None if the model didn't return an object at all."""
    if not isinstance(obj, dict):
        return None
    return {f["name"]: (obj.get(f["name"]) if obj.get(f["name"]) not in ("", []) else None)
            for f in schema["fields"]}


def fallback_extract_form(text, schema):
    """No-model baseline: detectors fill what they deterministically can."""
    rec = {f["name"]: None for f in schema["fields"]}
    for f in schema["fields"]:
        if f["type"] in DETECTABLE:
            found = detect(f["type"], text, f)
            if found:
                rec[f["name"]] = found[0]
    return rec


def _snap_detectable(text, schema, record):
    """Deterministic last resort: for robustly-detectable fields the LLM left
    unfilled, invalid, or hallucinated, fill straight from the source via the
    detector. The reference doubles as an extractor — it RECOVERS, not just flags.
    (Takes the first detected token; ambiguous when a type appears more than once.)"""
    rec = dict(record)
    for f in schema["fields"]:
        if f["type"] not in STRICT_XCHECK:
            continue
        found = detect(f["type"], text, f)
        if not found:
            continue
        val = rec.get(f["name"])
        ok = val not in (None, "") and any(_match(f["type"], val, t) for t in found)
        if not ok:
            rec[f["name"]] = found[0]
    return rec


def _norm_record(rec):
    """Canonical form of a record for stall detection: sorted items with
    whitespace collapsed and lower-cased, so cosmetic re-formatting doesn't read
    as a change between loop iterations."""
    return tuple(sorted((k, re.sub(r"\s+", " ", str(v)).strip().lower())
                        for k, v in rec.items()))


# ── public API ─────────────────────────────────────────────────────────────
def extract_form(text, schema, generate=None, max_iters=4, verbose=False):
    """Extract form fields from free text, verified against a schema + the source.

    Returns a dict:
      - ``record``     : {field: value}
      - ``result``     : "OK" or "REFUSED: could not fill/validate required fields: ..."
      - ``converged``  : True iff every required field is filled and valid
      - ``iterations`` : feedback passes run
      - ``gaps``       : remaining {field, problem, hint} items

    Works with no model (detectors fill what they can); pass ``generate`` for a
    specific LLM backend."""
    g = generate or gen
    keys = [f["name"] for f in schema["fields"]]

    def extract(t):
        prompt = (f'Extract these fields from the text and return ONLY a JSON object '
                  f'with exactly these keys: {keys}. Field specs: {_schema_line(schema)}. '
                  f'Use the exact values from the text; use null if a field is genuinely '
                  f'absent — do not guess. Text: "{t}"')
        try:
            rec = _coerce(json.loads(g(prompt, fmt="json")), schema)
        except Exception:
            rec = None
        return rec if rec is not None else fallback_extract_form(t, schema)

    def reference(t, record):
        return field_gaps(t, schema, record)

    def repair(t, record, gaps):
        problems = "\n".join(
            f'- field "{x["field"]}": {x["problem"]}.'
            + (f' Hint: {x["hint"]}.' if x["hint"] else "")
            for x in gaps)
        prompt = (f'You extracted this form data (JSON): {json.dumps(record)}\n'
                  f'A deterministic checker found these problems:\n{problems}\n'
                  f'Return the COMPLETE corrected JSON object with exactly these keys: '
                  f'{keys}, fixing the problems using values from the source text. Use '
                  f'null only if a value is truly absent — never invent one. '
                  f'Source text: "{t}"')
        try:
            return _coerce(json.loads(g(prompt, fmt="json")), schema)
        except Exception:
            return None

    record, initial, history, converged = feedback_loop(
        text, extract=extract, reference=reference, repair=repair,
        signature=_norm_record,
        finalize=lambda t, r: _snap_detectable(t, schema, r),
        max_iters=max_iters, verbose=verbose, label="form")

    gaps = field_gaps(text, schema, record)
    blocking = sorted({x["field"] for x in gaps})
    status = ("OK" if converged else
              "REFUSED: could not fill/validate required fields: " + ", ".join(blocking))
    return {"record": record, "result": status, "converged": converged,
            "iterations": len(history), "gaps": gaps, "initial": initial}

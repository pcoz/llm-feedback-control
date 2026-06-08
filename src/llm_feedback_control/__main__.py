"""Command-line entry point:  python -m llm_feedback_control  /  lfc

  lfc "A claim enters Intake. From Intake it goes to Triage."   # audit text
  lfc --check                                                   # backend doctor
  lfc --demo                                                    # M1/M2/M3 demos
  lfc --form --schema schema.json "..."                         # form extraction
  lfc --form --schema '{"fields":...}' "..."                    # form (inline schema)
  lfc                                                           # quick sample run

The audit runs with no model at all (deterministic regex extraction + exact
graph analysis); if an LLM backend is reachable it is used automatically and
the extraction quality goes up. Run ``lfc --check`` to see what's available.

Form extraction (``--form --schema``) also runs with no model: the regex
detectors fill email, phone, currency, date and custom-pattern fields
deterministically; a reachable LLM upgrades quality on string and enum fields.
"""
import argparse
import json
import os
import sys

from . import __version__, run_audit, doctor, info, extract_form

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SAMPLE = ("A claim enters Intake. From Intake it goes to Triage. Triage goes to "
          "FastTrack or to Investigation. FastTrack goes to Payout. Investigation "
          "goes to Payout or to Denied. Payout goes to Closed. Denied goes to Closed.")

SAMPLE_FORM_TEXT = ("Jane Doe, policy AB-123456, reach me at jane@x.com, "
                    "total $200, this is a fire claim.")
SAMPLE_FORM_SCHEMA = {"fields": [
    {"name": "name",   "type": "string",  "required": True},
    {"name": "ref",    "type": "pattern", "required": True, "pattern": r"[A-Z]{2}-\d{6}"},
    {"name": "email",  "type": "email",   "required": True},
    {"name": "amount", "type": "currency","required": True},
    {"name": "kind",   "type": "enum",    "required": True,
     "values": ["fire", "theft", "collision"]},
]}


def _print_audit(r):
    """Pretty-print a `run_audit` result dict for the terminal."""
    print("gate      :", r["gate"]["verdict"], "|", r["gate"]["reason"])
    if "extraction" in r:
        ex = r["extraction"]
        print(f"extracted : via={ex['via']}  states={ex['states']}")
        print(f"            transitions={ex['transitions']}")
    if "report_facts" in r:
        print("facts     :")
        for line in r["report_facts"].rstrip().splitlines():
            print("   " + line)
    if r.get("report_english"):
        print("grounded  :", r["report_english"][:400])
    print("result    :", r["result"])


def _print_doctor():
    """Print the backend doctor report — what's reachable and what to do next."""
    d = doctor()
    print("llm-feedback-control doctor")
    print("  config :", info())
    if d["ollama_reachable"]:
        print(f"  ollama : reachable at {d['ollama_host']}")
        print(f"  models : {', '.join(d['models_available']) or '(none pulled)'}")
        if d["small_model_present"]:
            print(f"  -> small model '{d['small_model']}' is present. Full LLM path enabled.")
        else:
            print(f"  -> small model '{d['small_model']}' NOT pulled. Run:  "
                  f"ollama pull {d['small_model']}")
    else:
        print(f"  ollama : NOT reachable at {d['ollama_host']}")
        print("  -> The deterministic pipeline still works (regex extraction + exact")
        print("     graph analysis). For the full LLM path, install Ollama")
        print("     (https://ollama.com) and `ollama pull {}`,".format(d["small_model"]))
        print("     or set CEILING_BACKEND=openai with OPENAI_API_KEY.")
    if d["ceiling_backend"] == "openai":
        print("  openai :", "OPENAI_API_KEY set" if d["openai_key_set"] else "OPENAI_API_KEY MISSING")


def _looks_like_path(s):
    """Heuristic: does the string look like a file path rather than inline JSON?"""
    return any(c in s for c in ("/", "\\")) or s.lower().endswith(".json")


def _load_schema(raw):
    """Load a schema from ``raw``, which may be a file path, ``@file``, or inline JSON."""
    path = None
    if raw.startswith("@"):
        path = raw[1:]
    elif os.path.isfile(raw):
        path = raw
    elif _looks_like_path(raw):
        raise FileNotFoundError(2, "No such file or directory", raw)
    if path is not None:
        try:
            with open(path, encoding="utf-8") as f:
                schema = json.load(f)
        except OSError as e:
            raise OSError(f"cannot read schema file {path!r}: {e}") from e
    else:
        schema = json.loads(raw)
    if not isinstance(schema, dict) or "fields" not in schema:
        raise ValueError("schema must be a JSON object with a 'fields' list")
    if not isinstance(schema["fields"], list):
        raise ValueError("'fields' must be a list")
    seen = set()
    for f in schema["fields"]:
        if not isinstance(f, dict) or "name" not in f or "type" not in f:
            raise ValueError("each field must have 'name' and 'type'")
        if f["name"] in seen:
            raise ValueError(f"duplicate field name: {f['name']}")
        seen.add(f["name"])
    return schema


def _print_form(r):
    """Pretty-print an ``extract_form`` result dict for the terminal."""
    print("result    :", r["result"])
    print("converged :", r["converged"])
    print("iterations:", r["iterations"])
    print("record    :")
    for k, v in r["record"].items():
        print(f"   {k}: {v}")
    if r["gaps"]:
        print("gaps:")
        for g in r["gaps"]:
            print(f"   {g['field']}: {g['problem']}")
            if g.get("hint"):
                print(f"      hint: {g['hint']}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="lfc",
        description="LLM feedback control: audit a process description into an "
                    "exact, grounded, refusable report, or extract form fields "
                    "against a schema.")
    ap.add_argument("text", nargs="?", help="process description to audit "
                    "(omit to run a built-in sample)")
    ap.add_argument("--check", action="store_true", help="probe the LLM backend and exit")
    ap.add_argument("--demo", action="store_true", help="run the M1/M2/M3 demos and exit")
    ap.add_argument("--json", action="store_true", help="print the raw result dict as JSON")
    ap.add_argument("--version", action="version", version=f"llm-feedback-control {__version__}")
    ap.add_argument("--form", action="store_true",
                    help="extract form fields instead of auditing a workflow. Requires --schema.")
    ap.add_argument("--schema",
                    help="form field schema: a JSON file path, @file, or inline JSON string.")
    args = ap.parse_args(argv)

    if args.check:
        _print_doctor()
        return 0
    if args.demo:
        from .auditor import main as demo_main
        demo_main()
        return 0

    if args.form:
        if not args.schema:
            schema = SAMPLE_FORM_SCHEMA
            if not args.text:
                print("(no schema or text given — using a built-in form sample)\n")
        else:
            try:
                schema = _load_schema(args.schema)
            except (json.JSONDecodeError, ValueError, OSError) as e:
                print(f"error: invalid schema: {e}")
                return 1
            if not args.text:
                print("(no text given — using a built-in form sample; pass your own as an argument)\n")
        text = args.text or SAMPLE_FORM_TEXT
        r = extract_form(text, schema)
        if args.json:
            print(json.dumps(r, indent=2))
        else:
            _print_form(r)
        return 0

    text = args.text or SAMPLE
    if not args.text:
        print(f"(no text given — auditing a built-in sample; pass your own as an argument)\n")
    r = run_audit(text)
    if args.json:
        print(json.dumps(r, indent=2))
    else:
        _print_audit(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

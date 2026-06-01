"""Command-line entry point:  python -m llm_feedback_control  /  lfc

  lfc "A claim enters Intake. From Intake it goes to Triage."   # audit text
  lfc --check                                                   # backend doctor
  lfc --demo                                                    # M1/M2/M3 demos
  lfc                                                           # quick sample run

The audit runs with no model at all (deterministic regex extraction + exact
graph analysis); if an LLM backend is reachable it is used automatically and
the extraction quality goes up. Run ``lfc --check`` to see what's available.
"""
import argparse
import json
import sys

from . import __version__, run_audit, doctor, info

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SAMPLE = ("A claim enters Intake. From Intake it goes to Triage. Triage goes to "
          "FastTrack or to Investigation. FastTrack goes to Payout. Investigation "
          "goes to Payout or to Denied. Payout goes to Closed. Denied goes to Closed.")


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


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="lfc",
        description="LLM feedback control: audit a process description into an "
                    "exact, grounded, refusable report.")
    ap.add_argument("text", nargs="?", help="process description to audit "
                    "(omit to run a built-in sample)")
    ap.add_argument("--check", action="store_true", help="probe the LLM backend and exit")
    ap.add_argument("--demo", action="store_true", help="run the M1/M2/M3 demos and exit")
    ap.add_argument("--json", action="store_true", help="print the raw audit dict as JSON")
    ap.add_argument("--version", action="version", version=f"llm-feedback-control {__version__}")
    args = ap.parse_args(argv)

    if args.check:
        _print_doctor()
        return 0
    if args.demo:
        from .auditor import main as demo_main
        demo_main()
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

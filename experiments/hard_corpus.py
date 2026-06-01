"""hard_corpus.py — does feedback control let a SMALL model reach a BIG one?

The headline thesis, measured on a HARD (messy/branchy/distractor-laden)
workflow-extraction corpus. Three configurations:

  small-open    : small model (LFC_MODEL, e.g. phi3:mini), one-shot
  small-closed  : same small model + the bounded positive-feedback loop
  ceiling       : a stronger reference model (LFC_CEILING, e.g. llama3.1:8b,
                  or OpenAI via CEILING_BACKEND=openai), one-shot

Metric: states & transitions F1 vs ground truth, and the headline number —
the % of the (ceiling - small_open) quality gap that the loop recovers.

This is the experiment worth running on a box where the bigger model is fast
(a modest GPU / large-RAM instance). Everything is configurable by env var
(see llm.py); no code changes between laptop and EC2.

Run:  python hard_corpus.py
"""
import sys, json, time, statistics as st
import llm_feedback_control as llm
from llm_feedback_control import extract_iterative, norm, valid, fallback_extract

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# messy prose: passive voice, synonyms (routed/sent/escalates/falls back/reverts),
# co-reference, and distractor sentences — but state names still appear after
# to/enters/at so a deterministic reference can still find candidates.
CORPUS = [
    dict(text="Every incoming claim is first logged into Intake. From Intake an "
              "adjuster routes it to Triage. Triage either fast-tracks it to FastTrack "
              "or, when the amount is large, sends it to Investigation. (All timestamps "
              "are UTC.) FastTrack proceeds to Payout. Investigation, after review, "
              "either advances to Payout or is denied and moves to Denied. Both Payout "
              "and Denied eventually transition to Closed.",
         states=["Intake", "Triage", "FastTrack", "Investigation", "Payout", "Denied", "Closed"],
         trans=[("Intake", "Triage"), ("Triage", "FastTrack"), ("Triage", "Investigation"),
                ("FastTrack", "Payout"), ("Investigation", "Payout"),
                ("Investigation", "Denied"), ("Payout", "Closed"), ("Denied", "Closed")]),
    dict(text="A commit lands in Queued. The runner picks it up and starts Compiling. "
              "If compilation succeeds it goes to Testing, otherwise to Failed. Testing, "
              "if green, is promoted to Deploying; if red, back to Failed. Deploying "
              "releases to Live. Failed sends the commit back to Queued for a retry. "
              "(This pipeline is owned by Platform Eng.)",
         states=["Queued", "Compiling", "Testing", "Deploying", "Live", "Failed"],
         trans=[("Queued", "Compiling"), ("Compiling", "Testing"), ("Compiling", "Failed"),
                ("Testing", "Deploying"), ("Testing", "Failed"), ("Deploying", "Live"),
                ("Failed", "Queued")]),
    dict(text="When a customer writes in, a ticket is created in New. An agent moves it "
              "to Triaged. From Triaged it is either resolved directly to Resolved, or "
              "escalated to Tier2. Tier2 may resolve it to Resolved or escalate further "
              "to Tier3. Tier3 always ends at Resolved. Resolved is archived to Closed.",
         states=["New", "Triaged", "Tier2", "Tier3", "Resolved", "Closed"],
         trans=[("New", "Triaged"), ("Triaged", "Resolved"), ("Triaged", "Tier2"),
                ("Tier2", "Resolved"), ("Tier2", "Tier3"), ("Tier3", "Resolved"),
                ("Resolved", "Closed")]),
    dict(text="Orders begin at Placed. Payment processing takes them to Paid, unless the "
              "card declines, in which case they fall back to Placed. Paid orders go to "
              "Fulfillment. From Fulfillment an order ships to Shipped or, if stock is "
              "missing, is cancelled to Cancelled. Shipped goes to Delivered. (Fraud "
              "checks run asynchronously and are out of scope.)",
         states=["Placed", "Paid", "Fulfillment", "Shipped", "Cancelled", "Delivered"],
         trans=[("Placed", "Paid"), ("Paid", "Placed"), ("Paid", "Fulfillment"),
                ("Fulfillment", "Shipped"), ("Fulfillment", "Cancelled"),
                ("Shipped", "Delivered")]),
    dict(text="A new-hire record starts in Created. HR advances it to Documentation. "
              "Once documents are verified, Documentation proceeds to ITSetup. ITSetup "
              "goes to Training, but if a security check fails it reverts to Documentation. "
              "Training completes to Active. (Managers are emailed at each step.)",
         states=["Created", "Documentation", "ITSetup", "Training", "Active"],
         trans=[("Created", "Documentation"), ("Documentation", "ITSetup"),
                ("ITSetup", "Training"), ("ITSetup", "Documentation"), ("Training", "Active")]),
]

EXTRACT = ('Extract the finite state machine. Return ONLY JSON '
           '{{"states":[...],"transitions":[["FROM","TO"],...]}} using exact state '
           'names from the text. Text: "{text}"')


def f1(states, trans, truth):
    """Return (states-F1, transitions-F1) of an extraction vs ground truth, name-normalised."""
    es = {norm(s) for s in states}; ts = {norm(s) for s in truth["states"]}
    et = {(norm(a), norm(b)) for a, b in trans}
    tt = {(norm(a), norm(b)) for a, b in truth["trans"]}
    def F(E, T):
        if not E and not T: return 1.0
        p = len(E & T) / len(E) if E else 0.0
        r = len(E & T) / len(T) if T else 0.0
        return 2 * p * r / (p + r) if (p + r) else 0.0
    return F(es, ts), F(et, tt)


def ceiling_extract(text):
    """Extract the FSM with the strong ceiling model, falling back to the deterministic parser."""
    try:
        o = json.loads(llm.gen_ceiling(EXTRACT.format(text=text), fmt="json"))
        if valid(o) and o.get("states"):
            return o
    except Exception:
        pass
    return fallback_extract(text)


def main():
    """Run open/closed/ceiling extraction over the hard corpus; print per-row F1 and the
    headline % of the small->ceiling gap that the feedback loop recovers."""
    print("=" * 80)
    print("HARD-CORPUS QUALITY UPLIFT —", llm.info())
    print("=" * 80)
    print(f"{'workflow':<11}{'open sF1':>9}{'open tF1':>9}{'clo sF1':>9}{'clo tF1':>9}"
          f"{'ceil sF1':>9}{'ceil tF1':>9}{'it':>4}")
    print("-" * 80)
    rows = []
    for d in CORPUS:
        final, initial, hist, conv = extract_iterative(d["text"], verbose=False)
        o_s, o_t = f1(initial["states"], initial["transitions"], d)
        c_s, c_t = f1(final["states"], final["transitions"], d)
        cg = ceiling_extract(d["text"])
        g_s, g_t = f1(cg["states"], cg["transitions"], d)
        rows.append((o_s, o_t, c_s, c_t, g_s, g_t, len(hist)))
        print(f"{d['states'][0][:10]:<11}{o_s:>9.2f}{o_t:>9.2f}{c_s:>9.2f}{c_t:>9.2f}"
              f"{g_s:>9.2f}{g_t:>9.2f}{len(hist):>4}")
    m = lambda i: st.mean(r[i] for r in rows)
    print("-" * 80)
    print(f"{'MEAN':<11}{m(0):>9.2f}{m(1):>9.2f}{m(2):>9.2f}{m(3):>9.2f}{m(4):>9.2f}{m(5):>9.2f}")

    def gap_recovered(open_, closed, ceil):
        return (closed - open_) / (ceil - open_) if (ceil - open_) > 1e-9 else float("nan")
    gs = gap_recovered(m(0), m(2), m(4))
    gt = gap_recovered(m(1), m(3), m(5))
    print("\n" + "=" * 80); print("HEADLINE"); print("=" * 80)
    print(f"  small open   : states {m(0):.2f}  transitions {m(1):.2f}")
    print(f"  small CLOSED : states {m(2):.2f}  transitions {m(3):.2f}")
    print(f"  big ceiling  : states {m(4):.2f}  transitions {m(5):.2f}")
    print(f"\n  gap to ceiling recovered by the loop:  states {gs*100:.0f}%  transitions {gt*100:.0f}%")
    print("\n  Interpretation: how much of the small->big quality gap the feedback")
    print("  loop closes, at the cost of extra passes (no extra parameters). The")
    print("  reference is plain text<->graph consistency — no special mathematics.")


if __name__ == "__main__":
    main()

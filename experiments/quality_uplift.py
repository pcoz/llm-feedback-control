"""quality_uplift.py — THE thesis, measured: can closing the loop get higher-
quality output from a SMALL model (trading passes for accuracy)?

Compares, on a ground-truthed workflow-extraction corpus, the SAME small model
(phi3:mini) in two configurations:
    OPEN-LOOP   : one-shot extraction (the usual way)
    CLOSED-LOOP : feedback re-extraction, bounded by deterministic text<->graph
                  consistency + a refusal clamp  (feedback.extract_iterative)

Metric: states & transitions F1 vs ground truth. The thesis is supported iff
CLOSED-LOOP F1 > OPEN-LOOP F1 (the loop upgrades the small model's output).
'Regardless of speed loss' — we report extra passes, not latency.

The reference uses NO special mathematics (plain regex consistency), so this tests
"LLM feedback control as a substitute for scale", standalone.

Requires: Ollama (phi3:mini).  Run:  python quality_uplift.py
"""
import sys, statistics as st
from llm_feedback_control import extract_iterative, norm

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# corpus: workflows with branches a small model tends to drop one-shot
CORPUS = [
    dict(text="A customer order enters Review. If approved it goes to Packing. If "
              "rejected it goes to Refund. Packing goes to Shipped. Shipped goes to "
              "Closed. Refund goes to Closed.",
         states=["Review", "Packing", "Refund", "Shipped", "Closed"],
         trans=[("Review", "Packing"), ("Review", "Refund"), ("Packing", "Shipped"),
                ("Shipped", "Closed"), ("Refund", "Closed")]),
    dict(text="A request enters Draft. Draft goes to Submitted. Submitted goes to "
              "Approved or to Rejected. Approved goes to Archived. Rejected goes to "
              "Archived.",
         states=["Draft", "Submitted", "Approved", "Rejected", "Archived"],
         trans=[("Draft", "Submitted"), ("Submitted", "Approved"),
                ("Submitted", "Rejected"), ("Approved", "Archived"),
                ("Rejected", "Archived")]),
    dict(text="A claim enters Intake. Intake goes to Triage. Triage goes to "
              "FastTrack or to Investigation. FastTrack goes to Payout. Investigation "
              "goes to Payout or to Denied. Payout goes to Closed. Denied goes to Closed.",
         states=["Intake", "Triage", "FastTrack", "Investigation", "Payout", "Denied", "Closed"],
         trans=[("Intake", "Triage"), ("Triage", "FastTrack"), ("Triage", "Investigation"),
                ("FastTrack", "Payout"), ("Investigation", "Payout"),
                ("Investigation", "Denied"), ("Payout", "Closed"), ("Denied", "Closed")]),
    dict(text="A build starts in Queued. Queued goes to Compiling. Compiling goes to "
              "Testing or to Failed. Testing goes to Deploying or to Failed. Deploying "
              "goes to Live. Failed goes to Queued.",
         states=["Queued", "Compiling", "Testing", "Deploying", "Live", "Failed"],
         trans=[("Queued", "Compiling"), ("Compiling", "Testing"), ("Compiling", "Failed"),
                ("Testing", "Deploying"), ("Testing", "Failed"), ("Deploying", "Live"),
                ("Failed", "Queued")]),
    dict(text="A call enters Greeting. Greeting goes to Menu. Menu goes to Sales or to "
              "Support or to Voicemail. Sales goes to Hangup. Support goes to Hangup. "
              "Voicemail goes to Hangup.",
         states=["Greeting", "Menu", "Sales", "Support", "Voicemail", "Hangup"],
         trans=[("Greeting", "Menu"), ("Menu", "Sales"), ("Menu", "Support"),
                ("Menu", "Voicemail"), ("Sales", "Hangup"), ("Support", "Hangup"),
                ("Voicemail", "Hangup")]),
]


def f1(extracted_states, extracted_trans, truth):
    """Return (states-F1, transitions-F1) of an extraction vs ground truth, name-normalised."""
    es = {norm(s) for s in extracted_states}
    ts = {norm(s) for s in truth["states"]}
    et = {(norm(a), norm(b)) for a, b in extracted_trans}
    tt = {(norm(a), norm(b)) for a, b in truth["trans"]}
    def F(E, T):
        if not E and not T: return 1.0
        p = len(E & T) / len(E) if E else 0.0
        r = len(E & T) / len(T) if T else 0.0
        return 2 * p * r / (p + r) if (p + r) else 0.0
    return F(es, ts), F(et, tt)


def main():
    """Compare open-loop vs closed-loop extraction F1 over the corpus and print the supported/not verdict."""
    print("=" * 74)
    print("QUALITY UPLIFT — small model open-loop vs closed-loop (F1 vs ground truth)")
    print("=" * 74)
    print(f"{'workflow':<12}{'open sF1':>9}{'open tF1':>9}{'clo sF1':>9}{'clo tF1':>9}{'iters':>7}{'conv':>6}")
    print("-" * 74)
    rows = []
    for d in CORPUS:
        final, initial, history, conv = extract_iterative(d["text"], verbose=False)
        o_sf, o_tf = f1(initial["states"], initial["transitions"], d)
        c_sf, c_tf = f1(final["states"], final["transitions"], d)
        rows.append((o_sf, o_tf, c_sf, c_tf, len(history), conv))
        name = d["states"][0][:11]
        print(f"{name:<12}{o_sf:>9.2f}{o_tf:>9.2f}{c_sf:>9.2f}{c_tf:>9.2f}{len(history):>7}{str(conv):>6}")
    m = lambda i: st.mean(r[i] for r in rows)
    print("-" * 74)
    print(f"{'MEAN':<12}{m(0):>9.2f}{m(1):>9.2f}{m(2):>9.2f}{m(3):>9.2f}")
    conv_n = sum(1 for r in rows if r[5])
    print(f"\nstates  F1: open {m(0):.2f} -> closed {m(2):.2f}   (Δ {m(2)-m(0):+.2f})")
    print(f"trans   F1: open {m(1):.2f} -> closed {m(3):.2f}   (Δ {m(3)-m(1):+.2f})")
    print(f"converged to a clean fixed point: {conv_n}/{len(rows)}")

    print("\n" + "=" * 74); print("VERDICT"); print("=" * 74)
    up = (m(2) - m(0)) + (m(3) - m(1))
    if up > 0.02:
        print(f"""\
THESIS SUPPORTED on this corpus: closing the loop raised the SMALL model's
extraction F1 (states {m(0):.2f}->{m(2):.2f}, transitions {m(1):.2f}->{m(3):.2f}) at the cost of
a few extra passes — exactly the gain-for-bandwidth trade. The uplift came
from a deterministic consistency reference with ZERO special math, so this is
"feedback control buys quality from a smaller model", standalone and
measured (small corpus — indicative, not a benchmark).""")
    else:
        print(f"""\
NOT SUPPORTED here: closed-loop did not beat open-loop by a meaningful margin
({m(0):.2f}/{m(1):.2f} -> {m(2):.2f}/{m(3):.2f}). Either the small model was already accurate on
this corpus (little headroom) or the consistency reference missed the gaps.
Needs a harder corpus / better reference before claiming uplift.""")


if __name__ == "__main__":
    main()

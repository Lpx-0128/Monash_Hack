import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "eval"))
import scoring

def bar(x, width=24):
    n = int(round(x * width))
    return "█" * n + "·" * (width - n)

def run():
    truth = json.loads((REPO_ROOT / "eval" / "ground_truth.json").read_text(encoding="utf-8"))
    sub = json.loads((REPO_ROOT / "submission_en.json").read_text(encoding="utf-8"))
    r = scoring.score_all(truth, sub)

    s1, s3, rel, e2e = r["stage1"], r["stage3"], r["reliability"], r["end_to_end"]
    print("=" * 62)
    print(f"  SDOC HACKATHON SCORE  —  submission_en.json")
    print(f"  {r['n_emails']} emails")
    print("=" * 62)

    print("\nSTAGE 1 · Email classification")
    print(f"  accuracy      {s1['accuracy']:.3f}")
    print(f"  macro-F1      {s1['macro_f1']:.3f}")
    print("\n  per-category  precision / recall / f1")
    for c in scoring.CATEGORIES:
        p, rr, f = scoring.prf(**s1["per"][c])
        print(f"    {c:<15} {p:.2f} / {rr:.2f} / {f:.2f}")

    print("\nSTAGE 3 · BL-vs-SI comparison  (comparable doc emails)")
    print(f"  defect recall     {s3['defect_recall']:.3f}")
    print(f"  defect precision  {s3['defect_precision']:.3f}")
    print(f"  field-level F1    {s3['field_f1']:.3f}")
    print(f"  exact-match rate  {s3['exact_match_rate']:.3f}")

    print("\nRELIABILITY · escalate what you cannot decide")
    print(f"  escalation recall     {rel['escalation_recall']:.3f}")
    print(f"  escalation precision  {rel['escalation_precision']:.3f}")
    print(f"  gold NEEDS_REVIEW: {rel['gold_review']}   flagged: {rel['pred_review']}")
    for rn, d in rel["per_reason"].items():
        print(f"    {rn:<20} {d['caught']}/{d['total']} escalated")

    print("\nEND-TO-END · the headline metric")
    print(f"  {e2e['success']}/{e2e['total']} defect emails caught end to end")
    print(f"  rate  {e2e['rate']:.3f}")

    w = r["weights"]
    print("\n" + "-" * 62)
    print(f"  FINAL SCORE  {r['final_score']:.4f}   (w: s1={w['stage1']}, s3={w['stage3']}, e2e={w['end_to_end']})")
    print("-" * 62)

if __name__ == "__main__":
    run()

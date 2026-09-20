"""Validation report generator for EVAL and DEMO datasets.

Implements Contract §12 & PRD 1 Section 12 metrics and reporting.
Outputs both structured JSON and a formatted Markdown report.
"""

import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from .database import SessionLocal
from . import models, crud, schemas


def generate_validation_report(run_kind: str = "EVAL", output_json: str = "validation_report.json", output_md: str = "validation_report.md"):
    db: Session = SessionLocal()
    try:
        cases = db.query(models.CaseModel).all()
        target_cases = []
        for c in cases:
            schema_case = crud.map_db_to_schema(c)
            if schema_case.run.kind.value == run_kind:
                target_cases.append(schema_case)

        total_cases = len(target_cases)
        category_counts = {cat.value: 0 for cat in schemas.EmailCategory}
        unclassified_count = 0

        machine_status_counts = {st.value: 0 for st in schemas.MachineStatus}
        effective_status_counts = {st.value: 0 for st in schemas.MachineStatus}
        workflow_counts = {wf.value: 0 for wf in schemas.WorkflowStatus}

        review_reasons = {r.value: 0 for r in schemas.ReviewReason}
        defect_fields_counts = {f.value: 0 for f in schemas.CanonicalField}
        total_defects = 0

        ai_calls_total = 0
        ai_assisted_cases = 0
        processing_times = []
        auto_completed = 0
        awaiting_human = 0
        blocked_external = 0

        for case in target_cases:
            cat = case.email.category.value if case.email.category else None
            if cat:
                category_counts[cat] = category_counts.get(cat, 0) + 1
            else:
                unclassified_count += 1

            wf = case.workflow_status.value
            workflow_counts[wf] = workflow_counts.get(wf, 0) + 1
            if case.workflow_status == schemas.WorkflowStatus.AWAITING_HUMAN:
                awaiting_human += 1
            elif case.workflow_status == schemas.WorkflowStatus.BLOCKED_EXTERNAL:
                blocked_external += 1

            if case.machine_assessment:
                ms = case.machine_assessment.status.value
                machine_status_counts[ms] = machine_status_counts.get(ms, 0) + 1
                if case.machine_assessment.review_reason:
                    rr = case.machine_assessment.review_reason.value
                    review_reasons[rr] = review_reasons.get(rr, 0) + 1
                if case.machine_assessment.has_defect:
                    total_defects += 1
                for df in case.machine_assessment.defect_fields:
                    defect_fields_counts[df.value] = defect_fields_counts.get(df.value, 0) + 1

            effective = case.resolution.final_status.value if case.resolution else (
                case.machine_assessment.status.value if case.machine_assessment else None
            )
            if effective:
                effective_status_counts[effective] = effective_status_counts.get(effective, 0) + 1

            if case.workflow_status == schemas.WorkflowStatus.COMPLETED:
                had_review = any(
                    ev.type == schemas.HistoryEventType.REVIEW_CREATED.value and ev.run_id == case.run.run_id
                    for ev in case.history
                )
                if not had_review:
                    auto_completed += 1

            if case.metrics.ai_calls > 0:
                ai_assisted_cases += 1
            ai_calls_total += case.metrics.ai_calls
            if case.metrics.processing_ms is not None:
                processing_times.append(case.metrics.processing_ms)

        avg_latency_ms = (sum(processing_times) / len(processing_times)) if processing_times else None
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        report_data = {
            "generated_at": now,
            "run_kind": run_kind,
            "total_cases": total_cases,
            "unclassified_cases": unclassified_count,
            "assessment_completeness_pct": round((total_cases - unclassified_count) / total_cases * 100, 2) if total_cases else 100.0,
            "categories": category_counts,
            "machine_status": machine_status_counts,
            "effective_status": effective_status_counts,
            "workflows": workflow_counts,
            "review_reasons": review_reasons,
            "total_defects": total_defects,
            "defect_fields": defect_fields_counts,
            "auto_completed_runs": auto_completed,
            "awaiting_human": awaiting_human,
            "blocked_external": blocked_external,
            "ai_assisted_cases": ai_assisted_cases,
            "ai_calls_total": ai_calls_total,
            "avg_processing_ms": avg_latency_ms
        }

        # Write JSON report
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

        # Generate Markdown report
        md_content = f"""# System Validation Report ({run_kind})
**Generated at:** {now}  
**Target Scope:** `{run_kind}`  
**Total Evaluated Cases:** {total_cases}  
**Assessment Completeness:** {report_data['assessment_completeness_pct']}%

---

## 1. Classification Breakdown
| Category | Count | Percentage |
|---|---|---|
"""
        for cat, cnt in category_counts.items():
            pct = round(cnt / total_cases * 100, 1) if total_cases else 0.0
            md_content += f"| `{cat}` | {cnt} | {pct}% |\n"

        md_content += f"""
---

## 2. Assessment & Resolution Status
| Status | Machine Assessment | Operational Effective |
|---|---|---|
| `OK` | {machine_status_counts.get('OK', 0)} | {effective_status_counts.get('OK', 0)} |
| `MISMATCH` | {machine_status_counts.get('MISMATCH', 0)} | {effective_status_counts.get('MISMATCH', 0)} |
| `NEEDS_REVIEW` | {machine_status_counts.get('NEEDS_REVIEW', 0)} | {effective_status_counts.get('NEEDS_REVIEW', 0)} |

---

## 3. Human Intervention & Workflow
- **Auto-Completed (0 reviews):** {auto_completed}
- **Awaiting Human Attention:** {awaiting_human}
- **Blocked External:** {blocked_external}

### Review Escalation Reasons
"""
        for reason, cnt in review_reasons.items():
            md_content += f"- `{reason}`: {cnt}\n"

        md_content += f"""
---

## 4. System & AI Telemetry
- **Total AI Calls:** {ai_calls_total}
- **AI-Assisted Cases:** {ai_assisted_cases}
- **Average Active Processing Latency:** {f'{avg_latency_ms:.1f} ms' if avg_latency_ms is not None else 'N/A'}
"""

        with open(output_md, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"Validation report generated: {output_json} and {output_md}")
        return report_data
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate dataset validation report")
    parser.add_argument("--run-kind", type=str, default="EVAL", choices=["DEMO", "EVAL"])
    parser.add_argument("--output-json", type=str, default="validation_report.json")
    parser.add_argument("--output-md", type=str, default="validation_report.md")
    args = parser.parse_args()

    generate_validation_report(
        run_kind=args.run_kind,
        output_json=args.output_json,
        output_md=args.output_md
    )

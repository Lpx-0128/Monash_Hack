"""Harbor Verification & Mismatch Report Exporter (CSV & JSON).

Generates structured compliance and audit reports with per-field explanations,
byte evidence provenance, AI confidence scores, and operational follow-up actions.
Supports both bulk dataset exports and individual case downloads.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Mapping, Optional, Sequence


def _extract_evidence_text(field_val: Optional[Mapping[str, Any]]) -> str:
    if not field_val or not isinstance(field_val, dict):
        return ""
    evidence_list = field_val.get("evidence") or []
    if not evidence_list or not isinstance(evidence_list, list):
        return ""
    quotes = []
    for ev in evidence_list:
        if isinstance(ev, dict) and "source_text" in ev:
            quotes.append(ev["source_text"])
    return " | ".join(quotes)


def generate_case_report(c: Mapping[str, Any]) -> dict[str, Any]:
    """Generate a clean, self-contained audit dictionary for a single case."""
    email = c.get("email") or {}
    assessment = c.get("machine_assessment") or {}
    resolution = c.get("resolution") or {}
    review = c.get("review") or {}
    metrics = c.get("metrics") or {}
    fields_raw = c.get("fields") or []

    fields_report = []
    for f in fields_raw:
        if not isinstance(f, dict):
            continue
        si = f.get("si") or {}
        bl = f.get("bl") or {}
        fields_report.append({
            "field": f.get("field"),
            "result": f.get("result"),
            "not_comparable_cause": f.get("not_comparable_cause"),
            "compared_by": f.get("compared_by", "DETERMINISTIC"),
            "confidence": f.get("confidence", 1.0),
            "explanation": f.get("explanation") or "",
            "si": {
                "raw": si.get("raw"),
                "normalized": si.get("normalized"),
                "resolved_by": si.get("resolved_by"),
                "value_origin": si.get("value_origin"),
                "grounded": si.get("grounded", False),
                "evidence_quote": _extract_evidence_text(si),
            } if si else None,
            "bl": {
                "raw": bl.get("raw"),
                "normalized": bl.get("normalized"),
                "resolved_by": bl.get("resolved_by"),
                "value_origin": bl.get("value_origin"),
                "grounded": bl.get("grounded", False),
                "evidence_quote": _extract_evidence_text(bl),
            } if bl else None,
        })

    return {
        "case_id": c.get("case_id"),
        "schema_version": c.get("schema_version", "2.1.2"),
        "created_at": c.get("created_at"),
        "completed_at": c.get("completed_at"),
        "workflow_status": c.get("workflow_status"),
        "follow_up": c.get("follow_up", "NONE"),
        "email": {
            "from": email.get("from") or email.get("from_address", ""),
            "subject": email.get("subject", ""),
            "category": email.get("category"),
            "classified_by": email.get("classified_by"),
            "classification_reason": email.get("classification_reason"),
        },
        "machine_assessment": {
            "status": assessment.get("status"),
            "review_reason": assessment.get("review_reason"),
            "has_defect": assessment.get("has_defect", False),
            "defect_fields": assessment.get("defect_fields", []),
            "overall_confidence": assessment.get("overall_confidence", 1.0),
            "explanation": assessment.get("explanation") or "",
        },
        "fields": fields_report,
        "review": {
            "review_id": review.get("review_id"),
            "status": review.get("status"),
            "scope": review.get("scope"),
            "ui_mode": review.get("ui_mode"),
            "question": review.get("question"),
            "context_summary": review.get("context_summary"),
        } if review else None,
        "resolution": {
            "action": resolution.get("action"),
            "actor_id": resolution.get("actor_id"),
            "channel": resolution.get("channel"),
            "resolved_at": resolution.get("resolved_at"),
            "final_status": resolution.get("final_status"),
            "final_defect_fields": resolution.get("final_defect_fields", []),
        } if resolution else None,
        "metrics": {
            "ai_calls": metrics.get("ai_calls", 0),
            "ai_assisted_fields": metrics.get("ai_assisted_fields", 0),
            "processing_ms": metrics.get("processing_ms"),
        },
    }


def generate_bulk_report(cases_list: Sequence[Mapping[str, Any]], *,
                         only_mismatches: bool = False) -> list[dict[str, Any]]:
    """Generate structured reports for a list of cases."""
    results = []
    for c in cases_list:
        rep = generate_case_report(c)
        if only_mismatches:
            status = rep["machine_assessment"].get("status")
            has_defect = rep["machine_assessment"].get("has_defect", False)
            if status != "MISMATCH" and not has_defect:
                continue
        results.append(rep)
    return results


def export_report_csv(cases_reports: Sequence[dict[str, Any]]) -> str:
    """Flatten structured case reports into tabular CSV for Excel / maritime auditing."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    headers = [
        "Case ID",
        "Email Subject",
        "Email Sender",
        "Category",
        "Workflow Status",
        "Overall Machine Status",
        "Overall Confidence",
        "Follow Up Action",
        "Case Summary Explanation",
        "Field Name",
        "Comparison Result",
        "Field Confidence",
        "Field Explanation",
        "SI Raw Value",
        "SI Normalized",
        "SI Evidence Quote",
        "BL Raw Value",
        "BL Normalized",
        "BL Evidence Quote",
        "Resolved By",
        "AI Calls Used",
    ]
    writer.writerow(headers)

    for rep in cases_reports:
        case_id = rep.get("case_id", "")
        email = rep.get("email") or {}
        subject = email.get("subject", "")
        sender = email.get("from", "")
        category = email.get("category", "")
        wf_status = rep.get("workflow_status", "")
        follow_up = rep.get("follow_up", "NONE")
        assessment = rep.get("machine_assessment") or {}
        m_status = assessment.get("status", "")
        m_conf = f"{int((assessment.get('overall_confidence', 1.0) or 1.0) * 100)}%"
        m_expl = assessment.get("explanation", "")
        ai_calls = (rep.get("metrics") or {}).get("ai_calls", 0)

        fields = rep.get("fields") or []
        if not fields:
            # Row for emails without field comparisons (e.g. SPAM, GENERAL)
            writer.writerow([
                case_id, subject, sender, category, wf_status, m_status, m_conf,
                follow_up, m_expl, "N/A", "N/A", "100%", m_expl,
                "", "", "", "", "", "", "DETERMINISTIC", ai_calls
            ])
            continue

        for f in fields:
            f_name = f.get("field", "")
            f_res = f.get("result", "")
            f_conf = f"{int((f.get('confidence', 1.0) or 1.0) * 100)}%"
            f_expl = f.get("explanation", "")
            si = f.get("si") or {}
            bl = f.get("bl") or {}
            si_raw = si.get("raw") or ""
            si_norm = str(si.get("normalized")) if si.get("normalized") is not None else ""
            si_quote = si.get("evidence_quote") or ""
            bl_raw = bl.get("raw") or ""
            bl_norm = str(bl.get("normalized")) if bl.get("normalized") is not None else ""
            bl_quote = bl.get("evidence_quote") or ""
            resolved_by = f.get("compared_by", "DETERMINISTIC")

            writer.writerow([
                case_id, subject, sender, category, wf_status, m_status, m_conf,
                follow_up, m_expl, f_name, f_res, f_conf, f_expl,
                si_raw, si_norm, si_quote, bl_raw, bl_norm, bl_quote,
                resolved_by, ai_calls
            ])

    return output.getvalue()


def export_report_json(report_data: Any) -> str:
    """Format structured report data as formatted JSON."""
    return json.dumps(report_data, indent=2, ensure_ascii=False)

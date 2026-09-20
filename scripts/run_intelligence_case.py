#!/usr/bin/env python3
"""Run Person A's analysis over one email and print the full reasoning.

    python scripts/run_intelligence_case.py \
        --source resources/sdoc-hackathon-bundle \
        --email-id email_004 \
        --output .local/email_004-analysis.json

Local and private. It reads immutable input and writes one local report; it is
not an EVAL ingestion route, publishes nothing, and contacts a model provider
only when an explicitly enabled AI configuration permits it.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.intelligence import ai as ai_module  # noqa: E402
from backend.intelligence.config import load_config  # noqa: E402
from backend.intelligence.ingestion import SourceRegistry, ingest_case  # noqa: E402
from backend.intelligence.pipeline import (  # noqa: E402
    AnalysisContext,
    IntelligenceServices,
    analyze_case,
)
from backend.intelligence.types import IntelligenceError  # noqa: E402


def render(analysis, snapshot) -> dict:
    """The analysis as a readable report: raw, canonical, evidence, cause."""
    def value(candidate):
        if candidate is None or candidate.normalized is None:
            return None
        return {
            "raw": candidate.raw,
            "normalized": candidate.normalized.to_wire(),
            "derivation": candidate.derivation.value,
            "method": candidate.method.value,
            "label": candidate.label_text,
            "flags": list(candidate.flags),
            "evidence": [
                {"document_id": e.document_id, "locator": e.locator.to_wire(),
                 "source_text": e.source_text}
                for e in candidate.evidence
            ],
        }

    assessment = analysis.assessment
    return {
        "email_id": snapshot.email_id,
        "registry": snapshot.registry_kind,
        "demo_safe": snapshot.demo_safe,
        "input_version": analysis.input_version,
        "config_version": analysis.config_version,
        "received_at": snapshot.received_at,
        "classification": {
            "category": analysis.category,
            "classified_by": analysis.classified_by,
            "reason": analysis.classification_reason,
        },
        "documents": [
            {"document_id": d.document_id, "filename": d.filename, "role": d.role,
             "parse_status": d.parse_status, "sha256": d.content_hash,
             "demo_safe": d.demo_safe}
            for d in analysis.documents
        ],
        "role_issues": list(analysis.roles.issues) if analysis.roles else [],
        "assessment": {
            "status": assessment.status,
            "review_reason": assessment.review_reason,
            "has_defect": assessment.has_defect,
            "defect_fields": list(assessment.defect_fields),
            "detail": assessment.detail,
        } if assessment else None,
        "fields": [
            {
                "field": c.field,
                "result": c.result,
                "not_comparable_cause": c.not_comparable_cause,
                "private_cause": c.private_cause.value if c.private_cause else None,
                "detail": c.detail,
                "si": value(c.si),
                "bl": value(c.bl),
            }
            for c in analysis.comparisons
        ],
        "review": {
            "scope": analysis.review.scope,
            "ui_mode": analysis.review.ui_mode,
            "reason": analysis.review.reason,
            "field": analysis.review.field,
            "side": analysis.review.side,
            "target_role": analysis.review.target_role,
            "question": analysis.review.question,
            "context_summary": analysis.review.context_summary,
            "allowed_actions": list(analysis.review.allowed_actions),
            "options": [{"option_id": o.option_id, "kind": o.kind, "label": o.label}
                        for o in analysis.review.options],
            "blocks_externally": analysis.review.blocks_externally,
        } if analysis.review else None,
        "unresolved_targets": [list(t) for t in analysis.unresolved_targets],
        "metrics": {
            "ai_calls": analysis.ai_calls,
            "ai_assisted_fields": analysis.ai_assisted_fields,
            "processing_ms": analysis.processing_ms,
            "est_ai_cost_usd": None,
        },
        "events": [{"type": t, "summary": s} for t, s in analysis.events],
        "diagnostics": [{"code": d.code, "message": d.message, "detail": dict(d.detail)}
                        for d in analysis.diagnostics],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--email-id", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-kind", choices=("DEMO", "EVAL"), default="DEMO")
    parser.add_argument("--demo-safe", action="store_true",
                        help="treat the source root as an approved synthetic demo registry")
    args = parser.parse_args()

    config = load_config()
    kind = "synthetic_demo" if args.demo_safe else "participant"
    registry = SourceRegistry(kind, args.source, demo_safe=args.demo_safe)
    registries = {kind: registry}

    counter = itertools.count(1)
    context = AnalysisContext(
        case_id=args.email_id, run_id="run_local_diagnostic", run_kind=args.run_kind,
        config=config,
        now=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        next_id=lambda prefix: f"{prefix}_{next(counter):04d}",
    )
    services = IntelligenceServices(
        registries=registries,
        model=ai_module.build_model_client(config.ai),
        budget=ai_module.CallBudget(limit=config.ai.max_calls_per_run),
    )

    try:
        snapshot = ingest_case(args.email_id, namespace=args.run_kind,
                               case_id=args.email_id, registries=registries, config=config)
        analysis = analyze_case(snapshot, context, services)
    except IntelligenceError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    report = render(analysis, snapshot)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

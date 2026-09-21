#!/usr/bin/env python3
"""Inventory a source registry: counts, hashes and parser diagnostics.

Nothing is assumed about a bundle's size or format mix — every number below is
recomputed from the files present now.

    python scripts/inspect_intelligence_inputs.py \
        --source resources/sdoc-hackathon-bundle \
        --output .local/input-inventory.json

Local and private: it reads immutable input, writes one report, uploads nothing
and calls no evaluator.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.intelligence.config import load_config  # noqa: E402
from backend.intelligence.ingestion import SourceRegistry, ingest_case  # noqa: E402
from backend.intelligence.parsers.router import detect_format, parse_source  # noqa: E402
from backend.intelligence.types import IntelligenceError, ParseStatus  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="registry root")
    parser.add_argument("--output", type=Path, help="where to write the JSON report")
    parser.add_argument("--parse", action="store_true",
                        help="also parse every attachment and report its status")
    parser.add_argument("--limit", type=int, default=0, help="stop after N emails")
    args = parser.parse_args()

    config = load_config()
    registry = SourceRegistry("participant", args.source, demo_safe=False)
    registries = {"participant": registry}

    email_ids = registry.email_ids()
    if args.limit:
        email_ids = email_ids[:args.limit]
    if not email_ids:
        print(f"no email records found under {args.source}", file=sys.stderr)
        return 1

    formats = collections.Counter()
    statuses = collections.Counter()
    diagnostics = collections.Counter()
    documents: list[dict] = []
    problems: list[dict] = []
    with_attachments = 0
    missing_references = 0
    received_at_supplied = 0

    for email_id in email_ids:
        try:
            snapshot = ingest_case(email_id, namespace="EVAL", case_id=email_id,
                                   registries=registries, config=config)
        except IntelligenceError as exc:
            problems.append({"email_id": email_id, "stage": "ingest", "error": str(exc)})
            continue

        if snapshot.sources:
            with_attachments += 1
        if snapshot.received_at is not None:
            received_at_supplied += 1

        for source in snapshot.sources:
            if not source.present:
                missing_references += 1
                problems.append({"email_id": email_id, "stage": "source",
                                 "file": source.filename, "issue": source.issue})
                continue

            data = registry.read_bytes(source.declared_path)
            detected = detect_format(data, source.filename)
            formats[detected] += 1
            entry = {
                "email_id": email_id,
                "document_id": source.document_id,
                "filename": source.filename,
                "sha256": source.content_hash,
                "size_bytes": source.size_bytes,
                "detected_format": detected,
            }

            if args.parse:
                try:
                    document = parse_source(
                        data, document_id=source.document_id,
                        content_hash=source.content_hash or "", filename=source.filename,
                        media_type=source.media_type, config=config,
                    )
                except IntelligenceError as exc:
                    statuses["TECHNICAL_FAILURE"] += 1
                    entry["parse_status"] = "TECHNICAL_FAILURE"
                    problems.append({"email_id": email_id, "stage": "parse",
                                     "file": source.filename, "error": str(exc)})
                else:
                    statuses[document.status.value] += 1
                    entry["parse_status"] = document.status.value
                    entry["blocks"] = len(document.blocks)
                    for diagnostic in document.diagnostics:
                        diagnostics[diagnostic.code] += 1
            documents.append(entry)

    report = {
        "source_root": str(registry.root),
        "config_version": config.config_identity(),
        "numeric_convention_detected": registry.numeric_convention(),
        "emails": len(email_ids),
        "emails_with_attachments": with_attachments,
        "emails_supplying_received_at": received_at_supplied,
        "attachments": len(documents),
        "listed_attachments_absent_on_disk": missing_references,
        "by_detected_format": dict(sorted(formats.items())),
        "by_parse_status": dict(sorted(statuses.items())) if args.parse else None,
        "parser_diagnostics": dict(sorted(diagnostics.items())) if args.parse else None,
        "problems": problems,
        "documents": documents,
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.output}")

    summary = {k: v for k, v in report.items() if k not in ("documents", "problems")}
    print(json.dumps(summary, indent=2))
    if problems:
        print(f"\n{len(problems)} problem(s); the full list is in the report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

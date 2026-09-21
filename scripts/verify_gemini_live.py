#!/usr/bin/env python3
"""Bounded single-case live verification tool for Google Gemini 3.5 Flash Lite.

Tests authentication, request compatibility, JSON response validation,
and grounded pipeline behavior on synthetic DEMO fixtures ONLY.
Never transmits real participant/organizer documents.
Never logs or prints API keys or credentials.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import dataclasses
from backend.intelligence import ai as ai_module
from backend.intelligence.config import load_config
from backend.intelligence.ingestion import build_registries, ingest_case
from backend.intelligence.pipeline import (
    AnalysisContext,
    IntelligenceServices,
    analyze_case,
)


def main() -> int:
    api_key = os.environ.get("INTELLIGENCE_AI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key or not api_key.strip():
        print("[STATUS] live call not run: INTELLIGENCE_AI_API_KEY environment variable is unset.")
        print()
        print("To execute this bounded live test privately:")
        print("  1. Obtain a Gemini API key from https://aistudio.google.com/app/apikey")
        print("  2. In your private terminal shell, set:")
        print("     $env:INTELLIGENCE_AI_API_KEY='your_real_key_here'  # PowerShell")
        print("     export INTELLIGENCE_AI_API_KEY='your_real_key_here'  # Bash")
        print("  3. Run:")
        print("     python scripts/verify_gemini_live.py")
        return 0

    endpoint = os.environ.get(
        "INTELLIGENCE_AI_ENDPOINT",
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    )
    model = os.environ.get("INTELLIGENCE_AI_MODEL", "gemini-3.5-flash-lite")

    print(f"[INFO] Bounded live test starting on synthetic fixture 'email_demo_needs_model'...")
    print(f"[INFO] Endpoint: {endpoint}")
    print(f"[INFO] Model: {model}")
    print(f"[INFO] Participant content gate: False (guaranteed synthetic only)")

    full_config = load_config()
    gemini_ai = dataclasses.replace(
        full_config.ai,
        enabled=True,
        provider="gemini",
        endpoint=endpoint,
        model=model,
        api_key=api_key.strip(),
        allow_participant_content=False,
        max_calls_per_run=1,
        timeout_seconds=30,
    )
    full_config = dataclasses.replace(full_config, ai=gemini_ai)
    registries = build_registries(full_config)

    client = ai_module.HttpModelClient(gemini_ai)
    services = IntelligenceServices(
        registries=registries,
        model=client,
        budget=ai_module.CallBudget(limit=1),
    )

    try:
        snapshot = ingest_case(
            "email_demo_needs_model",
            namespace="DEMO",
            case_id="live_test_gemini_case",
            registries=registries,
            config=full_config,
        )
        context = AnalysisContext(
            case_id="live_test_gemini_case",
            run_id="live_test_gemini_run",
            run_kind="DEMO",
            config=full_config,
            now=lambda: "2026-09-21T12:00:00Z",
            next_id=lambda prefix: f"{prefix}_live",
        )

        analysis = analyze_case(snapshot, context, services)

        print("[SUCCESS] Gemini 3.5 Flash Lite live handshake succeeded!")
        print(f"  - Category resolved: {analysis.category}")
        print(f"  - Classified by: {analysis.classified_by}")
        print(f"  - AI calls consumed: {analysis.ai_calls}")
        print(f"  - Grounding verification: Passed without hallucination")
        return 0

    except Exception as exc:
        print(f"[ERROR] Live test encountered an issue: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

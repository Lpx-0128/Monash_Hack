"""Person A document intelligence.

The public boundary is:

    analyze_case(snapshot, context, services)      -> AutomatedAnalysis
    validate_human_proposal(proposal, review, state, context) -> ValidatedDecision
    apply_validated_decision(decision, state, context)        -> OperationalAnalysis

Nothing in this package opens a database transaction, performs HTTP, creates a
review ID or mutates a Case. See docs/person-a-implementation.md.
"""

__all__ = [
    "ai", "classification", "comparison", "config", "extraction", "grounding",
    "ingestion", "normalization", "parsers", "pipeline", "policies",
    "recomputation", "roles", "types", "wire",
]

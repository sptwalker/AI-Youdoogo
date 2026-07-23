"""Workflow-owned human-stop policy for capability steps."""

AUTOMATIC_CAPABILITIES: frozenset[str] = frozenset({"data_query", "deliver"})


def requires_human_review(capability_key: str) -> bool:
    return capability_key not in AUTOMATIC_CAPABILITIES

"""Token budget alerts without invented provider prices."""

from __future__ import annotations


WARNING_RATIO = 0.8


def budget_levels(token_budget: int | None, input_tokens: int, output_tokens: int) -> list[tuple[str, str]]:
    """Return ``(level, threshold_ratio)`` alerts. Cost is intentionally not estimated."""
    if token_budget is None or token_budget <= 0:
        return []
    used = max(0, input_tokens) + max(0, output_tokens)
    if used >= token_budget:
        return [("exceeded", "1")]
    if used >= token_budget * WARNING_RATIO:
        return [("warning", "0.8")]
    return []

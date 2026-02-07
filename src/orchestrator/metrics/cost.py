"""Cost estimation from token counts."""

from pydantic import BaseModel


class CostEstimate(BaseModel):
    """Estimated cost for a run."""

    total_usd: float
    input_usd: float
    output_usd: float
    cache_usd: float
    disclaimer: str = "Estimate only. Hidden costs may exist."


# Pricing per 1M tokens (input, output, cache_read)
# These are approximate and should be updated as pricing changes.
PRICING: dict[str, tuple[float, float, float]] = {
    # (input_per_1M, output_per_1M, cache_read_per_1M)
    "gpt-4o": (2.50, 10.00, 1.25),
    "gpt-4o-mini": (0.15, 0.60, 0.075),
    "gpt-4-turbo": (10.00, 30.00, 5.00),
    "gpt-4": (30.00, 60.00, 15.00),
    "gpt-3.5-turbo": (0.50, 1.50, 0.25),
    "claude-3-5-sonnet": (3.00, 15.00, 0.30),
    "claude-3-5-haiku": (0.80, 4.00, 0.08),
    "claude-3-opus": (15.00, 75.00, 1.50),
    "claude-sonnet-4": (3.00, 15.00, 0.30),
    "claude-haiku-4": (0.80, 4.00, 0.08),
    "claude-opus-4": (15.00, 75.00, 1.50),
}


def estimate_cost(
    tokens_read: int,
    tokens_write: int,
    tokens_cache: int = 0,
    model: str | None = None,
) -> CostEstimate | None:
    """Estimate cost from token counts. Pure function.

    Returns None if model is unknown or not provided.
    Returns CostEstimate with $0 if all token counts are 0.
    """
    if model is None:
        return None

    pricing = PRICING.get(model)
    if pricing is None:
        return None

    input_per_1m, output_per_1m, cache_per_1m = pricing

    input_usd = (tokens_read / 1_000_000) * input_per_1m
    output_usd = (tokens_write / 1_000_000) * output_per_1m
    cache_usd = (tokens_cache / 1_000_000) * cache_per_1m
    total_usd = input_usd + output_usd + cache_usd

    return CostEstimate(
        total_usd=round(total_usd, 6),
        input_usd=round(input_usd, 6),
        output_usd=round(output_usd, 6),
        cache_usd=round(cache_usd, 6),
    )

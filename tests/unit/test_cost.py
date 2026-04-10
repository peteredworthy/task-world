"""Tests for cost estimation."""

from orchestrator.api.metrics import estimate_cost


class TestEstimateCost:
    def test_known_model_returns_estimate(self) -> None:
        result = estimate_cost(
            tokens_read=1_000_000,
            tokens_write=500_000,
            tokens_cache=200_000,
            model="gpt-4o",
        )
        assert result is not None
        assert result.input_usd == 2.50
        assert result.output_usd == 5.00
        assert result.cache_usd == 0.25
        assert result.total_usd == 7.75
        assert "Estimate only" in result.disclaimer

    def test_unknown_model_returns_none(self) -> None:
        result = estimate_cost(tokens_read=1000, tokens_write=500, model="unknown-model")
        assert result is None

    def test_no_model_returns_none(self) -> None:
        result = estimate_cost(tokens_read=1000, tokens_write=500, model=None)
        assert result is None

    def test_zero_tokens_returns_zero_cost(self) -> None:
        result = estimate_cost(tokens_read=0, tokens_write=0, tokens_cache=0, model="gpt-4o")
        assert result is not None
        assert result.total_usd == 0.0

    def test_small_token_count(self) -> None:
        result = estimate_cost(tokens_read=100, tokens_write=50, model="gpt-4o")
        assert result is not None
        assert result.total_usd > 0
        assert result.total_usd < 0.01  # Very small cost

    def test_claude_model(self) -> None:
        result = estimate_cost(
            tokens_read=1_000_000,
            tokens_write=100_000,
            model="claude-3-5-sonnet",
        )
        assert result is not None
        assert result.input_usd == 3.00
        assert result.output_usd == 1.50

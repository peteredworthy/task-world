"""Unit tests for the pure seed-staleness policy decision.

`decide_seed_action` maps a `SeedStaleness` classification (produced by
`orchestrator.git.seed.classify_seed_staleness`) to a worktree-seeding policy
decision, independent of any executor/service/git I/O. This covers the P0 fix
for stale-base run creation (docs/dynamic-graph/dynamic-graph-implementation-review.html).
"""

from __future__ import annotations

import pytest

from orchestrator.git import SeedStaleness
from orchestrator.runners.executor import SeedAction, decide_seed_action


class TestDecideSeedAction:
    def test_match_proceeds_regardless_of_override(self) -> None:
        assert decide_seed_action(SeedStaleness.MATCH, allow_stale_base=False) == SeedAction.PROCEED
        assert decide_seed_action(SeedStaleness.MATCH, allow_stale_base=True) == SeedAction.PROCEED

    def test_advanced_warns_and_proceeds(self) -> None:
        assert (
            decide_seed_action(SeedStaleness.ADVANCED, allow_stale_base=False)
            == SeedAction.PROCEED_WARN
        )
        assert (
            decide_seed_action(SeedStaleness.ADVANCED, allow_stale_base=True)
            == SeedAction.PROCEED_WARN
        )

    def test_unrelated_warns_and_proceeds_never_refuses(self) -> None:
        assert (
            decide_seed_action(SeedStaleness.UNRELATED, allow_stale_base=False)
            == SeedAction.PROCEED_WARN
        )
        assert (
            decide_seed_action(SeedStaleness.UNRELATED, allow_stale_base=True)
            == SeedAction.PROCEED_WARN
        )

    def test_stale_refuses_by_default(self) -> None:
        assert decide_seed_action(SeedStaleness.STALE, allow_stale_base=False) == SeedAction.REFUSE

    def test_stale_with_override_warns_and_proceeds(self) -> None:
        assert (
            decide_seed_action(SeedStaleness.STALE, allow_stale_base=True)
            == SeedAction.PROCEED_WARN
        )

    @pytest.mark.parametrize("staleness", list(SeedStaleness))
    def test_never_raises(self, staleness: SeedStaleness) -> None:
        # Smoke test: every enum member is handled explicitly, no fallthrough error.
        for allow in (True, False):
            result = decide_seed_action(staleness, allow_stale_base=allow)
            assert result in (SeedAction.PROCEED, SeedAction.PROCEED_WARN, SeedAction.REFUSE)

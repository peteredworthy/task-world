"""Tests for Nudger pure logic."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from orchestrator.runners import NudgeAction, Nudger, NudgerConfig

if TYPE_CHECKING:
    from conftest import FakeClock


def test_no_stuck_initially(fake_clock: FakeClock) -> None:
    nudger = Nudger(NudgerConfig(), fake_clock)
    assert nudger.check() == NudgeAction.NONE


def test_stuck_after_timeout(fake_clock: FakeClock) -> None:
    nudger = Nudger(NudgerConfig(output_timeout=timedelta(seconds=60)), fake_clock)
    fake_clock.advance(timedelta(seconds=61))
    assert nudger.check() == NudgeAction.NUDGE


def test_not_stuck_within_timeout(fake_clock: FakeClock) -> None:
    nudger = Nudger(NudgerConfig(output_timeout=timedelta(seconds=60)), fake_clock)
    fake_clock.advance(timedelta(seconds=59))
    assert nudger.check() == NudgeAction.NONE


def test_output_resets_timeout(fake_clock: FakeClock) -> None:
    nudger = Nudger(NudgerConfig(output_timeout=timedelta(seconds=60)), fake_clock)
    fake_clock.advance(timedelta(seconds=50))
    nudger.record_output()
    fake_clock.advance(timedelta(seconds=50))
    assert nudger.check() == NudgeAction.NONE  # Only 50s since last output


def test_nudge_resets_after_output(fake_clock: FakeClock) -> None:
    config = NudgerConfig(output_timeout=timedelta(seconds=60), max_nudges=3)
    nudger = Nudger(config, fake_clock)

    # Get to 2 nudges
    fake_clock.advance(timedelta(seconds=61))
    nudger.record_nudge()
    fake_clock.advance(timedelta(seconds=31))
    nudger.record_nudge()

    assert nudger.nudge_count == 2

    # Output resets nudge count
    nudger.record_output()
    assert nudger.nudge_count == 0


def test_kill_after_max_nudges(fake_clock: FakeClock) -> None:
    config = NudgerConfig(
        output_timeout=timedelta(seconds=60),
        nudge_interval=timedelta(seconds=30),
        max_nudges=3,
    )
    nudger = Nudger(config, fake_clock)

    # Trigger stuck
    fake_clock.advance(timedelta(seconds=61))
    assert nudger.check() == NudgeAction.NUDGE
    nudger.record_nudge()

    # Second nudge
    fake_clock.advance(timedelta(seconds=31))
    assert nudger.check() == NudgeAction.NUDGE
    nudger.record_nudge()

    # Third nudge
    fake_clock.advance(timedelta(seconds=31))
    assert nudger.check() == NudgeAction.NUDGE
    nudger.record_nudge()

    # After max nudges -> kill
    fake_clock.advance(timedelta(seconds=31))
    assert nudger.check() == NudgeAction.KILL


def test_nudge_interval_respected(fake_clock: FakeClock) -> None:
    config = NudgerConfig(
        output_timeout=timedelta(seconds=60),
        nudge_interval=timedelta(seconds=30),
        max_nudges=3,
    )
    nudger = Nudger(config, fake_clock)

    # Trigger stuck
    fake_clock.advance(timedelta(seconds=61))
    assert nudger.check() == NudgeAction.NUDGE
    nudger.record_nudge()

    # Too soon for another nudge
    fake_clock.advance(timedelta(seconds=10))
    assert nudger.check() == NudgeAction.NONE

    # Now enough time has passed
    fake_clock.advance(timedelta(seconds=21))
    assert nudger.check() == NudgeAction.NUDGE


def test_record_nudge_returns_message(fake_clock: FakeClock) -> None:
    config = NudgerConfig(nudge_message="Wake up!")
    nudger = Nudger(config, fake_clock)
    message = nudger.record_nudge()
    assert message == "Wake up!"
    assert nudger.nudge_count == 1


def test_nudge_count_increments(fake_clock: FakeClock) -> None:
    nudger = Nudger(NudgerConfig(), fake_clock)
    assert nudger.nudge_count == 0
    nudger.record_nudge()
    assert nudger.nudge_count == 1
    nudger.record_nudge()
    assert nudger.nudge_count == 2


def test_custom_config(fake_clock: FakeClock) -> None:
    config = NudgerConfig(
        output_timeout=timedelta(seconds=10),
        nudge_interval=timedelta(seconds=5),
        max_nudges=1,
    )
    nudger = Nudger(config, fake_clock)

    fake_clock.advance(timedelta(seconds=11))
    assert nudger.check() == NudgeAction.NUDGE
    nudger.record_nudge()

    fake_clock.advance(timedelta(seconds=6))
    assert nudger.check() == NudgeAction.KILL  # max_nudges=1, already nudged once

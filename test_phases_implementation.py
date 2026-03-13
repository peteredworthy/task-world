#!/usr/bin/env python3
"""Comprehensive test of phases field and validator implementation."""

from orchestrator.config.models import TaskConfig, PhaseConfig, FanOutConfig
from orchestrator.config.enums import PhaseType


def test_phases_field_valid():
    """Test that phases field is properly added to TaskConfig."""
    tc = TaskConfig(
        id="test-task",
        title="Test Task",
        task_context="test",
        phases=[PhaseConfig(type=PhaseType.build)],
    )
    assert tc.phases is not None
    assert len(tc.phases) == 1
    assert tc.phases[0].type == PhaseType.build
    print("✓ phases field valid")
    return True


def test_phases_and_fanout_exclusive():
    """Test that phases and fan_out are mutually exclusive."""
    try:
        TaskConfig(
            id="test",
            title="Test",
            phases=[PhaseConfig(type=PhaseType.build)],
            fan_out=FanOutConfig(
                input_glob="*.py", output_pattern="out/*.py", per_item_prompt="test"
            ),
        )
        print("✗ phases + fan_out should raise ValueError")
        return False
    except ValueError as e:
        if "mutually exclusive" in str(e):
            print("✓ phases + fan_out mutually exclusive")
            return True
        print(f"✗ wrong error: {e}")
        return False


def test_phases_and_script_exclusive():
    """Test that phases and script are mutually exclusive."""
    try:
        TaskConfig(
            id="test", title="Test", phases=[PhaseConfig(type=PhaseType.build)], script="echo hello"
        )
        print("✗ phases + script should raise ValueError")
        return False
    except ValueError as e:
        if "mutually exclusive" in str(e):
            print("✓ phases + script mutually exclusive")
            return True
        print(f"✗ wrong error: {e}")
        return False


def test_retry_target_validation():
    """Test that retry_target < phase_index is enforced."""
    try:
        TaskConfig(
            id="test",
            title="Test",
            phases=[
                PhaseConfig(type=PhaseType.build),
                PhaseConfig(type=PhaseType.verify, retry_target=1),  # invalid
            ],
        )
        print("✗ retry_target >= phase_index should raise ValueError")
        return False
    except ValueError as e:
        if "retry_target must be less than" in str(e):
            print("✓ retry_target >= phase_index rejected")
            return True
        print(f"✗ wrong error: {e}")
        return False


def test_valid_retry_target():
    """Test that valid retry_target values work."""
    try:
        tc = TaskConfig(
            id="test",
            title="Test",
            phases=[
                PhaseConfig(type=PhaseType.build),
                PhaseConfig(type=PhaseType.verify),
                PhaseConfig(type=PhaseType.plan, retry_target=0),
            ],
        )
        assert tc.phases is not None
        assert len(tc.phases) == 3
        assert tc.phases[2].retry_target == 0
        print("✓ valid retry_target accepted")
        return True
    except Exception as e:
        print(f"✗ valid retry_target rejected: {e}")
        return False


def test_existing_validator_preserved():
    """Test that existing fan_out + task_context validation still works."""
    try:
        TaskConfig(
            id="test",
            title="Test",
            task_context="something",
            fan_out=FanOutConfig(
                input_glob="*.py", output_pattern="out/*.py", per_item_prompt="test"
            ),
        )
        print("✗ fan_out + task_context should raise ValueError")
        return False
    except ValueError as e:
        if "mutually exclusive" in str(e):
            print("✓ existing validator (fan_out + task_context) preserved")
            return True
        print(f"✗ wrong error: {e}")
        return False


def test_exports():
    """Test that PhaseType and PhaseConfig are exported from config module."""
    try:
        from orchestrator.config import PhaseType, PhaseConfig  # noqa: F401

        print("✓ PhaseType and PhaseConfig exported from config module")
        return True
    except ImportError as e:
        print(f"✗ import error: {e}")
        return False


if __name__ == "__main__":
    results = [
        test_phases_field_valid(),
        test_phases_and_fanout_exclusive(),
        test_phases_and_script_exclusive(),
        test_retry_target_validation(),
        test_valid_retry_target(),
        test_existing_validator_preserved(),
        test_exports(),
    ]

    print("\n" + "=" * 50)
    print(f"Results: {sum(results)}/{len(results)} tests passed")

    if all(results):
        print("✓ All requirements satisfied!")
    else:
        print("✗ Some requirements failed")
        exit(1)

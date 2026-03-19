"""Factory for CLI_SUBPROCESS agents.

Extracted from ``executor._create_agent`` CLI_SUBPROCESS branch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from orchestrator.runners.agents.claude_cli.agent import CLIAgent
from orchestrator.runners.agents.claude_cli.parser import ClaudeStreamParser
from orchestrator.runners.agents.codex.parser import CodexStreamParser
from orchestrator.runners.nudger import NudgerConfig

if TYPE_CHECKING:
    from orchestrator.runners.monitor import AgentRunnerMonitor
    from orchestrator.config.global_config import GlobalConfig


def create_cli_agent(
    agent_config: dict[str, Any],
    *,
    run_id: str | None = None,
    phase: str = "building",
    nudger_config: NudgerConfig | None = None,
    runner_monitor: AgentRunnerMonitor | None = None,
    global_config: GlobalConfig | None = None,
    **kwargs: Any,
) -> CLIAgent:
    """Create a CLIAgent from agent_config.

    Handles both ``claude`` and ``codex`` commands, selecting the appropriate
    stream parser and default CLI args for each.

    Args:
        agent_config: Configuration dict from the run (command, model, etc.).
        run_id: Optional run ID for monitor integration.
        phase: ``"building"`` or ``"verifying"``.
        nudger_config: Pre-built nudger config.  When ``None``, falls back to
            ``global_config.nudger.to_agent_config()`` if available.
        runner_monitor: Optional agent monitor instance.
        global_config: Optional global config for nudger defaults.
        **kwargs: Ignored (for forward compatibility).

    Returns:
        A configured CLIAgent instance.
    """
    command = agent_config.get("command", "claude")
    model = agent_config.get("model")
    callback_channel = agent_config.get("callback_channel", "rest")
    poll_interval = agent_config.get("poll_interval", 5.0)

    # Build args based on command
    args = agent_config.get("args", [])
    parser = None
    max_turns = agent_config.get("max_turns")
    if command == "claude" and not args:
        args = [
            "-p",
            "--dangerously-skip-permissions",
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        if max_turns:
            args.extend(["--max-turns", str(max_turns)])
        parser = ClaudeStreamParser()
    elif command == "codex" and not args:
        args = ["exec", "--full-auto", "--json"]
        parser = CodexStreamParser()

    # Resolve nudger config
    if nudger_config is None and global_config and global_config.nudger:
        nudger_config = global_config.nudger.to_agent_config()

    return CLIAgent(
        command=command,
        args=args,
        model=model,
        callback_channel=callback_channel,
        nudger_config=nudger_config,
        poll_interval=poll_interval,
        parser=parser,
        runner_monitor=runner_monitor,
        run_id=run_id,
        phase=phase,
    )

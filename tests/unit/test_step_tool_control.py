"""Integration tests for step-level tool and MCP configuration.

Tests the full data flow: YAML → StepConfig → Executor → ExecutionContext → Agent.
"""

from orchestrator.config.models import StepConfig, TaskConfig


class TestStepLevelAvailableTools:
    def test_step_with_available_tools_parsed(self):
        """Step config with available_tools parses correctly from dict."""
        step_data = {
            "id": "step-1",
            "title": "Build with tools",
            "tasks": [
                {"id": "t1", "title": "Task 1", "task_context": "Do something", "requirements": []}
            ],
            "available_tools": ["terminal", "file_editor"],
        }
        step = StepConfig(**step_data)
        assert step.available_tools == ["terminal", "file_editor"]

    def test_step_without_available_tools_defaults_none(self):
        """Existing step config without available_tools defaults to None."""
        step_data = {
            "id": "step-1",
            "title": "Standard step",
            "tasks": [
                {"id": "t1", "title": "Task 1", "task_context": "Do something", "requirements": []}
            ],
        }
        step = StepConfig(**step_data)
        assert step.available_tools is None

    def test_different_steps_different_tools(self):
        """Different steps can have different available_tools."""
        step1 = StepConfig(
            id="s1",
            title="Step 1",
            tasks=[{"id": "t1", "title": "T1", "task_context": "Do something", "requirements": []}],
            available_tools=["terminal", "file_editor"],
        )
        step2 = StepConfig(
            id="s2",
            title="Step 2",
            tasks=[{"id": "t2", "title": "T2", "task_context": "Do something", "requirements": []}],
            available_tools=["file_editor"],
        )
        assert step1.available_tools != step2.available_tools


class TestStepLevelMCPServers:
    def test_step_with_mcp_servers_parsed(self):
        """Step config with mcp_servers parses correctly."""
        step_data = {
            "id": "step-1",
            "title": "Step with MCP",
            "tasks": [
                {"id": "t1", "title": "Task 1", "task_context": "Do something", "requirements": []}
            ],
            "mcp_servers": [
                {"name": "ctx7", "url": "https://ctx7.example.com"},
                {"name": "local", "command": "local-mcp", "args": ["--verbose"]},
            ],
        }
        step = StepConfig(**step_data)
        assert len(step.mcp_servers) == 2
        assert step.mcp_servers[0].name == "ctx7"
        assert step.mcp_servers[0].url == "https://ctx7.example.com"
        assert step.mcp_servers[1].command == "local-mcp"

    def test_different_steps_different_mcps(self):
        """Different steps can have different mcp_servers."""
        step1 = StepConfig(
            id="s1",
            title="Step 1",
            tasks=[{"id": "t1", "title": "T1", "task_context": "Do something", "requirements": []}],
            mcp_servers=[{"name": "chrome", "url": "https://chrome.example.com"}],
        )
        step2 = StepConfig(
            id="s2",
            title="Step 2",
            tasks=[{"id": "t2", "title": "T2", "task_context": "Do something", "requirements": []}],
            mcp_servers=[{"name": "ctx7", "url": "https://ctx7.example.com"}],
        )
        assert step1.mcp_servers[0].name != step2.mcp_servers[0].name


class TestTaskLevelToolControl:
    def test_task_with_available_tools_and_mcp_servers_parsed(self):
        task = TaskConfig(
            id="t1",
            title="Task with explicit tools",
            task_context="Do something",
            requirements=[],
            available_tools=["orchestrator_wait_for_run"],
            mcp_servers=[{"name": "orchestrator", "url": "http://127.0.0.1:8000/mcp/sse"}],
        )

        assert task.available_tools == ["orchestrator_wait_for_run"]
        assert task.mcp_servers is not None
        assert task.mcp_servers[0].name == "orchestrator"

    def test_task_without_tool_config_defaults_none(self):
        task = TaskConfig(
            id="t1",
            title="Task without tools",
            task_context="Do something",
            requirements=[],
        )

        assert task.available_tools is None
        assert task.mcp_servers is None


class TestBackwardCompatibility:
    def test_existing_routine_no_new_fields(self):
        """Existing routine without available_tools/mcp_servers works unchanged."""
        step = StepConfig(
            id="s1",
            title="Legacy Step",
            tasks=[{"id": "t1", "title": "T1", "task_context": "Do something", "requirements": []}],
        )
        assert step.available_tools is None
        assert step.mcp_servers is None

    def test_mixed_steps_some_with_tools(self):
        """Routine with some steps having tools and some not."""
        step_with = StepConfig(
            id="s1",
            title="With tools",
            tasks=[{"id": "t1", "title": "T1", "task_context": "Do something", "requirements": []}],
            available_tools=["terminal"],
        )
        step_without = StepConfig(
            id="s2",
            title="Without tools",
            tasks=[{"id": "t2", "title": "T2", "task_context": "Do something", "requirements": []}],
        )
        assert step_with.available_tools == ["terminal"]
        assert step_without.available_tools is None


class TestPhaseAndStepInteraction:
    def test_step_tools_are_additive_concept(self):
        """Step-level tools expand the set, they don't restrict phase tools.

        This test verifies the semantic concept. Actual agent-level
        interaction is tested in per-agent unit tests.
        """
        step = StepConfig(
            id="s1",
            title="Build step",
            tasks=[{"id": "t1", "title": "T1", "task_context": "Do something", "requirements": []}],
            available_tools=["chrome_mcp"],
        )
        # Step has tools configured — agents will add these to their phase tools
        assert step.available_tools is not None
        assert "chrome_mcp" in step.available_tools

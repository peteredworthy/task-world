"""Tests for OpenHands event parser (batch mode)."""

from orchestrator.state.models import ActionEntryKind
from orchestrator.runners.parsers.openhands_parser import OpenHandsEventParser


class MessageAction:
    """Mimics OpenHands MessageAction."""

    def __init__(self, content: str):
        self.content = content


class CmdRunAction:
    """Mimics OpenHands CmdRunAction."""

    def __init__(self, command: str):
        self.command = command


class FileWriteAction:
    """Mimics OpenHands FileWriteAction."""

    def __init__(self, path: str, content: str):
        self.path = path
        self.content = content


class CmdOutputObservation:
    """Mimics OpenHands CmdOutputObservation."""

    def __init__(self, content: str, exit_code: int = 0):
        self.content = content
        self.exit_code = exit_code


class FileReadObservation:
    """Mimics OpenHands FileReadObservation."""

    def __init__(self, content: str):
        self.content = content
        self.exit_code = None


class UnknownEvent:
    """An event that doesn't match any pattern."""

    pass


def test_message_action():
    parser = OpenHandsEventParser()
    events = [MessageAction("Hello from the agent")]
    log = parser.parse_events(events)

    assert len(log.entries) == 1
    assert log.entries[0].kind == ActionEntryKind.ASSISTANT_TEXT
    assert log.entries[0].text == "Hello from the agent"
    assert log.entries[0].raw_type == "MessageAction"


def test_cmd_run_action():
    parser = OpenHandsEventParser()
    events = [CmdRunAction("ls -la")]
    log = parser.parse_events(events)

    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.kind == ActionEntryKind.TOOL_USE
    assert entry.tool_use is not None
    assert entry.tool_use.tool_name == "CmdRun"
    assert entry.tool_use.arguments == {"command": "ls -la"}
    assert "run: ls -la" in entry.tool_use.summary


def test_file_write_action():
    parser = OpenHandsEventParser()
    events = [FileWriteAction("/tmp/test.py", "print('hello')")]
    log = parser.parse_events(events)

    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.kind == ActionEntryKind.TOOL_USE
    assert entry.tool_use is not None
    assert entry.tool_use.arguments["path"] == "/tmp/test.py"
    assert entry.tool_use.arguments["content"] == "print('hello')"


def test_cmd_output_observation():
    parser = OpenHandsEventParser()
    events = [CmdOutputObservation("file1.py\nfile2.py", exit_code=0)]
    log = parser.parse_events(events)

    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.kind == ActionEntryKind.TOOL_RESULT
    assert entry.tool_result is not None
    assert entry.tool_result.output == "file1.py\nfile2.py"
    assert entry.tool_result.exit_code == 0
    assert entry.tool_result.success is True


def test_cmd_output_observation_failure():
    parser = OpenHandsEventParser()
    events = [CmdOutputObservation("error: not found", exit_code=1)]
    log = parser.parse_events(events)

    entry = log.entries[0]
    assert entry.tool_result is not None
    assert entry.tool_result.success is False
    assert entry.tool_result.exit_code == 1


def test_file_read_observation():
    parser = OpenHandsEventParser()
    events = [FileReadObservation("import sys")]
    log = parser.parse_events(events)

    entry = log.entries[0]
    assert entry.kind == ActionEntryKind.TOOL_RESULT
    assert entry.tool_result is not None
    assert entry.tool_result.output == "import sys"
    assert entry.tool_result.success is True  # No exit_code -> success


def test_full_conversation():
    parser = OpenHandsEventParser()
    events = [
        MessageAction("I'll check the files."),
        CmdRunAction("ls"),
        CmdOutputObservation("main.py\ntest.py", exit_code=0),
        FileWriteAction("/tmp/out.txt", "results"),
        MessageAction("Done!"),
    ]
    log = parser.parse_events(events)

    assert len(log.entries) == 5
    assert log.entries[0].kind == ActionEntryKind.ASSISTANT_TEXT
    assert log.entries[1].kind == ActionEntryKind.TOOL_USE
    assert log.entries[2].kind == ActionEntryKind.TOOL_RESULT
    assert log.entries[3].kind == ActionEntryKind.TOOL_USE
    assert log.entries[4].kind == ActionEntryKind.ASSISTANT_TEXT
    assert log.total_turns == 2


def test_unknown_events_skipped():
    parser = OpenHandsEventParser()
    events = [UnknownEvent()]
    log = parser.parse_events(events)

    assert len(log.entries) == 0


def test_output_truncation():
    parser = OpenHandsEventParser()
    long_output = "x" * 10000
    events = [CmdOutputObservation(long_output, exit_code=0)]
    log = parser.parse_events(events)

    entry = log.entries[0]
    assert entry.tool_result is not None
    assert entry.tool_result.output_length == 10000
    assert len(entry.tool_result.output) < 10000


def test_empty_events():
    parser = OpenHandsEventParser()
    log = parser.parse_events([])

    assert len(log.entries) == 0
    assert log.total_turns == 0


def test_sequence_numbers_are_sequential():
    parser = OpenHandsEventParser()
    events = [
        MessageAction("first"),
        CmdRunAction("echo"),
        CmdOutputObservation("ok", 0),
    ]
    log = parser.parse_events(events)

    assert [e.sequence_num for e in log.entries] == [1, 2, 3]

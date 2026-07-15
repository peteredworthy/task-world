"""Pure command applier for execution graph fixtures."""

from collections.abc import Mapping, Sequence
from itertools import chain
from typing import cast

from orchestrator.graph.commands.lifecycle import (
    Clock,
    GraphProjection,
    IdGenerator,
    NONTERMINAL_RUN_STATES,
    RUN_LIFECYCLE_TRANSITIONS,
    TERMINAL_RUN_STATES,
)
from orchestrator.graph.catalog import GraphCatalog
from orchestrator.graph.commands.callbacks import COMMAND_SPECIFICATIONS as CALLBACK_COMMAND_SPECS
from orchestrator.graph.commands.callbacks import RecordDecisionCommand
from orchestrator.graph.commands.file_state import (
    COMMAND_SPECIFICATIONS as FILE_STATE_COMMAND_SPECS,
)
from orchestrator.graph.commands.lifecycle import COMMAND_SPECIFICATIONS as LIFECYCLE_COMMAND_SPECS
from orchestrator.graph.commands.patches import COMMAND_SPECIFICATIONS as PATCH_COMMAND_SPECS
from orchestrator.graph.commands.patches import SubmitPatchCommand, SubmitPatchFields
from orchestrator.graph.commands.records import COMMAND_SPECIFICATIONS as RECORD_COMMAND_SPECS
from orchestrator.graph.commands.schedule import COMMAND_SPECIFICATIONS as SCHEDULE_COMMAND_SPECS
from orchestrator.graph.specifications import (
    CommandExecutionContext,
    HydratedEvent,
)
from orchestrator.graph.events.topology import (
    COMMAND_SPECIFICATIONS as TOPOLOGY_COMMAND_SPECS,
    SEED_COMPILED_EVENTS,
    SeedCompiledEventsCommand,
)

COMMAND_SPECIFICATION_GROUPS = (
    LIFECYCLE_COMMAND_SPECS,
    CALLBACK_COMMAND_SPECS,
    TOPOLOGY_COMMAND_SPECS,
    SCHEDULE_COMMAND_SPECS,
    PATCH_COMMAND_SPECS,
    RECORD_COMMAND_SPECS,
    FILE_STATE_COMMAND_SPECS,
)
COMMAND_SPECIFICATIONS = tuple(chain.from_iterable(COMMAND_SPECIFICATION_GROUPS))
_CATALOG_COMMAND_NAMES = frozenset(spec.name for spec in COMMAND_SPECIFICATIONS)


def apply_command(
    catalog: GraphCatalog,
    projection: GraphProjection,
    events: Sequence[HydratedEvent],
    command_type: str,
    payload: Mapping[str, object],
    context: CommandExecutionContext,
) -> list[HydratedEvent]:
    """Apply one catalog command against hydrated graph history."""
    if type(catalog) is not GraphCatalog:
        raise TypeError("graph command dispatch requires a GraphCatalog")
    specification = catalog.resolve_command(command_type)
    command = specification.validate(payload)
    if command_type == SEED_COMPILED_EVENTS.name:
        typed_command = cast(SeedCompiledEventsCommand, command)
        for event in typed_command.events:
            catalog.resolve_event(event.metadata.event_type).serialize(event)
    return specification.handle(command, projection, tuple(events), context)


__all__ = [
    "Clock",
    "GraphProjection",
    "IdGenerator",
    "RUN_LIFECYCLE_TRANSITIONS",
    "TERMINAL_RUN_STATES",
    "NONTERMINAL_RUN_STATES",
    "apply_command",
    "COMMAND_SPECIFICATIONS",
    "COMMAND_SPECIFICATION_GROUPS",
    "RecordDecisionCommand",
    "SubmitPatchCommand",
    "SubmitPatchFields",
]

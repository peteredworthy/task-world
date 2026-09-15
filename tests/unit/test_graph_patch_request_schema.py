"""Pure validation matrix for the operator graph-patch HTTP contract."""

import pytest
from pydantic import ValidationError

from orchestrator.api.routers.graph import SubmitGraphPatchRequest


@pytest.mark.parametrize(
    "payload",
    [
        {"patch_id": "p", "base_graph_position": "0", "ops": []},
        {"patch_id": "p", "base_graph_position": 0, "carryover_summary": "r", "ops": []},
        {"patch_id": "p", "base_graph_position": 0, "unknown": True, "ops": []},
        {"patch_id": "", "ops": []},
        {"patch_id": "p" * 201, "ops": []},
        {"patch_id": "not a patch id", "ops": []},
        {"rationale_record_id": "", "ops": []},
        {"rationale_record_id": "r" * 201, "ops": []},
        {"rationale_record_id": "not a rationale id", "ops": []},
        {"base_graph_position": -1, "ops": []},
        {"patch_id": "p"},
    ],
)
def test_operator_patch_request_rejects_noncanonical_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        SubmitGraphPatchRequest.model_validate(payload)

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.graph.events.leases import (
    EVENT_SPECIFICATIONS,
    LeaseGrantedPayload,
    LeaseRenewedPayload,
)


def test_lease_payloads_require_exact_identity_and_claims() -> None:
    with pytest.raises(ValidationError):
        LeaseGrantedPayload.model_validate({"lease_id": "lease-1", "node_id": "node-1"})
    with pytest.raises(ValidationError):
        LeaseGrantedPayload.model_validate(
            {
                "lease_id": "lease-1",
                "node_id": "node-1",
                "generation": "1",
                "execution_id": "exec-1",
                "base_snapshot_id": "snapshot-1",
                "expires_at": datetime.now(UTC),
                "resource_claims": (),
            }
        )


def test_lease_renewal_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        LeaseRenewedPayload.model_validate(
            {
                "lease_id": "lease-1",
                "node_id": "node-1",
                "generation": 1,
                "execution_id": "exec-1",
                "observed_at": datetime.now(UTC),
                "expires_at": datetime.now(UTC),
                "legacy_note": "no",
            }
        )


def test_only_five_strict_lease_events_are_registered() -> None:
    assert {spec.name for spec in EVENT_SPECIFICATIONS} == {
        "lease_granted",
        "lease_renewed",
        "lease_released",
        "lease_revoked",
        "lease_expired",
    }

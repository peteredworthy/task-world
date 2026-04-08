# Step 02 Plan Context: M2 - DB Migration and Persistence

## Milestone M2: DB Migration and Persistence

Persist the new fields to the database.

**Steps:**
1. Add `token_usage_by_model` JSON column to `AttemptModel` and `RunModel` in `db/orm/models.py`. [I-08, I-21]
2. Create Alembic migration adding both columns with default empty JSON array. [I-08, I-12, I-21]
3. Update `db/access/repositories.py` to serialize/deserialize the `token_usage_by_model` field when reading/writing attempts and runs. [I-08]
4. Integration test: create a run, verify empty `token_usage_by_model` persists and round-trips. [I-25]

**Verification:** Migration applies cleanly. Existing runs unaffected (empty list default). All tests pass. [I-24]

## Implementation Order

M2 depends on M1. M1-M4 are strictly sequential (each builds on the prior). M5 depends on M4. M6 depends on M5.

## Testing Strategy

| Milestone | Backend Tests | Frontend Tests | Manual Check |
|-----------|--------------|----------------|--------------|
| M2 | Integration: migration applies, round-trip serialization | N/A | N/A |

## Risk Mitigations

- **Migration safety**: Test migration on a copy of production DB before applying. Columns default to empty JSON array so existing rows are unaffected.
- **Backward compatibility**: Legacy flat fields always populated. Frontend falls back gracefully for pre-migration runs.
- **Incremental commits**: Each milestone committed separately. If M6 has issues, M1-M5 are safe and functional.

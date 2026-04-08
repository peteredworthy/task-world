# Step 02: Code Locations

## Code Locations

- `src/orchestrator/db/orm/models.py` — `AttemptModel` class lines 219–221: add `token_usage_by_model = Column(JSON, default=list)` column
- `src/orchestrator/db/orm/models.py` — `RunModel` class lines 87–89: add `token_usage_by_model = Column(JSON, default=list)` column
- `src/orchestrator/db/migrations/versions/` (new migration file): Alembic migration adding both JSON columns with `server_default='[]'`
- `src/orchestrator/db/access/repositories.py` — `_to_domain()` method lines 127–133, 279–281: deserialize JSON → `ModelTokenUsage` objects for attempts and runs
- `src/orchestrator/db/access/repositories.py` — `_to_model()` method lines 300–304, 420–424: serialize `ModelTokenUsage` → JSON for storage

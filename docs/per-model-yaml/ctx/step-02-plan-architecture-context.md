# Step 02: Architecture Context

## DB Schema Changes

### Alembic Migration

Add two JSON columns:

```python
# attempts table
op.add_column('attempts', sa.Column('token_usage_by_model', sa.JSON(), server_default='[]'))

# runs table
op.add_column('runs', sa.Column('token_usage_by_model', sa.JSON(), server_default='[]'))
```

No backfill needed. Old rows get empty arrays. New runs populate both the new JSON columns and the legacy flat fields.

### ORM Changes (db/orm/models.py)

```python
class AttemptModel(Base):
    # ... existing columns ...
    token_usage_by_model = Column(JSON, default=list)

class RunModel(Base):
    # ... existing columns ...
    token_usage_by_model = Column(JSON, default=list)
```

### Serialization / Deserialization

When writing: serialize `list[ModelTokenUsage]` to JSON list of dicts. When reading: deserialize JSON back to `list[ModelTokenUsage]`. Handle corrupt JSON gracefully (return empty list).

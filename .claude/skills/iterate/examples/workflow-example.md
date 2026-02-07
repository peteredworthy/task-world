# Example: Iterative Workflow for "Add Pagination to API"

## Phase 1: Task Breakdown

```
Original Request: "Add pagination to the /api/users endpoint"

Tasks Created:
1. Add pagination parameters to schema (offset, limit, defaults)
2. Update repository query to support pagination
3. Update API endpoint to use pagination
4. Add pagination metadata to response (total, page, has_more)
5. Write tests for pagination edge cases
```

## Phase 2: Execute & Verify Each Task

### Task 1: Schema Update

**Builder (haiku):**
```
Task(
  subagent_type="general-purpose",
  model="haiku",
  prompt="Add pagination query parameters to the user list schema:
    - offset: int, default 0, min 0
    - limit: int, default 20, min 1, max 100
    Update UserListRequest in api/schemas/users.py"
)
```

**Verifier (sonnet):**
```
Task(
  subagent_type="general-purpose",
  model="sonnet",
  prompt="VERIFY: Pagination parameters were added to UserListRequest.
    Check:
    1. offset and limit fields exist with correct types
    2. Default values are set
    3. Validation constraints are in place (min/max)
    4. Type hints are correct
    Report: PASS/FAIL and any gaps found."
)
```

**Result:** PASS - no gaps

### Task 2: Repository Query

**Builder (sonnet):**
```
Task(
  subagent_type="general-purpose",
  model="sonnet",  # Moderate complexity - SQL logic
  prompt="Update UserRepository.list_users() to accept offset and limit params.
    Apply them to the database query. Ensure efficient query execution."
)
```

**Verifier (sonnet):**
```
Task(
  subagent_type="general-purpose",
  model="sonnet",
  prompt="VERIFY: Repository pagination implementation.
    Check:
    1. Method signature accepts offset/limit
    2. Query applies OFFSET and LIMIT correctly
    3. Query is still efficient (no N+1, proper indexing considered)
    Report: PASS/FAIL and any gaps found."
)
```

**Result:** PARTIAL - Gap found: "No total count query for pagination metadata"

**Fix Builder (haiku):**
```
Task(
  subagent_type="general-purpose",
  model="haiku",
  prompt="Add a count_users() method to UserRepository that returns total user count.
    This is needed for pagination metadata."
)
```

**Re-verify (sonnet):** PASS

### Task 3-5: [Similar pattern continues...]

## Phase 3: Final Validation

**Final Validator (opus):**
```
Task(
  subagent_type="general-purpose",
  model="opus",
  prompt="FINAL VALIDATION for 'Add pagination to /api/users endpoint'

    Completed work:
    - Schema: offset/limit params with validation
    - Repository: paginated query + count method
    - Endpoint: accepts params, returns paginated results
    - Response: includes total, page, has_more metadata
    - Tests: edge cases covered (empty, first page, last page, invalid)

    Verify:
    1. Does this fully satisfy 'Add pagination to /api/users endpoint'?
    2. Any gaps between request and delivery?
    3. Do all parts integrate correctly?

    Report: COMPLETE/INCOMPLETE with gaps if any."
)
```

**Result:** COMPLETE - All requirements met, integration verified.

## Key Patterns Demonstrated

1. **Model selection matched to complexity:**
   - Schema changes → haiku (simple)
   - SQL logic → sonnet (moderate)
   - Final validation → opus (critical)

2. **Verification found a real gap:**
   - Missing count query for metadata
   - Fixed with targeted sub-agent
   - Re-verified before proceeding

3. **Clear, focused prompts:**
   - Each builder got specific instructions
   - Each verifier got explicit checklist

4. **Final validation caught nothing:**
   - Because iterative verification already fixed gaps
   - But still mandatory to confirm integration

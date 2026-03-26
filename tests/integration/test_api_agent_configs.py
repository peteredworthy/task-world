"""Integration tests for agent config CRUD API endpoints (/api/agents)."""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.runners import seed_default_agents
from orchestrator.api.app import create_app
from orchestrator.db import init_db


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app(db_path=":memory:", routine_dirs=[])
    await init_db(app.state.engine)
    async with app.state.session_factory() as session:
        await seed_default_agents(session)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()


# ---------------------------------------------------------------------------
# GET /api/agents - list seeded defaults
# ---------------------------------------------------------------------------


class TestListAgents:
    async def test_returns_200(self, client: AsyncClient) -> None:
        resp = await client.get("/api/agents")
        assert resp.status_code == 200

    async def test_returns_seeded_defaults(self, client: AsyncClient) -> None:
        resp = await client.get("/api/agents")
        data: list[dict[str, Any]] = resp.json()
        names = {a["name"] for a in data}
        assert {"Planner", "Builder", "Verifier"}.issubset(names)

    async def test_agents_have_required_fields(self, client: AsyncClient) -> None:
        resp = await client.get("/api/agents")
        for agent in resp.json():
            assert "id" in agent
            assert "name" in agent
            assert "system_prompt" in agent
            assert "default_prompt" in agent
            assert "model_profile" in agent
            assert "created_at" in agent
            assert "updated_at" in agent

    async def test_agents_ordered_alphabetically(self, client: AsyncClient) -> None:
        resp = await client.get("/api/agents")
        names = [a["name"] for a in resp.json()]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# POST /api/agents - create
# ---------------------------------------------------------------------------


class TestCreateAgent:
    async def test_create_returns_201(self, client: AsyncClient) -> None:
        payload = {
            "name": "MyAgent",
            "system_prompt": "Be helpful.",
            "model_profile": "coder",
        }
        resp = await client.post("/api/agents", json=payload)
        assert resp.status_code == 201

    async def test_create_returns_schema(self, client: AsyncClient) -> None:
        payload = {
            "name": "SchemaAgent",
            "system_prompt": "Do things.",
            "default_prompt": "Factory default.",
            "model_profile": "architect",
        }
        resp = await client.post("/api/agents", json=payload)
        data = resp.json()
        assert data["name"] == "SchemaAgent"
        assert data["system_prompt"] == "Do things."
        assert data["default_prompt"] == "Factory default."
        assert data["model_profile"] == "architect"
        assert data["id"]

    async def test_create_duplicate_name_returns_409(self, client: AsyncClient) -> None:
        payload = {"name": "Planner", "system_prompt": "duplicate"}
        resp = await client.post("/api/agents", json=payload)
        assert resp.status_code == 409

    async def test_create_missing_name_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post("/api/agents", json={"system_prompt": "no name"})
        assert resp.status_code == 422

    async def test_create_empty_name_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post("/api/agents", json={"name": "", "system_prompt": "empty name"})
        assert resp.status_code == 422

    async def test_create_missing_system_prompt_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post("/api/agents", json={"name": "NoPrompt"})
        assert resp.status_code == 422

    async def test_create_default_model_profile_is_coder(self, client: AsyncClient) -> None:
        payload = {"name": "DefaultProfile", "system_prompt": "test"}
        resp = await client.post("/api/agents", json=payload)
        assert resp.json()["model_profile"] == "coder"

    async def test_create_appears_in_list(self, client: AsyncClient) -> None:
        await client.post("/api/agents", json={"name": "ListMe", "system_prompt": "hi"})
        resp = await client.get("/api/agents")
        names = [a["name"] for a in resp.json()]
        assert "ListMe" in names


# ---------------------------------------------------------------------------
# GET /api/agents/{id}
# ---------------------------------------------------------------------------


class TestGetAgent:
    async def test_get_by_id_returns_200(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/api/agents", json={"name": "Fetchable", "system_prompt": "here"}
        )
        agent_id = create_resp.json()["id"]
        resp = await client.get(f"/api/agents/{agent_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == agent_id

    async def test_get_seeded_agent_by_id(self, client: AsyncClient) -> None:
        agents = (await client.get("/api/agents")).json()
        builder = next(a for a in agents if a["name"] == "Builder")
        resp = await client.get(f"/api/agents/{builder['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Builder"

    async def test_get_nonexistent_returns_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/agents/does-not-exist")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/agents/{id}
# ---------------------------------------------------------------------------


class TestUpdateAgent:
    async def test_update_name(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/api/agents", json={"name": "OldName", "system_prompt": "old"}
        )
        agent_id = create_resp.json()["id"]
        resp = await client.put(f"/api/agents/{agent_id}", json={"name": "NewName"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "NewName"

    async def test_update_system_prompt(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/api/agents", json={"name": "PromptAgent", "system_prompt": "old prompt"}
        )
        agent_id = create_resp.json()["id"]
        resp = await client.put(f"/api/agents/{agent_id}", json={"system_prompt": "new prompt"})
        assert resp.status_code == 200
        assert resp.json()["system_prompt"] == "new prompt"

    async def test_update_model_profile(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/api/agents", json={"name": "ProfileAgent", "system_prompt": "x"}
        )
        agent_id = create_resp.json()["id"]
        resp = await client.put(f"/api/agents/{agent_id}", json={"model_profile": "architect"})
        assert resp.status_code == 200
        assert resp.json()["model_profile"] == "architect"

    async def test_partial_update_preserves_other_fields(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/api/agents",
            json={"name": "Partial", "system_prompt": "original", "model_profile": "coder"},
        )
        agent_id = create_resp.json()["id"]
        resp = await client.put(f"/api/agents/{agent_id}", json={"name": "PartialUpdated"})
        data = resp.json()
        assert data["name"] == "PartialUpdated"
        assert data["system_prompt"] == "original"
        assert data["model_profile"] == "coder"

    async def test_update_nonexistent_returns_404(self, client: AsyncClient) -> None:
        resp = await client.put("/api/agents/ghost-id", json={"name": "X"})
        assert resp.status_code == 404

    async def test_update_to_conflicting_name_returns_409(self, client: AsyncClient) -> None:
        resp_a = await client.post("/api/agents", json={"name": "ConflictA", "system_prompt": "a"})
        await client.post("/api/agents", json={"name": "ConflictB", "system_prompt": "b"})
        agent_id = resp_a.json()["id"]
        resp = await client.put(f"/api/agents/{agent_id}", json={"name": "ConflictB"})
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# DELETE /api/agents/{id}
# ---------------------------------------------------------------------------


class TestDeleteAgent:
    async def test_delete_returns_204(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/api/agents", json={"name": "ToDelete", "system_prompt": "bye"}
        )
        agent_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/agents/{agent_id}")
        assert resp.status_code == 204

    async def test_deleted_agent_not_in_list(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/api/agents", json={"name": "Gone", "system_prompt": "poof"}
        )
        agent_id = create_resp.json()["id"]
        await client.delete(f"/api/agents/{agent_id}")
        agents = (await client.get("/api/agents")).json()
        assert not any(a["id"] == agent_id for a in agents)

    async def test_deleted_agent_returns_404_on_get(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/api/agents", json={"name": "Ephemeral", "system_prompt": "gone"}
        )
        agent_id = create_resp.json()["id"]
        await client.delete(f"/api/agents/{agent_id}")
        resp = await client.get(f"/api/agents/{agent_id}")
        assert resp.status_code == 404

    async def test_delete_nonexistent_returns_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/agents/no-such-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/agents/{id}/reset-prompt
# ---------------------------------------------------------------------------


class TestResetPrompt:
    async def test_reset_restores_default_prompt(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/api/agents",
            json={
                "name": "Resettable",
                "system_prompt": "original",
                "default_prompt": "factory default",
            },
        )
        agent_id = create_resp.json()["id"]
        # Modify the system prompt
        await client.put(f"/api/agents/{agent_id}", json={"system_prompt": "custom modified"})
        # Reset
        resp = await client.post(f"/api/agents/{agent_id}/reset-prompt")
        assert resp.status_code == 200
        assert resp.json()["system_prompt"] == "factory default"

    async def test_reset_nonexistent_returns_404(self, client: AsyncClient) -> None:
        resp = await client.post("/api/agents/missing/reset-prompt")
        assert resp.status_code == 404

    async def test_reset_without_default_returns_400(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/api/agents",
            json={
                "name": "NoDefaultAgent",
                "system_prompt": "custom",
                "default_prompt": "",
            },
        )
        agent_id = create_resp.json()["id"]
        resp = await client.post(f"/api/agents/{agent_id}/reset-prompt")
        assert resp.status_code == 400

    async def test_reset_seeded_agent_restores_original(self, client: AsyncClient) -> None:
        agents = (await client.get("/api/agents")).json()
        builder = next(a for a in agents if a["name"] == "Builder")
        original_prompt = builder["default_prompt"]
        agent_id = builder["id"]

        # Modify
        await client.put(f"/api/agents/{agent_id}", json={"system_prompt": "hacked!"})
        # Reset
        resp = await client.post(f"/api/agents/{agent_id}/reset-prompt")
        assert resp.status_code == 200
        assert resp.json()["system_prompt"] == original_prompt


# ---------------------------------------------------------------------------
# Full CRUD lifecycle
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    async def test_create_read_update_delete(self, client: AsyncClient) -> None:
        # Create
        create_resp = await client.post(
            "/api/agents",
            json={
                "name": "Lifecycle",
                "system_prompt": "step 1",
                "default_prompt": "step 1",
                "model_profile": "coder",
            },
        )
        assert create_resp.status_code == 201
        agent_id = create_resp.json()["id"]

        # Read
        get_resp = await client.get(f"/api/agents/{agent_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "Lifecycle"

        # Update
        put_resp = await client.put(
            f"/api/agents/{agent_id}",
            json={"system_prompt": "step 2", "model_profile": "architect"},
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["system_prompt"] == "step 2"
        assert put_resp.json()["model_profile"] == "architect"

        # Reset prompt
        reset_resp = await client.post(f"/api/agents/{agent_id}/reset-prompt")
        assert reset_resp.status_code == 200
        assert reset_resp.json()["system_prompt"] == "step 1"

        # Delete
        del_resp = await client.delete(f"/api/agents/{agent_id}")
        assert del_resp.status_code == 204

        # Confirm gone
        assert (await client.get(f"/api/agents/{agent_id}")).status_code == 404

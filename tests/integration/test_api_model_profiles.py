"""Integration tests for model profiles and agent runner model-default API endpoints."""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import ModelProfile
from orchestrator.db import init_db


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app(db_path=":memory:", routine_dirs=[])
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()


class TestListModelProfiles:
    async def test_returns_all_profiles(self, client: AsyncClient) -> None:
        response = await client.get("/api/model-profiles")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == len(ModelProfile)

    async def test_profile_names_match_enum(self, client: AsyncClient) -> None:
        response = await client.get("/api/model-profiles")
        assert response.status_code == 200
        names = {item["name"] for item in response.json()}
        expected = {p.value for p in ModelProfile}
        assert names == expected

    async def test_each_profile_has_description(self, client: AsyncClient) -> None:
        response = await client.get("/api/model-profiles")
        assert response.status_code == 200
        for item in response.json():
            assert "description" in item
            assert isinstance(item["description"], str)
            assert len(item["description"]) > 0


class TestAgentRunnerModelDefaultEndpoints:
    async def test_get_model_defaults_empty_for_unknown_runner(self, client: AsyncClient) -> None:
        response = await client.get("/api/agent-runners/cli_subprocess/model-profile-defaults")
        assert response.status_code == 200
        data = response.json()
        assert data["agent_runner_type"] == "cli_subprocess"
        assert data["model_profile_defaults"] == {}

    async def test_set_and_get_model_defaults_roundtrip(self, client: AsyncClient) -> None:
        payload = {
            "agent_runner_type": "claude_sdk",
            "model_profile_defaults": {
                "coder": "claude-sonnet-4-6",
                "architect": "claude-opus-4-6",
            },
        }
        put_resp = await client.put(
            "/api/agent-runners/claude_sdk/model-profile-defaults", json=payload
        )
        assert put_resp.status_code == 200
        put_data = put_resp.json()
        assert put_data["agent_runner_type"] == "claude_sdk"
        assert put_data["model_profile_defaults"]["coder"] == "claude-sonnet-4-6"
        assert put_data["model_profile_defaults"]["architect"] == "claude-opus-4-6"

        get_resp = await client.get("/api/agent-runners/claude_sdk/model-profile-defaults")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data["model_profile_defaults"]["coder"] == "claude-sonnet-4-6"
        assert get_data["model_profile_defaults"]["architect"] == "claude-opus-4-6"

    async def test_put_replaces_all_existing_model_defaults(self, client: AsyncClient) -> None:
        first = {
            "agent_runner_type": "cli_subprocess",
            "model_profile_defaults": {"coder": "model-a", "designer": "model-b"},
        }
        await client.put("/api/agent-runners/cli_subprocess/model-profile-defaults", json=first)

        second = {
            "agent_runner_type": "cli_subprocess",
            "model_profile_defaults": {"summarizer": "model-c"},
        }
        await client.put("/api/agent-runners/cli_subprocess/model-profile-defaults", json=second)

        get_resp = await client.get("/api/agent-runners/cli_subprocess/model-profile-defaults")
        data = get_resp.json()
        # Old entries should be gone; only new entry remains
        assert "coder" not in data["model_profile_defaults"]
        assert "designer" not in data["model_profile_defaults"]
        assert data["model_profile_defaults"]["summarizer"] == "model-c"

    async def test_profiles_isolated_per_runner_type(self, client: AsyncClient) -> None:
        await client.put(
            "/api/agent-runners/claude_sdk/model-profile-defaults",
            json={
                "agent_runner_type": "claude_sdk",
                "model_profile_defaults": {"coder": "sdk-model"},
            },
        )
        await client.put(
            "/api/agent-runners/cli_subprocess/model-profile-defaults",
            json={
                "agent_runner_type": "cli_subprocess",
                "model_profile_defaults": {"coder": "cli-model"},
            },
        )

        sdk_resp = await client.get("/api/agent-runners/claude_sdk/model-profile-defaults")
        cli_resp = await client.get("/api/agent-runners/cli_subprocess/model-profile-defaults")

        assert sdk_resp.json()["model_profile_defaults"]["coder"] == "sdk-model"
        assert cli_resp.json()["model_profile_defaults"]["coder"] == "cli-model"

    async def test_put_empty_model_defaults_clears_all(self, client: AsyncClient) -> None:
        await client.put(
            "/api/agent-runners/openhands_local/model-profile-defaults",
            json={
                "agent_runner_type": "openhands_local",
                "model_profile_defaults": {"coder": "some-model"},
            },
        )
        await client.put(
            "/api/agent-runners/openhands_local/model-profile-defaults",
            json={
                "agent_runner_type": "openhands_local",
                "model_profile_defaults": {},
            },
        )
        get_resp = await client.get("/api/agent-runners/openhands_local/model-profile-defaults")
        assert get_resp.json()["model_profile_defaults"] == {}

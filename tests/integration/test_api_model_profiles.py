"""Integration tests for model profiles and runner profile API endpoints."""

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


class TestRunnerProfileEndpoints:
    async def test_get_profiles_empty_for_unknown_runner(self, client: AsyncClient) -> None:
        response = await client.get("/api/agent-runners/cli_subprocess/profiles")
        assert response.status_code == 200
        data = response.json()
        assert data["runner_type"] == "cli_subprocess"
        assert data["profiles"] == {}

    async def test_set_and_get_profiles_roundtrip(self, client: AsyncClient) -> None:
        payload = {
            "runner_type": "claude_sdk",
            "profiles": {
                "coder": "claude-sonnet-4-6",
                "architect": "claude-opus-4-6",
            },
        }
        put_resp = await client.put("/api/agent-runners/claude_sdk/profiles", json=payload)
        assert put_resp.status_code == 200
        put_data = put_resp.json()
        assert put_data["runner_type"] == "claude_sdk"
        assert put_data["profiles"]["coder"] == "claude-sonnet-4-6"
        assert put_data["profiles"]["architect"] == "claude-opus-4-6"

        get_resp = await client.get("/api/agent-runners/claude_sdk/profiles")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data["profiles"]["coder"] == "claude-sonnet-4-6"
        assert get_data["profiles"]["architect"] == "claude-opus-4-6"

    async def test_put_replaces_all_existing_profiles(self, client: AsyncClient) -> None:
        first = {
            "runner_type": "cli_subprocess",
            "profiles": {"coder": "model-a", "designer": "model-b"},
        }
        await client.put("/api/agent-runners/cli_subprocess/profiles", json=first)

        second = {
            "runner_type": "cli_subprocess",
            "profiles": {"summarizer": "model-c"},
        }
        await client.put("/api/agent-runners/cli_subprocess/profiles", json=second)

        get_resp = await client.get("/api/agent-runners/cli_subprocess/profiles")
        data = get_resp.json()
        # Old entries should be gone; only new entry remains
        assert "coder" not in data["profiles"]
        assert "designer" not in data["profiles"]
        assert data["profiles"]["summarizer"] == "model-c"

    async def test_profiles_isolated_per_runner_type(self, client: AsyncClient) -> None:
        await client.put(
            "/api/agent-runners/claude_sdk/profiles",
            json={"runner_type": "claude_sdk", "profiles": {"coder": "sdk-model"}},
        )
        await client.put(
            "/api/agent-runners/cli_subprocess/profiles",
            json={"runner_type": "cli_subprocess", "profiles": {"coder": "cli-model"}},
        )

        sdk_resp = await client.get("/api/agent-runners/claude_sdk/profiles")
        cli_resp = await client.get("/api/agent-runners/cli_subprocess/profiles")

        assert sdk_resp.json()["profiles"]["coder"] == "sdk-model"
        assert cli_resp.json()["profiles"]["coder"] == "cli-model"

    async def test_put_empty_profiles_clears_all(self, client: AsyncClient) -> None:
        await client.put(
            "/api/agent-runners/openhands_local/profiles",
            json={"runner_type": "openhands_local", "profiles": {"coder": "some-model"}},
        )
        await client.put(
            "/api/agent-runners/openhands_local/profiles",
            json={"runner_type": "openhands_local", "profiles": {}},
        )
        get_resp = await client.get("/api/agent-runners/openhands_local/profiles")
        assert get_resp.json()["profiles"] == {}

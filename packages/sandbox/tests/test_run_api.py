from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
from django.test import Client


@pytest.mark.django_db
def test_start_run_accepts_request_when_routes_are_introspected() -> None:
    from agent_server.api.runs import StartRunRequest
    from agent_server.urls import api

    async def _noop_scan(task: str, *, conversation_id: str, request):
        return task

    async def _noop_run_agent(**kwargs) -> None:
        return None

    async def _noop_title(*args, **kwargs) -> None:
        return None

    # Force the same startup/schema-generation path that was surfacing the
    # incomplete QueryParams/StartRunRequest model error before request parsing.
    assert StartRunRequest.__pydantic_complete__ is True
    _ = api.urls

    client = Client()
    with (
        patch.dict(os.environ, {"API_KEY": "test-api-key"}, clear=False),
        patch("agent_server.api.runs._scan_task_for_dlp", _noop_scan),
        patch("agent_server.api.runs._get_memory_store", return_value=object()),
        patch("agent_server.api.runs._generate_conversation_title_and_icon", _noop_title),
        patch("agent_server.engine.run._run_agent", _noop_run_agent),
    ):
        response = client.post(
            "/runs",
            data=json.dumps({"task": "build a clone"}),
            content_type="application/json",
            HTTP_X_API_KEY="test-api-key",
        )

    assert response.status_code == 201, response.content.decode()
    body = response.json()
    assert body["status"] == "running"
    assert body["run_id"]
    assert body["conversation_id"] == body["run_id"]

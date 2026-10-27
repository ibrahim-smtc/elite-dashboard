"""
Tests for mcp/outbound_server.py.
Run with: python -m pytest mcp/test_outbound_server.py

Uses a mock Google Sheets service object: runs 100% locally with NO network,
NO Google credentials, and NO database required.
"""

from __future__ import annotations

import asyncio
import os
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import outbound_server as obs


class FakeValues:
    def __init__(self, g_column_data: list[list[str]]):
        self.g_data = g_column_data
        self.last_update_range = None
        self.last_update_body = None

    def get(self, spreadsheetId, range):
        class Request:
            def __init__(self, data):
                self.data = data

            def execute(self):
                return {"values": self.data}

        return Request(self.g_data)

    def update(self, spreadsheetId, range, valueInputOption, body):
        self.last_update_range = range
        self.last_update_body = body

        class Request:
            def execute(self):
                return {"updatedRows": 1}

        return Request()


class FakeSheetsService:
    def __init__(self, g_column_data: list[list[str]]):
        self.fake_values = FakeValues(g_column_data)

    def spreadsheets(self):
        class Spreadsheets:
            def __init__(self, values_obj):
                self._values = values_obj

            def values(self):
                return self._values

        return Spreadsheets(self.fake_values)


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("OUTBOUND_MCP_TOKEN", "test-secret-token")
    monkeypatch.setenv("SHEET_ID", "test-sheet-123")
    monkeypatch.setenv("SHEET_TAB", "Leads")


def call(monkeypatch, args: dict, token: str | None = "test-secret-token"):
    headers = {"authorization": f"Bearer {token}"} if token else {}
    monkeypatch.setattr(obs, "get_http_headers", lambda include_all=False: headers)

    async def run():
        async with Client(obs.mcp) as c:
            return (await c.call_tool("save_call_outcome", args)).structured_content

    return asyncio.run(run())


def test_row_found_and_written(mock_env, monkeypatch):
    fake_service = FakeSheetsService([["uuid-001"], ["uuid-002"]])
    monkeypatch.setattr(obs, "get_sheets_service", lambda: fake_service)

    result = call(monkeypatch, {
        "contact_id": "uuid-002",
        "summary": "Customer interested in Virtus GT.",
        "lead_type": "Hot",
    })

    assert result == {"row": 3, "status": "Done"}
    assert fake_service.fake_values.last_update_range == "Leads!D3:F3"
    assert fake_service.fake_values.last_update_body == {
        "values": [["Customer interested in Virtus GT.", "Hot", "Done"]]
    }


def test_id_not_found_raises_tool_error(mock_env, monkeypatch):
    fake_service = FakeSheetsService([["uuid-001"]])
    monkeypatch.setattr(obs, "get_sheets_service", lambda: fake_service)

    with pytest.raises(ToolError, match="not found"):
        call(monkeypatch, {
            "contact_id": "missing-uuid",
            "summary": "Some summary",
            "lead_type": "Warm",
        })


def test_invalid_lead_type_rejected(mock_env, monkeypatch):
    fake_service = FakeSheetsService([["uuid-001"]])
    monkeypatch.setattr(obs, "get_sheets_service", lambda: fake_service)

    with pytest.raises(Exception):
        call(monkeypatch, {
            "contact_id": "uuid-001",
            "summary": "Valid summary",
            "lead_type": "InvalidType",
        })


def test_missing_or_wrong_bearer_token_rejected(mock_env, monkeypatch):
    fake_service = FakeSheetsService([["uuid-001"]])
    monkeypatch.setattr(obs, "get_sheets_service", lambda: fake_service)

    # Wrong token
    with pytest.raises(ToolError, match="Unauthorized"):
        call(monkeypatch, {"contact_id": "uuid-001", "summary": "Hi", "lead_type": "Cold"}, token="wrong-token")

    # Missing token
    with pytest.raises(ToolError, match="Unauthorized"):
        call(monkeypatch, {"contact_id": "uuid-001", "summary": "Hi", "lead_type": "Cold"}, token=None)


def test_token_env_unset_fails_closed(monkeypatch):
    monkeypatch.delenv("OUTBOUND_MCP_TOKEN", raising=False)
    fake_service = FakeSheetsService([["uuid-001"]])
    monkeypatch.setattr(obs, "get_sheets_service", lambda: fake_service)

    with pytest.raises(ToolError, match="Unauthorized"):
        call(monkeypatch, {"contact_id": "uuid-001", "summary": "Hi", "lead_type": "Cold"}, token="any-token")

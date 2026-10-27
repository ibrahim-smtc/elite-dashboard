"""
MCP server for the outbound sales call write-back (Step 2).
A single-tool FastMCP server that updates columns D, E, F in a Google Sheet
once an outbound AI conversation finishes:
    - D: Summary (max 400 chars)
    - E: Lead Type (Hot, Warm, or Cold)
    - F: Status ("Done")
Never reads or exposes any customer data (columns A, B, C) back through the tool.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Annotated, Literal
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from google.oauth2 import service_account
from googleapiclient.discovery import build
from pydantic import Field


# Load .env from repo root if present
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

log = logging.getLogger("outbound_mcp")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_sheets_service = None
_sheets_lock = threading.Lock()

def get_sheets_service():
    """Lazily initialize and cache the Google Sheets API resource."""
    global _sheets_service
    if _sheets_service is not None:
        return _sheets_service

    with _sheets_lock:
        if _sheets_service is not None:
            return _sheets_service

        raw_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        key_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()

        creds = None
        if raw_json:
            try:
                info = json.loads(raw_json)
                creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
            except Exception as e:
                log.error("Failed to parse GOOGLE_SERVICE_ACCOUNT_JSON: %s", e)
                raise ToolError("Google Service Account configuration error.") from None
        elif key_file and Path(key_file).exists():
            creds = service_account.Credentials.from_service_account_file(key_file, scopes=SCOPES)
        else:
            raise ToolError("No Google Service Account credentials configured (JSON or file).")
        _sheets_service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        return _sheets_service

# ---------------------------------------------------------------------------
# FastMCP Setup & Auth Guard
# ---------------------------------------------------------------------------

mcp = FastMCP("elite-outbound-mcp",
    instructions="Outbound call write-back server for Elite Volkswagen.",
    mask_error_details=True,  # Never leak internal tracebacks, JSON keys, or sheet details
)

def verify_bearer_token() -> None:
    """
    Fail closed: reject every call if OUTBOUND_MCP_TOKEN is unset or empty.
    FastMCP's get_http_headers() strips Authorization unless include_all=True is used.
    """
    expected = os.environ.get("OUTBOUND_MCP_TOKEN", "").strip()
    if not expected:
        raise ToolError("Unauthorized: OUTBOUND_MCP_TOKEN is not configured.")

    headers = get_http_headers(include_all=True)
    auth_header = headers.get("authorization", "")

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip(), expected):
        raise ToolError("Unauthorized: invalid or missing Bearer token.")


# ---------------------------------------------------------------------------
# Tool: save_call_outcome
# ---------------------------------------------------------------------------

LeadType = Literal["Hot", "Warm", "Cold"]

@mcp.tool
def save_call_outcome(
    contact_id: Annotated[str, Field(description="The Call ID (UUID) stored in column G of the sheet.")],
    summary: Annotated[str, Field(max_length=400, description="1-2 sentence summary of the conversation.")],
    lead_type: Annotated[LeadType, Field(description="Lead qualification: Hot, Warm, or Cold.")] ) -> dict:

    """Write back the result of an outbound call into Google Sheets.
    Searches column G for contact_id and updates D, E, F with summary, lead_type, and 'Done'."""
    verify_bearer_token()

    target_id = (contact_id or "").strip()
    if not target_id:
        raise ToolError("contact_id is required.")

    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        raise ToolError("SHEET_ID is not configured.")

    tab = os.environ.get("SHEET_TAB", "Leads").strip() or "Leads"

    service = get_sheets_service()

    # 1. Read ONLY column G (G2:G) to find the matching row. Never read columns A-C
    try:
        read_res = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=f"{tab}!G2:G")
            .execute()
        )

    except Exception as e:
        log.error("Failed to read column G from Google Sheets: %s", e)
        raise ToolError("Failed to access Google Sheets.") from None

    rows = read_res.get("values", [])
    matched_row: int | None = None

    for idx, row in enumerate(rows):
        if row and row[0].strip() == target_id:
            matched_row = idx + 2  # G2 is index 0 -> row 2
            break

    if matched_row is None:
        raise ToolError(f"Call ID '{target_id}' was not found in the sheet.")

    # 2. Write columns D, E, F in ONE values.update cal
    update_range = f"{tab}!D{matched_row}:F{matched_row}"
    clean_summary = summary.strip()[:400]
    body = {
        "values": [[clean_summary, lead_type, "Done"]]
    }

    try:
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=update_range,
            valueInputOption="RAW",
            body=body,
        ).execute()

    except Exception as e:
        log.error("Failed to update row %d in Google Sheets: %s", matched_row, e)
        raise ToolError("Failed to update Google Sheets.") from None

    log.info("Updated row %d for call ID %s (%s)", matched_row, target_id, lead_type)
    return {"row": matched_row, "status": "Done"}


# ---------------------------------------------------------------------------
# Main tester functon
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    mcp.run(
        transport="http",
        show_banner=False,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("OUTBOUND_PORT") or 8766),
        path="/mcp",
        stateless_http=True,
        json_response=True,
    )
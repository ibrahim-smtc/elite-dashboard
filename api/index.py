"""
Vercel Serverless Function entrypoint for Volkswagen Elite Motors CRM Dashboard.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path so 'app' and sibling modules import correctly in serverless environment
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app

# Export for ASGI
__all__ = ["app"]

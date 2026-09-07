"""Shared helpers for tools in this project.

Keeps env loading and paths consistent so each tool script stays small.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is optional until a tool needs secrets
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / ".tmp"


def load_env() -> None:
    """Load .env from the project root if python-dotenv is installed."""
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env")


def require_env(name: str) -> str:
    """Return an env var or raise a clear error naming what's missing."""
    load_env()
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name} (set it in .env)")
    return value


def tmp_path(name: str) -> Path:
    """Path inside .tmp/, creating the directory if needed."""
    TMP.mkdir(exist_ok=True)
    return TMP / name

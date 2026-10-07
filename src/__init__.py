"""Shared package initialization for the assessment starter pack.

A local .env file is loaded automatically (without overriding variables already
set by the operating system). This keeps `python run_local.py`, the public eval
runner, and direct module usage consistent.
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)

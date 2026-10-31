"""Shared setup for the CLI, the MCP server and the app: where data lives, which device to use."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .device import FileSource, PhoneSource, SimSource, Source
from .session import Session

DATA = Path(os.environ.get("HOMESCREEN_DATA") or Path.home() / "Library/Application Support/homescreen-mcp")


def booted_sim() -> str:
    devs = json.loads(subprocess.run(["xcrun", "simctl", "list", "devices", "booted", "-j"],
                                     capture_output=True, text=True, check=True).stdout)["devices"]
    booted = [d["udid"] for items in devs.values() for d in items if d["state"] == "Booted"]
    if len(booted) != 1:
        raise RuntimeError(f"HOMESCREEN_SIM=booted needs exactly one booted simulator, found {len(booted)}")
    return booted[0]


def make_source() -> Source:
    """HOMESCREEN_FIXTURE (a saved layout) > HOMESCREEN_SIM (booted|udid) > USB iPhone."""
    fixture, sim = os.environ.get("HOMESCREEN_FIXTURE"), os.environ.get("HOMESCREEN_SIM")
    if fixture:
        return FileSource(fixture)
    if sim:
        return SimSource(booted_sim() if sim == "booted" else sim)
    return PhoneSource(os.environ.get("HOMESCREEN_UDID"))


_session: Session | None = None


def session() -> Session:
    global _session
    if _session is None:
        _session = Session(make_source(), DATA)
    return _session

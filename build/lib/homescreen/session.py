"""Draft, backups and the guarded apply.

Rules:
- Edits only ever touch the draft. The phone is written by apply() and restore() alone.
- apply() needs the token from the latest diff, refuses if the draft has problems or the
  phone changed since it was read, backs up first, verifies after, and never retries.
"""

from __future__ import annotations

import copy
import datetime as dt
import plistlib
from pathlib import Path
from typing import Any, Callable

from . import colors
from .device import Source
from .model import Layout, LayoutError, structure

KEEP_READS = 10
MAX_UNDO = 200


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _pack(state: list[Any], library: list[Any] | None) -> bytes:
    blob: dict[str, Any] = {"state": state}
    if library is not None:
        blob["library"] = library
    return plistlib.dumps(blob, fmt=plistlib.FMT_BINARY)


def _unpack(data: bytes) -> tuple[list[Any], list[Any] | None]:
    blob = plistlib.loads(data)
    if isinstance(blob, list):  # backups from before the App Library existed
        return blob, None
    return blob["state"], blob.get("library")


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-._" else "_" for c in s)


class Session:
    def __init__(self, source: Source, data_dir: str | Path):
        self.source = source
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.layout: Layout | None = None
        self.device_id: str | None = None
        self.info: dict[str, Any] = {}
        self.usage: dict[str, Any] | None = None  # Screen Time opens, loaded on request
        self._undo: list[tuple[list[Any], list[Any] | None, list[Any]]] = []
        self._redo: list[tuple[list[Any], list[Any] | None, list[Any]]] = []
        self._load_draft()

    # ---- persistence ------------------------------------------------------------

    @property
    def draft_path(self) -> Path:
        return self.dir / "draft.plist"

    def _dev_dir(self, kind: str) -> Path:
        p = self.dir / kind / _safe(self.device_id or "unknown")
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _save_draft(self) -> None:
        assert self.layout is not None
        blob = {"device": self.device_id, "info": self.info, "source": self.layout.source, "state": self.layout.to_state(),
                "source_library": self.layout.source_library, "library": self.layout.to_library(),
                "bank": self.layout.to_bank()}
        blob = {k: v for k, v in blob.items() if v is not None}  # plists have no null
        self.draft_path.write_bytes(plistlib.dumps(blob, fmt=plistlib.FMT_BINARY))

    def _load_draft(self) -> None:
        if self.draft_path.exists():
            blob = plistlib.loads(self.draft_path.read_bytes())
            self.device_id = blob["device"]
            self.info = blob.get("info", {})
            self.layout = Layout(blob["state"], source=blob["source"], library=blob.get("library"),
                                 source_library=blob.get("source_library"), bank=blob.get("bank"))

    def require(self) -> Layout:
        if self.layout is None:
            raise LayoutError("no layout loaded yet; call read first")
        return self.layout

    def edited(self) -> None:
        self._save_draft()

    # ---- edits with undo ----------------------------------------------------------

    def _snap(self) -> tuple[list[Any], list[Any] | None, list[Any]]:
        lay = self.require()
        return copy.deepcopy(lay.to_state()), copy.deepcopy(lay.to_library()), copy.deepcopy(lay.to_bank())

    def _load_snap(self, snap: tuple[list[Any], list[Any] | None, list[Any]]) -> None:
        lay = self.require()
        self.layout = Layout(snap[0], lay.page_slots, lay.dock_slots, source=lay.source,
                             library=snap[1], source_library=lay.source_library, bank=snap[2])

    def edit(self, fn: Callable[[Layout], Any]) -> Any:
        """Run fn on the draft as one undoable step. If it raises, the draft is left untouched."""
        before = self._snap()
        try:
            out = fn(self.require())
        except Exception:
            self._load_snap(before)
            raise
        self._undo.append(before)
        del self._undo[:-MAX_UNDO]
        self._redo.clear()
        self._save_draft()
        return out

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snap())
        self._load_snap(self._undo.pop())
        self._save_draft()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snap())
        self._load_snap(self._redo.pop())
        self._save_draft()
        return True

    def load_usage(self, days: int = 30) -> dict[str, Any]:
        from . import usage
        lay = self.require()
        known = {n.bundle_id for n in lay.nodes.values() if n.bundle_id}
        self.usage = usage.load(known, days)
        return self.usage

    def history(self) -> dict[str, int]:
        return {"undo": len(self._undo), "redo": len(self._redo)}

    # ---- read -------------------------------------------------------------------

    async def read(self) -> dict[str, Any]:
        info = await self.source.info()
        self.device_id = info.get("UniqueDeviceID") or self.source.name
        self.info = {k: v for k, v in info.items() if k in ("DeviceName", "ProductType", "ProductVersion")}
        state, library = await self.source.read()
        reads = self._dev_dir("reads")
        (reads / f"{_stamp()}.plist").write_bytes(_pack(state, library))
        for old in sorted(reads.glob("*.plist"))[:-KEEP_READS]:
            old.unlink()
        self.layout = Layout(state, library=library)
        self._undo.clear()
        self._redo.clear()
        self._save_draft()
        return {"device": {k: v for k, v in info.items() if k != "UniqueDeviceID"},
                **self.layout.summary()["counts"]}

    def reset(self) -> None:
        self.edit(lambda lay: None)  # records an undo step for the reset
        self.layout = self.require().original()
        self._save_draft()

    # ---- icons ------------------------------------------------------------------

    async def icon(self, bundle_id: str) -> bytes | None:
        cache = self._dev_dir("icons") / f"{_safe(bundle_id)}.png"
        if cache.exists():
            return cache.read_bytes()
        png = await self.source.icon_png(bundle_id)
        if png:
            cache.write_bytes(png)
        return png

    async def icon_colors(self, ids: list[str] | None = None) -> dict[str, Any]:
        lay = self.require()
        ids = ids or [i for i in lay.leaf_ids() if lay.nodes[i].bundle_id]
        out: dict[str, Any] = {}
        for i in ids:
            node = lay.get(i)
            png = await self.icon(node.bundle_id) if node.bundle_id else None
            out[i] = {"name": node.name, **(colors.dominant(png) if png else {"family": "unknown"})}
        return out

    # ---- write ------------------------------------------------------------------

    def _backup(self, state: list[Any], library: list[Any] | None, label: str) -> Path:
        p = self._dev_dir("backups") / f"{_stamp()}-{label}.plist"
        p.write_bytes(_pack(state, library))
        return p

    async def _write_verified(self, target: list[Any], target_lib: list[Any] | None,
                              label: str) -> dict[str, Any]:
        current, current_lib = await self.source.read()
        backup = self._backup(current, current_lib, label)
        # A backup made before the App Library was tracked has no library list; judge the
        # result on dock and pages only (the source keeps unlisted apps in the library).
        lib_known = target_lib is not None
        try:
            await self.source.write(target, target_lib)
        except Exception as e:
            # A lost response doesn't tell us whether the write landed. Look, don't retry.
            after, after_lib = await self.source.read()
            landed = structure(after, after_lib if lib_known else None) == structure(target, target_lib)
            return {"ok": landed, "backup": backup.name,
                    "error": f"write call failed ({e}); re-read shows the new layout "
                             f"{'DID' if landed else 'did NOT'} land. Not retrying."}
        after, after_lib = await self.source.read()
        ok = structure(after, after_lib if lib_known else None) == structure(target, target_lib)
        res: dict[str, Any] = {"ok": ok, "backup": backup.name}
        if after_lib is not None:
            res["app_library_only"] = len(after_lib)
        if not ok:
            want = Layout(target, library=target_lib)
            got = Layout(after, library=after_lib if lib_known else None)
            wp, gp = want.positions(), got.positions()
            res["mismatches"] = {
                "added_by_ios": sorted(set(gp) - set(wp)),
                "missing": sorted(set(wp) - set(gp)),
                "moved": {k: f"wanted {wp[k]}, got {gp[k]}" for k in wp
                          if k in gp and wp[k] != gp[k] and not k.startswith(("folder:", "widget:"))},
                "pages": f"wanted {len(target) - 1}, got {len(after) - 1}",
            }
        self.layout = Layout(after, library=after_lib)
        self._undo.clear()
        self._redo.clear()
        self._save_draft()
        return res

    async def apply(self, token: str) -> dict[str, Any]:
        lay = self.require()
        if token != lay.token():
            raise LayoutError("token doesn't match the current draft; run diff and use its apply_token")
        problems = lay.validate()
        if problems:
            raise LayoutError(f"draft has problems, not applying: {problems}")
        now, now_lib = await self.source.read()
        if structure(now, now_lib) != structure(lay.source, lay.source_library):
            raise LayoutError("the phone's layout changed since it was read (app installed or moved?). "
                              "Read again and redo the edits.")
        return await self._write_verified(lay.to_state(), lay.to_library(), "before-apply")

    def backups(self) -> list[str]:
        return sorted(p.name for p in self._dev_dir("backups").glob("*.plist"))

    async def restore(self, name: str) -> dict[str, Any]:
        p = self._dev_dir("backups") / name
        if not p.exists() or p.parent != self._dev_dir("backups"):
            raise LayoutError(f"no backup named {name!r}")
        return await self._write_verified(*_unpack(p.read_bytes()), "before-restore")

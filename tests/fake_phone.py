"""A made-up ~300-app icon state, shaped like SpringBoard's formatVersion 2 output,
with solid-color icons, so the whole flow can run without a phone."""

from __future__ import annotations

import datetime as dt
import io
import plistlib
import random
from pathlib import Path

from PIL import Image, ImageDraw

COLORS = {"red": (230, 40, 40), "orange": (245, 140, 20), "yellow": (250, 210, 30), "green": (40, 180, 70),
          "blue": (30, 110, 230), "purple": (140, 60, 200), "white": (245, 245, 245), "black": (20, 20, 20)}


def app(bundle: str, name: str) -> dict:
    return {"displayIdentifier": bundle, "bundleIdentifier": bundle, "displayName": name,
            "bundleVersion": "1.0", "iconModDate": dt.datetime(2026, 1, 1),
            "someFutureKey": {"nested": [1, 2, 3]}}  # must survive round trips untouched


def widget(name: str, size: str) -> dict:
    return {"iconType": "custom", "gridSize": size, "displayName": name,
            "elements": [{"containerBundleIdentifier": "com.apple.weather", "kind": name}],
            "uniqueIdentifier": f"W-{name}-{size}"}


def folder(name: str, apps: list[dict]) -> dict:
    return {"displayName": name, "listType": "folder", "iconLists": [apps[i:i + 9] for i in range(0, len(apps), 9)]}


def build(path: Path, n_apps: int = 300, seed: int = 7, as_dict: bool = False) -> dict[str, str]:
    rnd = random.Random(seed)
    names = list(COLORS)
    color_of: dict[str, str] = {}
    apps = []
    for i in range(n_apps):
        b = f"com.example.app{i:03d}"
        color_of[b] = names[i % len(names)]
        apps.append(app(b, f"App {i:03d}"))
    rnd.shuffle(apps)

    dock, rest = apps[:4], apps[4:]
    pages: list[list[dict]] = []
    pages.append([widget("Weather", "medium"), *rest[:16]])  # 8 + 16 = 24
    rest = rest[16:]
    pages.append([widget("Calendar", "small"), folder("Social", rest[:12]), *rest[12:31]])  # 4 + 1 + 19
    rest = rest[31:]
    while rest:
        page, rest = rest[:20], rest[20:]
        if len(pages) % 2 == 0 and len(page) >= 4:
            page = [folder(f"Folder {len(pages)}", page[:6]), *page[6:]]
        pages.append(page)

    if as_dict:  # SpringBoard's own form, with some apps kept only in the App Library
        lib = [x for x in pages[-1] if "listType" not in x][-12:]
        pages[-1] = [x for x in pages[-1] if x not in lib]
        pages = [pg for pg in pages if pg]
        disk = lambda x: x["bundleIdentifier"] if "bundleIdentifier" in x and "gridSize" not in x else (
            {**x, "iconLists": [[disk(i) for i in p] for p in x["iconLists"]]} if "iconLists" in x else x)
        raw = {"buttonBar": [disk(x) for x in dock], "iconLists": [[disk(x) for x in p] for p in pages],
               "ignored": [disk(x) for x in lib]}
        path.write_bytes(plistlib.dumps(raw, fmt=plistlib.FMT_BINARY))
    else:
        path.write_bytes(plistlib.dumps([dock, *pages], fmt=plistlib.FMT_BINARY))
    icons = path.with_suffix(".icons")
    icons.mkdir(exist_ok=True)
    for b, c in color_of.items():
        img = Image.new("RGBA", (120, 120), COLORS[c] + (255,))
        ImageDraw.Draw(img).ellipse((40, 40, 80, 80), fill=(255, 255, 255, 255))  # a white glyph
        buf = io.BytesIO()
        img.save(buf, "PNG")
        (icons / f"{b}.png").write_bytes(buf.getvalue())
    return color_of


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "fake.plist")
    build(out, as_dict="--dict" in sys.argv)
    print(f"wrote {out}")

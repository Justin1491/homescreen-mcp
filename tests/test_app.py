import asyncio
import importlib
import plistlib

import pytest

from homescreen import organize
from homescreen.device import FileSource
from homescreen.model import Layout, LayoutError
from homescreen.session import Session

from fake_phone import build


@pytest.fixture
def dict_phone(tmp_path):
    path = tmp_path / "phone.plist"
    colors = build(path, as_dict=True)
    return path, colors


def session_for(path, tmp_path):
    s = Session(FileSource(path), tmp_path / "data")
    asyncio.run(s.read())
    return s


def test_edit_is_atomic_and_undoable(dict_phone, tmp_path):
    s = session_for(dict_phone[0], tmp_path)
    before = s.require().token()
    first = s.require().pages[2][1].id
    with pytest.raises(LayoutError):
        # first move succeeds, second fails: the whole step must roll back
        w = next(n.id for n in s.require().nodes.values() if n.kind == "widget")
        s.edit(lambda lay: (lay.move(first, "library"), lay.move(w, "library")))
    assert s.require().token() == before and s.history() == {"undo": 0, "redo": 0}
    s.edit(lambda lay: lay.move(first, "library"))
    assert s.require().diff()["to_app_library"] == 1
    assert s.undo() and s.require().token() == before
    assert s.redo() and s.require().diff()["to_app_library"] == 1


def test_page_ops_and_dissolve(dict_phone, tmp_path):
    s = session_for(dict_phone[0], tmp_path)
    lay = s.require()
    n = len(lay.pages)
    lay.insert_page(2)
    assert lay.pages[1] == [] and len(lay.pages) == n + 1
    lay.move_page(2, n + 1)
    assert lay.pages[-1] == []
    lay.delete_page(n + 1)
    folder = next(x for x in lay.pages[1] if x.kind == "folder")
    kids = [c.id for p in folder.children for c in p]
    lay.dissolve_folder(folder.id)
    assert [x.id for x in lay.pages[1]][1:1 + len(kids)] == kids
    in_lib = len(lay.library)
    page = next(i for i, p in enumerate(lay.pages, 1) if p and all(x.kind != "widget" for x in p))
    apps_on_page = sum(len([c for q in x.children for c in q]) if x.kind == "folder" else 1 for x in lay.pages[page - 1])
    lay.delete_page(page)
    assert len(lay.library) == in_lib + apps_on_page
    with pytest.raises(LayoutError, match="widgets"):
        lay.delete_page(1)


def test_sorts_keep_items_and_page_one(dict_phone, tmp_path):
    path, color_of = dict_phone
    s = session_for(path, tmp_path)
    page1 = [x.id for x in s.require().pages[0]]
    colors = asyncio.run(s.icon_colors())
    s.edit(lambda lay: organize.by_color(lay, colors))
    lay = s.require()
    assert lay.validate() == [] and [x.id for x in lay.pages[0]] == page1
    loose = [x.id for p in lay.pages[1:] for x in p if x.kind == "app"]
    fams = [color_of[i] for i in loose]
    order = [f for f in organize.COLOR_ORDER if f in fams]
    assert fams == sorted(fams, key=order.index)
    s.edit(lambda lay: organize.alphabetical(lay))
    assert s.require().validate() == []
    s.edit(lambda lay: organize.sort_folder_contents(lay))
    assert s.require().validate() == []


def test_into_folders(dict_phone, tmp_path):
    s = session_for(dict_phone[0], tmp_path)
    lay = s.require()
    social = next(x for p in lay.pages for x in p if x.kind == "folder" and x.name == "Social")
    loose = [x.id for p in lay.pages[2:] for x in p if x.kind == "app"]
    res = s.edit(lambda lay: organize.into_folders(lay, {"social": loose[:2], "Brand New": loose[2:5],
                                                         "Lonely": loose[5:6]}))
    lay = s.require()
    assert res["count"] == 5 and set(res["filed"]) == {"Social", "Brand New"}
    assert set(loose[:2]) <= {c.id for p in social.children for c in p}
    assert all(len(p) <= 9 for p in social.children)
    new = next(x for p in lay.pages for x in p if x.kind == "folder" and x.name == "Brand New")
    assert [c.id for c in new.children[0]] == loose[2:5]
    assert lay.validate() == []


def test_app_api_guards_and_ops(dict_phone, tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    monkeypatch.setenv("HOMESCREEN_FIXTURE", str(dict_phone[0]))
    monkeypatch.setenv("HOMESCREEN_DATA", str(tmp_path / "appdata"))
    import homescreen.config as config
    import homescreen.ui as ui
    importlib.reload(config)
    importlib.reload(ui)
    c = TestClient(ui.app, base_url="http://127.0.0.1:8765")
    assert c.get("/").status_code == 200 and ui.TOKEN in c.get("/").text
    assert c.post("/api/read", json={}).status_code == 403
    assert TestClient(ui.app, base_url="http://evil.example").get("/api/state").status_code == 403
    h = {"X-Token": ui.TOKEN}
    v = c.post("/api/read", json={}, headers=h).json()
    assert v["loaded"] and v["library"] is not None
    app_id = next(x["id"] for x in v["pages"][2] if x["kind"] == "app")
    v = c.post("/api/op", json={"op": "move", "args": {"id": app_id, "target": "library"}}, headers=h).json()
    assert v["diff"]["to_app_library"] == 1 and v["history"]["undo"] == 1
    wid = next(x["id"] for p in v["pages"] for x in p if x["kind"] == "widget")
    bad = c.post("/api/op", json={"op": "move", "args": {"id": wid, "target": "dock"}}, headers=h)
    assert bad.status_code == 400 and "dock" in bad.json()["error"]
    r = c.post("/api/apply", json={"token": v["diff"]["apply_token"]}, headers=h).json()
    assert r["result"]["ok"]
    assert c.get("/api/backups").json()["backups"]
    assert c.get("/icon", params={"id": app_id}).status_code == 200


def test_screen_time_reader_and_optimizer(tmp_path):
    import time
    from homescreen import usage
    from fake_phone import app as mkapp
    # two synced "devices": the phone (opens of its own apps) and an unrelated Mac
    now_us = int((time.time() - usage.MAC_EPOCH) * 1e6)
    old_us = int((time.time() - 60 * 86400 - usage.MAC_EPOCH) * 1e6)
    phone, mac, other = (tmp_path / "remote" / n for n in ("PHONE", "MAC", "OLD"))
    for d in (phone, mac, other):
        d.mkdir(parents=True)
    rec = lambda b, n: (b"SEGB" + (b"\x00\x0a" + b.encode() + b"J") * (2 * n))
    (phone / str(now_us)).write_bytes(rec("com.a.hot", 50) + rec("com.a.warm", 10) + rec("com.a.cold", 1))
    (mac / str(now_us)).write_bytes(rec("com.apple.dt.Xcode", 99))
    (other / str(old_us)).write_bytes(rec("com.a.cold", 500))  # older than 30 days: ignored
    known = {"com.a.hot", "com.a.warm", "com.a.cold", "com.a.never"}
    u = usage.load(known, 30, tmp_path / "remote")
    assert u["ok"] and u["opens"] == {"com.a.hot": 50, "com.a.warm": 10, "com.a.cold": 1}
    assert [d["id"] for d in u["devices"]] == ["PHONE"]
    # hot app buried on page 3, cold app on page 1
    state = [[], [mkapp("com.a.cold", "Cold")], [mkapp("com.a.never", "Never")], [mkapp("com.a.hot", "Hot"), mkapp("com.a.warm", "Warm")]]
    lay = Layout(state, library=[])
    assert usage.swipes(lay, u["opens"]) == 50 * 2 + 10 * 2
    res = usage.optimize(lay, u["opens"])
    assert res["swipes_after"] == 0 and res["swipes_before"] == 120
    assert [n.id for n in lay.pages[0]][:3] == ["com.a.hot", "com.a.warm", "com.a.cold"]
    assert lay.validate() == []
    assert usage.load(known, 30, tmp_path / "missing")["ok"] is False


def test_bank_and_swap(dict_phone, tmp_path):
    s = session_for(dict_phone[0], tmp_path)
    lay = s.require()
    wpage, w = next((i, x.id) for i, p in enumerate(lay.pages, 1) for x in p if x.kind == "widget")
    a, b = [x.id for x in lay.pages[3] if x.kind == "app"][:2]
    s.edit(lambda lay: (lay.move(w, "bank"), lay.move(a, "bank")))
    assert any("App Bank" in p for p in s.require().validate())
    # the bank survives undo/redo and a restart of the session
    s.undo(); s.redo()
    s2 = Session(FileSource(dict_phone[0]), tmp_path / "data")
    assert [n.id for n in s2.require().bank] == [w, a]
    with pytest.raises(LayoutError):
        s2.edit(lambda lay: lay.move(w, next(n.id for n in lay.nodes.values() if n.kind == "folder")))
    s2.edit(lambda lay: (lay.move(w, f"page:{wpage}", 0), lay.move(a, "page:4", 0)))
    assert s2.require().validate() == []
    s2.edit(lambda lay: lay.swap(a, b))
    ids = [x.id for x in s2.require().pages[3]]
    assert ids.index(b) < ids.index(a)
    with pytest.raises(LayoutError, match="widgets"):
        s2.edit(lambda lay: lay.swap(w, next(x.id for x in lay.dock)))

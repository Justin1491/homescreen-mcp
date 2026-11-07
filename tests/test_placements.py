import asyncio
import plistlib

import pytest

from fake_phone import app
from homescreen.device import FileSource
from homescreen.model import Layout, LayoutError, structure
from homescreen.session import Session, placed_structure


def run(coro):
    return asyncio.run(coro)


def test_duplicate_move_reload_diff_and_remove(tmp_path):
    original = app('com.example.chat', 'ChatGPT')
    path = tmp_path / 'phone.plist'
    path.write_bytes(plistlib.dumps([[], [original], []]))
    s = Session(FileSource(path), tmp_path / 'data')
    run(s.read())
    placement = s.edit(lambda lay: lay.duplicate('com.example.chat', 'page:2'))
    assert placement != 'com.example.chat'
    assert s.require().validate() == []
    assert s.require().diff()['items_moved'] == 1
    s2 = Session(FileSource(path), tmp_path / 'data')
    assert s2.require().pages[1][0].id == placement
    s2.edit(lambda lay: lay.move(placement, 'page:1', 0))
    assert s2.require().pages[0][0].id == placement
    assert s2.undo() and s2.require().pages[1][0].id == placement
    s2.edit(lambda lay: lay.remove_placement(placement))
    assert s2.require().pages[0][0].id == 'com.example.chat'


def test_read_native_placement_has_stable_id_and_name():
    a = app('com.example.chat', 'ChatGPT')
    b = {'bundleIdentifier': 'com.example.chat', 'displayIdentifier': 'AAAAAAAA-0000-0000-0000-000000000000', 'iconType': 'app', 'iconLists': []}
    lay = Layout([[], [b], [a]])
    other = lay.pages[0][0]
    assert other.id != lay.pages[1][0].id
    assert other.name == 'ChatGPT'
    lay.move(other.id, 'page:2')
    reread = Layout(lay.to_state())
    assert reread.pages[1][-1].id == other.id


def test_final_placement_goes_to_library():
    a = app('com.example.chat', 'ChatGPT')
    lay = Layout([[], [a]], library=[])
    lay.remove_placement('com.example.chat')
    assert not lay.pages[0]
    assert [n.bundle_id for n in lay.library] == ['com.example.chat']
    assert not any('item set changed' in x for x in lay.validate())


def test_verification_compares_placement_count_and_normalization():
    a = app('com.example.chat', 'ChatGPT')
    b = {'bundleIdentifier': 'com.example.chat', 'displayIdentifier': 'AAAAAAAA-0000-0000-0000-000000000000', 'iconType': 'app'}
    assert placed_structure([[], [b]], [], None) == placed_structure([[], [a]], [], None)
    assert placed_structure([[], [a], [b]], [], None) != placed_structure([[], [a], []], [], None)
    assert structure([[], [a], [b]]) != structure([[], [a], []])


def test_do_not_duplicate_widgets_or_weblinks():
    lay = Layout([[], [{'displayIdentifier': 'WEB', 'webClipURL': '/'}]])
    with pytest.raises(LayoutError):
        lay.duplicate('WEB', 'page:1')


def test_apply_duplicate_and_restore_backup(tmp_path):
    a = app('com.example.chat', 'ChatGPT')
    other = app('com.example.other', 'Other')
    path = tmp_path / 'phone.plist'
    path.write_bytes(plistlib.dumps([[], [a], [other]]))
    s = Session(FileSource(path), tmp_path / 'data')
    run(s.read())
    new_id = s.edit(lambda lay: lay.duplicate('com.example.chat', 'page:2'))
    result = run(s.apply(s.require().token()))
    assert result['ok'], result
    assert s.require().pages[1][-1].id == new_id
    restored = run(s.restore(result['backup']))
    assert restored['ok'], restored
    assert len(s.require().pages[1]) == 1


def test_verification_detects_dropped_duplicate(tmp_path):
    class DroppingSource(FileSource):
        async def write(self, state, library, pins=None):
            state[2] = [x for x in state[2] if x.get('iconType') != 'app']
            await super().write(state, library, pins)

    path = tmp_path / 'phone.plist'
    path.write_bytes(plistlib.dumps([[], [app('com.example.chat', 'ChatGPT')], [app('com.example.other', 'Other')]]))
    s = Session(DroppingSource(path), tmp_path / 'data')
    run(s.read())
    s.edit(lambda lay: lay.duplicate('com.example.chat', 'page:2'))
    result = run(s.apply(s.require().token()))
    assert not result['ok'] and result['outcome'] == 'mismatch'


def test_deleting_duplicate_page_keeps_app_out_of_library():
    a = app('com.example.chat', 'ChatGPT')
    lay = Layout([[], [a], [app('com.example.other', 'Other')]], library=[])
    lay.duplicate('com.example.chat', 'page:2')
    lay.delete_page(2)
    assert lay.pages[0][0].bundle_id == 'com.example.chat'
    assert [n.bundle_id for n in lay.library] == ['com.example.other']
    assert not lay.validate()


def test_old_draft_pin_for_uuid_backed_app_is_preserved():
    b = {'bundleIdentifier': 'com.example.chat', 'displayIdentifier': 'AAAAAAAA-0000-0000-0000-000000000000', 'iconType': 'app'}
    lay = Layout([[], [b]], pins={'com.example.chat': 7})
    assert lay.pins[lay.pages[0][0].id] == 7


def test_removing_last_uuid_icon_writes_app_library_bundle():
    from homescreen.device import to_root_archive
    b = {'bundleIdentifier': 'com.example.chat', 'displayIdentifier': 'AAAAAAAA-0000-0000-0000-000000000000', 'iconType': 'app'}
    lay = Layout([[], [b]], library=[])
    lay.remove_placement(lay.pages[0][0].id)
    assert to_root_archive(lay.to_state(), lay.to_library())['ignored'] == ['com.example.chat']
    assert lay.diff()['to_app_library'] == 1


def test_source_pin_is_not_reassigned_when_original_icon_removed(tmp_path):
    a = app('com.example.chat', 'ChatGPT')
    b = {'bundleIdentifier': 'com.example.chat', 'displayIdentifier': 'AAAAAAAA-0000-0000-0000-000000000000', 'iconType': 'app'}
    lay = Layout([[], [b]], source=[[], [a], [b]], pins={}, source_pins={'com.example.chat': 5}, library=[], source_library=[])
    assert lay.source_pins == {'com.example.chat': 5}


def test_verification_matches_widget_disk_and_live_export_shapes():
    disk = {'elementType': 'widget', 'gridSize': 'small', 'displayIdentifier': 'WIDGET-DISPLAY',
            'uniqueIdentifier': 'WIDGET-CONFIG', 'bundleIdentifier': 'example.widget'}
    live = {k: v for k, v in disk.items() if k != 'uniqueIdentifier'}
    assert placed_structure([[], [disk]], None, None) == placed_structure([[], [live]], None, None)


def test_normalized_final_icon_retains_pin_on_verified_write(tmp_path):
    class NormalizingSource(FileSource):
        async def write(self, state, library, pins=None):
            for page in state:
                for item in page:
                    if item.get('iconType') == 'app':
                        item['displayIdentifier'] = item['bundleIdentifier']
                        item.pop('iconType')
            await super().write(state, library, pins)

    a = app('com.example.chat', 'ChatGPT')
    b = {'bundleIdentifier': 'com.example.chat', 'displayIdentifier': 'AAAAAAAA-0000-0000-0000-000000000000', 'iconType': 'app'}
    other = app('com.example.other', 'Other')
    path = tmp_path / 'phone.plist'
    path.write_bytes(plistlib.dumps([[], [a, other], [b]]))
    s = Session(NormalizingSource(path), tmp_path / 'data')
    run(s.read())
    duplicate = s.require().pages[1][0].id
    s.edit(lambda lay: lay.remove_placement('com.example.chat'))
    s.edit(lambda lay: lay.pin(duplicate, 2, 8))
    result = run(s.apply(s.require().token()))
    assert result['ok'], result
    assert s.require().pins[s.require().pages[1][0].id] == 8


def test_validation_rejects_ambiguous_and_library_conflicts():
    a = app('com.example.chat', 'ChatGPT')
    ambiguous = Layout([[], [a], [a]], library=[])
    assert any('duplicate app placement identifiers' in p for p in ambiguous.validate())
    conflict = Layout([[], [a]], library=[a])
    assert any('App Library-only' in p for p in conflict.validate())


def test_search_finds_each_placement_by_bundle():
    a = app('com.example.chat', 'ChatGPT')
    lay = Layout([[], [a], [app('com.example.other', 'Other')]])
    extra = lay.duplicate('com.example.chat', 'page:2')
    matches = lay.find('com.example.chat')
    assert {n.id for n in matches} == {'com.example.chat', extra}
    assert all(n.describe()['bundle_id'] == 'com.example.chat' for n in matches)


def test_duplicate_placements_have_distinct_pin_keys():
    from homescreen.session import pins_by_page
    a = app('com.example.chat', 'ChatGPT')
    lay = Layout([[], [a], [app('com.example.other', 'Other')]])
    extra = lay.duplicate('com.example.chat', 'page:2')
    lay.pin('com.example.chat', 1, 4)
    lay.pin(extra, 2, 8)
    pins = pins_by_page(lay)
    assert pins[0] == {'com.example.chat': 4}
    assert pins[1] == {lay.get(extra).raw['displayIdentifier']: 8}


def test_legacy_duplicate_draft_pin_migrates_to_same_placement():
    a = app('com.example.chat', 'ChatGPT')
    b = {'bundleIdentifier': 'com.example.chat', 'displayIdentifier': 'AAAAAAAA-0000-0000-0000-000000000000', 'iconType': 'app'}
    state = [[], [a], [b]]
    lay = Layout(state, source=state, pins={'app:1': 8}, source_pins={'app:1': 8})
    assert lay.pins == {lay.pages[1][0].id: 8}
    assert lay.source_pins == {lay.pages[1][0].id: 8}

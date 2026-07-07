from __future__ import annotations

import custom_components.bticino_c300x.entry_locks as entry_locks
from custom_components.bticino_c300x.entry_locks import clear_entry_locks, entry_lock


def test_entry_lock_is_cached_per_entry_and_scope() -> None:
    first = entry_lock("entry-1", "ring_capture")
    second = entry_lock("entry-1", "ring_capture")
    other_scope = entry_lock("entry-1", "qml_patch")
    other_entry = entry_lock("entry-2", "ring_capture")

    assert first is second
    assert first is not other_scope
    assert first is not other_entry
    clear_entry_locks("entry-1")
    clear_entry_locks("entry-2")


def test_clear_entry_locks_removes_only_matching_entry_locks() -> None:
    entry_lock("entry-1", "ring_capture")
    entry_lock("entry-1", "message_refresh:memos")
    entry_lock("entry-2", "ring_capture")

    clear_entry_locks("entry-1")

    assert not any(key[0] == "entry-1" for key in entry_locks._locks)
    assert ("entry-2", "ring_capture") in entry_locks._locks
    clear_entry_locks("entry-2")

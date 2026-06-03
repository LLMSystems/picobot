from pathlib import Path

from simplified_chatbot.tools import file_state
from simplified_chatbot.tools.file_state import FileStates


def test_check_read_warns_when_file_has_not_been_read(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello\n", encoding="utf-8")
    states = FileStates()

    warning = states.check_read(path)

    assert warning == (
        "Warning: file has not been read yet. "
        "Read it first to verify content before editing."
    )


def test_record_read_enables_dedup_for_unchanged_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello\n", encoding="utf-8")
    states = FileStates()

    states.record_read(path, offset=3, limit=10)

    assert states.is_unchanged(path, offset=3, limit=10) is True
    assert states.is_unchanged(path, offset=1, limit=10) is False
    assert states.check_read(path) is None


def test_file_state_tolerates_mtime_change_when_content_is_same(tmp_path, monkeypatch):
    path = tmp_path / "notes.txt"
    path.write_text("hello\n", encoding="utf-8")
    states = FileStates()
    states.record_read(path)

    original_mtime = file_state.os.path.getmtime(path.resolve())

    def fake_getmtime(target):
        resolved = Path(target).resolve()
        if resolved == path.resolve():
            return original_mtime + 10
        return file_state.os.path.getmtime(target)

    monkeypatch.setattr(file_state.os.path, "getmtime", fake_getmtime)

    assert states.is_unchanged(path) is True
    assert states.check_read(path) is None


def test_file_state_detects_content_change_and_disables_dedup(tmp_path, monkeypatch):
    path = tmp_path / "notes.txt"
    path.write_text("hello\n", encoding="utf-8")
    states = FileStates()
    states.record_read(path)
    path.write_text("changed\n", encoding="utf-8")

    original_mtime = file_state.os.path.getmtime(path.resolve())

    def fake_getmtime(target):
        resolved = Path(target).resolve()
        if resolved == path.resolve():
            return original_mtime + 10
        return file_state.os.path.getmtime(target)

    monkeypatch.setattr(file_state.os.path, "getmtime", fake_getmtime)

    assert states.is_unchanged(path) is False
    assert states.check_read(path) == (
        "Warning: file has been modified since last read. "
        "Re-read to verify content before editing."
    )


def test_record_write_disables_dedup_and_clear_resets_state(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello\n", encoding="utf-8")
    states = FileStates()

    states.record_write(path)

    assert states.is_unchanged(path) is False
    assert states.check_read(path) is None

    states.clear()

    assert states.check_read(path) == (
        "Warning: file has not been read yet. "
        "Read it first to verify content before editing."
    )

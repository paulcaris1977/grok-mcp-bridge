import pytest

import store


@pytest.fixture(autouse=True)
def _sqlite(tmp_path, monkeypatch):
    """Chaque test a sa propre base SQLite, jamais /data."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("NOTES_PATH", raising=False)
    store.init()

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_path():
    base = Path.cwd() / ".tmp_pytest"
    base.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="case_", dir=base))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def restore_environment():
    original = os.environ.copy()
    try:
        yield
    finally:
        current_keys = list(os.environ.keys())
        for key in current_keys:
            if key not in original:
                os.environ.pop(key, None)
        os.environ.update(original)

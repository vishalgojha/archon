from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

_TMP_ROOT = Path(__file__).resolve().parent / "archon" / "tests" / "_tmp_fixture"


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    folder = _TMP_ROOT / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)

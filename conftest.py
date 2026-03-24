from __future__ import annotations

import shutil
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent
_TMP_ROOT = Path(__file__).resolve().parent / "archon" / "tests" / "_tmp_fixture"

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    folder = _TMP_ROOT / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from archon.archon_cli import cli


def _latest_scan_json(output_dir: Path) -> Path:
    matches = sorted(output_dir.glob("redteam-regression-scan-*.json"))
    assert matches
    return matches[-1]


def test_redteam_regression_writes_artifacts(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CI", "true")
    output_dir = tmp_path / "redteam"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "redteam",
            "regression",
            "--output-dir",
            str(output_dir),
            "--payloads-per-vector",
            "1",
        ],
    )

    assert result.exit_code == 0
    json_path = _latest_scan_json(output_dir)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["total_payloads"] == 8
    md_path = json_path.with_suffix(".md")
    assert md_path.exists()
    assert "Red-Team Scan" in md_path.read_text(encoding="utf-8")

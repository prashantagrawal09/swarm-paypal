"""The smoke script's full step list must pass against the simulated PayPal."""

from __future__ import annotations

import json

import pytest

from scripts import paypal_smoke


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(paypal_smoke, "REPORT_PATH", tmp_path / "report.json")
    monkeypatch.setattr(paypal_smoke, "STATE_PATH", tmp_path / "state.json")


async def test_simulated_smoke_run_passes_every_step(tmp_path, capsys):
    exit_code = await paypal_smoke.main(["--simulated"])
    output = capsys.readouterr().out
    assert exit_code == 0, output

    report = json.loads((tmp_path / "report.json").read_text())
    statuses = {r["name"]: r["status"] for r in report["results"]}
    assert len(statuses) == 17
    assert set(statuses.values()) == {"PASS"}, statuses
    assert "approval link" in output
    assert report["ids"]["capture"].startswith("SIM-CAPTURE-")
    assert not (tmp_path / "state.json").exists()  # simulated runs never touch saved state


def test_table_rendering():
    results = [
        paypal_smoke.StepResult(1, "Token", "PASS", "", 12),
        paypal_smoke.StepResult(2, "Reauthorize", "EXPECTED", "too soon", 40),
    ]
    table = paypal_smoke.render_table(results)
    assert "PASS 1  EXPECTED 1  SKIP 0  FAIL 0" in table

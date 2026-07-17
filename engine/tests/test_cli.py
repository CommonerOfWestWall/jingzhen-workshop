import json
import subprocess
import sys


def run_cli(*args: str) -> dict:
    process = subprocess.run(
        [sys.executable, "-m", "jingzhen_engine.cli", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(process.stdout.strip().splitlines()[-1])


def test_probe_runtime_returns_structured_result() -> None:
    result = run_cli("probe-runtime")

    assert result["ok"] is True
    assert result["command"] == "probe-runtime"
    assert "python" in result["runtime"]
    assert "opencv" in result["runtime"]


def test_plan_chunks_cli() -> None:
    result = run_cli("plan-chunks", "--frames", "23", "--chunk-size", "10", "--overlap", "2")

    assert result["windows"] == [[0, 10], [8, 18], [16, 23]]

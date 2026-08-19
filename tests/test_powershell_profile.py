from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _child_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key.casefold() != "psmodulepath"
    }


def test_windows_dpapi_profile_roundtrip(tmp_path):
    script = PROJECT_ROOT / "tests" / "powershell" / "profile_roundtrip.ps1"
    module = PROJECT_ROOT / "scripts" / "ModelProfile.psm1"
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-ModulePath",
            str(module),
            "-TempDirectory",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
        env=_child_environment(),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    combined_output = completed.stdout + completed.stderr
    assert completed.returncode == 0, combined_output
    assert "profile_roundtrip_ok" in completed.stdout
    assert "unit-key-" not in combined_output
    assert "example.invalid" not in combined_output


def test_profile_input_helpers_have_no_model_defaults_and_retry_blank_ids():
    script = PROJECT_ROOT / "tests" / "powershell" / "profile_input_helpers.ps1"
    manager = PROJECT_ROOT / "scripts" / "manage_model_profile.ps1"
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-ManagerPath",
            str(manager),
        ],
        cwd=PROJECT_ROOT,
        env=_child_environment(),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    combined_output = completed.stdout + completed.stderr
    assert completed.returncode == 0, combined_output
    assert "profile_input_helpers_ok" in completed.stdout
    assert "fable" not in combined_output.casefold()
    assert "opus" not in combined_output.casefold()

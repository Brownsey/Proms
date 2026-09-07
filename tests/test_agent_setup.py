import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_windows_setup_check_reports_ready_without_exposing_proxy_values() -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None

    result = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "setup.ps1"),
            "-CheckOnly",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "READY: setup prerequisites are available"


def test_agent_instructions_define_the_safe_automated_setup_flow() -> None:
    instructions = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "scripts/setup.ps1" in instructions
    assert "powershell.exe -NoProfile" in instructions
    assert "-CheckOnly" in instructions
    assert "Always run the full idempotent setup command" in instructions
    assert "Never open or read proxy files" in instructions
    assert "numeric counts from `GET /configuration`" in instructions
    assert "uv run proms" in instructions
    assert "Never print, commit, or upload proxy values" in instructions
    assert "npm run verify" in instructions


def test_setup_refreshes_path_without_overwriting_process_specific_entries() -> None:
    script = (ROOT / "scripts" / "setup.ps1").read_text(encoding="utf-8")

    assert '$env:Path = "$machinePath;$userPath;$env:Path"' in script
    assert "setx" not in script.lower()

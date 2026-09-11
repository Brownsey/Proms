import os
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


def test_full_setup_builds_local_control_ui_and_preserves_proxy_files(tmp_path: Path) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None

    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "setup.ps1", scripts / "setup.ps1")
    for name in ("pyproject.toml", "uv.lock", "package.json", "package-lock.json"):
        (repo / name).write_text("fixture", encoding="utf-8")
    for name in ("proxies.txt", "rotating_proxies.txt"):
        (repo / name).write_text(f"preserve-{name}\n", encoding="utf-8")

    command_log = tmp_path / "commands.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "node.cmd").write_text("@echo v20.9.0\n", encoding="utf-8")
    for command in ("uv", "npm"):
        (fake_bin / f"{command}.cmd").write_text(
            f'@echo {command} %*>>"%PROMS_TEST_COMMAND_LOG%"\n',
            encoding="utf-8",
        )
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    environment["PROMS_TEST_COMMAND_LOG"] = str(command_log)

    result = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(scripts / "setup.ps1"),
        ],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert command_log.read_text(encoding="utf-8").splitlines() == [
        "uv sync --locked",
        "npm ci",
        "uv run playwright install chromium",
        "npm run build",
    ]
    assert (repo / "proxies.txt").read_text(encoding="utf-8") == "preserve-proxies.txt\n"
    assert (repo / "rotating_proxies.txt").read_text(encoding="utf-8") == (
        "preserve-rotating_proxies.txt\n"
    )
    assert "uv run proms" in result.stdout
    assert "http://127.0.0.1:8000/control/" in result.stdout

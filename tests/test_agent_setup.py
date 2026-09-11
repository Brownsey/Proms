import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def working_bash() -> str:
    candidates = []
    if os.name == "nt":
        candidates.append(
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/bin/bash.exe"
        )
    discovered = shutil.which("bash")
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        result = subprocess.run(
            [str(candidate), "--version"], capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            return str(candidate)
    pytest.skip("working bash is unavailable")


def bash_path(shell: str, path: Path) -> str:
    if os.name != "nt":
        return str(path)
    result = subprocess.run(
        [shell, "-lc", 'cygpath -u "$1"', "_", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def write_fake_macos(fake_bin: Path, version: str = "14.7") -> Path:
    bash_environment = fake_bin / "macos-env.sh"
    bash_environment.write_text(
        "uname() { echo Darwin; }\n"
        f'sw_vers() {{ [ "$1" = -productVersion ] && echo {version}; }}\n',
        encoding="utf-8",
    )
    return bash_environment


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
    assert "numeric count from `GET /configuration`" in instructions
    assert "uv run --locked proms" in instructions
    assert "Never print, commit, or upload proxy values" in instructions
    assert "npm run verify" in instructions


def test_setup_refreshes_path_without_overwriting_process_specific_entries() -> None:
    script = (ROOT / "scripts" / "setup.ps1").read_text(encoding="utf-8")

    assert '$env:Path = "$machinePath;$userPath;$env:Path"' in script
    assert "setx" not in script.lower()


@pytest.mark.parametrize("proxy_contents", [None, "preserve-proxies.txt\n"])
def test_full_setup_builds_local_control_ui_and_handles_proxy_file(
    tmp_path: Path, proxy_contents: str | None
) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None

    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "setup.ps1", scripts / "setup.ps1")
    for name in ("pyproject.toml", "uv.lock", "package.json", "package-lock.json"):
        (repo / name).write_text("fixture", encoding="utf-8")
    if proxy_contents is not None:
        (repo / "proxies.txt").write_text(proxy_contents, encoding="utf-8")

    command_log = tmp_path / "commands.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "node.cmd").write_text("@echo v20.9.0\n", encoding="utf-8")
    for command in ("uv", "npm", "npx"):
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
        "npx playwright install chromium",
        "uv run --locked playwright install chromium",
        "npm run build",
    ]
    assert (repo / "proxies.txt").read_text(encoding="utf-8") == (proxy_contents or "")
    assert "uv run --locked proms" in result.stdout
    assert "http://127.0.0.1:8000/control/" in result.stdout


@pytest.mark.parametrize("proxy_contents", [None, "preserve-proxies.txt\n"])
def test_posix_setup_installs_with_brew_builds_ui_and_handles_proxy_file(
    tmp_path: Path, proxy_contents: str | None
) -> None:
    shell = working_bash()
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "setup.sh", scripts / "setup.sh")
    for name in ("pyproject.toml", "uv.lock", "package.json", "package-lock.json"):
        (repo / name).write_text("fixture", encoding="utf-8")
    if proxy_contents is not None:
        (repo / "proxies.txt").write_text(proxy_contents, encoding="utf-8")

    command_log = tmp_path / "commands.log"
    fake_bin = tmp_path / "bin"
    templates = tmp_path / "templates"
    outside = tmp_path / "outside"
    fake_bin.mkdir()
    templates.mkdir()
    outside.mkdir()
    bash_environment = write_fake_macos(fake_bin)
    (templates / "uv").write_text(
        '#!/bin/sh\nprintf "uv %s\\n" "$*" >> "$PROMS_TEST_COMMAND_LOG"\n',
        encoding="utf-8",
    )
    (templates / "node").write_text("#!/bin/sh\necho v24.0.0\n", encoding="utf-8")
    for command in ("npm", "npx"):
        (templates / command).write_text(
            f'#!/bin/sh\nprintf "{command} %s\\n" "$*" >> "$PROMS_TEST_COMMAND_LOG"\n',
            encoding="utf-8",
        )
    (fake_bin / "brew").write_text(
        "#!/bin/sh\n"
        'printf "brew %s\\n" "$*" >> "$PROMS_TEST_COMMAND_LOG"\n'
        'if [ "$1" = --prefix ]; then echo "$PROMS_FAKE_NODE_PREFIX"; exit 0; fi\n'
        'if [ "$2" = uv ]; then cp "$PROMS_FAKE_TEMPLATES/uv" "$PROMS_FAKE_BIN/uv"; '
        'chmod +x "$PROMS_FAKE_BIN/uv"; fi\n'
        'if [ "$2" = node@24 ]; then mkdir -p "$PROMS_FAKE_NODE_PREFIX/bin"; '
        'cp "$PROMS_FAKE_TEMPLATES/node" "$PROMS_FAKE_NODE_PREFIX/bin/node"; '
        'cp "$PROMS_FAKE_TEMPLATES/npm" "$PROMS_FAKE_NODE_PREFIX/bin/npm"; '
        'cp "$PROMS_FAKE_TEMPLATES/npx" "$PROMS_FAKE_NODE_PREFIX/bin/npx"; '
        'chmod +x "$PROMS_FAKE_NODE_PREFIX/bin/node" "$PROMS_FAKE_NODE_PREFIX/bin/npm" '
        '"$PROMS_FAKE_NODE_PREFIX/bin/npx"; fi\n',
        encoding="utf-8",
    )
    (fake_bin / "brew").chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{bash_path(shell, fake_bin)}:/usr/bin:/bin"
    environment["PROMS_TEST_COMMAND_LOG"] = bash_path(shell, command_log)
    environment["PROMS_FAKE_BIN"] = bash_path(shell, fake_bin)
    environment["PROMS_FAKE_TEMPLATES"] = bash_path(shell, templates)
    environment["PROMS_FAKE_NODE_PREFIX"] = bash_path(shell, tmp_path / "node-prefix")
    environment["BASH_ENV"] = bash_path(shell, bash_environment)

    result = subprocess.run(
        [shell, bash_path(shell, scripts / "setup.sh")],
        cwd=outside,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert command_log.read_text(encoding="utf-8").splitlines() == [
        "brew install uv",
        "brew install node@24",
        "brew --prefix node@24",
        "uv sync --locked",
        "npm ci",
        "npx playwright install chromium",
        "uv run --locked playwright install chromium",
        "npm run build",
    ]
    assert (repo / "proxies.txt").read_text(encoding="utf-8") == (proxy_contents or "")
    assert "uv run --locked proms" in result.stdout
    assert "http://127.0.0.1:8000/control/" in result.stdout


def test_posix_setup_check_only_reports_missing_tools_without_installing(tmp_path: Path) -> None:
    shell = working_bash()
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "setup.sh", scripts / "setup.sh")
    for name in ("pyproject.toml", "uv.lock", "package.json", "package-lock.json"):
        (repo / name).write_text("fixture", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    bash_environment = write_fake_macos(fake_bin)
    environment = os.environ.copy()
    environment["PATH"] = f"{bash_path(shell, fake_bin)}:/usr/bin:/bin"
    environment["BASH_ENV"] = bash_path(shell, bash_environment)
    result = subprocess.run(
        [shell, bash_path(shell, scripts / "setup.sh"), "--check-only"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Missing prerequisites" in result.stderr
    assert "npx" in result.stderr
    assert "Run bash scripts/setup.sh" in result.stderr


def test_posix_setup_gives_actionable_error_when_homebrew_is_unavailable(
    tmp_path: Path,
) -> None:
    shell = working_bash()
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "setup.sh", scripts / "setup.sh")
    for name in ("pyproject.toml", "uv.lock", "package.json", "package-lock.json"):
        (repo / name).write_text("fixture", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    bash_environment = write_fake_macos(fake_bin)
    environment = os.environ.copy()
    environment["PATH"] = f"{bash_path(shell, fake_bin)}:/usr/bin:/bin"
    environment["BASH_ENV"] = bash_path(shell, bash_environment)
    result = subprocess.run(
        [shell, bash_path(shell, scripts / "setup.sh")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Homebrew is required" in result.stderr
    assert "https://brew.sh" in result.stderr
    assert "bash scripts/setup.sh again" in result.stderr


def test_posix_setup_rejects_non_macos_before_checking_tools(tmp_path: Path) -> None:
    shell = working_bash()
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    fake_bin = tmp_path / "bin"
    scripts.mkdir(parents=True)
    fake_bin.mkdir()
    shutil.copy2(ROOT / "scripts" / "setup.sh", scripts / "setup.sh")
    for name in ("pyproject.toml", "uv.lock", "package.json", "package-lock.json"):
        (repo / name).write_text("fixture", encoding="utf-8")
    bash_environment = fake_bin / "linux-env.sh"
    bash_environment.write_text("uname() { echo Linux; }\n", encoding="utf-8")
    environment = os.environ.copy()
    environment["PATH"] = f"{bash_path(shell, fake_bin)}:/usr/bin:/bin"
    environment["BASH_ENV"] = bash_path(shell, bash_environment)

    result = subprocess.run(
        [shell, bash_path(shell, scripts / "setup.sh"), "--check-only"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert result.stderr.strip() == "Proms setup requires macOS 14 Sonoma or newer."


def test_posix_setup_rejects_macos_13_before_checking_tools(tmp_path: Path) -> None:
    shell = working_bash()
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    fake_bin = tmp_path / "bin"
    scripts.mkdir(parents=True)
    fake_bin.mkdir()
    shutil.copy2(ROOT / "scripts" / "setup.sh", scripts / "setup.sh")
    for name in ("pyproject.toml", "uv.lock", "package.json", "package-lock.json"):
        (repo / name).write_text("fixture", encoding="utf-8")
    bash_environment = write_fake_macos(fake_bin, "13.6.9")
    environment = os.environ.copy()
    environment["PATH"] = f"{bash_path(shell, fake_bin)}:/usr/bin:/bin"
    environment["BASH_ENV"] = bash_path(shell, bash_environment)

    result = subprocess.run(
        [shell, bash_path(shell, scripts / "setup.sh"), "--check-only"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert result.stderr.strip() == "Proms setup requires macOS 14 Sonoma or newer."

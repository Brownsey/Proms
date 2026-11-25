import subprocess
import sys
from collections.abc import Sequence


def test_server_binds_only_to_loopback_by_default(monkeypatch) -> None:
    from proms import __main__

    called_with: dict[str, object] = {}

    def fake_run(app: str, **options: object) -> None:
        called_with.update(app=app, **options)

    monkeypatch.setattr(__main__.uvicorn, "run", fake_run)

    __main__.main([])

    assert called_with == {
        "app": "proms.app:app",
        "host": "127.0.0.1",
        "port": 8000,
    }


def test_cli_can_launch_and_close_eight_direct_chrome_windows(monkeypatch, capsys) -> None:
    from proms import __main__

    requests = []

    def fake_request(method: str, payload: dict[str, object] | None = None) -> dict[str, int]:
        requests.append((method, payload))
        return {"launched": 8, "active": 8, "closed": 8}

    monkeypatch.setattr(__main__, "_request", fake_request)
    __main__.main(["launch", "--direct", "8", "--chrome", "--url", "about:blank"])
    __main__.main(["status"])
    __main__.main(["close"])

    assert requests == [
        ("POST", {"direct_windows": 8, "chrome_profiles": True, "url": "about:blank"}),
        ("GET", None),
        ("DELETE", None),
    ]
    assert capsys.readouterr().out.splitlines() == [
        "Launched 8 windows. 8 active.",
        "8 active windows.",
        "Closed 8 windows.",
    ]


def test_verify_runs_every_locked_quality_gate(monkeypatch) -> None:
    from proms import verify

    commands: list[list[str]] = []

    def fake_run(command: Sequence[str], *, check: bool) -> None:
        assert check is True
        commands.append(list(command))

    monkeypatch.setattr(verify.subprocess, "run", fake_run)

    verify.main()

    assert commands == [
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        [sys.executable, "-m", "ty", "check"],
        [sys.executable, "-m", "pytest"],
    ]


def test_verify_stops_when_a_gate_fails(monkeypatch) -> None:
    from proms import verify

    commands: list[list[str]] = []

    def fake_run(command: Sequence[str], *, check: bool) -> None:
        commands.append(list(command))
        if command[2:4] == ["ruff", "format"]:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(verify.subprocess, "run", fake_run)

    try:
        verify.main()
    except subprocess.CalledProcessError as error:
        assert error.returncode == 1
    else:
        raise AssertionError("verify should propagate a failing quality gate")

    assert len(commands) == 2

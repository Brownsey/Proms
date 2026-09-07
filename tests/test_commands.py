import subprocess
from collections.abc import Sequence


def test_server_binds_only_to_loopback_by_default(monkeypatch) -> None:
    from proms import __main__

    called_with: dict[str, object] = {}

    def fake_run(app: str, **options: object) -> None:
        called_with.update(app=app, **options)

    monkeypatch.setattr(__main__.uvicorn, "run", fake_run)

    __main__.main()

    assert called_with == {
        "app": "proms.app:app",
        "host": "127.0.0.1",
        "port": 8000,
    }


def test_verify_runs_every_locked_quality_gate(monkeypatch) -> None:
    from proms import verify

    commands: list[list[str]] = []

    def fake_run(command: Sequence[str], *, check: bool) -> None:
        assert check is True
        commands.append(list(command))

    monkeypatch.setattr(verify.subprocess, "run", fake_run)

    verify.main()

    assert commands == [
        ["uv", "run", "--locked", "ruff", "check", "."],
        ["uv", "run", "--locked", "ruff", "format", "--check", "."],
        ["uv", "run", "--locked", "ty", "check"],
        ["uv", "run", "--locked", "pytest"],
    ]


def test_verify_stops_when_a_gate_fails(monkeypatch) -> None:
    from proms import verify

    commands: list[list[str]] = []

    def fake_run(command: Sequence[str], *, check: bool) -> None:
        commands.append(list(command))
        if command[3:5] == ["ruff", "format"]:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(verify.subprocess, "run", fake_run)

    try:
        verify.main()
    except subprocess.CalledProcessError as error:
        assert error.returncode == 1
    else:
        raise AssertionError("verify should propagate a failing quality gate")

    assert len(commands) == 2

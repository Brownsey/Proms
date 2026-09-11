import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from proms.app import create_app

LOCAL_CONTROL_ORIGIN = "http://127.0.0.1:8000"


def client_for(tmp_path: Path) -> tuple[TestClient, Path, Path]:
    static_file = tmp_path / "static.txt"
    rotating_file = tmp_path / "rotating.txt"
    return (
        TestClient(create_app(proxy_file=static_file, rotating_proxy_file=rotating_file)),
        static_file,
        rotating_file,
    )


@pytest.mark.parametrize(
    ("mode", "target_name", "other_name"),
    [("static", "static.txt", "rotating.txt"), ("rotating", "rotating.txt", "static.txt")],
)
def test_save_proxy_list_replaces_only_selected_mode_and_refreshes_counts(
    tmp_path: Path, mode: str, target_name: str, other_name: str
) -> None:
    client, static_file, rotating_file = client_for(tmp_path)
    files = {"static.txt": static_file, "rotating.txt": rotating_file}
    files[target_name].write_text("old.test:7001\n", encoding="utf-8")
    files[other_name].write_text("untouched.test:7002\n", encoding="utf-8")
    submitted = "# local examples\none.test:8001\n\nhttps://user:placeholder@two.test:8002\n"

    with client:
        response = client.post(
            "/configuration/proxies",
            json={"mode": mode, "proxies": submitted},
            headers={"Origin": LOCAL_CONTROL_ORIGIN},
        )
        configuration = client.get("/configuration")

    assert response.status_code == 200
    assert response.json() == {"mode": mode, "count": 2}
    assert response.headers["access-control-allow-origin"] == LOCAL_CONTROL_ORIGIN
    assert response.headers["vary"] == "Origin"
    assert "access-control-allow-credentials" not in response.headers
    assert files[target_name].read_text(encoding="utf-8") == submitted
    assert files[other_name].read_text(encoding="utf-8") == "untouched.test:7002\n"
    expected = {"static_proxy_count": 1, "rotating_proxy_count": 1}
    expected[f"{mode}_proxy_count"] = 2
    assert configuration.json() == expected


@pytest.mark.parametrize("submitted", ["", "\n# keep no proxies here\n"])
def test_empty_proxy_list_requires_explicit_clear_confirmation(
    tmp_path: Path, submitted: str
) -> None:
    client, static_file, _ = client_for(tmp_path)
    original = "existing.test:8001\n"
    static_file.write_text(original, encoding="utf-8")

    with client:
        rejected = client.post(
            "/configuration/proxies", json={"mode": "static", "proxies": submitted}
        )
        assert static_file.read_text(encoding="utf-8") == original
        accepted = client.post(
            "/configuration/proxies",
            json={"mode": "static", "proxies": submitted, "confirm_clear": True},
        )

    assert rejected.status_code == 400
    assert "confirm_clear" in rejected.json()["detail"]
    assert accepted.json() == {"mode": "static", "count": 0}
    assert static_file.read_text(encoding="utf-8") == submitted


@pytest.mark.parametrize(
    "body",
    [
        b'{"mode":"static","proxies":"secret-marker.test:8001"',
        b'["secret-marker.test:8001"]',
        b'{"mode":"static"}',
        b'{"mode":"static","proxies":"one.test:8001","extra":"secret-marker"}',
        b'{"mode":1,"proxies":"secret-marker.test:8001"}',
        b'{"mode":"static","proxies":["secret-marker.test:8001"]}',
        b'{"mode":"static","proxies":"one.test:8001","confirm_clear":"yes"}',
        b'{"mode":"secret-marker","proxies":"one.test:8001"}',
    ],
)
def test_invalid_json_shape_and_types_are_secret_safe_and_leave_file_unchanged(
    tmp_path: Path, body: bytes
) -> None:
    client, static_file, _ = client_for(tmp_path)
    original = "existing.test:8001\n"
    static_file.write_text(original, encoding="utf-8")

    with client:
        response = client.post(
            "/configuration/proxies",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 400
    assert "secret-marker" not in response.text
    assert static_file.read_text(encoding="utf-8") == original


def test_invalid_proxy_reports_safe_line_reason_without_writing(tmp_path: Path) -> None:
    client, static_file, _ = client_for(tmp_path)
    original = "existing.test:8001\n"
    static_file.write_text(original, encoding="utf-8")

    with client:
        response = client.post(
            "/configuration/proxies",
            json={
                "mode": "static",
                "proxies": "good.test:8001\nhttp://user:secret-marker@[bad:8002",
            },
        )

    assert response.status_code == 400
    assert "line 2" in response.json()["detail"]
    assert "secret-marker" not in response.text
    assert static_file.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    "bad_host",
    [
        "bad\x00secret-marker.test",
        "bad?secret-marker.test",
        "bad#secret-marker.test",
        r"bad\secret-marker.test",
        "bad[secret-marker.test",
        "bad]secret-marker.test",
        "bad<secret-marker.test",
        "bad>secret-marker.test",
        "bad^secret-marker.test",
        "bad|secret-marker.test",
        "bad%00secret-marker.test",
        "bad%secret-marker.test",
    ],
)
def test_legacy_proxy_rejects_unsafe_host_characters_without_writing(
    tmp_path: Path, bad_host: str
) -> None:
    client, static_file, rotating_file = client_for(tmp_path)
    original = "existing.test:8001\n"
    other = "untouched.test:8002\n"
    static_file.write_text(original, encoding="utf-8")
    rotating_file.write_text(other, encoding="utf-8")

    with client:
        response = client.post(
            "/configuration/proxies",
            json={"mode": "static", "proxies": f"{bad_host}:9001"},
        )

    assert response.status_code == 400
    assert "secret-marker" not in response.text
    assert static_file.read_text(encoding="utf-8") == original
    assert rotating_file.read_text(encoding="utf-8") == other


def test_url_proxy_rejects_percent_encoded_host_without_writing(tmp_path: Path) -> None:
    client, static_file, rotating_file = client_for(tmp_path)
    original = "existing.test:8001\n"
    other = "untouched.test:8002\n"
    static_file.write_text(original, encoding="utf-8")
    rotating_file.write_text(other, encoding="utf-8")

    with client:
        response = client.post(
            "/configuration/proxies",
            json={"mode": "static", "proxies": "http://bad%00secret-marker.test:9001"},
        )

    assert response.status_code == 400
    assert "secret-marker" not in response.text
    assert static_file.read_text(encoding="utf-8") == original
    assert rotating_file.read_text(encoding="utf-8") == other


def test_oversize_body_is_rejected_safely_without_writing(tmp_path: Path) -> None:
    client, static_file, _ = client_for(tmp_path)
    original = "existing.test:8001\n"
    static_file.write_text(original, encoding="utf-8")
    body = json.dumps({"mode": "static", "proxies": "secret-marker" + "x" * (1024 * 1024)}).encode()

    with client:
        response = client.post(
            "/configuration/proxies",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 400
    assert "large" in response.json()["detail"].lower()
    assert "secret-marker" not in response.text
    assert static_file.read_text(encoding="utf-8") == original


def test_replace_failure_preserves_original_and_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, static_file, _ = client_for(tmp_path)
    original = "existing.test:8001\n"
    static_file.write_text(original, encoding="utf-8")
    before = {path.name for path in tmp_path.iterdir()}

    def fail_replace(source: str | bytes | Path, destination: str | bytes | Path) -> None:
        del source, destination
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with client:
        response = client.post(
            "/configuration/proxies",
            json={"mode": "static", "proxies": "replacement.test:9001\n"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unable to save static proxy configuration"}
    assert static_file.read_text(encoding="utf-8") == original
    assert {path.name for path in tmp_path.iterdir()} == before


def test_encoding_failure_preserves_original_and_removes_temporary_file(tmp_path: Path) -> None:
    client, static_file, _ = client_for(tmp_path)
    original = "existing.test:8001\n"
    static_file.write_text(original, encoding="utf-8")
    before = {path.name for path in tmp_path.iterdir()}

    with client:
        response = client.post(
            "/configuration/proxies",
            content=json.dumps(
                {"mode": "static", "proxies": "# unsafe surrogate: \ud800", "confirm_clear": True}
            ),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unable to save static proxy configuration"}
    assert static_file.read_text(encoding="utf-8") == original
    assert {path.name for path in tmp_path.iterdir()} == before


def test_disallowed_origin_wins_before_body_parsing_or_filesystem_effects(tmp_path: Path) -> None:
    client, static_file, _ = client_for(tmp_path)
    original = "existing.test:8001\n"
    static_file.write_text(original, encoding="utf-8")
    before = {path.name for path in tmp_path.iterdir()}

    with client:
        response = client.post(
            "/configuration/proxies",
            content=b'{"mode":"static","proxies":"secret-marker',
            headers={"Content-Type": "application/json", "Origin": "https://blocked.test"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Origin not allowed"}
    assert "secret-marker" not in response.text
    assert static_file.read_text(encoding="utf-8") == original
    assert {path.name for path in tmp_path.iterdir()} == before

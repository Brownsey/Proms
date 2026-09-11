import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from proms.app import create_app

LOCAL_CONTROL_ORIGIN = "http://127.0.0.1:8000"


def client_for(tmp_path: Path) -> tuple[TestClient, Path]:
    proxy_file = tmp_path / "proxies.txt"
    return TestClient(create_app(proxy_file=proxy_file)), proxy_file


def test_save_proxy_list_replaces_list_and_refreshes_count(tmp_path: Path) -> None:
    client, proxy_file = client_for(tmp_path)
    proxy_file.write_text("old.test:7001\n", encoding="utf-8")
    submitted = "# local examples\none.test:8001\n\nhttps://user:placeholder@two.test:8002\n"

    with client:
        response = client.post(
            "/configuration/proxies",
            json={"proxies": submitted},
            headers={"Origin": LOCAL_CONTROL_ORIGIN},
        )
        configuration = client.get("/configuration")

    assert response.status_code == 200
    assert response.json() == {"count": 2}
    assert response.headers["access-control-allow-origin"] == LOCAL_CONTROL_ORIGIN
    assert response.headers["vary"] == "Origin"
    assert "access-control-allow-credentials" not in response.headers
    assert proxy_file.read_text(encoding="utf-8") == submitted
    assert configuration.json() == {"proxy_count": 2}


@pytest.mark.parametrize("submitted", ["", "\n# keep no proxies here\n"])
def test_empty_proxy_list_requires_explicit_clear_confirmation(
    tmp_path: Path, submitted: str
) -> None:
    client, static_file = client_for(tmp_path)
    original = "existing.test:8001\n"
    static_file.write_text(original, encoding="utf-8")

    with client:
        rejected = client.post("/configuration/proxies", json={"proxies": submitted})
        assert static_file.read_text(encoding="utf-8") == original
        accepted = client.post(
            "/configuration/proxies",
            json={"proxies": submitted, "confirm_clear": True},
        )

    assert rejected.status_code == 400
    assert "confirm_clear" in rejected.json()["detail"]
    assert accepted.json() == {"count": 0}
    assert static_file.read_text(encoding="utf-8") == submitted


@pytest.mark.parametrize(
    "body",
    [
        b'{"proxies":"secret-marker.test:8001"',
        b'["secret-marker.test:8001"]',
        b"{}",
        b'{"proxies":"one.test:8001","extra":"secret-marker"}',
        b'{"mode":"static","proxies":"secret-marker.test:8001"}',
        b'{"rotating_proxies":"secret-marker.test:8001","proxies":"one.test:8001"}',
        b'{"proxies":["secret-marker.test:8001"]}',
        b'{"proxies":"one.test:8001","confirm_clear":"yes"}',
    ],
)
def test_invalid_json_shape_and_types_are_secret_safe_and_leave_file_unchanged(
    tmp_path: Path, body: bytes
) -> None:
    client, static_file = client_for(tmp_path)
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
    client, static_file = client_for(tmp_path)
    original = "existing.test:8001\n"
    static_file.write_text(original, encoding="utf-8")

    with client:
        response = client.post(
            "/configuration/proxies",
            json={
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
    client, static_file = client_for(tmp_path)
    original = "existing.test:8001\n"
    static_file.write_text(original, encoding="utf-8")

    with client:
        response = client.post(
            "/configuration/proxies",
            json={"proxies": f"{bad_host}:9001"},
        )

    assert response.status_code == 400
    assert "secret-marker" not in response.text
    assert static_file.read_text(encoding="utf-8") == original


def test_url_proxy_rejects_percent_encoded_host_without_writing(tmp_path: Path) -> None:
    client, static_file = client_for(tmp_path)
    original = "existing.test:8001\n"
    static_file.write_text(original, encoding="utf-8")

    with client:
        response = client.post(
            "/configuration/proxies",
            json={"proxies": "http://bad%00secret-marker.test:9001"},
        )

    assert response.status_code == 400
    assert "secret-marker" not in response.text
    assert static_file.read_text(encoding="utf-8") == original


def test_oversize_body_is_rejected_safely_without_writing(tmp_path: Path) -> None:
    client, static_file = client_for(tmp_path)
    original = "existing.test:8001\n"
    static_file.write_text(original, encoding="utf-8")
    body = json.dumps({"proxies": "secret-marker" + "x" * (1024 * 1024)}).encode()

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
    client, static_file = client_for(tmp_path)
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
            json={"proxies": "replacement.test:9001\n"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unable to save proxy configuration"}
    assert static_file.read_text(encoding="utf-8") == original
    assert {path.name for path in tmp_path.iterdir()} == before


def test_encoding_failure_preserves_original_and_removes_temporary_file(tmp_path: Path) -> None:
    client, static_file = client_for(tmp_path)
    original = "existing.test:8001\n"
    static_file.write_text(original, encoding="utf-8")
    before = {path.name for path in tmp_path.iterdir()}

    with client:
        response = client.post(
            "/configuration/proxies",
            content=json.dumps({"proxies": "# unsafe surrogate: \ud800", "confirm_clear": True}),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unable to save proxy configuration"}
    assert static_file.read_text(encoding="utf-8") == original
    assert {path.name for path in tmp_path.iterdir()} == before


def test_disallowed_origin_wins_before_body_parsing_or_filesystem_effects(tmp_path: Path) -> None:
    client, static_file = client_for(tmp_path)
    original = "existing.test:8001\n"
    static_file.write_text(original, encoding="utf-8")
    before = {path.name for path in tmp_path.iterdir()}

    with client:
        response = client.post(
            "/configuration/proxies",
            content=b'{"proxies":"secret-marker',
            headers={"Content-Type": "application/json", "Origin": "https://blocked.test"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Origin not allowed"}
    assert "secret-marker" not in response.text
    assert static_file.read_text(encoding="utf-8") == original
    assert {path.name for path in tmp_path.iterdir()} == before

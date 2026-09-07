from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_api import FakeLauncher, write_proxies

from proms.app import create_app

PRODUCTION_ORIGIN = "https://proms-rust.vercel.app"


def test_health_and_missing_or_empty_configuration_are_safe(tmp_path: Path) -> None:
    static_file = tmp_path / "proxies.txt"
    rotating_file = tmp_path / "rotating_proxies.txt"
    static_file.write_text("\n# no configured proxies\n", encoding="utf-8")
    app = create_app(proxy_file=static_file, rotating_proxy_file=rotating_file)

    with TestClient(app) as client:
        health = client.get("/health")
        configuration = client.get("/configuration")

    assert health.json() == {"status": "ok"}
    assert configuration.json() == {
        "static_proxy_count": 0,
        "rotating_proxy_count": 0,
    }


def test_configuration_returns_counts_without_proxy_values(tmp_path: Path) -> None:
    static_file = tmp_path / "proxies.txt"
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(static_file, "https://alice:secret@static.test:8001")
    write_proxies(rotating_file, "rotate-one.test:9001", "rotate-two.test:9002")
    app = create_app(proxy_file=static_file, rotating_proxy_file=rotating_file)

    with TestClient(app) as client:
        response = client.get("/configuration")

    assert response.json() == {
        "static_proxy_count": 1,
        "rotating_proxy_count": 2,
    }
    assert "secret" not in response.text
    assert "static.test" not in response.text


def test_configuration_rejects_a_malformed_existing_file(tmp_path: Path) -> None:
    static_file = tmp_path / "proxies.txt"
    static_file.write_text("not-a-proxy", encoding="utf-8")
    app = create_app(
        proxy_file=static_file,
        rotating_proxy_file=tmp_path / "missing-rotating.txt",
    )

    with TestClient(app) as client:
        response = client.get("/configuration")

    assert response.status_code == 400
    assert "line 1" in response.json()["detail"]
    assert "not-a-proxy" not in response.text


@pytest.mark.parametrize(
    "origin",
    [
        PRODUCTION_ORIGIN,
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
)
def test_default_origins_receive_exact_cors_headers(origin: str) -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["vary"] == "Origin"
    assert "access-control-allow-credentials" not in response.headers


def test_environment_and_injected_origins_are_additions(monkeypatch) -> None:
    monkeypatch.setenv(
        "PROMS_ALLOWED_ORIGINS",
        " https://env-one.test,https://env-two.test, ,",
    )
    app = create_app(allowed_origins=["https://injected.test"])

    with TestClient(app) as client:
        for origin in [PRODUCTION_ORIGIN, "https://env-two.test", "https://injected.test"]:
            response = client.get("/health", headers={"Origin": origin})
            assert response.headers["access-control-allow-origin"] == origin


def test_allowed_production_origin_can_mutate_and_preflight(tmp_path: Path) -> None:
    static_file = tmp_path / "proxies.txt"
    write_proxies(static_file, "static.test:8001")
    launcher = FakeLauncher()
    app = create_app(proxy_file=static_file, launch_browser=launcher)

    with TestClient(app) as client:
        preflight = client.options(
            "/browsers",
            headers={
                "Origin": PRODUCTION_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        launched = client.post(
            "/browsers",
            json={"windows_per_proxy": 1},
            headers={"Origin": PRODUCTION_ORIGIN},
        )

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == PRODUCTION_ORIGIN
    assert "POST" in preflight.headers["access-control-allow-methods"]
    assert "Content-Type" in preflight.headers["access-control-allow-headers"]
    assert launched.status_code == 200
    assert launched.headers["access-control-allow-origin"] == PRODUCTION_ORIGIN
    assert launched.headers["vary"] == "Origin"
    assert len(launcher.browsers) == 1


def test_disallowed_origin_cannot_launch_or_close_browsers(tmp_path: Path) -> None:
    static_file = tmp_path / "proxies.txt"
    write_proxies(static_file, "static.test:8001")
    launcher = FakeLauncher()
    app = create_app(proxy_file=static_file, launch_browser=launcher)

    with TestClient(app) as client:
        assert client.post("/browsers", json={"windows_per_proxy": 1}).status_code == 200
        existing = launcher.browsers[0]
        static_file.unlink()

        launch = client.post(
            "/browsers",
            json={"windows_per_proxy": 1},
            headers={"Origin": "https://evil.test"},
        )
        close = client.delete("/browsers", headers={"Origin": "https://evil.test"})

        assert launch.status_code == 403
        assert close.status_code == 403
        assert len(launcher.browsers) == 1
        assert not existing.closed
        assert client.get("/browsers").json() == {"active": 1}
        assert client.delete("/browsers").json() == {"closed": 1}

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_api import FakeLauncher, write_proxies

from proms.app import create_app

PRODUCTION_ORIGIN = "https://proms.brownsey.co.uk"


def test_health_and_missing_or_empty_configuration_are_safe(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("\n# no configured proxies\n", encoding="utf-8")
    app = create_app(proxy_file=proxy_file)

    with TestClient(app) as client:
        health = client.get("/health")
        configuration = client.get("/configuration")

    assert health.json() == {"status": "ok"}
    assert configuration.json() == {"proxy_count": 0}


def test_configuration_returns_counts_without_proxy_values(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    write_proxies(proxy_file, "https://alice:secret@fixed.test:8001", "sticky.test:9001")
    app = create_app(proxy_file=proxy_file)

    with TestClient(app) as client:
        response = client.get("/configuration")

    assert response.json() == {"proxy_count": 2}
    assert "secret" not in response.text
    assert "fixed.test" not in response.text


def test_configuration_rejects_a_malformed_existing_file(tmp_path: Path) -> None:
    static_file = tmp_path / "proxies.txt"
    static_file.write_text("not-a-proxy", encoding="utf-8")
    app = create_app(proxy_file=static_file)

    with TestClient(app) as client:
        response = client.get("/configuration")

    assert response.status_code == 400
    assert "line 1" in response.json()["detail"]
    assert "not-a-proxy" not in response.text


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
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


def test_external_environment_and_injected_origins_remain_blocked(monkeypatch) -> None:
    monkeypatch.setenv(
        "PROMS_ALLOWED_ORIGINS",
        " https://env-one.test,https://env-two.test, ,",
    )
    app = create_app(allowed_origins=["https://injected.test"])

    with TestClient(app) as client:
        for origin in ["https://env-one.test", "https://injected.test"]:
            response = client.get("/health", headers={"Origin": origin})
            assert response.status_code == 403
            assert "access-control-allow-origin" not in response.headers


def test_valid_configured_loopback_origins_are_allowed(monkeypatch) -> None:
    monkeypatch.setenv("PROMS_ALLOWED_ORIGINS", "http://127.0.0.2:8123")
    app = create_app(allowed_origins=["http://[::1]:9000"])

    with TestClient(app) as client:
        for origin in ["http://127.0.0.2:8123", "http://[::1]:9000"]:
            response = client.get("/health", headers={"Origin": origin})
            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize(
    "origin",
    [
        "https://localhost:8000",
        "http://localhost:0",
        "http://localhost:8000/path",
        "http://user@localhost:8000",
        "not-an-origin",
    ],
)
def test_malformed_configured_origins_remain_blocked(origin: str) -> None:
    app = create_app(allowed_origins=[origin])

    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": origin})

    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


def test_hosted_origin_remains_blocked_when_environment_or_caller_injects_it(
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROMS_ALLOWED_ORIGINS", PRODUCTION_ORIGIN)
    app = create_app(allowed_origins=[PRODUCTION_ORIGIN])

    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": PRODUCTION_ORIGIN})

    assert "access-control-allow-origin" not in response.headers


def test_local_control_origin_can_mutate_and_preflight(tmp_path: Path) -> None:
    static_file = tmp_path / "proxies.txt"
    write_proxies(static_file, "static.test:8001")
    launcher = FakeLauncher()
    app = create_app(proxy_file=static_file, launch_browser=launcher)

    with TestClient(app) as client:
        preflight = client.options(
            "/browsers",
            headers={
                "Origin": "http://127.0.0.1:8000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        launched = client.post(
            "/browsers",
            json={"windows_per_proxy": 1},
            headers={"Origin": "http://127.0.0.1:8000"},
        )

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:8000"
    assert "POST" in preflight.headers["access-control-allow-methods"]
    assert "Content-Type" in preflight.headers["access-control-allow-headers"]
    assert launched.status_code == 200
    assert launched.headers["access-control-allow-origin"] == "http://127.0.0.1:8000"
    assert launched.headers["vary"] == "Origin"
    assert len(launcher.browsers) == 1


def test_local_control_origin_can_preflight_private_network_health() -> None:
    with TestClient(create_app()) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": "http://127.0.0.1:8000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Private-Network": "true",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:8000"
    assert response.headers["access-control-allow-private-network"] == "true"


def test_hosted_origin_cannot_read_mutate_or_preflight_private_network(
    tmp_path: Path,
) -> None:
    static_file = tmp_path / "proxies.txt"
    write_proxies(static_file, "static.test:8001")
    launcher = FakeLauncher()
    app = create_app(proxy_file=static_file, launch_browser=launcher)

    with TestClient(app) as client:
        read = client.get("/configuration", headers={"Origin": PRODUCTION_ORIGIN})
        mutation = client.post(
            "/browsers",
            json={"windows_per_proxy": 1},
            headers={"Origin": PRODUCTION_ORIGIN},
        )
        preflight = client.options(
            "/health",
            headers={
                "Origin": PRODUCTION_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Private-Network": "true",
            },
        )

    assert read.status_code == 403
    assert "access-control-allow-origin" not in read.headers
    assert mutation.status_code == 403
    assert len(launcher.browsers) == 0
    assert preflight.status_code >= 400
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-private-network" not in preflight.headers


def test_disallowed_origin_cannot_preflight_private_network_health() -> None:
    with TestClient(create_app()) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": "https://evil.test",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Private-Network": "true",
            },
        )

    assert response.status_code >= 400
    assert "access-control-allow-origin" not in response.headers


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

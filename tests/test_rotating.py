import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_api import FakeLauncher, write_proxies

from proms.app import BrowserManager, create_app

IP_CHECK_URL = "https://check.test/ip"
TARGET_URL = "https://target.test/path"


def test_mixed_launch_uses_each_proxy_count_and_loads_target_url(tmp_path: Path) -> None:
    static_file = tmp_path / "proxies.txt"
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(static_file, "static-one.test:8001", "static-two.test:8002")
    write_proxies(rotating_file, "rotate.test:9001")
    launcher = FakeLauncher()
    app = create_app(
        proxy_file=static_file,
        rotating_proxy_file=rotating_file,
        ip_check_url=IP_CHECK_URL,
        launch_browser=launcher,
    )

    with TestClient(app) as client:
        response = client.post(
            "/browsers",
            json={
                "static_windows_per_proxy": 2,
                "rotating_windows_per_proxy": 2,
                "url": TARGET_URL,
            },
        )

        assert response.json() == {"launched": 6, "active": 6}
        assert launcher.proxies == [
            {"server": "http://static-one.test:8001"},
            {"server": "http://static-one.test:8001"},
            {"server": "http://static-two.test:8002"},
            {"server": "http://static-two.test:8002"},
            {"server": "http://rotate.test:9001"},
            {"server": "http://rotate.test:9001"},
        ]
        assert [browser.page_urls for browser in launcher.browsers[:4]] == [
            ["about:blank", TARGET_URL],
        ] * 4
        assert [browser.page_urls for browser in launcher.browsers[4:]] == [
            ["about:blank", IP_CHECK_URL, TARGET_URL],
        ] * 2


def test_legacy_request_remains_static_only_and_defaults_to_blank(tmp_path: Path) -> None:
    static_file = tmp_path / "proxies.txt"
    write_proxies(static_file, "static.test:8001")
    launcher = FakeLauncher()
    app = create_app(
        proxy_file=static_file,
        rotating_proxy_file=tmp_path / "missing-rotating.txt",
        launch_browser=launcher,
    )

    with TestClient(app) as client:
        response = client.post("/browsers", json={"windows_per_proxy": 1})

    assert response.json() == {"launched": 1, "active": 1}
    assert launcher.browsers[0].page_urls == ["about:blank"]


def test_only_requested_proxy_list_is_loaded(tmp_path: Path) -> None:
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(rotating_file, "rotate.test:9001")
    rotating_launcher = FakeLauncher()
    rotating_app = create_app(
        proxy_file=tmp_path / "missing-static.txt",
        rotating_proxy_file=rotating_file,
        ip_check_url=IP_CHECK_URL,
        launch_browser=rotating_launcher,
    )

    with TestClient(rotating_app) as client:
        rotating = client.post("/browsers", json={"rotating_windows_per_proxy": 1})

    static_file = tmp_path / "proxies.txt"
    write_proxies(static_file, "static.test:8001")
    static_app = create_app(
        proxy_file=static_file,
        rotating_proxy_file=tmp_path / "missing-rotating.txt",
        launch_browser=FakeLauncher(),
    )
    with TestClient(static_app) as client:
        static = client.post("/browsers", json={"static_windows_per_proxy": 1})

    assert rotating.status_code == 200
    assert static.status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"static_windows_per_proxy": 0, "rotating_windows_per_proxy": 0},
        {"windows_per_proxy": 1, "static_windows_per_proxy": 0},
        {"windows_per_proxy": 1, "rotating_windows_per_proxy": 1},
        {"static_windows_per_proxy": True},
        {"rotating_windows_per_proxy": "1"},
        {"static_windows_per_proxy": -1},
        {"rotating_windows_per_proxy": 1, "rotation_attempts": 0},
        {"rotating_windows_per_proxy": 1, "rotation_attempts": 21},
        {"static_windows_per_proxy": 1, "url": "/relative"},
        {"static_windows_per_proxy": 1, "url": "ftp://target.test"},
        {"static_windows_per_proxy": 1, "url": "https://bad host.test"},
    ],
)
def test_v2_request_validation_returns_400(tmp_path: Path, payload: dict[str, object]) -> None:
    static_file = tmp_path / "proxies.txt"
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(static_file, "static.test:8001")
    write_proxies(rotating_file, "rotate.test:9001")
    app = create_app(
        proxy_file=static_file,
        rotating_proxy_file=rotating_file,
        launch_browser=FakeLauncher(),
    )

    with TestClient(app) as client:
        response = client.post("/browsers", json=payload)

    assert response.status_code == 400


def test_requested_missing_rotating_proxy_list_returns_400(tmp_path: Path) -> None:
    app = create_app(
        proxy_file=tmp_path / "missing-static.txt",
        rotating_proxy_file=tmp_path / "missing-rotating.txt",
        launch_browser=FakeLauncher(),
    )

    with TestClient(app) as client:
        response = client.post("/browsers", json={"rotating_windows_per_proxy": 1})

    assert response.status_code == 400
    assert "not found" in response.json()["detail"]


def test_rotating_duplicate_ip_retries_with_a_fresh_browser(tmp_path: Path) -> None:
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(rotating_file, "rotate.test:9001")
    launcher = FakeLauncher()
    launcher.ip_bodies = {
        1: "198.51.100.1\n",
        2: "198.51.100.1",
        3: "198.51.100.2",
    }
    app = create_app(
        rotating_proxy_file=rotating_file,
        ip_check_url=IP_CHECK_URL,
        launch_browser=launcher,
    )

    with TestClient(app) as client:
        response = client.post(
            "/browsers",
            json={"rotating_windows_per_proxy": 2, "rotation_attempts": 2},
        )

        assert response.json() == {"launched": 2, "active": 2}
        assert len(launcher.browsers) == 3
        assert launcher.browsers[1].closed


def test_rotating_invalid_ip_retries_with_a_fresh_browser(tmp_path: Path) -> None:
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(rotating_file, "rotate.test:9001")
    launcher = FakeLauncher()
    launcher.ip_bodies = {1: "not an ip", 2: "198.51.100.2"}
    app = create_app(
        rotating_proxy_file=rotating_file,
        ip_check_url=IP_CHECK_URL,
        launch_browser=launcher,
    )

    with TestClient(app) as client:
        response = client.post(
            "/browsers",
            json={"rotating_windows_per_proxy": 1, "rotation_attempts": 2},
        )

        assert response.json() == {"launched": 1, "active": 1}
        assert launcher.browsers[0].closed
        assert not launcher.browsers[1].closed


def test_rotating_retry_surfaces_a_browser_that_could_not_close(tmp_path: Path) -> None:
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(rotating_file, "rotate.test:9001")
    launcher = FakeLauncher()
    launcher.ip_bodies = {1: "not an ip"}
    launcher.close_errors = {1: "connected"}
    app = create_app(
        rotating_proxy_file=rotating_file,
        ip_check_url=IP_CHECK_URL,
        launch_browser=launcher,
    )

    with TestClient(app) as client:
        response = client.post(
            "/browsers",
            json={"rotating_windows_per_proxy": 1, "rotation_attempts": 2},
        )

        assert response.status_code == 400
        assert "1 browser(s) remain active" in response.json()["detail"]
        assert client.get("/browsers").json() == {"active": 1}
        launcher.browsers[0].close_error = None
        assert client.delete("/browsers").json() == {"closed": 1}


def test_rotating_exhaustion_rolls_back_request_and_preserves_old_browser(
    tmp_path: Path,
) -> None:
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(rotating_file, "rotate.test:9001")
    launcher = FakeLauncher()
    launcher.ip_bodies = {
        1: "198.51.100.1",
        2: "198.51.100.2",
        3: "198.51.100.1",
        4: "198.51.100.1",
    }
    app = create_app(
        rotating_proxy_file=rotating_file,
        ip_check_url=IP_CHECK_URL,
        launch_browser=launcher,
    )

    with TestClient(app) as client:
        assert client.post("/browsers", json={"rotating_windows_per_proxy": 1}).status_code == 200
        existing = launcher.browsers[0]

        response = client.post(
            "/browsers",
            json={"rotating_windows_per_proxy": 2, "rotation_attempts": 2},
        )

        assert response.status_code == 400
        assert "unique IP" in response.json()["detail"]
        assert not existing.closed
        assert all(browser.closed for browser in launcher.browsers[1:])
        assert client.get("/browsers").json() == {"active": 1}


@pytest.mark.asyncio
async def test_concurrent_rotating_requests_cannot_accept_the_same_ip(tmp_path: Path) -> None:
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(rotating_file, "rotate.test:9001")
    launcher = FakeLauncher()
    launcher.ip_bodies = {
        1: "198.51.100.1",
        2: "198.51.100.1",
        3: "198.51.100.2",
    }
    app = create_app(
        rotating_proxy_file=rotating_file,
        ip_check_url=IP_CHECK_URL,
        launch_browser=launcher,
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            responses = await asyncio.gather(
                client.post(
                    "/browsers",
                    json={"rotating_windows_per_proxy": 1, "rotation_attempts": 2},
                ),
                client.post(
                    "/browsers",
                    json={"rotating_windows_per_proxy": 1, "rotation_attempts": 2},
                ),
            )

            assert [response.status_code for response in responses] == [200, 200]
            assert (await client.get("/browsers")).json() == {"active": 2}
            assert len(launcher.browsers) == 3
            assert sum(browser.closed for browser in launcher.browsers) == 1

    assert sum(browser.closed for browser in launcher.browsers) == 3


def test_disconnected_rotating_browser_releases_its_ip(tmp_path: Path) -> None:
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(rotating_file, "rotate.test:9001")
    launcher = FakeLauncher()
    launcher.ip_bodies = {
        1: "198.51.100.1",
        2: "198.51.100.1",
        3: "198.51.100.1",
    }
    app = create_app(
        rotating_proxy_file=rotating_file,
        ip_check_url=IP_CHECK_URL,
        launch_browser=launcher,
    )

    with TestClient(app) as client:
        assert client.post("/browsers", json={"rotating_windows_per_proxy": 1}).status_code == 200
        launcher.browsers[0].connected = False

        response = client.post("/browsers", json={"rotating_windows_per_proxy": 1})

        assert response.json() == {"launched": 1, "active": 1}
        assert not launcher.browsers[1].closed
        assert client.delete("/browsers").json() == {"closed": 1}
        reused_after_close = client.post("/browsers", json={"rotating_windows_per_proxy": 1})
        assert reused_after_close.json() == {"launched": 1, "active": 1}


def test_ip_navigation_failure_retries_but_target_failure_rolls_back(tmp_path: Path) -> None:
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(rotating_file, "rotate.test:9001")
    launcher = FakeLauncher()
    launcher.navigation_errors = {1: {IP_CHECK_URL}, 3: {TARGET_URL}}
    app = create_app(
        rotating_proxy_file=rotating_file,
        ip_check_url=IP_CHECK_URL,
        launch_browser=launcher,
    )

    with TestClient(app) as client:
        retried = client.post(
            "/browsers",
            json={
                "rotating_windows_per_proxy": 1,
                "rotation_attempts": 2,
                "url": TARGET_URL,
            },
        )
        target_failed = client.post(
            "/browsers",
            json={"rotating_windows_per_proxy": 1, "url": TARGET_URL},
        )

        assert retried.status_code == 200
        assert launcher.browsers[0].closed
        assert target_failed.status_code == 400
        assert "Navigation failed" in target_failed.json()["detail"]
        assert launcher.browsers[2].closed
        assert client.get("/browsers").json() == {"active": 1}


@pytest.mark.asyncio
async def test_concurrent_post_waits_for_failed_transaction_rollback(tmp_path: Path) -> None:
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(rotating_file, "rotate.test:9001")
    close_entered = asyncio.Event()
    release_close = asyncio.Event()
    launcher = FakeLauncher()
    launcher.ip_bodies = {
        1: "198.51.100.1",
        2: "not an ip",
        3: "198.51.100.1",
    }
    launcher.close_waits = {1: (close_entered, release_close)}
    app = create_app(
        rotating_proxy_file=rotating_file,
        ip_check_url=IP_CHECK_URL,
        launch_browser=launcher,
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            failing = asyncio.create_task(
                client.post(
                    "/browsers",
                    json={
                        "rotating_windows_per_proxy": 2,
                        "rotation_attempts": 1,
                    },
                )
            )
            await close_entered.wait()
            concurrent = asyncio.create_task(
                client.post(
                    "/browsers",
                    json={"rotating_windows_per_proxy": 1},
                )
            )
            for _ in range(3):
                await asyncio.sleep(0)
            try:
                assert len(launcher.proxies) == 2
            finally:
                release_close.set()

            failed_response, concurrent_response = await asyncio.gather(failing, concurrent)
            assert failed_response.status_code == 400
            assert concurrent_response.status_code == 200


@pytest.mark.asyncio
async def test_concurrent_post_waits_for_delete_close_outcome(tmp_path: Path) -> None:
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(rotating_file, "rotate.test:9001")
    close_entered = asyncio.Event()
    release_close = asyncio.Event()
    launcher = FakeLauncher()
    launcher.ip_bodies = {1: "198.51.100.1", 2: "198.51.100.1"}
    launcher.close_waits = {1: (close_entered, release_close)}
    app = create_app(
        rotating_proxy_file=rotating_file,
        ip_check_url=IP_CHECK_URL,
        launch_browser=launcher,
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (
                await client.post("/browsers", json={"rotating_windows_per_proxy": 1})
            ).status_code == 200
            deleting = asyncio.create_task(client.delete("/browsers"))
            await close_entered.wait()
            concurrent = asyncio.create_task(
                client.post("/browsers", json={"rotating_windows_per_proxy": 1})
            )
            for _ in range(3):
                await asyncio.sleep(0)
            try:
                assert len(launcher.proxies) == 1
            finally:
                release_close.set()

            delete_response, post_response = await asyncio.gather(deleting, concurrent)
            assert delete_response.json() == {"closed": 1}
            assert post_response.status_code == 200


def test_unknown_rotating_ip_blocks_launch_until_delete_recovers(tmp_path: Path) -> None:
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(rotating_file, "rotate.test:9001")
    launcher = FakeLauncher()
    launcher.ip_bodies = {1: "not an ip", 2: "198.51.100.2"}
    launcher.close_errors = {1: "connected"}
    app = create_app(
        rotating_proxy_file=rotating_file,
        ip_check_url=IP_CHECK_URL,
        launch_browser=launcher,
    )

    with TestClient(app) as client:
        failed = client.post("/browsers", json={"rotating_windows_per_proxy": 1})
        blocked = client.post("/browsers", json={"rotating_windows_per_proxy": 1})

        try:
            assert failed.status_code == 400
            assert blocked.status_code == 400
            assert "unknown IP" in blocked.json()["detail"]
            assert len(launcher.proxies) == 1
        finally:
            launcher.browsers[0].close_error = None
            cleanup = client.delete("/browsers")
        assert cleanup.json() == {"closed": 1}
        recovered = client.post("/browsers", json={"rotating_windows_per_proxy": 1})
        assert recovered.status_code == 200


def test_static_browser_with_no_rotating_ip_does_not_block_rotation(tmp_path: Path) -> None:
    static_file = tmp_path / "proxies.txt"
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(static_file, "static.test:8001")
    write_proxies(rotating_file, "rotate.test:9001")
    launcher = FakeLauncher()
    app = create_app(
        proxy_file=static_file,
        rotating_proxy_file=rotating_file,
        ip_check_url=IP_CHECK_URL,
        launch_browser=launcher,
    )

    with TestClient(app) as client:
        assert client.post("/browsers", json={"windows_per_proxy": 1}).status_code == 200
        rotating = client.post("/browsers", json={"rotating_windows_per_proxy": 1})

        assert rotating.json() == {"launched": 1, "active": 2}


def test_unknown_rotating_ip_blocks_mixed_request_before_static_launch(
    tmp_path: Path,
) -> None:
    static_file = tmp_path / "proxies.txt"
    rotating_file = tmp_path / "rotating_proxies.txt"
    write_proxies(static_file, "static.test:8001")
    write_proxies(rotating_file, "rotate.test:9001")
    launcher = FakeLauncher()
    launcher.ip_bodies = {1: "not an ip"}
    launcher.close_errors = {1: "connected"}
    app = create_app(
        proxy_file=static_file,
        rotating_proxy_file=rotating_file,
        ip_check_url=IP_CHECK_URL,
        launch_browser=launcher,
    )

    with TestClient(app) as client:
        failed = client.post("/browsers", json={"rotating_windows_per_proxy": 1})
        mixed = client.post(
            "/browsers",
            json={
                "static_windows_per_proxy": 1,
                "rotating_windows_per_proxy": 1,
            },
        )

        try:
            assert failed.status_code == 400
            assert mixed.status_code == 400
            assert "unknown IP" in mixed.json()["detail"]
            assert len(launcher.proxies) == 1
            assert len(launcher.browsers) == 1
        finally:
            launcher.browsers[0].close_error = None
            client.delete("/browsers")


@pytest.mark.asyncio
async def test_cancellation_after_first_browser_rolls_back_owned_browser() -> None:
    launch_entered = asyncio.Event()
    release_launch = asyncio.Event()
    launcher = FakeLauncher()
    launcher.launch_waits = {2: (launch_entered, release_launch)}
    manager = BrowserManager(launcher)
    task = asyncio.create_task(
        manager.launch(
            [{"server": "http://one.test:8001"}, {"server": "http://two.test:8002"}],
            1,
        )
    )
    await launch_entered.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert launcher.browsers[0].closed
    assert manager.active() == 0


@pytest.mark.asyncio
async def test_cancellation_during_new_page_closes_owned_browser() -> None:
    page_entered = asyncio.Event()
    release_page = asyncio.Event()
    launcher = FakeLauncher()
    launcher.new_page_waits = {1: (page_entered, release_page)}
    manager = BrowserManager(launcher)
    task = asyncio.create_task(manager.launch([{"server": "http://one.test:8001"}], 1))
    await page_entered.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert launcher.browsers[0].closed
    assert manager.active() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_url", [IP_CHECK_URL, TARGET_URL])
async def test_cancellation_during_rotating_navigation_closes_owned_browser(
    blocked_url: str,
) -> None:
    navigation_entered = asyncio.Event()
    release_navigation = asyncio.Event()
    launcher = FakeLauncher()
    launcher.ip_bodies = {1: "198.51.100.1"}
    launcher.navigation_waits = {1: {blocked_url: (navigation_entered, release_navigation)}}
    manager = BrowserManager(launcher)
    task = asyncio.create_task(
        manager.launch(
            [],
            0,
            url=TARGET_URL,
            rotating_proxies=[{"server": "http://rotate.test:9001"}],
            rotating_windows_per_proxy=1,
            ip_check_url=IP_CHECK_URL,
        )
    )
    await navigation_entered.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert launcher.browsers[0].closed
    assert manager.active() == 0


@pytest.mark.asyncio
async def test_cancellation_during_rollback_waits_for_cleanup() -> None:
    close_entered = asyncio.Event()
    release_close = asyncio.Event()
    launcher = FakeLauncher()
    launcher.ip_bodies = {1: "198.51.100.1", 2: "not an ip"}
    launcher.close_waits = {1: (close_entered, release_close)}
    manager = BrowserManager(launcher)
    task = asyncio.create_task(
        manager.launch(
            [],
            0,
            rotating_proxies=[{"server": "http://rotate.test:9001"}],
            rotating_windows_per_proxy=2,
            rotation_attempts=1,
            ip_check_url=IP_CHECK_URL,
        )
    )
    await close_entered.wait()

    task.cancel()
    release_close.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert all(browser.closed for browser in launcher.browsers)
    assert manager.active() == 0


@pytest.mark.asyncio
async def test_close_all_cancellation_retains_connected_failure_for_retry() -> None:
    close_entered = asyncio.Event()
    release_close = asyncio.Event()
    launcher = FakeLauncher()
    launcher.close_errors = {1: "connected"}
    launcher.close_waits = {1: (close_entered, release_close)}
    manager = BrowserManager(launcher)
    await manager.launch([{"server": "http://one.test:8001"}], 1)
    task = asyncio.create_task(manager.close_all())
    await close_entered.wait()

    task.cancel()
    release_close.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert manager.active() == 1
    launcher.browsers[0].close_error = None
    assert await manager.close_all() == 1


@pytest.mark.asyncio
async def test_close_boundary_cancellation_is_retained_and_re_raised() -> None:
    launcher = FakeLauncher()
    launcher.close_errors = {1: "cancelled"}
    manager = BrowserManager(launcher)
    await manager.launch([{"server": "http://one.test:8001"}], 1)

    with pytest.raises(asyncio.CancelledError):
        await manager.close_all()

    assert manager.active() == 1
    launcher.browsers[0].close_error = None
    assert await manager.close_all() == 1

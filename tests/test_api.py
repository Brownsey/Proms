from collections.abc import Mapping
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from proms.app import BrowserCloseError, BrowserManager, create_app


class FakeBrowser:
    def __init__(self, *, page_error: bool = False, close_error: str | None = None) -> None:
        self.connected = True
        self.closed = False
        self.page_error = page_error
        self.close_error = close_error
        self.close_attempts = 0
        self.page_urls: list[str] = []

    def is_connected(self) -> bool:
        return self.connected

    async def close(self) -> None:
        self.close_attempts += 1
        if self.close_error == "connected":
            raise RuntimeError("Chromium refused to close")
        self.connected = False
        self.closed = True
        if self.close_error == "disconnected":
            raise RuntimeError("Chromium disconnected while closing")

    async def new_page(self) -> object:
        if self.page_error:
            raise RuntimeError("Chromium refused to open a page")
        self.page_urls.append("about:blank")
        return object()


class FakeLauncher:
    def __init__(self) -> None:
        self.proxies: list[dict[str, str]] = []
        self.browsers: list[FakeBrowser] = []
        self.fail_on_call: int | None = None
        self.fail_page_on_call: int | None = None
        self.close_errors: dict[int, str] = {}

    async def __call__(self, proxy: Mapping[str, str]) -> FakeBrowser:
        call_number = len(self.proxies) + 1
        self.proxies.append(dict(proxy))
        if call_number == self.fail_on_call:
            raise RuntimeError("Chromium refused to start")
        browser = FakeBrowser(
            page_error=call_number == self.fail_page_on_call,
            close_error=self.close_errors.get(call_number),
        )
        self.browsers.append(browser)
        return browser


def write_proxies(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines), encoding="utf-8")


def test_post_launches_requested_headed_browser_per_proxy(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    write_proxies(proxy_file, "one.test:8001", "socks5://two.test:8002")
    launcher = FakeLauncher()

    with TestClient(create_app(proxy_file=proxy_file, launch_browser=launcher)) as client:
        response = client.post("/browsers", json={"windows_per_proxy": 2})

        assert response.status_code == 200
        assert response.json() == {"launched": 4, "active": 4}
        assert launcher.proxies == [
            {"server": "http://one.test:8001"},
            {"server": "http://one.test:8001"},
            {"server": "socks5://two.test:8002"},
            {"server": "socks5://two.test:8002"},
        ]
        assert [browser.page_urls for browser in launcher.browsers] == [
            ["about:blank"],
            ["about:blank"],
            ["about:blank"],
            ["about:blank"],
        ]
        assert client.get("/browsers").json() == {"active": 4}


def test_post_reads_proxy_file_again_for_each_request(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    launcher = FakeLauncher()
    write_proxies(proxy_file, "first.test:8001")

    with TestClient(create_app(proxy_file=proxy_file, launch_browser=launcher)) as client:
        assert client.post("/browsers", json={"windows_per_proxy": 1}).json()["launched"] == 1
        write_proxies(proxy_file, "second.test:8002", "third.test:8003")
        assert client.post("/browsers", json={"windows_per_proxy": 1}).json() == {
            "launched": 2,
            "active": 3,
        }

    assert launcher.proxies == [
        {"server": "http://first.test:8001"},
        {"server": "http://second.test:8002"},
        {"server": "http://third.test:8003"},
    ]


def test_delete_closes_all_active_browsers(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    write_proxies(proxy_file, "one.test:8001", "two.test:8002")
    launcher = FakeLauncher()

    with TestClient(create_app(proxy_file=proxy_file, launch_browser=launcher)) as client:
        client.post("/browsers", json={"windows_per_proxy": 1})

        assert client.delete("/browsers").json() == {"closed": 2}
        assert client.get("/browsers").json() == {"active": 0}
        assert all(browser.closed for browser in launcher.browsers)


def test_lifespan_closes_active_browsers(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    write_proxies(proxy_file, "one.test:8001")
    launcher = FakeLauncher()

    with TestClient(create_app(proxy_file=proxy_file, launch_browser=launcher)) as client:
        client.post("/browsers", json={"windows_per_proxy": 1})
        browser = launcher.browsers[0]
        assert not browser.closed

    assert browser.closed


def test_failed_launch_rolls_back_only_new_browsers(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    write_proxies(proxy_file, "one.test:8001")
    launcher = FakeLauncher()

    with TestClient(create_app(proxy_file=proxy_file, launch_browser=launcher)) as client:
        assert client.post("/browsers", json={"windows_per_proxy": 1}).status_code == 200
        existing = launcher.browsers[0]
        launcher.fail_on_call = 3

        response = client.post("/browsers", json={"windows_per_proxy": 2})

        assert response.status_code == 400
        assert "Chromium refused to start" in response.json()["detail"]
        assert not existing.closed
        assert launcher.browsers[1].closed
        assert client.get("/browsers").json() == {"active": 1}


def test_failed_page_creation_closes_the_browser_and_rolls_back_request(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    write_proxies(proxy_file, "one.test:8001")
    launcher = FakeLauncher()

    with TestClient(create_app(proxy_file=proxy_file, launch_browser=launcher)) as client:
        assert client.post("/browsers", json={"windows_per_proxy": 1}).status_code == 200
        existing = launcher.browsers[0]
        launcher.fail_page_on_call = 3

        response = client.post("/browsers", json={"windows_per_proxy": 2})

        assert response.status_code == 400
        assert "Chromium refused to open a page" in response.json()["detail"]
        assert not existing.closed
        assert launcher.browsers[1].closed
        assert launcher.browsers[2].closed
        assert client.get("/browsers").json() == {"active": 1}


def test_failed_launch_retains_a_new_browser_that_could_not_close(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    write_proxies(proxy_file, "one.test:8001")
    launcher = FakeLauncher()

    with TestClient(create_app(proxy_file=proxy_file, launch_browser=launcher)) as client:
        assert client.post("/browsers", json={"windows_per_proxy": 1}).status_code == 200
        existing = launcher.browsers[0]
        launcher.close_errors[2] = "connected"
        launcher.fail_on_call = 3

        response = client.post("/browsers", json={"windows_per_proxy": 2})

        retained = launcher.browsers[1]
        assert response.status_code == 400
        assert "1 browser(s) remain active" in response.json()["detail"]
        assert not existing.closed
        assert retained.close_attempts == 1
        assert client.get("/browsers").json() == {"active": 2}
        retained.close_error = None
        assert client.delete("/browsers").json() == {"closed": 2}


def test_failed_page_creation_retains_its_browser_when_close_fails(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    write_proxies(proxy_file, "one.test:8001")
    launcher = FakeLauncher()

    with TestClient(create_app(proxy_file=proxy_file, launch_browser=launcher)) as client:
        assert client.post("/browsers", json={"windows_per_proxy": 1}).status_code == 200
        launcher.fail_page_on_call = 2
        launcher.close_errors[2] = "connected"

        response = client.post("/browsers", json={"windows_per_proxy": 1})

        retained = launcher.browsers[1]
        assert response.status_code == 400
        assert "1 browser(s) remain active" in response.json()["detail"]
        assert retained.close_attempts == 1
        assert client.get("/browsers").json() == {"active": 2}
        retained.close_error = None
        assert client.delete("/browsers").json() == {"closed": 2}


def test_delete_retries_connected_close_failures_and_ignores_disconnected_errors(
    tmp_path: Path,
) -> None:
    proxy_file = tmp_path / "proxies.txt"
    write_proxies(proxy_file, "one.test:8001", "two.test:8002")
    launcher = FakeLauncher()
    launcher.close_errors = {1: "connected", 2: "disconnected"}

    with TestClient(create_app(proxy_file=proxy_file, launch_browser=launcher)) as client:
        assert client.post("/browsers", json={"windows_per_proxy": 1}).status_code == 200

        response = client.delete("/browsers")

        assert response.status_code == 500
        assert "1 browser" in response.json()["detail"]
        assert [browser.close_attempts for browser in launcher.browsers] == [1, 1]
        assert client.get("/browsers").json() == {"active": 1}
        launcher.browsers[0].close_error = None
        assert client.delete("/browsers").json() == {"closed": 1}


@pytest.mark.asyncio
async def test_shutdown_stops_playwright_and_retains_connected_close_failures(
    monkeypatch,
) -> None:
    import proms.app as app_module

    browser = FakeBrowser(close_error="connected")

    class FakeChromium:
        async def launch(self, **_: object) -> FakeBrowser:
            return browser

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = FakeChromium()
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    runtime = FakePlaywright()

    class FakeStarter:
        async def start(self) -> FakePlaywright:
            return runtime

    monkeypatch.setattr(app_module, "async_playwright", lambda: FakeStarter())
    manager = BrowserManager()
    await manager.launch([{"server": "http://one.test:8001"}], 1)

    with pytest.raises(BrowserCloseError, match="1 browser"):
        await manager.shutdown()

    assert runtime.stopped
    assert manager.active() == 1


@pytest.mark.asyncio
async def test_concurrent_first_launches_start_and_stop_one_playwright_runtime(
    monkeypatch,
) -> None:
    import asyncio

    import proms.app as app_module

    start_entered = asyncio.Event()
    release_start = asyncio.Event()

    class FakeChromium:
        async def launch(self, **_: object) -> FakeBrowser:
            return FakeBrowser()

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = FakeChromium()
            self.stop_calls = 0

        async def stop(self) -> None:
            self.stop_calls += 1

    runtime = FakePlaywright()

    class FakeStarter:
        def __init__(self) -> None:
            self.start_calls = 0

        async def start(self) -> FakePlaywright:
            self.start_calls += 1
            start_entered.set()
            await release_start.wait()
            return runtime

    starter = FakeStarter()
    monkeypatch.setattr(app_module, "async_playwright", lambda: starter)
    manager = BrowserManager()
    first = asyncio.create_task(manager.launch([{"server": "http://one.test:8001"}], 1))
    second = asyncio.create_task(manager.launch([{"server": "http://two.test:8002"}], 1))

    await start_entered.wait()
    for _ in range(3):
        await asyncio.sleep(0)
    release_start.set()
    await asyncio.gather(first, second)
    await manager.shutdown()

    assert starter.start_calls == 1
    assert runtime.stop_calls == 1


def test_malformed_url_proxy_returns_400(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    write_proxies(proxy_file, "http://[bad:80")
    app = create_app(proxy_file=proxy_file, launch_browser=FakeLauncher())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/browsers", json={"windows_per_proxy": 1})

    assert response.status_code == 400
    assert "line 1" in response.json()["detail"]


def test_input_and_proxy_configuration_errors_return_400(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    launcher = FakeLauncher()
    app = create_app(proxy_file=proxy_file, launch_browser=launcher)

    with TestClient(app) as client:
        invalid_input = client.post("/browsers", json={"windows_per_proxy": 0})
        missing_file = client.post("/browsers", json={"windows_per_proxy": 1})
        proxy_file.write_text("bad proxy", encoding="utf-8")
        malformed_file = client.post("/browsers", json={"windows_per_proxy": 1})

    assert invalid_input.status_code == 400
    assert missing_file.status_code == 400
    assert "not found" in missing_file.json()["detail"]
    assert malformed_file.status_code == 400
    assert "line 1" in malformed_file.json()["detail"]
    assert launcher.proxies == []


def test_windows_per_proxy_requires_a_json_integer(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    write_proxies(proxy_file, "one.test:8001")
    app = create_app(proxy_file=proxy_file, launch_browser=FakeLauncher())

    with TestClient(app) as client:
        assert client.post("/browsers", json={"windows_per_proxy": True}).status_code == 400
        assert client.post("/browsers", json={"windows_per_proxy": "2"}).status_code == 400

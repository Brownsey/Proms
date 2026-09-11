import asyncio
from pathlib import Path

import httpx
import pytest
from test_api import FakeLauncher

from proms.app import create_app


@pytest.mark.asyncio
async def test_save_and_configuration_are_safe_while_launch_uses_its_snapshot(
    tmp_path: Path,
) -> None:
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("old.test:8001\n", encoding="utf-8")
    launch_entered = asyncio.Event()
    release_launch = asyncio.Event()
    launcher = FakeLauncher()
    launcher.launch_waits = {1: (launch_entered, release_launch)}
    app = create_app(proxy_file=proxy_file, launch_browser=launcher)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            launching = asyncio.create_task(client.post("/browsers", json={"windows_per_proxy": 1}))
            await launch_entered.wait()
            try:
                saved = await client.post(
                    "/configuration/proxies",
                    json={"proxies": "new-one.test:9001\nnew-two.test:9002\n"},
                )
                configuration = await client.get("/configuration")
            finally:
                release_launch.set()
            launched = await launching

    assert saved.json() == {"count": 2}
    assert configuration.json() == {"proxy_count": 2}
    assert launched.status_code == 200
    assert launcher.proxies == [{"server": "http://old.test:8001"}]
    assert proxy_file.read_text(encoding="utf-8") == "new-one.test:9001\nnew-two.test:9002\n"
    assert not list(tmp_path.glob(".*.tmp"))

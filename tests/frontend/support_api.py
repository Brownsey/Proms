from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from proms.app import create_app


class FakePage:
    async def goto(self, url: str) -> None:
        del url


class FakeBrowser:
    def __init__(self) -> None:
        self.connected = True

    def is_connected(self) -> bool:
        return self.connected

    async def new_page(self) -> FakePage:
        return FakePage()

    async def close(self) -> None:
        self.connected = False


async def launch_browser(proxy: Mapping[str, str]) -> FakeBrowser:
    assert proxy["server"] in {
        "http://initial.test:9000",
        "http://first.test:9001",
        "http://second.test:9002",
    }
    return FakeBrowser()


runtime_directory = TemporaryDirectory(prefix="proms-frontend-test-")
proxy_file = Path(runtime_directory.name) / "proxies.txt"
proxy_file.write_text("initial.test:9000\n", encoding="utf-8")

app = create_app(
    proxy_file=proxy_file,
    launch_browser=launch_browser,
    allowed_origins=["http://127.0.0.1:3000"],
)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8123)

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Protocol, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from playwright.async_api import (
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    ProxySettings as PlaywrightProxySettings,
)
from pydantic import BaseModel, Field

from proms.proxies import ProxyFileError, ProxySettings, load_proxies


class Browser(Protocol):
    def is_connected(self) -> bool: ...

    async def new_page(self) -> object: ...

    async def close(self) -> None: ...


LaunchBrowser = Callable[[Mapping[str, str]], Awaitable[Browser]]


class BrowserLaunchError(RuntimeError):
    """Raised when a requested group of browsers cannot be launched."""


class BrowserCloseError(RuntimeError):
    """Raised when one or more browsers remain connected after cleanup."""


class BrowserManager:
    def __init__(self, launch_browser: LaunchBrowser | None = None) -> None:
        self._launch_override = launch_browser
        self._playwright: Playwright | None = None
        self._playwright_lock = asyncio.Lock()
        self._browsers: list[Browser] = []

    async def _launch(self, proxy: Mapping[str, str]) -> Browser:
        if self._launch_override is not None:
            return await self._launch_override(proxy)
        if self._playwright is None:
            async with self._playwright_lock:
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
        settings = cast(PlaywrightProxySettings, dict(proxy))
        return await self._playwright.chromium.launch(headless=False, proxy=settings)

    async def launch(self, proxies: list[ProxySettings], windows_per_proxy: int) -> int:
        launched: list[Browser] = []
        retained = 0
        try:
            for proxy in proxies:
                for _ in range(windows_per_proxy):
                    browser = await self._launch(proxy)
                    try:
                        await browser.new_page()
                    except Exception:
                        if not await self._close_or_retain(browser):
                            retained += 1
                        raise
                    launched.append(browser)
        except Exception as error:
            for browser in launched:
                if not await self._close_or_retain(browser):
                    retained += 1
            cleanup = f"; cleanup failed: {retained} browser(s) remain active" if retained else ""
            raise BrowserLaunchError(f"Unable to launch browsers: {error}{cleanup}") from error
        self._browsers.extend(launched)
        return len(launched)

    async def _close_or_retain(self, browser: Browser) -> bool:
        with suppress(Exception):
            await browser.close()
        if browser.is_connected():
            self._browsers.append(browser)
            return False
        return True

    def active(self) -> int:
        self._browsers = [browser for browser in self._browsers if browser.is_connected()]
        return len(self._browsers)

    async def close_all(self) -> int:
        browsers, self._browsers = self._browsers, []
        closed = 0
        for browser in browsers:
            was_connected = browser.is_connected()
            if await self._close_or_retain(browser) and was_connected:
                closed += 1
        if self._browsers:
            remaining = len(self._browsers)
            raise BrowserCloseError(
                f"Unable to close {remaining} browser(s); {remaining} remain active"
            )
        return closed

    async def shutdown(self) -> None:
        try:
            await self.close_all()
        finally:
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None


class LaunchRequest(BaseModel):
    windows_per_proxy: int = Field(ge=1, strict=True)


def create_app(
    *, proxy_file: Path = Path("proxies.txt"), launch_browser: LaunchBrowser | None = None
) -> FastAPI:
    manager = BrowserManager(launch_browser)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            await manager.shutdown()

    application = FastAPI(lifespan=lifespan)

    @application.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": error.errors()})

    @application.post("/browsers")
    async def launch_browsers(request: LaunchRequest) -> dict[str, int]:
        try:
            proxies = load_proxies(proxy_file)
            launched = await manager.launch(proxies, request.windows_per_proxy)
        except (ProxyFileError, BrowserLaunchError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"launched": launched, "active": manager.active()}

    @application.get("/browsers")
    async def active_browsers() -> dict[str, int]:
        return {"active": manager.active()}

    @application.delete("/browsers")
    async def close_browsers() -> dict[str, int]:
        try:
            closed = await manager.close_all()
        except BrowserCloseError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        return {"closed": closed}

    return application


app = create_app()

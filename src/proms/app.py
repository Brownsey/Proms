import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from typing import Protocol, Self, cast
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from playwright.async_api import (
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    ProxySettings as PlaywrightProxySettings,
)
from pydantic import BaseModel, Field, field_validator, model_validator

from proms.proxies import ProxyFileError, ProxySettings, load_proxies


class Page(Protocol):
    async def goto(self, url: str) -> object: ...

    async def text_content(self, selector: str) -> str | None: ...


class Browser(Protocol):
    def is_connected(self) -> bool: ...

    async def new_page(self) -> Page: ...

    async def close(self) -> None: ...


LaunchBrowser = Callable[[Mapping[str, str]], Awaitable[Browser]]


class BrowserLaunchError(RuntimeError):
    """Raised when a requested group of browsers cannot be launched."""


class BrowserCloseError(RuntimeError):
    """Raised when one or more browsers remain connected after cleanup."""


@dataclass
class BrowserRecord:
    browser: Browser
    rotating: bool = False
    rotating_ip: str | None = None


class BrowserManager:
    def __init__(self, launch_browser: LaunchBrowser | None = None) -> None:
        self._launch_override = launch_browser
        self._playwright: Playwright | None = None
        self._playwright_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._browsers: list[BrowserRecord] = []

    async def _launch(self, proxy: Mapping[str, str]) -> Browser:
        if self._launch_override is not None:
            return await self._launch_override(proxy)
        if self._playwright is None:
            async with self._playwright_lock:
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
        settings = cast(PlaywrightProxySettings, dict(proxy))
        return await self._playwright.chromium.launch(headless=False, proxy=settings)

    async def launch(
        self,
        proxies: list[ProxySettings],
        windows_per_proxy: int,
        *,
        url: str = "about:blank",
        rotating_proxies: list[ProxySettings] | None = None,
        rotating_windows_per_proxy: int = 0,
        rotation_attempts: int = 5,
        ip_check_url: str = "https://api64.ipify.org",
    ) -> int:
        async with self._operation_lock:
            return await self._launch_transaction(
                proxies,
                windows_per_proxy,
                url=url,
                rotating_proxies=rotating_proxies,
                rotating_windows_per_proxy=rotating_windows_per_proxy,
                rotation_attempts=rotation_attempts,
                ip_check_url=ip_check_url,
            )

    async def _launch_transaction(
        self,
        proxies: list[ProxySettings],
        windows_per_proxy: int,
        *,
        url: str,
        rotating_proxies: list[ProxySettings] | None,
        rotating_windows_per_proxy: int,
        rotation_attempts: int,
        ip_check_url: str,
    ) -> int:
        owned: list[BrowserRecord] = []
        retained = 0
        try:
            if rotating_proxies:
                self.active()
                unknown_ips = sum(
                    record.rotating and record.rotating_ip is None for record in self._browsers
                )
                if unknown_ips:
                    raise RuntimeError(
                        f"Cannot launch rotating browsers: {unknown_ips} active rotating "
                        "browser(s) have an unknown IP; DELETE /browsers to retry cleanup"
                    )

            for proxy in proxies:
                for _ in range(windows_per_proxy):
                    browser = await self._launch(proxy)
                    record = BrowserRecord(browser)
                    owned.append(record)
                    page = await browser.new_page()
                    if url != "about:blank":
                        await page.goto(url)

            if rotating_proxies:
                self.active()
                used_ips = {
                    record.rotating_ip
                    for record in self._browsers
                    if record.rotating_ip is not None
                }
                for proxy in rotating_proxies:
                    for _ in range(rotating_windows_per_proxy):
                        last_error = "IP check failed"
                        for _ in range(rotation_attempts):
                            browser = await self._launch(proxy)
                            record = BrowserRecord(browser, rotating=True)
                            owned.append(record)
                            page = await browser.new_page()
                            try:
                                await page.goto(ip_check_url)
                                body = await page.text_content("body")
                                observed_ip = str(ip_address((body or "").strip()))
                                record.rotating_ip = observed_ip
                                if observed_ip in used_ips:
                                    raise ValueError(f"duplicate IP: {observed_ip}")
                            except Exception as error:
                                last_error = str(error)
                                _, rejected_retained = await self._cleanup_owned([record], owned)
                                retained += rejected_retained
                                if rejected_retained:
                                    raise RuntimeError(
                                        "Unable to close rejected rotating browser"
                                    ) from error
                                continue
                            await page.goto(url)
                            used_ips.add(observed_ip)
                            break
                        else:
                            raise RuntimeError(
                                "Unable to obtain a unique IP after "
                                f"{rotation_attempts} attempts: {last_error}"
                            )

            launched = len(owned)
            self._browsers.extend(owned)
            owned.clear()
            return launched
        except BaseException as error:
            _, rollback_retained = await self._cleanup_owned(list(owned), owned)
            retained += rollback_retained
            if not isinstance(error, Exception):
                raise
            cleanup = f"; cleanup failed: {retained} browser(s) remain active" if retained else ""
            raise BrowserLaunchError(f"Unable to launch browsers: {error}{cleanup}") from error

    async def _cleanup_owned(
        self, records: list[BrowserRecord], owned: list[BrowserRecord]
    ) -> tuple[int, int]:
        cleanup = asyncio.create_task(self._settle_records(records, owned))
        cancellation: asyncio.CancelledError | None = None
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError as error:
                cancellation = error
        result = cleanup.result()
        if cancellation is not None:
            raise cancellation
        return result

    async def _settle_records(
        self, records: list[BrowserRecord], owned: list[BrowserRecord]
    ) -> tuple[int, int]:
        closed = 0
        retained = 0
        cancellation: asyncio.CancelledError | None = None
        for record in records:
            try:
                was_connected = record.browser.is_connected()
            except asyncio.CancelledError as error:
                cancellation = error
                was_connected = True
            except BaseException:
                was_connected = True
            try:
                await record.browser.close()
            except asyncio.CancelledError as error:
                cancellation = error
            except BaseException:
                pass
            try:
                connected = record.browser.is_connected()
            except asyncio.CancelledError as error:
                cancellation = error
                connected = True
            except BaseException:
                connected = True
            if connected:
                self._browsers.append(record)
                retained += 1
            elif was_connected:
                closed += 1
            owned.remove(record)
        if cancellation is not None:
            raise cancellation
        return closed, retained

    def active(self) -> int:
        self._browsers = [record for record in self._browsers if record.browser.is_connected()]
        return len(self._browsers)

    async def close_all(self) -> int:
        async with self._operation_lock:
            return await self._close_all()

    async def _close_all(self) -> int:
        owned, self._browsers = self._browsers, []
        closed, retained = await self._cleanup_owned(list(owned), owned)
        if retained:
            raise BrowserCloseError(
                f"Unable to close {retained} browser(s); {retained} remain active"
            )
        return closed

    async def shutdown(self) -> None:
        async with self._operation_lock:
            try:
                await self._close_all()
            finally:
                if self._playwright is not None:
                    await self._playwright.stop()
                    self._playwright = None


class LaunchRequest(BaseModel):
    windows_per_proxy: int | None = Field(default=None, ge=1, strict=True)
    static_windows_per_proxy: int = Field(default=0, ge=0, strict=True)
    rotating_windows_per_proxy: int = Field(default=0, ge=0, strict=True)
    url: str = Field(default="about:blank", strict=True)
    rotation_attempts: int = Field(default=5, ge=1, le=20, strict=True)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if value == "about:blank":
            return value
        try:
            parsed = urlsplit(value)
            host = parsed.hostname
            _ = parsed.port
        except ValueError as error:
            raise ValueError("url must be an absolute HTTP(S) URL or about:blank") from error
        if (
            parsed.scheme not in {"http", "https"}
            or host is None
            or any(character.isspace() for character in value)
        ):
            raise ValueError("url must be an absolute HTTP(S) URL or about:blank")
        return value

    @model_validator(mode="after")
    def validate_launch_mode(self) -> Self:
        new_fields = {"static_windows_per_proxy", "rotating_windows_per_proxy"}
        if self.windows_per_proxy is not None:
            if self.model_fields_set & new_fields:
                raise ValueError("windows_per_proxy cannot be combined with new window counts")
        elif self.static_windows_per_proxy == 0 and self.rotating_windows_per_proxy == 0:
            raise ValueError("at least one window count must be greater than zero")
        return self


def create_app(
    *,
    proxy_file: Path = Path("proxies.txt"),
    rotating_proxy_file: Path = Path("rotating_proxies.txt"),
    ip_check_url: str = "https://api64.ipify.org",
    launch_browser: LaunchBrowser | None = None,
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
        return JSONResponse(status_code=400, content={"detail": jsonable_encoder(error.errors())})

    @application.post("/browsers")
    async def launch_browsers(request: LaunchRequest) -> dict[str, int]:
        try:
            static_count = request.windows_per_proxy or request.static_windows_per_proxy
            static_proxies = load_proxies(proxy_file) if static_count else []
            rotating_proxies = (
                load_proxies(rotating_proxy_file) if request.rotating_windows_per_proxy else []
            )
            launched = await manager.launch(
                static_proxies,
                static_count,
                url=request.url,
                rotating_proxies=rotating_proxies,
                rotating_windows_per_proxy=request.rotating_windows_per_proxy,
                rotation_attempts=request.rotation_attempts,
                ip_check_url=ip_check_url,
            )
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

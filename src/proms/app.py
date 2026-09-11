import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from playwright.async_api import (
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    ProxySettings as PlaywrightProxySettings,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

from proms.proxies import (
    ProxyFileError,
    ProxySettings,
    count_configured_proxies,
    load_proxies,
    parse_proxy_text,
    replace_proxy_file,
)

DEFAULT_ALLOWED_ORIGINS = {
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
}
MAX_PROXY_REQUEST_BYTES = 1024 * 1024
DEFAULT_TARGET_URL = "https://whatismyipaddress.com/"


def _is_http_loopback_origin(origin: str) -> bool:
    if not origin or origin != origin.strip() or any(character.isspace() for character in origin):
        return False
    try:
        parsed = urlsplit(origin)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "http"
        or host is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.netloc.endswith(":")
        or port == 0
    ):
        return False
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


class Page(Protocol):
    async def goto(self, url: str) -> object: ...


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
        max_windows: int | None = None,
    ) -> int:
        async with self._operation_lock:
            return await self._launch_transaction(
                proxies,
                windows_per_proxy,
                url=url,
                max_windows=max_windows,
            )

    async def _launch_transaction(
        self,
        proxies: list[ProxySettings],
        windows_per_proxy: int,
        *,
        url: str,
        max_windows: int | None,
    ) -> int:
        owned: list[BrowserRecord] = []
        retained = 0
        try:
            for _ in range(windows_per_proxy):
                for proxy in proxies:
                    if max_windows is not None and len(owned) >= max_windows:
                        break
                    browser = await self._launch(proxy)
                    record = BrowserRecord(browser)
                    owned.append(record)
                    page = await browser.new_page()
                    if url != "about:blank":
                        await page.goto(url)
                if max_windows is not None and len(owned) >= max_windows:
                    break

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
    model_config = ConfigDict(extra="forbid")

    windows_per_proxy: int = Field(default=1, ge=1, strict=True)
    max_windows: int | None = Field(default=None, ge=1, strict=True)
    url: str = Field(default=DEFAULT_TARGET_URL, strict=True)

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


def create_app(
    *,
    proxy_file: Path = Path("proxies.txt"),
    launch_browser: LaunchBrowser | None = None,
    allowed_origins: Iterable[str] | None = None,
    ui_build_path: Path = Path(".next"),
) -> FastAPI:
    manager = BrowserManager(launch_browser)
    proxy_file_lock = asyncio.Lock()
    origin_allowlist = set(DEFAULT_ALLOWED_ORIGINS)
    origin_allowlist.update(
        origin.strip()
        for origin in os.getenv("PROMS_ALLOWED_ORIGINS", "").split(",")
        if _is_http_loopback_origin(origin.strip())
    )
    if allowed_origins is not None:
        origin_allowlist.update(
            origin.strip() for origin in allowed_origins if _is_http_loopback_origin(origin.strip())
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            await manager.shutdown()

    application = FastAPI(lifespan=lifespan)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(origin_allowlist),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
        allow_private_network=True,
    )

    @application.middleware("http")
    async def reject_untrusted_browser_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in origin_allowlist:
            return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
        return await call_next(request)

    application.mount(
        "/_next/static",
        StaticFiles(directory=ui_build_path / "static", check_dir=False),
        name="next-static",
    )

    @application.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": jsonable_encoder(error.errors())})

    @application.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/control/")

    @application.get("/control/", include_in_schema=False)
    async def control_panel() -> FileResponse:
        control_html = ui_build_path / "server" / "app" / "control.html"
        if not control_html.is_file():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Local control panel is not built. Run scripts/setup.ps1 on Windows or "
                    "scripts/setup.sh on macOS, then restart uv run --locked proms."
                ),
            )
        return FileResponse(control_html, media_type="text/html")

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/configuration")
    async def configuration() -> dict[str, int]:
        try:
            async with proxy_file_lock:
                return {"proxy_count": count_configured_proxies(proxy_file)}
        except ProxyFileError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/configuration/proxies")
    async def save_proxy_configuration(request: Request) -> dict[str, str | int]:
        content_length = request.headers.get("content-length")
        try:
            if content_length is not None and int(content_length) > MAX_PROXY_REQUEST_BYTES:
                raise HTTPException(status_code=400, detail="Request body is too large")
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Malformed request body") from error

        body = bytearray()
        try:
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_PROXY_REQUEST_BYTES:
                    raise HTTPException(status_code=400, detail="Request body is too large")
            payload = json.loads(body)
        except HTTPException:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=400, detail="Malformed JSON request") from error

        allowed_fields = {"proxies", "confirm_clear"}
        if (
            type(payload) is not dict
            or "proxies" not in payload
            or not set(payload).issubset(allowed_fields)
        ):
            raise HTTPException(
                status_code=400,
                detail="Request must contain proxies and optional confirm_clear only",
            )

        contents = payload["proxies"]
        confirm_clear = payload.get("confirm_clear", False)
        if type(contents) is not str:
            raise HTTPException(status_code=400, detail="proxies must be a string")
        if type(confirm_clear) is not bool:
            raise HTTPException(status_code=400, detail="confirm_clear must be a boolean")

        try:
            proxies = parse_proxy_text(contents)
        except ProxyFileError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if not proxies and not confirm_clear:
            raise HTTPException(
                status_code=400,
                detail="confirm_clear must be true to save an empty proxy list",
            )

        try:
            async with proxy_file_lock:
                replace_proxy_file(proxy_file, contents)
        except (OSError, UnicodeError) as error:
            raise HTTPException(
                status_code=400,
                detail="Unable to save proxy configuration",
            ) from error
        return {"count": len(proxies)}

    @application.post("/browsers")
    async def launch_browsers(request: LaunchRequest) -> dict[str, int]:
        try:
            async with proxy_file_lock:
                proxies = load_proxies(proxy_file)
            launched = await manager.launch(
                proxies,
                request.windows_per_proxy,
                url=request.url,
                max_windows=request.max_windows,
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

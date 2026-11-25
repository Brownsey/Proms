import asyncio
import json
import os
from collections.abc import Iterable, Sequence
from contextlib import asynccontextmanager
from ipaddress import ip_address
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from proms.browsers import BrowserCloseError, BrowserLaunchError, BrowserManager, LaunchBrowser
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


class LaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    windows_per_proxy: int = Field(default=1, ge=1, strict=True)
    max_windows: int | None = Field(default=None, ge=1, strict=True)
    direct_windows: int | None = Field(default=None, ge=1, strict=True)
    url: str = Field(default=DEFAULT_TARGET_URL, strict=True)
    chrome_profiles: bool = Field(default=False, strict=True)

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
    def validate_connection_mode(self) -> Self:
        if self.direct_windows is not None and self.model_fields_set & {
            "windows_per_proxy",
            "max_windows",
        }:
            raise ValueError(
                "direct_windows cannot be combined with windows_per_proxy or max_windows"
            )
        return self


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
        detail = []
        for issue in error.errors():
            location = issue["loc"]
            field = location[1] if len(location) > 1 else None
            detail.append(
                {
                    "loc": ["body", field] if field in LaunchRequest.model_fields else ["body"],
                    "msg": issue["msg"],
                    "type": issue["type"],
                }
            )
        return JSONResponse(status_code=400, content={"detail": detail})

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
                if len(body) + len(chunk) > MAX_PROXY_REQUEST_BYTES:
                    raise HTTPException(status_code=400, detail="Request body is too large")
                body.extend(chunk)
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
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
            connections: Sequence[ProxySettings | None]
            if request.direct_windows is not None:
                connections = (None,)
                window_count = request.direct_windows
            else:
                async with proxy_file_lock:
                    connections = load_proxies(proxy_file)
                window_count = request.windows_per_proxy
            launched = await manager.launch(
                connections,
                window_count,
                url=request.url,
                max_windows=request.max_windows,
                chrome_profiles=request.chrome_profiles,
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
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"], www_redirect=False
)

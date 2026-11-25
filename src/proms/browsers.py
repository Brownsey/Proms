import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, cast

from playwright.async_api import BrowserContext, Playwright, async_playwright
from playwright.async_api import ProxySettings as PlaywrightProxySettings

from proms.proxies import ProxySettings


class Page(Protocol):
    async def goto(self, url: str) -> object: ...


class Browser(Protocol):
    def is_connected(self) -> bool: ...

    async def new_page(self) -> Page: ...

    async def close(self) -> None: ...


class ChromeProfile:
    def __init__(self, context: BrowserContext) -> None:
        self._context = context
        self._closed = False
        context.on("close", self._on_close)

    def _on_close(self, _: BrowserContext) -> None:
        self._closed = True

    def is_connected(self) -> bool:
        return not self._closed

    async def new_page(self) -> Page:
        # A regular Chrome window starts with a tab already open.
        pages = self._context.pages
        return pages[0] if pages else await self._context.new_page()

    async def close(self) -> None:
        await self._context.close()


type LaunchBrowser = Callable[[ProxySettings | None], Awaitable[Browser]]


class BrowserLaunchError(RuntimeError):
    """Raised when a requested group of browsers cannot be launched."""


class BrowserCloseError(RuntimeError):
    """Raised when one or more browsers remain connected after cleanup."""


async def _finish_task[T](task: asyncio.Task[T]) -> T:
    """Let a task finish updating ownership before propagating cancellation."""
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            cancellation = error
    result = task.result()
    if cancellation is not None:
        raise cancellation
    return result


def _is_connected(browser: Browser) -> bool:
    try:
        return browser.is_connected()
    except Exception:
        # Keep track of a browser whose connection could not be checked.
        return True


async def _settle_browsers(browsers: list[Browser]) -> int:
    closed = 0
    remaining: list[Browser] = []
    cancellation: asyncio.CancelledError | None = None
    for browser in browsers:
        was_connected = _is_connected(browser)
        try:
            await browser.close()
        except asyncio.CancelledError as error:
            cancellation = error
        except Exception:
            # The connection state determines whether a retry is needed.
            pass
        if _is_connected(browser):
            remaining.append(browser)
        elif was_connected:
            closed += 1
    browsers[:] = remaining
    if cancellation is not None:
        raise cancellation
    return closed


class BrowserManager:
    def __init__(self, launch_browser: LaunchBrowser | None = None) -> None:
        self._launch_override = launch_browser
        self._playwright: Playwright | None = None
        self._operation_lock = asyncio.Lock()
        self._browsers: list[Browser] = []

    async def _launch_owned(
        self, proxy: ProxySettings | None, *, chrome_profiles: bool, owned: list[Browser]
    ) -> Browser:
        if self._launch_override is not None:
            browser = await self._launch_override(proxy)
        else:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            settings = cast(PlaywrightProxySettings, proxy.copy()) if proxy is not None else None
            args = ["--no-proxy-server"] if proxy is None else None
            if chrome_profiles:
                context = await self._playwright.chromium.launch_persistent_context(
                    "", channel="chrome", headless=False, proxy=settings, args=args
                )
                browser = ChromeProfile(context)
            else:
                browser = await self._playwright.chromium.launch(
                    headless=False, proxy=settings, args=args
                )
        owned.append(browser)
        return browser

    async def launch(
        self,
        connections: Sequence[ProxySettings | None],
        windows_per_connection: int,
        *,
        url: str = "about:blank",
        max_windows: int | None = None,
        chrome_profiles: bool = False,
    ) -> int:
        async with self._operation_lock:
            if not connections or (max_windows is not None and max_windows <= 0):
                return 0
            self._browsers[:] = [browser for browser in self._browsers if _is_connected(browser)]
            owned: list[Browser] = []
            step = "start a browser"
            try:
                for _ in range(windows_per_connection):
                    for proxy in connections:
                        step = "start a browser"
                        launch = self._launch_owned(
                            proxy, chrome_profiles=chrome_profiles, owned=owned
                        )
                        if self._launch_override is None:
                            # Playwright can open the browser after request cancellation.
                            browser = await _finish_task(asyncio.create_task(launch))
                        else:
                            browser = await launch
                        step = "open a browser page"
                        page = await browser.new_page()
                        if url != "about:blank":
                            step = "load the target URL"
                            await page.goto(url)
                        if len(owned) == max_windows:
                            break
                    if len(owned) == max_windows:
                        break
            except BaseException as error:
                try:
                    await _finish_task(asyncio.create_task(_settle_browsers(owned)))
                finally:
                    self._browsers.extend(owned)
                if not isinstance(error, Exception):
                    raise
                # Playwright errors may contain navigation URLs and proxy diagnostics.
                detail = f"Unable to {step}."
                if step == "start a browser" and chrome_profiles:
                    detail += " Check that Google Chrome is installed."
                if owned:
                    detail += f" {len(owned)} browser(s) remain active after cleanup."
                raise BrowserLaunchError(detail) from error

            self._browsers.extend(owned)
            return len(owned)

    def active(self) -> int:
        return sum(_is_connected(browser) for browser in self._browsers)

    async def close_all(self) -> int:
        async with self._operation_lock:
            return await self._close_all()

    async def _close_all(self) -> int:
        closed = await _finish_task(asyncio.create_task(_settle_browsers(self._browsers)))
        if self._browsers:
            remaining = len(self._browsers)
            raise BrowserCloseError(
                f"Unable to close {remaining} browser(s); {remaining} remain active"
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

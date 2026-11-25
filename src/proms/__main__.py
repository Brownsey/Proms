import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

import uvicorn

HOST = "127.0.0.1"
PORT = 8000
BROWSERS_URL = f"http://{HOST}:{PORT}/browsers"


def _positive_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("enter a positive whole number") from error
    if count < 1:
        raise argparse.ArgumentTypeError("enter a positive whole number")
    return count


def _request(method: str, payload: dict[str, object] | None = None) -> dict[str, int]:
    request = Request(
        BROWSERS_URL,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json"} if payload is not None else {},
        method=method,
    )
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request) as response:
            return json.load(response)
    except HTTPError as error:
        with error:
            try:
                detail = json.load(error).get("detail")
            except (ValueError, AttributeError):
                detail = None
        if isinstance(detail, str):
            raise SystemExit(detail) from None
        if isinstance(detail, list):
            messages = [
                item["msg"]
                for item in detail
                if isinstance(item, dict) and isinstance(item.get("msg"), str)
            ]
            if messages:
                raise SystemExit("\n".join(messages)) from None
        raise SystemExit(f"Proms returned HTTP {error.code}.") from None
    except URLError:
        raise SystemExit(
            "Could not reach Proms. Start it in another terminal with 'uv run --locked proms'."
        ) from None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="proms", description="Run or control the local browser launcher."
    )
    commands = parser.add_subparsers(dest="command")
    launch = commands.add_parser("launch", help="Open windows through the running local service")
    connection = launch.add_mutually_exclusive_group()
    connection.add_argument(
        "--direct", type=_positive_count, metavar="COUNT", help="Open COUNT windows without a proxy"
    )
    connection.add_argument(
        "--windows-per-proxy",
        type=_positive_count,
        metavar="COUNT",
        help="Open COUNT windows per saved proxy (default: 1)",
    )
    launch.add_argument(
        "--max-windows", type=_positive_count, help="Cap the total number of proxied windows"
    )
    launch.add_argument(
        "--chrome",
        action="store_true",
        help="Use installed Google Chrome with a fresh temporary profile per window",
    )
    launch.add_argument("--url", help="Open this HTTP(S) URL or about:blank")
    commands.add_parser("status", help="Show how many windows are active")
    commands.add_parser("close", help="Close all windows opened by Proms")
    args = parser.parse_args(argv)

    match args.command:
        case "launch":
            if args.direct is not None and args.max_windows is not None:
                launch.error("--max-windows applies to proxy launches")
            payload = {
                key: value
                for key, value in {
                    "direct_windows": args.direct,
                    "windows_per_proxy": args.windows_per_proxy,
                    "max_windows": args.max_windows,
                    "chrome_profiles": args.chrome or None,
                    "url": args.url,
                }.items()
                if value is not None
            }
            result = _request("POST", payload)
            print(f"Launched {result['launched']} windows. {result['active']} active.")
        case "status":
            print(f"{_request('GET')['active']} active windows.")
        case "close":
            print(f"Closed {_request('DELETE')['closed']} windows.")
        case _:
            uvicorn.run("proms.app:app", host=HOST, port=PORT)


if __name__ == "__main__":
    main()

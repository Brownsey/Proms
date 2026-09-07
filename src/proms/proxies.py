from pathlib import Path
from urllib.parse import unquote, urlsplit

ProxySettings = dict[str, str]
SUPPORTED_SCHEMES = {"http", "https", "socks4", "socks5"}


class ProxyFileError(ValueError):
    """Raised when proxies.txt cannot supply valid proxies."""


def _port(value: str, line_number: int) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise ProxyFileError(
            f"Invalid proxy on line {line_number}: port must be a number"
        ) from error
    if not 1 <= port <= 65535:
        raise ProxyFileError(f"Invalid proxy on line {line_number}: port must be 1-65535")
    return port


def _host(value: str, line_number: int) -> str:
    if (
        not value
        or any(character.isspace() for character in value)
        or any(character in value for character in "/@")
    ):
        raise ProxyFileError(f"Invalid proxy on line {line_number}: host is malformed")
    return value


def _parse_proxy(value: str, line_number: int) -> ProxySettings:
    if "://" in value:
        try:
            parsed = urlsplit(value)
            host = parsed.hostname
            port = parsed.port
            username = parsed.username
            password = parsed.password
        except ValueError as error:
            raise ProxyFileError(
                f"Invalid proxy on line {line_number}: malformed URL ({error})"
            ) from error
        if parsed.scheme not in SUPPORTED_SCHEMES:
            raise ProxyFileError(f"Invalid proxy on line {line_number}: unsupported scheme")
        if parsed.path or parsed.query or parsed.fragment or host is None:
            raise ProxyFileError(f"Invalid proxy on line {line_number}: malformed URL")
        if port is None:
            raise ProxyFileError(f"Invalid proxy on line {line_number}: port is required")
        _port(str(port), line_number)
        host = _host(host, line_number)
        server_host = f"[{host}]" if ":" in host else host
        settings = {"server": f"{parsed.scheme}://{server_host}:{port}"}
        if "@" in parsed.netloc and (not username or not password):
            raise ProxyFileError(
                f"Invalid proxy on line {line_number}: both username and password are required"
            )
        if username and password:
            settings.update(username=unquote(username), password=unquote(password))
        return settings

    parts = value.split(":")
    if len(parts) not in {2, 4}:
        raise ProxyFileError(
            f"Invalid proxy on line {line_number}: expected host:port or host:port:user:pass"
        )
    host, port_value = parts[:2]
    port = _port(port_value, line_number)
    settings = {"server": f"http://{_host(host, line_number)}:{port}"}
    if len(parts) == 4:
        username, password = parts[2:]
        if not username or not password:
            raise ProxyFileError(
                f"Invalid proxy on line {line_number}: username and password cannot be empty"
            )
        settings.update(username=username, password=password)
    return settings


def _load_proxies(path: Path, *, optional: bool) -> list[ProxySettings]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as error:
        if optional:
            return []
        raise ProxyFileError(f"Proxy file not found: {path}") from error
    except OSError as error:
        raise ProxyFileError(f"Unable to read proxy file {path}: {error}") from error

    proxies = [
        _parse_proxy(line.strip(), line_number)
        for line_number, line in enumerate(lines, start=1)
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not proxies and not optional:
        raise ProxyFileError(f"Proxy file contains no proxies: {path}")
    return proxies


def load_proxies(path: Path) -> list[ProxySettings]:
    return _load_proxies(path, optional=False)


def count_configured_proxies(path: Path) -> int:
    return len(_load_proxies(path, optional=True))

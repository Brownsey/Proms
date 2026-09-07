# Proms

Local backend for opening interactive Chromium windows through private proxies.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync --locked
uv run playwright install chromium
```

Create `proxies.txt` in the repository root with one proxy per line. Blank lines
and lines beginning with `#` are ignored. Supported formats:

```text
host:port
http://host:port
http://username:password@host:port
host:port:username:password
socks5://host:port
```

`proxies.txt` is git-ignored because it may contain credentials.

## Run

```powershell
uv run proms
```

The API listens on `http://127.0.0.1:8000` so it is not exposed to other
machines by default.

Launch two browser windows per proxy:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/browsers `
  -ContentType 'application/json' `
  -Body '{"windows_per_proxy":2}'
```

Check or close active windows:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/browsers
Invoke-RestMethod -Method Delete http://127.0.0.1:8000/browsers
```

Browsers stay open while the backend runs. Stopping the backend closes every
browser it launched.

## Verify

```powershell
uv run --locked verify
```

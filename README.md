# Proms

Local backend for opening interactive Chromium windows through private proxies.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync --locked
uv run playwright install chromium
```

Create `proxies.txt` for static proxies and `rotating_proxies.txt` for rotating
proxy gateways. Each file uses one proxy per line. Blank lines and lines
beginning with `#` are ignored. Supported formats:

```text
host:port
http://host:port
http://username:password@host:port
host:port:username:password
socks5://host:port
```

Both proxy files are git-ignored because they may contain credentials.

## Run

```powershell
uv run proms
```

The API listens on `http://127.0.0.1:8000` so it is not exposed to other
machines by default.

Launch two browser windows per static proxy (legacy request):

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/browsers `
  -ContentType 'application/json' `
  -Body '{"windows_per_proxy":2}'
```

Launch a mixture with different counts and make every accepted window load the
same URL:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/browsers `
  -ContentType 'application/json' `
  -Body '{
    "static_windows_per_proxy": 2,
    "rotating_windows_per_proxy": 4,
    "url": "https://example.com",
    "rotation_attempts": 5
  }'
```

Counts apply to each proxy line. A list is optional when its count is `0`.

Before loading `url`, each rotating window checks its public address through
[`api64.ipify.org`](https://www.ipify.org/). Duplicate addresses are closed and
tried up to `rotation_attempts` times; if uniqueness cannot be achieved, the
whole request is rolled back. Previously active rotating windows are included
in the uniqueness check.

The rotating provider must assign a fresh IP to a fresh browser connection and
keep that IP sticky for the browser session. Providers that rotate every HTTP
request can only guarantee uniqueness at check time unless their session-token
format is configured in each proxy credential.

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

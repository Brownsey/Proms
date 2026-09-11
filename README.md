# Proms

A local browser launcher and control panel. The backend opens interactive Chromium windows through static and rotating proxies. All controls, including unsaved proxy drafts, stay on this computer. The hosted website contains installation guidance only.

## Setup

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node.js 20.9+.

### Agent-assisted Windows setup

An automation agent can read [`AGENTS.md`](AGENTS.md) and install the required tooling and dependencies with one idempotent command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
```

The script installs missing `uv` and Node.js LTS through Windows Package Manager, restores both lockfiles, installs Playwright Chromium, builds the local control panel, and creates empty ignored proxy files when absent. It preserves existing proxy files and never reads or prints their values. Windows may still require approval for an installer.

Agents can optionally check the machine prerequisites without installing anything:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -CheckOnly
```

Check mode does not replace the full setup command. Agents must never read proxy credentials. After startup, agents can use only the numeric counts from `GET /configuration` to determine whether proxies are configured; users can add or replace proxy lists through the local control panel.

### Manual setup

```powershell
uv sync --locked
npm ci
uv run playwright install chromium
npm run build
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

## Run the local service

```powershell
uv run proms
```

The API listens on `http://127.0.0.1:8000` so it is not exposed to other
machines by default.

## Use the control panel

Open [http://127.0.0.1:8000/control/](http://127.0.0.1:8000/control/). Use **Local proxy files** to save static or rotating proxy lists on this computer. Drafts, saved values, and control requests never pass through Vercel. Existing values are never displayed; only counts are returned. Saving replaces only the selected ignored local file.

[proms-rust.vercel.app](https://proms-rust.vercel.app) is an installer and documentation page. It cannot read or control the local service.

Additional trusted loopback development origins can be supplied as a comma-separated list in `PROMS_ALLOWED_ORIGINS`. Non-loopback browser origins remain blocked and cannot read status, save proxies, launch windows, or close windows.

The service also exposes `GET /health` and a secret-safe `GET /configuration` summary.

## API examples

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
npm run verify
```

Backend-only checks remain available as `uv run --locked verify`; frontend-only checks use `npm run verify:frontend`.

# Proms

A local browser launcher and control panel. The backend opens interactive Chromium windows through fixed proxies or sticky-session proxy credentials. All controls, including unsaved proxy drafts, stay on this computer. The hosted website contains installation guidance only.

## Setup

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node.js 20.9+.

### Agent-assisted Windows setup

An automation agent can read [`AGENTS.md`](AGENTS.md) and install the required tooling and dependencies with one idempotent command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
```

The script installs missing `uv` and Node.js LTS through Windows Package Manager, restores both lockfiles, installs both required Playwright Chromium revisions, builds the local control panel, and creates an empty ignored `proxies.txt` when absent. It preserves an existing file and never reads or prints its values. Windows may still require approval for an installer.

Agents can optionally check the machine prerequisites without installing anything:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -CheckOnly
```

Check mode does not replace the full setup command. Agents must never read proxy credentials. After startup, agents can use only the numeric count from `GET /configuration` to determine whether proxies are configured; users can add or replace the proxy list through the local control panel.

### Agent-assisted macOS setup (currently untested)

macOS support currently requires macOS 14 Sonoma or newer, Homebrew when tools need installing, and a logged-in GUI session so Chromium windows can open. Run from any directory inside or outside the checkout:

```bash
bash /path/to/Proms/scripts/setup.sh
```

The script finds the repository root, installs missing `uv` and Node.js 24 LTS through Homebrew, restores locked dependencies, installs both Playwright Chromium revisions, builds the local control panel, and creates a missing ignored `proxies.txt` without reading or replacing existing values.

Optional prerequisite check:

```bash
bash /path/to/Proms/scripts/setup.sh --check-only
```

This macOS path is currently untested on macOS hardware.

### Manual setup

```powershell
uv sync --locked
npm ci
npx playwright install chromium
uv run --locked playwright install chromium
npm run build
```

Create `proxies.txt` for fixed proxies or sticky-session proxy credentials. The file uses one proxy per line. Blank lines and lines
beginning with `#` are ignored. Supported formats:

```text
host:port
http://host:port
http://username:password@host:port
username:password@host:port
host:port:username:password
socks5://host:port
```

For backward compatibility, four-part values with a numeric second segment use `host:port:username:password`. A colon-containing password in `username:password@host:port` must use an explicit `http://` prefix.

The proxy file is git-ignored because it may contain credentials.

## Run the local service

```powershell
uv run --locked proms
```

The API listens on `http://127.0.0.1:8000` so it is not exposed to other
machines by default.

## Use the control panel

Open [http://127.0.0.1:8000/control/](http://127.0.0.1:8000/control/). Use **Local proxy file** to save the list on this computer. Drafts, saved values, and control requests never pass through Vercel. Existing values are never displayed; only the count is returned. Saving replaces the ignored local file.

[proms.brownsey.co.uk](https://proms.brownsey.co.uk) is an installer and documentation page. It cannot read or control the local service.

Additional trusted loopback development origins can be supplied as a comma-separated list in `PROMS_ALLOWED_ORIGINS`. Non-loopback browser origins remain blocked and cannot read status, save proxies, launch windows, or close windows.

The service also exposes `GET /health` and a secret-safe `GET /configuration` summary.

## API examples

Launch two browser windows per proxy:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/browsers `
  -ContentType 'application/json' `
  -Body '{"windows_per_proxy":2}'
```

Launch at most 50 windows, loading the same URL:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/browsers `
  -ContentType 'application/json' `
  -Body '{
    "windows_per_proxy": 2,
    "max_windows": 50,
    "url": "https://example.com"
  }'
```

`windows_per_proxy` applies to every proxy line. Optional `max_windows` caps the total. Launching proceeds once through every proxy before starting a second window per proxy, so a cap uses as many unique proxy lines as possible.

Every window uses a fresh temporary Chromium profile and browser context. Cookies and site storage are not shared between windows or reused by later launch jobs.

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

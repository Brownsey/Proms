# Proms

Proms opens multiple browser windows for side-by-side testing. Use Playwright Chromium or an installed copy of Google Chrome, and choose a direct connection or saved proxies. Each window starts with separate cookies and site storage.

## Quick start

**You need** Git and a logged-in desktop session. Install Google Chrome if you want regular Chrome windows with temporary profiles. The setup script installs missing development tools, installs locked dependencies and Playwright Chromium, and builds the control panel.

### 1. Get the code

Run these commands in PowerShell on Windows or Terminal on macOS.

```sh
git clone https://github.com/Brownsey/Proms.git
cd Proms
```

If you already have a checkout, open a terminal in its root instead and run `git pull --ff-only`. Then rerun setup to rebuild the panel and pick up dependency changes.

### 2. Run setup

**Windows** uses Windows Package Manager if it needs to install `uv` or Node.js LTS. Approve the installer prompt if Windows shows one.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
```

**macOS** requires macOS 14 Sonoma or newer. Install [Homebrew](https://brew.sh/) if setup needs it to install missing tools. The macOS setup has yet to be verified on macOS hardware.

```bash
bash scripts/setup.sh
```

### 3. Start Proms

From the repository root, run:

```sh
uv run --locked proms
```

Leave this terminal running and open the [local control panel](http://127.0.0.1:8000/control/). You can also run CLI commands in a second terminal from the same repository root. Press **Ctrl+C** in the service terminal to stop Proms and close its windows.

## Open eight Chrome profiles with no proxy

**Control panel**

1. Choose **Google Chrome (temporary profiles)** under **Launch mode**.
2. Choose **Direct (no proxy)** under **Network connection**.
3. Set **Window count** to `8`.
4. Set **Target URL** to the site you want to test or `about:blank`, then click **Launch windows**.

**CLI**

With Proms running, open a second terminal in the repository root.

```sh
uv run --locked proms launch --direct 8 --chrome --url about:blank
```

Replace `about:blank` with your test URL when needed. Check the active windows with `uv run --locked proms status`. When you’re done, run `uv run --locked proms close` to close all windows opened by Proms.

Use `uv run --locked proms launch --help` for launch options. If your system blocks the generated `proms` executable, use `uv run --locked python -m proms` with the same arguments.

In Chrome mode, each window uses a fresh profile directory. Closing the window removes its profile, so cookies and sign-ins start fresh in later launches. Direct launches work with an empty or missing proxy file. The control panel starts in **Saved proxies** mode and remembers the connection mode you select.

## Launch with saved proxies

In the control panel, open **Local proxy file**, enter one proxy per line, and save. Choose **Saved proxies** under **Network connection**, then set **Windows per proxy** and an optional **Maximum windows**. Proms launches one window for each proxy before starting the next round.

The CLI uses the same saved list. This example opens up to eight Chrome windows, with two per proxy:

```sh
uv run --locked proms launch --chrome --windows-per-proxy 2 --max-windows 8 --url about:blank
```

The local proxy file is git-ignored. Saving from the panel replaces the list on this computer. The panel shows the count without displaying saved values. Blank lines and lines starting with `#` are ignored. Supported formats include:

```text
host:port
http://host:port
http://username:password@host:port
username:password@host:port
host:port:username:password
socks5://host:port
```

Four-part values with a numeric second segment use `host:port:username:password`. Use an explicit `http://` prefix for a colon-containing password in `username:password@host:port`.

## Troubleshooting

- **The local page is unavailable.** Check that the service is still running and that [its health endpoint](http://127.0.0.1:8000/health) returns `{"status":"ok"}`. If the panel says it has not been built, rerun your platform’s setup script.
- **Chrome mode fails to start.** Check that Google Chrome is installed. The setup script installs Playwright Chromium for **Chromium (isolated sessions)**.
- **Saved proxies mode reports a missing list.** Save a list in **Local proxy file** or select **Direct (no proxy)**.

[proms.brownsey.co.uk](https://proms.brownsey.co.uk) hosts the installation guide. The browser controls are served by the local service at `127.0.0.1:8000`.

## API and development

`POST /browsers` accepts either `direct_windows` for a direct launch or `windows_per_proxy` with an optional `max_windows` for a proxy launch. Set `chrome_profiles` to `true` for Google Chrome. The optional `url` defaults to the IP checker.

For example, send this JSON to `http://127.0.0.1:8000/browsers` to open eight direct Chrome windows:

```json
{"direct_windows": 8, "chrome_profiles": true, "url": "about:blank"}
```

| Endpoint | Result |
| --- | --- |
| `GET /health` | Service health |
| `GET /configuration` | Saved proxy count |
| `GET /browsers` | Active window count |
| `DELETE /browsers` | Close all managed windows |

`PROMS_ALLOWED_ORIGINS` accepts a comma-separated list of trusted HTTP loopback development origins.

For manual setup with Python 3.12+, `uv`, and Node.js 20.9+ already available:

```sh
uv sync --locked
npm ci
npx playwright install chromium
uv run --locked playwright install chromium
npm run build
```

Run `npm run verify` for the full suite, `uv run --locked python -m proms.verify` for backend checks, or `npm run verify:frontend` for frontend checks.

"use client";

import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { resolveApiUrl } from "./environment";

const API_URL = resolveApiUrl(process.env.NODE_ENV, process.env.NEXT_PUBLIC_PROMS_API_URL);
const API_LABEL = API_URL || "this local address";
const STORAGE_KEY = "proms.launch-settings.v2";
const LEGACY_STORAGE_KEY = "proms.launch-settings.v1";
const DEFAULT_TARGET_URL = "https://whatismyipaddress.com/";
type Settings = {
  windowsPerProxy: string;
  maxWindows: string;
  targetUrl: string;
  chromeProfiles: boolean;
  directConnection: boolean;
  directWindows: string;
};
type Counts = { proxies: number | null; active: number | null };
type Action = "connect" | "refresh" | "launch" | "close" | "save";
const defaults: Settings = {
  windowsPerProxy: "1",
  maxWindows: "",
  targetUrl: DEFAULT_TARGET_URL,
  chromeProfiles: false,
  directConnection: false,
  directWindows: "1",
};

class UnexpectedResponse extends Error {}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function readSettings(): Settings {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored !== null) {
    const value = JSON.parse(stored) as (Partial<Settings> & { version?: unknown }) | null;
    if (value?.version === 2 && typeof value.windowsPerProxy === "string" && typeof value.maxWindows === "string") {
      return {
        ...defaults,
        windowsPerProxy: value.windowsPerProxy,
        maxWindows: value.maxWindows,
        chromeProfiles: value.chromeProfiles === true,
        directConnection: value.directConnection === true,
        directWindows: typeof value.directWindows === "string" ? value.directWindows : defaults.directWindows,
      };
    }
    return defaults;
  }

  const legacy = localStorage.getItem(LEGACY_STORAGE_KEY);
  if (legacy !== null) {
    const value = JSON.parse(legacy) as { staticWindows?: unknown } | null;
    if (typeof value?.staticWindows === "string" && !integer(value.staticWindows, "Windows per proxy")) {
      return { ...defaults, windowsPerProxy: value.staticWindows };
    }
  }
  return defaults;
}

function errorDetail(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (!Array.isArray(value)) return null;
  const messages = value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const message = "msg" in item && typeof item.msg === "string" ? item.msg : null;
    if (!message) return [];
    const location = "loc" in item && Array.isArray(item.loc) ? item.loc.filter((part: unknown) => part !== "body").join(".") : "";
    return [`${location ? `${location}: ` : ""}${message}`];
  });
  return messages.length ? messages.join("; ") : null;
}

async function requestJson(path: string, init?: RequestInit) {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  let body: unknown;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? errorDetail(body.detail) : null;
    throw new Error(detail ?? `Local service returned HTTP ${response.status}.`);
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new UnexpectedResponse("Local service returned an unexpected response.");
  }
  return body as Record<string, unknown>;
}

function integer(value: string, label: string) {
  if (!/^\d+$/.test(value)) return `${label} must be a whole number.`;
  const count = Number(value);
  if (!Number.isSafeInteger(count)) return `${label} is too large.`;
  return count < 1 ? `${label} must be 1 or greater.` : null;
}

function validate(settings: Settings) {
  const countError = settings.directConnection
    ? integer(settings.directWindows, "Window count")
    : integer(settings.windowsPerProxy, "Windows per proxy");
  if (countError) return countError;
  if (!settings.directConnection && settings.maxWindows) {
    const maxError = integer(settings.maxWindows, "Maximum windows");
    if (maxError) return maxError;
  }
  if (settings.targetUrl === "about:blank") return null;
  if (/^https?:\/\/[^/?#\\\s]/i.test(settings.targetUrl) && !/\s/.test(settings.targetUrl) && URL.canParse(settings.targetUrl)) {
    return null;
  }
  return "Target URL must be an absolute HTTP(S) URL or about:blank.";
}

export default function Dashboard() {
  const [settings, setSettings] = useState(defaults);
  const [storageReady, setStorageReady] = useState(false);
  const [connection, setConnection] = useState<"disconnected" | "connected">("disconnected");
  const [counts, setCounts] = useState<Counts>({ proxies: null, active: null });
  const [draft, setDraft] = useState("");
  const [action, setAction] = useState<Action | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const didAutoConnect = useRef(false);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      try {
        setSettings(readSettings());
      } catch {
        // Preferences are optional when storage is unavailable or corrupted.
      } finally {
        setStorageReady(true);
      }
    });
    return () => cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    if (!storageReady) return;
    try {
      localStorage.removeItem(LEGACY_STORAGE_KEY);
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        version: 2,
        windowsPerProxy: settings.windowsPerProxy,
        maxWindows: settings.maxWindows,
        ...(settings.chromeProfiles ? { chromeProfiles: true } : {}),
        ...(settings.directConnection ? { directConnection: true } : {}),
        ...(settings.directWindows !== defaults.directWindows ? { directWindows: settings.directWindows } : {}),
      }));
    } catch {
      // The current settings still work without local storage.
    }
  }, [settings.windowsPerProxy, settings.maxWindows, settings.chromeProfiles, settings.directConnection, settings.directWindows, storageReady]);

  useEffect(() => {
    if (!draft) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [draft]);

  function update<Field extends keyof Settings>(field: Field, value: Settings[Field]) {
    setSettings((current) => ({ ...current, [field]: value })); setError("");
  }

  const loadStatus = useCallback(async (mode: "connect" | "refresh") => {
    setAction(mode); setError(""); setNotice("");
    try {
      const [configuration, browsers] = await Promise.allSettled([
        requestJson("/configuration"),
        requestJson("/browsers"),
      ]);
      if (browsers.status === "rejected") throw browsers.reason;
      const { active } = browsers.value;
      if (!isCount(active)) throw new UnexpectedResponse("Local service returned an unexpected status response.");
      setConnection("connected");

      const proxies = configuration.status === "fulfilled" ? configuration.value.proxy_count : null;
      if (!isCount(proxies)) {
        setCounts({ proxies: null, active });
        setError(configuration.status === "rejected" && configuration.reason instanceof Error
          ? configuration.reason.message
          : "Local service returned an unexpected proxy count.");
        return;
      }

      setCounts({ proxies, active });
      setNotice(mode === "connect" ? "Local service connected." : "Status refreshed.");
    } catch (caught) {
      setConnection("disconnected"); setCounts({ proxies: null, active: null });
      setError(`${caught instanceof Error ? caught.message : "Connection failed."} Start the local service at ${API_LABEL}, then retry.`);
    } finally { setAction(null); }
  }, []);

  useEffect(() => { if (!didAutoConnect.current) { didAutoConnect.current = true; void loadStatus("connect"); } }, [loadStatus]);

  async function refreshActiveCount() {
    try {
      const { active } = await requestJson("/browsers");
      if (isCount(active)) setCounts((current) => ({ ...current, active }));
    } catch {
      // Keep the original operation error visible if status is unavailable.
    }
  }

  async function launch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem = validate(settings);
    if (problem) { setError(problem); setNotice(""); return; }
    setAction("launch"); setError(""); setNotice("");
    try {
      const connectionSettings = settings.directConnection
        ? { direct_windows: Number(settings.directWindows) }
        : {
            windows_per_proxy: Number(settings.windowsPerProxy),
            ...(settings.maxWindows ? { max_windows: Number(settings.maxWindows) } : {}),
          };
      const { launched, active } = await requestJson("/browsers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...connectionSettings,
          url: settings.targetUrl,
          ...(settings.chromeProfiles ? { chrome_profiles: true } : {}),
        }),
      });
      if (!isCount(launched) || !isCount(active)) throw new UnexpectedResponse("Local service returned an unexpected launch response.");
      setCounts((current) => ({ ...current, active }));
      setNotice(`Launched ${launched} windows. ${active} active.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Launch failed.");
      await refreshActiveCount();
    } finally {
      setAction(null);
    }
  }

  async function closeAll() {
    if (!window.confirm(`Close all ${counts.active ?? 0} active windows?`)) return;
    setAction("close"); setError(""); setNotice("");
    try {
      const { closed } = await requestJson("/browsers", { method: "DELETE" });
      if (!isCount(closed)) throw new UnexpectedResponse("Local service returned an unexpected close response.");
      setCounts((current) => ({ ...current, active: 0 }));
      setNotice(`Closed ${closed} windows.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Close failed.");
      await refreshActiveCount();
    } finally {
      setAction(null);
    }
  }

  async function saveProxies() {
    const hasProxy = draft.split(/\r?\n/).some((line) => line.trim() && !line.trimStart().startsWith("#"));
    if (!hasProxy && !window.confirm("Clear every proxy from this computer?")) return;
    setAction("save"); setError(""); setNotice("");
    try {
      const { count } = await requestJson("/configuration/proxies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proxies: draft, ...(!hasProxy ? { confirm_clear: true } : {}) }),
      });
      if (!isCount(count)) throw new UnexpectedResponse();
      setCounts((current) => ({ ...current, proxies: count }));
      setDraft("");
      setNotice(count === 0 ? "Cleared proxies." : `Saved ${count} ${count === 1 ? "proxy" : "proxies"}.`);
    } catch (caught) {
      if (caught instanceof TypeError) { setConnection("disconnected"); setCounts({ proxies: null, active: null }); setError(`Proxy list was not saved. Start the local service at ${API_LABEL}, reconnect, then try again. Draft kept.`); }
      else if (caught instanceof UnexpectedResponse) setError("Proxy list was not saved: unexpected save response. Draft kept.");
      else setError("Proxy list was not saved. Check each line uses a supported proxy format, then try again. Draft kept.");
    } finally { setAction(null); }
  }

  const busy = action !== null || !storageReady;
  const connected = connection === "connected";
  return (
    <main className="shell" aria-busy={busy}>
      <aside className="status-rail" aria-label="Local service status">
        <div>
          <p className="product-mark">PROMS / LOCAL CONTROL</p>
          <div className={`connection ${connected ? "is-connected" : ""}`}>
            <span className="signal" aria-hidden="true" />
            <span>{connected ? "Connected" : "Not connected"}</span>
          </div>
        </div>
        <div
          className="orbit"
          aria-label={
            counts.active === null
              ? "Active browser windows count unavailable"
              : `${counts.active} active browser windows`
          }
        >
          <span className="orbit-ring orbit-ring-outer" aria-hidden="true" />
          <span className="orbit-ring orbit-ring-inner" aria-hidden="true" />
          <div className="orbit-core">
            <strong>{counts.active ?? "—"}</strong>
            <span>active</span>
          </div>
          <span className="orbit-label orbit-proxy">P / {counts.proxies ?? "—"}</span>
        </div>
        <dl className="telemetry">
          <div><dt>Proxies</dt><dd>{counts.proxies ?? "—"}</dd></div>
          <div><dt>Windows</dt><dd>{counts.active === null ? "— active" : `${counts.active} active`}</dd></div>
        </dl>
        <div className="rail-actions">
          {connected ? (
            <button className="quiet-button" type="button" onClick={() => loadStatus("refresh")} disabled={busy}>
              {action === "refresh" ? "Refreshing…" : "Refresh status"}
            </button>
          ) : (
            <button className="connect-button" type="button" onClick={() => loadStatus("connect")} disabled={busy}>
              {action === "connect" ? "Connecting…" : "Retry connection"}
            </button>
          )}
          <p className="permission-note">
            This UI is served by the loopback service. Controls and proxy drafts stay on this PC.
            Existing proxy values are never displayed.
          </p>
        </div>
      </aside>

      <section className="manifest" aria-labelledby="manifest-heading">
        <header className="manifest-header">
          <div>
            <p className="eyebrow">Browser dispatch / single job</p>
            <h1 id="manifest-heading">Launch manifest</h1>
          </div>
          <p className="header-copy">
            Choose a browser, network connection, window count, and destination.
          </p>
        </header>
        <div className="message-stack" aria-live="polite" aria-atomic="true">
          {notice ? <p className="notice">{notice}</p> : null}
          {error ? <p role="alert" className="error">{error}</p> : null}
        </div>

        <form className="launch-form" onSubmit={launch} noValidate>
          <fieldset disabled={busy}>
            <legend>Browser</legend>
            <div className="count-fields">
              <label>
                <span>Launch mode</span>
                <select value={settings.chromeProfiles ? "chrome" : "chromium"} onChange={(event) => update("chromeProfiles", event.target.value === "chrome")} aria-describedby="launch-mode-help">
                  <option value="chromium">Chromium (isolated sessions)</option>
                  <option value="chrome">Google Chrome (temporary profiles)</option>
                </select>
                <small id="launch-mode-help">Chrome mode requires Google Chrome installed.</small>
              </label>
              <label>
                <span>Network connection</span>
                <select value={settings.directConnection ? "direct" : "proxy"} onChange={(event) => update("directConnection", event.target.value === "direct")}>
                  <option value="proxy">Saved proxies</option>
                  <option value="direct">Direct (no proxy)</option>
                </select>
              </label>
            </div>
          </fieldset>
          <fieldset disabled={busy}>
            <legend>Window capacity</legend>
            {settings.directConnection ? (
              <label className="wide-field">
                <span>Window count</span>
                <input type="number" inputMode="numeric" min="1" step="1" value={settings.directWindows} onChange={(event) => update("directWindows", event.target.value)} />
              </label>
            ) : (
              <div className="count-fields">
                <label>
                  <span>Windows per proxy</span>
                  <input type="number" inputMode="numeric" min="1" step="1" value={settings.windowsPerProxy} onChange={(event) => update("windowsPerProxy", event.target.value)} />
                  <small>{counts.proxies ?? "-"} lines available</small>
                </label>
                <label>
                  <span>Maximum windows</span>
                  <input type="number" inputMode="numeric" min="1" step="1" placeholder="All" value={settings.maxWindows} onChange={(event) => update("maxWindows", event.target.value)} />
                  <small>Blank launches all requested windows</small>
                </label>
              </div>
            )}
          </fieldset>
          <fieldset disabled={busy}>
            <legend>Destination</legend>
            <label className="wide-field">
              <span>Target URL</span>
              <input type="text" inputMode="url" autoCapitalize="none" spellCheck="false" value={settings.targetUrl} onChange={(event) => update("targetUrl", event.target.value)} />
              <small>Absolute HTTP(S) address or about:blank</small>
            </label>
          </fieldset>
          <details className="proxy-files">
            <summary><span>Local proxy file</span><small>Replace the proxy list</small></summary>
            <div className="proxy-files-body">
              <p>
                Save replaces the proxy file on this computer. Fixed proxies and sticky-session proxy
                credentials are accepted. Existing values are never displayed. Drafts go only to
                {` ${API_LABEL}`} and are never persisted in this browser.
              </p>
              <fieldset className="proxy-file-controls" disabled={busy}>
                <legend className="visually-hidden">Proxy file draft</legend>
                <div className="proxy-editor">
                  <label htmlFor="proxies">Proxies</label>
                  <textarea id="proxies" rows={6} autoComplete="off" autoCapitalize="none" spellCheck={false} aria-describedby="proxies-help" value={draft} onChange={(event) => { setDraft(event.target.value); setError(""); }} />
                  <small id="proxies-help">
                    One proxy per line. Blank lines and # comments are ignored. Use an http://
                    prefix when the password contains a colon.
                  </small>
                  <button className="save-list-button" type="button" onClick={saveProxies} disabled={!connected || busy}>
                    {action === "save" ? "Saving…" : "Save proxy list"}
                  </button>
                </div>
              </fieldset>
            </div>
          </details>
          <div className="action-row">
            <button className="launch-button" type="submit" disabled={!connected || busy}>
              {action === "launch" ? "Launching…" : "Launch windows"}
            </button>
            <button className="close-button" type="button" onClick={closeAll} disabled={!connected || busy || counts.active === 0}>
              {action === "close" ? "Closing…" : "Close all"}
            </button>
          </div>
        </form>
        <footer>
          <p>Each window starts with its own cookies and site storage. Later launches start fresh.</p>
          <p>Launch settings stay in this browser. Proxy values and service secrets are never persisted here.</p>
          <p>Control requests stay between this page and the local service.</p>
        </footer>
      </section>
    </main>
  );
}

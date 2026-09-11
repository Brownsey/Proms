"use client";

import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { resolveApiUrl } from "./environment";

const API_URL = resolveApiUrl(process.env.NODE_ENV, process.env.NEXT_PUBLIC_PROMS_API_URL);
const API_LABEL = API_URL || "this local address";
const STORAGE_KEY = "proms.launch-settings.v2";
const LEGACY_STORAGE_KEY = "proms.launch-settings.v1";
type Settings = { windowsPerProxy: string; maxWindows: string; targetUrl: string };
type Counts = { proxies: number | null; active: number | null };
type Action = "connect" | "refresh" | "launch" | "close" | "save";
const defaults: Settings = { windowsPerProxy: "1", maxWindows: "", targetUrl: "about:blank" };

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
  return body;
}

function integer(value: string, label: string, minimum: number) {
  if (!/^\d+$/.test(value)) return `${label} must be a whole number.`;
  return Number(value) < minimum ? `${label} must be ${minimum} or greater.` : null;
}

function validate(settings: Settings) {
  const countError = integer(settings.windowsPerProxy, "Windows per proxy", 1);
  if (countError) return countError;
  if (settings.maxWindows) {
    const maxError = integer(settings.maxWindows, "Maximum windows", 1);
    if (maxError) return maxError;
  }
  if (settings.targetUrl === "about:blank") return null;
  try {
    const url = new URL(settings.targetUrl);
    if ((url.protocol === "http:" || url.protocol === "https:") && url.hostname) return null;
  } catch {}
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
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored) {
          const value = JSON.parse(stored) as Partial<Settings> & { version?: unknown };
          if (value.version === 2 && typeof value.windowsPerProxy === "string" && typeof value.maxWindows === "string") {
            setSettings({ windowsPerProxy: value.windowsPerProxy, maxWindows: value.maxWindows, targetUrl: defaults.targetUrl });
          }
        } else {
          const legacy = localStorage.getItem(LEGACY_STORAGE_KEY);
          if (legacy) {
            const value = JSON.parse(legacy) as { staticWindows?: unknown };
            if (typeof value.staticWindows === "string" && /^\d+$/.test(value.staticWindows) && Number(value.staticWindows) >= 1) {
              setSettings({ ...defaults, windowsPerProxy: value.staticWindows });
            }
          }
        }
      } catch { localStorage.removeItem(STORAGE_KEY); }
      localStorage.removeItem(LEGACY_STORAGE_KEY);
      setStorageReady(true);
    });
    return () => cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    if (!storageReady) return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 2, windowsPerProxy: settings.windowsPerProxy, maxWindows: settings.maxWindows }));
  }, [settings.windowsPerProxy, settings.maxWindows, storageReady]);

  useEffect(() => {
    if (!draft) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [draft]);

  function update(field: keyof Settings, value: string) {
    setSettings((current) => ({ ...current, [field]: value })); setError("");
  }

  const loadStatus = useCallback(async (mode: "connect" | "refresh") => {
    setAction(mode); setError(""); setNotice("");
    try {
      const [configuration, browsers] = await Promise.all([requestJson("/configuration"), requestJson("/browsers")]) as [{ proxy_count?: unknown }, { active?: unknown }];
      if (typeof configuration.proxy_count !== "number" || typeof browsers.active !== "number") throw new Error("Local service returned an unexpected status response.");
      setCounts({ proxies: configuration.proxy_count, active: browsers.active }); setConnection("connected");
      setNotice(mode === "connect" ? "Local service connected." : "Status refreshed.");
    } catch (caught) {
      setConnection("disconnected"); setCounts({ proxies: null, active: null });
      setError(`${caught instanceof Error ? caught.message : "Connection failed."} Start the local service at ${API_LABEL}, then retry.`);
    } finally { setAction(null); }
  }, []);

  useEffect(() => { if (!didAutoConnect.current) { didAutoConnect.current = true; void loadStatus("connect"); } }, [loadStatus]);

  async function launch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem = validate(settings);
    if (problem) { setError(problem); setNotice(""); return; }
    setAction("launch"); setError(""); setNotice("");
    try {
      const result = await requestJson("/browsers", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ windows_per_proxy: Number(settings.windowsPerProxy), ...(settings.maxWindows ? { max_windows: Number(settings.maxWindows) } : {}), url: settings.targetUrl }) }) as { launched?: unknown; active?: unknown };
      if (typeof result.launched !== "number" || typeof result.active !== "number") throw new Error("Local service returned an unexpected launch response.");
      setCounts((current) => ({ ...current, active: result.active as number })); setNotice(`Launched ${result.launched} windows. ${result.active} active.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Launch failed."); } finally { setAction(null); }
  }

  async function closeAll() {
    if (!window.confirm(`Close all ${counts.active ?? 0} active windows?`)) return;
    setAction("close"); setError(""); setNotice("");
    try {
      const result = await requestJson("/browsers", { method: "DELETE" }) as { closed?: unknown };
      if (typeof result.closed !== "number") throw new Error("Local service returned an unexpected close response.");
      setCounts((current) => ({ ...current, active: 0 })); setNotice(`Closed ${result.closed} windows.`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Close failed."); } finally { setAction(null); }
  }

  async function saveProxies() {
    const hasProxy = draft.split(/\r?\n/).some((line) => line.trim() && !line.trimStart().startsWith("#"));
    if (!hasProxy && !window.confirm("Clear every proxy from this computer?")) return;
    setAction("save"); setError(""); setNotice("");
    try {
      const result = await requestJson("/configuration/proxies", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ proxies: draft, ...(!hasProxy ? { confirm_clear: true } : {}) }) }) as { count?: unknown };
      if (typeof result.count !== "number" || !Number.isInteger(result.count) || result.count < 0) throw new Error("unexpected save response");
      setCounts((current) => ({ ...current, proxies: result.count as number })); setDraft("");
      setNotice(result.count === 0 ? "Cleared proxies." : `Saved ${result.count} ${result.count === 1 ? "proxy" : "proxies"}.`);
    } catch (caught) {
      if (caught instanceof TypeError) { setConnection("disconnected"); setCounts({ proxies: null, active: null }); setError(`Proxy list was not saved. Start the local service at ${API_LABEL}, reconnect, then try again. Draft kept.`); }
      else if (caught instanceof Error && caught.message === "unexpected save response") setError("Proxy list was not saved: unexpected save response. Draft kept.");
      else setError("Proxy list was not saved. Check each line uses a supported proxy format, then try again. Draft kept.");
    } finally { setAction(null); }
  }

  const busy = action !== null;
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
            Set capacity for each proxy line, choose one destination, then dispatch headed Chromium
            windows from your machine.
          </p>
        </header>
        <div className="message-stack" aria-live="polite" aria-atomic="true">
          {notice ? <p className="notice">{notice}</p> : null}
          {error ? <p role="alert" className="error">{error}</p> : null}
        </div>

        <form className="launch-form" onSubmit={launch} noValidate>
          <fieldset disabled={busy}>
            <legend>Window capacity</legend>
            <div className="count-fields">
              <label>
                <span>Windows per proxy</span>
                <input type="number" inputMode="numeric" min="1" step="1" value={settings.windowsPerProxy} onChange={(event) => update("windowsPerProxy", event.target.value)} />
                <small>{counts.proxies ?? "—"} lines available</small>
              </label>
              <label>
                <span>Maximum windows</span>
                <input type="number" inputMode="numeric" min="1" step="1" placeholder="All" value={settings.maxWindows} onChange={(event) => update("maxWindows", event.target.value)} />
                <small>Blank launches all requested windows</small>
              </label>
            </div>
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
                <div className="proxy-editor-grid">
                  <div className="proxy-editor">
                    <label htmlFor="proxies">Proxies</label>
                    <textarea id="proxies" rows={6} autoComplete="off" autoCapitalize="none" spellCheck={false} aria-describedby="proxies-help" value={draft} onChange={(event) => { setDraft(event.target.value); setError(""); }} />
                    <small id="proxies-help">
                      One proxy per line, including username:password@host:port. Blank lines and #
                      comments are ignored. Use an http:// prefix when the password contains a
                      colon.
                    </small>
                    <button className="save-list-button" type="button" onClick={saveProxies} disabled={!connected || busy}>
                      {action === "save" ? "Saving…" : "Save proxy list"}
                    </button>
                  </div>
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
          <p>Launch settings stay in this browser. Proxy values and service secrets are never persisted here.</p>
          <p>Control requests stay between this page and the local service.</p>
        </footer>
      </section>
    </main>
  );
}

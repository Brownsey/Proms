"use client";

import { type FormEvent, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_PROMS_API_URL ?? "http://127.0.0.1:8000";
const STORAGE_KEY = "proms.launch-settings.v1";

type Settings = {
  staticWindows: string;
  rotatingWindows: string;
  targetUrl: string;
  rotationAttempts: string;
};

type Counts = {
  static: number | null;
  rotating: number | null;
  active: number | null;
};

const defaults: Settings = {
  staticWindows: "1",
  rotatingWindows: "0",
  targetUrl: "about:blank",
  rotationAttempts: "5",
};

function errorDetail(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (!Array.isArray(value)) return null;

  const messages = value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const message = "msg" in item && typeof item.msg === "string" ? item.msg : null;
    if (!message) return [];
    const location =
      "loc" in item && Array.isArray(item.loc)
        ? item.loc.filter((part: unknown) => part !== "body").join(".")
        : "";
    return [`${location ? `${location}: ` : ""}${message}`];
  });
  return messages.length ? messages.join("; ") : null;
}

async function requestJson(path: string, init?: RequestInit) {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? errorDetail(body.detail)
        : null;
    throw new Error(detail ?? `Local service returned HTTP ${response.status}.`);
  }
  return body;
}

function integer(value: string, label: string, minimum: number, maximum?: number) {
  if (!/^\d+$/.test(value)) return `${label} must be a whole number.`;
  const parsed = Number(value);
  if (parsed < minimum || (maximum !== undefined && parsed > maximum)) {
    return maximum === undefined
      ? `${label} must be ${minimum} or greater.`
      : `${label} must be between ${minimum} and ${maximum}.`;
  }
  return null;
}

function validTarget(value: string) {
  if (value === "about:blank") return true;
  try {
    const url = new URL(value);
    return (url.protocol === "http:" || url.protocol === "https:") && Boolean(url.hostname);
  } catch {
    return false;
  }
}

function validate(settings: Settings) {
  const staticError = integer(settings.staticWindows, "Static windows per proxy", 0);
  if (staticError) return staticError;
  const rotatingError = integer(settings.rotatingWindows, "Rotating windows per proxy", 0);
  if (rotatingError) return rotatingError;
  if (Number(settings.staticWindows) === 0 && Number(settings.rotatingWindows) === 0) {
    return "At least one window count must be greater than zero.";
  }
  if (!validTarget(settings.targetUrl)) {
    return "Target URL must be an absolute HTTP(S) URL or about:blank.";
  }
  return integer(settings.rotationAttempts, "Rotation attempts", 1, 20);
}

export default function Dashboard() {
  const [settings, setSettings] = useState<Settings>(defaults);
  const [storageReady, setStorageReady] = useState(false);
  const [connection, setConnection] = useState<"disconnected" | "connected">("disconnected");
  const [counts, setCounts] = useState<Counts>({ static: null, rotating: null, active: null });
  const [action, setAction] = useState<"connect" | "refresh" | "launch" | "close" | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored) {
        const value = JSON.parse(stored) as Partial<Settings> & { version?: unknown };
        if (
          value.version === 1 &&
          typeof value.staticWindows === "string" &&
          typeof value.rotatingWindows === "string" &&
          typeof value.rotationAttempts === "string"
        ) {
          setSettings({
            staticWindows: value.staticWindows,
            rotatingWindows: value.rotatingWindows,
            targetUrl: defaults.targetUrl,
            rotationAttempts: value.rotationAttempts,
          });
          }
        }
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
      setStorageReady(true);
    });
    return () => cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    if (!storageReady) return;
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        version: 1,
        staticWindows: settings.staticWindows,
        rotatingWindows: settings.rotatingWindows,
        rotationAttempts: settings.rotationAttempts,
      }),
    );
  }, [settings.staticWindows, settings.rotatingWindows, settings.rotationAttempts, storageReady]);

  function update(field: keyof Settings, value: string) {
    setSettings((current) => ({ ...current, [field]: value }));
    setError("");
  }

  async function loadStatus(mode: "connect" | "refresh") {
    setAction(mode);
    setError("");
    setNotice("");
    try {
      const [configuration, browsers] = (await Promise.all([
        requestJson("/configuration"),
        requestJson("/browsers"),
      ])) as [
        { static_proxy_count?: unknown; rotating_proxy_count?: unknown },
        { active?: unknown },
      ];
      if (
        typeof configuration.static_proxy_count !== "number" ||
        typeof configuration.rotating_proxy_count !== "number" ||
        typeof browsers.active !== "number"
      ) {
        throw new Error("Local service returned an unexpected status response.");
      }
      setCounts({
        static: configuration.static_proxy_count,
        rotating: configuration.rotating_proxy_count,
        active: browsers.active,
      });
      setConnection("connected");
      setNotice(mode === "connect" ? "Local service connected." : "Status refreshed.");
    } catch (caught) {
      setConnection("disconnected");
      setCounts({ static: null, rotating: null, active: null });
      const reason = caught instanceof Error ? caught.message : "Connection failed.";
      setError(
        `${reason} Start the local service at ${API_URL}, then allow local network access and connect again.`,
      );
    } finally {
      setAction(null);
    }
  }

  async function launch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validationError = validate(settings);
    if (validationError) {
      setError(validationError);
      setNotice("");
      return;
    }

    setAction("launch");
    setError("");
    setNotice("");
    try {
      const result = (await requestJson("/browsers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          static_windows_per_proxy: Number(settings.staticWindows),
          rotating_windows_per_proxy: Number(settings.rotatingWindows),
          url: settings.targetUrl,
          rotation_attempts: Number(settings.rotationAttempts),
        }),
      })) as { launched?: unknown; active?: unknown };
      if (typeof result.launched !== "number" || typeof result.active !== "number") {
        throw new Error("Local service returned an unexpected launch response.");
      }
      setCounts((current) => ({ ...current, active: result.active as number }));
      setNotice(`Launched ${result.launched} windows. ${result.active} active.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Launch failed.");
    } finally {
      setAction(null);
    }
  }

  async function closeAll() {
    if (!window.confirm(`Close all ${counts.active ?? 0} active windows?`)) return;
    setAction("close");
    setError("");
    setNotice("");
    try {
      const result = (await requestJson("/browsers", { method: "DELETE" })) as {
        closed?: unknown;
      };
      if (typeof result.closed !== "number") {
        throw new Error("Local service returned an unexpected close response.");
      }
      setCounts((current) => ({ ...current, active: 0 }));
      setNotice(`Closed ${result.closed} windows.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Close failed.");
    } finally {
      setAction(null);
    }
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

        <div className="orbit" aria-label={`${counts.active ?? 0} active browser windows`}>
          <span className="orbit-ring orbit-ring-outer" aria-hidden="true" />
          <span className="orbit-ring orbit-ring-inner" aria-hidden="true" />
          <div className="orbit-core">
            <strong>{counts.active ?? "—"}</strong>
            <span>active</span>
          </div>
          <span className="orbit-label orbit-static">S / {counts.static ?? "—"}</span>
          <span className="orbit-label orbit-rotating">R / {counts.rotating ?? "—"}</span>
        </div>

        <dl className="telemetry">
          <div>
            <dt>Static proxies</dt>
            <dd>{counts.static ?? "—"}</dd>
          </div>
          <div>
            <dt>Rotating proxies</dt>
            <dd>{counts.rotating ?? "—"}</dd>
          </div>
          <div>
            <dt>Windows</dt>
            <dd>{counts.active === null ? "— active" : `${counts.active} active`}</dd>
          </div>
        </dl>

        <div className="rail-actions">
          {connected ? (
            <button className="quiet-button" type="button" onClick={() => loadStatus("refresh")} disabled={busy}>
              {action === "refresh" ? "Refreshing…" : "Refresh status"}
            </button>
          ) : (
            <button className="connect-button" type="button" onClick={() => loadStatus("connect")} disabled={busy}>
              {action === "connect" ? "Connecting…" : "Connect local service"}
            </button>
          )}
          <p className="permission-note">
            The Proms local service must already be installed and running on this computer. {" "}
            <a href="https://github.com/Brownsey/Proms#setup" target="_blank" rel="noreferrer">
              Setup instructions
            </a>
            . {" "}
            Your browser may ask permission to reach devices on your local network. This page only contacts {API_URL}.
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
            Set capacity for each proxy line, choose one destination, then dispatch headed Chromium windows from your machine.
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
                <span>Static windows per proxy</span>
                <input
                  type="number"
                  inputMode="numeric"
                  min="0"
                  step="1"
                  value={settings.staticWindows}
                  onChange={(event) => update("staticWindows", event.target.value)}
                />
                <small>{counts.static ?? "—"} lines available</small>
              </label>
              <label>
                <span>Rotating windows per proxy</span>
                <input
                  type="number"
                  inputMode="numeric"
                  min="0"
                  step="1"
                  value={settings.rotatingWindows}
                  onChange={(event) => update("rotatingWindows", event.target.value)}
                />
                <small>{counts.rotating ?? "—"} lines available</small>
              </label>
            </div>
          </fieldset>

          <fieldset disabled={busy}>
            <legend>Destination</legend>
            <label className="wide-field">
              <span>Target URL</span>
              <input
                type="text"
                inputMode="url"
                autoCapitalize="none"
                spellCheck="false"
                value={settings.targetUrl}
                onChange={(event) => update("targetUrl", event.target.value)}
              />
              <small>Absolute HTTP(S) address or about:blank</small>
            </label>
          </fieldset>

          <fieldset disabled={busy}>
            <legend>Rotation policy</legend>
            <label className="attempt-field">
              <span>Rotation attempts</span>
              <input
                type="number"
                inputMode="numeric"
                min="1"
                max="20"
                step="1"
                value={settings.rotationAttempts}
                onChange={(event) => update("rotationAttempts", event.target.value)}
              />
              <small>Fresh-IP attempts per rotating window, 1–20</small>
            </label>
          </fieldset>

          <div className="action-row">
            <button className="launch-button" type="submit" disabled={!connected || busy}>
              {action === "launch" ? "Launching…" : "Launch windows"}
            </button>
            <button
              className="close-button"
              type="button"
              onClick={closeAll}
              disabled={!connected || busy || counts.active === 0}
            >
              {action === "close" ? "Closing…" : "Close all"}
            </button>
          </div>
        </form>

        <footer>
          <p>Settings stay in this browser. Proxy values and service secrets are never stored here.</p>
          <p>Safari does not support this remote-to-local control flow. Use Chrome, Edge, or Firefox.</p>
        </footer>
      </section>
    </main>
  );
}

import { CopyPrompt } from "./components/copy-prompt";

const steps = [
  ["01", "Open Codex", "Use Codex on the Windows PC where you want Proms to run."],
  ["02", "Paste the setup packet", "Codex will download or update Proms, install its locked dependencies, and start the service."],
  ["03", "Open local control", "When setup finishes, use http://127.0.0.1:8000/control/ to manage proxies and launch windows."],
] as const;

export default function Installer() {
  return (
    <main className="installer-shell">
      <header className="installer-header">
        <p className="product-mark installer-mark">PROMS / WINDOWS HANDOFF</p>
        <nav className="project-links" aria-label="Project links">
          <a className="repo-link" href="https://github.com/Brownsey/Proms" target="_blank" rel="noreferrer">
            GitHub repository
          </a>
          <a className="repo-link" href="https://github.com/Brownsey/Proms#setup" target="_blank" rel="noreferrer">
            Setup guide
          </a>
        </nav>
      </header>

      <section className="installer-hero" aria-labelledby="installer-heading">
        <div>
          <p className="eyebrow">Local browser operations</p>
          <h1 id="installer-heading">Run Proms on this PC</h1>
        </div>
        <p className="installer-lede">
          The public site is only an installation guide. Browser controls and proxy values stay on this computer,
          behind the loopback service.
        </p>
      </section>

      <div className="handoff-grid">
        <section className="runbook" aria-labelledby="runbook-heading">
          <div className="section-heading">
            <p className="eyebrow">Human route</p>
            <h2 id="runbook-heading">Three steps to local control</h2>
          </div>
          <ol>
            {steps.map(([number, title, body]) => (
              <li key={number}>
                <span aria-hidden="true">{number}</span>
                <div>
                  <h3>{title}</h3>
                  <p>{body}</p>
                </div>
              </li>
            ))}
          </ol>
          <aside className="security-note">
            <strong>LOCAL BOUNDARY</strong>
            <p>
              Proxy entries are sent only to <code>127.0.0.1</code>. The hosted page cannot read, display, or store them.
            </p>
          </aside>
        </section>

        <section className="codex-lane" aria-labelledby="codex-heading">
          <div className="section-heading">
            <p className="eyebrow">Codex route</p>
            <h2 id="codex-heading">Copy one complete instruction</h2>
          </div>
          <p>Copy this read-only prompt into Codex. It includes the safe setup and verification boundaries.</p>
          <CopyPrompt />
        </section>
      </div>

      <footer className="installer-footer">
        <p>Proms runs Chromium and manages proxy files from your Windows machine.</p>
        <p>The hosted guide never connects to your local service.</p>
      </footer>
    </main>
  );
}

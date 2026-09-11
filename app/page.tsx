import { CopyPrompt } from "./components/copy-prompt";

export default function Installer() {
  return (
    <main className="installer-shell">
      <header className="installer-header">
        <p className="product-mark installer-mark">PROMS / LOCAL HANDOFF</p>
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
          <h1 id="installer-heading">Run Proms locally</h1>
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
            <h2 id="runbook-heading">Install, run, control</h2>
          </div>
          <section className="setup-stage" aria-labelledby="get-code-heading">
            <div className="platform-heading">
              <span aria-hidden="true">01</span>
              <h3 id="get-code-heading">Get the code</h3>
            </div>
            <p>Open PowerShell on Windows or Terminal on macOS. For a new checkout, run:</p>
            <div className="command-stack">
              <code>git clone https://github.com/Brownsey/Proms.git</code>
              <code>cd Proms</code>
            </div>
            <p>Already have Proms? Enter its repository root, preserve local changes, then update:</p>
            <div className="command-stack">
              <code>git pull --ff-only</code>
            </div>
          </section>

          <section className="setup-stage" aria-labelledby="windows-heading">
            <div className="platform-heading">
              <span aria-hidden="true">02</span>
              <h3 id="windows-heading">Windows setup</h3>
            </div>
            <p>Install locked dependencies and build the local control panel:</p>
            <div className="command-stack">
              <code>powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1</code>
              <code>uv run --locked proms</code>
              <code>http://127.0.0.1:8000/control/</code>
            </div>
          </section>

          <section className="setup-stage" aria-labelledby="macos-heading">
            <div className="platform-heading">
              <span aria-hidden="true">03</span>
              <h3 id="macos-heading">macOS setup</h3>
              <strong className="untested-label">Currently untested</strong>
            </div>
            <p>Requires macOS 14 Sonoma or newer and a logged-in GUI session.</p>
            <p>Install locked dependencies and build the local control panel:</p>
            <div className="command-stack">
              <code>bash scripts/setup.sh</code>
              <code>uv run --locked proms</code>
              <code>http://127.0.0.1:8000/control/</code>
            </div>
          </section>
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
        <p>Proms runs Chromium and manages proxy files from your Windows or macOS computer.</p>
        <p>The hosted guide never connects to your local service.</p>
      </footer>
    </main>
  );
}

"use client";

import { useRef, useState } from "react";

export const CODEX_SETUP_PROMPT = [
  "Set up https://github.com/Brownsey/Proms on this Windows or macOS computer.",
  "Detect whether the operating system is Windows or macOS.",
  "Locate the existing checkout; if absent, run: git clone https://github.com/Brownsey/Proms.git",
  "Enter the repository root.",
  "If the checkout existed, preserve local changes, then run: git pull --ff-only",
  "Read AGENTS.md before doing substantive work.",
  "Never read or print proxy files or proxy values.",
  "On Windows, run the full idempotent setup command: powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1",
  "On macOS, run the full idempotent setup command: bash scripts/setup.sh",
  "Start uv run --locked proms persistently.",
  "Verify GET http://127.0.0.1:8000/health.",
  "Read only the numeric counts from GET http://127.0.0.1:8000/configuration.",
  "Open http://127.0.0.1:8000/control/ and report the result.",
].join("\n");

export function CopyPrompt() {
  const prompt = useRef<HTMLTextAreaElement>(null);
  const [status, setStatus] = useState<"idle" | "copied" | "failed">("idle");

  async function copy() {
    try {
      await navigator.clipboard.writeText(CODEX_SETUP_PROMPT);
      setStatus("copied");
    } catch {
      prompt.current?.focus();
      prompt.current?.select();
      setStatus("failed");
    }
  }

  return (
    <div className="handoff-packet">
      <div className="packet-label">
        <span>CODEX / SETUP PACKET</span>
        <span aria-hidden="true">LOCAL—01</span>
      </div>
      <label htmlFor="codex-prompt">Codex setup prompt</label>
      <textarea
        id="codex-prompt"
        ref={prompt}
        rows={13}
        readOnly
        spellCheck={false}
        value={CODEX_SETUP_PROMPT}
      />
      <div className="packet-actions">
        <button className="copy-button" type="button" onClick={copy}>
          Copy Codex prompt
        </button>
        <p className={`copy-status copy-${status}`} aria-live="polite">
          {status === "copied"
            ? "Copied"
            : status === "failed"
              ? "Copy failed — select the prompt and copy it manually."
              : "Paste into a Codex task on this computer."}
        </p>
      </div>
    </div>
  );
}

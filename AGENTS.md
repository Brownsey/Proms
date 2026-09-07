<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## Automated repository setup (Windows)

When asked to install, configure, or run Proms:

1. Work from the repository root.
2. Never open or read proxy files. Never print, commit, or upload proxy values. Never copy them into tests, commands, logs, or agent messages.
3. `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -CheckOnly` is an optional, read-only prerequisite diagnostic. It does not prove repository dependencies or Chromium are installed.
4. Always run the full idempotent setup command: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1`. This installs missing `uv` and Node.js LTS through `winget`, restores locked Python/npm dependencies, installs Playwright Chromium, and creates empty ignored proxy files when absent. An OS approval prompt may still require the user.
5. Start the loopback service with `uv run proms` and confirm `GET http://127.0.0.1:8000/health`.
6. Read only the numeric counts from `GET /configuration`. If both counts are zero, stop and ask the user to add proxy values locally; never inspect the files or ask them to paste credentials into chat.
7. Direct the user to `https://proms-rust.vercel.app` and its **Connect local service** button.
8. Run `npm run verify` after repository changes.

The hosted website cannot install or start the local service because browsers cannot launch native programs. Do not claim setup is zero-install.

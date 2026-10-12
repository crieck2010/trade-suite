# Agent Instructions & Project Standing Rules

## DevBridge Task Ingestion (Meta Muse × Google Drive × Antigravity)

- **Queue Location:** `G:\My Drive\inter-AI communications\agentic algorithmic trading system tools\`
  - `inbox/` — Incoming new spec tickets from Meta Muse / Charlie.
  - `processing/` — Claimed tickets currently in progress by Antigravity.
  - `completed/` — Finished tickets with clean tests and committed code.

- **Workflow Rule for Antigravity:**
  For each `*.md` ticket found in `inbox/`:
  1. Move it to `../processing/` immediately (claim it).
  2. Create branch `vibe/<slug>` from `master` in `crieck2010/trade-suite`. Pull first; never work on a stale tree.
  3. Implement per the ticket's Expected Behavior. Keep diffs minimal and additive. If the ticket would break an existing engine, STOP and leave a comment file in `processing/` instead of coding.
  4. Write/update tests and docs alongside the code.
  5. Run the affected test suite; everything must pass before pushing.
  6. Commit with a clear message referencing the ticket ID, push the branch, and open a Pull Request against `master`.
  7. Move the ticket to `../completed/`.

- **Safety & Scope Boundaries:**
  - Never merge your own PRs without human review.
  - Never use the GitHub PAT — use gh OAuth.
  - Never write strategy code that touches live broker execution; this system is research/paper-only until Charlie explicitly authorizes live execution.
  - Preserve strict engine/UI separation: UI components contain zero trading math or raw order routing.
  - All manual overrides and emergency halts write atomically to `audit_log.json`.

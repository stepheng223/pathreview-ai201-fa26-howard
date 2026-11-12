# Module 3 Journal

## Unit 7 — Issue selection

**Issue link:** https://github.com/codepath/pathreview-ai201-fa26-howard/issues/15

**Issue title:** Agent session state is not cleared between reviews for the same user

**Tier:** [x] Tier 1  [ ] Tier 2  [ ] Tier 3

The issue carries the `tier-1` label on GitHub. Tier 1 matches my
current comfort level: this is my first contribution to the PathReview
codebase, and while I'm comfortable with Python and have read through a
few multi-module repos before, I haven't worked inside this project's
agent/orchestration layer yet. Starting at Tier 1 lets me learn the
project's conventions (tests, CI, PR template, commit style) on an
issue whose fix is localized before I take on anything broader.

**Problem summary:**
The `Orchestrator` in `agent/orchestrator.py` creates one `ContextManager`
in `__init__` and never resets it, and it also merges each run's output
into whatever Redis blob the `SessionStore` already has for that profile.
So when the same orchestrator instance handles two reviews — or a second
review of the same profile after a restart — every tool whose input hash
matches a prior call short-circuits to the first run's cached `ToolResult`
instead of re-executing, and the saved session state still carries fields
from the earlier review. A successful fix empties the in-memory cache and
deletes the profile's stored session state at the top of `run`, so each
review starts from a clean slate and the orchestrator can be reused safely
across profiles without cross-contamination.

**Branch name:** fix/15-orchestrator-session-reset

**Setup confirmation:** [x] App runs locally at localhost:5173

**Cohort ledger:** [ ] Issue added to cohort ledger

### "Is this right for me?" — scope reasoning

- **Scope is bounded.** The fix touches three files named in the issue
  (`agent/orchestrator.py`, `agent/memory/context_manager.py`,
  `agent/memory/session_store.py`) and the change is localized to the
  entry of `Orchestrator.run` plus one small helper on `ContextManager`.
- **The bug is reproducible from reading the code.** `ContextManager` is
  constructed once in `__init__` and `session_store.get(...)` is merged
  into on every run — there is no reset path, so the behavior described
  in the issue follows directly from the control flow.
- **No architectural changes required.** No new abstractions, no data
  model changes, no cross-module refactor; just clearing state that
  should not have been carried across runs.
- **Testability is straightforward.** Running the orchestrator twice on
  distinct profile inputs and asserting the second run re-executes tools
  (rather than returning cached first-run results) is enough to pin the
  behavior down.
- **Effort estimate matches:** the issue lists 3–4 hours, which is
  consistent with the fix plus unit coverage.

# Solution plan

**Issue:** [#15 — Agent session state is not cleared between reviews for the
same user](https://github.com/codepath/pathreview-ai201-fa26-howard/issues/15)

## Understand

**Root cause.** `Orchestrator.__init__` builds exactly one `ContextManager`
and never resets it, and `Orchestrator.run` loads the profile's prior
Redis blob with `session_store.get(profile_id)` and merges this run's
output on top with `session_state.update(results)` before writing it
back. Nothing on the entry path to `run` drops either store.

**Expected behavior.** Every call to `run(profile_id, profile_data)` is a
fresh review: the in-memory memoization cache starts empty, and the
persisted session blob for that profile reflects only this run's output.

**Actual behavior.**
- Reusing the same `Orchestrator` for two profiles (or two reviews of
  the same profile) returns the *first* run's `ToolResult` for every
  tool whose `input_hash` matches, because `_execute_tool` finds a hit
  in `self.context_manager` and short-circuits before ever calling the
  tool.
- The Redis blob accumulates fields across runs: if run N executed tool
  X and run N+1 no longer does, X's old output is still in the blob
  `session_state.update(results)` writes back.

## Map

Files I expect to touch:

- `agent/orchestrator.py` — the fix lives at the top of `run()`.
- `agent/memory/context_manager.py` — needs a `clear()` method so the
  orchestrator has a clean way to drop cached results.
- `agent/memory/session_store.py` — read-only; the existing `delete()`
  method already does what the fix needs.
- `tests/unit/test_orchestrator_session_reset.py` *(new)* — regression
  tests that would fail without the fix.

Related call sites I checked and deliberately did **not** touch:
- `_execute_tool` and `_build_plan` — the bug is state carried into
  `run`, not logic inside those helpers.
- Callers of `Orchestrator.run` — the contract (`profile_id`,
  `profile_data` in; result dict out) doesn't change, so no caller
  needs updating.

## Plan

1. **Add `ContextManager.clear()`** — a one-liner that empties
   `self.results`. Keeps the reset vocabulary on the class that owns
   the cache instead of poking at its internals from the orchestrator.
2. **Reset at the top of `Orchestrator.run()`** — before `_build_plan`,
   call `self.context_manager.clear()` and, if a `session_store` is
   configured, `self.session_store.delete(profile_id)`.
3. **Drop the prior-blob load** — replace the `session_state =
   self.session_store.get(profile_id) or {}` line with a fresh
   `session_state: dict = {}`, so the write at the end is only this
   run's `results`, not a merge.
4. **Pin the behavior with regression tests** in
   `tests/unit/test_orchestrator_session_reset.py`:
   - Two `run` calls with identical inputs → the underlying tool is
     invoked twice, not once.
   - Two `run` calls for different profiles → profile B's returned
     `cached_results` contains only B's entries.
   - When a `session_store` is configured, `delete(profile_id)` is
     called once at the top of `run`, and the blob written back at the
     end reflects only this run.
5. **Run the full unit suite** (`make test-unit`) to confirm nothing
   else depended on the old carry-over behavior.

## Inputs & outputs

- **Input:** `run(profile_id: str, profile_data: dict)` — unchanged
  signature.
- **Output:** `{"profile_id", "tool_results", "cached_results"}` —
  unchanged shape; `cached_results` now reflects only this run.
- **Side effects:**
  - In-memory `ContextManager.results` is emptied at the top of each
    `run` and refilled by this run's executions.
  - Redis key `session:{profile_id}` is deleted at the top of each
    `run` and rewritten at the end with this run's output (TTL
    unchanged at 3600s via `SessionStore.set`).

## Risks & unknowns

- **Someone may have been relying on the stale behavior as an implicit
  cross-request cache.** The result dict still exposes
  `cached_results` per run, so callers that only read the current
  run's cache keep working. Any caller that was fishing an older
  profile's entries out of a long-lived orchestrator would break — I
  haven't found such a caller via `grep -rn "cached_results\|run("
  agent api`, but I'll re-check during PR review.
- **Redis `delete` on a missing key.** `SessionStore.delete` wraps the
  call in try/except and only logs on error, so the first-ever run
  for a profile (no blob to delete) is safe.
- **Concurrency.** Two `run` calls for the same `profile_id` racing on
  the same orchestrator will still interleave on the shared
  `ContextManager`. That's a pre-existing property of this class (it
  isn't thread-safe), and issue #15 is about serial reuse, so I'm
  leaving it out of scope and will note it in the PR description.
- **Tool side-effect idempotence.** If a tool called from `run` has
  external side effects (e.g. writes to GitHub), re-executing it on
  the second review of the same profile now actually re-invokes it
  instead of returning the cached result. For the tools currently in
  this repo (readme_scorer, tech_detector, skill_extractor,
  market_analyzer, github_tool read-only queries) that's the correct
  behavior, but worth calling out in the PR.

## Edge cases

- **No `session_store` configured.** The `if self.session_store:`
  guard around `delete` already handles this path.
- **Prior blob is empty or malformed.** `get` returns `None` on decode
  errors, and the new code no longer reads it, so this is moot.
- **First run for a profile.** `delete` on a missing Redis key is a
  no-op — covered by `SessionStore.delete`'s try/except.
- **Empty `profile_data`.** `_build_plan` returns an empty plan; the
  reset still runs, then `results` is `{}` and gets written back as an
  empty blob. Acceptable: matches "this run produced nothing".
- **Same profile, identical input, back-to-back runs.** The new
  behavior is to re-execute — this is the exact repro case for the
  bug, and the regression tests pin it.
- **Different profiles sharing input.** Each run clears the cache
  first, so profile B's `_execute_tool` sees an empty
  `ContextManager` even though the input hash would have matched
  profile A's.

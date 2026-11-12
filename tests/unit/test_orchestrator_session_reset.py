"""Regression tests for issue #15: session state must reset between reviews.

Before the fix, Orchestrator kept one ContextManager for its whole lifetime
and merged each run's output into whatever SessionStore already held, so a
second review of the same profile returned the first run's cached tool
results. These tests pin the clean-slate behavior.
"""

from unittest.mock import MagicMock

import pytest

from agent.orchestrator import Orchestrator
from agent.tools.base import BaseTool, ToolResult


class _CountingReadmeScorer(BaseTool):
    """Stand-in tool that records every call so we can tell cache hits
    from real executions."""

    name = "readme_scorer"
    description = "test double"

    def __init__(self):
        self.calls: list[dict] = []

    def execute(self, input_data: dict) -> ToolResult:
        self.calls.append(dict(input_data))
        return ToolResult(success=True, data={"score": len(self.calls)})


@pytest.mark.unit
class TestOrchestratorSessionReset:
    def _profile(self, readme: str) -> dict:
        return {"readme_content": readme}

    def test_second_run_same_input_reexecutes_tool(self):
        """Issue #15 repro: two reviews with identical tool inputs.

        Without the fix the second run short-circuited to the first run's
        cached ToolResult, so the tool was only called once.
        """
        tool = _CountingReadmeScorer()
        orch = Orchestrator({"readme_scorer": tool})

        orch.run("profile-A", self._profile("# hello"))
        orch.run("profile-A", self._profile("# hello"))

        assert len(tool.calls) == 2, (
            "second run must re-execute the tool, not return the first " "run's cached ToolResult"
        )

    def test_cached_results_do_not_leak_across_profiles(self):
        """A second profile's run must not expose profile-A's cache entries."""
        tool = _CountingReadmeScorer()
        orch = Orchestrator({"readme_scorer": tool})

        orch.run("profile-A", self._profile("# A"))
        result_b = orch.run("profile-B", self._profile("# B"))

        assert result_b["cached_results"].keys(), "run B should have its own cache"
        for key in result_b["cached_results"]:
            # Keys look like "<tool>:<input_hash>" — the hash encodes the
            # input dict, so A's entries and B's entries differ. After the
            # fix, run B's returned cache contains only B's entries.
            assert key.startswith("readme_scorer:")
        assert len(result_b["cached_results"]) == 1, "run B must not see profile-A's cached entries"

    def test_session_store_is_cleared_at_run_start(self):
        """Stale session blob for the profile must be dropped before the run.

        Without the fix, run() loaded the previous blob and merged this
        run's results on top, so removed/renamed tool outputs lingered.
        """
        store = MagicMock()
        store.get.return_value = {"readme_scorer": {"score": 999, "stale": True}}
        tool = _CountingReadmeScorer()
        orch = Orchestrator({"readme_scorer": tool}, session_store=store)

        orch.run("profile-A", self._profile("# fresh"))

        store.delete.assert_called_once_with("profile-A")
        # And the blob actually written back reflects THIS run, not the stale one.
        written = store.set.call_args.args[1]
        assert written["readme_scorer"] == {"score": 1}

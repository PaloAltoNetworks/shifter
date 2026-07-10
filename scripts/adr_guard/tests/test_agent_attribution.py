"""Tests for agent attribution detection."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from agent_attribution import find_agent_attribution_matches


class AgentAttributionTests(unittest.TestCase):
    def test_blocks_cursor_co_author_trailer(self):
        text = "fix: thing\n\nCo-authored-by: Cursor <cursoragent@cursor.com>\n"
        matches = find_agent_attribution_matches(text)
        self.assertGreaterEqual(len(matches), 1)
        rules = {match.rule for match in matches}
        self.assertIn("co-authored-by-cursor", rules)

    def test_blocks_made_with_cursor_pr_footer(self):
        text = "## Summary\n\nMade with [Cursor](https://cursor.com)\n"
        matches = find_agent_attribution_matches(text)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].rule, "made-with-cursor-footer")

    def test_blocks_generated_with_claude_code(self):
        text = "Generated with Claude Code\n"
        matches = find_agent_attribution_matches(text)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].rule, "generated-with-claude-code")

    def test_allows_cursor_docs_reference(self):
        text = "See https://cursor.com/docs/settings/aws-bedrock for setup.\n"
        self.assertEqual(find_agent_attribution_matches(text), [])


if __name__ == "__main__":
    unittest.main()

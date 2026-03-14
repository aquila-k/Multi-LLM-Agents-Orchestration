from __future__ import annotations

import unittest

from collab.runtime.renderers.markdown import render_markdown_document


class MarkdownRendererUnitTest(unittest.TestCase):
    def test_renders_nested_json_payload_to_markdown(self) -> None:
        rendered = render_markdown_document(
            title="Example",
            payload={
                "manifest": {"phase": "impl", "strategy": "COLLAB_IMPL_PATCH_FIRST"},
                "reasons": ["one", "two"],
            },
        )

        self.assertIn("# Example", rendered)
        self.assertIn("## manifest", rendered)
        self.assertIn("### phase", rendered)
        self.assertIn("- one", rendered)


if __name__ == "__main__":
    unittest.main()

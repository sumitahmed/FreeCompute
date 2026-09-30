import unittest
from harness.tools import web
from harness.tools.registry import ToolRegistry


class TestWebTools(unittest.TestCase):
    def test_search_web_structure(self):
        # Test query formatting and error handling for empty query
        empty_res = web.search_web("")
        self.assertIn("error", empty_res)

    def test_fetch_url_validation(self):
        # Test invalid protocol or non-existent
        res = web.fetch_url("http://0.0.0.0:12345/nonexistent")
        self.assertIn("error", res)

    def test_registry_argument_validation(self):
        registry = ToolRegistry(workspace_root=".")
        # Test write_file missing required path and content
        res = registry.execute("write_file", {})
        self.assertIn("error", res)
        self.assertIn("missing required argument", res["error"])

        # Test valid write_file
        res_valid = registry.execute("read_file", {})
        self.assertIn("error", res_valid)
        self.assertIn("missing required argument", res_valid["error"])


if __name__ == "__main__":
    unittest.main()

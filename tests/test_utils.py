import os
import sys
import unittest
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from utils import fix_json, extract_json


class TestFixJson(unittest.TestCase):
    def test_valid_json_unchanged(self):
        data = '{"a": 1, "b": "hello"}'
        result = fix_json(data)
        self.assertEqual(json.loads(result), {"a": 1, "b": "hello"})

    def test_newlines_in_string(self):
        data = '{"a": "line1\nline2\nline3"}'
        result = fix_json(data)
        self.assertIn("\\n", result)
        parsed = json.loads(result)
        self.assertEqual(parsed["a"], "line1\nline2\nline3")

    def test_tabs_in_string(self):
        data = '{"a": "col1\tcol2"}'
        result = fix_json(data)
        self.assertIn("\\t", result)

    def test_backslash_before_non_special(self):
        data = '{"hash": "\\$6\\$rounds=65636"}'
        result = fix_json(data)
        parsed = json.loads(result)
        self.assertEqual(parsed["hash"], "$6$rounds=65636")

    def test_braces_trim_extra_text(self):
        data = 'some prefix text {"a": 1} some suffix'
        result = fix_json(data)
        self.assertEqual(result, '{"a": 1}')

    def test_braces_trim_leading_text(self):
        data = 'Explanation: {"b": 2}'
        result = fix_json(data)
        self.assertEqual(result, '{"b": 2}')

    def test_nested_braces_trim(self):
        data = 'here {"a": {"b": [1, 2]}} there'
        result = fix_json(data)
        self.assertEqual(result, '{"a": {"b": [1, 2]}}')

    def test_no_braces(self):
        data = "just text no braces"
        result = fix_json(data)
        self.assertEqual(result, data)


class TestExtractJson(unittest.TestCase):
    def test_simple_json(self):
        data = '{"a": 1}'
        result = extract_json(data)
        self.assertEqual(json.loads(result), {"a": 1})

    def test_from_markdown_code_block(self):
        data = '```json\n{"a": 1}\n```'
        result = extract_json(data)
        self.assertEqual(json.loads(result), {"a": 1})

    def test_json_with_unmatched_inner_braces(self):
        data = '{"a": {"b": 2}}'
        result = extract_json(data)
        self.assertEqual(json.loads(result), {"a": {"b": 2}})

    def test_json_with_newlines(self):
        data = '{\n  "a": 1,\n  "b": "hello"\n}'
        result = extract_json(data)
        self.assertEqual(json.loads(result), {"a": 1, "b": "hello"})

    def test_text_before_after(self):
        data = 'Some response text {"filesystem": {}, "command_output": "ok"} trailing'
        result = extract_json(data)
        self.assertEqual(json.loads(result), {"filesystem": {}, "command_output": "ok"})

    def test_malformed_fallback(self):
        data = '{"broken'
        result = extract_json(data)
        self.assertIn(result, (data, '{"broken'))

    def test_array_at_top_level(self):
        data = "[1, 2, 3]"
        result = extract_json(data)
        self.assertEqual(json.loads(result), [1, 2, 3])

    def test_empty_string(self):
        result = extract_json("")
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "av_rsvp"


class Metadata(unittest.TestCase):
    def test_doctype_controllers_fields_and_links(self):
        doctypes = {json.loads(p.read_text())["name"]: p for p in ROOT.glob("rsvp/doctype/*/*.json")}
        for name, path in doctypes.items():
            doc = json.loads(path.read_text())
            self.assertEqual(doc["module"], "RSVP")
            self.assertEqual(set(doc["field_order"]), {f["fieldname"] for f in doc["fields"]})
            expected = name.replace(" ", "").replace("-", "")
            classes = [
                n.name
                for n in ast.parse(path.with_suffix(".py").read_text()).body
                if isinstance(n, ast.ClassDef)
            ]
            self.assertIn(expected, classes, name)
            for field in doc["fields"]:
                if field["fieldtype"] in {"Link", "Table"} and field.get("options", "").startswith("RSVP"):
                    self.assertIn(field["options"], doctypes)

    def test_navigation_targets_exist(self):
        available = {}
        for path in ROOT.rglob("*.json"):
            value = json.loads(path.read_text())
            if isinstance(value, dict) and value.get("name"):
                available.setdefault(value["doctype"], set()).add(value["name"])
        sidebar = json.loads((ROOT / "rsvp/sidebar/rsvp/rsvp.json").read_text())
        for item in sidebar["items"]:
            if item["type"] == "Link":
                self.assertIn(item["link_to"], available[item["link_type"]])
        dock = json.loads((ROOT / "dock/av_rsvp/av_rsvp.json").read_text())
        self.assertEqual(dock["items"][0]["link_to"], sidebar["name"])

    def test_no_guest_document_permissions_or_operational_writes(self):
        for path in ROOT.glob("rsvp/doctype/*/*.json"):
            doc = json.loads(path.read_text())
            for permission in doc["permissions"]:
                self.assertNotEqual(permission["role"], "Guest")
                if doc["name"] in {
                    "RSVP Attendee",
                    "RSVP Function Response",
                    "RSVP Check-in",
                    "RSVP Message Log",
                }:
                    self.assertFalse(permission.get("write"))
                    self.assertFalse(permission.get("create"))

    def test_mutating_api_endpoints_only_accept_post(self):
        tree = ast.parse((ROOT / "api.py").read_text())
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "whitelist"
                ):
                    keywords = {kw.arg: ast.literal_eval(kw.value) for kw in decorator.keywords}
                    self.assertEqual(keywords.get("methods"), ["POST"], node.name)


if __name__ == "__main__":
    unittest.main()

"""Offline safety/packaging tests: never send input, activate apps or capture chats."""
import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


ui = module("wechat_ui", ROOT / "skills/wechat-desktop/scripts/wechat_ui.py")
audit = module("public_audit", ROOT / "scripts/check_public_tree.py")


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.temp.name)
        ui.keyboard_path(self.runtime).parent.mkdir(parents=True)
        ui.keyboard_path(self.runtime).touch()
        (self.runtime / "wechat-capture").touch()

    def tearDown(self):
        self.temp.cleanup()

    def typing(self, text, action):
        args = argparse.Namespace(command="type", stdin=True, file=None)
        stream = io.TextIOWrapper(io.BytesIO(text.encode()), encoding="utf-8")
        with patch.object(ui.sys, "stdin", stream), patch.object(ui, "run_json", side_effect=action):
            ui.dispatch(args, self.runtime)

    def test_control_input_rejected_before_posting(self):
        for text in ["a\nb", "a\tb", "a\rb", "a\x00b", "a\u2028b", "x" * 201, ""]:
            with self.subTest(text=repr(text)), patch.object(ui, "run_json") as run:
                with self.assertRaises(ValueError):
                    self.typing(text, run)
                run.assert_not_called()

    def test_private_text_deleted_on_success_and_failure(self):
        for fail in [False, True]:
            seen = []

            def action(argv):
                path = Path(argv[-1])
                seen.append(path)
                self.assertEqual(path.read_text(), "Synthetic test message")
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                if fail:
                    raise RuntimeError("test failure")
                return {"posted": True}

            with patch.object(ui, "emit") as emit:
                if fail:
                    with self.assertRaises(RuntimeError):
                        self.typing("Synthetic test message", action)
                else:
                    self.typing("Synthetic test message", action)
                    self.assertNotIn("Synthetic test message", str(emit.call_args))
            self.assertTrue(seen)
            self.assertTrue(all(not p.exists() for p in seen))

    def test_activation_requires_foreground_authorization_flag(self):
        args = argparse.Namespace(command="activate", allow_foreground=False)
        with patch.object(ui.subprocess, "run") as run, patch.object(ui, "run_json") as inspect:
            with self.assertRaises(ValueError):
                ui.dispatch(args, self.runtime)
            run.assert_not_called()
            inspect.assert_not_called()

    def test_runtime_rejects_git_tree(self):
        (self.runtime / ".git").mkdir()
        with patch.dict(os.environ, {"WECHAT_AGENT_RUNTIME": str(self.runtime / "private")}):
            with self.assertRaises(ValueError):
                ui.runtime_path()
        self.assertFalse((self.runtime / "private").exists())

    def test_public_scan_blocks_data_and_credentials(self):
        self.assertTrue(audit.inspect("data/chat.txt", b"synthetic"))
        self.assertTrue(audit.inspect("docs/demo.png", b"not actually a png"))
        self.assertTrue(audit.inspect("docs/example.md", b"SQLite\0binary"))
        for token in [b"AIza" + b"a" * 35, b"ghp_" + b"a" * 35,
                      b"wxid_" + b"a" * 16, b"/Users/" + b"synthetic/private"]:
            self.assertTrue(audit.inspect("docs/example.md", token))
        self.assertEqual(audit.inspect("docs/example.md", b"Synthetic public documentation"), [])


if __name__ == "__main__":
    unittest.main()

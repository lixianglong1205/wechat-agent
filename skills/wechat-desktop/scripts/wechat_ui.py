#!/usr/bin/env python3
"""Build and run local WeChat UI primitives; no network, DB access or send loop."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
BUNDLE_ID = "org.rebyte.wechatagent.keyboard"
APP_NAME = "WeChat Agent Keyboard.app"


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def runtime_path():
    path = Path(os.environ.get(
        "WECHAT_AGENT_RUNTIME",
        str(Path.home() / "Library/Application Support/WeChatAgent/desktop"),
    )).expanduser()
    if not path.is_absolute():
        raise ValueError("WECHAT_AGENT_RUNTIME must be an absolute private path")
    path = path.resolve()
    # Reject output inside the installed skill, its source checkout, or any Git tree.
    if path == SKILL or SKILL in path.parents:
        raise ValueError("Runtime must be outside the skill")
    for ancestor in [path, *path.parents]:
        if (ancestor / ".git").exists():
            raise ValueError("Runtime must be outside all Git repositories")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != os.getuid():
        raise ValueError("Runtime must belong to the current user")
    path.chmod(0o700)
    return path


def keyboard_path(runtime):
    return runtime / APP_NAME / "Contents/MacOS/WeChatKeyboard"


def run_json(argv):
    result = subprocess.run([str(x) for x in argv], text=True, capture_output=True)
    if result.returncode:
        # Our tools log state/errors only, never the supplied message text.
        raise RuntimeError(result.stdout.strip() or result.stderr.strip() or "Tool failed")
    return json.loads(result.stdout)


def build(runtime):
    if shutil.which("xcrun") is None:
        raise RuntimeError("Install Xcode Command Line Tools first")
    compiler = subprocess.check_output(["xcrun", "swiftc", "--version"], text=True)
    fingerprint = hashlib.sha256()
    fingerprint.update(compiler.encode())
    fingerprint.update(Path(__file__).read_bytes())
    for path in sorted((HERE / "swift").glob("*.swift")):
        fingerprint.update(path.name.encode())
        fingerprint.update(path.read_bytes())
    stamp = fingerprint.hexdigest()
    manifest = runtime / "build.json"
    capture = runtime / "wechat-capture"
    keyboard = keyboard_path(runtime)
    if manifest.exists():
        previous = json.loads(manifest.read_text())
        if previous.get("fingerprint") == stamp and keyboard.exists() and capture.exists():
            emit({"built": True, "reused": True, "app": str(runtime / APP_NAME),
                  "runtime": str(runtime)})
            return

    # Compile fully before replacing our own old build. Never touch WeChat.app.
    with tempfile.TemporaryDirectory(prefix="build-", dir=runtime) as temp:
        stage = Path(temp)
        app = stage / APP_NAME
        executable = app / "Contents/MacOS/WeChatKeyboard"
        executable.parent.mkdir(parents=True)
        info = {
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleName": "WeChat Agent Keyboard",
            "CFBundleDisplayName": "WeChat Agent Keyboard",
            "CFBundleExecutable": "WeChatKeyboard",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "1",
            "LSUIElement": True,
            "NSAccessibilityUsageDescription": "Perform user-requested keyboard actions in WeChat.",
        }
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
        subprocess.run(["xcrun", "swiftc", "-swift-version", "5", "-O",
                        str(HERE / "swift/WeChatKeyboard.swift"), "-o", str(executable)], check=True)
        subprocess.run(["xcrun", "swiftc", "-parse-as-library", "-swift-version", "5", "-O",
                        str(HERE / "swift/WeChatCaptureProbe.swift"), "-o", str(stage / "wechat-capture")], check=True)
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", "--identifier",
                        BUNDLE_ID, str(app)], check=True)
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(app)], check=True)
        destination = runtime / APP_NAME
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(app), destination)
        os.replace(stage / "wechat-capture", capture)
        manifest.write_text(json.dumps({"fingerprint": stamp, "compiler": compiler.strip()}, indent=2))
        manifest.chmod(0o600)
    emit({"built": True, "reused": False, "app": str(runtime / APP_NAME),
          "runtime": str(runtime), "note": "Check macOS permissions for this build before input"})


def status(runtime):
    return {**run_json([keyboard_path(runtime), "status"]),
            **run_json([runtime / "wechat-capture", "--status"]),
            "app": str(runtime / APP_NAME), "runtime": str(runtime)}


def dispatch(args, runtime):
    if args.command == "build":
        return build(runtime)
    if not keyboard_path(runtime).exists() or not (runtime / "wechat-capture").exists():
        raise RuntimeError("Run build first")
    if args.command == "status":
        emit(status(runtime))
    elif args.command == "activate":
        if not args.allow_foreground:
            raise ValueError("activate requires --allow-foreground for an authorized foreground task")
        current = run_json([keyboard_path(runtime), "status"])
        if current["wechatInstances"] != 1:
            raise ValueError("Expected exactly one already-running WeChat process")
        subprocess.run(["/usr/bin/open", "-b", "com.tencent.xinWeChat"], check=True)
        emit({"activationRequested": True, "note": "Verify fresh screenshot and status"})
    elif args.command == "capture":
        if args.request_permission:
            emit(run_json([runtime / "wechat-capture", "--request-permission"]))
            return
        run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        folder = runtime / "captures" / run_id
        result = subprocess.run([str(runtime / "wechat-capture"), str(folder)])
        if result.returncode:
            raise RuntimeError("Capture failed; inspect preceding status; no keyboard input sent")
    elif args.command == "type":
        if args.stdin:
            data = sys.stdin.buffer.read(8193)
        else:
            with Path(args.file).open("rb") as handle:
                data = handle.read(8193)
        if len(data) > 8192:
            raise ValueError("Input too large")
        text = data.decode("utf-8")
        if not text or len(text) > 200 or any(ord(c) < 32 or ord(c) == 127 or c in "\u2028\u2029" for c in text):
            raise ValueError("Input must be 1-200 characters, one line, without control characters")
        # No text in argv/logs; private transient UTF-8 file is removed on every exit.
        fd, name = tempfile.mkstemp(prefix="input-", suffix=".txt", dir=runtime)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            emit(run_json([keyboard_path(runtime), "type", name]))
        finally:
            Path(name).unlink(missing_ok=True)
    else:
        emit(run_json([keyboard_path(runtime), args.command]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ["build", "status", "search", "select-all", "enter", "escape", "tab", "down", "up"]:
        commands.add_parser(name)
    activate = commands.add_parser("activate")
    activate.add_argument("--allow-foreground", action="store_true")
    capture = commands.add_parser("capture")
    capture.add_argument("--request-permission", action="store_true")
    typing = commands.add_parser("type")
    source = typing.add_mutually_exclusive_group(required=True)
    source.add_argument("--stdin", action="store_true")
    source.add_argument("--file")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if platform.system() != "Darwin":
            raise RuntimeError("This skill requires macOS")
        runtime = runtime_path()
        with (runtime / "operation.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            dispatch(args, runtime)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        emit({"error": str(error)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

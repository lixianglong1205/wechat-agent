#!/usr/bin/env python3
"""Check the exact staged bytes before publishing. Reports paths, not secret values."""
import re
import subprocess
import sys
from pathlib import PurePosixPath

ROOT_FILES = {"README.md", "LICENSE", ".gitignore"}
PREFIXES = ("docs/", "diagnostics/", "skills/wechat-desktop/", "scripts/", "tests/")
TEXT_SUFFIXES = {".md", ".py", ".swift", ".sh", ".yaml", ".yml"}
PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    "API credential": re.compile(rb"(?:AIza[0-9A-Za-z_-]{30,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{24,})"),
    "personal home path": re.compile(rb"/Users/(?!<|example\b)[A-Za-z0-9_.-]+/"),
    "WeChat account ID": re.compile(rb"wxid_[A-Za-z0-9]{5,}"),
    "personal tailnet address": re.compile(rb"[A-Za-z0-9-]+\.[A-Za-z0-9-]+\.ts\.net"),
    "email address": re.compile(rb"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "database key value": re.compile(rb'''["'](?:enc_key|raw_key|password|api_key)["']\s*:\s*["'][A-Za-z0-9+/=_-]{8,}["']'''),
}


def inspect(name, data):
    problems = []
    path = PurePosixPath(name)
    if name not in ROOT_FILES and (not name.startswith(PREFIXES) or path.suffix not in TEXT_SUFFIXES):
        problems.append("not in public source allowlist")
    if any(part in {"data", "backups", "captures", "objects", ".env", "runtime", "__pycache__"} for part in path.parts):
        problems.append("private/generated directory")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        problems.append("non-text content")
    if b"\0" in data:
        problems.append("binary content")
    if len(data) > 500_000:
        problems.append("unexpectedly large file")
    for label, pattern in PATTERNS.items():
        if pattern.search(data):
            problems.append(label)
    return problems


def main():
    raw = subprocess.check_output(["git", "ls-files", "--stage", "-z"])
    failures = []
    count = 0
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        header, raw_name = entry.split(b"\t", 1)
        mode, oid, stage = header.decode().split()
        name = raw_name.decode()
        count += 1
        if mode not in {"100644", "100755"} or stage != "0":
            failures.append((name, ["non-regular or conflicted index entry"]))
            continue
        data = subprocess.check_output(["git", "cat-file", "blob", oid])
        problems = inspect(name, data)
        if problems:
            failures.append((name, problems))
    if not count:
        print("No staged/tracked files to audit", file=sys.stderr)
        return 2
    for name, problems in failures:
        print(f"BLOCKED {name}: {', '.join(problems)}", file=sys.stderr)
    if failures:
        return 1
    print(f"Checked {count} indexed files: source allowlist, text-only, private-data patterns passed.")
    print("Pattern checks supplement manual review; they cannot recognize every private chat or secret.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

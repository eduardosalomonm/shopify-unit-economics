"""Fail closed on common private files/secrets in the public distribution.

Standard-library only. Reports file names and finding types, never matched values.
This is a release guard, not a guarantee that all possible PII can be recognized.
"""

import argparse
import io
from pathlib import Path
import re
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "provider credential": re.compile(rb"(?:shpat_|shpss_|gh[pousr]_)[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9_-]{30,}"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "personal filesystem path": re.compile(rb"/Users/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/"),
}
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def private_path(name):
    path = Path(name)
    lowered_name = path.name.casefold()
    lowered_parts = {part.casefold() for part in path.parts}
    return ((lowered_name.startswith(".env") and lowered_name != ".env.example")
            or path.suffix.casefold() in (".token", ".pem", ".key", ".db", ".sqlite", ".sqlite3")
            or lowered_name in ("costs.yml", "costs.private.json", "panel.html")
            or bool({"tuara", "output", "outputs", ".git"} & lowered_parts)
            or "data" in lowered_parts)


def content_findings(data):
    findings = secret_findings(data)
    if any(not (domain.lower().endswith(b".example") or domain.lower() in
                (b"example.com", b"example.org", b"example.net"))
           for domain in EMAIL.findall(data)):
        findings.append("non-example email address")
    return findings


def secret_findings(data):
    """Find credential-like material without treating normal Git trailers as PII."""
    return [label for label, pattern in PATTERNS.items() if pattern.search(data)]


def inspect_file(name, data):
    findings = ["private path"] if private_path(name) else []
    findings.extend(content_findings(data))
    suffix = Path(name).suffix.casefold()
    if suffix in (".xlsm", ".xltm"):
        findings.append("macro-enabled workbook")
    if suffix in (".xlsx", ".xlsm", ".xltx", ".xltm"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as workbook:
                if any("vbaproject" in n.lower() or "externallinks/" in n.lower()
                       for n in workbook.namelist()):
                    findings.append("workbook macro/external link")
                for member in workbook.namelist():
                    if member.endswith((".xml", ".rels")):
                        findings.extend(content_findings(workbook.read(member)))
        except zipfile.BadZipFile:
            findings.append("invalid workbook")
    return sorted(set(findings))


def inspect_worktree_path(root, name):
    """Inspect one public-package entry without following symbolic links."""
    path = root / name
    if path.is_symlink():
        return ["symlink not allowed in public package"]
    if not path.is_file():
        return []
    return inspect_file(name, path.read_bytes())


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="also inspect all reachable Git blobs")
    args = parser.parse_args()
    failed = False
    files = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")
    for raw in sorted(set(files)):
        if not raw:
            continue
        name = raw.decode("utf-8", "surrogateescape")
        findings = inspect_worktree_path(ROOT, name)
        for finding in findings:
            print("BLOCKED: %s: %s" % (name, finding))
            failed = True
    if args.history:
        for entry in git("rev-list", "--objects", "--all").decode(
                "utf-8", "surrogateescape").splitlines():
            oid, _, name = entry.partition(" ")
            if not name or git("cat-file", "-t", oid).strip() != b"blob":
                continue
            for finding in inspect_file(name, git("cat-file", "blob", oid)):
                print("BLOCKED history %s: %s: %s" % (oid[:12], name, finding))
                failed = True
        metadata = b"\n".join((
            git("log", "--all", "--format=%B%x00"),
            git("for-each-ref", "refs/tags", "--format=%(contents)%00"),
        ))
        # Commit bodies commonly carry public co-author email trailers. Scan Git
        # messages for credentials, keys and personal paths; file content keeps
        # the stricter non-example email rule.
        for finding in secret_findings(metadata):
            print("BLOCKED Git commit/tag messages: %s" % finding)
            failed = True
    print("Public release privacy guard: %s" % ("FAIL" if failed else "PASS"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

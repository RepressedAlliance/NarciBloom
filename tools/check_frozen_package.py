"""Verify an existing CI Fonts artifact and extract it for a startup-only check.

This does not build or run the application. The smoke workflow separately runs
check_frozen_startup.py on the launcher recorded in the resulting report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import sys
import urllib.request
import zipfile


def verify_run(repository, run_id, revision):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid GitHub repository")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected a complete lowercase source revision")
    if not str(run_id).isdigit() or int(run_id) <= 0:
        raise ValueError("Invalid package run ID")
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError("GH_TOKEN is required for the package run lookup")
    url = f"https://api.github.com/repos/{repository}/actions/runs/{int(run_id)}"
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        run = json.load(response)
    if (run.get("head_sha") != revision
            or run.get("path") != ".github/workflows/packages.yml"
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"):
        raise ValueError("Package run is not a successful packages.yml build of the expected revision")
    return {"id": int(run_id), "source_revision": run["head_sha"],
            "workflow": run["path"], "url": run["html_url"]}


def prepare(packages, destination, revision, platform):
    """Validate the downloaded manifest, ZIP paths and embedded build identity."""
    packages, destination = Path(packages).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError("Choose a new extraction directory")
    archives = list(packages.glob("*-Fonts.zip"))
    if len(archives) != 1:
        raise ValueError("Expected exactly one Fonts ZIP")
    archive = archives[0]
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    products = json.loads((packages / "artifacts.json").read_text(encoding="utf-8"))
    matches = [item for item in products if item.get("filename") == archive.name]
    if (len(matches) != 1 or matches[0].get("sha256") != digest
            or matches[0].get("size_bytes") != archive.stat().st_size):
        raise ValueError("Fonts ZIP differs from artifacts.json")
    checksum_rows = []
    for line in (packages / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError("Invalid SHA256SUMS.txt row")
        if match[2] == archive.name:
            checksum_rows.append(match[1])
    if checksum_rows != [digest]:
        raise ValueError("Fonts ZIP differs from SHA256SUMS.txt")

    launcher_name = "NarciBloom.exe" if platform == "win32" else "NarciBloom"
    expected_platform = "win32" if platform == "win32" else "linux"
    with zipfile.ZipFile(archive) as container:
        members, folded, roots = [], set(), set()
        total = 0
        for info in container.infolist():
            path = PurePosixPath(info.filename)
            parts = info.filename.split("/")
            if (info.orig_filename != info.filename or not info.filename
                    or "\\" in info.filename or path.is_absolute()
                    or any(not part or part in (".", "..")
                           or part.endswith((".", " "))
                           or any(ord(c) < 32 or c in ':*?"<>|' for c in part)
                           or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
                           for part in parts)
                    or info.filename.casefold() in folded
                    or info.is_dir() or info.flag_bits & 1
                    or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)):
                raise ValueError("Unsafe or duplicate package ZIP member")
            total += info.file_size
            if len(members) >= 10000 or total > 1024 * 1024 * 1024:
                raise ValueError("Package ZIP exceeds extraction bounds")
            roots.add(parts[0]);folded.add(info.filename.casefold());members.append(info)
        if len(roots) != 1:
            raise ValueError("Expected one portable package root")
        root = roots.pop()
        if root != archive.stem:
            raise ValueError("Portable folder and archive names differ")
        identity = json.loads(container.read(root + "/build-info.json"))
        if (identity.get("source_revision") != revision
                or identity.get("source_has_uncommitted_changes") is not False
                or identity.get("platform") != expected_platform):
            raise ValueError("Frozen build-info is not the expected clean source/platform")
        launcher = container.read(root + "/" + launcher_name)
        if platform == "win32":
            if (len(launcher) < 64 or launcher[:2] != b"MZ"):
                raise ValueError("Expected a Windows launcher")
            pe_at = struct.unpack_from("<I", launcher, 60)[0]
            if (pe_at + 6 > len(launcher) or launcher[pe_at:pe_at + 4] != b"PE\0\0"
                    or struct.unpack_from("<H", launcher, pe_at + 4)[0] != 0x8664):
                raise ValueError("Expected an x86-64 Windows launcher")
        elif (len(launcher) < 20 or launcher[:6] != b"\x7fELF\x02\x01"
              or struct.unpack_from("<H", launcher, 18)[0] != 62):
            raise ValueError("Expected an x86-64 Linux ELF launcher")
        # All paths and identities are checked before the first extraction write.
        destination.mkdir(parents=True)
        for info in members:
            target = destination.joinpath(*PurePosixPath(info.filename).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(container.read(info))
    executable = destination / root / launcher_name
    if platform != "win32":
        executable.chmod(0o755)
    return {"archive": archive.name, "sha256": digest,
            "size_bytes": archive.stat().st_size, "extracted_files": len(members),
            "build_info": identity, "launcher": str(executable)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--report", type=Path, required=True)
    options = parser.parse_args(argv)
    report = {"ok": False}
    try:
        report["run"] = verify_run(options.repository, options.run_id, options.source_revision)
        report["package"] = prepare(options.packages, options.output,
                                    options.source_revision, sys.platform)
        report["ok"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

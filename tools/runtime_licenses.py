"""Inventory Linux runtime origins and copy installed package notices.

This collects evidence, not a legal-compliance verdict. It does not download
sources or establish LGPL relinking/source-offer compliance. Run on the build
host after PyInstaller: its Analysis TOC is the preferred origin evidence.
"""
from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import sysconfig

LINUX_LIBRARY_EXCEPTIONS = ("libtcl*.so*", "libtk*.so*", "libffi.so*", "libcrypto.so*", "libssl.so*")
COMMON_ROOTS = (Path("/usr/share/licenses/common"), Path("/usr/share/common-licenses"))
SHARE_ROOT = Path("/usr/share")
SYSTEM_LIBRARY_ROOTS = ("/lib", "/lib64", "/usr/lib", "/usr/lib64")


def filter_linux_binaries(binaries):
    """Keep Python/extensions and selected permissive runtimes; use host system libraries.

    Assign the returned list to Analysis.binaries before EXE/COLLECT. This changes
    the product to require a compatible host such as the tested SteamOS version;
    it does not make a portable binary for arbitrary Linux distributions.
    """
    result = []
    for entry in binaries:
        destination, source, kind = entry
        name = PurePosixPath(destination).name
        system = any(source == root or source.startswith(root + "/") for root in SYSTEM_LIBRARY_ROOTS)
        keep = (kind == "EXTENSION" or not system or name.startswith("libpython")
                or "/lib-dynload/" in "/" + destination
                or any(fnmatch.fnmatchcase(name, pattern) for pattern in LINUX_LIBRARY_EXCEPTIONS))
        if keep:
            result.append(entry)
    return result


def _run(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, errors="replace", timeout=30,
                            env={**os.environ, "LC_ALL": "C"})
    return result.returncode, result.stdout


class _PackageDatabase:
    def __init__(self, manager):
        self.manager = manager

    def owner(self, source):
        if self.manager == "pacman":
            code, text = _run(["pacman", "-Qoq", str(source)])
            return text.strip().splitlines()[0] if code == 0 and text.strip() else None
        code, text = _run(["dpkg-query", "-S", str(source)])
        if code == 0:
            for line in text.splitlines():
                if ": " in line:
                    package, listed_path = line.rsplit(": ", 1)
                    if listed_path == str(source) and ", " not in package:
                        return package
        return None

    def details(self, package):
        if self.manager == "pacman":
            code, text = _run(["pacman", "-Qi", package])
            if code:
                raise RuntimeError(f"Cannot read installed package metadata: {package}")
            fields = dict((key.strip(), value.strip()) for key, value in
                          re.findall(r"^([^\n:]+):[ \t]*(.*)$", text, re.M))
            code, listing = _run(["pacman", "-Qlq", package])
            if code:
                raise RuntimeError(f"Cannot list installed package files: {package}")
            return {"name": package, "version": fields.get("Version"),
                    "declared_licenses": fields.get("Licenses", ""),
                    "source_package": None, "source_version": None,
                    "package_files": listing.splitlines()}
        code, text = _run(["dpkg-query", "-W", "-f=${Version}\t${source:Package}\t${source:Version}\n", package])
        if code:
            raise RuntimeError(f"Cannot read installed package metadata: {package}")
        fields = text.rstrip("\n").split("\t")
        if len(fields) != 3:
            raise RuntimeError(f"Unexpected package metadata: {package}")
        code, listing = _run(["dpkg-query", "-L", package])
        if code:
            raise RuntimeError(f"Cannot list installed package files: {package}")
        return {"name": package, "version": fields[0], "declared_licenses": "",
                "source_package": fields[1] or package.split(":")[0],
                "source_version": fields[2] or fields[0], "package_files": listing.splitlines()}


def _database():
    for manager, executable in (("pacman", "pacman"), ("dpkg", "dpkg-query")):
        if shutil.which(executable):
            return _PackageDatabase(manager)
    return None


def _analysis_origins(internal):
    package = internal.parent if internal.name == "_internal" else internal
    if package.parent.name != "frozen":
        return {}
    toc = package.parent.parent / "pyinstaller" / package.name / "Analysis-00.toc"
    if not toc.is_file():
        return {}
    try:
        contents = ast.literal_eval(toc.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError, UnicodeError) as exc:
        raise ValueError("Cannot parse the build's PyInstaller Analysis TOC") from exc
    origins = {}

    def walk(value):
        if not isinstance(value, (list, tuple)):
            return
        if (len(value) == 3 and all(isinstance(item, str) for item in value)
                and value[2] in {"BINARY", "EXTENSION"}):
            origins[value[0]] = Path(value[1])
        else:
            for item in value:
                walk(item)

    walk(contents)
    return origins


def _library_candidates(name):
    folders = {Path(root) for root in SYSTEM_LIBRARY_ROOTS}
    folders.update(Path(root) / "x86_64-linux-gnu" for root in SYSTEM_LIBRARY_ROOTS)
    extension_folder = sysconfig.get_config_var("DESTSHARED")
    if extension_folder:
        folders.add(Path(extension_folder))
    for folder in sorted(folders):
        path = folder / name
        if path.is_file():
            yield path
    loader = shutil.which("ldconfig")
    if loader:
        code, listing = _run([loader, "-p"])
        if code == 0:
            for line in listing.splitlines():
                match = re.match(r"\s*(\S+)\s+\([^)]*\)\s+=>\s+(\S+)", line)
                if match and match[1] == name and Path(match[2]).is_file():
                    yield Path(match[2])


def _checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _origin(path, relative, origins):
    source = origins.get(relative)
    if source is not None and source.is_file():
        return source, "pyinstaller-analysis"
    # Without the build TOC, a basename alone is insufficient provenance. Exact
    # bytes are required; patchelf-altered libraries need their original TOC.
    checksum = _checksum(path)
    for source in _library_candidates(path.name):
        if _checksum(source) == checksum:
            return source, "identical-installed-file"
    return None, None


def _provider_configs(provider_notices):
    result = []
    for value in provider_notices or ():
        if not isinstance(value, dict) or value.get("provider") != "CPython":
            raise ValueError("Only explicit CPython provider notices are supported")
        root = Path(value["source_root"]).resolve(strict=True)
        extensions = Path(value["stdlib_extension_root"]).resolve(strict=True)
        notice = Path(value["notice"]).resolve(strict=True)
        if not root.is_dir() or not extensions.is_dir() or not extensions.is_relative_to(root) or not notice.is_file():
            raise ValueError("CPython provider roots and notice must exist; extensions must be inside its source root")
        result.append({"provider": "CPython", "root": root, "extensions": extensions, "notice": notice})
    return result


def _provider_for(source, relative, providers):
    if source is None:
        return None
    actual = source.resolve(strict=True)
    destination = PurePosixPath(relative)
    if source.name != destination.name or actual.name != destination.name:
        return None
    for provider in providers:
        if not actual.is_relative_to(provider["root"]):
            continue
        within = actual.relative_to(provider["root"])
        if (within.parts[:-1] in (("lib",), ("lib64",))
                and re.fullmatch(r"libpython\d+\.\d+\.so(?:\.\d+)*", actual.name)):
            return provider
        extension = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*)\.cpython-(\d+)(?:-[A-Za-z0-9_-]+)?\.so", actual.name)
        target = re.fullmatch(r"python(\d+\.\d+)/lib-dynload/[^/]+", relative)
        if (actual.parent == provider["extensions"] and extension and target
                and extension[1] in sys.stdlib_module_names
                and extension[2] == target[1].replace(".", "")
                and provider["extensions"].parent.name == "python" + target[1]):
            return provider
    return None


def _notice_sources(package_files):
    for value in package_files:
        path = Path(value)
        try:
            relative = path.relative_to(SHARE_ROOT)
        except ValueError:
            continue
        if not path.is_file():
            continue
        if relative.parts[0] == "licenses" or (relative.parts[0] == "doc"
                and any(word in path.name.casefold() for word in ("license", "licence", "copying", "copyright", "notice"))):
            yield path


def _license_text(path):
    data = path.read_bytes()
    if path.suffix == ".gz":
        import gzip
        data = gzip.decompress(data)
    return data.decode("utf-8", errors="replace")


def _common_references(text, declared):
    references = set(re.findall(r"/usr/share/(?:common-licenses|licenses/common)/([A-Za-z0-9._+/-]+)", text))
    missing_identifiers = set()
    for token in re.findall(r"(?:LGPL|AGPL|GPL|GFDL|FDL)[A-Za-z0-9.+-]*", declared, re.I):
        upper = token.upper()
        match = re.match(r"(LGPL|AGPL|GPL|GFDL|FDL)-?(\d+)(?:\.(\d+))?", upper)
        if not match:
            missing_identifiers.add(token + " (version unspecified)")
            continue
        family, major, minor = match.groups()
        version = major + ("." + minor if minor and not (family in {"GPL", "AGPL"} and minor == "0") else "")
        family = "GFDL" if family == "FDL" else family
        aliases = {family + "-" + version, family + version}
        if family == "GFDL":
            aliases.add("FDL" + version)
        candidates = [root / alias for root in COMMON_ROOTS for alias in aliases]
        present = [candidate for candidate in candidates if candidate.exists()]
        if not present:
            missing_identifiers.add(token)
        else:
            for candidate in present:
                if candidate.is_file():
                    references.add(candidate.relative_to(next(root for root in COMMON_ROOTS if candidate.is_relative_to(root))).as_posix())
                else:
                    references.update(path.relative_to(next(root for root in COMMON_ROOTS if path.is_relative_to(root))).as_posix()
                                      for path in candidate.rglob("*") if path.is_file())
    found, missing = [], []
    for reference in sorted(references):
        if ".." in PurePosixPath(reference).parts:
            missing.append(reference)
            continue
        choices = [root / reference for root in COMMON_ROOTS]
        source = next((candidate for candidate in choices if candidate.is_file()), None)
        if source is not None:
            found.append(source)
        else:
            missing.append(reference)
    return found, sorted(set(missing) | missing_identifiers)


def _copy_notice(source, destination, relative):
    target = destination / relative
    if not target.resolve().is_relative_to(destination.resolve()):
        raise ValueError("Notice destination escapes the requested output directory")
    data = source.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != data:
        raise ValueError(f"Refusing to replace a different existing notice: {relative}")
    if not target.exists():
        target.write_bytes(data)
    return {"file": relative.as_posix(), "sha256": hashlib.sha256(data).hexdigest()}


def collect_native_notices(frozen_dir, notices_dir, *, provider_notices=None):
    """Copy installed Linux package copyright/notices and return a JSON report.

    Accept a frozen package root or its _internal directory. Missing origins,
    package-specific notices, and shared licenses are reported, never invented.
    The output lives under notices_dir/native plus native-runtime-report.json.
    Origin TOCs must come from the same build. This helper does not write sources,
    install packages, follow network links, or decide between alternative licenses.

    provider_notices may contain {'provider': 'CPython', 'source_root': ...,
    'stdlib_extension_root': ..., 'notice': ...}. Only traced libpython files or
    named stdlib extensions within those roots use this separately supplied notice;
    other unowned native libraries remain unresolved.
    """
    frozen = Path(frozen_dir).resolve(strict=True)
    internal = frozen / "_internal" if (frozen / "_internal").is_dir() else frozen
    providers = _provider_configs(provider_notices)
    destination = Path(notices_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    database = _database()
    origins = _analysis_origins(internal)
    report = {"schema": 1, "package_manager": database.manager if database else None,
              "files": [], "packages": [], "unresolved_files": [], "missing_notices": [],
              "source_review_required": [], "separately_supplied": [], "compliance_status": "not_assessed",
              "limitations": [
                  "Collecting license texts does not establish complete distribution compliance.",
                  "Corresponding source, source offers, and LGPL relinking obligations are not supplied or verified.",
                  "Package metadata can cover files not shipped; alternative licenses require a separate choice.",
              ]}
    grouped, provider_coverage = {}, {}
    for path in sorted(internal.rglob("*")):
        if not path.is_file() or ".so" not in path.name:
            continue
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                continue
        relative = path.relative_to(internal).as_posix()
        source, method = _origin(path, relative, origins)
        package = database.owner(source) if database and source is not None else None
        if package is None and database and source is not None and source.resolve() != source:
            package = database.owner(source.resolve())
        provider = _provider_for(source, relative, providers)
        if package is None and provider is None:
            report["unresolved_files"].append({"file": relative,
                "reason": "No matching installed package; obtain the interpreter/provider's notices and provenance separately."})
            continue
        item = {"file": relative, "package": package, "origin_method": method}
        if provider is not None:
            notice = _copy_notice(provider["notice"], destination, Path("native/providers/CPython/LICENSE.txt"))
            supplied = next((entry for entry in report["separately_supplied"] if entry["notice"] == notice), None)
            if supplied is None:
                supplied = {"provider": "CPython", "notice": notice, "files": []}
                report["separately_supplied"].append(supplied)
            supplied["files"].append(relative)
            provider_coverage[relative] = notice
            item.update({"notice_status": "separately_supplied", "provider": "CPython"})
        # Keep a portable report: do not publish a build user's home or venv path.
        if source.as_posix().startswith(("/usr/", "/lib/", "/lib64/")):
            item["system_source"] = source.as_posix()
        report["files"].append(item)
        if package is not None:
            grouped.setdefault(package, []).append(relative)
    for package, files in sorted(grouped.items()):
        details = database.details(package)
        sources = sorted(set(_notice_sources(details.pop("package_files"))))
        texts = "\n".join(_license_text(source) for source in sources)
        declared = details["declared_licenses"]
        if not declared:
            declared = " ; ".join(sorted(set(re.findall(r"^License:[ \t]*(.+)$", texts, re.M))))
            details["declared_licenses"] = declared
        copied = []
        label = re.sub(r"[^A-Za-z0-9._+-]", "_", package)
        for source in sources:
            relative = Path("native/packages") / label / source.relative_to(SHARE_ROOT)
            copied.append(_copy_notice(source, destination, relative))
        common_sources, missing_common = _common_references(texts, declared)
        for source in sorted(set(common_sources)):
            root = next(root for root in COMMON_ROOTS if source.is_relative_to(root))
            relative = Path("native/common") / source.relative_to(root)
            copied.append(_copy_notice(source, destination, relative))
        separately_supplied = all(relative in provider_coverage for relative in files)
        if not sources and separately_supplied:
            for relative in files:
                if provider_coverage[relative] not in copied:
                    copied.append(provider_coverage[relative])
            details["notice_status"] = "separately_supplied"
        elif not sources:
            report["missing_notices"].append({"package": package, "reason": "No package-specific notice installed"})
        if missing_common:
            report["missing_notices"].append({"package": package, "missing_shared_licenses": missing_common})
        markers = sorted(set(re.findall(r"\b(?:AGPL|LGPL|GPL|MPL)(?:[- .v]*\d+(?:\.\d+)*)?(?:-or-later|-only)?\b",
                                        declared + "\n" + texts, re.I)))
        if "lesser general public license" in texts.casefold() and not any("LGPL" in value.upper() for value in markers):
            markers.append("LGPL (license text)")
        if "gnu general public license" in texts.casefold() and not markers:
            markers.append("GPL (license text)")
        if markers:
            report["source_review_required"].append({"package": package, "markers": markers,
                "reason": "Review the specific shipped library, license alternatives/exceptions, corresponding source and relinking terms; not satisfied by these copied notices."})
        details.update({"files": files, "notices": copied, "missing_shared_licenses": missing_common})
        report["packages"].append(details)
    report["notice_collection_complete"] = not (report["unresolved_files"] or report["missing_notices"])
    (destination / "native-runtime-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report

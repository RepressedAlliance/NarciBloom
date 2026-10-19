"""Transactional installation of caller-built NarciBloom payloads.

The builder must recognize its source version and supply *only* the files it
intends to install, relative to the anthology root. This module neither builds
resources nor downloads DLC. Backups and transaction evidence stay in the local
game directory; they must never be shipped with a release or put in Git.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
import uuid

try:
    from .steam_discovery import STORY_TITLES, inspect_game
except ImportError:
    from steam_discovery import STORY_TITLES, inspect_game

STATE_DIR = ".narcibloom"
SCHEMA = 1
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_SAVE_SUFFIXES = {".sav", ".save", ".dat", ".ini", ".vms", ".srm", ".asd", ".ksd"}
_WINDOWS_RESERVED = re.compile(r"(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?\Z", re.I)


class InstallError(RuntimeError):
    """An installation could not safely proceed."""


class PathSafetyError(InstallError):
    pass


class GameRunningError(InstallError):
    def __init__(self, processes):
        self.processes = tuple(processes)
        super().__init__("Exit the game before changing its files: " + ", ".join(map(str, processes)))


class ConflictError(InstallError):
    def __init__(self, paths, message="Files changed after installation; preserved without overwriting"):
        self.paths = tuple(paths)
        super().__init__(message + ": " + ", ".join(self.paths))


def _relative(value: str) -> str:
    """One portable, canonical relative spelling; reject Windows hazards on Linux too."""
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise PathSafetyError(f"Invalid relative path: {value!r}")
    path = PurePosixPath(value)
    if (path.is_absolute() or PureWindowsPath(value).drive or str(path) != value
            or any(part in (".", "..") for part in path.parts)):
        raise PathSafetyError(f"Path escapes its root or is not canonical: {value!r}")
    for part in path.parts:
        if (any(ord(char) < 32 for char in part) or any(char in '<>:"|?*' for char in part)
                or part.endswith((" ", ".")) or _WINDOWS_RESERVED.fullmatch(part)):
            raise PathSafetyError(f"Nonportable path component: {part!r}")
    return value


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    if path.exists():
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    return False


def _safe_path(root: Path, relative: str) -> Path:
    relative = _relative(relative)
    current = root
    # Check root as well: state/backups must not be replaceable with a junction.
    if _is_link(root):
        raise PathSafetyError(f"Linked directory is not an installation target: {root}")
    for component in PurePosixPath(relative).parts:
        current = current / component
        if _is_link(current):
            raise PathSafetyError(f"Linked/reparse path is not allowed: {current}")
    if not current.resolve().is_relative_to(root.resolve()):
        raise PathSafetyError(f"Path escapes its root: {relative}")
    return current


def _target_relative(value: str) -> str:
    relative = _relative(value)
    parts = PurePosixPath(relative).parts
    if len(parts) < 2 or parts[0] not in STORY_TITLES:
        raise PathSafetyError("Payload paths must belong to a recognized story directory")
    if any(part.casefold().startswith("save") for part in parts[1:]):
        raise PathSafetyError(f"Save data is protected: {relative}")
    if PurePosixPath(relative).suffix.casefold() in _SAVE_SUFFIXES:
        raise PathSafetyError(f"Save/settings data is protected: {relative}")
    return relative


def _digest(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file() or _is_link(path):
        raise PathSafetyError(f"Expected an ordinary file: {path}")
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _atomic_copy(source: Path, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.narcibloom-{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as src, temporary.open("xb") as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        shutil.copystat(source, temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()  # Only the temporary file created by this call.


def _atomic_json(target: Path, value):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def running_game_processes(game_dir: Path) -> list[str]:
    """Conservatively check all known story executable names, including Wine.

    A same-named executable in a separate copy also blocks installation. Failure
    to enumerate processes raises instead of assuming that the game is stopped.
    """
    names = {f"{module}.exe" for module in STORY_TITLES}
    names.update(path.name.casefold() for path in game_dir.glob("*.exe"))
    if os.name == "nt":
        result = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                                text=True, errors="replace", check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        return [f"{row[0]} (PID {row[1]})" for row in csv.reader(io.StringIO(result.stdout))
                if len(row) >= 2 and row[0].casefold() in names]
    proc = Path("/proc")
    if not proc.is_dir():
        raise InstallError("Process enumeration requires /proc on this platform")
    matches = []
    for folder in proc.iterdir():
        if not folder.name.isdecimal():
            continue
        try:
            command = (folder / "cmdline").read_bytes().decode(errors="replace").split("\0")
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as exc:
            # Other users' processes cannot be the user's Steam/Wine children.
            if folder.stat().st_uid != os.getuid():
                continue
            raise InstallError(f"Cannot inspect process {folder.name}") from exc
        for argument in command:
            basename = argument.replace("\\", "/").rsplit("/", 1)[-1].casefold()
            if basename in names:
                matches.append(f"{basename} (PID {folder.name})")
                break
    return matches


class InstallManager:
    """Manage one game root with persistent originals and automatic rollback.

    ``process_checker`` is injectable for tests; production callers should keep
    the default. A file lock serializes cooperating installers. Users must keep
    the game closed during the operation; this cannot prevent Steam or another
    application from writing files outside the installer's lock.
    """

    def __init__(self, game_dir: str | Path, process_checker: Callable | None = None):
        self.game_dir = Path(game_dir).resolve(strict=True)
        if not self.game_dir.is_dir():
            raise PathSafetyError("Game root must be an existing directory")
        self.state = self.game_dir / STATE_DIR
        self._process_checker = process_checker or running_game_processes

    def _check_stopped(self):
        matches = self._process_checker(self.game_dir)
        if matches:
            raise GameRunningError(matches)

    @contextmanager
    def _locked(self):
        _safe_path(self.game_dir, STATE_DIR).mkdir(exist_ok=True)
        lock_path = _safe_path(self.state, "lock")
        with lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise InstallError("Another NarciBloom installer is using this game") from exc
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _json(self, name):
        path = _safe_path(self.state, name)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise InstallError(f"Invalid NarciBloom record: {path}") from exc

    def _validate_record(self, record):
        if record is None:
            return
        if (not isinstance(record, dict) or record.get("schema") != SCHEMA
                or record.get("game_root") != str(self.game_dir)
                or not isinstance(record.get("files"), dict)):
            raise InstallError("Unrecognized or mismatched installation record")
        seen = set()
        for relative, entry in record["files"].items():
            _target_relative(relative)
            if relative.casefold() in seen or not isinstance(entry, dict):
                raise InstallError("Duplicate or invalid installation record entry")
            seen.add(relative.casefold())
            if not _HASH.fullmatch(str(entry.get("installed_sha256", ""))):
                raise InstallError("Invalid installed file checksum")
            original = entry.get("original_sha256")
            if original is None:
                if entry.get("backup") is not None:
                    raise InstallError("Unexpected original backup")
            elif not _HASH.fullmatch(str(original)) or entry.get("backup") != f"backups/{original}":
                raise InstallError("Invalid original backup record")

    def read_record(self) -> dict | None:
        """Return a validated JSON-compatible installation record, or None."""
        record = self._json("record.json")
        self._validate_record(record)
        return record

    def original_file(self, relative: str) -> bytes | None:
        """Read the pre-install file without changing the game or installer state.

        Managed replacements read their checksum-verified original backup. Managed
        additions and missing unmanaged files return None. Other unmanaged files
        read from the current game directory. Pending transactions must first be
        recovered. This per-file API detects record changes while reading; callers
        constructing a multi-file baseline should keep other installers closed.
        """
        relative = _target_relative(relative)

        def ensure_no_pending():
            journal = self._json("transaction.json")
            if journal is not None and (not isinstance(journal, dict)
                                        or journal.get("status") == "pending"):
                raise InstallError("Recover the interrupted installation before reading original input")

        ensure_no_pending()
        record = self.read_record()
        entry = next((value for key, value in record["files"].items()
                      if key.casefold() == relative.casefold()), None) if record else None
        if entry is not None:
            source = self._original(entry)
            data = source.read_bytes() if source else None
            if data is not None and hashlib.sha256(data).hexdigest() != entry["original_sha256"]:
                raise InstallError("Original backup changed while reading")
        else:
            source = _safe_path(self.game_dir, relative)
            data = source.read_bytes() if source.is_file() else None
            if source.exists() and not source.is_file():
                raise PathSafetyError(f"Expected an ordinary file: {source}")
        ensure_no_pending()
        if self.read_record() != record:
            raise InstallError("Installation record changed while reading original input; retry")
        return data

    def update_metadata(self, metadata: dict) -> dict:
        """Replace caller metadata atomically, retaining version and all file records.

        No game files are copied/restored. For updating a package version use
        install() with its complete desired file set; unchanged hashes skip writes.
        """
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be a JSON object")
        metadata = json.loads(json.dumps(metadata))
        self._check_stopped()
        with self._locked():
            self._recover()
            record = self.read_record()
            if record is None:
                raise InstallError("There is no installation record to update")
            record["metadata"] = metadata
            _atomic_json(_safe_path(self.state, "record.json"), record)
            return record

    def _backup(self, source: Path, checksum: str) -> str:
        relative = f"backups/{checksum}"
        backup = _safe_path(self.state, relative)
        if not backup.exists():
            _atomic_copy(source, backup)
        if _digest(backup) != checksum:
            raise InstallError("Original backup checksum mismatch; game files were not changed")
        return relative

    def _original(self, entry):
        checksum = entry["original_sha256"]
        if checksum is None:
            return None
        source = _safe_path(self.state, entry["backup"])
        if _digest(source) != checksum:
            raise InstallError("Original backup is missing or modified; refusing restoration")
        return source

    def _unchanged(self, entries):
        conflicts = [relative for relative, entry in entries.items()
                     if _digest(_safe_path(self.game_dir, relative)) != entry["installed_sha256"]]
        if conflicts:
            raise ConflictError(conflicts)

    def install(self, payload_dir: str | Path, files: Iterable[str] | Mapping[str, str], *,
                version: str, metadata: dict | None = None) -> dict:
        """Install/reinstall/upgrade the complete desired file set.

        ``files`` is a sequence of relative paths, or a path->SHA-256 mapping.
        Passing a mapping additionally checks the caller's expected payload hashes.
        Omitted previously managed files are restored/removed as part of upgrade.
        All listed stories must already have executable AND archive data installed.
        metadata=None retains the previous metadata; a dict replaces it in full.
        """
        if not isinstance(version, str) or not version.strip():
            raise ValueError("A nonempty package version is required")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be a JSON object")
        json.dumps(metadata)  # Fail before any game-file changes.
        payload = Path(payload_dir).resolve(strict=True)
        if not payload.is_dir():
            raise PathSafetyError("Payload root must be a directory")
        expected = dict(files) if isinstance(files, Mapping) else None
        paths = list(files)
        if not paths:
            raise ValueError("An install must contain at least one explicit file")
        checked = [_target_relative(relative) for relative in paths]
        if len({relative.casefold() for relative in checked}) != len(checked):
            raise PathSafetyError("Duplicate/case-colliding payload paths")
        for relative in checked:
            if any(other.casefold().startswith(relative.casefold() + "/") for other in checked):
                raise PathSafetyError("Payload file/directory paths overlap")
        self._check_stopped()
        with self._locked():
            self._recover()
            info = inspect_game(self.game_dir)
            unavailable = [relative for relative in checked
                           if PurePosixPath(relative).parts[0] not in info.module_ids]
            if unavailable:
                raise ConflictError(unavailable, "Story files are not installed; no DLC will be installed")
            before = self.read_record()
            old_entries = before["files"] if before else {}
            old_spellings = {relative.casefold(): relative for relative in old_entries}
            if any(relative.casefold() in old_spellings
                   and old_spellings[relative.casefold()] != relative for relative in checked):
                raise PathSafetyError("An upgrade cannot change the case of a managed path")
            self._unchanged(old_entries)
            entries, operations = {}, []
            for relative in checked:
                source = _safe_path(payload, relative)
                checksum = _digest(source)
                if checksum is None:
                    raise InstallError(f"Missing payload file: {relative}")
                if expected is not None and checksum != expected[relative]:
                    raise InstallError(f"Payload checksum mismatch: {relative}")
                target = _safe_path(self.game_dir, relative)
                original_hash = _digest(target)
                if relative in old_entries:
                    entry = dict(old_entries[relative])
                    self._original(entry)  # Check retained originals even for a reinstall.
                else:
                    entry = {"original_sha256": original_hash,
                             "backup": self._backup(target, original_hash) if original_hash else None}
                entry["installed_sha256"] = checksum
                entries[relative] = entry
                operations.append((relative, original_hash, source, checksum))
            for relative, entry in old_entries.items():
                if relative not in entries:
                    operations.append((relative, entry["installed_sha256"], self._original(entry),
                                       entry["original_sha256"]))
            after = {"schema": SCHEMA, "game_root": str(self.game_dir), "version": version,
                     "metadata": (before.get("metadata", {}) if before else {}) if metadata is None else metadata,
                     "modules": sorted({p.split("/")[0] for p in checked}),
                     "files": entries}
            self._execute(operations, before, after)
            return after

    def uninstall(self) -> dict:
        """Restore originals/remove own additions only if all installed files match.

        A conflict aborts the entire operation. Backups/records remain available.
        Repeating an already completed uninstall is a no-op.
        """
        self._check_stopped()
        with self._locked():
            self._recover()
            before = self.read_record()
            if not before or not before["files"]:
                return {"restored": [], "removed": [], "already_uninstalled": True}
            self._unchanged(before["files"])
            operations, restored, removed = [], [], []
            for relative, entry in before["files"].items():
                source = self._original(entry)
                (restored if source else removed).append(relative)
                operations.append((relative, entry["installed_sha256"], source, entry["original_sha256"]))
            after = {"schema": SCHEMA, "game_root": str(self.game_dir), "version": None,
                     "metadata": {}, "modules": [], "files": {}}
            self._execute(operations, before, after)
            return {"restored": restored, "removed": removed, "already_uninstalled": False}

    def _execute(self, operations, before, after):
        transaction = f"transactions/{uuid.uuid4().hex}"
        journal = {"schema": SCHEMA, "game_root": str(self.game_dir), "status": "pending",
                   "before_record": before, "after_record": after, "operations": []}
        for index, (relative, before_hash, source, after_hash) in enumerate(operations):
            target = _safe_path(self.game_dir, relative)
            if _digest(target) != before_hash:
                raise ConflictError([relative])
            if before_hash == after_hash:
                continue
            before_file = f"{transaction}/before/{index}" if before_hash else None
            after_file = f"{transaction}/after/{index}" if after_hash else None
            if before_file:
                snapshot = _safe_path(self.state, before_file)
                _atomic_copy(target, snapshot)
                if _digest(snapshot) != before_hash:
                    raise ConflictError([relative], "File changed while taking rollback snapshot")
            if after_file:
                staged = _safe_path(self.state, after_file)
                _atomic_copy(source, staged)
                if _digest(staged) != after_hash:
                    raise InstallError(f"Payload changed while staging: {relative}")
            journal["operations"].append({"path": relative, "before_sha256": before_hash,
                                          "after_sha256": after_hash, "before_file": before_file,
                                          "after_file": after_file})
        journal_path = _safe_path(self.state, "transaction.json")
        self._check_stopped()
        _atomic_json(journal_path, journal)
        try:
            for operation in journal["operations"]:
                relative = operation["path"]
                target = _safe_path(self.game_dir, relative)
                if _digest(target) != operation["before_sha256"]:
                    raise ConflictError([relative])
                if operation["after_file"]:
                    _atomic_copy(_safe_path(self.state, operation["after_file"]), target)
                elif target.exists():
                    target.unlink()  # A tracked, unchanged addition only.
            changed = [operation["path"] for operation in journal["operations"]
                       if _digest(_safe_path(self.game_dir, operation["path"])) != operation["after_sha256"]]
            if changed:
                raise ConflictError(changed, "Files changed while committing installation")
            _atomic_json(_safe_path(self.state, "record.json"), after)
            journal["status"] = "committed"
            _atomic_json(journal_path, journal)
        except Exception as exc:
            try:
                self._recover()
            except Exception as recovery_error:
                raise InstallError(f"Installation failed; recovery needs attention: {recovery_error}") from exc
            raise

    def recover(self) -> dict:
        """Roll back a pending interrupted transaction, preserving outside changes."""
        self._check_stopped()
        with self._locked():
            return self._recover()

    def _recover(self) -> dict:
        journal = self._json("transaction.json")
        if journal is None:
            return {"recovered": False}
        if (not isinstance(journal, dict) or journal.get("schema") != SCHEMA
                or journal.get("game_root") != str(self.game_dir)
                or journal.get("status") not in {"pending", "committed", "rolled_back"}):
            raise InstallError("Invalid transaction journal; refusing automatic recovery")
        if journal["status"] != "pending":
            return {"recovered": False}
        self._check_stopped()
        self._validate_record(journal.get("before_record"))
        self._validate_record(journal.get("after_record"))
        if not isinstance(journal.get("operations"), list):
            raise InstallError("Invalid transaction operations")
        conflicts, plans, seen = [], [], set()
        for operation in journal["operations"]:
            if not isinstance(operation, dict):
                raise InstallError("Invalid transaction operation")
            relative = _target_relative(operation.get("path"))
            if relative.casefold() in seen:
                raise InstallError("Duplicate transaction path")
            seen.add(relative.casefold())
            for key in ("before_sha256", "after_sha256"):
                if operation.get(key) is not None and not _HASH.fullmatch(str(operation[key])):
                    raise InstallError("Invalid transaction checksum")
            target = _safe_path(self.game_dir, relative)
            current = _digest(target)
            before_hash, after_hash = operation.get("before_sha256"), operation.get("after_sha256")
            source = None
            if before_hash is not None:
                snapshot = operation.get("before_file")
                if not isinstance(snapshot, str) or not re.fullmatch(r"transactions/[0-9a-f]{32}/before/[0-9]+", snapshot):
                    raise InstallError("Invalid rollback snapshot path")
                source = _safe_path(self.state, snapshot)
                if _digest(source) != before_hash:
                    raise InstallError("Rollback snapshot is missing or modified")
            if current == before_hash:
                continue
            if current != after_hash:
                conflicts.append(relative)
            else:
                plans.append((relative, source, before_hash, after_hash))
        if conflicts:
            raise ConflictError(conflicts, "Interrupted transaction has later changes; automatic recovery stopped")
        for relative, source, before_hash, after_hash in reversed(plans):
            target = _safe_path(self.game_dir, relative)
            if _digest(target) != after_hash:
                raise ConflictError([relative], "File changed during recovery")
            if source is not None:
                _atomic_copy(source, target)
            elif target.exists():
                target.unlink()
        record = journal["before_record"]
        if record is None:
            record = {"schema": SCHEMA, "game_root": str(self.game_dir), "version": None,
                      "metadata": {}, "modules": [], "files": {}}
        _atomic_json(_safe_path(self.state, "record.json"), record)
        journal["status"] = "rolled_back"
        _atomic_json(_safe_path(self.state, "transaction.json"), journal)
        return {"recovered": True, "paths": [relative for relative, *_ in plans]}

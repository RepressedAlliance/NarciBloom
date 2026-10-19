"""Read-only discovery of locally installed Steam anthology stories.

No ownership is inferred from the app being present: only story directories with
their own executable and archive data are returned. This module never asks Steam
to install an app or DLC. A manifest is metadata, not proof that every DLC exists.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PureWindowsPath
import re

APP_ID = "426690"
STORY_TITLES = {
    "narci_onetwo": "Narcissu 1st & 2nd",
    "narci_himeko": "Himeko's Epilogue",
    "narci_iris": "A Little Iris",
    "narci_zero": "Narcissu Zero",
    "narci_sumire": "Sumire",
}


@dataclass(frozen=True)
class StoryInstallation:
    id: str
    title: str
    path: Path
    executable: Path
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class GameInstallation:
    path: Path
    modules: tuple[StoryInstallation, ...]
    manifest_path: Path | None = None
    build_id: str | None = None
    language: str | None = None
    installed_depots: tuple[str, ...] = ()
    missing_modules: tuple[str, ...] = ()

    @property
    def module_ids(self) -> tuple[str, ...]:
        return tuple(module.id for module in self.modules)


def parse_vdf(text: str) -> dict:
    """Parse the quoted/bare key-value subset used by Steam library manifests."""
    tokens = re.findall(r'//[^\n]*|"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+', text)
    tokens = [token for token in tokens if not token.startswith("//")]
    index = 0

    def value(token):
        if token.startswith('"'):
            if not token.endswith('"'):
                raise ValueError("Unterminated VDF string")
            return re.sub(r'\\([\\"])', r'\1', token[1:-1])
        return token

    def block(nested=False):
        nonlocal index
        result = {}
        while index < len(tokens):
            key = tokens[index]
            index += 1
            if key == "}":
                if not nested:
                    raise ValueError("Unexpected VDF closing brace")
                return result
            if key == "{" or index >= len(tokens):
                raise ValueError("Missing VDF value")
            token = tokens[index]
            index += 1
            if token == "}":
                raise ValueError("Missing VDF value")
            result[value(key).casefold()] = block(True) if token == "{" else value(token)
        if nested:
            raise ValueError("Unclosed VDF block")
        return result

    return block()


def _read_vdf(path: Path) -> dict:
    return parse_vdf(path.read_text(encoding="utf-8-sig"))


def _regular(path: Path) -> bool:
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        return False
    return path.is_file() and path.stat().st_size > 0


def inspect_game(game_dir: str | Path, manifest_path: str | Path | None = None) -> GameInstallation:
    """Inspect a selected game root; incomplete/uninstalled stories are omitted.

    A manually selected directory is supported without a Steam manifest. Version
    recognition of resource content belongs to the payload builder, not discovery.
    """
    root = Path(game_dir).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Game root is not a directory")
    modules = []
    for module_id, title in STORY_TITLES.items():
        folder = root / module_id
        if folder.is_symlink() or getattr(folder, "is_junction", lambda: False)():
            continue
        matches = ([path for path in folder.iterdir()
                    if path.name.casefold() == f"{module_id}.exe"] if folder.is_dir() else [])
        if len(matches) > 1:
            raise ValueError(f"Ambiguous story executable names in {module_id}: "
                             + ", ".join(sorted(path.name for path in matches)))
        exe = matches[0] if matches else folder / f"{module_id}.exe"
        archives = sorted(p for p in folder.glob("*.arc") if _regular(p))
        if _regular(exe) and archives:
            modules.append(StoryInstallation(module_id, title, folder, exe,
                                            (exe.name, *(p.name for p in archives))))
    manifest = Path(manifest_path).resolve(strict=True) if manifest_path else None
    state = _read_vdf(manifest).get("appstate", {}) if manifest else {}
    if manifest and str(state.get("appid", "")) != APP_ID:
        raise ValueError(f"Manifest is not for Steam app {APP_ID}")
    config = state.get("userconfig", {})
    depots = state.get("installeddepots", {})
    return GameInstallation(root, tuple(modules), manifest, state.get("buildid"),
                            config.get("language") if isinstance(config, dict) else None,
                            tuple(sorted(depots)) if isinstance(depots, dict) else (),
                            tuple(key for key in STORY_TITLES if key not in {m.id for m in modules}))


def default_steam_roots() -> tuple[Path, ...]:
    candidates = []
    if os.environ.get("STEAM_PATH"):
        candidates.append(Path(os.environ["STEAM_PATH"]))
    if os.name == "nt":
        import winreg
        for hive, key, field in [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ]:
            try:
                with winreg.OpenKey(hive, key) as handle:
                    candidates.append(Path(winreg.QueryValueEx(handle, field)[0]))
            except OSError:
                pass
    else:
        candidates.extend([Path.home() / ".steam/steam", Path.home() / ".local/share/Steam"])
    return tuple(candidates)


def discover_installations(steam_roots=None) -> list[GameInstallation]:
    """Discover the app in Steam's current/legacy libraryfolders layouts.

    Explicit roots can be Steam client or library roots. Bad manifests are skipped
    instead of treating their untrusted paths as game directories.
    """
    libraries = {}
    for candidate in default_steam_roots() if steam_roots is None else steam_roots:
        root = Path(candidate).expanduser().resolve()
        libraries[str(root).casefold()] = root
        config = root / "steamapps/libraryfolders.vdf"
        try:
            folders = _read_vdf(config).get("libraryfolders", {})
        except (OSError, ValueError):
            continue
        if not isinstance(folders, dict):
            continue
        for key, entry in folders.items():
            if not key.isdecimal():
                continue
            path = entry.get("path") if isinstance(entry, dict) else entry
            if isinstance(path, str) and path:
                library = Path(path).expanduser().resolve()
                libraries[str(library).casefold()] = library
    results = []
    for library in libraries.values():
        manifest = library / f"steamapps/appmanifest_{APP_ID}.acf"
        try:
            state = _read_vdf(manifest).get("appstate", {})
            directory = state.get("installdir", "")
            if (not isinstance(directory, str) or not directory or directory in (".", "..")
                    or "/" in directory or "\\" in directory
                    or PureWindowsPath(directory).drive or ":" in directory):
                continue
            common = (library / "steamapps/common").resolve()
            game = (common / directory).resolve(strict=True)
            if game.parent != common:
                continue
            info = inspect_game(game, manifest)
            if info.modules and all(existing.path != info.path for existing in results):
                results.append(info)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return results

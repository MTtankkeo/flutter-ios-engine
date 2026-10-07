"""Build selection, workspace paths, and shared process helpers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HOST = "host_release_arm64"
TARGET = "ios_release"
RUNTIME_MODES = ("release", "profile", "debug")
VERSION_PATTERNS = {
    "stable": r"\d+\.\d+\.\d+",
    "beta": r"\d+\.\d+\.\d+-\d+\.\d+\.pre",
}


def select_modes(release: bool = True, profile: bool = False, debug: bool = False) -> list[str]:
    modes = [mode for mode, enabled in zip(RUNTIME_MODES, (release, profile, debug)) if enabled]
    if not modes:
        raise ValueError("Select at least one build mode")
    return modes


def select_config(channel: str = "", version: str = "", patch_version: str = "1",
                  runtime_mode: str = "release") -> dict[str, str]:
    """Validate workflow inputs before using the version as a Git reference."""
    channel = channel.strip() or "stable"
    version = version.strip()
    patch_version = patch_version.strip()

    if channel not in VERSION_PATTERNS:
        raise ValueError("Channel must be stable or beta")

    if not re.fullmatch(VERSION_PATTERNS[channel], version):
        example = "3.47.6" if channel == "stable" else "3.50.0-0.1.pre"
        raise ValueError(f"Enter an exact {channel} version (format example: {example})")

    if not re.fullmatch(r"[1-9]\d*", patch_version):
        raise ValueError("Patch version must be a positive integer")
    if runtime_mode not in RUNTIME_MODES:
        raise ValueError("Build mode must be release, profile, or debug")

    return {
        "flutter_channel": channel,
        "flutter_version": version,
        "patch_version": patch_version,
        "runtime_mode": runtime_mode,
    }


@dataclass
class BuildContext:
    """Keep every build stage tied to the same workspace and selected release."""

    root: Path
    config: dict[str, str]

    @property
    def runtime_mode(self) -> str:
        return self.config.get("runtime_mode", "release")

    @property
    def host(self) -> str:
        return f"host_{self.runtime_mode}_arm64"

    @property
    def target(self) -> str:
        return f"ios_{self.runtime_mode}"

    @property
    def work(self) -> Path:
        return self.root / ".work"

    @property
    def flutter(self) -> Path:
        return self.work / "flutter"

    @property
    def src(self) -> Path:
        return self.flutter / "engine/src"

    @property
    def patch(self) -> Path:
        return self.root / "patches/ios-latency.patch"

    @property
    def stage(self) -> Path:
        return self.work / "package"

    @property
    def dist(self) -> Path:
        return self.root / "dist"

    @property
    def release_tag(self) -> str:
        return self.config["flutter_version"]

    def save_selection(self) -> None:
        (self.work / "build-selection.json").write_text(json.dumps(self.config, indent=2) + "\n")


def load_context(preparing: bool = False, root: Path = ROOT) -> BuildContext:
    """Read inputs once, then reuse the saved selection for subsequent stages."""
    if preparing:
        config = select_config(
            os.environ.get("FLUTTER_CHANNEL", ""),
            os.environ.get("FLUTTER_VERSION", ""),
            os.environ.get("PATCH_VERSION", "1"),
            os.environ.get("RUNTIME_MODE", "release"),
        )
    else:
        selection = root / ".work/build-selection.json"

        if not selection.is_file():
            raise RuntimeError("No prepared build selection; run prepare first")

        config = json.loads(selection.read_text())

    return BuildContext(root, config)


def run(*args: str | Path, cwd: Path) -> None:
    """Log and execute an argument list without invoking a shell."""
    command = list(map(str, args))
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def sha256_file(path: Path) -> str:
    """Hash large archives without loading them into memory."""
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()

"""Build selection, workspace paths, and shared process helpers."""
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


def select_config(defaults, channel="", version=""):
    selected = dict(defaults)
    selected["flutter_channel"] = channel.strip() or defaults.get("flutter_channel", "stable")
    selected["flutter_version"] = version.strip() or defaults["flutter_version"]
    channel = selected["flutter_channel"]
    version = selected["flutter_version"]
    patterns = {"stable": r"\d+\.\d+\.\d+", "beta": r"\d+\.\d+\.\d+-\d+\.\d+\.pre"}
    if channel not in patterns:
        raise ValueError("Channel must be stable or beta")
    if not re.fullmatch(patterns[channel], version):
        example = "3.47.6" if channel == "stable" else "3.50.0-0.1.pre"
        raise ValueError(f"Enter an exact {channel} version (format example: {example})")
    if (channel, version) != (defaults.get("flutter_channel", "stable"), defaults["flutter_version"]):
        selected.pop("flutter_commit", None)
    return selected


@dataclass
class BuildContext:
    root: Path
    config: dict

    @property
    def work(self):
        return self.root / ".work"

    @property
    def flutter(self):
        return self.work / "flutter"

    @property
    def src(self):
        return self.flutter / "engine/src"

    @property
    def patch(self):
        return self.root / "patches/ios-latency.patch"

    @property
    def stage(self):
        return self.work / "package"

    @property
    def dist(self):
        return self.root / "dist"

    @property
    def release_tag(self):
        return f'flutter-{self.config["flutter_version"]}-ios-latency.{self.config["patch_version"]}'

    def save_selection(self):
        (self.work / "build-selection.json").write_text(json.dumps(self.config, indent=2) + "\n")


def load_context(preparing=False, root=ROOT):
    if preparing:
        defaults = json.loads((root / "build-config.json").read_text())
        config = select_config(defaults, os.environ.get("FLUTTER_CHANNEL", ""),
                               os.environ.get("FLUTTER_VERSION", ""))
    else:
        selection = root / ".work/build-selection.json"
        if not selection.is_file():
            raise RuntimeError("No prepared build selection; run prepare first")
        config = json.loads(selection.read_text())
    return BuildContext(root, config)


def run(*args, cwd):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

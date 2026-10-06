#!/usr/bin/env python3
"""Prepare official stable sources, build, and package local-engine artifacts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "build-config.json").read_text())
PATCH = ROOT / "patches/ios-latency.patch"
WORK = ROOT / ".work"
FLUTTER = WORK / "flutter"
SRC = FLUTTER / "engine/src"
HOST = "host_release_arm64"
TARGET = "ios_release"


def run(*args, cwd=ROOT):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)


def revision():
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=FLUTTER, text=True
    ).strip()


def prepare(sync=False):
    version = CONFIG["flutter_version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise RuntimeError("Use an exact stable version, without a prerelease suffix")
    headers = {"User-Agent": "flutter-ios-engine", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        "https://api.github.com/repos/flutter/flutter/compare/"
        + CONFIG["flutter_commit"] + "...stable",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        comparison = json.load(response)
    if comparison["status"] not in ("ahead", "identical"):
        raise RuntimeError("Pinned commit is not on the official stable history")
    WORK.mkdir(exist_ok=True)
    if FLUTTER.exists():
        raise RuntimeError("Use a fresh .work directory; refusing to replace an existing checkout")
    run("git", "clone", "--depth=1", "--branch", version,
        "https://github.com/flutter/flutter.git", FLUTTER)
    if revision() != CONFIG["flutter_commit"]:
        raise RuntimeError("Flutter tag does not match the pinned commit")
    if sync:
        shutil.copy2(FLUTTER / "engine/scripts/standard.gclient", FLUTTER / ".gclient")
        # Avoid downloading Android dependencies for this iOS-only build.
        with (FLUTTER / ".gclient").open("a") as output:
            output.write('\nsolutions[0]["custom_vars"] = {"download_android_deps": False}\n')
        run("gclient", "sync", "--no-history", "--revision",
            ".@" + CONFIG["flutter_commit"], cwd=FLUTTER)
        if revision() != CONFIG["flutter_commit"]:
            raise RuntimeError("gclient changed the pinned revision")
    run("git", "apply", "--check", PATCH, cwd=FLUTTER)
    run("git", "apply", PATCH, cwd=FLUTTER)
    run("git", "diff", "--check", cwd=FLUTTER)


def build():
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("Build requires an Apple Silicon Mac with Xcode")
    run(SRC / "flutter/tools/gn", "--runtime-mode=release", "--mac-cpu=arm64",
        "--no-prebuilt-dart-sdk", "--no-lto", cwd=SRC)
    run("ninja", "-C", "out/" + HOST, "-j2", cwd=SRC)
    run(SRC / "flutter/tools/gn", "--ios", "--runtime-mode=release",
        "--no-lto", cwd=SRC)
    run("ninja", "-C", "out/" + TARGET, "-j2", cwd=SRC)


def copy(source, destination):
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def package():
    dist = ROOT / "dist"
    stage = WORK / "package"
    stage.mkdir(parents=True)
    for name in (HOST, TARGET):
        source = SRC / "out" / name
        destination = stage / "engine/src/out" / name
        destination.mkdir(parents=True)
        # Keep runtime artifacts, omitting object files and build-system state.
        for item in source.iterdir():
            if item.name in ("obj", "gen") or item.name.startswith("."):
                continue
            if item.suffix in (".ninja", ".o", ".a", ".TOC"):
                continue
            copy(item, destination / item.name)
        for relative in ("gen/dart-pkg", "gen/flutter/lib/snapshot", "gen/const_finder.dart.snapshot"):
            if (source / relative).exists():
                (destination / relative).parent.mkdir(parents=True, exist_ok=True)
                copy(source / relative, destination / relative)
    host = stage / "engine/src/out" / HOST
    target = stage / "engine/src/out" / TARGET
    # GN emits the release (product) platform into flutter_patched_sdk. Some
    # Flutter tool lookups use the product suffix even with local engines.
    if (target / "flutter_patched_sdk").is_dir() and not (target / "flutter_patched_sdk_product").exists():
        (target / "flutter_patched_sdk_product").symlink_to("flutter_patched_sdk", target_is_directory=True)
    if not (host / "dart-sdk/bin/dart").exists():
        raise RuntimeError("Host build must include a complete Dart SDK")
    for required in (host / "gen/dart-pkg/sky_engine", host / "font-subset",
                     target / "Flutter.xcframework", target / "flutter_patched_sdk",
                     target / "flutter_patched_sdk_product"):
        if not required.exists():
            raise RuntimeError(f"Missing local-engine artifact: {required}")
    if not list(target.glob("**/gen_snapshot*")):
        raise RuntimeError("Missing target gen_snapshot")
    copy(FLUTTER / "LICENSE", stage / "LICENSE")
    copy(PATCH, stage / "ios-latency.patch")
    metadata = dict(CONFIG, host_engine=HOST, local_engine=TARGET,
                    host_arch="arm64", runtime_mode="release", lto=False,
                    patch_sha256=hashlib.sha256(PATCH.read_bytes()).hexdigest(),
                    distribution_commit=os.environ.get("GITHUB_SHA", "local"),
                    xcode=subprocess.check_output(["xcodebuild", "-version"], text=True).strip())
    (stage / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    dist.mkdir(exist_ok=True)
    basename = f'flutter-{CONFIG["flutter_version"]}-ios-latency.{CONFIG["patch_version"]}'
    archive = dist / (basename + ".tar.gz")
    with tarfile.open(archive, "w:gz") as output:
        for child in stage.iterdir():
            output.add(child, arcname=child.name)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dist / (archive.name + ".sha256")).write_text(checksum + "  " + archive.name + "\n")
    shutil.copy2(stage / "metadata.json", dist / "metadata.json")
    # Validate the shipped layout by building an unsigned iOS app against it.
    app = WORK / "smoke_app"
    run(FLUTTER / "bin/flutter", "create", "--platforms=ios", "--project-name=engine_smoke", app)
    run(FLUTTER / "bin/flutter", "--local-engine-src-path=" + str(stage / "engine/src"),
        "--local-engine=" + TARGET, "--local-engine-host=" + HOST,
        "build", "ios", "--release", "--no-codesign", cwd=app)
    print("Validated archive:", archive)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "prepare", "build", "package"))
    command = parser.parse_args().command
    if command in ("check", "prepare"):
        prepare(sync=command == "prepare")
    elif command == "build":
        build()
    else:
        package()

"""Compile the iOS engine and matching Apple Silicon host tools."""
import os
import platform

from engine_common import HOST, TARGET, run


def build(context):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("Build requires an Apple Silicon Mac with Xcode")
    ninja = context.flutter / "third_party/ninja/ninja"
    if not ninja.is_file() or not os.access(ninja, os.X_OK):
        raise RuntimeError(f"Missing executable {ninja}; run prepare first")
    run(ninja, "--version", cwd=context.src)
    gn = context.src / "flutter/tools/gn"
    run(gn, "--runtime-mode=release", "--mac-cpu=arm64",
        "--no-prebuilt-dart-sdk", "--no-lto", cwd=context.src)
    run(ninja, "-C", "out/" + HOST, "-j3", cwd=context.src)
    run(gn, "--ios", "--runtime-mode=release", "--no-lto", cwd=context.src)
    run(ninja, "-C", "out/" + TARGET, "-j3", cwd=context.src)

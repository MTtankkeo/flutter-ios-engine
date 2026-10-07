"""Compile the iOS engine and matching Apple Silicon host tools."""

import os
import platform

from engine_common import BuildContext, run


def build(context: BuildContext) -> None:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("Build requires an Apple Silicon Mac with Xcode")

    # Use the Ninja version pinned by the selected Flutter checkout.
    ninja = context.flutter / "third_party/ninja/ninja"
    if not ninja.is_file() or not os.access(ninja, os.X_OK):
        raise RuntimeError(f"Missing executable {ninja}; run prepare first")

    run(ninja, "--version", cwd=context.src)
    gn = context.src / "flutter/tools/gn"

    # Host tools and the iOS engine must come from the same release.
    run(
        gn,
        f"--runtime-mode={context.runtime_mode}",
        "--mac-cpu=arm64",
        "--no-prebuilt-dart-sdk",
        "--no-lto",
        cwd=context.src,
    )

    run(ninja, "-C", f"out/{context.host}", cwd=context.src)
    run(gn, "--ios", f"--runtime-mode={context.runtime_mode}", "--no-lto", cwd=context.src)
    run(ninja, "-C", f"out/{context.target}", cwd=context.src)

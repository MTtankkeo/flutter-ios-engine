"""Stage compact runtime artifacts, preserve build results, and smoke-test them."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

from engine_common import BuildContext, run, sha256_file

RUNTIME_PATHS = (
    "dart-sdk", "font-subset", "impellerc", "shader_lib", "flutter_tester", "libtessellator.dylib",
    "frontend_server.dart.snapshot", "Flutter.xcframework", "Flutter.framework",
    "Flutter.framework.dSYM", "icudtl.dat", "flutter_patched_sdk",
    "flutter_patched_sdk_product", "LICENSE",
    "gen/dart-pkg", "gen/lib/snapshot", "gen/flutter/lib/snapshot", "gen/const_finder.dart.snapshot",
)
SNAPSHOT_NAMES = {"gen_snapshot", "gen_snapshot_arm64", "gen_snapshot_x64", "gen_snapshot_product"}


def copy(source: Path, destination: Path) -> None:
    """Stage files with hard links to avoid duplicating large build outputs."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True, copy_function=os.link)
    else:
        os.link(source, destination)


def stage_output(source: Path, destination: Path) -> None:
    """Ship runtime inputs only, never an entire compiler/toolchain directory."""
    destination.mkdir(parents=True)
    staged_directories = []
    for relative in RUNTIME_PATHS:
        path = source / relative
        if not path.exists():
            continue
        copy(path, destination / relative)
        if path.is_dir():
            staged_directories.append(path)

    for binary in source.rglob("gen_snapshot*"):
        # Whole runtime directories already include their snapshot generators.
        if any(binary.is_relative_to(directory) for directory in staged_directories):
            continue
        relative = binary.relative_to(source)

        if "obj" in relative.parts or "gen" in relative.parts:
            continue

        if binary.is_file() and binary.name in SNAPSHOT_NAMES:
            copy(binary, destination / relative)


def clean_objects(context: BuildContext) -> None:
    """Only remove generated object directories under our two build outputs."""
    out = (context.src / "out").resolve()
    for name in (context.host, context.target):
        output = (out / name).resolve()

        if not output.is_relative_to(out):
            raise RuntimeError("Build output escaped the workspace")

        # Remove nested object directories before their parents.
        for objects in sorted(output.rglob("obj"), key=lambda path: len(path.parts), reverse=True):
            if objects.is_symlink() or not objects.resolve().is_relative_to(output):
                raise RuntimeError("Refusing to remove objects outside the build output")

            if objects.is_dir():
                shutil.rmtree(objects)


def validate_runtime(host: Path, target: Path, mode: str = "release") -> None:
    """Ensure the staged engine contains everything needed by the smoke build."""
    # GN emits the release (product) platform into flutter_patched_sdk. Some
    # Flutter tool lookups use the product suffix even with local engines.
    sdk = target / "flutter_patched_sdk"
    product_sdk = target / "flutter_patched_sdk_product"
    if mode == "release" and sdk.is_dir() and not product_sdk.exists():
        product_sdk.symlink_to(sdk.name, target_is_directory=True)

    if not (host / "dart-sdk/bin/dart").exists():
        raise RuntimeError("Host build must include a complete Dart SDK")

    for required in (
        host / "gen/dart-pkg/sky_engine", host / "font-subset",
        target / "Flutter.xcframework", sdk,
    ):
        if not required.exists():
            raise RuntimeError(f"Missing local-engine artifact: {required}")

    if mode == "release" and not product_sdk.exists():
        raise RuntimeError(f"Missing local-engine artifact: {product_sdk}")
    if mode != "debug" and next(target.glob("**/gen_snapshot*"), None) is None:
        raise RuntimeError("Missing target gen_snapshot")
    if mode == "debug":
        for name in ("vm_isolate_snapshot.bin", "isolate_snapshot.bin"):
            if not (target / "gen/lib/snapshot" / name).is_file():
                raise RuntimeError(f"Missing debug snapshot: {name}")


def write_metadata(context: BuildContext) -> None:
    """Record the selected release, patch, and build tools alongside the engine."""
    metadata = dict(
        context.config,
        host_engine=context.host,
        local_engine=context.target,
        host_arch="arm64",
        runtime_mode=context.runtime_mode,
        lto=False,
        patch_sha256=hashlib.sha256(context.patch.read_bytes()).hexdigest(),
        distribution_commit=os.environ.get("GITHUB_SHA", "local"),
        xcode=subprocess.check_output(["xcodebuild", "-version"], text=True).strip(),
    )
    (context.stage / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")


def package(context: BuildContext) -> None:
    """Stage runtime files, free intermediate objects, and archive the result."""
    dist = context.dist
    stage = context.stage
    stage.mkdir(parents=True)
    outputs = stage / "engine/src/out"

    for name in (context.host, context.target):
        stage_output(context.src / "out" / name, outputs / name)
    validate_runtime(outputs / context.host, outputs / context.target, context.runtime_mode)

    copy(context.flutter / "LICENSE", stage / "LICENSE")
    copy(context.patch, stage / "ios-latency.patch")
    write_metadata(context)

    # The staged files share storage with the build outputs. Free objects before
    # Flutter bootstraps its SDK and before allocating a compressed archive.
    clean_objects(context)

    print("Free disk after object cleanup:", shutil.disk_usage(context.work).free, flush=True)
    dist.mkdir(exist_ok=True)
    archive = dist / "ios-engine.tar.gz"

    with tarfile.open(archive, "w:gz") as output:
        for child in stage.iterdir():
            output.add(child, arcname=child.name)
    checksum = sha256_file(archive)
    (dist / f"{archive.name}.sha256").write_text(f"{checksum}  {archive.name}\n")
    shutil.copy2(stage / "metadata.json", dist / "metadata.json")
    print("Packaged archive:", archive)


def smoke(context: BuildContext) -> None:
    """Build an unsigned iOS app against the packaged engine and host tools."""
    flutter = context.flutter / "bin/flutter"
    app = context.work / "smoke_app"
    run(
        flutter, "create", "--platforms=ios", "--project-name=engine_smoke", app,
        cwd=context.root,
    )
    run(
        flutter, f"--local-engine-src-path={context.stage / 'engine/src'}",
        f"--local-engine={context.target}", f"--local-engine-host={context.host}",
        "build", "ios", f"--{context.runtime_mode}", "--no-codesign", cwd=app,
    )
    print("Packaged engine passed unsigned iOS app build")

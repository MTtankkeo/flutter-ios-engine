"""Stage compact runtime artifacts, preserve build results, and smoke-test them."""
import hashlib
import json
import os
import shutil
import subprocess
import tarfile

from engine_common import HOST, TARGET, run, sha256_file


def copy(source, destination):
    if source.is_dir():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, symlinks=True, copy_function=os.link)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, destination)


def stage_output(source, destination):
    """Ship runtime inputs only, never an entire compiler/toolchain directory."""
    destination.mkdir(parents=True)
    runtime_names = (
        "dart-sdk", "font-subset", "impellerc", "shader_lib", "flutter_tester", "libtessellator.dylib",
        "frontend_server.dart.snapshot", "Flutter.xcframework", "Flutter.framework",
        "Flutter.framework.dSYM", "icudtl.dat", "flutter_patched_sdk",
        "flutter_patched_sdk_product", "LICENSE",
    )
    for name in runtime_names:
        if (source / name).exists():
            copy(source / name, destination / name)
    for relative in ("gen/dart-pkg", "gen/flutter/lib/snapshot", "gen/const_finder.dart.snapshot"):
        if (source / relative).exists():
            copy(source / relative, destination / relative)
    for binary in source.rglob("gen_snapshot*"):
        relative = binary.relative_to(source)
        if "obj" in relative.parts or "gen" in relative.parts:
            continue
        if binary.is_file() and binary.name in (
            "gen_snapshot", "gen_snapshot_arm64", "gen_snapshot_x64", "gen_snapshot_product"
        ):
            copy(binary, destination / relative)


def clean_objects(context):
    """Only remove generated object directories under our two build outputs."""
    out = (context.src / "out").resolve()
    for name in (HOST, TARGET):
        output = (out / name).resolve()
        if not output.is_relative_to(out):
            raise RuntimeError("Build output escaped the workspace")
        for objects in sorted(output.rglob("obj"), key=lambda p: len(p.parts), reverse=True):
            if objects.is_symlink() or not objects.resolve().is_relative_to(output):
                raise RuntimeError("Refusing to remove objects outside the build output")
            if objects.is_dir():
                shutil.rmtree(objects)


def package(context):
    dist = context.dist
    stage = context.stage
    stage.mkdir(parents=True)
    for name in (HOST, TARGET):
        source = context.src / "out" / name
        destination = stage / "engine/src/out" / name
        stage_output(source, destination)
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
    copy(context.flutter / "LICENSE", stage / "LICENSE")
    copy(context.patch, stage / "ios-latency.patch")
    metadata = dict(context.config, host_engine=HOST, local_engine=TARGET,
                    host_arch="arm64", runtime_mode="release", lto=False,
                    patch_sha256=hashlib.sha256(context.patch.read_bytes()).hexdigest(),
                    distribution_commit=os.environ.get("GITHUB_SHA", "local"),
                    xcode=subprocess.check_output(["xcodebuild", "-version"], text=True).strip())
    (stage / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    # The staged files share storage with the build outputs. Free objects before
    # Flutter bootstraps its SDK and before allocating a compressed archive.
    clean_objects(context)
    print("Free disk after object cleanup:", shutil.disk_usage(context.work).free, flush=True)
    dist.mkdir(exist_ok=True)
    archive = dist / (context.release_tag + ".tar.gz")
    with tarfile.open(archive, "w:gz") as output:
        for child in stage.iterdir():
            output.add(child, arcname=child.name)
    checksum = sha256_file(archive)
    (dist / (archive.name + ".sha256")).write_text(checksum + "  " + archive.name + "\n")
    shutil.copy2(stage / "metadata.json", dist / "metadata.json")
    print("Packaged archive:", archive)


def smoke(context):
    stage = context.stage
    app = context.work / "smoke_app"
    run(context.flutter / "bin/flutter", "create", "--platforms=ios", "--project-name=engine_smoke", app,
        cwd=context.root)
    run(context.flutter / "bin/flutter", "--local-engine-src-path=" + str(stage / "engine/src"),
        "--local-engine=" + TARGET, "--local-engine-host=" + HOST,
        "build", "ios", "--release", "--no-codesign", cwd=app)
    print("Packaged engine passed unsigned iOS app build")

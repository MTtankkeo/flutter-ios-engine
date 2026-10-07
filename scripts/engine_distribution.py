"""Combine independently validated build modes into one fixed-name archive."""

import json
from pathlib import Path
import shutil
import tarfile

from engine_common import RUNTIME_MODES, sha256_file
from engine_package import validate_runtime

IDENTITY_KEYS = (
    "flutter_channel", "flutter_version", "flutter_commit", "patch_version",
    "patch_sha256", "distribution_commit", "host_arch", "lto",
)


def combine(root: Path, artifacts: Path, modes: list[str]) -> None:
    if not modes or len(set(modes)) != len(modes) or any(mode not in RUNTIME_MODES for mode in modes):
        raise ValueError("Select unique release, profile, or debug modes")
    stage = root / ".work/combined"
    stage.mkdir(parents=True)
    outputs = stage / "engine/src/out"
    outputs.mkdir(parents=True)
    builds = {}
    baseline = None

    for mode in modes:
        incoming = artifacts / f"ios-engine-{mode}"
        archive = incoming / "ios-engine.tar.gz"
        checksum = (incoming / "ios-engine.tar.gz.sha256").read_text().split()
        if checksum != [sha256_file(archive), archive.name]:
            raise RuntimeError(f"Invalid archive checksum for {mode}")
        unpacked = root / ".work" / f"unpacked-{mode}"
        unpacked.mkdir(parents=True)
        with tarfile.open(archive) as source:
            source.extractall(unpacked, filter="data")
        metadata = json.loads((unpacked / "metadata.json").read_text())
        external_metadata = json.loads((incoming / "metadata.json").read_text())
        if metadata != external_metadata:
            raise RuntimeError(f"Archive metadata differs for {mode}")
        if metadata["runtime_mode"] != mode:
            raise RuntimeError(f"Wrong build mode in {mode} artifact")
        identity = {key: metadata[key] for key in IDENTITY_KEYS}
        if baseline is None:
            baseline = identity
            for name in ("LICENSE", "ios-latency.patch"):
                shutil.copy2(unpacked / name, stage / name)
        elif identity != baseline:
            raise RuntimeError("Build modes came from different sources or configurations")
        if sha256_file(unpacked / "ios-latency.patch") != metadata["patch_sha256"]:
            raise RuntimeError(f"Wrong patch in {mode} artifact")
        host, target = f"host_{mode}_arm64", f"ios_{mode}"
        if (metadata["host_engine"], metadata["local_engine"]) != (host, target):
            raise RuntimeError(f"Wrong engine directories for {mode}")
        source_outputs = unpacked / "engine/src/out"
        if {path.name for path in source_outputs.iterdir()} != {host, target}:
            raise RuntimeError(f"Unexpected engine directories for {mode}")
        validate_runtime(source_outputs / host, source_outputs / target, mode)
        for name in (host, target):
            shutil.move(str(source_outputs / name), outputs / name)
        builds[mode] = metadata

    combined = dict(baseline, modes=modes, engines=builds)
    (stage / "metadata.json").write_text(json.dumps(combined, indent=2) + "\n")
    dist = root / "dist"
    dist.mkdir(exist_ok=True)
    archive = dist / "ios-engine.tar.gz"
    with tarfile.open(archive, "w:gz") as destination:
        for child in stage.iterdir():
            destination.add(child, arcname=child.name)
    (dist / "ios-engine.tar.gz.sha256").write_text(f"{sha256_file(archive)}  {archive.name}\n")
    shutil.copy2(stage / "metadata.json", dist / "metadata.json")
    print("Combined validated modes:", ", ".join(modes))

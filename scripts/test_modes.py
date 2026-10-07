"""Exercise mode selection, mode-specific artifacts, and combined releases."""

import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import engine_build
import engine_distribution
import engine_package
from engine_common import BuildContext, RUNTIME_MODES, load_context, select_config, select_modes, sha256_file


def make_package(root: Path, mode: str, commit: str = "a" * 40) -> BuildContext:
    config = dict(select_config("stable", "3.47.6", runtime_mode=mode), flutter_commit=commit)
    context = BuildContext(root, config)
    files = {
        context.host: (
            "dart-sdk/bin/dart", "font-subset", "gen/dart-pkg/sky_engine/lib/sky.dart",
        ),
        context.target: (
            "Flutter.xcframework/ios-arm64/Flutter.framework/Flutter",
            "flutter_patched_sdk/platform_strong.dill",
        ),
    }
    if mode == "debug":
        files[context.target] += (
            "gen/lib/snapshot/vm_isolate_snapshot.bin", "gen/lib/snapshot/isolate_snapshot.bin",
        )
    else:
        files[context.target] += ("gen_snapshot_arm64",)
    if mode == "release":
        files[context.target] += ("flutter_patched_sdk_product/platform_strong.dill",)
    for name, relatives in files.items():
        for relative in relatives:
            path = context.src / "out" / name / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
            if relative == "dart-sdk/bin/dart":
                path.chmod(0o755)
    context.patch.parent.mkdir(parents=True)
    context.patch.write_text("same patch")
    (context.flutter / "LICENSE").write_text("fixture license")
    with patch.object(engine_package.subprocess, "check_output", return_value="Xcode fixture"):
        engine_package.package(context)
    return context


class ModeTest(unittest.TestCase):
    def test_default_and_selected_matrix(self):
        self.assertEqual(select_modes(), ["release"])
        self.assertEqual(select_modes(True, True, True), list(RUNTIME_MODES))
        self.assertEqual(select_modes(False, False, True), ["debug"])
        with self.assertRaisesRegex(ValueError, "at least one"):
            select_modes(False, False, False)
        with self.assertRaisesRegex(ValueError, "Build mode"):
            select_config("stable", "3.47.6", runtime_mode="simulator")

    def test_saved_mode_wins_over_later_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(os.environ, {"FLUTTER_VERSION": "3.47.6", "RUNTIME_MODE": "debug"}):
                context = load_context(preparing=True, root=root)
            context.work.mkdir()
            context.save_selection()
            with patch.dict(os.environ, {"RUNTIME_MODE": "release"}):
                loaded = load_context(root=root)
            self.assertEqual((loaded.host, loaded.target), ("host_debug_arm64", "ios_debug"))

    def test_all_modes_use_matching_host_and_device_commands(self):
        for mode in RUNTIME_MODES:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                context = BuildContext(Path(temporary), select_config("stable", "3.47.6", runtime_mode=mode))
                ninja = context.flutter / "third_party/ninja/ninja"
                ninja.parent.mkdir(parents=True)
                ninja.touch()
                ninja.chmod(0o755)
                with (
                    patch.object(engine_build.platform, "system", return_value="Darwin"),
                    patch.object(engine_build.platform, "machine", return_value="arm64"),
                    patch.object(engine_build, "run") as run,
                ):
                    engine_build.build(context)
                builds = [call.args for call in run.call_args_list if "-C" in call.args]
                self.assertEqual(builds, [
                    (ninja, "-C", f"out/{context.host}"),
                    (ninja, "-C", f"out/{context.target}"),
                ])
                gn_calls = [call.args for call in run.call_args_list if f"--runtime-mode={mode}" in call.args]
                self.assertEqual(len(gn_calls), 2)
                with patch.object(engine_package, "run") as run:
                    engine_package.smoke(context)
                command = run.call_args.args
                self.assertIn(f"--{mode}", command)
                self.assertIn(f"--local-engine={context.target}", command)
                self.assertIn(f"--local-engine-host={context.host}", command)

    def test_debug_keeps_jit_snapshots_and_does_not_require_aot(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = make_package(Path(temporary), "debug")
            target = context.stage / "engine/src/out" / context.target
            self.assertTrue((target / "gen/lib/snapshot/isolate_snapshot.bin").is_file())
            self.assertFalse((target / "flutter_patched_sdk_product").exists())
            self.assertFalse(list(target.rglob("gen_snapshot*")))
            (target / "gen/lib/snapshot/isolate_snapshot.bin").unlink()
            with self.assertRaisesRegex(RuntimeError, "debug snapshot"):
                engine_package.validate_runtime(context.stage / "engine/src/out" / context.host, target, "debug")


class CombinedDistributionTest(unittest.TestCase):
    def artifacts(self, base: Path, modes: list[str], different_source: bool = False) -> Path:
        artifacts = base / "incoming"
        for mode in modes:
            commit = "b" * 40 if different_source and mode == "debug" else "a" * 40
            context = make_package(base / mode, mode, commit)
            shutil.copytree(context.dist, artifacts / f"ios-engine-{mode}")
        return artifacts

    def test_combines_selected_modes_with_fixed_names_and_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            modes = list(RUNTIME_MODES)
            artifacts = self.artifacts(base, modes)
            root = base / "combined"
            engine_distribution.combine(root, artifacts, modes)
            archive = root / "dist/ios-engine.tar.gz"
            metadata = json.loads((root / "dist/metadata.json").read_text())
            self.assertEqual(metadata["modes"], modes)
            self.assertEqual(set(metadata["engines"]), set(modes))
            with tarfile.open(archive) as output:
                names = output.getnames()
                for mode in modes:
                    self.assertIn(f"engine/src/out/ios_{mode}", names)
                    self.assertIn(f"engine/src/out/host_{mode}_arm64/dart-sdk/bin/dart", names)
                self.assertEqual(json.load(output.extractfile("metadata.json")), metadata)
                if os.name != "nt":
                    self.assertTrue(output.getmember("engine/src/out/host_debug_arm64/dart-sdk/bin/dart").mode & 0o111)
            self.assertEqual((root / "dist/ios-engine.tar.gz.sha256").read_text().split(),
                             [sha256_file(archive), "ios-engine.tar.gz"])

    def test_single_selected_debug_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            artifacts = self.artifacts(base, ["debug"])
            engine_distribution.combine(base / "combined", artifacts, ["debug"])
            metadata = json.loads((base / "combined/dist/metadata.json").read_text())
            self.assertEqual(metadata["modes"], ["debug"])

    def test_rejects_mismatched_sources_before_writing_distribution(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            artifacts = self.artifacts(base, ["release", "debug"], different_source=True)
            root = base / "combined"
            with self.assertRaisesRegex(RuntimeError, "different sources"):
                engine_distribution.combine(root, artifacts, ["release", "debug"])
            self.assertFalse((root / "dist").exists())

    def test_rejects_corrupt_or_missing_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            artifacts = self.artifacts(base, ["release"])
            with self.assertRaises(FileNotFoundError):
                engine_distribution.combine(base / "missing", artifacts, ["release", "profile"])
            (artifacts / "ios-engine-release/ios-engine.tar.gz.sha256").write_text("wrong  ios-engine.tar.gz\n")
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                engine_distribution.combine(base / "corrupt", artifacts, ["release"])


if __name__ == "__main__":
    unittest.main()

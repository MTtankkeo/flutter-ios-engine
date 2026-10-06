import json
import os
import subprocess
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from engine_common import BuildContext, HOST, TARGET, load_context, select_config
import engine_package
import engine_source

DEFAULTS = {
    "flutter_channel": "stable", "flutter_version": "3.47.6",
    "flutter_commit": "a" * 40, "patch_version": "1", "patch_source_commit": "b" * 40,
}


class SelectionTest(unittest.TestCase):
    def test_default_keeps_pin_and_override_resolves_its_own_commit(self):
        self.assertEqual(select_config(DEFAULTS)["flutter_commit"], "a" * 40)
        for channel, version in (("stable", "3.47.5"), ("beta", "3.50.0-0.1.pre")):
            config = select_config(DEFAULTS, channel, version)
            self.assertEqual(config["flutter_channel"], channel)
            self.assertEqual(config["flutter_version"], version)
            self.assertNotIn("flutter_commit", config)
        self.assertIn("flutter_commit", DEFAULTS)

    def test_rejects_wrong_channel_versions_and_ref_injection(self):
        for channel, version in (("dev", "3.47.6"), ("stable", "3.50.0-0.1.pre"),
                                 ("beta", "3.47.6"), ("stable", "stable"),
                                 ("stable", "3.47.6; echo unsafe")):
            with self.subTest(channel=channel, version=version), self.assertRaises(ValueError):
                select_config(DEFAULTS, channel, version)

    def test_later_steps_use_saved_selection_not_defaults_or_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = select_config(DEFAULTS, "beta", "3.50.0-0.1.pre")
            config["flutter_commit"] = "c" * 40
            context = BuildContext(root, config)
            context.work.mkdir()
            context.save_selection()
            with patch.dict(os.environ, {"FLUTTER_CHANNEL": "stable", "FLUTTER_VERSION": "3.47.6"}):
                loaded = load_context(root=root)
            self.assertEqual(loaded.config, config)
            self.assertEqual(loaded.release_tag, "flutter-3.50.0-0.1.pre-ios-latency.1")

    def test_verifies_the_selected_channel_and_rejects_divergence(self):
        with patch.object(engine_source.urllib.request, "urlopen") as urlopen:
            response = urlopen.return_value.__enter__.return_value
            response.read.return_value = b'{"status":"ahead"}'
            engine_source.verify_channel("c" * 40, "beta")
            self.assertTrue(urlopen.call_args.args[0].full_url.endswith("...beta"))
            response.read.return_value = b'{"status":"diverged"}'
            with self.assertRaisesRegex(RuntimeError, "official beta"):
                engine_source.verify_channel("c" * 40, "beta")

    def test_incompatible_patch_stops_before_dependency_sync(self):
        def run_command(*args, **kwargs):
            if args[:3] == ("git", "apply", "--check"):
                raise subprocess.CalledProcessError(1, args)

        with tempfile.TemporaryDirectory() as temporary:
            context = BuildContext(Path(temporary), dict(DEFAULTS))
            with patch.object(engine_source, "run", side_effect=run_command), \
                 patch.object(engine_source, "revision", return_value="a" * 40), \
                 patch.object(engine_source, "verify_channel"), \
                 patch.object(engine_source, "sync_dependencies") as sync:
                with self.assertRaisesRegex(RuntimeError, "backport for stable 3.47.6"):
                    engine_source.prepare(context, sync=True)
                sync.assert_not_called()

    def test_pinned_default_rejects_a_changed_tag(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = BuildContext(Path(temporary), dict(DEFAULTS))
            with patch.object(engine_source, "run"), \
                 patch.object(engine_source, "revision", return_value="c" * 40):
                with self.assertRaisesRegex(RuntimeError, "pinned commit"):
                    engine_source.prepare(context)


class DistributionTest(unittest.TestCase):
    def test_package_records_selected_release_and_excludes_intermediates(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = BuildContext(Path(temporary), dict(DEFAULTS, flutter_channel="beta",
                                                       flutter_version="3.50.0-0.1.pre"))
            fixtures = {
                HOST: ("dart-sdk/bin/dart", "font-subset", "gen/dart-pkg/sky_engine/lib/sky.dart",
                       "obj/large.o", "clang_x64/obj/large.o"),
                TARGET: ("Flutter.xcframework/ios-arm64/Flutter.framework/Flutter",
                         "flutter_patched_sdk/platform_strong.dill",
                         "flutter_patched_sdk_product/platform_strong.dill",
                         "clang_x64/gen_snapshot", "obj/large.o"),
            }
            for name, paths in fixtures.items():
                for relative in paths:
                    file = context.src / "out" / name / relative
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_bytes(b"fixture")
            context.patch.parent.mkdir(parents=True)
            context.patch.write_text("fixture patch")
            (context.flutter / "LICENSE").write_text("fixture license")
            with patch.object(engine_package.subprocess, "check_output", return_value="Xcode fixture"):
                engine_package.package(context)
            archive = context.dist / (context.release_tag + ".tar.gz")
            with tarfile.open(archive) as packaged:
                names = packaged.getnames()
                self.assertFalse(any("obj" in Path(name).parts for name in names))
                metadata = json.load(packaged.extractfile("metadata.json"))
            self.assertEqual(metadata["flutter_version"], "3.50.0-0.1.pre")
            self.assertEqual(metadata["flutter_channel"], "beta")
            self.assertTrue((context.dist / (archive.name + ".sha256")).exists())

    def test_smoke_build_uses_packaged_paths(self):
        context = BuildContext(Path("workspace").resolve(), DEFAULTS)
        with patch.object(engine_package, "run") as run:
            engine_package.smoke(context)
        self.assertEqual(run.call_args_list[0].kwargs["cwd"], context.root)
        self.assertIn("--local-engine-src-path=" + str(context.stage / "engine/src"), run.call_args.args)


if __name__ == "__main__":
    unittest.main()

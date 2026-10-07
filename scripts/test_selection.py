"""Verify release selection, source preparation, and packaged engine artifacts."""

import json
import os
import subprocess
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import engine_package
import engine_source
from engine_common import BuildContext, HOST, TARGET, load_context, select_config

PREPARED_CONFIG = {
    "flutter_channel": "stable",
    "flutter_version": "3.47.6",
    "flutter_commit": "a" * 40,
    "patch_version": "1",
}


class SelectionTest(unittest.TestCase):
    def test_explicit_versions_resolve_their_own_commit(self):
        for channel, version in (("stable", "3.47.5"), ("beta", "3.50.0-0.1.pre")):
            with self.subTest(channel=channel, version=version):
                config = select_config(channel, version)
                self.assertEqual(config["flutter_channel"], channel)
                self.assertEqual(config["flutter_version"], version)
                self.assertNotIn("flutter_commit", config)
                self.assertEqual(config["patch_version"], "1")

    def test_preparing_uses_environment_without_a_config_file(self):
        environment = {
            "FLUTTER_CHANNEL": "beta",
            "FLUTTER_VERSION": "3.50.0-0.1.pre",
            "PATCH_VERSION": "2",
        }
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, environment, clear=True):
                context = load_context(preparing=True, root=Path(temporary))

            self.assertEqual(context.release_tag, "3.50.0-0.1.pre")
            self.assertNotIn("flutter_commit", context.config)

    def test_missing_version_fails_before_preparation(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "exact stable version"):
                load_context(preparing=True)

    def test_rejects_invalid_patch_versions(self):
        for revision in ("", "0", "-1", "1.2", "1; echo unsafe"):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                select_config("stable", "3.47.6", revision)

    def test_rejects_wrong_channel_versions_and_ref_injection(self):
        invalid_releases = (
            ("dev", "3.47.6"),
            ("stable", "3.50.0-0.1.pre"),
            ("beta", "3.47.6"),
            ("stable", "stable"),
            ("stable", "3.47.6; echo unsafe"),
        )
        for channel, version in invalid_releases:
            with self.subTest(channel=channel, version=version), self.assertRaises(ValueError):
                select_config(channel, version)

    def test_later_steps_use_saved_selection_not_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = select_config("beta", "3.50.0-0.1.pre", "2")
            config["flutter_commit"] = "c" * 40
            context = BuildContext(root, config)
            context.work.mkdir()
            context.save_selection()

            # Later workflow steps must honor the saved selection even if inputs change.
            with patch.dict(os.environ, {"FLUTTER_CHANNEL": "stable", "FLUTTER_VERSION": "3.47.6"}):
                loaded = load_context(root=root)

            self.assertEqual(loaded.config, config)
            self.assertEqual(loaded.release_tag, "3.50.0-0.1.pre")


class SourceTest(unittest.TestCase):
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
        def reject_patch_check(*args, **kwargs):
            # Only compatibility checking fails; cloning is treated as successful.
            if args[:3] == ("git", "apply", "--check"):
                raise subprocess.CalledProcessError(1, args)

        with tempfile.TemporaryDirectory() as temporary:
            context = BuildContext(Path(temporary), select_config("stable", "3.47.6"))
            with (
                patch.object(engine_source, "run", side_effect=reject_patch_check),
                patch.object(engine_source, "revision", return_value="a" * 40),
                patch.object(engine_source, "verify_channel"),
                patch.object(engine_source, "sync_dependencies") as sync,
            ):
                with self.assertRaisesRegex(RuntimeError, "backport for stable 3.47.6"):
                    engine_source.prepare(context, sync=True)
                sync.assert_not_called()

    def test_preparation_records_the_selected_tag_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = BuildContext(Path(temporary), select_config("stable", "3.47.6"))
            with (
                patch.object(engine_source, "run"),
                patch.object(engine_source, "revision", return_value="c" * 40),
                patch.object(engine_source, "verify_channel"),
            ):
                engine_source.prepare(context)

            prepared = load_context(root=context.root)
            self.assertEqual(prepared.config["flutter_commit"], "c" * 40)


class DistributionTest(unittest.TestCase):
    def test_package_records_selected_release_and_excludes_intermediates(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = dict(
                PREPARED_CONFIG, flutter_channel="beta", flutter_version="3.50.0-0.1.pre",
            )
            context = BuildContext(Path(temporary), config)
            # Mix required runtime files with objects that must never be distributed.
            fixtures = {
                HOST: (
                    "dart-sdk/bin/dart",
                    "font-subset",
                    "gen/dart-pkg/sky_engine/lib/sky.dart",
                    "obj/large.o",
                    "clang_x64/obj/large.o",
                ),
                TARGET: (
                    "Flutter.xcframework/ios-arm64/Flutter.framework/Flutter",
                    "flutter_patched_sdk/platform_strong.dill",
                    "flutter_patched_sdk_product/platform_strong.dill",
                    "clang_x64/gen_snapshot",
                    "obj/large.o",
                ),
            }
            for name, paths in fixtures.items():
                for relative in paths:
                    path = context.src / "out" / name / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"fixture")
            context.patch.parent.mkdir(parents=True)
            context.patch.write_text("fixture patch")
            (context.flutter / "LICENSE").write_text("fixture license")

            with patch.object(engine_package.subprocess, "check_output", return_value="Xcode fixture"):
                engine_package.package(context)

            archive = context.dist / "ios-engine.tar.gz"
            with tarfile.open(archive) as packaged:
                names = packaged.getnames()
                self.assertFalse(any("obj" in Path(name).parts for name in names))
                metadata = json.load(packaged.extractfile("metadata.json"))
            self.assertEqual(metadata["flutter_version"], "3.50.0-0.1.pre")
            self.assertEqual(metadata["flutter_channel"], "beta")
            self.assertTrue((context.dist / f"{archive.name}.sha256").exists())

    def test_smoke_build_uses_packaged_paths(self):
        context = BuildContext(Path("workspace").resolve(), PREPARED_CONFIG)
        with patch.object(engine_package, "run") as run:
            engine_package.smoke(context)

        self.assertEqual(run.call_args_list[0].kwargs["cwd"], context.root)
        self.assertIn(
            f"--local-engine-src-path={context.stage / 'engine/src'}", run.call_args.args,
        )


if __name__ == "__main__":
    unittest.main()

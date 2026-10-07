"""Verify build commands, staged runtime files, and object cleanup."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import engine_build
import engine_package
from engine_common import BuildContext, HOST, TARGET


def create_files(root: Path, *paths: str) -> None:
    """Create a minimal output tree without running an engine build."""
    for relative in paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")


class PackageTest(unittest.TestCase):
    def test_stage_keeps_runtime_files_without_nested_objects_or_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            destination = base / "stage"
            create_files(
                source,
                "dart-sdk/bin/dart",
                "clang_x64/gen_snapshot",
                "dart-sdk/bin/utils/gen_snapshot",
                "clang_x64/obj/huge.o",
                "obj/huge.o",
                "shell_unittests",
                "gen/dart-pkg/sky_engine/lib/sky.dart",
                "gen/unrelated/huge.dat",
            )

            engine_package.stage_output(source, destination)

            for relative in ("clang_x64/gen_snapshot", "gen/dart-pkg/sky_engine/lib/sky.dart"):
                with self.subTest(retained=relative):
                    self.assertTrue((destination / relative).is_file())
            for relative in ("clang_x64/obj", "obj", "shell_unittests", "gen/unrelated"):
                with self.subTest(excluded=relative):
                    self.assertFalse((destination / relative).exists())

            # Staging must share storage, including snapshots already inside the SDK.
            for relative in ("dart-sdk/bin/dart", "dart-sdk/bin/utils/gen_snapshot"):
                with self.subTest(hard_link=relative):
                    self.assertTrue(os.path.samefile(source / relative, destination / relative))

    def test_cleanup_removes_only_generated_objects(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = BuildContext(Path(temporary), {})
            for name in (HOST, TARGET):
                create_files(
                    context.src / "out" / name,
                    "obj/large.o", "clang_x64/obj/large.o", "clang_x64/gen_snapshot",
                )

            engine_package.clean_objects(context)

            for name in (HOST, TARGET):
                with self.subTest(target=name):
                    output = context.src / "out" / name
                    self.assertFalse((output / "obj").exists())
                    self.assertFalse((output / "clang_x64/obj").exists())
                    self.assertTrue((output / "clang_x64/gen_snapshot").is_file())


class BuildTest(unittest.TestCase):
    def setUp(self) -> None:
        # Exercise macOS command generation without requiring a Mac or Xcode.
        for attribute, value in (("system", "Darwin"), ("machine", "arm64")):
            platform_patch = patch.object(engine_build.platform, attribute, return_value=value)
            platform_patch.start()
            self.addCleanup(platform_patch.stop)

    def test_build_uses_flutter_pinned_ninja_for_both_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = BuildContext(Path(temporary), {})
            ninja = context.flutter / "third_party/ninja/ninja"
            ninja.parent.mkdir(parents=True)
            ninja.touch()
            ninja.chmod(0o755)
            with patch.object(engine_build, "run") as run:
                engine_build.build(context)

            self.assertEqual(run.call_args_list[0].args, (ninja, "--version"))
            builds = [call.args for call in run.call_args_list if "-C" in call.args]
            self.assertEqual(
                builds,
                [
                    (ninja, "-C", "out/host_release_arm64"),
                    (ninja, "-C", "out/ios_release"),
                ],
            )

    def test_missing_pinned_ninja_fails_before_gn(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = BuildContext(Path(temporary), {})
            with patch.object(engine_build, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "run prepare first"):
                    engine_build.build(context)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

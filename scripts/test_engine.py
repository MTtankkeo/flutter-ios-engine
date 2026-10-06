import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import engine_build
import engine_package
from engine_common import BuildContext, HOST, TARGET


class PackageTest(unittest.TestCase):
    def test_stage_keeps_runtime_files_without_nested_objects_or_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            for relative in ("dart-sdk/bin/dart", "clang_x64/gen_snapshot",
                             "clang_x64/obj/huge.o", "obj/huge.o",
                             "shell_unittests", "gen/dart-pkg/sky_engine/lib/sky.dart",
                             "gen/unrelated/huge.dat"):
                file = source / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b"fixture")
            destination = base / "stage"
            engine_package.stage_output(source, destination)
            self.assertTrue((destination / "clang_x64/gen_snapshot").is_file())
            self.assertTrue((destination / "gen/dart-pkg/sky_engine/lib/sky.dart").is_file())
            self.assertFalse((destination / "clang_x64/obj").exists())
            self.assertFalse((destination / "obj").exists())
            self.assertFalse((destination / "shell_unittests").exists())
            self.assertFalse((destination / "gen/unrelated").exists())
            self.assertTrue(os.path.samefile(source / "dart-sdk/bin/dart",
                                            destination / "dart-sdk/bin/dart"))

    def test_cleanup_removes_only_generated_objects(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = BuildContext(Path(temporary), {})
            src = context.src
            for name in (HOST, TARGET):
                output = src / "out" / name
                for relative in ("obj/large.o", "clang_x64/obj/large.o", "clang_x64/gen_snapshot"):
                    file = output / relative
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_bytes(b"fixture")
            engine_package.clean_objects(context)
            for name in (HOST, TARGET):
                output = src / "out" / name
                self.assertFalse((output / "obj").exists())
                self.assertFalse((output / "clang_x64/obj").exists())
                self.assertTrue((output / "clang_x64/gen_snapshot").is_file())


class BuildTest(unittest.TestCase):
    def test_build_uses_flutter_pinned_ninja_for_both_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = BuildContext(Path(temporary), {})
            checkout = context.flutter
            ninja = checkout / "third_party/ninja/ninja"
            ninja.parent.mkdir(parents=True)
            ninja.touch()
            ninja.chmod(0o755)
            with patch.object(engine_build.platform, "system", return_value="Darwin"), \
                 patch.object(engine_build.platform, "machine", return_value="arm64"), \
                 patch.object(engine_build, "run") as run:
                engine_build.build(context)
            self.assertEqual(run.call_args_list[0].args, (ninja, "--version"))
            builds = [call.args for call in run.call_args_list if "-C" in call.args]
            self.assertEqual(builds, [
                (ninja, "-C", "out/host_release_arm64", "-j3"),
                (ninja, "-C", "out/ios_release", "-j3"),
            ])

    def test_missing_pinned_ninja_fails_before_gn(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = BuildContext(Path(temporary), {})
            with patch.object(engine_build.platform, "system", return_value="Darwin"), \
                 patch.object(engine_build.platform, "machine", return_value="arm64"), \
                 patch.object(engine_build, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "run prepare first"):
                    engine_build.build(context)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

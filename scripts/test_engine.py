import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import engine


class BuildTest(unittest.TestCase):
    def test_build_uses_flutter_pinned_ninja_for_both_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)
            ninja = checkout / "third_party/ninja/ninja"
            ninja.parent.mkdir(parents=True)
            ninja.touch()
            ninja.chmod(0o755)
            with patch.object(engine, "FLUTTER", checkout), \
                 patch.object(engine.platform, "system", return_value="Darwin"), \
                 patch.object(engine.platform, "machine", return_value="arm64"), \
                 patch.object(engine, "run") as run:
                engine.build()
            self.assertEqual(run.call_args_list[0].args, (ninja, "--version"))
            builds = [call.args for call in run.call_args_list if "-C" in call.args]
            self.assertEqual(builds, [
                (ninja, "-C", "out/host_release_arm64", "-j2"),
                (ninja, "-C", "out/ios_release", "-j2"),
            ])

    def test_missing_pinned_ninja_fails_before_gn(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(engine, "FLUTTER", Path(temporary)), \
             patch.object(engine.platform, "system", return_value="Darwin"), \
             patch.object(engine.platform, "machine", return_value="arm64"), \
             patch.object(engine, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "run prepare first"):
                engine.build()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

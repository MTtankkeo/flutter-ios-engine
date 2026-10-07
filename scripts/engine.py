#!/usr/bin/env python3
"""Command entry point for source preparation, builds, and distribution."""

import argparse
import json
import os
from pathlib import Path

from engine_build import build
from engine_common import ROOT, load_context, select_modes
from engine_distribution import combine
from engine_package import package, smoke
from engine_source import prepare


def main() -> None:
    actions = {"build": build, "package": package, "smoke": smoke}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "prepare", *actions, "release-tag", "matrix", "combine"))
    parser.add_argument("--modes", nargs="+")
    parser.add_argument("--artifacts", type=Path, default=ROOT / ".work/artifacts")
    args = parser.parse_args()
    command = args.command
    if command == "matrix":
        load_context(preparing=True)
        modes = select_modes(
            release=os.environ.get("BUILD_RELEASE", "true") == "true",
            profile=os.environ.get("BUILD_PROFILE", "false") == "true",
            debug=os.environ.get("BUILD_DEBUG", "false") == "true",
        )
        print(json.dumps(modes))
        return
    if command == "combine":
        combine(ROOT, args.artifacts, args.modes or [])
        return
    context = load_context(preparing=command in ("check", "prepare"))

    if command in ("check", "prepare"):
        prepare(context, sync=command == "prepare")
    elif command == "release-tag":
        print(context.release_tag)
    else:
        actions[command](context)


if __name__ == "__main__":
    main()

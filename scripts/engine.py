#!/usr/bin/env python3
"""Command entry point for source preparation, builds, and distribution."""
import argparse

from engine_build import build
from engine_common import load_context
from engine_package import package, smoke
from engine_source import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "prepare", "build", "package", "smoke", "release-tag"))
    command = parser.parse_args().command
    context = load_context(preparing=command in ("check", "prepare"))
    if command in ("check", "prepare"):
        prepare(context, sync=command == "prepare")
    elif command == "release-tag":
        print(context.release_tag)
    else:
        {"build": build, "package": package, "smoke": smoke}[command](context)


if __name__ == "__main__":
    main()

"""Check out an official release, sync dependencies, and apply the patch."""
import ast
import json
import os
import subprocess
import urllib.request

from engine_common import run


def revision(context):
    return subprocess.check_output(["git", "rev-parse", "HEAD"],
                                   cwd=context.flutter, text=True).strip()


def verify_channel(commit, channel):
    headers = {"User-Agent": "flutter-ios-engine", "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    request = urllib.request.Request(
        f"https://api.github.com/repos/flutter/flutter/compare/{commit}...{channel}", headers=headers
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        comparison = json.load(response)
    if comparison["status"] not in ("ahead", "identical"):
        raise RuntimeError(f"Selected release is not on official {channel} history")


def sync_dependencies(context):
    standard = ast.parse((context.flutter / "engine/scripts/standard.gclient").read_text())
    solutions = ast.literal_eval(standard.body[0].value)
    solutions[0]["custom_vars"] = {"download_android_deps": False}
    (context.flutter / ".gclient").write_text("solutions = " + repr(solutions) + "\n")
    run("gclient", "sync", "--no-history", "--revision",
        ".@" + context.config["flutter_commit"], cwd=context.flutter)
    if revision(context) != context.config["flutter_commit"]:
        raise RuntimeError("gclient changed the selected revision")


def prepare(context, sync=False):
    context.work.mkdir(exist_ok=True)
    if context.flutter.exists():
        raise RuntimeError("Use a fresh .work directory; refusing to replace an existing checkout")
    version = context.config["flutter_version"]
    run("git", "clone", "--depth=1", "--branch", version,
        "https://github.com/flutter/flutter.git", context.flutter, cwd=context.root)
    commit = revision(context)
    expected = context.config.get("flutter_commit")
    if expected and expected != commit:
        raise RuntimeError("Flutter tag does not match the pinned commit")
    verify_channel(commit, context.config["flutter_channel"])
    context.config["flutter_commit"] = commit
    # Check compatibility before the expensive dependency sync.
    try:
        run("git", "apply", "--check", context.patch, cwd=context.flutter)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"Patch needs a backport for {context.config['flutter_channel']} {version}") from error
    if sync:
        sync_dependencies(context)
    run("git", "apply", context.patch, cwd=context.flutter)
    run("git", "diff", "--check", cwd=context.flutter)
    context.save_selection()
    print(f"Prepared {context.config['flutter_channel']} {version} ({commit})", flush=True)

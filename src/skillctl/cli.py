"""Synchronize managed skills with the desired state in config.toml."""

import argparse
import sys

from .contracts import SkillError
from .manager import default_home, sync
from .progress import ProgressReporter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skillctl")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync", help="Download/update configured skills and remove unconfigured managed skills")
    parser.parse_args(argv)
    try:
        with ProgressReporter() as progress:
            result = sync(default_home(), progress=progress)
        for name in result.updated:
            print(f"Updated {name}")
        for name in result.removed:
            print(f"Removed {name}")
        for name, message in result.errors.items():
            print(f"{name}: {message}", file=sys.stderr)
        if result.updated or result.removed:
            print("Run /reload in Pi to refresh skills.")
        elif not result.errors:
            print("Nothing to sync.")
        return 1 if result.errors else 0
    except SkillError as exc:
        print(f"skillctl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

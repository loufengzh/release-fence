"""Machine-readable command-line entry point."""
import argparse
import json
import os
import sys
from .core import FenceError, Policy, diff, load_json, scan


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect ZIP packaging without extraction")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "check"):
        command = commands.add_parser(name)
        command.add_argument("archive")
        command.add_argument("--policy")
    command = commands.add_parser("diff")
    command.add_argument("before")
    command.add_argument("after")
    args = parser.parse_args(argv)
    try:
        if args.command == "diff":
            result = diff(load_json(args.before), load_json(args.after))
            status = 1 if any(result.values()) else 0
        else:
            policy = Policy.from_dict(load_json(args.policy)) if args.policy else Policy()
            result = scan(args.archive, policy)
            status = 1 if args.command == "check" and result["violations"] else 0
    except (FenceError, OSError) as exc:
        print(f"release-fence: {exc}", file=sys.stderr)
        return 2
    try:
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
        sys.stdout.flush()
    except OSError as exc:
        # Prevent interpreter shutdown from retrying a failed buffered sink and
        # replacing the documented I/O error status with 120.
        try:
            target = sys.stdout.fileno()
            sink = os.open(os.devnull, os.O_WRONLY)
            if sink != target:
                try:
                    os.dup2(sink, target)
                finally:
                    os.close(sink)
        except (OSError, ValueError, AttributeError):
            sys.stdout = None
        print(f"release-fence: output failed ({type(exc).__name__})", file=sys.stderr)
        return 2
    return status


if __name__ == "__main__":
    raise SystemExit(main())

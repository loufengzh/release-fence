"""Machine-readable command-line entry point."""
import argparse
import json
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
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
        return status
    except (FenceError, OSError) as exc:
        print(f"release-fence: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Test a wheel in a clean environment on Linux, Windows, and macOS."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import venv
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    # Prevent a developer's checkout from masking a broken wheel.
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory(prefix="release fence smoke ") as directory:
        work = Path(directory)
        home = work / "venv"
        venv.EnvBuilder(with_pip=True).create(home)
        scripts = home / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        cli = scripts / ("release-fence.exe" if os.name == "nt" else "release-fence")

        def run(argv, expected=0):
            result = subprocess.run([str(arg) for arg in argv], cwd=work, env=env,
                                    capture_output=True, text=True, encoding="utf-8")
            if result.returncode != expected:
                raise RuntimeError(f"{argv!r}: expected exit {expected}, got "
                                   f"{result.returncode}\n{result.stdout}\n{result.stderr}")
            return result

        run([python, "-m", "pip", "install", "--no-index", "--no-deps", wheel])
        tests = run([python, "-I", "-m", "unittest", "discover", "-s", root / "tests", "-v"])
        print(tests.stderr, end="")
        run([cli, "--help"])
        archive = work / "synthetic release.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as stream:
            stream.writestr("LICENSE", "Synthetic public fixture\n")
            stream.writestr("package/\u4f60\u597d.txt", "hello\n")
        policy = work / "policy.json"
        policy.write_text(json.dumps({"required": ["LICENSE"], "forbidden": ["*.TXT"]}), encoding="utf-8")
        passed = run([cli, "check", archive, "--policy", policy])
        inventory = json.loads(passed.stdout)
        assert inventory["violations"] == [], inventory
        assert [item["path"] for item in inventory["files"]] == ["LICENSE", "package/\u4f60\u597d.txt"]
        before = work / "before.json"
        before.write_text(passed.stdout, encoding="utf-8")
        policy.write_text('{"required": ["MISSING"]}', encoding="utf-8")
        failed = run([cli, "check", archive, "--policy", policy], expected=1)
        assert json.loads(failed.stdout)["violations"] == ["missing required path: MISSING"]
        scanned = run([cli, "scan", archive, "--policy", policy])
        assert json.loads(scanned.stdout) == json.loads(failed.stdout)
        same = run([cli, "diff", before, before])
        assert json.loads(same.stdout) == {"added": [], "removed": [], "changed": []}
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("LICENSE", "Changed synthetic fixture\n")
        after = work / "after.json"
        after.write_text(run([cli, "scan", archive]).stdout, encoding="utf-8")
        changed = run([cli, "diff", before, after], expected=1)
        assert json.loads(changed.stdout) == {"added": [], "removed": ["package/\u4f60\u597d.txt"], "changed": ["LICENSE"]}
        invalid = work / "invalid.zip"
        invalid.write_bytes(b"not an archive")
        error = run([cli, "scan", invalid], expected=2)
        assert error.stdout == "" and "release-fence:" in error.stderr
    print("Installed-wheel tests and CLI exit codes 0/1/2 passed.")


if __name__ == "__main__":
    main()

"""Windows worktree provisioning and isolated local tests. Never contacts a Pi."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LOCK = Path("requirements/windows-dev/requirements.lock")
IMPORTS = ("pytest", "pytestqt", "PySide6.QtWidgets", "numpy", "pandas", "scipy",
           "cv2", "joblib", "sklearn", "skimage", "matplotlib", "psutil", "serial", "pyDOE3")
SUBMODULE = "firmware/third_party/cpputest"
CUBE = Path(r"C:\ST\STM32CubeIDE_1.18.1\STM32CubeIDE")


def invoke(args, *, cwd=ROOT, env=None):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env,
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, args, result.stdout, result.stderr)
    return result.stdout.strip()


def git(*args, root=ROOT):
    return invoke(["git", "-C", root, *args], cwd=root)


def git_submodule(*args, root=ROOT):
    # Git for Windows shell helpers need the environment set by its own Bash.
    # Pass arguments separately: no user input is interpolated into shell code.
    exe = Path(shutil.which("git") or "")
    bash = exe.parent.parent / "bin/bash.exe"
    if os.name == "nt" and bash.is_file():
        return invoke([bash, "-lc", 'exec git "$@"', "worktree-git", "-C", root,
                       "submodule", *args], cwd=root)
    return git("submodule", *args, root=root)


def validate_root(root):
    root = Path(root).resolve(strict=True)
    if Path(git("rev-parse", "--show-toplevel", root=root)).resolve() != root:
        raise ValueError("Expected a Git worktree root")
    return root


def lock_pins(root):
    result = {}
    for line in (root / LOCK).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", line):
            raise ValueError(f"Invalid development lock entry: {line}")
        name, version = line.split("==")
        result[re.sub(r"[-_.]+", "-", name).lower()] = version
    if not result:
        raise ValueError("Empty development dependency lock")
    return result


def python_identity(python):
    code = ("import sys,struct,platform,json;print(json.dumps(dict("
            "executable=sys.executable,prefix=sys.prefix,base_prefix=sys.base_prefix,"
            "version=list(sys.version_info[:3]),bits=struct.calcsize('P')*8,"
            "implementation=platform.python_implementation(),platform=sys.platform)))")
    result = json.loads(invoke([python, "-I", "-B", "-c", code]))
    if (result["platform"] != "win32" or result["implementation"] != "CPython"
            or result["version"][:2] != [3, 13] or result["bits"] != 64):
        raise ValueError("Requires Windows x64 CPython 3.13")
    return result


def verify_environment(root):
    directory = root / "env"
    python = directory / "Scripts/python.exe"
    if directory.resolve() != directory or python.resolve() != python:
        raise ValueError("env must be independent, not a junction or symlink")
    if not python.is_file():
        raise ValueError(f"Environment is missing or incomplete: {python}. "
                         "Preserve it for diagnosis and provision a fresh worktree.")
    identity = python_identity(python)
    if Path(identity["prefix"]).resolve() != directory or identity["prefix"] == identity["base_prefix"]:
        raise ValueError("Interpreter is not this worktree's virtual environment")
    code = ("import importlib.metadata as m,json,re;print(json.dumps({"
            "re.sub(r'[-_.]+','-',d.metadata['Name']).lower():d.version for d in m.distributions()}))")
    installed = json.loads(invoke([python, "-I", "-B", "-c", code]))
    mismatches = {n: {"expected": v, "actual": installed.get(n)}
                  for n, v in lock_pins(root).items() if installed.get(n) != v}
    if mismatches:
        raise ValueError("Environment differs from development lock; use a fresh worktree: " + json.dumps(mismatches))
    invoke([python, "-I", "-B", "-m", "pip", "check"])
    invoke([python, "-I", "-B", "-c",
            "import importlib; " + "; ".join(f"importlib.import_module({n!r})" for n in IMPORTS)])
    return identity


def firmware_preflight(root, *, check_only):
    if not shutil.which("cmake"):
        raise ValueError("CMake is required for firmware host tests")
    vswhere = Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    compiler = shutil.which("cl") or shutil.which("gcc")
    if not compiler and vswhere.is_file():
        compiler = invoke([vswhere, "-latest", "-products", "*", "-requires",
                           "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-find",
                           r"VC\Tools\MSVC\**\bin\Hostx64\x64\cl.exe"])
    if not compiler:
        raise ValueError("Install Visual Studio C++ build tools for firmware host tests")
    if not (CUBE / "headless-build.bat").is_file():
        raise ValueError(f"STM32CubeIDE headless build is missing: {CUBE}")
    state = git_submodule("status", "--", SUBMODULE, root=root)
    # invoke strips whitespace, including the leading clean-status space.
    if state.startswith(("+", "U")):
        raise ValueError("CppUTest is mismatched or conflicted; preserve it and resolve explicitly")
    expected = git("ls-tree", "HEAD", "--", SUBMODULE, root=root).split()[2]
    module = root / SUBMODULE
    if state.startswith("-"):
        if check_only:
            raise ValueError("CppUTest is uninitialized; rerun setup with -IncludeFirmware")
        if module.exists() and any(module.iterdir()):
            raise ValueError("Uninitialized CppUTest directory is nonempty")
        git_submodule("update", "--init", "--", SUBMODULE, root=root)
    if git("rev-parse", "HEAD", root=module) != expected:
        raise ValueError("CppUTest does not match the tracked gitlink")
    if git("status", "--porcelain", "--untracked-files=all", root=module):
        raise ValueError("CppUTest is dirty; setup will not overwrite it")
    return {"cpputest_commit": expected, "compiler": compiler, "cubeide": str(CUBE)}


def setup(root, python, *, include_firmware=False, check_only=False):
    root = validate_root(root)
    python = Path(python)
    if not python.is_absolute() or not python.is_file():
        raise ValueError("--python requires an existing absolute executable")
    python_identity(python)
    lock_pins(root)
    directory = root / "env"
    if not directory.exists():
        if check_only:
            raise ValueError("env is missing; run setup without -CheckOnly")
        # Existing/partial environments are never repaired or overwritten.
        directory.mkdir(exist_ok=False)
        invoke([python, "-I", "-m", "venv", directory], cwd=root)
        invoke([directory / "Scripts/python.exe", "-I", "-m", "pip", "install",
                "--disable-pip-version-check", "--no-deps", "-r", root / LOCK], cwd=root)
    result = {"environment": verify_environment(root)}
    if include_firmware:
        result["firmware"] = firmware_preflight(root, check_only=check_only)
    return result


def test_arguments(args):
    # Prevent aliases, ini overrides, and external plugins from changing the
    # runner-owned temporary/report paths or restoring inherited pytest options.
    prohibited = ("--basetemp", "--junit", "--log-file", "--html", "--self-contained-html",
                  "--output", "--rootdir", "--override-ini", "--confcutdir",
                  "--config-file", "--debug")
    for arg in args:
        if (arg.startswith(prohibited) or arg in ("-c", "-o", "-p")
                or (arg.startswith(("-o", "-c", "-p")) and not arg.startswith("--"))):
            raise ValueError(f"Runner owns pytest configuration and evidence paths: {arg}")
    return list(args)


def test_environment(run_root, environ=None):
    env = dict(os.environ if environ is None else environ)
    for name in list(env):
        if (name.upper().startswith(("LABCRAFT_MACHINE", "LABCRAFT_DEVELOPMENT", "LABCRAFT_DEPLOYMENT",
                                     "PYTEST_", "PYTHON")) or name in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH")):
            env.pop(name, None)
    env.update(QT_QPA_PLATFORM="offscreen", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", MPLCONFIGDIR=str(run_root / "mpl"),
               XDG_CACHE_HOME=str(run_root / "cache"), TEMP=str(run_root / "temp"), TMP=str(run_root / "temp"))
    for directory in ("mpl", "cache", "temp"):
        (run_root / directory).mkdir()
    return env


def run_tests(root, args):
    root = validate_root(root)
    args = test_arguments(args)
    identity = verify_environment(root)
    run_root = Path(tempfile.mkdtemp(prefix="labcraft-worktree-tests-")).resolve()
    roots = [Path(line[9:]).resolve() for line in git("worktree", "list", "--porcelain", root=root).splitlines()
             if line.startswith("worktree ")]
    if any(run_root.is_relative_to(r) for r in roots):
        raise ValueError("OS temporary directory must be outside all worktrees")
    env = test_environment(run_root)
    command = [str(root / "env/Scripts/python.exe"), "-m", "pytest", "-p", "pytestqt.plugin",
               "--basetemp", str(run_root / "pytest"), "--junitxml", str(run_root / "junit.xml"), *args]
    evidence = {"worktree": str(root), "commit": git("rev-parse", "HEAD", root=root),
                "interpreter": identity, "dependency_lock_sha256": hashlib.sha256((root / LOCK).read_bytes()).hexdigest(),
                "evidence_directory": str(run_root), "command": command}
    report = run_root / "run.json"
    report.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence), flush=True)
    # Reuse the existing owned-tree cleanup implementation. No process search
    # or signaling by executable name; only this still-live Popen child.
    from tools.optimizer_memory_qualification import terminate_owned_tree
    with (run_root / "pytest.log").open("w", encoding="utf-8") as log:
        child = subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                                 start_new_session=os.name != "nt")
        evidence["pid"] = child.pid
        try:
            code = child.wait()
        except KeyboardInterrupt:
            terminate_owned_tree(child)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                terminate_owned_tree(child, force=True)
                child.wait(timeout=10)
            code = 130
        evidence["exit_code"] = code
        report.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print((run_root / "pytest.log").read_text(encoding="utf-8"), end="")
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    provision = sub.add_parser("setup")
    provision.add_argument("--python", required=True)
    provision.add_argument("--include-firmware", action="store_true")
    provision.add_argument("--check-only", action="store_true")
    test = sub.add_parser("test")
    test.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.action == "setup":
            print(json.dumps(setup(ROOT, args.python, include_firmware=args.include_firmware,
                                   check_only=args.check_only), indent=2))
            return 0
        return run_tests(ROOT, args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args)
    except subprocess.CalledProcessError as exc:
        print(f"Command failed ({exc.returncode}): {exc.cmd}\n{exc.stdout}\n{exc.stderr}", file=sys.stderr)
        return exc.returncode
    except (OSError, ValueError) as exc:
        print(f"Worktree development refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    status = main()
    # Windows native failures arrive as unsigned DWORDs. sys.exit needs the
    # signed 32-bit representation to preserve those bits rather than exit 1.
    if os.name == "nt" and 0x80000000 <= status <= 0xFFFFFFFF:
        status -= 0x100000000
    raise SystemExit(status)

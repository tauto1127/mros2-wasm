#!/usr/bin/env python3
"""Build a run-local native mROS 2 peer from an isolated POSIX source copy."""

from pathlib import Path
import subprocess


RUN_DIR = Path(__file__).resolve().parent
SOURCE_TREE = Path("/home/osslab/mros2-posix-worktree")
SOURCE_COPY = Path("/tmp/mros2-posix-run04-final-source")
BUILD_DIR = Path("/tmp/mros2-posix-run04-final-build")
APP_SOURCE = SOURCE_COPY / "workspace/echoreply_string/app.cpp"
EXECUTABLE = BUILD_DIR / "mros2-posix"
IP_PATCH = RUN_DIR / "native-peer-ip.patch"


def run(args, input_bytes=None):
    command = ["rtk", *map(str, args)]
    print("[CR-NATIVE-R04-BUILD] command=" + " ".join(command), flush=True)
    result = subprocess.run(command, input=input_bytes, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main():
    if SOURCE_COPY.exists() or BUILD_DIR.exists():
        raise SystemExit(
            "refusing to reuse or overwrite existing isolated source/build paths")
    run(["cp", "-a", SOURCE_TREE, SOURCE_COPY])
    run(["cp", RUN_DIR / "native_peer.cpp", APP_SOURCE])
    run(["proxy", "patch", "-p1", "-d", SOURCE_COPY],
        input_bytes=IP_PATCH.read_bytes())
    run(["cmake", "-S", SOURCE_COPY, "-B", BUILD_DIR,
         "-DCMAKE_APPNAME=echoreply_string"])
    run(["cmake", "--build", BUILD_DIR, "--target", "mros2-posix",
         "--parallel", "4"])
    if not EXECUTABLE.is_file():
        raise SystemExit(f"build succeeded without expected executable: {EXECUTABLE}")
    print(f"[CR-NATIVE-R04-BUILD] event=build_complete executable={EXECUTABLE}",
          flush=True)


if __name__ == "__main__":
    main()

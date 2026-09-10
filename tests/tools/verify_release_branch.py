from __future__ import annotations

import argparse
import subprocess


def run_git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{completed.stdout}")
    return completed.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify release PR branches include the latest develop commit."
    )
    parser.add_argument("--develop-ref", default="origin/develop")
    parser.add_argument("--head-ref", default="HEAD")
    args = parser.parse_args()

    run_git("fetch", "origin", "develop", "--quiet")
    develop_sha = run_git("rev-parse", args.develop_ref)
    head_sha = run_git("rev-parse", args.head_ref)
    merge_base = run_git("merge-base", args.develop_ref, args.head_ref)

    print(f"develop_ref={args.develop_ref}")
    print(f"develop_sha={develop_sha}")
    print(f"head_ref={args.head_ref}")
    print(f"head_sha={head_sha}")
    print(f"merge_base={merge_base}")

    if merge_base != develop_sha:
        print(
            "::error::Release branch is not based on the latest origin/develop. "
            "Update the release branch from develop and rerun validation."
        )
        return 1

    print("Release branch contains the latest origin/develop commit.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"::error::{exc}")
        raise SystemExit(1) from exc

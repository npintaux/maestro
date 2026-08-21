"""Preflight prerequisite check for Maestro's version-control integration.

Maestro operates on an **already-provisioned GitHub repository, cloned locally**. This
script is the mechanical twin of that prose precondition: `/conduct` runs it before Phase 0
and refuses to start unless every prerequisite holds. Exit code is non-zero on any failure —
a precondition that is not a script that bites is not a precondition.

Checks (all must pass):
  1. git-worktree   — the current directory is inside a git working tree.
  2. origin-remote  — an `origin` remote is configured, over HTTPS (SSH is out of scope per
                      the Antigravity `permissioned-github` contract).
  3. gh-auth        — the `gh` CLI is installed and authenticated.
  4. default-branch — the repository's default branch is `main`.
  5. main-protection— branch protection is enabled on `main`. This is what makes "the human
                      owns the merge" real: without it, that rule is only prose.

Command execution is injected (see `run_checks`) so the check logic is unit-testable without
a real git repo, network, or `gh` install.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field

# A command runner returns (returncode, stdout, stderr).
Runner = Callable[[Sequence[str]], "tuple[int, str, str]"]


@dataclass
class Check:
    """The outcome of a single preflight prerequisite check."""

    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class PreflightReport:
    """Aggregate result of all preflight checks."""

    checks: list[Check] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.is_valid,
            "checks": [c.to_dict() for c in self.checks],
        }


def _default_runner(cmd: Sequence[str]) -> tuple[int, str, str]:
    """Execute a command, returning (returncode, stdout, stderr). Never raises."""
    try:
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]!r}"
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - defensive
        return 1, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def _check_git_worktree(run: Runner) -> Check:
    rc, out, err = run(["git", "rev-parse", "--is-inside-work-tree"])
    if rc == 0 and out.strip() == "true":
        return Check("git-worktree", True, "inside a git working tree")
    return Check(
        "git-worktree",
        False,
        "not inside a git working tree — clone the provisioned GitHub repo first "
        f"({err.strip() or out.strip() or 'git rev-parse failed'}).",
    )


def _check_origin_remote(run: Runner) -> Check:
    rc, out, err = run(["git", "remote", "get-url", "origin"])
    url = out.strip()
    if rc != 0 or not url:
        return Check(
            "origin-remote",
            False,
            f"no 'origin' remote configured ({err.strip() or 'git remote get-url origin failed'}).",
        )
    if url.startswith("git@") or url.startswith("ssh://"):
        return Check(
            "origin-remote",
            False,
            f"origin '{url}' uses SSH; Maestro requires HTTPS (per permissioned-github).",
        )
    if not url.startswith("https://"):
        return Check(
            "origin-remote",
            False,
            f"origin '{url}' is not HTTPS; Maestro requires HTTPS (per permissioned-github).",
        )
    return Check("origin-remote", True, f"origin over HTTPS: {url}")


def _check_gh_auth(run: Runner) -> Check:
    rc, out, err = run(["gh", "auth", "status"])
    if rc == 0:
        return Check("gh-auth", True, "gh CLI is authenticated")
    return Check(
        "gh-auth",
        False,
        f"gh CLI not installed or not authenticated — run 'gh auth login' "
        f"({(err or out).strip() or 'gh auth status failed'}).",
    )


def _check_default_branch(run: Runner) -> Check:
    rc, out, err = run(
        ["gh", "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"]
    )
    name = out.strip()
    if rc != 0:
        return Check(
            "default-branch",
            False,
            f"could not determine the default branch ({err.strip() or 'gh repo view failed'}).",
        )
    if name != "main":
        return Check(
            "default-branch",
            False,
            f"default branch is '{name}', but Maestro requires 'main'.",
        )
    return Check("default-branch", True, "default branch is 'main'")


def _check_main_protection(run: Runner) -> Check:
    rc, out, err = run(
        ["gh", "api", "repos/{owner}/{repo}/branches/main", "--jq", ".protected"]
    )
    if rc != 0:
        return Check(
            "main-protection",
            False,
            "could not read protection status for 'main' "
            f"({err.strip() or 'gh api failed'}); ensure the repo exists and the token reads it.",
        )
    if out.strip() != "true":
        return Check(
            "main-protection",
            False,
            "branch protection is NOT enabled on 'main'. Enable it so the human-reviewed "
            "integration -> main merge is enforced (otherwise that gate is only prose). "
            "On a free personal account this requires a public repo or GitHub Pro.",
        )
    return Check("main-protection", True, "branch protection is enabled on 'main'")


def run_checks(runner: Runner | None = None) -> PreflightReport:
    """Run every preflight check and return the aggregate report."""
    run = runner or _default_runner
    return PreflightReport(
        checks=[
            _check_git_worktree(run),
            _check_origin_remote(run),
            _check_gh_auth(run),
            _check_default_branch(run),
            _check_main_protection(run),
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint: run preflight checks, print a JSON report, exit non-zero on failure."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify Maestro's version-control prerequisites: a cloned, HTTPS-origin GitHub "
            "repo, an authenticated gh CLI, default branch 'main', and branch protection on 'main'."
        )
    )
    parser.parse_args(argv)

    report = run_checks()
    print(json.dumps(report.to_dict(), indent=2))

    if not report.is_valid:
        print(
            f"ERROR: preflight failed with {len(report.failures)} unmet prerequisite(s):",
            file=sys.stderr,
        )
        for c in report.failures:
            print(f"  - {c.name}: {c.detail}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

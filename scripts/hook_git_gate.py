"""Harness PreToolUse Hook Adapter for the Git Branch Gate.

Intercepts shell commands (Antigravity tool ``run_command``) before they execute and
mechanically enforces Maestro's version-control non-negotiables:

  1. **No commit to a protected branch.** ``git commit`` is denied when the current
     branch is ``main``/``master``. Agents commit on the per-run integration branch
     (``maestro/<slug>``) or a subsystem branch (``issue/<n>-<subsystem>``); the human
     owns the one merge that reaches ``main``.
  2. **No push to a protected branch.** ``git push`` is denied when it targets
     ``main``/``master`` (explicit refspec destination, or a bare push while on a
     protected branch). Pushing to ``main`` is reserved for the human-reviewed
     ``integration -> main`` PR, backed by GitHub branch protection.
  3. **Only Maestro-shaped branches may be created.** ``git checkout -b`` /
     ``git switch -c`` / ``git branch <name>`` are denied unless the new branch matches
     the integration shape ``maestro/<slug>`` or the subsystem shape
     ``issue/<n>-<subsystem>``. Enforcing shape at creation means an agent can never end
     up *on* an off-process branch, so rule 1 only has to police ``main``/``master``.

This is the mechanical twin of the prose guardrails in the borrowed SDD ``commit`` /
``ship`` skills: under task pressure a subagent ignores prose, so the non-negotiable is a
hook that emits ``{"decision":"deny"}``.

Design: fail **open**. Anything the gate cannot confidently evaluate (not a git command,
unparseable payload, current branch undeterminable) is allowed, so a bug in the gate never
blocks unrelated work. Only a *confident* violation denies.

The Antigravity harness invokes this file directly as ``python3 scripts/hook_git_gate.py``;
it reads the tool-call JSON on stdin and prints a single allow/deny decision on stdout,
always exiting 0 (blocking is done by the decision, not the exit code).
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence

PROTECTED_BRANCHES = frozenset({"main", "master"})

# Allowed branch shapes an agent is permitted to CREATE.
INTEGRATION_BRANCH_RE = re.compile(r"^maestro/[a-z0-9][a-z0-9._-]*$")
SUBSYSTEM_BRANCH_RE = re.compile(r"^issue/[0-9]+-[a-z0-9-]+$")

# Shell operators that separate independent commands in one command line.
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[|&;]")

# `git checkout -b`, `git checkout -B`, `git switch -c`, `git switch -C` all create a branch.
_CHECKOUT_CREATE_FLAGS = frozenset({"-b", "-B", "-c", "-C"})

# `git branch` flags that mean "list / delete / rename / configure", i.e. NOT a plain create.
_BRANCH_NON_CREATE_FLAGS = frozenset(
    {
        "-d", "-D", "--delete",
        "-m", "-M", "--move",
        "-c", "-C", "--copy",
        "--list", "-l",
        "-a", "--all", "-r", "--remotes",
        "-v", "-vv", "--verbose",
        "--contains", "--no-contains", "--merged", "--no-merged", "--points-at",
        "--set-upstream-to", "-u", "--unset-upstream", "--edit-description",
        "--show-current", "--format", "--sort", "--color", "--column", "--no-column",
    }
)

# `git push` flags that consume the following token as their value.
_PUSH_VALUE_FLAGS = frozenset({"-o", "--push-option", "--repo", "--receive-pack", "--exec"})

_REASON_PREFIX = "PreToolUse Git Gate"


def _tokenize(segment: str) -> list[str]:
    """Split one command segment into shell tokens, tolerating malformed quoting."""
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _git_invocation(tokens: Sequence[str]) -> tuple[str, list[str]] | None:
    """Return ``(subcommand, args_after_subcommand)`` for the first ``git`` call, or None.

    Skips global options that precede the subcommand, including ``-C <dir>`` and
    ``-c <key=val>`` which each consume a following value token.
    """
    try:
        i = list(tokens).index("git")
    except ValueError:
        return None
    j = i + 1
    n = len(tokens)
    while j < n:
        tok = tokens[j]
        if tok in ("-C", "-c"):  # global flag that takes a value
            j += 2
            continue
        if tok.startswith("-"):
            j += 1
            continue
        return tokens[j], list(tokens[j + 1 :])
    return None


def _iter_git_invocations(command: str) -> Iterator[tuple[str, list[str]]]:
    """Yield each ``git`` invocation (subcommand + args) across a chained command line."""
    for segment in _SEGMENT_SPLIT_RE.split(command):
        inv = _git_invocation(_tokenize(segment))
        if inv is not None:
            yield inv


def _deny(reason: str) -> dict[str, str]:
    return {"decision": "deny", "reason": f"{_REASON_PREFIX}: {reason}"}


def _allow() -> dict[str, str]:
    return {"decision": "allow"}


def _branch_dest_basename(refspec: str) -> str:
    """Extract the destination branch name from a push refspec (``src:dst`` or ``dst``)."""
    dest = refspec.split(":")[-1]  # `src:dst` -> `dst`; bare `dst` -> `dst`
    dest = dest.lstrip("+")  # `+refspec` force-push marker
    return dest.rsplit("/", 1)[-1]  # `refs/heads/main` -> `main`


def _check_commit(current_branch: str | None) -> dict[str, str] | None:
    """Deny a commit on a protected branch. Fail open if the branch is unknown."""
    if current_branch is None:
        return None
    if current_branch in PROTECTED_BRANCHES:
        return _deny(
            f"'git commit' is blocked on protected branch '{current_branch}'. Maestro commits "
            "on the integration branch (maestro/<slug>) or a subsystem branch "
            "(issue/<n>-<subsystem>); only the human merges to main."
        )
    return None


def _check_push(args: Sequence[str], current_branch: str | None) -> dict[str, str] | None:
    """Deny a push that targets a protected branch."""
    positionals: list[str] = []
    k = 0
    n = len(args)
    while k < n:
        tok = args[k]
        if tok in _PUSH_VALUE_FLAGS:
            k += 2
            continue
        if tok.startswith("-"):
            k += 1
            continue
        positionals.append(tok)
        k += 1

    refspecs = positionals[1:]  # positionals[0] is the remote
    if not refspecs:
        # Bare `git push` / `git push <remote>`: pushes the current branch.
        if current_branch in PROTECTED_BRANCHES:
            return _deny(
                f"'git push' from protected branch '{current_branch}' is blocked. Pushing to "
                "main is reserved for the human-reviewed integration -> main PR."
            )
        return None

    for refspec in refspecs:
        if _branch_dest_basename(refspec) in PROTECTED_BRANCHES:
            return _deny(
                f"'git push' targeting protected branch (refspec '{refspec}') is blocked. "
                "Pushing to main is reserved for the human-reviewed integration -> main PR."
            )
    return None


def _validate_new_branch(name: str) -> dict[str, str] | None:
    """Deny creation of a branch whose name is not a Maestro-shaped branch."""
    if INTEGRATION_BRANCH_RE.match(name) or SUBSYSTEM_BRANCH_RE.match(name):
        return None
    return _deny(
        f"creating branch '{name}' is blocked: Maestro branches must match the integration "
        "shape 'maestro/<slug>' or the subsystem shape 'issue/<n>-<subsystem>' "
        "(e.g. 'issue/12-redirect-resolver')."
    )


def _check_checkout_create(args: Sequence[str]) -> dict[str, str] | None:
    """Validate the new branch name for ``git checkout -b`` / ``git switch -c``."""
    for idx, tok in enumerate(args):
        if tok in _CHECKOUT_CREATE_FLAGS and idx + 1 < len(args):
            return _validate_new_branch(args[idx + 1])
    return None  # not a branch-creating checkout/switch


def _check_branch_create(args: Sequence[str]) -> dict[str, str] | None:
    """Validate the new branch name for a plain ``git branch <name>`` creation."""
    positionals: list[str] = []
    for tok in args:
        if tok.startswith("-"):
            if tok in _BRANCH_NON_CREATE_FLAGS or "=" in tok:
                return None  # listing / deleting / renaming / configuring, not creating
            continue  # an unrecognized boolean flag (e.g. -f/--force); keep scanning
        positionals.append(tok)
    if positionals:
        return _validate_new_branch(positionals[0])
    return None  # `git branch` with no name just lists


def evaluate_command(command: str, current_branch: str | None) -> dict[str, str]:
    """Evaluate a shell command against the git gate rules. First confident denial wins."""
    if not command or not command.strip():
        return _allow()

    for subcommand, args in _iter_git_invocations(command):
        decision: dict[str, str] | None = None
        if subcommand == "commit":
            decision = _check_commit(current_branch)
        elif subcommand == "push":
            decision = _check_push(args, current_branch)
        elif subcommand in ("checkout", "switch"):
            decision = _check_checkout_create(args)
        elif subcommand == "branch":
            decision = _check_branch_create(args)
        if decision is not None:
            return decision
    return _allow()


def resolve_current_branch(cwd: str | None) -> str | None:
    """Best-effort resolution of the current git branch. Returns None if undeterminable."""
    try:
        proc = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    branch = proc.stdout.strip()
    return branch or None


def process_pre_tool_use_hook(
    stdin_data: str,
    branch_resolver: Callable[[str | None], str | None] | None = None,
) -> dict[str, str]:
    """Process a PreToolUse hook payload and decide allow vs deny for a git command.

    Args:
        stdin_data: JSON string passed via stdin by the agent harness.
        branch_resolver: Optional override for resolving the current branch from the command's
            working directory. Defaults to :func:`resolve_current_branch`. Injected in tests.

    Returns:
        Dictionary with 'decision' ('allow' or 'deny') and, on denial, a 'reason'.
    """
    if not stdin_data or not stdin_data.strip():
        return _allow()

    try:
        payload = json.loads(stdin_data)
    except json.JSONDecodeError:
        return _allow()

    if not isinstance(payload, dict):
        return _allow()

    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        return _allow()

    if tool_call.get("name") != "run_command":
        return _allow()

    args = tool_call.get("args")
    if not isinstance(args, dict):
        return _allow()

    command = args.get("CommandLine")
    if not isinstance(command, str):
        return _allow()

    cwd = args.get("Cwd") if isinstance(args.get("Cwd"), str) else None

    resolver = branch_resolver or resolve_current_branch
    current_branch = resolver(cwd)
    return evaluate_command(command, current_branch)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for the PreToolUse git gate hook."""
    parser = argparse.ArgumentParser(
        description="PreToolUse hook adapter enforcing Maestro's git branch non-negotiables."
    )
    parser.add_argument(
        "--branch",
        "-b",
        help="Explicit current branch (overrides git resolution; for testing/diagnostics).",
    )
    args = parser.parse_args(argv)

    try:
        stdin_content = sys.stdin.read()
    except Exception:  # pragma: no cover - defensive
        stdin_content = ""

    resolver = (lambda _cwd: args.branch) if args.branch is not None else None
    result = process_pre_tool_use_hook(stdin_content, branch_resolver=resolver)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

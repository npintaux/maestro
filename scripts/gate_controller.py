#!/usr/bin/env python3
"""Mechanical Gate Orchestrator & Bounded Remediation Controller.

Deterministic state manager and circuit breaker for Maestro phase transitions:
1. Tracks state & interlocks in a state file (.maestro/gate_state.json).
2. Enforces phase prerequisites (cannot advance to Phase N+1 if Phase N gate failed).
3. Enforces a strict 3-attempt remediation budget on gate failures.
4. Tripping the circuit breaker (attempt > 3) hard-halts execution with exit code 3.
5. Exit codes:
   - 0: Gate passed successfully
   - 1: Gate failed, remediation attempt available (attempt <= 3)
   - 2: Interlock / prerequisite blocked or invalid CLI usage
   - 3: Circuit breaker tripped (max attempts exceeded)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_STATE_PATH = ".maestro/gate_state.json"
MAX_REMEDIATION_ATTEMPTS = 3

PHASE_DEPENDENCIES: dict[str, list[str]] = {
    "gate-0": [],
    "gate-adversarial": ["gate-0"],
    "gate-0.5": ["gate-adversarial"],
    "gate-1": ["gate-0.5"],
    "gate-security": ["gate-0.5"],
    "gate-ui": ["gate-0.5"],
    "gate-frontend": ["gate-ui"],
    "gate-2": ["gate-1", "gate-security"],
    "gate-3": ["gate-2"],
    "gate-4": ["gate-3"],
    "boundaries": [],
    "redlock": [],
    "all": [],
}


@dataclass
class GateExecutionRecord:
    """Record of a single gate execution."""

    stage: str
    subsystem: str
    exit_code: int
    attempt: int
    passed: bool
    timestamp: str
    stdout_snippet: str = ""
    stderr_snippet: str = ""


@dataclass
class GateState:
    """Persistent gate state across lifecycle execution."""

    completed_stages: list[str] = field(default_factory=list)
    remediation_attempts: dict[str, int] = field(default_factory=dict)
    execution_history: list[dict[str, Any]] = field(default_factory=list)
    circuit_breaker_tripped: bool = False
    tripped_stage: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GateState:
        """Create state from dictionary."""
        return cls(
            completed_stages=list(data.get("completed_stages", [])),
            remediation_attempts=dict(data.get("remediation_attempts", {})),
            execution_history=list(data.get("execution_history", [])),
            circuit_breaker_tripped=bool(data.get("circuit_breaker_tripped", False)),
            tripped_stage=str(data.get("tripped_stage", "")),
        )


def load_state(state_file: Path | str = DEFAULT_STATE_PATH) -> tuple[GateState, Path]:
    """Load gate state from disk or initialize fresh state."""
    path = Path(state_file)
    if not path.exists():
        return GateState(), path

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return GateState.from_dict(data), path
    except (json.JSONDecodeError, OSError):
        return GateState(), path


def save_state(state: GateState, state_file: Path | str = DEFAULT_STATE_PATH) -> Path:
    """Save gate state to disk."""
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    return path


def check_interlocks(stage: str, state: GateState) -> list[str]:
    """Verify all prerequisite stages have passed before running target stage."""
    prereqs = PHASE_DEPENDENCIES.get(stage, [])
    missing: list[str] = []
    for p in prereqs:
        if p not in state.completed_stages:
            missing.append(p)
    return missing


DEFAULT_RUNNER_SCRIPT = str(Path(__file__).resolve().parent / "run_gate_suite.sh")


def execute_gate(
    stage: str,
    subsystem: str = "",
    state_file: Path | str = DEFAULT_STATE_PATH,
    max_attempts: int = MAX_REMEDIATION_ATTEMPTS,
    runner_script: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Execute a gate stage, enforce interlocks, and update remediation state."""
    runner = runner_script or DEFAULT_RUNNER_SCRIPT
    state, path = load_state(state_file)

    # 1. Check if circuit breaker is already tripped
    if state.circuit_breaker_tripped:
        return 3, {
            "status": "CIRCUIT_BREAKER_TRIPPED",
            "tripped_stage": state.tripped_stage,
            "message": (
                f"Execution is halted because circuit breaker was tripped at stage "
                f"'{state.tripped_stage}'. Reset with `scripts/gate_controller.py reset`."
            ),
        }

    # 2. Check interlocks
    missing_prereqs = check_interlocks(stage, state)
    if missing_prereqs:
        return 2, {
            "status": "INTERLOCK_BLOCKED",
            "stage": stage,
            "missing_prerequisites": missing_prereqs,
            "message": (
                f"Cannot execute '{stage}': prerequisite stages not completed: "
                f"{', '.join(missing_prereqs)}."
            ),
        }

    # 3. Determine attempt number
    stage_key = f"{stage}:{subsystem}" if subsystem else stage
    current_attempt = state.remediation_attempts.get(stage_key, 0) + 1

    if current_attempt > max_attempts:
        state.circuit_breaker_tripped = True
        state.tripped_stage = stage_key
        save_state(state, path)
        return 3, {
            "status": "CIRCUIT_BREAKER_TRIPPED",
            "stage": stage,
            "subsystem": subsystem,
            "attempt": current_attempt,
            "max_attempts": max_attempts,
            "message": (
                f"Remediation attempt budget exceeded ({current_attempt - 1}/{max_attempts}) "
                f"for stage '{stage_key}'. Execution halted."
            ),
        }

    # 4. Execute the gate runner
    cmd = ["bash", runner, stage]
    if subsystem:
        cmd.append(subsystem)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        exit_code = proc.returncode
        stdout_str = proc.stdout
        stderr_str = proc.stderr
    except OSError as err:
        return 2, {
            "status": "RUNNER_ERROR",
            "stage": stage,
            "error": str(err),
            "message": f"Failed to invoke gate runner '{runner}': {err}",
        }

    passed = exit_code == 0
    now_iso = datetime.now(UTC).isoformat()

    record = GateExecutionRecord(
        stage=stage,
        subsystem=subsystem,
        exit_code=exit_code,
        attempt=current_attempt,
        passed=passed,
        timestamp=now_iso,
        stdout_snippet=stdout_str[-1000:] if stdout_str else "",
        stderr_snippet=stderr_str[-1000:] if stderr_str else "",
    )
    state.execution_history.append(asdict(record))

    if passed:
        state.remediation_attempts[stage_key] = 0
        if stage not in state.completed_stages:
            state.completed_stages.append(stage)
        save_state(state, path)
        return 0, {
            "status": "PASSED",
            "stage": stage,
            "subsystem": subsystem,
            "attempt": current_attempt,
            "exit_code": 0,
            "stdout": stdout_str,
        }

    # Failed: record attempt
    state.remediation_attempts[stage_key] = current_attempt
    save_state(state, path)

    return 1, {
        "status": "FAILED",
        "stage": stage,
        "subsystem": subsystem,
        "attempt": current_attempt,
        "max_attempts": max_attempts,
        "can_retry": current_attempt < max_attempts,
        "exit_code": exit_code,
        "stdout": stdout_str,
        "stderr": stderr_str,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for the mechanical gate controller."""
    parser = argparse.ArgumentParser(
        description="Maestro Gate Orchestrator & Bounded Remediation Controller"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run command
    run_parser = subparsers.add_parser("run", help="Run a gate stage through the controller")
    run_parser.add_argument(
        "stage",
        help=(
            "Stage to execute (gate-0, gate-0.5, gate-1, gate-security, gate-ui, "
            "gate-frontend, gate-2..4, all)"
        ),
    )
    run_parser.add_argument(
        "--subsystem",
        default="",
        help="Optional subsystem target name",
    )
    run_parser.add_argument(
        "--state-file",
        default=DEFAULT_STATE_PATH,
        help="Path to state file (default: .maestro/gate_state.json)",
    )
    run_parser.add_argument(
        "--max-attempts",
        type=int,
        default=MAX_REMEDIATION_ATTEMPTS,
        help="Maximum allowed remediation attempts before tripping circuit breaker (default: 3)",
    )
    run_parser.add_argument(
        "--json",
        action="store_true",
        help="Output full JSON report",
    )

    # status command
    status_parser = subparsers.add_parser("status", help="Print current gate status and progress")
    status_parser.add_argument(
        "--state-file",
        default=DEFAULT_STATE_PATH,
        help="Path to state file",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output status as JSON",
    )

    # reset command
    reset_parser = subparsers.add_parser("reset", help="Reset gate state or clear circuit breaker")
    reset_parser.add_argument(
        "--state-file",
        default=DEFAULT_STATE_PATH,
        help="Path to state file",
    )

    args = parser.parse_args(argv)

    if args.command == "status":
        state, _ = load_state(args.state_file)
        if args.json:
            print(json.dumps(state.to_dict(), indent=2))
        else:
            print("==================================================")
            print("📊 Maestro Gate Controller Status")
            print("==================================================")
            print(f"Completed Stages: {', '.join(state.completed_stages) or 'None'}")
            print(f"Circuit Breaker Tripped: {state.circuit_breaker_tripped}")
            if state.circuit_breaker_tripped:
                print(f"Tripped Stage: {state.tripped_stage}")
            if state.remediation_attempts:
                print("Active Remediation Counters:")
                for k, v in state.remediation_attempts.items():
                    print(f"  - {k}: {v}/{MAX_REMEDIATION_ATTEMPTS} attempts")
        return 0

    if args.command == "reset":
        state_path = Path(args.state_file)
        if state_path.exists():
            state_path.unlink()
        print(f"✅ Reset gate controller state ({state_path}).")
        return 0

    if args.command == "run":
        exit_code, result = execute_gate(
            stage=args.stage,
            subsystem=args.subsystem,
            state_file=args.state_file,
            max_attempts=args.max_attempts,
        )

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            status_tag = result.get("status", "UNKNOWN")
            if exit_code == 0:
                print(f"✅ [{args.stage}] {status_tag}: Gate passed successfully.")
            elif exit_code == 1:
                att = result.get("attempt", 1)
                max_att = result.get("max_attempts", 3)
                print(f"⚠️ [{args.stage}] {status_tag}: Gate failed (Attempt {att}/{max_att}).")
                if result.get("stderr"):
                    print(f"Error output:\n{result['stderr']}")
                elif result.get("stdout"):
                    print(f"Output snippet:\n{result['stdout'][-500:]}")
            elif exit_code == 2:
                print(f"🚫 [{args.stage}] {status_tag}: {result.get('message')}")
            elif exit_code == 3:
                print(f"🛑 [{args.stage}] {status_tag}: {result.get('message')}")

        return exit_code

    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""Unit tests for scripts/gate_controller.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.gate_controller import (
    GateState,
    check_interlocks,
    execute_gate,
    load_state,
    main,
    save_state,
)


def test_gate_state_serialization() -> None:
    state = GateState(
        completed_stages=["gate-0", "gate-0.5"],
        remediation_attempts={"gate-2:billing": 1},
        circuit_breaker_tripped=False,
    )
    d = state.to_dict()
    restored = GateState.from_dict(d)
    assert restored.completed_stages == ["gate-0", "gate-0.5"]
    assert restored.remediation_attempts == {"gate-2:billing": 1}
    assert not restored.circuit_breaker_tripped


def test_load_save_state(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    state, path = load_state(state_file)
    assert state.completed_stages == []

    state.completed_stages.append("gate-0")
    save_state(state, state_file)

    loaded, _ = load_state(state_file)
    assert loaded.completed_stages == ["gate-0"]


def test_load_corrupt_state(tmp_path: Path) -> None:
    state_file = tmp_path / "corrupt.json"
    state_file.write_text("{bad json", encoding="utf-8")
    state, _ = load_state(state_file)
    assert state.completed_stages == []


def test_check_interlocks() -> None:
    state = GateState(completed_stages=["gate-0"])
    missing = check_interlocks("gate-0.5", state)
    assert missing == ["gate-adversarial"]

    adv_missing = check_interlocks("gate-adversarial", state)
    assert adv_missing == []

    state.completed_stages.append("gate-adversarial")
    missing_ready = check_interlocks("gate-0.5", state)
    assert missing_ready == []

    missing_2 = check_interlocks("gate-2", state)
    assert "gate-1" in missing_2
    assert "gate-security" in missing_2


def test_check_interlocks_gate_ui() -> None:
    state = GateState(completed_stages=[])
    assert check_interlocks("gate-ui", state) == ["gate-0.5"]

    state.completed_stages.append("gate-0.5")
    assert check_interlocks("gate-ui", state) == []


def test_check_interlocks_gate_frontend() -> None:
    state = GateState(completed_stages=["gate-0.5"])
    # gate-frontend requires the frozen ui-spec (gate-ui) before it can validate the code.
    assert check_interlocks("gate-frontend", state) == ["gate-ui"]

    state.completed_stages.append("gate-ui")
    assert check_interlocks("gate-frontend", state) == []


def test_execute_gate_interlock_blocked(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    exit_code, result = execute_gate(
        stage="gate-2",
        state_file=state_file,
    )
    assert exit_code == 2
    assert result["status"] == "INTERLOCK_BLOCKED"
    assert "missing_prerequisites" in result


def test_execute_gate_success(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "All checks passed"
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc):
        exit_code, result = execute_gate(
            stage="gate-0",
            state_file=state_file,
        )
        assert exit_code == 0
        assert result["status"] == "PASSED"

    loaded, _ = load_state(state_file)
    assert "gate-0" in loaded.completed_stages


def test_execute_gate_failure_and_remediation_loop(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = ""
    mock_proc.stderr = "Linter error"

    with patch("subprocess.run", return_value=mock_proc):
        # Attempt 1
        exit_code_1, res_1 = execute_gate(
            stage="gate-0",
            subsystem="billing",
            state_file=state_file,
            max_attempts=3,
        )
        assert exit_code_1 == 1
        assert res_1["attempt"] == 1
        assert res_1["can_retry"] is True

        # Attempt 2
        exit_code_2, res_2 = execute_gate(
            stage="gate-0",
            subsystem="billing",
            state_file=state_file,
            max_attempts=3,
        )
        assert exit_code_2 == 1
        assert res_2["attempt"] == 2
        assert res_2["can_retry"] is True

        # Attempt 3
        exit_code_3, res_3 = execute_gate(
            stage="gate-0",
            subsystem="billing",
            state_file=state_file,
            max_attempts=3,
        )
        assert exit_code_3 == 1
        assert res_3["attempt"] == 3
        assert res_3["can_retry"] is False

        # Attempt 4: trips circuit breaker
        exit_code_4, res_4 = execute_gate(
            stage="gate-0",
            subsystem="billing",
            state_file=state_file,
            max_attempts=3,
        )
        assert exit_code_4 == 3
        assert res_4["status"] == "CIRCUIT_BREAKER_TRIPPED"

        # Subsequent call when already tripped
        exit_code_5, res_5 = execute_gate(
            stage="gate-0",
            state_file=state_file,
        )
        assert exit_code_5 == 3
        assert res_5["status"] == "CIRCUIT_BREAKER_TRIPPED"


def test_execute_gate_oserror(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    with patch("subprocess.run", side_effect=OSError("Runner script missing")):
        exit_code, result = execute_gate(
            stage="gate-0",
            state_file=state_file,
        )
        assert exit_code == 2
        assert result["status"] == "RUNNER_ERROR"


def test_cli_status_command(tmp_path: Path, capsys: object) -> None:
    state_file = tmp_path / "state.json"
    state = GateState(completed_stages=["gate-0"], remediation_attempts={"gate-1": 2})
    save_state(state, state_file)

    exit_code = main(["status", "--state-file", str(state_file)])
    assert exit_code == 0

    exit_code_json = main(["status", "--state-file", str(state_file), "--json"])
    assert exit_code_json == 0


def test_cli_reset_command(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    state = GateState(completed_stages=["gate-0"])
    save_state(state, state_file)
    assert state_file.exists()

    exit_code = main(["reset", "--state-file", str(state_file)])
    assert exit_code == 0
    assert not state_file.exists()


def test_cli_run_success(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "OK"
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc):
        exit_code = main(["run", "gate-0", "--state-file", str(state_file)])
        assert exit_code == 0


def test_cli_run_failure(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = ""
    mock_proc.stderr = "Linter failure"

    with patch("subprocess.run", return_value=mock_proc):
        exit_code = main(["run", "gate-0", "--state-file", str(state_file)])
        assert exit_code == 1


def test_cli_run_failure_json(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = "some stdout"
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc):
        exit_code = main(["run", "gate-0", "--state-file", str(state_file), "--json"])
        assert exit_code == 1


def test_cli_run_interlock_blocked(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    exit_code = main(["run", "gate-2", "--state-file", str(state_file)])
    assert exit_code == 2


def test_cli_status_tripped(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    state = GateState(
        completed_stages=[],
        circuit_breaker_tripped=True,
        tripped_stage="gate-1",
    )
    save_state(state, state_file)

    exit_code = main(["status", "--state-file", str(state_file)])
    assert exit_code == 0


def test_cli_run_circuit_breaker(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    state = GateState(circuit_breaker_tripped=True, tripped_stage="gate-0")
    save_state(state, state_file)

    exit_code = main(["run", "gate-0", "--state-file", str(state_file)])
    assert exit_code == 3


def test_cli_run_failure_stdout_only(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = "Violation found in audit output"
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc):
        exit_code = main(["run", "gate-0", "--state-file", str(state_file)])
        assert exit_code == 1

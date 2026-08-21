#!/usr/bin/env bash
# Maestro Master Mechanical Gate Suite Runner
# Deterministically runs all stage gates and outputs standardized JSON / exit codes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${MAESTRO_WORKSPACE:-$PWD}"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export MAESTRO_PLUGIN_DIR="${MAESTRO_PLUGIN_DIR:-$PLUGIN_ROOT}"

cd "$TARGET_DIR"

STAGE="${1:-all}"
SUBSYSTEM="${2:-}"

echo "=================================================="
echo "🎯 Running Maestro Mechanical Gates [Stage: $STAGE]"
echo "=================================================="

run_gate_0() {
    echo "▶ [Gate 0] Checking ADR Structural & Sequencing Rules..."
    uv run python3 "$SCRIPT_DIR/validate_adrs.py" docs/adr
    echo "✅ [Gate 0] Passed."
}

run_gate_adversarial() {
    echo "▶ [Gate Adversarial] Checking docs/adr/objections/ Structured Adversarial Review..."
    uv run python3 "$SCRIPT_DIR/validate_adversarial_review.py" docs/adr/objections --required-critics resilience,cost,simplicity --adr-dir docs/adr
    echo "✅ [Gate Adversarial] Passed."
}

run_gate_0_5() {
    echo "▶ [Gate 0.5] Checking Human-in-the-Loop Sign-Off Tokens..."
    uv run python3 "$SCRIPT_DIR/validate_adrs.py" docs/adr --require-approval
    echo "✅ [Gate 0.5] Passed."
}

run_gate_1() {
    echo "▶ [Gate 1] Checking Architecture WAF Compliance & Frozen Decisions..."
    uv run python3 "$SCRIPT_DIR/audit_waf_compliance.py" docs/architecture.md
    echo "✅ [Gate 1] Passed."
}

run_gate_security() {
    echo "▶ [Gate Security] Checking docs/security.md STRIDE Threat Model & IAM Matrix..."
    uv run python3 "$SCRIPT_DIR/audit_security.py" docs/security.md
    echo "✅ [Gate Security] Passed."
}

run_gate_contract() {
    if [ -z "$SUBSYSTEM" ]; then
        echo "▶ [Gate Contract] Validating Contract & Spec across all subsystems in src/modules..."
        local found=0
        for mod in src/modules/*; do
            if [ -d "$mod" ] && [ -f "$mod/openapi.yaml" ]; then
                found=1
                echo "  -> Checking contract for '$mod/openapi.yaml'..."
                uv run python3 "$SCRIPT_DIR/validate_contract.py" "$mod/openapi.yaml"
            fi
        done
        if [ "$found" -eq 0 ]; then
            echo "  (No subsystems with openapi.yaml found in src/modules/)"
        fi
    else
        local spec_path="src/modules/$SUBSYSTEM/openapi.yaml"
        echo "▶ [Gate Contract] Validating Contract & Spec for '$spec_path'..."
        if [ ! -f "$spec_path" ]; then
            echo "❌ Contract file not found: $spec_path"
            exit 1
        fi
        uv run python3 "$SCRIPT_DIR/validate_contract.py" "$spec_path"
    fi
    echo "✅ [Gate Contract] Passed."
}

run_gate_ui() {
    # gate-ui: frozen ui-spec.json contract validation (front-end / UXP track).
    # Optional per subsystem — a subsystem without a ui-spec.json is simply skipped in the
    # all-subsystems sweep. The design system defaults to the shipped corporate tokens, or a
    # project-local design-system/ directory when present.
    local ds_arg=()
    if [ -d "design-system" ]; then
        ds_arg=(--design-system design-system)
    fi
    local prd_arg=()
    if [ -f "docs/PRD.md" ]; then
        prd_arg=(--prd docs/PRD.md)
    fi

    if [ -z "$SUBSYSTEM" ]; then
        echo "▶ [Gate UI] Validating ui-spec.json across all subsystems in src/modules..."
        local found=0
        for mod in src/modules/*; do
            if [ -d "$mod" ] && [ -f "$mod/ui-spec.json" ]; then
                found=1
                echo "  -> Checking ui-spec for '$mod/ui-spec.json'..."
                uv run python3 "$SCRIPT_DIR/validate_ui_spec.py" "$mod/ui-spec.json" "${ds_arg[@]}" "${prd_arg[@]}"
            fi
        done
        if [ "$found" -eq 0 ]; then
            echo "  (No subsystems with ui-spec.json found in src/modules/)"
        fi
    else
        local spec_path="src/modules/$SUBSYSTEM/ui-spec.json"
        echo "▶ [Gate UI] Validating ui-spec for '$spec_path'..."
        if [ ! -f "$spec_path" ]; then
            echo "❌ ui-spec file not found: $spec_path"
            exit 1
        fi
        uv run python3 "$SCRIPT_DIR/validate_ui_spec.py" "$spec_path" "${ds_arg[@]}" "${prd_arg[@]}"
    fi
    echo "✅ [Gate UI] Passed."
}

run_gate_frontend() {
    # gate-frontend: conformance of an implemented Flask/Jinja/CSS front-end to the frozen
    # ui-spec.json + design system (tokens.css sync, zero magic colors, screen bijection, nav
    # wiring). Optional per subsystem — a subsystem without a frontend/ directory is skipped in the
    # all-subsystems sweep. Design system defaults to shipped tokens, or a project-local
    # design-system/ directory when present.
    local ds_arg=()
    if [ -d "design-system" ]; then
        ds_arg=(--design-system design-system)
    fi

    if [ -z "$SUBSYSTEM" ]; then
        echo "▶ [Gate Frontend] Validating front-end conformance across all subsystems in src/modules..."
        local found=0
        for mod in src/modules/*; do
            if [ -d "$mod" ] && [ -d "$mod/frontend" ]; then
                found=1
                echo "  -> Checking front-end for '$mod'..."
                uv run python3 "$SCRIPT_DIR/validate_frontend.py" "$mod" "${ds_arg[@]}"
            fi
        done
        if [ "$found" -eq 0 ]; then
            echo "  (No subsystems with a frontend/ directory found in src/modules/)"
        fi
    else
        local sub_path="src/modules/$SUBSYSTEM"
        echo "▶ [Gate Frontend] Validating front-end conformance for '$sub_path'..."
        if [ ! -d "$sub_path/frontend" ]; then
            echo "❌ front-end directory not found: $sub_path/frontend"
            exit 1
        fi
        uv run python3 "$SCRIPT_DIR/validate_frontend.py" "$sub_path" "${ds_arg[@]}"
    fi
    echo "✅ [Gate Frontend] Passed."
}

run_gate_boundaries() {
    if [ -n "$SUBSYSTEM" ]; then
        local target_paths="${3:-src/modules/$SUBSYSTEM}"
        echo "▶ [Gate Boundary Guard] Verifying workspace boundaries for subsystem '$SUBSYSTEM'..."
        uv run python3 "$SCRIPT_DIR/check_boundaries.py" --subsystem "$SUBSYSTEM" --paths "$target_paths"
        echo "✅ [Gate Boundary Guard] Passed."
    fi
}

run_gate_redlock() {
    if [ -n "$SUBSYSTEM" ]; then
        echo "▶ [Gate RED-Lock] Verifying orthogonal test suite integrity for '$SUBSYSTEM'..."
        uv run python3 "$SCRIPT_DIR/verify_red_suite.py" check --subsystem "$SUBSYSTEM"
        echo "✅ [Gate RED-Lock] Passed."
    fi
}

run_gate_code_quality() {
    if [ -z "$SUBSYSTEM" ]; then
        local target_dir="src"
        local mod_dirs=(src/modules/*)
    else
        local target_dir="src/modules/$SUBSYSTEM"
        local mod_dirs=("src/modules/$SUBSYSTEM")
    fi

    echo "▶ [Gate Code Quality] Running Ruff linter on '$target_dir'..."
    if [ -d "$target_dir" ]; then
        uv run ruff check "$target_dir"
        echo "▶ [Gate Code Quality] Running Ruff format check on '$target_dir'..."
        uv run ruff format --check "$target_dir"
        echo "▶ [Gate Code Quality] Running Mypy strict type check on '$target_dir'..."
        uv run mypy --strict "$target_dir"
    fi

    echo "▶ [Gate Code Quality] Auditing 1-class-per-file and domain purity across module directories..."
    for mod in "${mod_dirs[@]}"; do
        if [ -d "$mod" ]; then
            echo "  -> Auditing implementation for '$mod'..."
            uv run python3 "$SCRIPT_DIR/audit_implementation.py" "$mod"
        fi
    done
    echo "✅ [Gate Code Quality] Passed."
}

run_gate_test_coverage() {
    run_gate_redlock

    if [ -z "$SUBSYSTEM" ]; then
        echo "▶ [Gate Test Coverage] Auditing OpenAPI endpoint coverage across all subsystems..."
        for mod in src/modules/*; do
            if [ -d "$mod" ] && [ -f "$mod/openapi.yaml" ]; then
                echo "  -> Auditing test coverage for '$mod/openapi.yaml'..."
                uv run python3 "$SCRIPT_DIR/audit_test_coverage.py" "$mod/openapi.yaml"
            fi
        done
    else
        local spec_path="src/modules/$SUBSYSTEM/openapi.yaml"
        if [ -f "$spec_path" ]; then
            echo "▶ [Gate Test Coverage] Auditing OpenAPI endpoint coverage for '$spec_path'..."
            uv run python3 "$SCRIPT_DIR/audit_test_coverage.py" "$spec_path"
        fi
    fi

    echo "▶ [Gate Test Coverage] Running Pytest unit & behavioral test suites..."
    if [ -d "tests" ] && [ -n "$(find tests -name 'test_*.py' 2>/dev/null)" ]; then
        uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=100
    fi
    echo "✅ [Gate Test Coverage] Passed."
}

case "$STAGE" in
    gate-0)
        run_gate_0
        ;;
    gate-adversarial|adversarial)
        run_gate_adversarial
        ;;
    gate-0.5)
        run_gate_0
        if [ -d "docs/adr/objections" ]; then
            run_gate_adversarial
        fi
        run_gate_0_5
        ;;
    gate-1)
        run_gate_0
        run_gate_0_5
        run_gate_1
        ;;
    gate-security|security)
        run_gate_security
        ;;
    gate-ui|ui)
        run_gate_ui
        ;;
    gate-frontend|frontend)
        run_gate_frontend
        ;;
    gate-2|gate-contract|contract)
        run_gate_contract
        ;;
    gate-3|gate-code-quality|code-quality)
        run_gate_code_quality
        ;;
    gate-4|gate-test-coverage|test-coverage)
        run_gate_test_coverage
        ;;
    boundaries|gate-boundary)
        run_gate_boundaries
        ;;
    redlock|gate-redlock)
        run_gate_redlock
        ;;
    all)
        if [ -d "docs/adr" ]; then
            run_gate_0
            if [ -d "docs/adr/objections" ]; then
                run_gate_adversarial
            fi
            run_gate_0_5
        fi
        if [ -f "docs/architecture.md" ]; then
            run_gate_1
        fi
        if [ -f "docs/security.md" ]; then
            run_gate_security
        fi
        if [ -d "src/modules" ]; then
            run_gate_contract
            run_gate_ui
            run_gate_frontend
            run_gate_code_quality
        fi
        run_gate_test_coverage
        ;;
    *)
        echo "❌ Unknown stage '$STAGE'. Valid stages: gate-0, gate-adversarial, gate-0.5, gate-1, gate-security, gate-ui, gate-frontend, gate-2 (contract), gate-3 (code-quality), gate-4 (test-coverage), boundaries, redlock, all"
        exit 1
        ;;
esac

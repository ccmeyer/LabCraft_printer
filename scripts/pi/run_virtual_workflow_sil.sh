#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ALLOWED_ROOT="$REPO_ROOT/verification_reports/virtual_workflows"

usage() {
  printf '%s\n' \
    "Usage:" \
    "  $0 preflight [--output-root PATH] [--qt-platform offscreen|minimal] [--output PATH]" \
    "  $0 prove --preflight PATH [--output-root PATH] [--qt-platform PLATFORM] [--output PATH]" \
    "  $0 collect --preflight PATH --proof PATH [run_virtual_workflow options]" \
    "  $0 replay --aggregate PATH [--output-root PATH]" \
    "  $0 bundle (--report-set PATH | --aggregate PATH [...]) --proof PATH --trace PATH --output PATH" \
    "  $0 cleanup --manifest PATH [--output-root PATH]" \
    "" \
    "All scenario execution is forced through a Bubblewrap private-device sandbox."
}

if [ "$#" -lt 1 ]; then
  usage
  exit 3
fi

MODE="$1"
shift

if [ -x "$REPO_ROOT/venv/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/venv/bin/python"
elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
elif [ -x "$REPO_ROOT/env/bin/python" ]; then
  PYTHON_BIN="$REPO_ROOT/env/bin/python"
else
  printf 'Pi SIL error: no repository-local Python interpreter was found.\n' >&2
  exit 3
fi

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Pi SIL error: required command is missing: %s\n' "$1" >&2
    exit 3
  fi
}

require_command bwrap
require_command strace
require_command findmnt

OUTPUT_ROOT="$ALLOWED_ROOT/pi-sil"
QT_PLATFORM="offscreen"
PREFLIGHT_PATH=""
PROOF_PATH=""
TRACE_PATH=""
REPORT_SET_PATH=""
AGGREGATE_PATHS=()
OUTPUT_PATH=""
MANIFEST_PATH=""
RUNNER_ARGS=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --output-root)
      OUTPUT_ROOT="$2"
      shift 2
      ;;
    --qt-platform)
      QT_PLATFORM="$2"
      shift 2
      ;;
    --preflight)
      PREFLIGHT_PATH="$2"
      shift 2
      ;;
    --proof)
      PROOF_PATH="$2"
      shift 2
      ;;
    --trace)
      TRACE_PATH="$2"
      shift 2
      ;;
    --report-set)
      REPORT_SET_PATH="$2"
      shift 2
      ;;
    --aggregate)
      AGGREGATE_PATHS+=("$2")
      shift 2
      ;;
    --output)
      OUTPUT_PATH="$2"
      shift 2
      ;;
    --manifest)
      MANIFEST_PATH="$2"
      shift 2
      ;;
    --)
      shift
      RUNNER_ARGS+=("$@")
      break
      ;;
    *)
      if [ "$MODE" = "collect" ]; then
        RUNNER_ARGS+=("$1")
        shift
      else
        printf 'Pi SIL error: unknown %s option: %s\n' "$MODE" "$1" >&2
        usage
        exit 3
      fi
      ;;
  esac
done

case "$QT_PLATFORM" in
  offscreen|minimal) ;;
  *)
    printf 'Pi SIL error: unsupported Qt platform: %s\n' "$QT_PLATFORM" >&2
    exit 3
    ;;
esac

mkdir -p "$OUTPUT_ROOT"
OUTPUT_ROOT="$(realpath "$OUTPUT_ROOT")"
ALLOWED_ROOT="$(realpath "$ALLOWED_ROOT")"
case "$OUTPUT_ROOT/" in
  "$ALLOWED_ROOT/"*) ;;
  *)
    printf 'Pi SIL error: output root must be beneath %s\n' "$ALLOWED_ROOT" >&2
    exit 3
    ;;
esac

sandbox_exec() {
  bwrap \
    --unshare-all \
    --die-with-parent \
    --new-session \
    --ro-bind / / \
    --dev /dev \
    --proc /proc \
    --tmpfs /tmp \
    --bind "$OUTPUT_ROOT" "$OUTPUT_ROOT" \
    --chdir "$REPO_ROOT" \
    --setenv QT_QPA_PLATFORM "$QT_PLATFORM" \
    --setenv PYTHONDONTWRITEBYTECODE "1" \
    --setenv PYTHONUNBUFFERED "1" \
    --setenv XDG_CACHE_HOME "/tmp/xdg-cache" \
    --setenv XDG_RUNTIME_DIR "/tmp" \
    "$@"
}

case "$MODE" in
  preflight)
    if [ -z "$OUTPUT_PATH" ]; then
      STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
      OUTPUT_PATH="$OUTPUT_ROOT/pi-safety-$STAMP/preflight.json"
    fi
    mkdir -p "$(dirname "$OUTPUT_PATH")"
    sandbox_exec "$PYTHON_BIN" -m tools.virtual_workflows.pi_sil preflight \
      --repo-root "$REPO_ROOT" \
      --output-root "$OUTPUT_ROOT" \
      --qt-platform "$QT_PLATFORM" \
      --output "$OUTPUT_PATH"
    ;;

  prove)
    if [ -z "$PREFLIGHT_PATH" ] || [ ! -f "$PREFLIGHT_PATH" ]; then
      printf 'Pi SIL error: prove requires an existing --preflight file.\n' >&2
      exit 3
    fi
    PROOF_DIR="$(dirname "$PREFLIGHT_PATH")"
    AUDIT_ROOT="$PROOF_DIR/audit"
    TRACE_PATH="$PROOF_DIR/hardware_access_trace.txt"
    if [ -z "$OUTPUT_PATH" ]; then
      OUTPUT_PATH="$PROOF_DIR/hardware_proof.json"
    fi
    mkdir -p "$AUDIT_ROOT"
    set +e
    AUDIT_OUTPUT="$(
      sandbox_exec strace -f -yy -qq \
        -e trace=%file,ioctl,process \
        -o "$TRACE_PATH" \
        "$PYTHON_BIN" tools/run_virtual_workflow.py \
        --scenario virtual_print_array_96_v1 \
        --output-root "$AUDIT_ROOT" \
        --qt-platform "$QT_PLATFORM" \
        --speed-multiplier 100 \
        --timeout-seconds 600 2>&1
    )"
    AUDIT_CODE="$?"
    set -e
    printf '%s\n' "$AUDIT_OUTPUT"
    if [ "$AUDIT_CODE" -ne 0 ]; then
      printf 'Pi SIL error: traced safety scenario exited %s.\n' "$AUDIT_CODE" >&2
      exit "$AUDIT_CODE"
    fi
    AUDIT_REPORT="$(
      find "$AUDIT_ROOT" -type f -name report.json -print | sort | tail -n 1
    )"
    if [ -z "$AUDIT_REPORT" ]; then
      printf 'Pi SIL error: traced safety scenario produced no report.\n' >&2
      exit 3
    fi
    sandbox_exec "$PYTHON_BIN" -m tools.virtual_workflows.pi_sil validate-trace \
      --preflight "$PREFLIGHT_PATH" \
      --trace "$TRACE_PATH" \
      --audit-report "$AUDIT_REPORT" \
      --output "$OUTPUT_PATH"
    ;;

  collect)
    if [ -z "$PREFLIGHT_PATH" ] || [ ! -f "$PREFLIGHT_PATH" ]; then
      printf 'Pi SIL error: collect requires an existing --preflight file.\n' >&2
      exit 3
    fi
    if [ -z "$PROOF_PATH" ] || [ ! -f "$PROOF_PATH" ]; then
      printf 'Pi SIL error: collect requires an existing --proof file.\n' >&2
      exit 3
    fi
    sandbox_exec "$PYTHON_BIN" tools/run_virtual_workflow.py \
      --output-root "$OUTPUT_ROOT" \
      --qt-platform "$QT_PLATFORM" \
      --target-pi \
      --pi-preflight "$PREFLIGHT_PATH" \
      --pi-hardware-proof "$PROOF_PATH" \
      "${RUNNER_ARGS[@]}"
    ;;

  replay)
    if [ "${#AGGREGATE_PATHS[@]}" -ne 1 ]; then
      printf 'Pi SIL error: replay requires exactly one --aggregate.\n' >&2
      exit 3
    fi
    sandbox_exec "$PYTHON_BIN" -m tools.virtual_workflows.pi_sil replay-suite \
      --repo-root "$REPO_ROOT" \
      --output-root "$OUTPUT_ROOT" \
      --aggregate "${AGGREGATE_PATHS[0]}"
    ;;

  bundle)
    if [ -z "$PROOF_PATH" ] || [ -z "$TRACE_PATH" ] || [ -z "$OUTPUT_PATH" ]; then
      printf 'Pi SIL error: bundle requires proof, trace, and output.\n' >&2
      exit 3
    fi
    if { [ -n "$REPORT_SET_PATH" ] && [ "${#AGGREGATE_PATHS[@]}" -ne 0 ]; } ||
       { [ -z "$REPORT_SET_PATH" ] && [ "${#AGGREGATE_PATHS[@]}" -eq 0 ]; }; then
      printf 'Pi SIL error: bundle requires exactly one entrypoint kind.\n' >&2
      exit 3
    fi
    BUNDLE_ARGS=(
      --repo-root "$REPO_ROOT"
      --proof "$PROOF_PATH"
      --trace "$TRACE_PATH"
      --output "$OUTPUT_PATH"
    )
    if [ -n "$REPORT_SET_PATH" ]; then
      BUNDLE_ARGS+=(--report-set "$REPORT_SET_PATH")
    else
      for aggregate_path in "${AGGREGATE_PATHS[@]}"; do
        BUNDLE_ARGS+=(--aggregate "$aggregate_path")
      done
    fi
    sandbox_exec "$PYTHON_BIN" -m tools.virtual_workflows.pi_sil bundle \
      "${BUNDLE_ARGS[@]}"
    ;;

  cleanup)
    if [ -z "$MANIFEST_PATH" ] || [ ! -f "$MANIFEST_PATH" ]; then
      printf 'Pi SIL error: cleanup requires an existing --manifest file.\n' >&2
      exit 3
    fi
    sandbox_exec "$PYTHON_BIN" -m tools.virtual_workflows.pi_sil cleanup \
      --manifest "$MANIFEST_PATH" \
      --repo-root "$REPO_ROOT" \
      --output-root "$OUTPUT_ROOT"
    ;;

  *)
    printf 'Pi SIL error: unknown mode: %s\n' "$MODE" >&2
    usage
    exit 3
    ;;
esac

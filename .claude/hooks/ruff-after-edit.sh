#!/usr/bin/env bash
# PostToolUse hook: lint and type-check a Python file after Edit or Write.
# Always exits 0, so a failed check is reported but never blocks the edit.

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

file_path=$(jq -r '.tool_input.file_path // empty')

case "$file_path" in
  *.py) ;;
  *) exit 0 ;;
esac
[[ -f "$file_path" ]] || exit 0

# Auto-fix what ruff can; show what it cannot.
uv run ruff check --fix "$file_path" >&2 || true

# Type-check only the agents code, with the project's virtual environment.
case "$file_path" in
  "$PWD"/services/*)
    pyright --pythonpath "$(uv run which python)" "$file_path" >&2 || true
    ;;
esac

exit 0

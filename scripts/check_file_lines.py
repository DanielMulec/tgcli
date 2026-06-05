from __future__ import annotations

from pathlib import Path

MAX_CODE_LINES = 400
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOTS = [PROJECT_ROOT / "src", PROJECT_ROOT / "tests", PROJECT_ROOT / "scripts"]


def python_files() -> list[Path]:
    files: list[Path] = []
    for root in CODE_ROOTS:
        files.extend(root.rglob("*.py"))
    return sorted(files)


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def oversized_files() -> list[str]:
    violations: list[str] = []
    for path in python_files():
        lines = line_count(path)
        if lines > MAX_CODE_LINES:
            relative_path = path.relative_to(PROJECT_ROOT)
            violations.append(f"{relative_path}: {lines} lines")
    return violations


def main() -> int:
    violations = oversized_files()
    if not violations:
        return 0
    print(f"Python code files must be at most {MAX_CODE_LINES} lines.")
    for violation in violations:
        print(violation)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

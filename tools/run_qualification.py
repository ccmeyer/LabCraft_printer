from __future__ import annotations

try:
    from qualification.cli import main
except ModuleNotFoundError:
    from tools.qualification.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

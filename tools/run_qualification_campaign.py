from __future__ import annotations

try:
    from qualification.campaign_cli import main
except ModuleNotFoundError:
    from tools.qualification.campaign_cli import main


if __name__ == "__main__":
    raise SystemExit(main())

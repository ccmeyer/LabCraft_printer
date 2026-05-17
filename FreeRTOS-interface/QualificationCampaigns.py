from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tools.qualification.campaign import CampaignError, QualificationCampaign, load_campaign


@dataclass(frozen=True)
class QualificationCampaignEntry:
    campaign_path: Path
    campaign: QualificationCampaign

    @property
    def campaign_id(self) -> str:
        return self.campaign.campaign_id

    @property
    def display_name(self) -> str:
        suffix = "operator-gated" if self.campaign.requires_operator_prompts else "local"
        return f"{self.campaign.name}  |  {suffix}  |  {len(self.campaign.steps)} suites"


def default_campaign_root(repo_root: str | Path) -> Path:
    return Path(repo_root) / "tools" / "qualification" / "campaigns"


def discover_campaign_entries(root: str | Path) -> list[QualificationCampaignEntry]:
    campaign_root = Path(root)
    if not campaign_root.exists():
        return []

    entries: list[QualificationCampaignEntry] = []
    for campaign_path in campaign_root.glob("*.json"):
        try:
            entries.append(QualificationCampaignEntry(campaign_path=campaign_path, campaign=load_campaign(campaign_path)))
        except CampaignError:
            continue
    entries.sort(key=lambda item: _campaign_sort_key(item.campaign.campaign_id))
    return entries


def _campaign_sort_key(campaign_id: str) -> tuple[int, str]:
    preferred = {
        "machine_full_qualification_v1": 0,
    }
    return (preferred.get(campaign_id, 100), campaign_id)

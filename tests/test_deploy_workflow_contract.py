from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_prod_nexus_deploy_workflow_runs_publish_smoke() -> None:
    workflow = (ROOT / ".github/workflows/deploy-nexus-prod.yml").read_text(encoding="utf-8")

    assert "Validate Nexus Redis overlay publish" in workflow
    assert "scripts/check_nexus_publish.py" in workflow
    assert '--symbols "SPY,QQQ,IWM"' in workflow


def test_prod_nexus_validation_workflow_is_scheduled_for_market_open() -> None:
    workflow = (ROOT / ".github/workflows/validate-nexus-prod.yml").read_text(encoding="utf-8")

    assert 'cron: "40 13 * * 1-5"' in workflow
    assert 'cron: "40 14 * * 1-5"' in workflow
    assert "scripts/check_nexus_publish.py" in workflow

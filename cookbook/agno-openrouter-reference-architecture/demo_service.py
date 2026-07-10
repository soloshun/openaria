"""Cookbook-owned FastAPI simulator for one synthetic pipeline incident."""

from pathlib import Path

from fastapi import FastAPI, HTTPException

app = FastAPI(title="OpenARIA synthetic incident estate", version="0.1.0")

INCIDENT_ID = "schema-drift-001"

_INCIDENT = {
    "id": INCIDENT_ID,
    "source_tool": "synthetic_prefect",
    "pipeline_name": "stock_feature_pipeline",
    "environment": "demo",
    "status": "open",
}

_CONTEXT = {
    "logs": ["transform_prices failed with KeyError: 'Close'"],
    "metrics": {"failure_count": 1, "last_success_age_minutes": 1440},
    "lineage": {
        "upstream": ["yfinance_extract"],
        "downstream": ["moving_average_features", "daily_stock_dashboard"],
    },
    "schema": {
        "expected": ["Date", "Open", "High", "Low", "Close", "Volume"],
        "current": ["Date", "Open", "High", "Low", "closing_price", "Volume"],
    },
    "verification": {"status": "not_run", "notes": "No remediation is available in this cookbook."},
}

_KNOWLEDGE_ROOT = Path(__file__).parent / "knowledge"


def _require_incident(incident_id: str) -> None:
    if incident_id != INCIDENT_ID:
        raise HTTPException(status_code=404, detail="Synthetic incident not found")


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str) -> dict[str, object]:
    """Return the normalized synthetic incident."""
    _require_incident(incident_id)
    return _INCIDENT


@app.get("/incidents/{incident_id}/context/{context_name}")
def get_context(incident_id: str, context_name: str) -> object:
    """Return one bounded synthetic context item for an agent tool."""
    _require_incident(incident_id)
    if context_name not in _CONTEXT:
        raise HTTPException(status_code=404, detail="Synthetic context item not found")
    return _CONTEXT[context_name]


@app.get("/knowledge/{knowledge_type}/{document_name}")
def read_knowledge(knowledge_type: str, document_name: str) -> dict[str, str]:
    """Return one cookbook-owned runbook or playbook Markdown document."""
    if knowledge_type not in {"runbooks", "playbooks"}:
        raise HTTPException(status_code=404, detail="Knowledge type not found")
    if Path(document_name).name != document_name:
        raise HTTPException(status_code=400, detail="Invalid knowledge document name")

    document_path = _KNOWLEDGE_ROOT / knowledge_type / f"{document_name}.md"
    if not document_path.is_file():
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return {"name": document_name, "content": document_path.read_text(encoding="utf-8")}

"""Tests for all provider-independent agent output contracts."""

import json

import pytest
from pydantic import BaseModel, ValidationError

from autonomous_ai_company.schemas.agent_outputs import (
    CEOAgentOutput,
    DataScientistAgentOutput,
    FinanceAgentOutput,
    MarketingAgentOutput,
    ReportAgentOutput,
)


ModelCase = tuple[type[BaseModel], dict[str, object], str, object]

MODEL_CASES: tuple[ModelCase, ...] = (
    (
        FinanceAgentOutput,
        {
            "executive_summary": "Revenue is growing with manageable risk.",
            "key_findings": ["Gross margin improved."],
            "recommendations": ["Maintain pricing discipline."],
            "risk_level": "low",
            "confidence_score": 0.91,
        },
        "executive_summary",
        123,
    ),
    (
        MarketingAgentOutput,
        {
            "executive_summary": "Retention is the strongest growth lever.",
            "key_findings": ["Repeat purchases increased."],
            "opportunities": ["Expand the loyalty campaign."],
            "recommendations": ["Test segmented retention offers."],
            "confidence_score": 0.84,
        },
        "opportunities",
        "not-a-list",
    ),
    (
        DataScientistAgentOutput,
        {
            "executive_summary": "The forecast indicates moderate growth.",
            "model_interpretation": "Holdout error is within tolerance.",
            "forecast_outlook": "Sales are likely to rise next quarter.",
            "limitations": ["The history covers only twelve months."],
            "recommendations": ["Retrain after the next quarter closes."],
            "confidence_score": 0.78,
        },
        "model_interpretation",
        ["not", "a", "string"],
    ),
    (
        ReportAgentOutput,
        {
            "title": "Quarterly Business Review",
            "executive_summary": "Performance is stable with upside potential.",
            "sections": {"finance": "Margins improved."},
            "key_recommendations": ["Prioritize retention."],
            "unavailable_sections": [],
        },
        "sections",
        ["not", "a", "mapping"],
    ),
    (
        CEOAgentOutput,
        {
            "executive_summary": "The company is positioned for steady growth.",
            "business_health": "stable",
            "strategic_priorities": ["Protect margin."],
            "key_risks": ["Customer concentration."],
            "final_recommendation": "Invest selectively in retention.",
            "confidence_score": 0.88,
        },
        "strategic_priorities",
        "not-a-list",
    ),
)


@pytest.mark.parametrize(("model_type", "valid_data", "_", "__"), MODEL_CASES)
def test_agent_output_accepts_valid_data_and_serializes_to_json(
    model_type: type[BaseModel],
    valid_data: dict[str, object],
    _: str,
    __: object,
) -> None:
    """Every valid agent contract should round-trip through JSON."""

    output = model_type.model_validate(valid_data)

    assert json.loads(output.model_dump_json()) == valid_data


@pytest.mark.parametrize(
    ("model_type", "valid_data", "required_field", "_"),
    MODEL_CASES,
)
def test_agent_output_rejects_missing_required_field(
    model_type: type[BaseModel],
    valid_data: dict[str, object],
    required_field: str,
    _: object,
) -> None:
    """Incomplete agent responses should fail instead of being guessed."""

    incomplete_data = valid_data.copy()
    incomplete_data.pop(required_field)

    with pytest.raises(ValidationError):
        model_type.model_validate(incomplete_data)


@pytest.mark.parametrize(
    ("model_type", "valid_data", "invalid_field", "invalid_value"),
    MODEL_CASES,
)
def test_agent_output_rejects_invalid_field_type(
    model_type: type[BaseModel],
    valid_data: dict[str, object],
    invalid_field: str,
    invalid_value: object,
) -> None:
    """Strict schemas should reject malformed types returned by an LLM."""

    invalid_data = {**valid_data, invalid_field: invalid_value}

    with pytest.raises(ValidationError):
        model_type.model_validate(invalid_data)


@pytest.mark.parametrize(("model_type", "_", "__", "___"), MODEL_CASES)
def test_every_schema_field_has_a_description(
    model_type: type[BaseModel],
    _: dict[str, object],
    __: str,
    ___: object,
) -> None:
    """Generated JSON schemas should explain every field to callers."""

    assert all(field.description for field in model_type.model_fields.values())

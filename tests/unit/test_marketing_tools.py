"""Unit tests for deterministic Decimal marketing calculations."""

import json
from decimal import Decimal

import pytest

from autonomous_ai_company.exceptions import InvalidDatasetError
from autonomous_ai_company.tools.marketing_tools import (
    MarketingDataset,
    average_order_value,
    calculate_marketing_kpis,
    churn_rate,
    customer_count,
    customer_growth,
    repeat_customer_rate,
    retention_rate,
    revenue_by_segment,
    top_segments,
)


CURRENT_PERIOD: MarketingDataset = (
    {"customer_id": "c1", "revenue": Decimal("100.105"), "segment": "Enterprise"},
    {"customer_id": "c1", "revenue": Decimal("50.105"), "segment": "Enterprise"},
    {"customer_id": "c2", "revenue": Decimal("75.555"), "segment": "SMB"},
    {"customer_id": "c3", "revenue": 25, "segment": "Enterprise"},
)
PREVIOUS_PERIOD: MarketingDataset = (
    {"customer_id": "c1", "revenue": 80.0, "segment": "Enterprise"},
    {"customer_id": "c2", "revenue": 60, "segment": "SMB"},
    {"customer_id": "c4", "revenue": 40, "segment": "SMB"},
    {"customer_id": "c5", "revenue": 20, "segment": "Consumer"},
)


def test_individual_marketing_kpis_are_exact_and_deterministic() -> None:
    """Every public calculation should return its known Decimal result."""

    assert customer_count(CURRENT_PERIOD) == 3
    assert repeat_customer_rate(CURRENT_PERIOD) == Decimal("33.33")
    assert average_order_value(CURRENT_PERIOD) == Decimal("62.69")
    assert customer_growth(CURRENT_PERIOD, PREVIOUS_PERIOD) == Decimal("-25.00")
    assert retention_rate(CURRENT_PERIOD, PREVIOUS_PERIOD) == Decimal("50.00")
    assert churn_rate(CURRENT_PERIOD, PREVIOUS_PERIOD) == Decimal("50.00")
    assert revenue_by_segment(CURRENT_PERIOD) == {
        "Enterprise": Decimal("175.20"),
        "SMB": Decimal("75.56"),
    }
    assert top_segments(CURRENT_PERIOD) == ["Enterprise", "SMB"]


def test_calculate_marketing_kpis_returns_complete_decimal_contract() -> None:
    """The aggregate tool should calculate all KPIs from normalized data once."""

    kpis = calculate_marketing_kpis(CURRENT_PERIOD, PREVIOUS_PERIOD)

    assert kpis == {
        "customer_count": 3,
        "repeat_customer_rate": Decimal("33.33"),
        "average_order_value": Decimal("62.69"),
        "customer_growth": Decimal("-25.00"),
        "retention_rate": Decimal("50.00"),
        "churn_rate": Decimal("50.00"),
        "top_segments": ["Enterprise", "SMB"],
        "revenue_by_segment": {
            "Enterprise": Decimal("175.20"),
            "SMB": Decimal("75.56"),
        },
    }
    serialized = json.loads(json.dumps(kpis, default=str))
    assert serialized["average_order_value"] == "62.69"
    assert serialized["revenue_by_segment"]["Enterprise"] == "175.20"


def test_segment_ranking_uses_alphabetical_tie_breaking_and_limit() -> None:
    """Equal revenue must produce stable ranking independent of row order."""

    tied: MarketingDataset = (
        {"customer_id": "c1", "revenue": 10, "segment": "Zulu"},
        {"customer_id": "c2", "revenue": 10, "segment": "Alpha"},
        {"customer_id": "c3", "revenue": 5, "segment": "Beta"},
    )

    assert top_segments(tied, limit=2) == ["Alpha", "Zulu"]


@pytest.mark.parametrize("limit", (True, 0, -1, 1.5))
def test_top_segments_rejects_invalid_limits(limit: object) -> None:
    """Ranking limits must be positive integers and never booleans."""

    with pytest.raises(ValueError, match="positive integer"):
        top_segments(CURRENT_PERIOD, limit=limit)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("dataset", "message"),
    (
        (object(), "sequence of row mappings"),
        ("not-a-dataset", "sequence of row mappings"),
        ([], "at least one row"),
        (["row"], "row 0 must be a mapping"),
        ([{"revenue": 1, "segment": "SMB"}], "customer_id"),
        ([{"customer_id": "c1", "segment": "SMB"}], "revenue"),
        ([{"customer_id": "c1", "revenue": 1}], "segment"),
        (
            [{"customer_id": 1, "revenue": 1, "segment": "SMB"}],
            "customer_id must be a string",
        ),
        (
            [{"customer_id": "  ", "revenue": 1, "segment": "SMB"}],
            "customer_id must be non-empty",
        ),
        (
            [{"customer_id": "c1", "revenue": 1, "segment": 2}],
            "segment must be a string",
        ),
        (
            [{"customer_id": "c1", "revenue": 1, "segment": "  "}],
            "segment must be non-empty",
        ),
        (
            [{"customer_id": "c1", "revenue": "1", "segment": "SMB"}],
            "must be an int, float, or Decimal",
        ),
        (
            [{"customer_id": "c1", "revenue": True, "segment": "SMB"}],
            "must be an int, float, or Decimal",
        ),
        (
            [{"customer_id": "c1", "revenue": float("nan"), "segment": "SMB"}],
            "finite number",
        ),
        (
            [{"customer_id": "c1", "revenue": Decimal("Infinity"), "segment": "SMB"}],
            "finite number",
        ),
        (
            [{"customer_id": "c1", "revenue": -1, "segment": "SMB"}],
            "must not be negative",
        ),
        (
            [{"customer_id": "c1", "revenue": Decimal("1E+100"), "segment": "SMB"}],
            "exceeds supported precision",
        ),
    ),
)
def test_dataset_validation_raises_domain_error_with_cause(
    dataset: object,
    message: str,
) -> None:
    """Malformed rows should cross the tool boundary as InvalidDatasetError."""

    with pytest.raises(InvalidDatasetError, match=message) as captured:
        customer_count(dataset)  # type: ignore[arg-type]

    assert isinstance(captured.value.__cause__, (TypeError, ValueError, KeyError))


def test_tools_do_not_mutate_caller_records() -> None:
    """Normalization must not rewrite identifiers, segments, or revenue values."""

    dataset = [{"customer_id": " c1 ", "revenue": Decimal("1.005"), "segment": " SMB "}]
    original = [dict(dataset[0])]

    assert calculate_marketing_kpis(dataset, dataset)["average_order_value"] == Decimal(
        "1.00"
    )
    assert dataset == original

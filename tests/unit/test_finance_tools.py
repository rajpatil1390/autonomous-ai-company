"""Tests for exact deterministic finance calculation tools."""

import json
from collections.abc import Callable
from decimal import Decimal

import pytest

from autonomous_ai_company.exceptions import (
    InvalidDatasetError,
    UndefinedMetricError,
)
from autonomous_ai_company.tools.finance_tools import (
    FinancialDataset,
    average_order_value,
    calculate_kpis,
    profit_margin,
    revenue_growth_rate,
    total_cost,
    total_profit,
    total_revenue,
)


CURRENT_PERIOD: FinancialDataset = (
    {"revenue": 100, "cost": 60},
    {"revenue": 200.0, "cost": 120.0},
)
PREVIOUS_PERIOD: FinancialDataset = (
    {"revenue": 80, "cost": 50},
    {"revenue": 120, "cost": 70},
)


def test_individual_kpis_return_expected_decimal_values() -> None:
    """Each public calculation should return the exact known Decimal result."""

    assert total_revenue(CURRENT_PERIOD) == Decimal("300.00")
    assert total_cost(CURRENT_PERIOD) == Decimal("180.00")
    assert total_profit(CURRENT_PERIOD) == Decimal("120.00")
    assert average_order_value(CURRENT_PERIOD) == Decimal("150.00")
    assert profit_margin(CURRENT_PERIOD) == Decimal("40.00")
    assert revenue_growth_rate(CURRENT_PERIOD, PREVIOUS_PERIOD) == Decimal("50.00")


def test_calculate_kpis_returns_complete_decimal_dictionary() -> None:
    """The aggregate entry point should preserve keys and use Decimal values."""

    assert calculate_kpis(CURRENT_PERIOD, PREVIOUS_PERIOD) == {
        "total_revenue": Decimal("300.00"),
        "total_profit": Decimal("120.00"),
        "total_cost": Decimal("180.00"),
        "average_order_value": Decimal("150.00"),
        "profit_margin": Decimal("40.00"),
        "revenue_growth_rate": Decimal("50.00"),
    }


def test_decimal_inputs_preserve_exact_precision() -> None:
    """Decimal inputs should never pass through binary floating point."""

    dataset: FinancialDataset = (
        {"revenue": Decimal("0.10"), "cost": Decimal("0.03")},
        {"revenue": Decimal("0.20"), "cost": Decimal("0.06")},
    )

    assert total_revenue(dataset) == Decimal("0.30")
    assert total_cost(dataset) == Decimal("0.09")
    assert total_profit(dataset) == Decimal("0.21")


def test_decimal_kpis_serialize_as_exact_json_strings() -> None:
    """JSON boundaries should encode Decimal values as strings, not floats."""

    serialized = json.dumps(
        calculate_kpis(CURRENT_PERIOD, PREVIOUS_PERIOD),
        default=str,
        sort_keys=True,
    )
    decoded = json.loads(serialized)

    assert decoded == {
        "average_order_value": "150.00",
        "profit_margin": "40.00",
        "revenue_growth_rate": "50.00",
        "total_cost": "180.00",
        "total_profit": "120.00",
        "total_revenue": "300.00",
    }


def test_rounding_policy_uses_half_even_for_money_and_percentages() -> None:
    """Midpoints should follow the documented unbiased half-even policy."""

    rounded_inputs: FinancialDataset = (
        {"revenue": Decimal("10.005"), "cost": Decimal("0.005")},
        {"revenue": Decimal("10.015"), "cost": Decimal("0.015")},
    )
    repeating_percentage: FinancialDataset = (
        {"revenue": Decimal("3.00"), "cost": Decimal("2.00")},
    )

    assert total_revenue(rounded_inputs) == Decimal("20.02")
    assert total_cost(rounded_inputs) == Decimal("0.02")
    assert average_order_value(
        (
            {"revenue": Decimal("10.01")},
            {"revenue": Decimal("0.00")},
        )
    ) == Decimal("5.00")
    assert profit_margin(repeating_percentage) == Decimal("33.33")
    assert revenue_growth_rate(
        ({"revenue": Decimal("4.00")},),
        ({"revenue": Decimal("3.00")},),
    ) == Decimal("33.33")


def test_large_monetary_values_remain_exact() -> None:
    """Large valid amounts should aggregate without binary precision loss."""

    dataset: FinancialDataset = (
        {
            "revenue": Decimal("999999999999999999999999999999999999.99"),
            "cost": Decimal("0.01"),
        },
        {"revenue": Decimal("0.01"), "cost": Decimal("0.01")},
    )

    assert total_revenue(dataset) == Decimal("1000000000000000000000000000000000000.00")
    assert total_cost(dataset) == Decimal("0.02")


def test_float_compatibility_converts_through_decimal_text() -> None:
    """Existing float callers should be converted before monetary arithmetic."""

    dataset: FinancialDataset = (
        {"revenue": 0.1, "cost": 0.03},
        {"revenue": 0.2, "cost": 0.06},
    )

    assert total_revenue(dataset) == Decimal("0.30")
    assert total_profit(dataset) == Decimal("0.21")


@pytest.mark.parametrize(
    "calculation",
    (
        total_revenue,
        total_cost,
        total_profit,
        average_order_value,
        profit_margin,
    ),
)
def test_single_period_calculations_reject_empty_dataset(
    calculation: Callable[[FinancialDataset], Decimal],
) -> None:
    """An empty dataset should fail rather than produce a misleading zero."""

    with pytest.raises(InvalidDatasetError, match="at least one row") as captured:
        calculation(())

    assert isinstance(captured.value.__cause__, ValueError)


def test_growth_and_aggregate_reject_empty_datasets() -> None:
    """Multi-period calculations should enforce non-empty period inputs."""

    with pytest.raises(InvalidDatasetError, match="at least one row"):
        revenue_growth_rate((), PREVIOUS_PERIOD)
    with pytest.raises(InvalidDatasetError, match="at least one row"):
        revenue_growth_rate(CURRENT_PERIOD, ())
    with pytest.raises(InvalidDatasetError, match="at least one row"):
        calculate_kpis((), PREVIOUS_PERIOD)


@pytest.mark.parametrize(
    ("calculation", "dataset", "column"),
    (
        (total_revenue, ({"cost": 10},), "revenue"),
        (total_cost, ({"revenue": 10},), "cost"),
        (total_profit, ({"revenue": 10},), "cost"),
        (average_order_value, ({"cost": 10},), "revenue"),
        (profit_margin, ({"revenue": 10},), "cost"),
    ),
)
def test_calculations_reject_missing_columns(
    calculation: Callable[[FinancialDataset], Decimal],
    dataset: FinancialDataset,
    column: str,
) -> None:
    """Missing required columns should identify the absent input by name."""

    with pytest.raises(InvalidDatasetError, match=column) as captured:
        calculation(dataset)

    assert isinstance(captured.value.__cause__, KeyError)


@pytest.mark.parametrize(
    ("dataset", "cause_type", "message"),
    (
        ("not-a-dataset", TypeError, "sequence of row mappings"),
        (("not-a-row",), TypeError, "row 0 must be a mapping"),
        (({"revenue": "100"},), TypeError, "int, float, or Decimal"),
        (({"revenue": True},), TypeError, "int, float, or Decimal"),
        (({"revenue": float("nan")},), ValueError, "finite number"),
        (({"revenue": float("inf")},), ValueError, "finite number"),
        (({"revenue": Decimal("NaN")},), ValueError, "finite number"),
        (({"revenue": Decimal("Infinity")},), ValueError, "finite number"),
        (
            ({"revenue": Decimal("1E+100")},),
            ValueError,
            "exceeds supported precision",
        ),
    ),
)
def test_revenue_validation_rejects_invalid_data(
    dataset: object,
    cause_type: type[Exception],
    message: str,
) -> None:
    """Malformed rows and values should produce actionable validation errors."""

    with pytest.raises(InvalidDatasetError, match=message) as captured:
        total_revenue(dataset)  # type: ignore[arg-type]

    assert isinstance(captured.value.__cause__, cause_type)


def test_cost_validation_rejects_invalid_data() -> None:
    """Cost values receive the same strict numeric validation as revenue."""

    with pytest.raises(
        InvalidDatasetError,
        match="cost.*int, float, or Decimal",
    ) as captured:
        total_cost(({"cost": "60"},))

    assert isinstance(captured.value.__cause__, TypeError)


def test_profit_margin_rejects_zero_revenue() -> None:
    """Margin should fail explicitly when its revenue denominator is zero."""

    with pytest.raises(
        UndefinedMetricError,
        match="total revenue is zero",
    ) as captured:
        profit_margin(({"revenue": 0, "cost": 0},))

    assert isinstance(captured.value.__cause__, ZeroDivisionError)


def test_growth_rate_rejects_zero_previous_revenue() -> None:
    """Growth should fail explicitly when its comparison baseline is zero."""

    zero_revenue_period: FinancialDataset = ({"revenue": 0, "cost": 0},)

    with pytest.raises(
        UndefinedMetricError,
        match="previous revenue is zero",
    ) as captured:
        revenue_growth_rate(CURRENT_PERIOD, zero_revenue_period)

    assert isinstance(captured.value.__cause__, ZeroDivisionError)


@pytest.mark.parametrize("column", ("revenue", "cost"))
def test_source_financial_values_must_not_be_negative(column: str) -> None:
    """Gross revenue and cost inputs should reject unsupported negative values."""

    with pytest.raises(
        InvalidDatasetError,
        match=f"{column}.*must not be negative",
    ) as captured:
        if column == "revenue":
            total_revenue(({"revenue": Decimal("-0.001")},))
        else:
            total_cost(({"cost": Decimal("-0.001")},))

    assert isinstance(captured.value.__cause__, ValueError)


def test_negative_profit_is_allowed_for_a_loss() -> None:
    """Costs exceeding revenue represent a valid loss, not invalid source data."""

    loss_period: FinancialDataset = ({"revenue": 100, "cost": 150},)

    assert total_profit(loss_period) == Decimal("-50.00")
    assert profit_margin(loss_period) == Decimal("-50.00")

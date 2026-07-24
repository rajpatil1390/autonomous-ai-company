"""Deterministic ``Decimal`` finance calculations over in-memory order data.

Every function is pure: results depend only on arguments, no state is mutated,
and no external service or file is accessed. Monetary values are rounded to
two decimal places with ``ROUND_HALF_EVEN`` when validated. Monetary averages
use the same cent precision, and percentages are rounded to two decimal
percentage points. This explicit policy avoids hidden binary-float rounding and
reduces systematic bias when many midpoint values are processed.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from typing import TypedDict

from autonomous_ai_company.exceptions import (
    InvalidDatasetError,
    UndefinedMetricError,
)


type FinancialRecord = Mapping[str, object]
type FinancialDataset = Sequence[FinancialRecord]


MONEY_QUANTUM = Decimal("0.01")
PERCENTAGE_QUANTUM = Decimal("0.01")
ONE_HUNDRED = Decimal("100")
ZERO_MONEY = Decimal("0.00")
DECIMAL_PRECISION = 50


class FinanceKPIs(TypedDict):
    """Describe the exact KPI collection returned to agent code.

    ``Decimal`` values should cross JSON boundaries as strings so consumers do
    not silently convert exact financial values back to binary floating point.
    """

    total_revenue: Decimal
    total_profit: Decimal
    total_cost: Decimal
    average_order_value: Decimal
    profit_margin: Decimal
    revenue_growth_rate: Decimal


def _to_money(value: object, row_index: int, column: str) -> Decimal:
    """Convert one supported numeric value into finite, non-negative cents.

    Floats remain accepted for API compatibility, but their shortest decimal
    string is converted immediately; no monetary arithmetic uses ``float``.
    Callers should supply ``Decimal`` or integer values whenever possible.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(
            f"row {row_index} column '{column}' must be an int, float, or Decimal"
        )

    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))

    if not decimal_value.is_finite():
        raise ValueError(f"row {row_index} column '{column}' must be a finite number")
    if decimal_value < 0:
        raise ValueError(f"row {row_index} column '{column}' must not be negative")

    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        try:
            return decimal_value.quantize(
                MONEY_QUANTUM,
                rounding=ROUND_HALF_EVEN,
            )
        except InvalidOperation as error:
            raise ValueError(
                f"row {row_index} column '{column}' exceeds supported precision"
            ) from error


def _validated_column_values(
    dataset: FinancialDataset,
    column: str,
) -> list[Decimal]:
    """Return rounded, non-negative money values from a required column."""

    if isinstance(dataset, (str, bytes)) or not isinstance(dataset, Sequence):
        raise TypeError("dataset must be a sequence of row mappings")
    if not dataset:
        raise ValueError("dataset must contain at least one row")

    values: list[Decimal] = []
    for index, row in enumerate(dataset):
        if not isinstance(row, Mapping):
            raise TypeError(f"row {index} must be a mapping")
        if column not in row:
            raise KeyError(f"row {index} is missing required column '{column}'")
        values.append(_to_money(row[column], index, column))

    return values


def _sum_money(values: list[Decimal]) -> Decimal:
    """Sum cent-normalized values under the documented decimal precision."""

    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return sum(values, start=ZERO_MONEY)


def _total_for_column(dataset: FinancialDataset, column: str) -> Decimal:
    """Translate structural validation failures into the finance domain."""

    try:
        return _sum_money(_validated_column_values(dataset, column))
    except (TypeError, ValueError, KeyError) as error:
        raise InvalidDatasetError(str(error)) from error


def total_revenue(dataset: FinancialDataset) -> Decimal:
    """Return exact revenue rounded to cents with ``ROUND_HALF_EVEN``."""

    return _total_for_column(dataset, "revenue")


def total_cost(dataset: FinancialDataset) -> Decimal:
    """Return exact cost rounded to cents with ``ROUND_HALF_EVEN``."""

    return _total_for_column(dataset, "cost")


def total_profit(dataset: FinancialDataset) -> Decimal:
    """Return exact revenue minus cost, allowing a negative loss result."""

    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return total_revenue(dataset) - total_cost(dataset)


def average_order_value(dataset: FinancialDataset) -> Decimal:
    """Return revenue per row rounded to cents with ``ROUND_HALF_EVEN``."""

    revenue = total_revenue(dataset)
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return (revenue / Decimal(len(dataset))).quantize(
            MONEY_QUANTUM,
            rounding=ROUND_HALF_EVEN,
        )


def profit_margin(dataset: FinancialDataset) -> Decimal:
    """Return profit percentage rounded to two decimal percentage points."""

    revenue = total_revenue(dataset)
    if revenue == ZERO_MONEY:
        cause = ZeroDivisionError(
            "profit margin is undefined when total revenue is zero"
        )
        raise UndefinedMetricError(str(cause)) from cause

    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return ((revenue - total_cost(dataset)) / revenue * ONE_HUNDRED).quantize(
            PERCENTAGE_QUANTUM, rounding=ROUND_HALF_EVEN
        )


def revenue_growth_rate(
    current_period: FinancialDataset,
    previous_period: FinancialDataset,
) -> Decimal:
    """Return revenue growth rounded to two decimal percentage points."""

    current_revenue = total_revenue(current_period)
    previous_revenue = total_revenue(previous_period)
    if previous_revenue == ZERO_MONEY:
        cause = ZeroDivisionError(
            "revenue growth is undefined when previous revenue is zero"
        )
        raise UndefinedMetricError(str(cause)) from cause

    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return (
            (current_revenue - previous_revenue) / previous_revenue * ONE_HUNDRED
        ).quantize(PERCENTAGE_QUANTUM, rounding=ROUND_HALF_EVEN)


def calculate_kpis(
    current_period: FinancialDataset,
    previous_period: FinancialDataset,
) -> FinanceKPIs:
    """Return every finance KPI as an exact ``Decimal`` value.

    Public function names and dictionary keys remain stable. Only the numeric
    representation changes from binary floats to exact decimal values.
    """

    return {
        "total_revenue": total_revenue(current_period),
        "total_profit": total_profit(current_period),
        "total_cost": total_cost(current_period),
        "average_order_value": average_order_value(current_period),
        "profit_margin": profit_margin(current_period),
        "revenue_growth_rate": revenue_growth_rate(
            current_period,
            previous_period,
        ),
    }

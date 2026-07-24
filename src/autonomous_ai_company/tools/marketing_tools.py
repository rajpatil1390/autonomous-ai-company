"""Calculate deterministic marketing KPIs from in-memory order records.

Each record requires ``customer_id``, ``revenue``, and ``segment``. Monetary
values and percentages use ``Decimal`` with two-place ``ROUND_HALF_EVEN``
rounding. Functions are pure and perform no file, network, or model operations.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from typing import TypedDict

from autonomous_ai_company.exceptions import InvalidDatasetError


type MarketingRecord = Mapping[str, object]
type MarketingDataset = Sequence[MarketingRecord]
type NormalizedOrder = tuple[str, Decimal, str]

MONEY_QUANTUM = Decimal("0.01")
PERCENTAGE_QUANTUM = Decimal("0.01")
ONE_HUNDRED = Decimal("100")
ZERO_MONEY = Decimal("0.00")
DECIMAL_PRECISION = 50
DEFAULT_SEGMENT_LIMIT = 3


class MarketingKPIs(TypedDict):
    """Describe every deterministic metric supplied to the Marketing Agent."""

    customer_count: int
    repeat_customer_rate: Decimal
    average_order_value: Decimal
    customer_growth: Decimal
    retention_rate: Decimal
    churn_rate: Decimal
    top_segments: list[str]
    revenue_by_segment: dict[str, Decimal]


def _to_money(value: object, row_index: int) -> Decimal:
    """Normalize one finite, non-negative revenue value to exact cents."""

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(
            f"row {row_index} column 'revenue' must be an int, float, or Decimal"
        )
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    if not decimal_value.is_finite():
        raise ValueError(f"row {row_index} column 'revenue' must be a finite number")
    if decimal_value < 0:
        raise ValueError(f"row {row_index} column 'revenue' must not be negative")
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        try:
            return decimal_value.quantize(
                MONEY_QUANTUM,
                rounding=ROUND_HALF_EVEN,
            )
        except InvalidOperation as error:
            raise ValueError(
                f"row {row_index} column 'revenue' exceeds supported precision"
            ) from error


def _validated_orders(dataset: MarketingDataset) -> list[NormalizedOrder]:
    """Validate and normalize one marketing dataset without mutating it."""

    if isinstance(dataset, (str, bytes)) or not isinstance(dataset, Sequence):
        raise TypeError("dataset must be a sequence of row mappings")
    if not dataset:
        raise ValueError("dataset must contain at least one row")

    orders: list[NormalizedOrder] = []
    for index, row in enumerate(dataset):
        if not isinstance(row, Mapping):
            raise TypeError(f"row {index} must be a mapping")
        for column in ("customer_id", "revenue", "segment"):
            if column not in row:
                raise KeyError(f"row {index} is missing required column '{column}'")
        customer_id = row["customer_id"]
        segment = row["segment"]
        if not isinstance(customer_id, str):
            raise TypeError(f"row {index} customer_id must be a string")
        if not customer_id.strip():
            raise ValueError(f"row {index} customer_id must be non-empty")
        if not isinstance(segment, str):
            raise TypeError(f"row {index} segment must be a string")
        if not segment.strip():
            raise ValueError(f"row {index} segment must be non-empty")
        orders.append(
            (
                customer_id.strip(),
                _to_money(row["revenue"], index),
                segment.strip(),
            )
        )
    return orders


def _orders(dataset: MarketingDataset) -> list[NormalizedOrder]:
    """Translate structural failures into the marketing domain boundary."""

    try:
        return _validated_orders(dataset)
    except (TypeError, ValueError, KeyError) as error:
        raise InvalidDatasetError(str(error)) from error


def _customers(orders: list[NormalizedOrder]) -> set[str]:
    """Return unique customer identifiers from normalized orders."""

    return {customer_id for customer_id, _, _ in orders}


def _percentage(numerator: int, denominator: int) -> Decimal:
    """Return a half-even percentage for a guaranteed positive denominator."""

    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return (Decimal(numerator) / Decimal(denominator) * ONE_HUNDRED).quantize(
            PERCENTAGE_QUANTUM, rounding=ROUND_HALF_EVEN
        )


def _average_order_value(orders: list[NormalizedOrder]) -> Decimal:
    """Calculate exact mean revenue over normalized orders."""

    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        revenue = sum((order[1] for order in orders), start=ZERO_MONEY)
        return (revenue / Decimal(len(orders))).quantize(
            MONEY_QUANTUM,
            rounding=ROUND_HALF_EVEN,
        )


def _revenue_by_segment(
    orders: list[NormalizedOrder],
) -> dict[str, Decimal]:
    """Aggregate exact revenue with deterministic alphabetical key ordering."""

    totals: dict[str, Decimal] = {}
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        for _, revenue, segment in orders:
            totals[segment] = totals.get(segment, ZERO_MONEY) + revenue
    return {segment: totals[segment] for segment in sorted(totals)}


def customer_count(dataset: MarketingDataset) -> int:
    """Return the number of unique current-period customers."""

    return len(_customers(_orders(dataset)))


def repeat_customer_rate(dataset: MarketingDataset) -> Decimal:
    """Return the percentage of customers with more than one order."""

    orders = _orders(dataset)
    counts = Counter(order[0] for order in orders)
    repeat_customers = sum(count > 1 for count in counts.values())
    return _percentage(repeat_customers, len(counts))


def average_order_value(dataset: MarketingDataset) -> Decimal:
    """Return mean order revenue rounded to cents."""

    return _average_order_value(_orders(dataset))


def customer_growth(
    current_period: MarketingDataset,
    previous_period: MarketingDataset,
) -> Decimal:
    """Return unique-customer growth relative to the previous period."""

    current_customers = len(_customers(_orders(current_period)))
    previous_customers = len(_customers(_orders(previous_period)))
    return _percentage(
        current_customers - previous_customers,
        previous_customers,
    )


def retention_rate(
    current_period: MarketingDataset,
    previous_period: MarketingDataset,
) -> Decimal:
    """Return the percentage of previous customers retained currently."""

    current_customers = _customers(_orders(current_period))
    previous_customers = _customers(_orders(previous_period))
    return _percentage(
        len(current_customers & previous_customers),
        len(previous_customers),
    )


def churn_rate(
    current_period: MarketingDataset,
    previous_period: MarketingDataset,
) -> Decimal:
    """Return the complement of retention as percentage points."""

    return ONE_HUNDRED - retention_rate(current_period, previous_period)


def revenue_by_segment(dataset: MarketingDataset) -> dict[str, Decimal]:
    """Return exact current-period revenue grouped by segment."""

    return _revenue_by_segment(_orders(dataset))


def top_segments(
    dataset: MarketingDataset,
    limit: int = DEFAULT_SEGMENT_LIMIT,
) -> list[str]:
    """Return leading segments by revenue with deterministic tie-breaking."""

    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    totals = revenue_by_segment(dataset)
    ranked = sorted(totals, key=lambda segment: (-totals[segment], segment))
    return ranked[:limit]


def calculate_marketing_kpis(
    current_period: MarketingDataset,
    previous_period: MarketingDataset,
) -> MarketingKPIs:
    """Calculate every marketing KPI once from validated normalized records."""

    current_orders = _orders(current_period)
    previous_orders = _orders(previous_period)
    current_customers = _customers(current_orders)
    previous_customers = _customers(previous_orders)
    order_counts = Counter(order[0] for order in current_orders)
    retained_customers = len(current_customers & previous_customers)
    retention = _percentage(retained_customers, len(previous_customers))
    segment_revenue = _revenue_by_segment(current_orders)
    ranked_segments = sorted(
        segment_revenue,
        key=lambda segment: (-segment_revenue[segment], segment),
    )

    return {
        "customer_count": len(current_customers),
        "repeat_customer_rate": _percentage(
            sum(count > 1 for count in order_counts.values()),
            len(current_customers),
        ),
        "average_order_value": _average_order_value(current_orders),
        "customer_growth": _percentage(
            len(current_customers) - len(previous_customers),
            len(previous_customers),
        ),
        "retention_rate": retention,
        "churn_rate": ONE_HUNDRED - retention,
        "top_segments": ranked_segments[:DEFAULT_SEGMENT_LIMIT],
        "revenue_by_segment": segment_revenue,
    }

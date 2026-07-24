"""Compute deterministic time-series and model-summary statistics.

All arithmetic is performed with :class:`~decimal.Decimal` under a documented
four-decimal, ``ROUND_HALF_EVEN`` policy. The module interprets an ordered
numeric sequence as observations at equally spaced intervals; it does not
train models, call providers, access files, or mutate caller-owned data.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from typing import Literal, TypedDict

from autonomous_ai_company.exceptions import InvalidDatasetError


type Numeric = int | float | Decimal
type TimeSeries = Sequence[Numeric]

STATISTIC_QUANTUM = Decimal("0.0001")
ONE_HUNDRED = Decimal("100")
ZERO = Decimal("0")
DECIMAL_PRECISION = 50
DEFAULT_MOVING_AVERAGE_WINDOW = 3
DEFAULT_FORECAST_HORIZON = 3
DEFAULT_SEASON_LENGTH = 2
DEFAULT_ANOMALY_THRESHOLD = Decimal("3")
SEASONALITY_THRESHOLD = Decimal("0.5000")
NINETY_FIVE_PERCENT_Z_SCORE = Decimal("1.96")


class TrendSummary(TypedDict):
    """Describe the direction and exact least-squares slope of a series."""

    direction: Literal["increasing", "decreasing", "stable"]
    slope: Decimal


class ForecastSummary(TypedDict):
    """Describe a deterministic linear extrapolation without model training."""

    method: Literal["linear_trend"]
    horizon: int
    values: list[Decimal]
    mean: Decimal
    minimum: Decimal
    maximum: Decimal


class SeasonalitySummary(TypedDict):
    """Describe lag autocorrelation and its deterministic detection decision."""

    season_length: int
    correlation: Decimal | None
    detected: bool


class ConfidenceIntervalSummary(TypedDict):
    """Describe a two-sided 95% confidence interval for the series mean."""

    confidence_level: Decimal
    mean: Decimal
    lower: Decimal
    upper: Decimal


class FeatureImportanceEntry(TypedDict):
    """Describe one normalized feature contribution."""

    feature: str
    importance: Decimal
    percentage: Decimal


class DataScienceMetrics(TypedDict):
    """Collect every deterministic statistic supplied to the agent."""

    trend_detection: TrendSummary
    moving_average: list[Decimal]
    forecast_summary: ForecastSummary
    anomaly_count: int
    seasonality_indicator: SeasonalitySummary
    confidence_interval_summary: ConfidenceIntervalSummary
    feature_importance_summary: list[FeatureImportanceEntry]
    model_metrics_summary: dict[str, Decimal]


def _quantize(value: Decimal) -> Decimal:
    """Apply the module-wide four-decimal half-even output policy."""

    try:
        return value.quantize(STATISTIC_QUANTUM, rounding=ROUND_HALF_EVEN)
    except InvalidOperation as error:
        raise ValueError("numeric value exceeds supported precision") from error


def _to_decimal(value: object, label: str) -> Decimal:
    """Convert one supported finite numeric input without binary arithmetic."""

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"{label} must be an int, float, or Decimal")
    converted = value if isinstance(value, Decimal) else Decimal(str(value))
    if not converted.is_finite():
        raise ValueError(f"{label} must be finite")
    return _quantize(converted)


def _validated_series(dataset: TimeSeries) -> list[Decimal]:
    """Validate an equally spaced time series and normalize its observations."""

    if isinstance(dataset, (str, bytes)) or not isinstance(dataset, Sequence):
        raise TypeError("dataset must be a sequence of numeric observations")
    if len(dataset) < 2:
        raise ValueError("dataset must contain at least two observations")
    return [
        _to_decimal(value, f"observation {index}")
        for index, value in enumerate(dataset)
    ]


def _series(dataset: TimeSeries) -> list[Decimal]:
    """Translate structural failures into the shared dataset exception."""

    try:
        return _validated_series(dataset)
    except (TypeError, ValueError) as error:
        raise InvalidDatasetError(str(error)) from error


def _positive_integer(value: object, label: str) -> int:
    """Validate deterministic window, horizon, and lag parameters."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _mean(values: Sequence[Decimal]) -> Decimal:
    """Return an unrounded Decimal mean for internal calculations."""

    return sum(values, start=ZERO) / Decimal(len(values))


def _linear_slope(values: Sequence[Decimal]) -> Decimal:
    """Return the least-squares slope over zero-based equally spaced indices."""

    x_values = [Decimal(index) for index in range(len(values))]
    x_mean = _mean(x_values)
    y_mean = _mean(values)
    numerator = sum(
        (
            (x_value - x_mean) * (y_value - y_mean)
            for x_value, y_value in zip(x_values, values, strict=True)
        ),
        start=ZERO,
    )
    denominator = sum(
        ((x_value - x_mean) ** 2 for x_value in x_values),
        start=ZERO,
    )
    return numerator / denominator


def trend_detection(dataset: TimeSeries) -> TrendSummary:
    """Return increasing, decreasing, or stable least-squares trend evidence."""

    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        slope = _quantize(_linear_slope(_series(dataset)))
    direction: Literal["increasing", "decreasing", "stable"]
    if slope > ZERO:
        direction = "increasing"
    elif slope < ZERO:
        direction = "decreasing"
    else:
        direction = "stable"
    return {"direction": direction, "slope": slope}


def moving_average(
    dataset: TimeSeries,
    window: int = DEFAULT_MOVING_AVERAGE_WINDOW,
) -> list[Decimal]:
    """Return rolling means for a validated positive window."""

    values = _series(dataset)
    validated_window = _positive_integer(window, "window")
    if validated_window > len(values):
        raise ValueError("window must not exceed the dataset length")
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return [
            _quantize(_mean(values[index - validated_window : index]))
            for index in range(validated_window, len(values) + 1)
        ]


def forecast_summary(
    dataset: TimeSeries,
    horizon: int = DEFAULT_FORECAST_HORIZON,
) -> ForecastSummary:
    """Linearly extrapolate a bounded number of future equally spaced values."""

    values = _series(dataset)
    validated_horizon = _positive_integer(horizon, "horizon")
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        slope = _linear_slope(values)
        intercept = _mean(values) - slope * _mean(
            [Decimal(index) for index in range(len(values))]
        )
        forecasts = [
            _quantize(intercept + slope * Decimal(index))
            for index in range(
                len(values),
                len(values) + validated_horizon,
            )
        ]
        forecast_mean = _quantize(_mean(forecasts))
    return {
        "method": "linear_trend",
        "horizon": validated_horizon,
        "values": forecasts,
        "mean": forecast_mean,
        "minimum": min(forecasts),
        "maximum": max(forecasts),
    }


def anomaly_count(
    dataset: TimeSeries,
    threshold: Numeric = DEFAULT_ANOMALY_THRESHOLD,
) -> int:
    """Count observations beyond a population-standard-deviation threshold."""

    values = _series(dataset)
    validated_threshold = _to_decimal(threshold, "threshold")
    if validated_threshold <= ZERO:
        raise ValueError("threshold must be greater than zero")
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        mean = _mean(values)
        variance = _mean([(value - mean) ** 2 for value in values])
        standard_deviation = variance.sqrt()
        indices = (
            []
            if standard_deviation == ZERO
            else [
                index
                for index, value in enumerate(values)
                if abs(value - mean) > validated_threshold * standard_deviation
            ]
        )
    return len(indices)


def seasonality_indicator(
    dataset: TimeSeries,
    season_length: int = DEFAULT_SEASON_LENGTH,
) -> SeasonalitySummary:
    """Measure autocorrelation at a caller-selected seasonal lag."""

    values = _series(dataset)
    validated_length = _positive_integer(season_length, "season_length")
    if validated_length >= len(values):
        raise ValueError("season_length must be smaller than the dataset length")
    leading = values[:-validated_length]
    lagged = values[validated_length:]
    if len(leading) < 2:
        return {
            "season_length": validated_length,
            "correlation": None,
            "detected": False,
        }
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        leading_mean = _mean(leading)
        lagged_mean = _mean(lagged)
        numerator = sum(
            (
                (left - leading_mean) * (right - lagged_mean)
                for left, right in zip(leading, lagged, strict=True)
            ),
            start=ZERO,
        )
        left_variance = sum(
            ((value - leading_mean) ** 2 for value in leading),
            start=ZERO,
        )
        right_variance = sum(
            ((value - lagged_mean) ** 2 for value in lagged),
            start=ZERO,
        )
        denominator = (left_variance * right_variance).sqrt()
        correlation = (
            None if denominator == ZERO else _quantize(numerator / denominator)
        )
    return {
        "season_length": validated_length,
        "correlation": correlation,
        "detected": correlation is not None and correlation >= SEASONALITY_THRESHOLD,
    }


def confidence_interval_summary(
    dataset: TimeSeries,
) -> ConfidenceIntervalSummary:
    """Return a deterministic normal-approximation 95% interval for the mean."""

    values = _series(dataset)
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        mean = _mean(values)
        squared_deviations = sum(
            ((value - mean) ** 2 for value in values),
            start=ZERO,
        )
        sample_variance = squared_deviations / Decimal(len(values) - 1)
        standard_error = (sample_variance / Decimal(len(values))).sqrt()
        margin = NINETY_FIVE_PERCENT_Z_SCORE * standard_error
        rounded_mean = _quantize(mean)
    return {
        "confidence_level": Decimal("0.9500"),
        "mean": rounded_mean,
        "lower": _quantize(mean - margin),
        "upper": _quantize(mean + margin),
    }


def feature_importance_summary(
    feature_importances: Mapping[str, Numeric] | None,
) -> list[FeatureImportanceEntry]:
    """Normalize optional precomputed feature weights into percentages."""

    if feature_importances is None:
        return []
    if not isinstance(feature_importances, Mapping):
        raise TypeError("feature_importances must be a mapping when provided")
    converted: dict[str, Decimal] = {}
    for feature, importance in feature_importances.items():
        if not isinstance(feature, str) or not feature.strip():
            raise ValueError("feature names must be non-empty strings")
        value = _to_decimal(importance, f"importance for '{feature}'")
        if value < ZERO:
            raise ValueError("feature importance must not be negative")
        converted[feature.strip()] = value
    total = sum(converted.values(), start=ZERO)
    if converted and total == ZERO:
        raise ValueError("feature importances must include a positive value")
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return [
            {
                "feature": feature,
                "importance": converted[feature],
                "percentage": _quantize(converted[feature] / total * ONE_HUNDRED),
            }
            for feature in sorted(
                converted,
                key=lambda name: (-converted[name], name),
            )
        ]


def model_metrics_summary(
    model_metrics: Mapping[str, Numeric] | None,
) -> dict[str, Decimal]:
    """Validate optional externally computed classification and error metrics.

    Canonical JSON-safe keys are ``accuracy``, ``precision``, ``recall``,
    ``f1_score``, ``mae``, ``mse``, ``rmse``, and ``r2``. The tools validate and
    format these supplied values; they never derive metrics from predictions.
    """

    if model_metrics is None:
        return {}
    if not isinstance(model_metrics, Mapping):
        raise TypeError("model_metrics must be a mapping when provided")
    bounded_metrics = {"accuracy", "precision", "recall", "f1_score"}
    error_metrics = {"mae", "mse", "rmse"}
    allowed = bounded_metrics | error_metrics | {"r2"}
    unknown = set(model_metrics) - allowed
    if unknown:
        raise ValueError(f"unsupported model metric: {sorted(unknown)[0]}")
    converted = {
        metric: _to_decimal(value, f"model metric '{metric}'")
        for metric, value in model_metrics.items()
    }
    for metric in sorted(bounded_metrics & converted.keys()):
        if not ZERO <= converted[metric] <= 1:
            raise ValueError(f"{metric} must be between zero and one")
    for metric in sorted(error_metrics & converted.keys()):
        if converted[metric] < ZERO:
            raise ValueError(f"{metric} must not be negative")
    return {metric: converted[metric] for metric in sorted(converted)}


def calculate_data_science_metrics(
    dataset: TimeSeries,
    *,
    moving_average_window: int = DEFAULT_MOVING_AVERAGE_WINDOW,
    forecast_horizon: int = DEFAULT_FORECAST_HORIZON,
    season_length: int = DEFAULT_SEASON_LENGTH,
    anomaly_threshold: Numeric = DEFAULT_ANOMALY_THRESHOLD,
    feature_importances: Mapping[str, Numeric] | None = None,
    model_metrics: Mapping[str, Numeric] | None = None,
) -> DataScienceMetrics:
    """Calculate the complete deterministic analytics evidence contract."""

    return {
        "trend_detection": trend_detection(dataset),
        "moving_average": moving_average(dataset, moving_average_window),
        "forecast_summary": forecast_summary(dataset, forecast_horizon),
        "anomaly_count": anomaly_count(dataset, anomaly_threshold),
        "seasonality_indicator": seasonality_indicator(
            dataset,
            season_length,
        ),
        "confidence_interval_summary": confidence_interval_summary(dataset),
        "feature_importance_summary": feature_importance_summary(feature_importances),
        "model_metrics_summary": model_metrics_summary(model_metrics),
    }

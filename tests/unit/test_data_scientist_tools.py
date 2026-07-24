"""Unit tests for deterministic Decimal analytics tools."""

import json
from decimal import Decimal

import pytest

from autonomous_ai_company.exceptions import InvalidDatasetError
from autonomous_ai_company.tools.data_scientist_tools import (
    TimeSeries,
    anomaly_count,
    calculate_data_science_metrics,
    confidence_interval_summary,
    feature_importance_summary,
    forecast_summary,
    model_metrics_summary,
    moving_average,
    seasonality_indicator,
    trend_detection,
)


SERIES: TimeSeries = (
    Decimal("10"),
    Decimal("20"),
    Decimal("10"),
    Decimal("20"),
    Decimal("10"),
    Decimal("20"),
)


def test_complete_analytics_contract_is_exact_and_json_serializable() -> None:
    """The aggregate tool should produce every required deterministic metric."""

    metrics = calculate_data_science_metrics(
        SERIES,
        feature_importances={"price": Decimal("0.75"), "season": 0.25},
        model_metrics={
            "accuracy": Decimal("0.90"),
            "precision": Decimal("0.85"),
            "recall": Decimal("0.80"),
            "f1_score": Decimal("0.825"),
            "mae": Decimal("1.25"),
            "mse": Decimal("2.25"),
            "rmse": 1.5,
            "r2": Decimal("0.80"),
        },
    )

    assert metrics == {
        "trend_detection": {
            "direction": "increasing",
            "slope": Decimal("0.8571"),
        },
        "moving_average": [
            Decimal("13.3333"),
            Decimal("16.6667"),
            Decimal("13.3333"),
            Decimal("16.6667"),
        ],
        "forecast_summary": {
            "method": "linear_trend",
            "horizon": 3,
            "values": [
                Decimal("18.0000"),
                Decimal("18.8571"),
                Decimal("19.7143"),
            ],
            "mean": Decimal("18.8571"),
            "minimum": Decimal("18.0000"),
            "maximum": Decimal("19.7143"),
        },
        "anomaly_count": 0,
        "seasonality_indicator": {
            "season_length": 2,
            "correlation": Decimal("1.0000"),
            "detected": True,
        },
        "confidence_interval_summary": {
            "confidence_level": Decimal("0.9500"),
            "mean": Decimal("15.0000"),
            "lower": Decimal("10.6173"),
            "upper": Decimal("19.3827"),
        },
        "feature_importance_summary": [
            {
                "feature": "price",
                "importance": Decimal("0.7500"),
                "percentage": Decimal("75.0000"),
            },
            {
                "feature": "season",
                "importance": Decimal("0.2500"),
                "percentage": Decimal("25.0000"),
            },
        ],
        "model_metrics_summary": {
            "accuracy": Decimal("0.9000"),
            "f1_score": Decimal("0.8250"),
            "mae": Decimal("1.2500"),
            "mse": Decimal("2.2500"),
            "precision": Decimal("0.8500"),
            "r2": Decimal("0.8000"),
            "recall": Decimal("0.8000"),
            "rmse": Decimal("1.5000"),
        },
    }
    serialized = json.loads(json.dumps(metrics, default=str))
    assert serialized["forecast_summary"]["values"][1] == "18.8571"
    assert serialized["model_metrics_summary"]["rmse"] == "1.5000"


def test_trend_supports_decreasing_and_stable_series() -> None:
    """Slope signs should map deterministically to all trend categories."""

    assert trend_detection((3, 2, 1)) == {
        "direction": "decreasing",
        "slope": Decimal("-1.0000"),
    }
    assert trend_detection((2, 2, 2)) == {
        "direction": "stable",
        "slope": Decimal("0.0000"),
    }


def test_moving_average_forecast_anomaly_and_interval_values() -> None:
    """Individual tools should expose their exact calculation policies."""

    assert moving_average((1, 2, 3), 1) == [
        Decimal("1.0000"),
        Decimal("2.0000"),
        Decimal("3.0000"),
    ]
    assert forecast_summary((1, 2, 3), 1)["values"] == [Decimal("4.0000")]
    assert anomaly_count((10, 10, 10, 10, 10, 100), Decimal("1.5")) == 1
    assert anomaly_count((5, 5, 5)) == 0
    assert confidence_interval_summary((1, 2, 3, 4)) == {
        "confidence_level": Decimal("0.9500"),
        "mean": Decimal("2.5000"),
        "lower": Decimal("1.2348"),
        "upper": Decimal("3.7652"),
    }


def test_seasonality_handles_insufficient_constant_and_negative_correlation() -> None:
    """Undefined and weak lag relationships must never be called seasonal."""

    assert seasonality_indicator((1, 2, 3), 2) == {
        "season_length": 2,
        "correlation": None,
        "detected": False,
    }
    assert seasonality_indicator((5, 5, 5, 5), 2)["correlation"] is None
    negative = seasonality_indicator((1, 3, 2, 0, 1, 3), 2)
    assert negative["correlation"] is not None
    assert negative["detected"] is False


def test_optional_summaries_support_absence_empty_inputs_and_ties() -> None:
    """Optional externally computed evidence should remain optional and sorted."""

    assert feature_importance_summary(None) == []
    assert feature_importance_summary({}) == []
    assert feature_importance_summary({"z": 1, "a": 1}) == [
        {
            "feature": "a",
            "importance": Decimal("1.0000"),
            "percentage": Decimal("50.0000"),
        },
        {
            "feature": "z",
            "importance": Decimal("1.0000"),
            "percentage": Decimal("50.0000"),
        },
    ]
    assert model_metrics_summary(None) == {}
    assert model_metrics_summary({}) == {}
    assert model_metrics_summary({"r2": -2}) == {"r2": Decimal("-2.0000")}


@pytest.mark.parametrize(
    ("dataset", "message"),
    (
        (object(), "sequence of numeric observations"),
        ("123", "sequence of numeric observations"),
        ([], "at least two observations"),
        ([1], "at least two observations"),
        ([True, 1], "observation 0"),
        (["1", 2], "observation 0"),
        ([float("nan"), 1], "must be finite"),
        ([Decimal("Infinity"), 1], "must be finite"),
        ([Decimal("1E+100"), 1], "supported precision"),
    ),
)
def test_series_validation_raises_domain_error_with_cause(
    dataset: object,
    message: str,
) -> None:
    """Malformed observations should cross the tool boundary as domain errors."""

    with pytest.raises(InvalidDatasetError, match=message) as captured:
        trend_detection(dataset)  # type: ignore[arg-type]

    assert isinstance(captured.value.__cause__, (TypeError, ValueError))


@pytest.mark.parametrize("window", (True, 0, -1, 1.5))
def test_moving_average_rejects_invalid_windows(window: object) -> None:
    """Window size must be a positive integer within the dataset."""

    with pytest.raises(ValueError, match="positive integer"):
        moving_average(SERIES, window)  # type: ignore[arg-type]


def test_window_horizon_season_and_threshold_bounds() -> None:
    """All algorithm parameters should reject mathematically invalid bounds."""

    with pytest.raises(ValueError, match="dataset length"):
        moving_average((1, 2), 3)
    with pytest.raises(ValueError, match="positive integer"):
        forecast_summary(SERIES, 0)
    with pytest.raises(ValueError, match="positive integer"):
        seasonality_indicator(SERIES, False)
    with pytest.raises(ValueError, match="smaller than"):
        seasonality_indicator(SERIES, len(SERIES))
    with pytest.raises(TypeError, match="threshold"):
        anomaly_count(SERIES, "3")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="greater than zero"):
        anomaly_count(SERIES, 0)


@pytest.mark.parametrize(
    ("importances", "exception", "message"),
    (
        ([], TypeError, "must be a mapping"),
        ({1: 1}, ValueError, "feature names"),
        ({"  ": 1}, ValueError, "feature names"),
        ({"price": "high"}, TypeError, "importance for"),
        ({"price": Decimal("NaN")}, ValueError, "must be finite"),
        ({"price": -1}, ValueError, "must not be negative"),
        ({"price": 0, "season": 0}, ValueError, "positive value"),
    ),
)
def test_feature_importance_validation(
    importances: object,
    exception: type[Exception],
    message: str,
) -> None:
    """Only non-negative finite named feature weights are meaningful."""

    with pytest.raises(exception, match=message):
        feature_importance_summary(importances)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("metrics", "exception", "message"),
    (
        ([], TypeError, "must be a mapping"),
        ({"specificity": 1}, ValueError, "unsupported model metric"),
        ({"accuracy": "high"}, TypeError, "model metric"),
        ({"accuracy": -1}, ValueError, "between zero and one"),
        ({"accuracy": 2}, ValueError, "between zero and one"),
        ({"precision": 2}, ValueError, "between zero and one"),
        ({"recall": -1}, ValueError, "between zero and one"),
        ({"f1_score": 2}, ValueError, "between zero and one"),
        ({"mae": -1}, ValueError, "mae must not be negative"),
        ({"mse": -1}, ValueError, "mse must not be negative"),
        ({"rmse": -1}, ValueError, "rmse must not be negative"),
    ),
)
def test_model_metric_validation(
    metrics: object,
    exception: type[Exception],
    message: str,
) -> None:
    """Provided metrics must respect their established mathematical domains."""

    with pytest.raises(exception, match=message):
        model_metrics_summary(metrics)  # type: ignore[arg-type]


def test_tools_never_mutate_the_input_series_or_mappings() -> None:
    """Normalization and sorting must leave caller-owned data untouched."""

    series = [1.23456, 2.34567, 3.45678]
    importances = {" feature ": Decimal("1")}
    original_series = list(series)
    original_importances = dict(importances)

    calculate_data_science_metrics(
        series,
        feature_importances=importances,
        season_length=1,
    )

    assert series == original_series
    assert importances == original_importances

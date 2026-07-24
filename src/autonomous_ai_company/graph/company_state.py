"""Define the JSON-safe shared state contract for company workflows.

This module deliberately contains no graph engine, agent, provider, or business
logic. It describes only the data that future nodes may read and return.
"""

from typing import Literal, TypedDict


type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]
type JSONDocument = dict[str, JSONValue]
type Dataset = list[JSONDocument]
type ExecutionStatus = Literal["pending", "running", "completed", "failed"]


class CompanyState(TypedDict, total=False):
    """Describe shared, JSON-serializable workflow data.

    Every field is optional so parallel nodes can return independent partial
    updates instead of mutating one shared dictionary. The graph runtime will
    assemble those updates into the state observed by downstream nodes.

    Attributes:
        dataset: JSON-safe source records available to analytical nodes.
        finance_result: Serialized Finance Agent output, or null when absent.
        marketing_result: Serialized Marketing Agent output, or null when absent.
        data_scientist_result: Serialized Data Scientist output, or null.
        report_result: Serialized Report Agent output, or null when absent.
        ceo_result: Serialized CEO Agent output, or null when absent.
        audit_events: Ordered serialized audit event envelopes.
        generation_results: Ordered provider-neutral generation result records.
        execution_status: Overall workflow lifecycle status.
        errors: Structured JSON-safe failures collected during execution.
        metadata: JSON-safe correlation and workflow configuration attributes.
    """

    dataset: Dataset
    finance_result: JSONDocument | None
    marketing_result: JSONDocument | None
    data_scientist_result: JSONDocument | None
    report_result: JSONDocument | None
    ceo_result: JSONDocument | None
    audit_events: list[JSONDocument]
    generation_results: list[JSONDocument]
    execution_status: ExecutionStatus
    errors: list[JSONDocument]
    metadata: JSONDocument

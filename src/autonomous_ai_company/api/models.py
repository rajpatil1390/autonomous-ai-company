"""Define strict HTTP request and non-domain response contracts."""

from pydantic import BaseModel, ConfigDict, Field

from autonomous_ai_company.graph.company_state import Dataset


class APIModel(BaseModel):
    """Reject undeclared or coercible HTTP data at the transport boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)


class HealthResponse(APIModel):
    """Describe the process liveness response."""

    status: str


class VersionResponse(APIModel):
    """Describe the stable application identity response."""

    application: str
    version: str


class WorkflowRequest(APIModel):
    """Carry every caller-supplied input required by the company graph.

    Historical data and analytical series are required explicitly so the API
    never derives, calculates, or fabricates business inputs.
    """

    dataset: Dataset
    previous_dataset: Dataset
    data_scientist_series: list[int | float]
    business_context: str = Field(default="", max_length=4_000)
    executive_question: str | None = Field(default=None, max_length=1_000)

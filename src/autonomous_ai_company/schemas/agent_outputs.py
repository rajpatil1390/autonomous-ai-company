"""Define provider-independent contracts for validated agent responses.

These schemas separate agent communication from LLM and orchestration
implementations so every downstream consumer receives predictable JSON data.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _AgentOutputModel(BaseModel):
    """Apply strict validation consistently across every agent boundary.

    A shared private base prevents individual outputs from silently coercing
    malformed values or accepting undeclared fields returned by an LLM.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )


class FinanceAgentOutput(_AgentOutputModel):
    """Provide a reliable finance narrative without calculating raw metrics.

    The contract keeps tool-calculated numbers separate from the Finance
    Agent's responsibility: explaining findings, risks, and recommendations.
    """

    executive_summary: str = Field(
        min_length=1,
        description="Concise interpretation of the organization's finances.",
    )
    key_findings: list[str] = Field(
        min_length=1,
        description="Evidence-based observations derived from calculated KPIs.",
    )
    recommendations: list[str] = Field(
        min_length=1,
        description="Actions supported by the validated financial findings.",
    )
    risk_level: Literal["low", "medium", "high"] = Field(
        description="Overall financial risk classification.",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the interpretation, from zero to one.",
    )


class MarketingAgentOutput(_AgentOutputModel):
    """Standardize marketing insights for orchestration and reporting.

    A dedicated contract lets later graph nodes consume marketing conclusions
    without depending on a prompt format or a particular model provider.
    """

    executive_summary: str = Field(
        min_length=1,
        description="Concise interpretation of marketing performance.",
    )
    key_findings: list[str] = Field(
        min_length=1,
        description="Important observations supported by marketing data.",
    )
    opportunities: list[str] = Field(
        min_length=1,
        description="Potential areas for measurable marketing improvement.",
    )
    recommendations: list[str] = Field(
        min_length=1,
        description="Suggested marketing actions grounded in the findings.",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the interpretation, from zero to one.",
    )


class DataScientistAgentOutput(_AgentOutputModel):
    """Represent model results as a validated business-facing explanation.

    The schema prevents forecasting calculations from being confused with the
    agent's role of interpreting tool-produced metrics and predictions.
    """

    executive_summary: str = Field(
        min_length=1,
        description="Business-level summary of the analytical results.",
    )
    model_interpretation: str = Field(
        min_length=1,
        description="Plain-language interpretation of model performance.",
    )
    forecast_outlook: str = Field(
        min_length=1,
        description="Business meaning of forecasts calculated by ML tools.",
    )
    limitations: list[str] = Field(
        description="Known data or modeling constraints affecting conclusions.",
    )
    recommendations: list[str] = Field(
        min_length=1,
        description="Actions supported by the analytical evidence.",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the interpretation, from zero to one.",
    )


class ReportAgentOutput(_AgentOutputModel):
    """Define the assembled report content before any file is written.

    Separating report content from rendering keeps external write operations
    outside the schema and allows the same validated result to target HTML,
    PDF, or another presentation format later.
    """

    title: str = Field(
        min_length=1,
        description="Human-readable title for the executive report.",
    )
    executive_summary: str = Field(
        min_length=1,
        description="Cross-functional summary for executive readers.",
    )
    sections: dict[str, str] = Field(
        min_length=1,
        description="Named report sections containing validated narrative text.",
    )
    key_recommendations: list[str] = Field(
        min_length=1,
        description="Highest-priority actions synthesized across agents.",
    )
    unavailable_sections: list[str] = Field(
        description="Sections omitted because source data or an agent failed.",
    )


class CEOAgentOutput(_AgentOutputModel):
    """Provide the final strategic synthesis as a stable supervisor contract.

    This output gives orchestration a typed final decision boundary while
    keeping approval workflows and external actions out of the model itself.
    """

    executive_summary: str = Field(
        min_length=1,
        description="Unified narrative of overall business performance.",
    )
    business_health: Literal[
        "critical",
        "concerning",
        "stable",
        "strong",
    ] = Field(
        description="Overall qualitative classification of business health.",
    )
    strategic_priorities: list[str] = Field(
        min_length=1,
        description="Ordered priorities synthesized from all available agents.",
    )
    key_risks: list[str] = Field(
        description="Material risks executives should monitor or mitigate.",
    )
    final_recommendation: str = Field(
        min_length=1,
        description="Primary strategic recommendation supported by the analysis.",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the synthesis, from zero to one.",
    )

"""Statically validate the version 1.0 release documentation assets."""

from __future__ import annotations

import re
import tomllib
import xml.etree.ElementTree as element_tree
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
RELEASE_FILES = {
    "changelog": ROOT / "CHANGELOG.md",
    "license": ROOT / "LICENSE",
    "contributing": ROOT / "CONTRIBUTING.md",
    "conduct": ROOT / "CODE_OF_CONDUCT.md",
    "security_contact": ROOT / "SECURITY_CONTACT.md",
    "roadmap": ROOT / "ROADMAP.md",
    "readme": ROOT / "README.md",
    "architecture": ROOT / "docs" / "architecture.md",
    "api": ROOT / "docs" / "api.md",
    "deployment": ROOT / "docs" / "deployment.md",
    "developer": ROOT / "docs" / "developer-guide.md",
    "operations": ROOT / "docs" / "operations-guide.md",
    "troubleshooting": ROOT / "docs" / "troubleshooting.md",
    "screenshots": ROOT / "assets" / "screenshots" / "README.md",
    "demo": ROOT / "assets" / "demo" / "demo-script.md",
    "bug_template": ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.md",
    "feature_template": (ROOT / ".github" / "ISSUE_TEMPLATE" / "feature_request.md"),
    "pull_request_template": ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md",
}
DIAGRAMS = {
    name: ROOT / "assets" / "architecture" / f"{name}.drawio"
    for name in ("system-overview", "workflow", "deployment")
}
LOCAL_LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
)


def markdown(name: str) -> str:
    """Return one UTF-8 release document."""

    return RELEASE_FILES[name].read_text(encoding="utf-8")


def headings(text: str) -> set[str]:
    """Return normalized ATX Markdown heading labels."""

    return {
        match.group(1).strip()
        for match in re.finditer(r"^#{1,6}\s+(.+?)\s*$", text, re.MULTILINE)
    }


def front_matter(name: str) -> dict[str, Any]:
    """Parse one issue template's YAML front matter."""

    text = markdown(name)
    assert text.startswith("---\n")
    document = yaml.safe_load(text.split("---\n", maxsplit=2)[1])
    assert isinstance(document, dict)
    return document


def test_all_requested_release_assets_exist_and_are_nonempty() -> None:
    """The full release document, diagram, template, and demo set must exist."""

    paths = [*RELEASE_FILES.values(), *DIAGRAMS.values()]
    assert len(paths) == 21
    assert all(path.is_file() for path in paths)
    assert all(path.stat().st_size > 0 for path in paths)


def test_release_versions_are_consistent() -> None:
    """Package, chart, API documentation, and changelog identify v1.0.0."""

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    chart = yaml.safe_load(
        (ROOT / "helm" / "autonomous-ai-company" / "Chart.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert project["project"]["version"] == "1.0.0"
    assert chart["version"] == "1.0.0"
    assert chart["appVersion"] == "1.0.0"
    assert "## [1.0.0] - 2026-07-15" in markdown("changelog")
    assert '"version": "1.0.0"' in markdown("api")


def test_readme_contains_every_release_landing_page_section() -> None:
    """The landing page must cover product, engineering, and operations."""

    readme_headings = headings(markdown("readme"))
    required = {
        "Highlights",
        "Architecture",
        "Workflow",
        "Quick start",
        "API",
        "Containers and production deployment",
        "Docker",
        "Kubernetes",
        "Helm",
        "Terraform and AWS",
        "Observability",
        "Security",
        "Performance and benchmarks",
        "Reliability, disaster recovery, and SRE",
        "Project structure",
        "Testing and quality",
        "Demo",
        "Screenshots",
        "FAQ",
        "Contributing and governance",
        "License",
        "Acknowledgements",
    }
    assert required <= readme_headings
    assert markdown("readme").count("![") >= 5
    assert markdown("readme").count("```mermaid") >= 2


def test_release_guides_have_complete_required_sections() -> None:
    """Architecture, API, development, operations, and support are actionable."""

    expected = {
        "architecture": {
            "System context",
            "Dependency direction",
            "Agent architecture",
            "LangGraph workflow",
            "Shared state",
            "Security and integrity boundaries",
            "Runtime composition",
            "Deployment architecture",
        },
        "api": {
            "Public endpoints",
            "Workflow request",
            "`POST /workflow/run`",
            "`POST /workflow/stream`",
            "Error responses",
        },
        "developer": {
            "Requirements",
            "Install",
            "Run locally",
            "Source layout",
            "Make a change",
            "Quality gates",
            "Test layers",
            "Security checklist",
        },
        "operations": {
            "Deployment",
            "Observability",
            "SLO and on-call practice",
            "Audit persistence",
            "Security operations",
            "Performance and capacity",
            "Chaos engineering",
            "Disaster recovery",
            "Escalation",
        },
        "troubleshooting": {
            "Application will not start",
            "Workflow returns `400` or `422`",
            "Workflow returns `503`",
            "SSE stream stops or buffers",
            "PostgreSQL audit failures",
            "Tests fail",
        },
    }
    for name, required in expected.items():
        assert required <= headings(markdown(name))


def test_local_markdown_links_resolve_without_network() -> None:
    """Every committed relative link must resolve from its source document."""

    failures: list[str] = []
    for path in RELEASE_FILES.values():
        text = path.read_text(encoding="utf-8")
        for target in LOCAL_LINK_PATTERN.findall(text):
            target_path = target.split("#", maxsplit=1)[0]
            if not target_path or target_path.startswith(
                ("http://", "https://", "mailto:")
            ):
                continue
            if not (path.parent / target_path).resolve().exists():
                failures.append(f"{path.relative_to(ROOT)} -> {target_path}")
    assert failures == []


def test_drawio_sources_are_valid_editable_mxgraph_documents() -> None:
    """Each architecture source must parse and contain vertices plus edges."""

    diagram_ids: set[str] = set()
    for path in DIAGRAMS.values():
        root = element_tree.parse(path).getroot()
        assert root.tag == "mxfile"
        diagrams = root.findall("diagram")
        assert len(diagrams) == 1
        diagram_id = diagrams[0].attrib["id"]
        assert diagram_id not in diagram_ids
        diagram_ids.add(diagram_id)
        cells = diagrams[0].findall("./mxGraphModel/root/mxCell")
        assert len([cell for cell in cells if cell.attrib.get("vertex") == "1"]) >= 8
        assert len([cell for cell in cells if cell.attrib.get("edge") == "1"]) >= 7


def test_screenshot_documentation_requires_real_sanitized_captures() -> None:
    """Screenshot placeholders must define honest capture and redaction policy."""

    text = markdown("screenshots")
    for filename in (
        "openapi.png",
        "workflow-result.png",
        "streaming.png",
        "grafana-overview.png",
        "mlflow-workflow.png",
    ):
        assert filename in text
    for forbidden_content in ("JWTs", "API keys", "raw prompts", "user identifiers"):
        assert forbidden_content in text
    assert "rather than fabricated UI" in text


def test_demo_is_executable_and_candid_about_boundaries() -> None:
    """The demo must cover real flows without overstating reliability evidence."""

    text = markdown("demo")
    for section in (
        "Preparation",
        "1. Architecture — 90 seconds",
        "2. Public health and authentication — 60 seconds",
        "3. Synchronous workflow — 2 minutes",
        "4. Streaming workflow — 90 seconds",
        "5. Audit and observability — 2 minutes",
        "6. Engineering quality — 60 seconds",
        "Close",
    ):
        assert section in headings(text)
    assert "may incur\nprovider charges" in text
    assert "Do not promise a heartbeat" in text
    assert "without printing it" in text


def test_issue_and_pull_request_templates_enforce_quality_and_safety() -> None:
    """Contribution templates must collect reproducibility and risk evidence."""

    bug = front_matter("bug_template")
    feature = front_matter("feature_template")
    assert bug["name"] == "Bug report"
    assert bug["labels"] == "bug"
    assert feature["name"] == "Feature request"
    assert feature["labels"] == "enhancement"
    assert {"Reproduction", "Expected behavior", "Actual behavior"} <= headings(
        markdown("bug_template")
    )
    assert {"Architecture impact", "Security and privacy", "Operational impact"} <= (
        headings(markdown("feature_template"))
    )
    pull_request = markdown("pull_request_template")
    for gate in ("ruff check .", "ruff format --check .", "100% application"):
        assert gate in pull_request


def test_governance_documents_define_contribution_and_private_reporting() -> None:
    """Release governance must make onboarding and safe reporting explicit."""

    assert "Architecture rules" in headings(markdown("contributing"))
    assert "Pull requests" in headings(markdown("contributing"))
    assert "Expected behavior" in headings(markdown("conduct"))
    assert "Enforcement" in headings(markdown("conduct"))
    security = markdown("security_contact")
    assert "Security → Report a vulnerability" in security
    assert "Do not report vulnerabilities through public issues" in security
    assert "MIT License" in RELEASE_FILES["license"].read_text(encoding="utf-8")


def test_roadmap_separates_released_features_from_future_direction() -> None:
    """The roadmap must identify v1.0 and avoid promising unapproved delivery."""

    roadmap_headings = headings(markdown("roadmap"))
    assert {
        "Version 1.0 — Production foundation",
        "Version 1.1 — Identity and reliability",
        "Version 1.2 — Evaluation and provider breadth",
        "Version 2.0 — Governed autonomous operations",
        "Explicitly not promised",
    } <= roadmap_headings
    assert "not a delivery promise" in markdown("roadmap")


def test_release_assets_contain_no_secrets_or_unresolved_required_placeholders() -> (
    None
):
    """Public release material must not contain credentials or drafting markers."""

    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [*RELEASE_FILES.values(), *DIAGRAMS.values()]
    )
    assert all(pattern.search(text) is None for pattern in SECRET_PATTERNS)
    assert re.search(r"OWNER/REPOSITORY|\bTODO\b|\bTBD\b|CHANGEME", text) is None

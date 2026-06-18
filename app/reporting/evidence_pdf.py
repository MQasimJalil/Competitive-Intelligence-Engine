from html import escape
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.schemas import NormalizedBusinessProfile


def render_evidence_appendix_bytes(profile: NormalizedBusinessProfile) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"{profile.domain} evidence appendix",
        author="Competitor Brief",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"{escape(profile.domain)} evidence appendix", styles["Title"]),
        Paragraph(
            "Deterministically extracted public evidence. Citation IDs are used by the report "
            "and optional AI analysis.",
            styles["BodyText"],
        ),
        Spacer(1, 5 * mm),
    ]
    for fact in profile.facts:
        title = fact.source_title or str(fact.source_url)
        story.extend(
            [
                Paragraph(
                    f"<b>{fact.citation_id} | {escape(fact.kind.value.replace('_', ' ').title())}"
                    f"</b>: {escape(fact.value)}",
                    styles["BodyText"],
                ),
                Paragraph(f"<b>Evidence:</b> {escape(fact.evidence_excerpt)}", styles["BodyText"]),
                Paragraph(
                    f"<b>Source:</b> {escape(title)}<br/>{escape(str(fact.source_url))}",
                    styles["BodyText"],
                ),
                Spacer(1, 4 * mm),
            ]
        )
    if not profile.facts:
        story.append(Paragraph("Data unavailable", styles["BodyText"]))
    document.build(story)
    return buffer.getvalue()

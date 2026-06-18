from html import escape
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.tools.competitor_brief.view_model import ReportView

INK = colors.HexColor("#11110F")
MUTED = colors.HexColor("#69665E")
ACCENT = colors.HexColor("#11110F")
PAPER = colors.HexColor("#EEE9DD")
PALE_GREEN = colors.HexColor("#F2F5DE")
PALE_AMBER = colors.HexColor("#F4EEDA")
BORDER = colors.HexColor("#B9B4A8")


class PDFValidationError(ValueError):
    pass


def render_competitor_pdf(report: ReportView, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(render_competitor_pdf_bytes(report))
    return output_path


def render_competitor_pdf_bytes(report: ReportView) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=13 * mm,
        rightMargin=13 * mm,
        topMargin=12 * mm,
        bottomMargin=10 * mm,
        title=f"{report.domain} intelligence dossier",
        author="Competitor Intelligence",
    )
    styles = _styles()
    story = [
        *_prototype_header(report, styles),
        Spacer(1, 5 * mm),
        _metric_grid(report, styles),
        Spacer(1, 5 * mm),
        _card(
            "30-second read",
            _with_source(
                report.executive.at_a_glance,
                report.executive.at_a_glance_source_number,
            ),
            styles,
            bg="#EEF3FF",
            border="#B9C8FF",
        ),
        Spacer(1, 3 * mm),
        _card(
            "Strategic read",
            _strategic_read(report),
            styles,
            bg="#FFF8E6",
            border="#E6D39D",
        ),
        Spacer(1, 4 * mm),
        Paragraph("Evidence Coverage", styles["h2"]),
        *_bullet(_evidence_coverage(report), styles),
        Spacer(1, 4 * mm),
        Paragraph("Truth-Bounded Takeaways", styles["h2"]),
        _takeaways_table(report, styles),
        Spacer(1, 4 * mm),
        Paragraph("Method And Limits", styles["h2"]),
        _method_table(report, styles),
        Spacer(1, 5 * mm),
        Paragraph("Product & Pricing Map", styles["h1"]),
        Paragraph(_safe(_offer_intro(report)), styles["body"]),
        Spacer(1, 4 * mm),
        _product_table(report, styles),
        Spacer(1, 5 * mm),
        Paragraph("What They Sell", styles["h2"]),
        *_bullet(_section_points(report, "What they offer"), styles),
        Spacer(1, 4 * mm),
        Paragraph("Positioning Pattern", styles["h2"]),
        *_bullet(_section_points(report, "What stands out"), styles),
        Spacer(1, 4 * mm),
        Paragraph("Catalog Signals", styles["h2"]),
        _catalog_table(report, styles),
        Spacer(1, 4 * mm),
        Paragraph("Open Verification Points", styles["h2"]),
        *_bullet(report.executive.unknowns or ["No major evidence gaps were surfaced."], styles),
        Spacer(1, 5 * mm),
        Paragraph("Competitive Interpretation", styles["h1"]),
        Paragraph(
            "Reasoned analysis below is constrained by collected public evidence. "
            "Unverified areas are labeled as evidence gaps.",
            styles["small"],
        ),
        *_interpretation_cards(report, styles),
        Spacer(1, 4 * mm),
        Paragraph("Competitive Battlecard", styles["h2"]),
        _battlecard_table(report, styles),
        Spacer(1, 4 * mm),
        *(_ai_analysis_cards(report, styles) if report.ai_analysis else []),
        Paragraph("Evidence Ledger", styles["h2"]),
        Paragraph(
            "Customer-facing citations are compact. Download evidence for the full ledger.",
            styles["small"],
        ),
        _source_table(report, styles),
        Spacer(1, 3 * mm),
        Paragraph("Competitive Implications", styles["h2"]),
        *_bullet(_competitive_implications(report), styles, small=True),
    ]
    document.build(story, onFirstPage=_footer(report), onLaterPages=_footer(report))
    pdf = buffer.getvalue()
    validate_pdf_page_limit(pdf, has_ai_analysis=report.ai_analysis is not None)
    return pdf


def validate_pdf_page_limit(pdf: bytes, *, has_ai_analysis: bool) -> None:
    page_count = len(PdfReader(BytesIO(pdf)).pages)
    maximum = 4
    if page_count < 1 or page_count > maximum:
        raise PDFValidationError(
            f"Competitor report must contain at least 1 and at most {maximum} page"
            f"{'s' if maximum != 1 else ''}; generated {page_count}."
        )


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "eyebrow": ParagraphStyle(
            "Eyebrow",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#3155FF"),
            spaceAfter=3,
            uppercase=True,
        ),
        "title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=25,
            leading=28,
            textColor=colors.HexColor("#141821"),
            alignment=TA_LEFT,
            spaceAfter=4,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=25,
            leading=28,
            textColor=colors.HexColor("#141821"),
            alignment=TA_LEFT,
            spaceAfter=4,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=15,
            textColor=colors.HexColor("#141821"),
            spaceBefore=2,
            spaceAfter=5,
        ),
        "h3": ParagraphStyle(
            "H3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#5A6475"),
            spaceAfter=3,
        ),
        "meta": ParagraphStyle(
            "Meta",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.2,
            leading=9,
            textColor=MUTED,
        ),
        "glance": ParagraphStyle(
            "Glance",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=INK,
        ),
        "inverse_eyebrow": ParagraphStyle(
            "InverseEyebrow",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=6.8,
            leading=8,
            textColor=colors.HexColor("#D7FF3F"),
            spaceAfter=2,
            uppercase=True,
        ),
        "glance_inverse": ParagraphStyle(
            "GlanceInverse",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=PAPER,
        ),
        "fact_label": ParagraphStyle(
            "FactLabel",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=8.5,
            textColor=MUTED,
            uppercase=True,
        ),
        "fact_value": ParagraphStyle(
            "FactValue",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=11.5,
            textColor=INK,
        ),
        "section_title": ParagraphStyle(
            "SectionTitle",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=12.5,
            textColor=INK,
            spaceAfter=2,
        ),
        "section_description": ParagraphStyle(
            "SectionDescription",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=9.5,
            textColor=MUTED,
            spaceAfter=4,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.3,
            leading=10.5,
            textColor=INK,
            leftIndent=7,
            firstLineIndent=-7,
            spaceAfter=3,
        ),
        "source": ParagraphStyle(
            "Source",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=6.6,
            leading=8.2,
            textColor=MUTED,
        ),
        "note": ParagraphStyle(
            "Note",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=6.6,
            leading=8.2,
            textColor=MUTED,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#20242D"),
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#596273"),
            spaceAfter=4,
        ),
        "metric": ParagraphStyle(
            "Metric",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=16,
            textColor=colors.HexColor("#141821"),
        ),
        "metric_label": ParagraphStyle(
            "MetricLabel",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#596273"),
        ),
        "citation": ParagraphStyle(
            "Citation",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=5.8,
            leading=7,
            textColor=colors.HexColor("#8A92A3"),
            spaceAfter=2,
        ),
    }


def _prototype_header(report: ReportView, styles: dict[str, ParagraphStyle]) -> list:
    return [
        Paragraph("PUBLIC-SOURCE COMPETITOR DOSSIER", styles["eyebrow"]),
        Paragraph(_safe(report.domain), styles["title"]),
        Paragraph(
            _safe(
                "A scan-first report combining competitive interpretation, business signals, "
                "and strict citation discipline."
            ),
            styles["body"],
        ),
        Table([[""]], colWidths=[170 * mm], rowHeights=[0.8]),
    ]


def _metric_grid(report: ReportView, styles: dict[str, ParagraphStyle]) -> Table:
    metrics = report.executive.top_metrics[:6]
    while len(metrics) < 6:
        metrics.append(type(metrics[0])("Data unavailable", "Data unavailable"))
    data = [
        [
            _metric(metrics[0].value, metrics[0].label, styles),
            _metric(metrics[1].value, metrics[1].label, styles),
            _metric(metrics[2].value, metrics[2].label, styles),
        ],
        [
            _metric(metrics[3].value, metrics[3].label, styles),
            _metric(metrics[4].value, metrics[4].label, styles),
            _metric(metrics[5].value, metrics[5].label, styles),
        ],
    ]
    table = Table(data, colWidths=[55 * mm, 55 * mm, 55 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#CDD3E2")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CDD3E2")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7F8FC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _metric(value: str, label: str, styles: dict[str, ParagraphStyle]) -> list:
    return [
        Paragraph(_safe(value), styles["metric"]),
        Paragraph(_safe(label), styles["metric_label"]),
    ]


def _card(
    title: str,
    body: str,
    styles: dict[str, ParagraphStyle],
    *,
    bg: str = "#FFFFFF",
    border: str = "#CDD3E2",
) -> Table:
    table = Table(
        [[Paragraph(_safe(title.upper()), styles["h3"]), Paragraph(_safe(body), styles["body"])]],
        colWidths=[45 * mm, 120 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(border)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _bullet(items: list[str], styles: dict[str, ParagraphStyle], *, small: bool = False) -> list:
    style = styles["small"] if small else styles["body"]
    return [Paragraph(f"- {_safe(item)}", style) for item in items[:6]]


def _takeaways_table(report: ReportView, styles: dict[str, ParagraphStyle]) -> Table:
    rows = [
        ["Signal", "What it means", "Evidence"],
        [
            "Clear offer",
            _first_section_point(report, "What they offer"),
            _source_marker(report, "What they offer"),
        ],
        [
            "Proof depth",
            _proof_read(report),
            _source_marker(report, "Customer trust and recent activity"),
        ],
        [
            "Buyer risk",
            "Claims are useful but should be treated as public-source evidence, "
            "not independent verification.",
            "Inference",
        ],
    ]
    return _simple_table(rows, [32 * mm, 102 * mm, 31 * mm], styles, font_size=7.5)


def _method_table(report: ReportView, styles: dict[str, ParagraphStyle]) -> Table:
    rows = [
        ["Control", "How the report treats it"],
        [
            "Claims",
            "Only public-source facts with source references are used in the customer dossier.",
        ],
        [
            "Missing data",
            "Unknowns stay unknown; the report does not infer private performance or intent.",
        ],
        [
            "Evidence depth",
            f"{report.coverage_sentence} Full fact ledger remains available separately.",
        ],
    ]
    return _simple_table(rows, [36 * mm, 129 * mm], styles, font_size=7.2)


def _product_table(report: ReportView, styles: dict[str, ParagraphStyle]) -> Table:
    offer_points = _section_points(report, "What they offer")
    rows = [["Offer / item signal", "Observed evidence", "Read"]]
    prices = next(
        (fact.value for fact in report.executive.quick_facts if fact.label == "Observed prices"),
        "Data unavailable",
    )
    product = next(
        (fact.value for fact in report.executive.quick_facts if fact.label == "Products spotted"),
        "Data unavailable",
    )
    collections = next(
        (
            fact.value
            for fact in report.executive.quick_facts
            if fact.label == "Collections spotted"
        ),
        "Data unavailable",
    )
    rows.append(["Products observed", _shorten(product, 70), "Actual public product links"])
    rows.append(["Collections observed", _shorten(collections, 70), "Catalog grouping, not SKUs"])
    rows.append(["Visible price signal", prices, "Public catalog / product pricing"])
    for point in offer_points[:4]:
        rows.append(
            [
                "Offer evidence",
                _source_marker(report, "What they offer"),
                point,
            ]
        )
    while len(rows) < 5:
        rows.append(["Data unavailable", "Data unavailable", "No validated public data"])
    return _simple_table(rows[:6], [50 * mm, 45 * mm, 70 * mm], styles, font_size=8)


def _catalog_table(report: ReportView, styles: dict[str, ParagraphStyle]) -> Table:
    rows = [["Signal", "Visible evidence", "Source"]]
    for title in ("What they offer", "What stands out", "Customer trust and recent activity"):
        rows.append(
            [
                title,
                _first_section_point(report, title),
                _source_marker(report, title),
            ]
        )
    return _simple_table(rows, [36 * mm, 92 * mm, 37 * mm], styles, font_size=7.5)


def _battlecard_table(report: ReportView, styles: dict[str, ParagraphStyle]) -> Table:
    rows = [
        ["Arena", "Competitor signal", "Competitive response"],
        [
            "Offer",
            _first_section_point(report, "What they offer"),
            "Compete with clearer proof, sharper packaging, or easier comparison.",
        ],
        [
            "Proof",
            _first_section_point(report, "Customer trust and recent activity"),
            "Show customer outcomes, reviews, usage photos, and third-party trust signals.",
        ],
        [
            "Positioning",
            _first_section_point(report, "What stands out"),
            "Make the claim specific, measurable, and easier to verify.",
        ],
    ]
    return _simple_table(rows, [30 * mm, 62 * mm, 73 * mm], styles, font_size=7.5)


def _source_table(report: ReportView, styles: dict[str, ParagraphStyle]) -> Table:
    rows = [["Source", "Used for"]]
    for source in report.executive.sources[:6]:
        rows.append([f"[{source.number}] {source.label}", _source_usage(report, source.number)])
    if len(rows) == 1:
        rows.append(["Data unavailable", "No source ledger was available."])
    return _simple_table(rows, [45 * mm, 120 * mm], styles, font_size=7)


def _simple_table(
    rows: list[list[str]],
    widths: list[float],
    styles: dict[str, ParagraphStyle],
    *,
    font_size: float,
) -> Table:
    wrapped = [
        row if index == 0 else [Paragraph(_safe(str(cell)), styles["small"]) for cell in row]
        for index, row in enumerate(rows)
    ]
    table = Table(wrapped, colWidths=widths)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), font_size),
                ("LEADING", (0, 0), (-1, -1), font_size + 1.5),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CDD3E2")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _interpretation_cards(report: ReportView, styles: dict[str, ParagraphStyle]) -> list:
    strengths = _first_section_point(report, "What they offer")
    gaps = "; ".join(report.executive.unknowns[:2]) or "No major evidence gap was surfaced."
    likely_buyer = _first_section_point(report, "What stands out")
    return [
        _card(
            "Strengths",
            _with_source(strengths, _source_for_section(report, "What they offer")),
            styles,
        ),
        Spacer(1, 3 * mm),
        _card(
            "Weaknesses / gaps",
            gaps,
            styles,
            bg="#FFF8E6",
            border="#E6D39D",
        ),
        Spacer(1, 3 * mm),
        _card(
            "Likely buyer",
            _with_source(likely_buyer, _source_for_section(report, "What stands out")),
            styles,
        ),
    ]


def _ai_analysis_cards(report: ReportView, styles: dict[str, ParagraphStyle]) -> list:
    if not report.ai_analysis:
        return []
    blocks = [
        ("AI Summary", report.ai_analysis.summary[:2]),
        ("Differentiators", report.ai_analysis.differentiators[:2]),
        ("Commercial Observations", report.ai_analysis.commercial_observations[:2]),
        ("Public Signals", report.ai_analysis.public_signals[:2]),
        ("Risks And Unknowns", report.ai_analysis.risks_and_unknowns[:2]),
    ]
    story = [Paragraph("Strategic Analysis", styles["h2"])]
    for title, statements in blocks:
        story.append(_ai_statement_card(title, statements, styles))
        story.append(Spacer(1, 2 * mm))
    return story


def _ai_statement_card(
    title: str,
    statements,
    styles: dict[str, ParagraphStyle],
) -> Table:
    body = [Paragraph(_safe(title.upper()), styles["h3"])]
    if not statements:
        body.append(Paragraph("Data unavailable", styles["body"]))
    for statement in statements:
        body.append(Paragraph(_safe(statement.text), styles["body"]))
        citation = ", ".join(statement.citation_ids[:3])
        if citation:
            body.append(Paragraph(_safe(f"Evidence: {citation}"), styles["citation"]))
    table = Table([[body]], colWidths=[165 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#D8DDE8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _footer(report: ReportView):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#596273"))
        canvas.drawString(14 * mm, 8 * mm, f"{report.domain} competitor dossier")
        canvas.drawRightString(196 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def _section_points(report: ReportView, title: str) -> list[str]:
    section = next((item for item in report.executive.sections if item.title == title), None)
    if section is None or not section.points:
        return ["Data unavailable"]
    return [_with_source(point.text, point.source_number) for point in section.points[:5]]


def _first_section_point(report: ReportView, title: str) -> str:
    section = next((item for item in report.executive.sections if item.title == title), None)
    if section and section.points:
        return section.points[0].text
    return "Data unavailable"


def _source_for_section(report: ReportView, title: str) -> int:
    section = next((item for item in report.executive.sections if item.title == title), None)
    if section and section.points:
        return section.points[0].source_number
    return 0


def _source_marker(report: ReportView, title: str) -> str:
    number = _source_for_section(report, title)
    return f"[{number}]" if number else "Data unavailable"


def _with_source(text: str, source_number: int) -> str:
    return f"{text} [{source_number}]" if source_number else text


def _strategic_read(report: ReportView) -> str:
    trust = _first_section_point(report, "Customer trust and recent activity")
    gaps = "; ".join(report.executive.unknowns[:2])
    if gaps:
        return f"{trust} Evidence gaps: {gaps}"
    return trust


def _evidence_coverage(report: ReportView) -> list[str]:
    items = [f"Verified: {report.executive.coverage_explained}"]
    if report.executive.sources:
        items.append(f"Sources cited: {len(report.executive.sources)} compact source references.")
    if report.executive.unknowns:
        items.append(f"Not verified: {'; '.join(report.executive.unknowns[:2])}.")
    return items


def _offer_intro(report: ReportView) -> str:
    prices = next(
        (fact.value for fact in report.executive.quick_facts if fact.label == "Observed prices"),
        "Data unavailable",
    )
    return (
        f"The public offer map below is assembled from validated product, pricing, "
        f"and positioning evidence. Observed price signal: {prices}."
    )


def _proof_read(report: ReportView) -> str:
    proof = _first_section_point(report, "Customer trust and recent activity")
    if proof == "Data unavailable":
        return "No strong public proof signal was validated in this scan."
    return _shorten(proof, 115)


def _competitive_implications(report: ReportView) -> list[str]:
    return [
        f"Hardest to beat: {_shorten(_first_section_point(report, 'What they offer'), 140)}",
        "Easiest to challenge: "
        f"{'; '.join(report.executive.unknowns[:2]) or 'proof depth and claim specificity.'}",
        "A competitor should show specific evidence, customer outcomes, and clearer proof "
        "than the public pages provide.",
    ]


def _source_usage(report: ReportView, number: int) -> str:
    usages = []
    for section in report.executive.sections:
        if any(point.source_number == number for point in section.points):
            usages.append(section.title)
    if report.executive.at_a_glance_source_number == number:
        usages.append("30-second read")
    return ", ".join(dict.fromkeys(usages)) or "Supporting evidence"


def _offer_signal(report: ReportView) -> str:
    if report.ai_analysis and report.ai_analysis.summary:
        return _sentence_safe_limit(report.ai_analysis.summary[0].text, 72)
    facts = {fact.label: fact.value for fact in report.executive.quick_facts}
    products = facts.get("Products spotted", "Data unavailable")
    collections = facts.get("Collections spotted", "")
    if products and products != "Not clearly identified":
        return products
    if collections and collections != "Not clearly identified":
        return f"Collections: {collections}"
    return _first_section_point(report, "What they offer")


def _ai_label(report: ReportView) -> str:
    if report.ai_analysis:
        return "AI included"
    if report.ai_analysis_status in {"failed", "budget_blocked"}:
        return "AI unavailable"
    return "Deterministic"


def _sentence_safe_limit(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    candidate = normalized[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    for marker in (". ", "! ", "? "):
        boundary = candidate.rfind(marker)
        if boundary >= max(24, int(limit * 0.45)):
            return candidate[: boundary + 1]
    return candidate


def _shorten(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rsplit(' ', 1)[0]}..."


def _header(report: ReportView, styles: dict[str, ParagraphStyle]) -> Table:
    left = [
        Paragraph("VALIDATED INTELLIGENCE DOSSIER", styles["eyebrow"]),
        Paragraph(_safe(report.domain), styles["title"]),
        Paragraph(
            _safe(f"Generated {report.generated_label} | {report.coverage_sentence}"),
            styles["meta"],
        ),
    ]
    right = Paragraph(
        "<b>Research standard</b><br/>Public evidence, validated findings, and traceable "
        "source references.",
        styles["meta"],
    )
    table = Table([[left, right]], colWidths=[128 * mm, 42 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 1.4, INK),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _at_a_glance(report: ReportView, styles: dict[str, ParagraphStyle]) -> Table:
    reference = (
        f" <font color='#596579'>[{report.executive.at_a_glance_source_number}]</font>"
        if report.executive.at_a_glance_source_number
        else ""
    )
    content = [
        Paragraph("EXECUTIVE ASSESSMENT", styles["inverse_eyebrow"]),
        Paragraph(
            f"{_safe(report.executive.at_a_glance)}{reference}",
            styles["glance_inverse"],
        ),
    ]
    table = Table([[content]], colWidths=[170 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), INK),
                ("BOX", (0, 0), (-1, -1), 0.5, INK),
                ("TEXTCOLOR", (0, 0), (-1, -1), PAPER),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _quick_facts(report: ReportView, styles: dict[str, ParagraphStyle]) -> Table:
    cells = []
    for fact in report.executive.quick_facts:
        cells.append(
            [
                Paragraph(_safe(fact.label.upper()), styles["fact_label"]),
                Paragraph(_safe(fact.value), styles["fact_value"]),
            ]
        )
    table = Table([cells], colWidths=[42.5 * mm] * 4)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PAPER),
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _section_grid(report: ReportView, styles: dict[str, ParagraphStyle]) -> Table:
    section_cells = [_section_cell(section, styles) for section in report.executive.sections]
    unknowns = [
        Paragraph("WHAT WE COULD NOT VERIFY", styles["section_title"]),
        Paragraph(
            "Evidence gaps are limitations of this scan, not competitor weaknesses.",
            styles["section_description"],
        ),
    ]
    unknowns.extend(
        Paragraph(f"- {_safe(item)}", styles["bullet"]) for item in report.executive.unknowns
    )
    section_cells.append(unknowns)
    table = Table(
        [[section_cells[0], section_cells[1]], [section_cells[2], section_cells[3]]],
        colWidths=[83 * mm, 83 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("BACKGROUND", (1, 1), (1, 1), PALE_AMBER),
            ]
        )
    )
    return table


def _section_cell(section, styles: dict[str, ParagraphStyle]) -> list:
    content = [
        Paragraph(_safe(section.title.upper()), styles["section_title"]),
        Paragraph(_safe(section.description), styles["section_description"]),
    ]
    if section.points:
        content.extend(
            Paragraph(
                f"- {_safe(item.text)} <font color='#596579'>[{item.source_number}]</font>",
                styles["bullet"],
            )
            for item in section.points
        )
    else:
        content.append(Paragraph("- No usable public evidence found.", styles["bullet"]))
    return content


def _next_checks(report: ReportView, styles: dict[str, ParagraphStyle]) -> Table:
    content = [
        Paragraph("SUGGESTED NEXT CHECKS", styles["section_title"]),
        Paragraph(
            "Research actions for the reader, not conclusions about the competitor.",
            styles["section_description"],
        ),
    ]
    content.extend(
        Paragraph(f"- {_safe(item)}", styles["bullet"]) for item in report.executive.next_checks
    )
    table = Table([[content]], colWidths=[170 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#C7E8D1")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _ai_analysis(report: ReportView, styles: dict[str, ParagraphStyle]) -> list:
    statements = [
        *report.ai_analysis.summary[:2],
        *report.ai_analysis.commercial_observations[:1],
        *report.ai_analysis.public_signals[:1],
    ]
    content = [
        Paragraph("STRATEGIC READING", styles["section_title"]),
        Paragraph(
            "Generated only from the evidence ledger. Citation IDs map to the downloadable "
            "evidence appendix.",
            styles["section_description"],
        ),
    ]
    content.extend(
        Paragraph(
            f"- {_safe(statement.text)} "
            f"<font color='#596579'>[{', '.join(statement.citation_ids)}]</font>",
            styles["bullet"],
        )
        for statement in statements
    )
    table = Table([[content]], colWidths=[170 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PAPER),
                ("BOX", (0, 0), (-1, -1), 1.0, INK),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return [table, Spacer(1, 3 * mm)]


def _sources(report: ReportView, styles: dict[str, ParagraphStyle]) -> KeepTogether:
    source_lines = [
        Paragraph(f"<b>[{source.number}]</b> {_safe(source.label)}", styles["source"])
        for source in report.executive.sources
    ]
    return KeepTogether(
        [
            Paragraph("SOURCES", styles["eyebrow"]),
            *source_lines,
            Spacer(1, 1.5 * mm),
            Paragraph(_safe(report.executive.methodology_note), styles["note"]),
        ]
    )


def _safe(value: str) -> str:
    normalized = (
        value.replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    return escape(normalized)

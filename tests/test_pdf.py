from io import BytesIO

import pytest
from app.reporting.pdf import (
    PDFValidationError,
    render_competitor_pdf_bytes,
    validate_pdf_page_limit,
)
from app.schemas import (
    AIAnalysis,
    BusinessCategory,
    BusinessFact,
    CitedStatement,
    ExtractionResult,
    ExtractionStatus,
    NormalizedBusinessProfile,
    ObservedClaim,
)
from app.tools.competitor_brief.profile_builder import build_competitor_profile
from app.tools.competitor_brief.view_model import build_report_view
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas


def test_pdf_is_real_single_page_report():
    result = ExtractionResult(
        value={
            "claims": [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "Goalkeeper gloves designed around price and quality.",
                    "evidence_excerpt": "Goalkeeper gloves designed around price and quality.",
                    "source_url": "https://example.com/about",
                }
            ]
        },
        source_url="https://example.com/about",
        extractor_name="positioning_facts",
        confidence=0.8,
        status=ExtractionStatus.OK,
    )
    profile = build_competitor_profile("example.com", [result])
    report = build_report_view("example.com", [result], profile)

    pdf = render_competitor_pdf_bytes(report)
    reader = PdfReader(BytesIO(pdf))

    assert pdf.startswith(b"%PDF")
    assert 1 <= len(reader.pages) <= 3
    assert "30-SECOND READ" in reader.pages[0].extract_text()


def test_pdf_includes_ai_analysis_when_available():
    result = ExtractionResult(
        value={
            "claims": [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "A concise public claim.",
                    "evidence_excerpt": "A concise public claim.",
                    "source_url": "https://example.com/about",
                }
            ]
        },
        source_url="https://example.com/about",
        extractor_name="positioning_facts",
        confidence=0.8,
        status=ExtractionStatus.OK,
    )
    profile = build_competitor_profile("example.com", [result])
    analysis = AIAnalysis(
        summary=[CitedStatement(text="The company makes a concise claim.", citation_ids=["F001"])]
    )
    report = build_report_view("example.com", [result], profile, ai_analysis=analysis)

    reader = PdfReader(BytesIO(render_competitor_pdf_bytes(report)))
    text = "\n".join(page.extract_text() for page in reader.pages)

    assert "Strategic Analysis" in text
    assert "F001" in text


def test_pdf_moves_ai_analysis_near_top_before_evidence_coverage():
    result = ExtractionResult(
        value={
            "claims": [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "A concise public claim.",
                    "evidence_excerpt": "A concise public claim.",
                    "source_url": "https://example.com/about",
                }
            ]
        },
        source_url="https://example.com/about",
        extractor_name="positioning_facts",
        confidence=0.8,
        status=ExtractionStatus.OK,
    )
    profile = build_competitor_profile("example.com", [result])
    analysis = AIAnalysis(
        summary=[CitedStatement(text="The company makes a concise claim.", citation_ids=["F001"])]
    )
    report = build_report_view("example.com", [result], profile, ai_analysis=analysis)

    reader = PdfReader(BytesIO(render_competitor_pdf_bytes(report)))
    text = "\n".join(page.extract_text() for page in reader.pages)

    assert text.index("Strategic Analysis") < text.index("Evidence Coverage")
    assert text.index("Strategic Analysis") < text.index("Product & Pricing Map")


def test_pdf_uses_complete_sentence_for_thirty_second_read():
    result = ExtractionResult(
        value={
            "claims": [
                {
                    "category": "positioning",
                    "fact_type": "structured_description",
                    "value": (
                        "Solo GK is a goalkeeper glove brand serving keepers who want "
                        "specialist equipment and clear buying guidance. This second sentence "
                        "is intentionally long enough that a naive character cutoff would "
                        "slice it in the middle of a thought."
                    ),
                    "evidence_excerpt": "Solo GK is a goalkeeper glove brand.",
                    "source_url": "https://example.com/about",
                }
            ]
        },
        source_url="https://example.com/about",
        extractor_name="positioning_facts",
        confidence=0.8,
        status=ExtractionStatus.OK,
    )
    profile = build_competitor_profile("example.com", [result])
    report = build_report_view("example.com", [result], profile)

    text = PdfReader(BytesIO(render_competitor_pdf_bytes(report))).pages[0].extract_text()

    assert "Solo GK is a goalkeeper glove brand" in text
    assert "thought..." not in text
    assert "30-SECOND READ" in text


def test_pdf_product_map_labels_collections_apart_from_products():
    claims = [
        ObservedClaim(
            category=BusinessCategory.PRODUCTS_MODULES,
            fact_type="product_collection",
            value="Lunar",
            evidence_excerpt="Lunar",
            source_url="https://example.com/collections/lunar",
        ),
        ObservedClaim(
            category=BusinessCategory.PRODUCTS_MODULES,
            fact_type="product_collection",
            value="Vortex",
            evidence_excerpt="Vortex",
            source_url="https://example.com/collections/vortex",
        ),
        ObservedClaim(
            category=BusinessCategory.PRODUCTS_MODULES,
            fact_type="linked_product",
            value="Lunar 2",
            evidence_excerpt="Lunar 2",
            source_url="https://example.com/products/lunar-2",
        ),
    ]
    result = ExtractionResult(
        value={"claims": [claim.model_dump(mode="json") for claim in claims]},
        source_url="https://example.com/",
        extractor_name="products_modules_facts",
        confidence=0.8,
        status=ExtractionStatus.OK,
    )
    profile = build_competitor_profile("example.com", [result])
    report = build_report_view("example.com", [result], profile)

    reader = PdfReader(BytesIO(render_competitor_pdf_bytes(report)))
    text = "\n".join(page.extract_text() for page in reader.pages)

    assert "Products observed" in text
    assert "Lunar 2" in text
    assert "Collections observed" in text
    assert "Lunar, Vortex" in text


def test_pdf_uses_prototype_top_metrics_and_does_not_truncate_catalog_rows():
    long_claim = (
        "Contact latex, wet-weather grip, dry-weather grip, buyer guidance, and accessible "
        "pricing are all visible public offer signals for the brand."
    )
    claims = [
        ObservedClaim(
            category=BusinessCategory.POSITIONING,
            fact_type="page_claim",
            value="Solo GK is a UK-based goalkeeper glove brand.",
            evidence_excerpt="Solo GK is a UK-based goalkeeper glove brand.",
            source_url="https://example.com/about",
        ),
        ObservedClaim(
            category=BusinessCategory.PRODUCTS_MODULES,
            fact_type="page_claim",
            value=long_claim,
            evidence_excerpt=long_claim,
            source_url="https://example.com/products/lunar-2",
        ),
        *[
            ObservedClaim(
                category=BusinessCategory.PRODUCTS_MODULES,
                fact_type="linked_product",
                value=f"Lunar glove {index}",
                evidence_excerpt=f"Lunar glove {index}",
                source_url=f"https://example.com/products/lunar-{index}",
            )
            for index in range(1, 21)
        ],
        ObservedClaim(
            category=BusinessCategory.PRODUCTS_MODULES,
            fact_type="visible_price",
            value="Â£25",
            evidence_excerpt="Â£25",
            source_url="https://example.com/products/lunar-1",
        ),
        ObservedClaim(
            category=BusinessCategory.PRODUCTS_MODULES,
            fact_type="visible_price",
            value="Â£40",
            evidence_excerpt="Â£40",
            source_url="https://example.com/products/lunar-2",
        ),
    ]
    result = ExtractionResult(
        value={"claims": [claim.model_dump(mode="json") for claim in claims]},
        source_url="https://example.com/",
        extractor_name="products_modules_facts",
        confidence=0.8,
        status=ExtractionStatus.OK,
    )
    profile = build_competitor_profile("example.com", [result])
    report = build_report_view("example.com", [result], profile)

    reader = PdfReader(BytesIO(render_competitor_pdf_bytes(report)))
    text = "\n".join(page.extract_text() for page in reader.pages)

    assert "Country" in text
    assert "Industry" in text
    assert "Business model" in text
    assert "Observed price band" in text
    assert "Shop listing count" in text
    assert "20 items" in text
    normalized_text = " ".join(text.split())
    assert long_claim in normalized_text
    assert "accessible pricing are all visible public offer signals" in normalized_text


def test_pdf_uses_dynamic_portfolio_metric_label_for_non_ecommerce():
    result = ExtractionResult(
        value={
            "claims": [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "Hostinger offers web hosting and a website builder.",
                    "evidence_excerpt": "Hostinger offers web hosting and a website builder.",
                    "source_url": "https://hostinger.example/",
                },
                {
                    "category": "pricing_packaging",
                    "fact_type": "visible_price",
                    "value": "$2.99",
                    "evidence_excerpt": "$2.99",
                    "source_url": "https://hostinger.example/pricing",
                },
            ]
        },
        source_url="https://hostinger.example/",
        extractor_name="positioning_facts",
        confidence=0.8,
        status=ExtractionStatus.OK,
    )
    profile = build_competitor_profile("hostinger.example", [result])
    report = build_report_view("hostinger.example", [result], profile)

    reader = PdfReader(BytesIO(render_competitor_pdf_bytes(report)))
    text = "\n".join(page.extract_text() for page in reader.pages)

    assert "Commercial signal" in text
    assert "Pricing visible" in text


def test_full_dossier_contains_all_ai_analysis_and_full_evidence_ledger():
    from app.reporting.dossier_pdf import render_full_dossier_bytes

    result = ExtractionResult(
        value={
            "claims": [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "A concise public claim.",
                    "evidence_excerpt": "A concise public claim.",
                    "source_url": "https://example.com/about",
                }
            ]
        },
        source_url="https://example.com/about",
        extractor_name="positioning_facts",
        confidence=0.8,
        status=ExtractionStatus.OK,
    )
    profile = build_competitor_profile("example.com", [result])
    business_profile = NormalizedBusinessProfile(
        domain="example.com",
        facts=[
            BusinessFact(
                citation_id="F001",
                kind="product",
                value="Complete evidence ledger item",
                evidence_excerpt="Complete evidence excerpt",
                source_url="https://example.com/product",
                category="products_modules",
            )
        ],
    )
    analysis = AIAnalysis(
        summary=[CitedStatement(text="Summary statement.", citation_ids=["F001"])],
        differentiators=[CitedStatement(text="Differentiator statement.", citation_ids=["F001"])],
        commercial_observations=[
            CitedStatement(text="Commercial statement.", citation_ids=["F001"])
        ],
        risks_and_unknowns=[CitedStatement(text="Risk statement.", citation_ids=["F001"])],
    )
    report = build_report_view(
        "example.com",
        [result],
        profile,
        business_profile=business_profile,
        ai_analysis=analysis,
    )

    reader = PdfReader(BytesIO(render_full_dossier_bytes(report)))
    text = "\n".join(page.extract_text() for page in reader.pages)

    assert 1 <= len(reader.pages) <= 3
    assert "30-SECOND READ" in text
    assert "Competitive Interpretation" in text
    assert "Competitive Battlecard" in text
    assert "Differentiator statement." in text
    assert "Commercial statement." in text
    assert "Risk statement." in text
    assert "Complete evidence ledger item" not in text
    assert "https://example.com/product" not in text


def _multi_page_pdf(page_count: int) -> bytes:
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    for page in range(page_count):
        canvas.drawString(20, 20, f"page {page + 1}")
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def test_pdf_validator_requires_one_page_without_ai():
    validate_pdf_page_limit(_multi_page_pdf(4), has_ai_analysis=False)

    with pytest.raises(PDFValidationError, match="at most 4 pages"):
        validate_pdf_page_limit(_multi_page_pdf(5), has_ai_analysis=False)


def test_pdf_validator_allows_up_to_four_pages_with_ai():
    validate_pdf_page_limit(_multi_page_pdf(4), has_ai_analysis=True)

    with pytest.raises(PDFValidationError, match="at most 4 pages"):
        validate_pdf_page_limit(_multi_page_pdf(5), has_ai_analysis=True)

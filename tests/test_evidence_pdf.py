from io import BytesIO

from app.reporting.evidence_pdf import render_evidence_appendix_bytes
from app.schemas import BusinessFact, NormalizedBusinessProfile
from pypdf import PdfReader


def test_evidence_appendix_contains_citation_and_source():
    profile = NormalizedBusinessProfile(
        domain="example.com",
        facts=[
            BusinessFact(
                citation_id="F001",
                kind="price",
                value="$40",
                evidence_excerpt="Lunar Pro - $40",
                source_url="https://example.com/lunar",
                source_title="Lunar glove",
                category="products_modules",
            )
        ],
    )

    pdf = render_evidence_appendix_bytes(profile)
    text = PdfReader(BytesIO(pdf)).pages[0].extract_text()

    assert "F001" in text
    assert "Lunar glove" in text

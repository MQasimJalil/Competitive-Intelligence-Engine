from app.scrapers.structured_data import extract_structured_data


def test_extract_structured_data_collects_company_products_and_social_links():
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@graph": [
        {
          "@type": "Organization",
          "description": "Professional goalkeeper gloves at accessible prices.",
          "sameAs": ["https://instagram.com/example"]
        },
        {"@type": "Product", "name": "Eclipse Pro"}
      ]
    }
    </script>
    """

    results = extract_structured_data(html, "https://example.com")

    facts = next(result for result in results if result.extractor_name == "structured_data_facts")
    social = next(
        result for result in results if result.extractor_name == "structured_social_links"
    )
    values = [claim["value"] for claim in facts.value["claims"]]
    assert "Professional goalkeeper gloves at accessible prices." in values
    assert "Eclipse Pro" in values
    assert social.value == ["https://instagram.com/example"]

import pytest
from app.schemas import ExtractionResult, ExtractionStatus
from pydantic import ValidationError


def test_ok_result_requires_value():
    with pytest.raises(ValidationError):
        ExtractionResult(
            value="",
            source_url="https://example.com",
            extractor_name="page_title",
            confidence=0.9,
            status=ExtractionStatus.OK,
        )


def test_ok_result_requires_source_url():
    with pytest.raises(ValidationError):
        ExtractionResult(
            value="Example",
            extractor_name="page_title",
            confidence=0.9,
            status=ExtractionStatus.OK,
        )


def test_unavailable_result_has_safe_defaults():
    result = ExtractionResult.unavailable(extractor_name="pricing")
    assert result.value is None
    assert result.status == ExtractionStatus.NO_DATA
    assert result.confidence == 0.0

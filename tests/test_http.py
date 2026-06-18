from app.schemas import ExtractionStatus
from app.scrapers.http import status_for_http_response


def test_status_for_http_response_maps_common_failures():
    assert status_for_http_response(200) == ExtractionStatus.OK
    assert status_for_http_response(404) == ExtractionStatus.NO_DATA
    assert status_for_http_response(429) == ExtractionStatus.RATE_LIMITED
    assert status_for_http_response(403) == ExtractionStatus.TOS_BLOCKED
    assert status_for_http_response(500) == ExtractionStatus.NETWORK_FAILED

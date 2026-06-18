from collections.abc import Iterable

from app.schemas import ExtractionResult, ExtractionStatus


def display_value(result: ExtractionResult) -> str:
    if result.status != ExtractionStatus.OK or result.value is None:
        return "Data unavailable"
    if isinstance(result.value, dict):
        return ", ".join(f"{key}: {value}" for key, value in result.value.items())
    if isinstance(result.value, list):
        return ", ".join(str(item) for item in result.value)
    return str(result.value)


def summarize_results(results: Iterable[ExtractionResult]) -> dict[str, int]:
    counts = {status.value: 0 for status in ExtractionStatus}
    for result in results:
        counts[result.status.value] += 1
    return counts

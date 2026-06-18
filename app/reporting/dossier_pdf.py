from app.reporting.pdf import render_competitor_pdf_bytes
from app.tools.competitor_brief.view_model import ReportView


def render_full_dossier_bytes(report: ReportView) -> bytes:
    return render_competitor_pdf_bytes(report)

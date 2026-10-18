"""Server-side PDF for signed consultation summaries ."""

from __future__ import annotations

import datetime as dt
import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

from ibolit.core import clock
from ibolit.consultations.models import Consultation, ConsultationSummary


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_summary_pdf(summary: ConsultationSummary, consultation: Consultation, *, signed_at: dt.datetime) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title="Consultation summary", author="iBolit",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor="#142D3B")
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor="#087F72")
    body = styles["BodyText"]
    tz = clock.clinic_tz()
    appointment = consultation.appointment
    provider = consultation.provider
    specialty = provider.specialty.name_i18n.get("en", "") if provider.specialty else ""

    story = [
        Paragraph(_escape(summary.title), h1),
        Paragraph(
            _escape(
                f"{provider.display_name} · {specialty} · {appointment.starts_at.astimezone(tz):%d %b %Y · %H:%M}"
                f"–{appointment.ends_at.astimezone(tz):%H:%M} (Almaty)"
            ),
            body,
        ),
        Paragraph(_escape(f"Patient: {consultation.patient.full_name}"), body),
        Spacer(1, 6 * mm),
        Paragraph("Assessment", h2),
        Paragraph(_escape(summary.assessment), body),
        Paragraph("What we discussed", h2),
        Paragraph(_escape(summary.discussed), body),
    ]
    if summary.next_steps:
        story.append(Paragraph("Your next steps", h2))
        story.append(ListFlowable([ListItem(Paragraph(_escape(step), body)) for step in summary.next_steps], bulletType="bullet"))
    if summary.follow_up_at:
        story.append(Paragraph("Follow-up", h2))
        story.append(Paragraph(_escape(f"{summary.follow_up_at.astimezone(tz):%d %b · %H:%M}"), body))
    story += [
        Spacer(1, 8 * mm),
        Paragraph(
            _escape(
                f"Clinician-authored summary, version {summary.version}. Reviewed and signed by "
                f"{provider.display_name} on {signed_at.astimezone(tz):%d %b %Y %H:%M} (Almaty)."
            ),
            body,
        ),
        Paragraph(_escape("Call 103 if you develop a sudden severe headache, weakness or fainting."), body),
    ]
    doc.build(story)
    return buffer.getvalue()

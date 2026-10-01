"""Helpers for Slice 12 agency-portal tests: make an agency user + build small PDFs."""

from __future__ import annotations

from io import BytesIO

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from api.app.models.public import StaffRole
from api.app.services.staff import create_staff, grant_workspace_access


def make_agency_user(*, clerk_user_id: str, email: str, workspace_id: int) -> int:
    """Create an agency Staff row bound to exactly one workspace; return its staff id."""
    staff = create_staff(clerk_user_id=clerk_user_id, email=email, role=StaffRole.agency)
    grant_workspace_access(staff_id=staff.id, workspace_id=workspace_id)
    return staff.id


def pdf_with_image() -> bytes:
    """A one-page PDF with an embedded raster image (an XObject pypdf can extract)."""
    img = Image.new("RGB", (24, 24), (120, 120, 120))
    ibuf = BytesIO()
    img.save(ibuf, format="PNG")
    ibuf.seek(0)
    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawImage(ImageReader(ibuf), 20, 20, width=60, height=60)
    c.showPage()
    c.save()
    return buf.getvalue()


def pdf_text_only() -> bytes:
    """A one-page PDF with no embedded images."""
    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(20, 20, "authorization letter")
    c.showPage()
    c.save()
    return buf.getvalue()

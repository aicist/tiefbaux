from __future__ import annotations

import io
import os
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from ..schemas import ExportOfferMetadata, OfferLine

# ── Company info ────────────────────────────────────────────────────
COMPANY_NAME = "Faßbender Tenten GmbH & Co. KG"
COMPANY_ADDRESS = "Bornheimer Str. 172–180 · 53119 Bonn"
COMPANY_CONTACT = "Tel. 0228 / 64808-71 · info@fassbender-tenten.de"
COMPANY_CITY = "Bonn"
_LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "logo_ft.jpg")

# ── Colors ──────────────────────────────────────────────────────────
DARK = colors.HexColor("#0F2B46")
ACCENT = colors.HexColor("#146c60")
GRAY_600 = colors.HexColor("#475569")
GRAY_400 = colors.HexColor("#94A3B8")
GRAY_200 = colors.HexColor("#E2E8F0")
ROW_ALT = colors.HexColor("#F8FAFC")
WHITE = colors.white

PAGE_W, PAGE_H = A4
L_MARGIN = 25 * mm
R_MARGIN = 20 * mm
T_MARGIN = 40 * mm
B_MARGIN = 25 * mm
CONTENT_W = PAGE_W - L_MARGIN - R_MARGIN


# ── Number formatting (German locale) ──────────────────────────────
def _fmt_money(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_qty(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(round(value, 3)).replace(".", ",")


# ── NumberedCanvas for "Seite X von Y" ─────────────────────────────
class NumberedCanvas(canvas.Canvas):
    """Canvas subclass that tracks pages and renders 'Seite X von Y' on each."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_number(num_pages)
            super().showPage()
        super().save()

    def _draw_page_number(self, total: int):
        self.setFont("Helvetica", 8)
        self.setFillColor(GRAY_400)
        text = f"Seite {self._pageNumber} von {total}"
        self.drawRightString(PAGE_W - R_MARGIN, 12 * mm, text)


# ── Page callbacks ──────────────────────────────────────────────────
def _draw_header_footer(canvas_obj: canvas.Canvas, doc, metadata: ExportOfferMetadata):
    """Draw company header and footer on every page."""
    canvas_obj.saveState()

    # ── Header: logo (left) + company info (right-aligned) ───
    x_right = PAGE_W - R_MARGIN
    y_top = PAGE_H - 15 * mm

    # Logo — vertically centered with the company text block
    logo = os.path.normpath(_LOGO_PATH)
    if os.path.isfile(logo):
        logo_h = 22 * mm
        text_center_y = y_top - 11  # midpoint of the 3 text lines
        canvas_obj.drawImage(logo, L_MARGIN, text_center_y - logo_h / 2, width=logo_h, height=logo_h, preserveAspectRatio=True, mask="auto")

    canvas_obj.setFont("Helvetica-Bold", 10)
    canvas_obj.setFillColor(DARK)
    canvas_obj.drawRightString(x_right, y_top, COMPANY_NAME)
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(GRAY_600)
    canvas_obj.drawRightString(x_right, y_top - 12, COMPANY_ADDRESS)
    canvas_obj.drawRightString(x_right, y_top - 22, COMPANY_CONTACT)

    # ── Header line ───
    canvas_obj.setStrokeColor(ACCENT)
    canvas_obj.setLineWidth(1.5)
    canvas_obj.line(L_MARGIN, PAGE_H - T_MARGIN + 5 * mm, x_right, PAGE_H - T_MARGIN + 5 * mm)

    # ── Footer ───
    canvas_obj.setStrokeColor(GRAY_200)
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(L_MARGIN, B_MARGIN - 5 * mm, x_right, B_MARGIN - 5 * mm)

    canvas_obj.restoreState()


# ── Styles ──────────────────────────────────────────────────────────
def _make_styles() -> dict[str, ParagraphStyle]:
    return {
        "heading": ParagraphStyle(
            "Heading",
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=DARK,
            spaceAfter=2 * mm,
        ),
        "subheading": ParagraphStyle(
            "SubHeading",
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=GRAY_600,
        ),
        "address_small": ParagraphStyle(
            "AddressSmall",
            fontName="Helvetica",
            fontSize=7,
            leading=9,
            textColor=GRAY_400,
        ),
        "address": ParagraphStyle(
            "Address",
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=DARK,
        ),
        "label": ParagraphStyle(
            "Label",
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=GRAY_600,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=DARK,
        ),
        "body_small": ParagraphStyle(
            "BodySmall",
            fontName="Helvetica",
            fontSize=7,
            leading=9,
            textColor=GRAY_600,
        ),
        "section_header": ParagraphStyle(
            "SectionHeader",
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=DARK,
        ),
        "total_label": ParagraphStyle(
            "TotalLabel",
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=DARK,
            alignment=2,  # RIGHT
        ),
        "total_value": ParagraphStyle(
            "TotalValue",
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=14,
            textColor=DARK,
            alignment=2,
        ),
        "total_brutto_label": ParagraphStyle(
            "TotalBruttoLabel",
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=DARK,
            alignment=2,
        ),
        "total_brutto_value": ParagraphStyle(
            "TotalBruttoValue",
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=ACCENT,
            alignment=2,
        ),
    }


# ── Main PDF builder ───────────────────────────────────────────────
def build_offer_pdf(lines: list[OfferLine], metadata: ExportOfferMetadata) -> bytes:
    buffer = io.BytesIO()

    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=L_MARGIN,
        rightMargin=R_MARGIN,
        topMargin=T_MARGIN,
        bottomMargin=B_MARGIN,
        title="Angebot",
        author="TiefbauX",
    )

    frame = Frame(L_MARGIN, B_MARGIN, CONTENT_W, PAGE_H - T_MARGIN - B_MARGIN, id="main")

    def on_page(c, d):
        _draw_header_footer(c, d, metadata)

    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=on_page)])

    styles = _make_styles()
    story: list = []

    # ── Recipient address block ───
    story.append(
        Paragraph(
            f"{COMPANY_NAME} · {COMPANY_ADDRESS}",
            styles["address_small"],
        )
    )
    story.append(Spacer(1, 3 * mm))

    customer_name = metadata.customer_name or "—"
    customer_address = metadata.customer_address or ""
    address_lines = f"<b>{customer_name}</b>"
    if customer_address:
        address_lines += f"<br/>{customer_address}"
    story.append(Paragraph(address_lines, styles["address"]))
    story.append(Spacer(1, 10 * mm))

    # ── Date + reference ───
    date_str = metadata.created_at.strftime("%d.%m.%Y")
    offer_nr = metadata.created_at.strftime("A-%Y%m%d-%H%M")
    story.append(
        Paragraph(f"{COMPANY_CITY}, {date_str}", styles["label"])
    )
    story.append(Spacer(1, 5 * mm))

    # ── Subject line ───
    project = metadata.project_name or "—"
    story.append(
        Paragraph(f"Angebot {offer_nr}", styles["heading"])
    )
    story.append(
        Paragraph(f"Projekt: {project}", styles["subheading"])
    )
    story.append(Spacer(1, 8 * mm))

    # ── Intro text ───
    story.append(
        Paragraph(
            "Sehr geehrte Damen und Herren,<br/><br/>"
            "für die nachfolgend aufgeführten Leistungen erlauben wir uns, "
            "Ihnen folgendes Angebot zu unterbreiten:",
            styles["body"],
        )
    )
    story.append(Spacer(1, 6 * mm))

    # ── Table with LV positions only ───
    col_widths = [16 * mm, 52 * mm, 48 * mm, 18 * mm, 18 * mm, 22 * mm]
    header_data = ["Pos.", "Beschreibung", "Artikel", "Menge", "EP (€)", "Gesamt (€)"]

    table_data = [header_data]
    table_styles_list = [
        # Header row
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "LEFT"),
        ("ALIGN", (3, 0), (-1, 0), "RIGHT"),
        # Global
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]

    row_idx = 1
    for line in lines:
        if line.is_additional:
            # Sub-row for additional article: indent with "+"
            artikel_text = f"<font color='#475569'>+ {escape(line.artikelname)}</font>"
            if line.hersteller:
                artikel_text += f"<br/><font size='6' color='#64748B'>{escape(line.hersteller)}</font>"
            artikel_text += f"<br/><font size='6' color='#94A3B8'>{escape(line.artikel_id)}</font>"

            table_data.append([
                "",
                Paragraph("<font color='#64748B'>Zusatzartikel</font>", styles["body_small"]),
                Paragraph(artikel_text, styles["body"]),
                f"{_fmt_qty(line.quantity)} {line.unit}",
                _fmt_money(line.price_net),
                _fmt_money(line.total_net),
            ])
        else:
            desc_text = escape(line.description or "")
            if line.supplier_open:
                artikel_text = "<font color='#CA8A04'><b>Lieferant offen</b></font>"
            else:
                alt_suffix = " *" if line.is_alternative else ""
                artikel_text = f"{escape(line.artikelname)}{alt_suffix}"
                if line.hersteller:
                    artikel_text += f"<br/><font size='6' color='#64748B'>{escape(line.hersteller)}</font>"
                artikel_text += f"<br/><font size='6' color='#94A3B8'>{escape(line.artikel_id)}</font>"

            table_data.append([
                line.ordnungszahl,
                Paragraph(desc_text, styles["body"]),
                Paragraph(artikel_text, styles["body"]),
                f"{_fmt_qty(line.quantity)} {line.unit}",
                _fmt_money(line.price_net),
                _fmt_money(line.total_net),
            ])
        if (row_idx - 1) % 2 == 0:
            table_styles_list.append(("BACKGROUND", (0, row_idx), (-1, row_idx), ROW_ALT))
        table_styles_list.append(("ALIGN", (3, row_idx), (-1, row_idx), "RIGHT"))
        table_styles_list.append(("LINEBELOW", (0, row_idx), (-1, row_idx), 0.25, GRAY_200))
        row_idx += 1

    table = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle(table_styles_list))
    story.append(table)
    story.append(Spacer(1, 10 * mm))

    # ── Totals section ───
    mwst = round(metadata.total_net * 0.19, 2)
    brutto = round(metadata.total_net + mwst, 2)

    totals_data = [
        [
            Paragraph("Netto", styles["total_label"]),
            Paragraph(f"{_fmt_money(metadata.total_net)} EUR", styles["total_value"]),
        ],
        [
            Paragraph("MwSt. 19 %", styles["total_label"]),
            Paragraph(f"{_fmt_money(mwst)} EUR", styles["total_value"]),
        ],
        [
            Paragraph("<b>Gesamtbetrag brutto</b>", styles["total_brutto_label"]),
            Paragraph(f"<b>{_fmt_money(brutto)} EUR</b>", styles["total_brutto_value"]),
        ],
    ]
    totals_table = Table(totals_data, colWidths=[CONTENT_W - 60 * mm, 60 * mm], hAlign="RIGHT")
    totals_table.setStyle(
        TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEABOVE", (0, 2), (-1, 2), 1, DARK),
        ])
    )
    story.append(totals_table)
    story.append(Spacer(1, 8 * mm))

    # ── Alternative footnote ───
    has_alternatives = any(line.is_alternative for line in lines)
    if has_alternatives:
        story.append(
            Paragraph(
                "<font size='7' color='#64748B'>* Alternativ zur bauseitigen Prüfung</font>",
                styles["body"],
            )
        )
        story.append(Spacer(1, 6 * mm))
    else:
        story.append(Spacer(1, 4 * mm))

    # ── Closing text ───
    story.append(
        Paragraph(
            "Wir freuen uns auf Ihre Rückmeldung und stehen für Rückfragen "
            "jederzeit gerne zur Verfügung.<br/><br/>"
            "Mit freundlichen Grüßen<br/>"
            f"{COMPANY_NAME}",
            styles["body"],
        )
    )

    doc.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()


def now_metadata(
    customer_name: str | None,
    project_name: str | None,
    total_net: float,
    customer_address: str | None = None,
) -> ExportOfferMetadata:
    return ExportOfferMetadata(
        customer_name=customer_name,
        customer_address=customer_address,
        project_name=project_name,
        created_at=datetime.now(),
        total_net=round(total_net, 2),
    )

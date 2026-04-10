"""
Build a formal Vehicle Rental Agreement PDF.

Covers all three parties: Renter (client), Vehicle Owner (host), and Ardena platform.
Includes vehicle details, rental terms, payment info, car rules, standard T&Cs,
and timestamped electronic signatures for all parties.
"""
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------- colours ----------
NAVY = colors.HexColor("#1A2E4A")
GOLD = colors.HexColor("#C9A84C")
LIGHT_GRAY = colors.HexColor("#F5F5F5")
MID_GRAY = colors.HexColor("#CCCCCC")
DARK_GRAY = colors.HexColor("#555555")

COMMISSION_RATE = 0.15


# ---------- helpers ----------

def _fmt_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(tz=None)
    return dt.strftime("%d %B %Y at %H:%M")


def _fmt_date(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(tz=None)
    return dt.strftime("%d %B %Y")


def _safe(val, fallback="—") -> str:
    if val is None:
        return fallback
    s = str(val).strip()
    return s if s else fallback


def _detect_payment_method(paid_payment) -> str:
    if not paid_payment:
        return "—"
    if getattr(paid_payment, "mpesa_receipt_number", None):
        return "M-Pesa (Mobile Money)"
    if getattr(paid_payment, "pesapal_order_tracking_id", None):
        method = getattr(paid_payment, "pesapal_payment_method", None) or "Card"
        account = getattr(paid_payment, "pesapal_payment_account", None)
        return f"{method}" + (f" ending {account}" if account else "")
    if getattr(paid_payment, "stellar_tx_hash", None):
        return "Stellar USDC (Ardena Pay)"
    return "Electronic Payment"


def _payment_reference(paid_payment) -> str:
    if not paid_payment:
        return "—"
    ref = (
        getattr(paid_payment, "mpesa_receipt_number", None)
        or getattr(paid_payment, "pesapal_confirmation_code", None)
        or getattr(paid_payment, "stellar_tx_hash", None)
        or getattr(paid_payment, "pesapal_order_tracking_id", None)
    )
    return _safe(ref)


def _payment_date(paid_payment) -> Optional[datetime]:
    if not paid_payment:
        return None
    return getattr(paid_payment, "updated_at", None) or getattr(paid_payment, "created_at", None)


# ---------- style factory ----------

def _styles():
    base = getSampleStyleSheet()

    def ps(name, parent="Normal", **kw):
        return ParagraphStyle(name, parent=base[parent], **kw)

    return {
        "doc_title": ps("DocTitle", "Normal",
                        fontSize=20, fontName="Helvetica-Bold",
                        textColor=NAVY, alignment=TA_CENTER, spaceAfter=2),
        "doc_sub": ps("DocSub", "Normal",
                      fontSize=9, textColor=DARK_GRAY,
                      alignment=TA_CENTER, spaceAfter=2),
        "section": ps("Section", "Normal",
                      fontSize=11, fontName="Helvetica-Bold",
                      textColor=NAVY, spaceBefore=14, spaceAfter=4),
        "field_label": ps("FieldLabel", "Normal",
                          fontSize=8, fontName="Helvetica-Bold",
                          textColor=DARK_GRAY),
        "field_value": ps("FieldValue", "Normal",
                          fontSize=9, fontName="Helvetica"),
        "body": ps("Body", "Normal",
                   fontSize=8, leading=12, alignment=TA_JUSTIFY,
                   textColor=DARK_GRAY),
        "sig_name": ps("SigName", "Normal",
                       fontSize=10, fontName="Helvetica-Bold",
                       textColor=NAVY, alignment=TA_CENTER),
        "sig_label": ps("SigLabel", "Normal",
                        fontSize=7, textColor=DARK_GRAY, alignment=TA_CENTER),
        "footer": ps("Footer", "Normal",
                     fontSize=7, textColor=MID_GRAY, alignment=TA_CENTER),
        "bullet": ps("Bullet", "Normal",
                     fontSize=8, leading=12, leftIndent=10,
                     textColor=DARK_GRAY, alignment=TA_JUSTIFY),
        "warning": ps("Warning", "Normal",
                      fontSize=8, fontName="Helvetica-Bold",
                      textColor=colors.HexColor("#8B0000")),
    }


def _info_table(rows: list, col_w=(55, None)) -> Table:
    """Two-column label/value table."""
    page_w = A4[0] - 30 * mm
    right = page_w - col_w[0] * mm if col_w[1] is None else col_w[1]
    t = Table(rows, colWidths=[col_w[0] * mm, right])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (0, -1), DARK_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _section_rule():
    return HRFlowable(width="100%", thickness=0.5, color=MID_GRAY, spaceAfter=6)


# ---------- main builder ----------

def build_agreement_pdf(booking, paid_payment=None) -> bytes:
    """
    Build a formal Vehicle Rental Agreement PDF.

    Args:
        booking: ORM Booking object with .car, .car.host, .client loaded.
        paid_payment: Completed Payment ORM object (for method, reference, date).

    Returns:
        Raw PDF bytes.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=20 * mm,
        title="Vehicle Rental Agreement",
        author="Ardena Group",
    )

    st = _styles()
    now = datetime.now(timezone.utc)

    car = getattr(booking, "car", None)
    host = getattr(booking, "host", None) or (car.host if car else None)
    client = getattr(booking, "client", None)

    booking_ref = _safe(getattr(booking, "booking_id", None))
    pay_date = _payment_date(paid_payment)
    pay_method = _detect_payment_method(paid_payment)
    pay_ref = _payment_reference(paid_payment)

    total_price = float(getattr(booking, "total_price", 0) or 0)
    commission = round(total_price * COMMISSION_RATE, 2)
    host_receives = round(total_price - commission, 2)

    story = []

    # ── HEADER ──────────────────────────────────────────────────────────────
    story.append(Paragraph("ARDENA GROUP", st["doc_title"]))
    story.append(Paragraph("VEHICLE RENTAL AGREEMENT", ParagraphStyle(
        "AgreementSub", parent=st["doc_title"], fontSize=13, spaceAfter=4)))
    story.append(Paragraph(
        f"Agreement Reference: <b>{booking_ref}</b>  &nbsp;|&nbsp;  "
        f"Date Issued: <b>{_fmt_date(now)}</b>",
        st["doc_sub"]))
    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=6))

    story.append(Paragraph(
        'This Vehicle Rental Agreement ("Agreement") is entered into between the parties '
        "identified below and facilitated by Ardena Group as the platform operator. "
        "By completing payment the Renter accepts all terms herein. "
        "Electronic signatures constitute legally binding acceptance.",
        st["body"]))
    story.append(Spacer(1, 4 * mm))

    # ── SECTION 1: PARTIES ──────────────────────────────────────────────────
    story.append(Paragraph("1. PARTIES TO THIS AGREEMENT", st["section"]))
    story.append(_section_rule())

    # Platform
    story.append(Paragraph("1.1  Platform Operator", st["field_label"]))
    story.append(Spacer(1, 1 * mm))
    story.append(_info_table([
        ["Company", "Ardena Group"],
        ["Role", "Marketplace Platform Operator"],
        ["Email", "hello@ardena.xyz"],
        ["Website", "www.ardena.xyz"],
        ["Liability", "Ardena acts as facilitator only and is not a party to the rental contract between Host and Renter."],
    ]))
    story.append(Spacer(1, 4 * mm))

    # Host
    story.append(Paragraph("1.2  Vehicle Owner (Host)", st["field_label"]))
    story.append(Spacer(1, 1 * mm))
    host_name = _safe(getattr(host, "full_name", None)) if host else "—"
    host_email = _safe(getattr(host, "email", None)) if host else "—"
    host_phone = _safe(getattr(host, "mobile_number", None)) if host else "—"
    host_city = _safe(getattr(host, "city", None)) if host else "—"
    host_id_num = _safe(getattr(host, "id_number", None)) if host else "—"
    story.append(_info_table([
        ["Full Name", host_name],
        ["Email", host_email],
        ["Phone", host_phone],
        ["City", host_city],
        ["ID / Passport", host_id_num],
    ]))
    story.append(Spacer(1, 4 * mm))

    # Client
    story.append(Paragraph("1.3  Renter (Client)", st["field_label"]))
    story.append(Spacer(1, 1 * mm))
    client_name = _safe(getattr(client, "full_name", None)) if client else "—"
    client_email = _safe(getattr(client, "email", None)) if client else "—"
    client_phone = _safe(getattr(client, "mobile_number", None)) if client else "—"
    client_id_num = _safe(getattr(client, "id_number", None)) if client else "—"
    client_dob = getattr(client, "date_of_birth", None) if client else None
    client_dob_str = client_dob.strftime("%d %B %Y") if client_dob else "—"
    story.append(_info_table([
        ["Full Name", client_name],
        ["Email", client_email],
        ["Phone", client_phone],
        ["ID / Passport", client_id_num],
        ["Date of Birth", client_dob_str],
    ]))
    story.append(Spacer(1, 5 * mm))

    # ── SECTION 2: VEHICLE ──────────────────────────────────────────────────
    story.append(Paragraph("2. VEHICLE DETAILS", st["section"]))
    story.append(_section_rule())

    car_name = _safe(getattr(car, "name", None)) if car else "—"
    car_model = _safe(getattr(car, "model", None)) if car else "—"
    car_year = _safe(getattr(car, "year", None)) if car else "—"
    car_body = _safe(getattr(car, "body_type", None)) if car else "—"
    car_color = _safe(getattr(car, "color", None)) if car else "—"
    car_transmission = _safe(getattr(car, "transmission", None)) if car else "—"
    car_fuel = _safe(getattr(car, "fuel_type", None)) if car else "—"
    car_seats = _safe(getattr(car, "seats", None)) if car else "—"
    car_mileage = getattr(car, "mileage", None) if car else None
    car_mileage_str = f"{car_mileage:,} km" if car_mileage else "—"

    story.append(_info_table([
        ["Make / Model", f"{car_name} {car_model}".strip() or "—"],
        ["Year", car_year],
        ["Body Type", car_body],
        ["Colour", car_color],
        ["Transmission", car_transmission],
        ["Fuel Type", car_fuel],
        ["Seats", car_seats],
        ["Odometer at Listing", car_mileage_str],
    ]))
    story.append(Spacer(1, 5 * mm))

    # ── SECTION 3: RENTAL TERMS ─────────────────────────────────────────────
    story.append(Paragraph("3. RENTAL TERMS", st["section"]))
    story.append(_section_rule())

    rental_days = int(getattr(booking, "rental_days", 0) or 0)
    pickup_time = _safe(getattr(booking, "pickup_time", None))
    return_time = _safe(getattr(booking, "return_time", None))
    pickup_loc = _safe(getattr(booking, "pickup_location", None))
    return_loc = _safe(getattr(booking, "return_location", None))
    drive_type_raw = _safe(getattr(booking, "drive_type", "self"))
    drive_type_display = "With Chauffeur" if drive_type_raw == "withDriver" else "Self-Drive"
    checkin_raw = _safe(getattr(booking, "check_in_preference", "self"))
    checkin_display = "Host-Assisted Check-In" if checkin_raw == "assisted" else "Self Check-In"
    special_req = _safe(getattr(booking, "special_requirements", None), fallback="None")

    story.append(_info_table([
        ["Pickup Date", _fmt_date(getattr(booking, "start_date", None))],
        ["Pickup Time", pickup_time],
        ["Pickup Location", pickup_loc],
        ["Return Date", _fmt_date(getattr(booking, "end_date", None))],
        ["Return Time", return_time],
        ["Return Location", return_loc],
        ["Rental Duration", f"{rental_days} day{'s' if rental_days != 1 else ''}"],
        ["Drive Type", drive_type_display],
        ["Check-In", checkin_display],
        ["Special Requirements", special_req],
    ]))
    story.append(Spacer(1, 5 * mm))

    # ── SECTION 4: FINANCIAL TERMS ──────────────────────────────────────────
    story.append(Paragraph("4. FINANCIAL TERMS", st["section"]))
    story.append(_section_rule())

    daily_rate = float(getattr(booking, "daily_rate", 0) or 0)
    base_price = float(getattr(booking, "base_price", 0) or 0)
    damage_fee = float(getattr(booking, "damage_waiver_fee", 0) or 0)
    damage_enabled = bool(getattr(booking, "damage_waiver_enabled", False))

    page_w = A4[0] - 30 * mm
    fin_data = [
        ["Description", "Amount (KES)"],
        [f"Daily Rate × {rental_days} day{'s' if rental_days != 1 else ''}  (KES {daily_rate:,.2f}/day)",
         f"{base_price:,.2f}"],
        ["Damage Protection Waiver" if damage_enabled else "Damage Protection Waiver (Declined)",
         f"{damage_fee:,.2f}" if damage_enabled else "—"],
        ["TOTAL CHARGED", f"{total_price:,.2f}"],
    ]
    t_fin = Table(fin_data, colWidths=[page_w * 0.68, page_w * 0.32])
    t_fin.setStyle(TableStyle([
        # Header row
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        # Body rows
        ("FONTNAME", (0, 1), (-1, -2), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, LIGHT_GRAY]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        # Total row
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), LIGHT_GRAY),
        ("LINEABOVE", (0, -1), (-1, -1), 1, NAVY),
        ("LINEBELOW", (0, -1), (-1, -1), 1, NAVY),
        # Grid
        ("GRID", (0, 0), (-1, -1), 0.3, MID_GRAY),
    ]))
    story.append(t_fin)
    story.append(Spacer(1, 4 * mm))

    story.append(_info_table([
        ["Payment Method", pay_method],
        ["Payment Reference", pay_ref],
        ["Payment Date", _fmt_dt(pay_date) if pay_date else "—"],
        ["Platform Commission (15%)", f"KES {commission:,.2f}"],
        ["Host Payout", f"KES {host_receives:,.2f}"],
    ]))
    story.append(Spacer(1, 5 * mm))

    # ── SECTION 5: VEHICLE RULES ─────────────────────────────────────────────
    story.append(Paragraph("5. VEHICLE RULES & RESTRICTIONS", st["section"]))
    story.append(_section_rule())

    car_rules = getattr(car, "rules", None) if car else None
    if car_rules and car_rules.strip():
        # Render each line as a bullet
        for line in car_rules.strip().splitlines():
            line = line.strip("•- \t")
            if line:
                story.append(Paragraph(f"• {line}", st["bullet"]))
    else:
        story.append(Paragraph(
            "No specific rules have been stated by the vehicle owner beyond the standard terms below.",
            st["body"]))
    story.append(Spacer(1, 5 * mm))

    # ── SECTION 6: STANDARD TERMS & CONDITIONS ───────────────────────────────
    story.append(Paragraph("6. STANDARD TERMS & CONDITIONS", st["section"]))
    story.append(_section_rule())

    terms = [
        ("6.1 Eligibility",
         "The Renter must hold a valid driver's licence appropriate for the vehicle category "
         "and must be at least the minimum age specified by the Vehicle Owner. "
         "The Renter must present valid identification upon vehicle collection."),

        ("6.2 Condition of Vehicle",
         "The Renter accepts the vehicle in its current condition at the time of pickup. "
         "Any pre-existing damage must be noted and agreed upon by both parties before departure. "
         "Undisclosed damage discovered at return shall be the Renter's responsibility."),

        ("6.3 Fuel Policy",
         "The vehicle must be returned with the same fuel level as at the time of collection "
         "unless otherwise agreed in writing. Failure to do so may result in a refuelling charge "
         "at the prevailing market rate plus a service fee, billed through the platform."),

        ("6.4 Damage & Liability",
         "The Renter is fully liable for any damage, loss, or theft of the vehicle during the "
         "rental period, including damage caused by third parties, weather events, or road hazards. "
         "If the Damage Protection Waiver was elected, the Renter's excess liability is limited "
         "to the terms disclosed at the time of booking. The waiver does not cover wilful damage, "
         "driving under the influence, or breach of these terms."),

        ("6.5 Traffic Violations & Fines",
         "The Renter is solely responsible for all traffic fines, parking penalties, road tolls, "
         "and any other statutory charges incurred during the rental period. "
         "These may be passed on to the Renter by the Vehicle Owner via Ardena after the rental ends."),

        ("6.6 Late Return",
         "The vehicle must be returned by the agreed return date and time. Late returns will be "
         "charged at the daily rate pro-rated to the number of additional hours/days, subject to "
         "the Vehicle Owner's agreement. Failure to return the vehicle without notice may be treated "
         "as unauthorised use and reported to the relevant authorities."),

        ("6.7 Prohibited Use",
         "The vehicle may not be: used for hire or reward (e.g. taxi, courier, delivery services); "
         "driven by any person not named in this agreement; taken outside the agreed geographic area; "
         "used in any illegal activity; driven off-road unless explicitly permitted; "
         "or modified in any way without the owner's written consent."),

        ("6.8 Cancellation Policy",
         "Cancellations made more than 48 hours before the pickup date qualify for a full refund. "
         "Cancellations within 48 hours may incur a fee at the Vehicle Owner's discretion. "
         "No-shows without prior notice are non-refundable. "
         "Ardena's platform fee is non-refundable once a booking is confirmed."),

        ("6.9 Insurance",
         "Comprehensive insurance for the rental period is the responsibility of the Vehicle Owner. "
         "The Renter is strongly advised to confirm insurance coverage before pickup. "
         "Ardena does not provide or guarantee insurance coverage for any party."),

        ("6.10 Dispute Resolution",
         "Any dispute arising from this Agreement shall first be submitted to Ardena's "
         "dispute resolution process via hello@ardena.xyz. "
         "If unresolved within 14 days, disputes shall be settled under the applicable laws "
         "of the jurisdiction in which the rental took place."),

        ("6.11 Platform Role",
         "Ardena Group acts solely as a technology marketplace connecting Vehicle Owners and Renters. "
         "Ardena is not the owner, lessor, insurer, or guarantor of any vehicle. "
         "Ardena's liability to any party is limited to the platform commission received for that booking."),

        ("6.12 Governing Law",
         "This Agreement is governed by the laws of the Republic of Kenya. "
         "By accepting these terms both parties submit to the exclusive jurisdiction of the Kenyan courts."),
    ]

    for heading, body in terms:
        story.append(Paragraph(f"<b>{heading}</b>", st["body"]))
        story.append(Paragraph(body, st["body"]))
        story.append(Spacer(1, 2 * mm))

    story.append(Spacer(1, 4 * mm))

    # ── SECTION 7: ELECTRONIC SIGNATURES ─────────────────────────────────────
    story.append(Paragraph("7. ELECTRONIC SIGNATURES", st["section"]))
    story.append(_section_rule())

    story.append(Paragraph(
        "By completing the payment process on the Ardena platform, the Renter has electronically "
        "agreed to all terms of this Agreement. The Vehicle Owner accepted these terms when listing "
        "the vehicle and confirming the booking on the platform. Ardena Group countersigns as platform "
        "operator. These electronic signatures carry full legal effect under applicable electronic "
        "commerce laws.",
        st["body"]))
    story.append(Spacer(1, 5 * mm))

    # Signature timestamps
    client_sig_date = _fmt_dt(pay_date or now)
    booking_confirmed = getattr(booking, "status_updated_at", None)
    host_sig_date = _fmt_dt(booking_confirmed or pay_date or now)
    platform_sig_date = _fmt_dt(now)

    sig_col_w = (A4[0] - 30 * mm) / 3

    def _sig_cell(name, role, date_str, party):
        lines = [
            Paragraph(f"<b>{name}</b>", ParagraphStyle(
                "SN", parent=st["sig_name"], fontSize=11)),
            Spacer(1, 2),
            Paragraph(party, ParagraphStyle(
                "SP", parent=st["sig_label"], fontName="Helvetica-Bold",
                textColor=NAVY, fontSize=8)),
            Spacer(1, 4),
            HRFlowable(width="80%", thickness=1, color=NAVY),
            Spacer(1, 3),
            Paragraph(role, st["sig_label"]),
            Spacer(1, 2),
            Paragraph(f"Date: {date_str}", ParagraphStyle(
                "SD", parent=st["sig_label"], fontSize=7)),
        ]
        return lines

    client_cell = _sig_cell(client_name, "Electronically signed by completing payment",
                            client_sig_date, "RENTER")
    host_cell = _sig_cell(host_name, "Electronically confirmed upon listing & booking acceptance",
                          host_sig_date, "VEHICLE OWNER")
    platform_cell = _sig_cell("Ardena Group", "Countersigned as Platform Operator",
                              platform_sig_date, "PLATFORM")

    # Wrap each cell in a Table for padding
    def _wrap_cell(cell_content):
        inner = Table([[item] for item in cell_content],
                      colWidths=[sig_col_w - 6 * mm])
        inner.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return inner

    sig_table = Table(
        [[_wrap_cell(client_cell), _wrap_cell(host_cell), _wrap_cell(platform_cell)]],
        colWidths=[sig_col_w, sig_col_w, sig_col_w],
    )
    sig_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY),
        ("BOX", (0, 0), (-1, -1), 0.5, MID_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, MID_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(sig_table)
    story.append(Spacer(1, 6 * mm))

    # ── FOOTER NOTE ──────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=MID_GRAY, spaceAfter=4))
    story.append(Paragraph(
        f"This document was automatically generated by the Ardena platform on "
        f"{_fmt_dt(now)} and constitutes a legally binding agreement. "
        f"Reference: {booking_ref}  ·  hello@ardena.xyz  ·  www.ardena.xyz",
        st["footer"]))

    doc.build(story)
    return buf.getvalue()

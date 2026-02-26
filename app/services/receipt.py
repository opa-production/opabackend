"""
Generate booking receipt as PDF. Used by both host and client receipt endpoints.
"""
from datetime import datetime, timezone
from io import BytesIO
from typing import TYPE_CHECKING, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

COMMISSION_RATE = 0.15  # 15%


def _fmt_date(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(tz=None)
    return dt.strftime("%d %b %Y %H:%M")


def _fmt_date_only(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(tz=None)
    return dt.strftime("%d %b %Y")


def build_receipt_pdf(booking, paid_payment=None) -> bytes:
    """
    Build a PDF receipt for the given booking.

    booking: ORM object with .car, .host, .client loaded; optional .payments.
    paid_payment: Optional Payment object with status completed (for M-Pesa receipt, paid date).
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReceiptTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=6,
    )
    heading_style = ParagraphStyle(
        "ReceiptHeading",
        parent=styles["Heading2"],
        fontSize=11,
        spaceAfter=4,
        spaceBefore=10,
    )
    normal_style = styles["Normal"]

    story = []

    # Title
    story.append(Paragraph("Booking Receipt", title_style))
    story.append(Paragraph("Ardena", normal_style))
    story.append(Spacer(1, 6))
    receipt_date = datetime.now(timezone.utc)
    story.append(Paragraph(f"Receipt date: {_fmt_date(receipt_date)}", normal_style))
    story.append(Spacer(1, 12))

    # Booking info
    story.append(Paragraph("Booking details", heading_style))
    booking_id = getattr(booking, "booking_id", None) or f"#{getattr(booking, 'id', '')}"
    status = getattr(booking, "status", None)
    status_str = status.value if hasattr(status, "value") else str(status)
    data_booking = [
        ["Booking ID", booking_id],
        ["Status", status_str],
        ["Start date", _fmt_date_only(getattr(booking, "start_date", None))],
        ["End date", _fmt_date_only(getattr(booking, "end_date", None))],
        ["Pickup", f"{getattr(booking, 'pickup_time', '') or '—'} at {getattr(booking, 'pickup_location', '') or '—'}"],
        ["Return", f"{getattr(booking, 'return_time', '') or '—'} at {getattr(booking, 'return_location', '') or '—'}"],
    ]
    t_booking = Table(data_booking, colWidths=[90, None])
    t_booking.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    story.append(t_booking)
    story.append(Spacer(1, 10))

    # Car
    car = getattr(booking, "car", None)
    if car:
        story.append(Paragraph("Vehicle", heading_style))
        car_name = getattr(car, "name", "") or ""
        car_model = getattr(car, "model", "") or ""
        car_year = getattr(car, "year", "") or ""
        data_car = [
            ["Car", f"{car_name} {car_model} {car_year}".strip() or "—"],
        ]
        t_car = Table(data_car, colWidths=[90, None])
        t_car.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
        story.append(t_car)
        story.append(Spacer(1, 10))

    # Host & Client
    host = getattr(booking, "host", None) or (car.host if car else None)
    client = getattr(booking, "client", None)
    story.append(Paragraph("Parties", heading_style))
    host_name = getattr(host, "full_name", None) if host else "—"
    client_name = getattr(client, "full_name", None) if client else "—"
    client_email = getattr(client, "email", None) if client else "—"
    data_parties = [
        ["Host", host_name or "—"],
        ["Client", f"{client_name or '—'}" + (f" ({client_email})" if client_email else "")],
    ]
    t_parties = Table(data_parties, colWidths=[90, None])
    t_parties.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    story.append(t_parties)
    story.append(Spacer(1, 10))

    # Pricing
    story.append(Paragraph("Pricing", heading_style))
    rental_days = getattr(booking, "rental_days", 0) or 0
    daily_rate = float(getattr(booking, "daily_rate", 0) or 0)
    base_price = float(getattr(booking, "base_price", 0) or 0)
    damage_waiver_fee = float(getattr(booking, "damage_waiver_fee", 0) or 0)
    total_price = float(getattr(booking, "total_price", 0) or 0)
    data_pricing = [
        ["Rental", f"{rental_days} days × KES {daily_rate:,.2f}", f"KES {base_price:,.2f}"],
        ["Damage waiver", "", f"KES {damage_waiver_fee:,.2f}"],
        ["Total", "", f"KES {total_price:,.2f}"],
    ]
    t_pricing = Table(data_pricing, colWidths=[80, None, 70])
    t_pricing.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
            ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.black),
        ])
    )
    story.append(t_pricing)
    story.append(Spacer(1, 10))

    # Payment info
    story.append(Paragraph("Payment", heading_style))
    mpesa_receipt = None
    paid_at = None
    if paid_payment:
        mpesa_receipt = getattr(paid_payment, "mpesa_receipt_number", None)
        paid_at = getattr(paid_payment, "updated_at", None) or getattr(paid_payment, "created_at", None)
    if not paid_payment and getattr(booking, "payments", None):
        for p in booking.payments:
            if getattr(p, "status", None) and getattr(p.status, "value", None) == "completed":
                mpesa_receipt = getattr(p, "mpesa_receipt_number", None) or mpesa_receipt
                pt = getattr(p, "updated_at", None) or getattr(p, "created_at", None)
                if pt and (paid_at is None or pt > paid_at):
                    paid_at = pt
                if mpesa_receipt:
                    break
    payment_status = "Paid" if (paid_payment or (getattr(booking, "payments", None) and any(
        getattr(p, "status", None) and getattr(p.status, "value", None) == "completed" for p in booking.payments
    ))) else "Pending"
    data_payment = [
        ["Payment status", payment_status],
        ["M-Pesa receipt", mpesa_receipt or "—"],
        ["Paid at", _fmt_date(paid_at) if paid_at else "—"],
    ]
    t_payment = Table(data_payment, colWidths=[90, None])
    t_payment.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    story.append(t_payment)
    story.append(Spacer(1, 10))

    # Commission & host amount (same receipt for both parties)
    commission_amount = round(total_price * COMMISSION_RATE, 2)
    host_receives = round(total_price - commission_amount, 2)
    story.append(Paragraph("Host payout", heading_style))
    data_commission = [
        ["Platform commission (15%)", f"KES {commission_amount:,.2f}"],
        ["Host receives", f"KES {host_receives:,.2f}"],
    ]
    t_commission = Table(data_commission, colWidths=[140, 70])
    t_commission.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ])
    )
    story.append(t_commission)

    story.append(Spacer(1, 20))
    story.append(Paragraph("Thank you for using Ardena.", normal_style))

    doc.build(story)
    return buf.getvalue()

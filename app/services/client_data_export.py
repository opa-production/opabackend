"""
Generate a GDPR-style data export PDF for a client.
Includes profile, KYC, driving licence, payment methods, and booking history.
"""
from datetime import datetime, timezone
from io import BytesIO
from typing import Iterable, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models import (
    Booking,
    Client,
    ClientKyc,
    DrivingLicense,
    HostRating,
    ClientRating,
    PaymentMethod,
)


def _fmt_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _fmt_date(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    if hasattr(dt, "tzinfo") and dt.tzinfo:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d")


def build_client_data_pdf(
    client: Client,
    bookings: Iterable[Booking],
    driving_license: Optional[DrivingLicense] = None,
    latest_kyc: Optional[ClientKyc] = None,
    payment_methods: Optional[Iterable[PaymentMethod]] = None,
    ratings_from_hosts: Optional[Iterable[ClientRating]] = None,
    ratings_given_to_hosts: Optional[Iterable[HostRating]] = None,
) -> bytes:
    """
    Build a PDF containing a snapshot of all key data we store for a client.
    Returns raw PDF bytes suitable for download or email attachment.
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
        "ClientDataTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=8,
    )
    heading_style = ParagraphStyle(
        "ClientDataHeading",
        parent=styles["Heading2"],
        fontSize=11,
        spaceAfter=4,
        spaceBefore=10,
    )
    normal_style = styles["Normal"]

    story = []

    # Title and metadata
    story.append(Paragraph("Your Ardena Data Export", title_style))
    story.append(Paragraph("Ardena Group", normal_style))
    generated_at = datetime.now(timezone.utc)
    story.append(Paragraph(f"Generated at: {_fmt_dt(generated_at)}", normal_style))
    story.append(Spacer(1, 10))

    # Account overview
    story.append(Paragraph("Account overview", heading_style))
    overview_rows = [
        ["Client ID", str(client.id)],
        ["Full name", client.full_name or "—"],
        ["Email", client.email or "—"],
        ["Account created at", _fmt_dt(client.created_at)],
        ["Last updated at", _fmt_dt(getattr(client, "updated_at", None))],
        ["Account active", "Yes" if client.is_active else "No"],
        ["Terms accepted at", _fmt_dt(getattr(client, "terms_accepted_at", None))],
    ]
    t_overview = Table(overview_rows, colWidths=[120, None])
    t_overview.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(t_overview)

    # Profile details
    story.append(Spacer(1, 8))
    story.append(Paragraph("Profile details", heading_style))
    profile_rows = [
        ["Bio", client.bio or "—"],
        ["Fun fact", client.fun_fact or "—"],
        ["Mobile number", client.mobile_number or "—"],
        ["ID number", client.id_number or "—"],
        ["Date of birth", _fmt_date(getattr(client, "date_of_birth", None))],
        ["Gender", client.gender or "—"],
        ["Avatar URL", client.avatar_url or "—"],
        ["ID document URL", client.id_document_url or "—"],
        ["License document URL", client.license_document_url or "—"],
    ]
    t_profile = Table(profile_rows, colWidths=[120, None])
    t_profile.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(t_profile)

    # KYC
    story.append(Spacer(1, 8))
    story.append(Paragraph("KYC verification (latest)", heading_style))
    if latest_kyc:
        kyc_rows = [
            ["Session ID", latest_kyc.dojah_reference_id],
            ["Status", latest_kyc.status],
            ["Document type", latest_kyc.document_type or "—"],
            ["Decision reason", latest_kyc.decision_reason or "—"],
            ["Verified at", _fmt_dt(getattr(latest_kyc, "verified_at", None))],
            ["Record created at", _fmt_dt(latest_kyc.created_at)],
        ]
    else:
        kyc_rows = [["Status", "No KYC records found"]]
    t_kyc = Table(kyc_rows, colWidths=[120, None])
    t_kyc.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(t_kyc)

    # Driving licence
    story.append(Spacer(1, 8))
    story.append(Paragraph("Driving licence", heading_style))
    if driving_license:
        dl_rows = [
            ["License number", driving_license.license_number],
            ["Category", driving_license.category],
            ["Issue date", _fmt_date(driving_license.issue_date)],
            ["Expiry date", _fmt_date(driving_license.expiry_date)],
            ["Verified", "Yes" if driving_license.is_verified else "No"],
            ["Verification notes", driving_license.verification_notes or "—"],
        ]
    else:
        dl_rows = [["Status", "No driving licence on file"]]
    t_dl = Table(dl_rows, colWidths=[120, None])
    t_dl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(t_dl)

    # Payment methods
    story.append(Spacer(1, 8))
    story.append(Paragraph("Payment methods", heading_style))
    pm_list = list(payment_methods or [])
    if pm_list:
        pm_rows = [["Name", "Type", "Masked details", "Default"]]
        for pm in pm_list:
            if pm.method_type.value == "mpesa":
                masked = pm.mpesa_number or "—"
            else:
                last_four = pm.card_last_four or "****"
                masked = f"{(pm.card_type or '').upper()} **** **** **** {last_four}"
            pm_rows.append(
                [
                    pm.name,
                    pm.method_type.value,
                    masked,
                    "Yes" if pm.is_default else "No",
                ]
            )
        t_pm = Table(pm_rows, colWidths=[80, 60, None, 40])
        t_pm.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("ALIGN", (3, 1), (3, -1), "CENTER"),
                ]
            )
        )
    else:
        t_pm = Table([["Status", "No payment methods on file"]], colWidths=[120, None])
        t_pm.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                ]
            )
        )
    story.append(t_pm)

    # Booking history
    story.append(Spacer(1, 8))
    story.append(Paragraph("Booking history", heading_style))
    bookings_list = list(bookings)
    if bookings_list:
        booking_rows = [
            ["Booking ID", "Car", "Start", "End", "Status", "Total (KES)"]
        ]
        for b in bookings_list:
            car = getattr(b, "car", None)
            car_name = ""
            if car:
                car_name = " ".join(
                    x for x in [car.name, car.model, str(car.year or "")] if x
                ).strip()
            start = _fmt_dt(b.start_date)
            end = _fmt_dt(b.end_date)
            status = b.status.value if hasattr(b.status, "value") else str(b.status)
            total = f"{float(b.total_price or 0):,.2f}"
            booking_rows.append(
                [
                    b.booking_id,
                    car_name or "—",
                    start,
                    end,
                    status,
                    total,
                ]
            )
        t_bookings = Table(booking_rows, colWidths=[70, 110, 80, 80, 60, 60])
        t_bookings.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("ALIGN", (5, 1), (5, -1), "RIGHT"),
                ]
            )
        )
    else:
        t_bookings = Table(
            [["Status", "No bookings found for this account"]],
            colWidths=[120, None],
        )
        t_bookings.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                ]
            )
        )
    story.append(t_bookings)

    # Ratings summary (optional)
    story.append(Spacer(1, 8))
    story.append(Paragraph("Ratings", heading_style))
    ratings_from_hosts_list = list(ratings_from_hosts or [])
    ratings_given_to_hosts_list = list(ratings_given_to_hosts or [])

    avg_from_hosts = (
        sum(r.rating for r in ratings_from_hosts_list) / len(ratings_from_hosts_list)
        if ratings_from_hosts_list
        else None
    )
    avg_given = (
        sum(r.rating for r in ratings_given_to_hosts_list)
        / len(ratings_given_to_hosts_list)
        if ratings_given_to_hosts_list
        else None
    )

    ratings_rows = [
        ["Ratings received from hosts", str(len(ratings_from_hosts_list))],
        [
            "Average rating from hosts",
            f"{avg_from_hosts:.2f}" if avg_from_hosts is not None else "—",
        ],
        ["Ratings you have given to hosts", str(len(ratings_given_to_hosts_list))],
        [
            "Average rating you have given",
            f"{avg_given:.2f}" if avg_given is not None else "—",
        ],
    ]
    t_ratings = Table(ratings_rows, colWidths=[180, None])
    t_ratings.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(t_ratings)

    story.append(Spacer(1, 20))
    story.append(
        Paragraph(
            "If you have any questions about this export or want any data corrected or removed, please contact the Ardena Group support team.",
            normal_style,
        )
    )

    doc.build(story)
    return buf.getvalue()


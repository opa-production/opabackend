"""
Host KYC via Veriff: create session (app opens URL), get status, webhook updates result.
"""

import html
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote, urlparse

import requests
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_current_host
from app.core.config import settings
from app.db.session import get_db
from app.models import Host, HostKyc
from app.schemas import (
    HostKycSessionRequest,
    HostKycSessionResponse,
    HostKycStatusResponse,
)

router = APIRouter(tags=["Host KYC"])
logger = logging.getLogger(__name__)

VERIFF_SESSIONS_PATH = "/v1/sessions"

SAFE_KYC_ERROR = "KYC verification is temporarily unavailable. Please try again later or contact support."


def _safe_veriff_error_detail(
    response_message: Optional[str], status_code: Optional[int]
) -> str:
    """Return a user-safe error message. Never expose API keys or raw Veriff messages."""
    if not response_message:
        return SAFE_KYC_ERROR
    msg_lower = response_message.lower()
    if status_code in (401, 403, 404):
        return SAFE_KYC_ERROR
    if "api key" in msg_lower or (
        "integration" in msg_lower and "not active" in msg_lower
    ):
        return SAFE_KYC_ERROR
    import re

    if re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        response_message,
        re.I,
    ):
        return SAFE_KYC_ERROR
    return SAFE_KYC_ERROR


def _allowed_return_to(return_to: str) -> bool:
    """True if return_to is in allowed prefixes (avoids open redirect)."""
    if not return_to or not return_to.strip():
        return False
    prefixes = [
        p.strip()
        for p in (settings.KYC_ALLOWED_RETURN_PREFIXES or "").split(",")
        if p.strip()
    ]
    return any(return_to.strip().lower().startswith(p.lower()) for p in prefixes)


def build_kyc_redirect_response(return_to: Optional[str]) -> HTMLResponse:
    """
    Build HTML redirect response for KYC callback. Shared so the same logic
    can be used at both /api/v1/host/kyc/redirect and /host/kyc/redirect.
    """
    if not return_to or not _allowed_return_to(return_to):
        return HTMLResponse(
            content="<html><body><p>Invalid or missing return link. You can close this page and open the app.</p></body></html>",
            status_code=400,
        )
    escaped = html.escape(return_to.strip())
    content = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={escaped}"></head><body><p>Redirecting to app… <a href="{escaped}">Open app</a></p></body></html>"""
    return HTMLResponse(content=content)


@router.get("/host/kyc/redirect", response_class=HTMLResponse)
async def kyc_redirect(
    return_to: Optional[str] = Query(
        None, description="Deep link to open the app, e.g. ardenahost://kyc/result"
    ),
):
    """
    Veriff redirects here after verification (HTTPS only). We redirect the browser to return_to
    (your app deep link) so the app opens. return_to must match KYC_ALLOWED_RETURN_PREFIXES.
    """
    return build_kyc_redirect_response(return_to)


@router.post("/host/kyc/session", response_model=HostKycSessionResponse)
async def create_kyc_session(
    body: Optional[HostKycSessionRequest] = Body(None),
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a Veriff verification session for the current host.
    Returns verification_url: open this in a browser or webview so the host can complete ID + liveness.
    Pass callback_url (e.g. your app deep link like myapp://kyc/result) so Veriff redirects the user back to the app after verification; then the app can call GET /host/kyc/status to show the result.
    """
    if not settings.VERIFF_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=SAFE_KYC_ERROR,
        )
    base = (settings.VERIFF_BASE_URL or "https://stationapi.veriff.com").rstrip("/")
    url = base + VERIFF_SESSIONS_PATH

    # vendorData so we can map session -> host in webhook (Veriff returns it in webhook payload)
    verification_payload = {"vendorData": str(current_host.id)}
    callback_url = (body and body.callback_url and body.callback_url.strip()) or None
    if callback_url:
        callback_lower = callback_url.lower()
        if callback_lower.startswith("https://"):
            # Veriff allows HTTPS; use as-is
            verification_payload["callback"] = callback_url
        elif settings.VERIFF_CALLBACK_URL:
            # App sent a deep link (e.g. ardenahost://kyc/result); Veriff allows only HTTPS.
            # Extract origin from VERIFF_CALLBACK_URL and append the host redirect path.
            parsed = urlparse(settings.VERIFF_CALLBACK_URL)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            redirect_url = f"{origin}/api/v1/host/kyc/redirect"
            verification_payload["callback"] = (
                f"{redirect_url}?return_to={quote(callback_url, safe='')}"
            )
            parsed = urlparse(settings.VERIFF_CALLBACK_URL)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            redirect_url = f"{origin}/api/v1/host/kyc/redirect"
            verification_payload["callback"] = f"{redirect_url}?return_to={quote(callback_url, safe='')}"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only HTTPS return URLs are allowed by Veriff. Set VERIFF_CALLBACK_URL on the server for app deep links (e.g. ardenahost://kyc/result).",
            )
    payload = {"verification": verification_payload}

    try:
        r = requests.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-AUTH-CLIENT": settings.VERIFF_API_KEY,
            },
            timeout=15,
        )
        if not r.ok:
            try:
                err_body = r.json()
            except Exception:
                err_body = r.text or ""
            logger.warning("Veriff session create %s: %s", r.status_code, err_body)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        err_detail = SAFE_KYC_ERROR
        status_from_upstream = None
        if hasattr(e, "response") and e.response is not None:
            status_from_upstream = getattr(e.response, "status_code", None)
            try:
                err_json = e.response.json()
                raw = err_json.get("message") or err_json.get("detail") or ""
                err_detail = _safe_veriff_error_detail(raw, status_from_upstream)
            except Exception:
                err_detail = _safe_veriff_error_detail(None, status_from_upstream)
        logger.exception("Veriff session create failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=err_detail,
        ) from e

    verification = data.get("verification") or data
    session_id = verification.get("id") or verification.get("sessionId") or ""
    verification_url = verification.get("url") or ""

    if not session_id or not verification_url:
        logger.warning("Veriff response missing id or url: %s", data)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid response from verification service.",
        )

    # Store pending KYC row so webhook can find host_id by session_id
    kyc = HostKyc(
        host_id=current_host.id,
        veriff_session_id=session_id,
        status="pending",
    )
    db.add(kyc)
    await db.commit()

    return HostKycSessionResponse(
        verification_url=verification_url,
        session_id=session_id,
    )


@router.get("/host/kyc/status", response_model=HostKycStatusResponse)
async def get_kyc_status(
    current_host: Host = Depends(get_current_host),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the latest KYC verification status for the current host.
    Use this after the user returns from Veriff to show approved/declined/pending.
    """
    stmt = (
        select(HostKyc)
        .filter(HostKyc.host_id == current_host.id)
        .order_by(HostKyc.created_at.desc())
    )
    result = await db.execute(stmt)
    latest = result.scalars().first()

    if not latest:
        return HostKycStatusResponse(
            user_id=current_host.id,
            veriff_session_id=None,
            status="pending",
            document_type=None,
            decision_reason=None,
            verified_at=None,
        )
    return HostKycStatusResponse(
        user_id=current_host.id,
        veriff_session_id=latest.veriff_session_id,
        status=latest.status,
        document_type=latest.document_type,
        decision_reason=latest.decision_reason,
        verified_at=latest.verified_at,
    )

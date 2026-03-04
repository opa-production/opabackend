"""
Client KYC via Veriff: create session (app opens URL), get status, webhook updates result.
Mirrors host_kyc.py but authenticates via get_current_client and stores rows in client_kycs.
"""
import html
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import requests
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth import get_current_client
from app.config import settings
from app.database import get_db
from app.models import Client, ClientKyc
from app.schemas import ClientKycSessionRequest, ClientKycSessionResponse, ClientKycStatusResponse

router = APIRouter(tags=["Client KYC"])
logger = logging.getLogger(__name__)

VERIFF_SESSIONS_PATH = "/v1/sessions"


def _allowed_return_to(return_to: str) -> bool:
    """True if return_to is in allowed prefixes (avoids open redirect)."""
    if not return_to or not return_to.strip():
        return False
    prefixes = [p.strip() for p in (settings.KYC_ALLOWED_RETURN_PREFIXES or "").split(",") if p.strip()]
    return any(return_to.strip().lower().startswith(p.lower()) for p in prefixes)


def build_client_kyc_redirect_response(return_to: Optional[str]) -> HTMLResponse:
    """
    Build HTML redirect response for client KYC callback.
    """
    if not return_to or not _allowed_return_to(return_to):
        return HTMLResponse(
            content="<html><body><p>Invalid or missing return link. You can close this page and open the app.</p></body></html>",
            status_code=400,
        )
    escaped = html.escape(return_to.strip())
    content = (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0;url={escaped}"></head>'
        f'<body><p>Redirecting to app\u2026 <a href="{escaped}">Open app</a></p></body></html>'
    )
    return HTMLResponse(content=content)


@router.get("/client/kyc/redirect", response_class=HTMLResponse)
def client_kyc_redirect(
    return_to: Optional[str] = Query(None, description="Deep link to open the app, e.g. ardena://kyc/result"),
):
    """
    Veriff redirects here after verification (HTTPS only). We redirect the browser to return_to
    (your app deep link) so the app opens. return_to must match KYC_ALLOWED_RETURN_PREFIXES.
    """
    return build_client_kyc_redirect_response(return_to)


@router.post("/client/kyc/session", response_model=ClientKycSessionResponse)
def create_client_kyc_session(
    body: Optional[ClientKycSessionRequest] = Body(None),
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Create a Veriff verification session for the current client.
    Returns verification_url: open this in a browser or webview so the client can complete ID + liveness.
    Pass callback_url (e.g. ardena://kyc/result) so Veriff redirects the user back after verification;
    then the app can call GET /client/kyc/status to show the result.
    """
    if not settings.VERIFF_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="KYC is not configured. Set VERIFF_API_KEY.",
        )
    base = (settings.VERIFF_BASE_URL or "https://stationapi.veriff.com").rstrip("/")
    url = base + VERIFF_SESSIONS_PATH

    # vendorData prefixed with "client:" so the webhook knows this is a client session
    verification_payload = {"vendorData": f"client:{current_client.id}"}
    callback_url = (body and body.callback_url and body.callback_url.strip()) or None
    if callback_url:
        callback_lower = callback_url.lower()
        if callback_lower.startswith("https://"):
            verification_payload["callback"] = callback_url
        elif settings.VERIFF_CALLBACK_URL:
            cb_base = settings.VERIFF_CALLBACK_URL.rstrip("/")
            # Point to the client redirect endpoint
            redirect_url = cb_base.replace("/host/kyc/redirect", "/client/kyc/redirect")
            verification_payload["callback"] = f"{redirect_url}?return_to={quote(callback_url, safe='')}"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only HTTPS return URLs are allowed by Veriff. Set VERIFF_CALLBACK_URL on the server for app deep links.",
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
            logger.warning("Veriff client session create %s: %s", r.status_code, err_body)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        err_detail = "Could not create verification session. Try again later."
        if hasattr(e, "response") and e.response is not None:
            try:
                err_json = e.response.json()
                err_detail = err_json.get("message") or err_json.get("detail") or err_detail
            except Exception:
                pass
        logger.exception("Veriff client session create failed: %s", e)
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

    kyc = ClientKyc(
        client_id=current_client.id,
        veriff_session_id=session_id,
        status="pending",
    )
    db.add(kyc)
    db.commit()

    return ClientKycSessionResponse(
        verification_url=verification_url,
        session_id=session_id,
    )


@router.get("/client/kyc/status", response_model=ClientKycStatusResponse)
def get_client_kyc_status(
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Return the latest KYC verification status for the current client.
    Use this after the user returns from Veriff to show approved/declined/pending.
    """
    latest = (
        db.query(ClientKyc)
        .filter(ClientKyc.client_id == current_client.id)
        .order_by(ClientKyc.created_at.desc())
        .first()
    )
    if not latest:
        return ClientKycStatusResponse(
            user_id=current_client.id,
            veriff_session_id=None,
            status="pending",
            document_type=None,
            decision_reason=None,
            verified_at=None,
        )
    return ClientKycStatusResponse(
        user_id=current_client.id,
        veriff_session_id=latest.veriff_session_id,
        status=latest.status,
        document_type=latest.document_type,
        decision_reason=latest.decision_reason,
        verified_at=latest.verified_at,
    )

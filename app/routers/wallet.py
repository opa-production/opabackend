"""
Ardena Pay: Stellar wallet (client) – get wallet, create wallet, balances.

Balances are fetched from Stellar Horizon on each GET, saved to the DB, then returned to the UI.
UI receives: public_key, network, balance_xlm, balance_usdc, balance_updated_at, secret_key (testnet), created_at.
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Client, ClientWallet, StellarPaymentTransaction, IncomingStellarPayment, Notification
from app.auth import get_current_client
from app.schemas import WalletResponse, StellarTransactionResponse, IncomingWalletPaymentResponse
from app.services.stellar_wallet import (
    create_and_fund_wallet,
    get_balances,
    parse_balances_for_response,
    get_incoming_payments,
    ksh_to_usd_float,
    _is_testnet,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# On testnet, set STELLAR_SHOW_SECRET_TESTNET=1 to include secret_key in response (for importing into Freighter/Lobstr)
SHOW_SECRET_TESTNET = os.getenv("STELLAR_SHOW_SECRET_TESTNET", "1").strip().lower() in ("1", "true", "yes")


async def _fetch_and_save_balances(wallet: ClientWallet, db: AsyncSession) -> tuple[str, str]:
    """Fetch balances from Horizon, save to wallet in DB, return (balance_xlm, balance_usdc)."""
    balances_raw = get_balances(wallet.stellar_public_key)
    balances = parse_balances_for_response(balances_raw)
    balance_xlm = balances.get("xlm", "0")
    balance_usdc = balances.get("usdc", "0")
    now = datetime.now(timezone.utc)
    wallet.balance_xlm = balance_xlm
    wallet.balance_usdc = balance_usdc
    wallet.balance_updated_at = now
    await db.commit()
    await db.refresh(wallet)
    return balance_xlm, balance_usdc


def _wallet_to_response(
    wallet: ClientWallet,
    balance_xlm: str | None = None,
    balance_usdc: str | None = None,
    include_secret: bool = False,
) -> WalletResponse:
    """Build API response from wallet; use provided balances or stored (DB)."""
    xlm = balance_xlm if balance_xlm is not None else (wallet.balance_xlm or "0")
    usdc = balance_usdc if balance_usdc is not None else (wallet.balance_usdc or "0")
    return WalletResponse(
        public_key=wallet.stellar_public_key,
        network=wallet.network,
        balance_xlm=xlm,
        balance_usdc=usdc,
        balance_updated_at=wallet.balance_updated_at,
        secret_key=wallet.stellar_secret_encrypted if include_secret else None,
        created_at=wallet.created_at,
    )


# NOTE: Ardena Pay wallet endpoints disabled — replaced by KuvarPay crypto payments.
# Re-enable when building own crypto infrastructure.
# @router.get("/client/wallet", response_model=WalletResponse)
async def get_wallet(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current client's Ardena Pay (Stellar) wallet.

    Fetches balances from Stellar Horizon, saves them to the DB, then returns the wallet.
    Response fields for UI: public_key, network, balance_xlm, balance_usdc, balance_updated_at, secret_key (testnet), created_at.
    """
    result = await db.execute(
        select(ClientWallet).where(ClientWallet.client_id == current_client.id)
    )
    wallet = result.scalar_one_or_none()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No wallet found. Create one with POST /client/wallet.",
        )
    balance_xlm, balance_usdc = await _fetch_and_save_balances(wallet, db)
    include_secret = wallet.network == "testnet" and SHOW_SECRET_TESTNET
    return _wallet_to_response(wallet, balance_xlm=balance_xlm, balance_usdc=balance_usdc, include_secret=include_secret)


# @router.post("/client/wallet", response_model=WalletResponse, status_code=status.HTTP_201_CREATED)
async def create_wallet(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Create an Ardena Pay (Stellar) wallet for the current client.

    - Generates a new keypair, funds it on testnet (Friendbot), and adds a USDC trust line.
    - If the client already has a wallet, returns 400.
    - Use GET /client/wallet to fetch wallet and balances afterward.
    """
    result = await db.execute(
        select(ClientWallet).where(ClientWallet.client_id == current_client.id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have a wallet. Use GET /client/wallet to view it.",
        )
    wallet_result = create_and_fund_wallet()
    if not wallet_result:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not create or fund wallet on Stellar testnet. Please try again later.",
        )
    public_key, secret_key = wallet_result
    network = "testnet" if _is_testnet() else "mainnet"
    wallet = ClientWallet(
        client_id=current_client.id,
        network=network,
        stellar_public_key=public_key,
        stellar_secret_encrypted=secret_key,  # stored as-is for testnet; encrypt in production if needed
    )
    db.add(wallet)
    await db.commit()
    await db.refresh(wallet)
    balance_xlm, balance_usdc = await _fetch_and_save_balances(wallet, db)
    include_secret = SHOW_SECRET_TESTNET and network == "testnet"
    return _wallet_to_response(wallet, balance_xlm=balance_xlm, balance_usdc=balance_usdc, include_secret=include_secret)


# @router.get("/client/wallet/transactions", response_model=List[StellarTransactionResponse])
async def list_wallet_transactions(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
    booking_id: Optional[int] = Query(None, description="Filter by booking id"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """
    List Ardena Pay (USDC/XLM) transactions for the current client's wallet.
    Same data as GET /api/v1/client/payments/transactions.
    """
    stmt = select(StellarPaymentTransaction).where(
        StellarPaymentTransaction.client_id == current_client.id
    )
    if booking_id is not None:
        stmt = stmt.where(StellarPaymentTransaction.booking_id == booking_id)
    stmt = stmt.order_by(StellarPaymentTransaction.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        StellarTransactionResponse(
            id=r.id,
            booking_id=r.booking_id,
            amount_ksh=r.amount_ksh,
            amount_usd=ksh_to_usd_float(r.amount_ksh),
            amount_usdc=r.amount_usdc,
            amount_xlm=r.amount_xlm,
            stellar_tx_hash=r.stellar_tx_hash,
            from_address=r.from_address,
            to_address=r.to_address,
            created_at=r.created_at,
        )
        for r in rows
    ]


# @router.get("/client/wallet/incoming", response_model=List[IncomingWalletPaymentResponse])
async def list_incoming_wallet_payments(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """
    List incoming Ardena Pay (USDC/XLM) payments to the client's wallet.
    Fetches from Stellar Horizon, stores new receipts, and creates in-app notifications
    ("You received X USDC") for new incoming payments so users see them in GET /client/notifications.
    """
    result = await db.execute(
        select(ClientWallet).where(ClientWallet.client_id == current_client.id)
    )
    wallet = result.scalar_one_or_none()
    if not wallet:
        return []
    incoming_raw = get_incoming_payments(wallet.stellar_public_key, limit=limit + 50)
    hash_result = await db.execute(
        select(IncomingStellarPayment.stellar_tx_hash).where(
            IncomingStellarPayment.client_id == current_client.id
        )
    )
    existing_hashes = {row[0] for row in hash_result.all()}
    in_app_enabled = getattr(current_client, "in_app_notifications_enabled", True)
    new_notif_count = 0

    for pay in incoming_raw:
        tx_hash = pay.get("tx_hash")
        if not tx_hash or tx_hash in existing_hashes:
            continue
        amount_asset = pay.get("asset_code") or "XLM"
        amount = pay.get("amount") or "0"
        from_addr = pay.get("from_address") or ""
        rec = IncomingStellarPayment(
            client_id=current_client.id,
            stellar_tx_hash=tx_hash,
            amount_asset=amount_asset,
            amount=amount,
            from_address=from_addr,
            to_address=wallet.stellar_public_key,
        )
        db.add(rec)
        await db.flush()
        if in_app_enabled:
            try:
                title = f"You received {amount} {amount_asset}"
                message = f"Your Ardena Pay wallet received {amount} {amount_asset}."
                notif = Notification(
                    recipient_type="client",
                    recipient_id=current_client.id,
                    title=title[:255],
                    message=message,
                    notification_type="success",
                    sender_name="Ardena Pay",
                )
                db.add(notif)
                await db.flush()
                rec.notification_id = notif.id
                new_notif_count += 1
            except Exception as e:
                logger.exception("[WALLET] Failed to create notification for new incoming payment tx=%s: %s", tx_hash[:16], e)
        existing_hashes.add(tx_hash)

    # Backfill notifications for existing incoming payments that never got one (e.g. synced before we created notifs)
    if in_app_enabled:
        try:
            missing_result = await db.execute(
                select(IncomingStellarPayment).where(
                    IncomingStellarPayment.client_id == current_client.id,
                    IncomingStellarPayment.notification_id.is_(None),
                )
            )
            missing = list(missing_result.scalars().all())
            for rec in missing:
                try:
                    title = f"You received {rec.amount} {rec.amount_asset}"
                    message = f"Your Ardena Pay wallet received {rec.amount} {rec.amount_asset}."
                    notif = Notification(
                        recipient_type="client",
                        recipient_id=current_client.id,
                        title=title[:255],
                        message=message,
                        notification_type="success",
                        sender_name="Ardena Pay",
                    )
                    db.add(notif)
                    await db.flush()
                    rec.notification_id = notif.id
                    new_notif_count += 1
                except Exception as e:
                    logger.exception("[WALLET] Failed to backfill notification for incoming_stellar_payment id=%s: %s", rec.id, e)
            if missing:
                logger.info("[WALLET] Backfilled %s notification(s) for client_id=%s", len(missing), current_client.id)
        except Exception as e:
            logger.exception("[WALLET] Backfill query failed for client_id=%s: %s", current_client.id, e)

    if new_notif_count:
        logger.info("[WALLET] Created %s in-app notification(s) for incoming payments, client_id=%s", new_notif_count, current_client.id)
    await db.commit()
    rows_result = await db.execute(
        select(IncomingStellarPayment)
        .where(IncomingStellarPayment.client_id == current_client.id)
        .order_by(IncomingStellarPayment.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = list(rows_result.scalars().all())
    return [
        IncomingWalletPaymentResponse(
            id=r.id,
            amount_asset=r.amount_asset,
            amount=r.amount,
            from_address=r.from_address,
            stellar_tx_hash=r.stellar_tx_hash,
            created_at=r.created_at,
            notification_id=r.notification_id,
        )
        for r in rows
    ]

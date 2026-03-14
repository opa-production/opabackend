"""
Ardena Pay: Stellar wallet (client) – get wallet, create wallet, balances.

Balances are fetched from Stellar Horizon on each GET, saved to DB, then returned to the UI.
UI receives: public_key, network, balance_xlm, balance_usdc, balance_updated_at, secret_key (testnet), created_at.
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.database import get_db
from app.models import Client, ClientWallet
from app.auth import get_current_client
from app.schemas import WalletResponse
from app.services.stellar_wallet import (
    create_and_fund_wallet,
    get_balances,
    parse_balances_for_response,
    _is_testnet,
)
from sqlalchemy.orm import Session

router = APIRouter()
logger = logging.getLogger(__name__)

# On testnet, set STELLAR_SHOW_SECRET_TESTNET=1 to include secret_key in response (for importing into Freighter/Lobstr)
SHOW_SECRET_TESTNET = os.getenv("STELLAR_SHOW_SECRET_TESTNET", "1").strip().lower() in ("1", "true", "yes")


def _fetch_and_save_balances(wallet: ClientWallet, db: Session) -> tuple[str, str]:
    """Fetch balances from Horizon, save to wallet in DB, return (balance_xlm, balance_usdc)."""
    balances_raw = get_balances(wallet.stellar_public_key)
    balances = parse_balances_for_response(balances_raw)
    balance_xlm = balances.get("xlm", "0")
    balance_usdc = balances.get("usdc", "0")
    now = datetime.now(timezone.utc)
    wallet.balance_xlm = balance_xlm
    wallet.balance_usdc = balance_usdc
    wallet.balance_updated_at = now
    db.commit()
    db.refresh(wallet)
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


@router.get("/client/wallet", response_model=WalletResponse)
def get_wallet(
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Get the current client's Ardena Pay (Stellar) wallet.

    Fetches balances from Stellar Horizon, saves them to the DB, then returns the wallet.
    Response fields for UI: public_key, network, balance_xlm, balance_usdc, balance_updated_at, secret_key (testnet), created_at.
    """
    wallet = db.query(ClientWallet).filter(ClientWallet.client_id == current_client.id).first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No wallet found. Create one with POST /client/wallet.",
        )
    balance_xlm, balance_usdc = _fetch_and_save_balances(wallet, db)
    include_secret = wallet.network == "testnet" and SHOW_SECRET_TESTNET
    return _wallet_to_response(wallet, balance_xlm=balance_xlm, balance_usdc=balance_usdc, include_secret=include_secret)


@router.post("/client/wallet", response_model=WalletResponse, status_code=status.HTTP_201_CREATED)
def create_wallet(
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Create an Ardena Pay (Stellar) wallet for the current client.

    - Generates a new keypair, funds it on testnet (Friendbot), and adds a USDC trust line.
    - If the client already has a wallet, returns 400.
    - Use GET /client/wallet to fetch wallet and balances afterward.
    """
    existing = db.query(ClientWallet).filter(ClientWallet.client_id == current_client.id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have a wallet. Use GET /client/wallet to view it.",
        )
    result = create_and_fund_wallet()
    if not result:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not create or fund wallet on Stellar testnet. Please try again later.",
        )
    public_key, secret_key = result
    network = "testnet" if _is_testnet() else "mainnet"
    wallet = ClientWallet(
        client_id=current_client.id,
        network=network,
        stellar_public_key=public_key,
        stellar_secret_encrypted=secret_key,  # stored as-is for testnet; encrypt in production if needed
    )
    db.add(wallet)
    db.commit()
    db.refresh(wallet)
    balance_xlm, balance_usdc = _fetch_and_save_balances(wallet, db)
    include_secret = SHOW_SECRET_TESTNET and network == "testnet"
    return _wallet_to_response(wallet, balance_xlm=balance_xlm, balance_usdc=balance_usdc, include_secret=include_secret)

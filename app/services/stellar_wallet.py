"""
Ardena Pay: Stellar wallet creation, funding (testnet), USDC trust line, and balance fetching.
"""
from __future__ import annotations

import os
import logging
import requests
from typing import Any

from stellar_sdk import Keypair, Server, Asset, Network, TransactionBuilder
from stellar_sdk.operation import ChangeTrust, Payment
from stellar_sdk.exceptions import BadRequestError

logger = logging.getLogger(__name__)

# Testnet defaults
DEFAULT_HORIZON_TESTNET = "https://horizon-testnet.stellar.org"
DEFAULT_USDC_ISSUER_TESTNET = "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"
FRIENDBOT_URL = "https://friendbot.stellar.org"


def _get_horizon_url() -> str:
    return os.getenv("STELLAR_HORIZON_URL", DEFAULT_HORIZON_TESTNET)


def _get_usdc_issuer() -> str:
    return os.getenv("STELLAR_USDC_ISSUER_TESTNET", DEFAULT_USDC_ISSUER_TESTNET)


def _is_testnet() -> bool:
    url = _get_horizon_url()
    return "testnet" in url.lower()


def _get_platform_public_key() -> str | None:
    """Platform wallet that receives USDC payments. Set STELLAR_PLATFORM_PUBLIC_KEY."""
    return os.getenv("STELLAR_PLATFORM_PUBLIC_KEY") or None


def ksh_to_usdc(amount_ksh: float) -> str:
    """
    Convert KSH to USDC amount (string for Stellar). Uses USDC_PER_KSH env (e.g. 0.0075).
    Returns decimal string with up to 7 decimals (Stellar asset amount format).
    """
    rate = float(os.getenv("USDC_PER_KSH", "0.0075"))
    usdc = amount_ksh * rate
    return f"{usdc:.7f}".rstrip("0").rstrip(".")


def ksh_to_usd_float(amount_ksh: float) -> float:
    """Convert KSH to USD value for display. Uses USDC_PER_KSH (1 KSH = X USD)."""
    rate = float(os.getenv("USDC_PER_KSH", "0.0075"))
    return amount_ksh * rate


def ksh_to_xlm(amount_ksh: float) -> str:
    """
    Convert KSH to XLM amount for payment. Uses USDC_PER_KSH (KSH→USD) and USD_PER_XLM (1 XLM = X USD).
    So: amount_xlm = (amount_ksh * USDC_PER_KSH) / USD_PER_XLM.
    Returns decimal string for Stellar native amount (max 7 decimals).
    """
    usdc_per_ksh = float(os.getenv("USDC_PER_KSH", "0.0075"))
    usd_per_xlm = float(os.getenv("USD_PER_XLM", "0.16"))  # 1 XLM ≈ 0.16 USD; align with UI/CoinGecko if needed
    if usd_per_xlm <= 0:
        usd_per_xlm = 0.16
    amount_usd = amount_ksh * usdc_per_ksh
    amount_xlm = amount_usd / usd_per_xlm
    return f"{amount_xlm:.7f}".rstrip("0").rstrip(".")


def create_keypair() -> tuple[str, str]:
    """Generate a new Stellar keypair. Returns (public_key, secret_key)."""
    keypair = Keypair.random()
    return keypair.public_key, keypair.secret


def fund_testnet(public_key: str) -> bool:
    """Fund account on Stellar testnet via Friendbot. Returns True on success."""
    try:
        r = requests.get(FRIENDBOT_URL, params={"addr": public_key}, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        logger.warning("[STELLAR] Friendbot funding failed for %s: %s", public_key[:8], e)
        return False


def add_usdc_trust_line(public_key: str, secret_key: str) -> bool:
    """Add USDC trust line for the account. Returns True on success."""
    try:
        server = Server(horizon_url=_get_horizon_url())
        issuer = _get_usdc_issuer()
        account = server.load_account(public_key)
        keypair = Keypair.from_secret(secret_key)
        asset = Asset("USDC", issuer)
        network = Network.TESTNET_NETWORK_PASSPHRASE if _is_testnet() else Network.PUBLIC_NETWORK_PASSPHRASE
        tx = (
            TransactionBuilder(
                source_account=account,
                network_passphrase=network,
                base_fee=100,
            )
            .append_operation(ChangeTrust(asset=asset))
            .set_timeout(30)
            .build()
        )
        tx.sign(keypair)
        server.submit_transaction(tx)
        return True
    except BadRequestError as e:
        # e.g. trust line already exists
        if "op_already_exists" in str(e).lower() or "trustline" in str(e).lower():
            return True
        logger.warning("[STELLAR] ChangeTrust BadRequest for %s: %s", public_key[:8], e)
        return False
    except Exception as e:
        logger.warning("[STELLAR] Add USDC trust line failed for %s: %s", public_key[:8], e)
        return False


def get_balances(public_key: str) -> list[dict[str, Any]]:
    """
    Fetch account balances from Horizon. Returns list of { asset_type, asset_code, balance, ... }.
    Native XLM has asset_type 'native'. USDC has asset_type 'credit_alphanum4', asset_code 'USDC'.
    """
    try:
        server = Server(horizon_url=_get_horizon_url())
        account = server.accounts().account_id(public_key).call()
        # SDK may return dict, or object with raw_data / balances
        if isinstance(account, dict):
            balances = account.get("balances", [])
        elif hasattr(account, "raw_data") and isinstance(getattr(account, "raw_data"), dict):
            balances = account.raw_data.get("balances", [])
        else:
            balances = getattr(account, "balances", [])
        # Normalize to list of dicts (SDK sometimes returns balance objects)
        out = []
        for b in list(balances) if balances else []:
            if isinstance(b, dict):
                out.append(b)
            else:
                out.append({
                    "asset_type": getattr(b, "asset_type", None),
                    "asset_code": getattr(b, "asset_code", None),
                    "balance": getattr(b, "balance", "0"),
                })
        logger.info("[STELLAR] get_balances for %s: %s balance(s) from Horizon", public_key[:8], len(out))
        print(f"[STELLAR] get_balances: {len(out)} balance(s) from Horizon for {public_key[:12]}...", flush=True)
        return out
    except Exception as e:
        logger.warning("[STELLAR] get_balances failed for %s: %s", public_key[:8], e)
        print(f"[STELLAR] get_balances FAILED: {e}", flush=True)
        return []


def parse_balances_for_response(balances: list[dict[str, Any]]) -> dict[str, str]:
    """
    Convert Horizon balances to a simple dict: { "xlm": "100.0", "usdc": "50.0" }.
    Handles both dict and object-like items (e.g. from SDK).
    """
    out: dict[str, str] = {}
    for b in balances:
        # Support dict or object (e.g. AttrDict)
        at = (b.get("asset_type") if isinstance(b, dict) else getattr(b, "asset_type", None)) or ""
        balance_val = (b.get("balance") if isinstance(b, dict) else getattr(b, "balance", None)) or "0"
        code = (b.get("asset_code") if isinstance(b, dict) else getattr(b, "asset_code", None)) or ""
        if at == "native":
            out["xlm"] = balance_val
        elif at == "credit_alphanum4" and (code == "USDC" or (isinstance(code, str) and code.upper() == "USDC")):
            out["usdc"] = balance_val
        elif at == "credit_alphanum12" and (str(code).upper() == "USDC"):
            out["usdc"] = balance_val
    if "xlm" not in out:
        out["xlm"] = "0"
    if "usdc" not in out:
        out["usdc"] = "0"
    return out


def send_xlm_payment(
    from_secret_key: str,
    to_public_key: str,
    amount_xlm: str,
) -> str | None:
    """
    Send native XLM from one account to another. Returns Stellar transaction hash on success, None on failure.
    amount_xlm: string amount (e.g. "10.5").
    """
    try:
        server = Server(horizon_url=_get_horizon_url())
        keypair = Keypair.from_secret(from_secret_key)
        account = server.load_account(keypair.public_key)
        network = Network.TESTNET_NETWORK_PASSPHRASE if _is_testnet() else Network.PUBLIC_NETWORK_PASSPHRASE
        tx = (
            TransactionBuilder(
                source_account=account,
                network_passphrase=network,
                base_fee=100,
            )
            .append_operation(Payment(destination=to_public_key, asset=Asset.native(), amount=amount_xlm))
            .set_timeout(30)
            .build()
        )
        tx.sign(keypair)
        result = server.submit_transaction(tx)
        tx_hash = result.get("hash") if isinstance(result, dict) else getattr(result, "hash", None)
        if tx_hash:
            logger.info("[STELLAR] XLM payment sent: tx=%s amount=%s to=%s", tx_hash[:8], amount_xlm, to_public_key[:8])
        return str(tx_hash) if tx_hash else None
    except Exception as e:
        logger.warning("[STELLAR] send_xlm_payment failed: %s", e)
        return None


def send_usdc_payment(
    from_secret_key: str,
    to_public_key: str,
    amount_usdc: str,
) -> str | None:
    """
    Send USDC from one account to another. Returns Stellar transaction hash on success, None on failure.
    amount_usdc: string amount (e.g. "10.50").
    """
    try:
        server = Server(horizon_url=_get_horizon_url())
        issuer = _get_usdc_issuer()
        keypair = Keypair.from_secret(from_secret_key)
        account = server.load_account(keypair.public_key)
        asset = Asset("USDC", issuer)
        network = Network.TESTNET_NETWORK_PASSPHRASE if _is_testnet() else Network.PUBLIC_NETWORK_PASSPHRASE
        tx = (
            TransactionBuilder(
                source_account=account,
                network_passphrase=network,
                base_fee=100,
            )
            .append_operation(Payment(destination=to_public_key, asset=asset, amount=amount_usdc))
            .set_timeout(30)
            .build()
        )
        tx.sign(keypair)
        result = server.submit_transaction(tx)
        tx_hash = result.get("hash") if isinstance(result, dict) else getattr(result, "hash", None)
        if tx_hash:
            logger.info("[STELLAR] Payment sent: tx=%s amount=%s to=%s", tx_hash[:8], amount_usdc, to_public_key[:8])
        return str(tx_hash) if tx_hash else None
    except Exception as e:
        logger.warning("[STELLAR] send_usdc_payment failed: %s", e)
        return None


def get_incoming_payments(public_key: str, limit: int = 50) -> list[dict[str, Any]]:
    """
    Fetch incoming payments to a Stellar account from Horizon (payments where account is the destination).
    Returns list of dicts: { tx_hash, amount, asset_type, asset_code, from_address, created_at }.
    Horizon /accounts/{id}/payments returns all payments where the account participated; we keep only
    those where we are the receiver (source_account != our key, or to == our key).
    """
    try:
        base = _get_horizon_url().rstrip("/")
        url = f"{base}/accounts/{public_key}/payments"
        r = requests.get(url, params={"limit": limit, "order": "desc"}, timeout=15)
        r.raise_for_status()
        data = r.json()
        records = data.get("_embedded", {}).get("records", [])
        usdc_issuer = _get_usdc_issuer()
        out: list[dict[str, Any]] = []
        for op in records:
            # Include both "payment" and "create_account" (initial XLM funding)
            op_type = op.get("type") or ""
            if op_type not in ("payment", "create_account"):
                continue
            source = op.get("source_account") or op.get("from") or ""
            to_addr = op.get("to") or op.get("account") or ""
            # Incoming = we are NOT the source (someone sent to us). For /accounts/OUR_ID/payments, if source != us, we're receiver.
            if source == public_key:
                continue
            from_addr = source
            amount = op.get("amount", "0")
            if op_type == "create_account":
                amount = op.get("starting_balance", amount)
                asset_code = "XLM"
                asset_type = "native"
            else:
                asset_type = op.get("asset_type", "native")
                asset_code = (op.get("asset_code") or "").strip().upper() or "XLM"
                if asset_type == "native":
                    asset_code = "XLM"
                elif asset_type in ("credit_alphanum4", "credit_alphanum12") and op.get("asset_issuer") == usdc_issuer:
                    asset_code = "USDC"
            tx_hash = op.get("transaction_hash") or ""
            created_at = op.get("created_at")
            out.append({
                "tx_hash": tx_hash,
                "amount": amount,
                "asset_type": asset_type,
                "asset_code": asset_code,
                "from_address": from_addr,
                "created_at": created_at,
            })
        if records and not out:
            # Debug: Horizon returned records but none matched; log first record keys/structure
            first = records[0]
            logger.info(
                "[STELLAR] get_incoming_payments debug: first record keys=%s type=%s source=%s to=%s",
                list(first.keys()),
                first.get("type"),
                first.get("source_account") or first.get("from"),
                first.get("to") or first.get("account"),
            )
        logger.info("[STELLAR] get_incoming_payments for %s: %s records from Horizon, %s incoming", public_key[:8], len(records), len(out))
        return out
    except Exception as e:
        logger.warning("[STELLAR] get_incoming_payments failed for %s: %s", public_key[:8], e)
        return []


def create_and_fund_wallet() -> tuple[str, str] | None:
    """
    Create a new Stellar keypair, fund it on testnet, add USDC trust line.
    Returns (public_key, secret_key) on success, None on failure.
    """
    public_key, secret_key = create_keypair()
    if not fund_testnet(public_key):
        return None
    # Wait a moment for account to be visible
    import time
    time.sleep(2)
    add_usdc_trust_line(public_key, secret_key)
    return public_key, secret_key

#!/usr/bin/env bash
# Expose backend on port 8001 for callbacks (Payhero M-Pesa, Veriff KYC).
# After ngrok starts, copy the HTTPS URL and set in .env:
#   PAYHERO_CALLBACK_URL=https://YOUR-SUBDOMAIN.ngrok-free.app/api/v1/mpesa/callback
#   VERIFF_CALLBACK_URL=https://YOUR-SUBDOMAIN.ngrok-free.app/api/v1/host/kyc/redirect
# Then restart the backend.

echo "Starting ngrok for port 8001..."
echo ""
echo "When you see 'Forwarding https://....ngrok-free.app', add to .env:"
echo "  PAYHERO_CALLBACK_URL=https://YOUR-SUBDOMAIN.ngrok-free.app/api/v1/mpesa/callback"
echo "  VERIFF_CALLBACK_URL=https://YOUR-SUBDOMAIN.ngrok-free.app/api/v1/host/kyc/redirect"
echo ""
ngrok http 8001

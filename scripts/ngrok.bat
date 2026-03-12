@echo off
REM Expose backend on port 8001 for callbacks (Payhero M-Pesa, Veriff KYC).
REM After ngrok starts, copy the HTTPS URL and set in .env:
REM   PAYHERO_CALLBACK_URL=https://YOUR-SUBDOMAIN.ngrok-free.app/api/v1/mpesa/callback
REM   VERIFF_CALLBACK_URL=https://YOUR-SUBDOMAIN.ngrok-free.app/api/v1/host/kyc/redirect
REM Then restart the backend.

echo Starting ngrok for port 8001...
echo.
echo When you see "Forwarding https://....ngrok-free.app", add to .env:
echo   PAYHERO_CALLBACK_URL=https://YOUR-SUBDOMAIN.ngrok-free.app/api/v1/mpesa/callback
echo   VERIFF_CALLBACK_URL=https://YOUR-SUBDOMAIN.ngrok-free.app/api/v1/host/kyc/redirect
echo.
ngrok http 8001

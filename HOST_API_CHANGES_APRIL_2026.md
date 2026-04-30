# Host API Changes - Launch Phase (April 2026)

To simplify the launch and make the platform more accessible for small businesses and peer-to-peer hosts, we have implemented the following changes to the Host API:

## 1. Car Listing Limit
- **All host accounts** are now limited to a maximum of **10 car listings**.
- This limit applies to both incomplete and complete listings.
- When a host attempts to create an 11th car (via `POST /api/v1/cars/basics`), the API will return a `403 Forbidden` error with the message: `"You have reached the limit of 10 car listings. Please contact support to increase your limit."`

## 2. Subscription Plans Disabled
- **Paid plans (Starter & Premium)** have been temporarily disabled.
- The `GET /api/v1/host/subscription/plans` endpoint now only returns the **Free** plan.
- The following checkout endpoints now return a `403 Forbidden` error:
    - `POST /api/v1/host/subscription/checkout` (M-Pesa)
    - `POST /api/v1/host/subscription/checkout/card` (Paystack Card)

## 3. Free Trial Removed
- The one-time 30-day free trial has been disabled.
- The `POST /api/v1/host/subscription/trial` endpoint is now commented out/disabled and returns a `403 Forbidden` error.
- All trial-related status fields in `GET /api/v1/host/subscription/me` will now return `false`.

## Summary for Host Application Update
- Update the UI to reflect the 10-car listing limit.
- Hide or disable "Upgrade Plan" and "Start Free Trial" buttons/sections in the Host app.
- Ensure the app handles `403 Forbidden` errors from subscription endpoints gracefully by informing the user that paid plans are currently disabled.

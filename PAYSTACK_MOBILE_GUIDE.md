# Paystack Integration — React Native Mobile Guide

This document covers everything you need to implement card payments with Paystack in the React Native (JavaScript) app.
M-Pesa, Ardena Pay (Stellar), and all other flows are **unchanged**.

---

## What Changed vs PesaPal

| Area | Before (PesaPal) | After (Paystack) |
|------|-----------------|-----------------|
| Add card method endpoint | `POST /api/v1/client/payment-methods/card-pesapal` | `POST /api/v1/client/payment-methods/card-paystack` |
| Card type field in request | `card_type: "visa" \| "mastercard"` | **Removed** — Paystack auto-detects the card type |
| Payment method type value | `"visa"` or `"mastercard"` | `"card"` |
| redirect_url key in payment response | `redirect_url` | `redirect_url` (**same field**, just a different URL) |
| After-payment callback endpoint | `GET /pesapal/return` | `GET /paystack/callback` |
| Status polling param | `order_tracking_id` | `paystack_reference` |
| Status response field | `order_tracking_id` | `paystack_reference` |

---

## Step 1 — Add a Card Payment Method

Call this once to let the user register a card method (no card data required).

```
POST /api/v1/client/payment-methods/card-paystack
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "My Card",          // optional display name; defaults to "Card"
  "is_default": true
}
```

**Response** (same `PaymentMethodResponse` shape as before):
```json
{
  "id": 42,
  "name": "My Card",
  "method_type": "card",
  "card_type": "card",
  "card_last_four": null,
  "is_default": true
}
```

Save the `id` — you'll pass it as `payment_method_id` when initiating a booking payment.

---

## Step 2 — Initiate a Card Payment

```
POST /api/v1/client/payments/process
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "booking_id": "BK-XXXXXXXX",
  "payment_method_id": 42
}
```

**Response:**
```json
{
  "success": true,
  "booking_id": "BK-XXXXXXXX",
  "amount_paid": 5500.0,
  "payment_method_type": "card",
  "payment_method_name": "My Card",
  "transaction_id": "BK-XXXXXXXX-a1b2c3d4",
  "message": "Redirect to complete card payment. Poll GET /client/payments/status?paystack_reference=... for status.",
  "paid_at": "2026-04-17T10:00:00Z",
  "redirect_url": "https://checkout.paystack.com/xxxxxxxxxxxxxxxx",
  "booking": { ... }
}
```

> **Key field:** `redirect_url` — open this URL in the browser so the user can enter their card.

---

## Step 3 — Open the Paystack Hosted Page

Open `redirect_url` using `expo-web-browser` (recommended) or `Linking`:

```javascript
import * as WebBrowser from 'expo-web-browser';
import * as Linking from 'expo-linking';

async function openPaystackPage(redirectUrl, paystackReference, bookingId) {
  // Build the deep link your app will receive after payment
  const callbackUrl = Linking.createURL('payment/result');

  const result = await WebBrowser.openAuthSessionAsync(redirectUrl, callbackUrl);

  if (result.type === 'success' || result.type === 'dismiss') {
    // Payment may or may not have been completed — always poll for status
    await pollPaymentStatus(paystackReference, bookingId);
  }
}
```

> **Why `openAuthSessionAsync`?** It handles the deep-link redirect back to the app automatically on both iOS and Android.

---

## Step 4 — Poll for Payment Status

After the browser closes, poll until status is no longer `pending`:

```javascript
async function pollPaymentStatus(paystackReference, bookingId) {
  const MAX_POLLS = 20;
  const INTERVAL_MS = 3000;

  for (let i = 0; i < MAX_POLLS; i++) {
    const res = await fetch(
      `/api/v1/client/payments/status?paystack_reference=${paystackReference}`,
      { headers: { Authorization: `Bearer ${accessToken}` } }
    );
    const data = await res.json();

    if (data.status === 'completed') {
      // Booking confirmed — navigate to confirmation screen
      navigation.navigate('BookingConfirmed', { bookingId });
      return;
    }

    if (data.status === 'failed' || data.status === 'cancelled') {
      // Show error message from data.message
      showError(data.message || 'Payment failed. Please try again.');
      return;
    }

    // Still pending — wait and retry
    await new Promise(r => setTimeout(r, INTERVAL_MS));
  }

  // Timeout — tell user to check booking screen
  showError('Payment status unknown. Please check your bookings.');
}
```

You can also poll by `booking_id` if you don't have the reference:
```
GET /api/v1/client/payments/status?booking_id=BK-XXXXXXXX
```

---

## Step 5 — Handle the Deep Link (Optional but Recommended)

When Paystack finishes, it redirects to `GET /api/v1/paystack/callback?reference=...`, which then
redirects to your app's deep link: `oparides://payment/result?reference=<ref>`.

Listen for it with `expo-linking`:

```javascript
import * as Linking from 'expo-linking';
import { useEffect } from 'react';

function usePaymentDeepLink(onReference) {
  useEffect(() => {
    const sub = Linking.addEventListener('url', ({ url }) => {
      const { path, queryParams } = Linking.parse(url);
      if (path === 'payment/result' && queryParams?.reference) {
        onReference(queryParams.reference);
      }
    });
    return () => sub.remove();
  }, [onReference]);
}
```

Then use this reference to call `pollPaymentStatus` immediately.

---

## Full Payment Flow Summary

```
User taps "Pay with Card"
         │
         ▼
POST /api/v1/client/payments/process
   → { redirect_url, transaction_id (= paystack_reference) }
         │
         ▼
Open redirect_url in expo-web-browser
   (Paystack hosted checkout page)
         │
  User enters card details
         │
         ▼
Paystack processes payment
         │
    ┌────┴────┐
    │         │
  Success   Abandon/Fail
    │         │
    └────┬────┘
         │
         ▼
Paystack redirects to:
  GET /api/v1/paystack/callback?reference=xxx
         │
         ▼
Backend redirects to deep link:
  oparides://payment/result?reference=xxx
         │
         ▼
App catches deep link → poll status
         │
  ┌──────┴──────┐
  │             │
completed     failed
  │             │
Navigate to  Show error
Confirmed      msg
```

---

## API Reference

### `POST /api/v1/client/payment-methods/card-paystack`

Add a card payment method (no card data stored).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | No | Display name (default: "Card") |
| `is_default` | boolean | No | Set as default method |

---

### `POST /api/v1/client/payments/process`

Initiate a payment (unchanged from before).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `booking_id` | string | Yes | e.g. `"BK-XXXXXXXX"` |
| `payment_method_id` | integer | Yes | ID from `/client/payment-methods` |

**Response additions for card payments:**

| Field | Description |
|-------|-------------|
| `redirect_url` | Paystack hosted checkout URL — open in browser |
| `transaction_id` | Same as `paystack_reference` — use for polling |

---

### `GET /api/v1/client/payments/status`

Poll payment status. Provide **one** of the three params:

| Param | Description |
|-------|-------------|
| `paystack_reference` | Paystack reference (from `transaction_id` in payment response) |
| `checkout_request_id` | M-Pesa CheckoutRequestID (unchanged) |
| `booking_id` | Booking ID — returns the latest payment for the booking |

**Response:**

```json
{
  "checkout_request_id": "BK-XXXXXXXX-a1b2c3d4",
  "booking_id": "BK-XXXXXXXX",
  "status": "completed",
  "message": null,
  "amount": 5500.0,
  "paid_at": "2026-04-17T10:05:00Z",
  "mpesa_receipt_number": null,
  "paystack_reference": "BK-XXXXXXXX-a1b2c3d4"
}
```

`status` values: `pending` | `completed` | `cancelled` | `failed`

---

## Environment / Config Checklist (Backend)

```env
PAYSTACK_SECRET_KEY=sk_live_xxxxxxxxxx          # from Paystack dashboard
PAYSTACK_CALLBACK_BASE_URL=https://api.ardena.xyz/api/v1
FRONTEND_URL=oparides://                         # your app's deep link scheme
```

Set the Paystack webhook URL in the [Paystack dashboard](https://dashboard.paystack.com/#/settings/developer):
```
https://api.ardena.xyz/api/v1/paystack/webhook
```

---

## Dependencies (React Native)

```bash
npx expo install expo-web-browser expo-linking
```

These are already available in Expo SDK — no extra native config needed for managed workflow.

For bare React Native use `react-native-inappbrowser-reborn` or `@react-native-community/react-native-inappbrowser`.

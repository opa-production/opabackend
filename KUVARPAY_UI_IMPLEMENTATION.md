# KuvarPay Inline Checkout — UI Implementation Guide

This guide explains how to add **KuvarPay crypto payments** to the Ardena checkout flow.
The user selects "Pay with Crypto" on the checkout screen, the app creates a server-side
session, then renders the KuvarPay inline widget inside your custom UI container.

---

## 1. SDK Auto-Initialization

Add the script tag **once** to your HTML shell (e.g. `index.html`).
The `data-inline-checkout="true"` flag puts the SDK into inline mode — it will mount
into a DOM element you provide instead of opening a full-page modal.

```html
<script
  src="https://pay.kuvarpay.com/kuvarpay-sdk.js"
  data-api-key="YOUR_PUBLISHABLE_KEY"
  data-business-id="YOUR_BUSINESS_ID"
  data-base-url="https://pay.kuvarpay.com"
  data-debug="false"
  data-inline-checkout="true"
></script>
```

> **Note:** `data-api-key` is the **publishable** key only — never put the secret key in
> frontend code. The backend creates sessions using the secret key.

---

## 2. Payment Flow Overview

```
User selects "Pay with Crypto"
       ↓
POST /api/v1/client/payments/kuvarpay/create-session   ← backend creates KuvarPay session
       ↓
Backend returns { session_id, publishable_key, business_id, amount_ksh }
       ↓
Frontend mounts KuvarPay inline widget with session_id
       ↓
User selects crypto & completes payment inside widget
       ↓
KuvarPay sends webhook → POST /api/v1/kuvarpay/webhook   ← backend confirms booking
       ↓
Frontend polls GET /api/v1/client/payments/kuvarpay/status/{session_id}
       ↓
Status = "completed" → navigate to booking confirmed screen
```

---

## 3. Backend API Reference

### Create session

```
POST /api/v1/client/payments/kuvarpay/create-session
Authorization: Bearer <client_token>
Content-Type: application/json

{
  "bookingId": "BK-ABC12345"
}
```

**Response 201:**
```json
{
  "session_id": "cs_112fa537568040d5a282b525a32692ff",
  "auth_token": "eyJhbGci...",
  "publishable_key": "rsp_live_...",
  "business_id": "102a8387-...",
  "booking_id": "BK-ABC12345",
  "amount_ksh": 4500.00,
  "message": "KuvarPay session created. Initialize the checkout widget with session_id."
}
```

> **Important:** Pass **both** `session_id` and `auth_token` to `KuvarPay.openPayment()`.
> The `auth_token` is a short-lived JWT KuvarPay uses to authenticate the widget session.

### Poll payment status

```
GET /api/v1/client/payments/kuvarpay/status/{session_id}
Authorization: Bearer <client_token>
```

**Response 200:**
```json
{
  "session_id": "cs_xxxxxxxxxxxxxxxx",
  "booking_id": "BK-ABC12345",
  "status": "completed",      // pending | completed | failed | cancelled
  "amount_ksh": 4500.00,
  "message": "KuvarPay crypto payment completed",
  "paid_at": "2025-04-28T12:00:00Z"
}
```

---

## 4. Frontend Implementation

### HTML container

Place this where you want the widget to appear in your checkout UI:

```html
<!-- Your custom checkout card -->
<div class="payment-method-card" id="crypto-section">
  <h3>Pay with Crypto</h3>
  <p id="crypto-amount">Loading...</p>

  <!-- KuvarPay inline widget mounts here -->
  <div id="kuvarpay-container" style="min-height: 400px;"></div>

  <p id="crypto-status-msg" class="hidden"></p>
</div>
```

### JavaScript

```javascript
// kuvarpay-checkout.js

const API_BASE = 'https://api.ardena.xyz/api/v1';
let _pollInterval = null;

/**
 * Call this when the user taps "Pay with Crypto" on the checkout screen.
 * @param {string} bookingId  - e.g. "BK-ABC12345"
 * @param {string} authToken  - client JWT
 */
async function initKuvarPayCheckout(bookingId, authToken) {
  // 1. Create server-side session
  const res = await fetch(`${API_BASE}/client/payments/kuvarpay/create-session`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${authToken}`,
    },
    body: JSON.stringify({ bookingId }),
  });

  if (!res.ok) {
    const err = await res.json();
    showError(err.detail || 'Could not start crypto payment. Please try again.');
    return;
  }

  const { session_id, auth_token, amount_ksh } = await res.json();

  document.getElementById('crypto-amount').textContent =
    `KES ${amount_ksh.toLocaleString()}`;

  // 2. Open the KuvarPay payment widget with the session
  //    KuvarPay SDK exposes window.KuvarPay after the script loads.
  //    The SDK auto-initialised with your publishable key via the <script> data- attrs.
  window.KuvarPay.openPayment(
    { sessionId: session_id, authToken: auth_token },
    {
      onSuccess: (sid) => onPaymentSuccess(sid || session_id, authToken),
      onCancel:  () => onPaymentFailure({ message: 'Payment cancelled.' }),
      onError:   (err) => onPaymentFailure(err),
    },
    { theme: 'light' }   // or 'dark'
  );

  // 3. Start polling as a backup (webhook updates DB; polling catches UI)
  _pollInterval = setInterval(() => pollStatus(session_id, authToken), 4000);
}

async function pollStatus(sessionId, authToken) {
  try {
    const res = await fetch(
      `${API_BASE}/client/payments/kuvarpay/status/${sessionId}`,
      { headers: { 'Authorization': `Bearer ${authToken}` } },
    );
    if (!res.ok) return;
    const data = await res.json();

    if (data.status === 'completed') {
      clearInterval(_pollInterval);
      navigateToConfirmed(data.booking_id);
    } else if (data.status === 'failed' || data.status === 'cancelled') {
      clearInterval(_pollInterval);
      showError('Payment was not completed. Please try a different method.');
    }
  } catch (_) { /* network hiccup — keep polling */ }
}

function onPaymentSuccess(sessionId, authToken) {
  // SDK fired success — verify via backend before navigating
  clearInterval(_pollInterval);
  pollStatus(sessionId, authToken);
}

function onPaymentFailure(err) {
  clearInterval(_pollInterval);
  showError((err && err.message) || 'Payment failed. Please try again.');
}

function navigateToConfirmed(bookingId) {
  // Replace with your navigation logic (React Navigation, Vue Router, etc.)
  window.location.href = `/booking/confirmed?id=${bookingId}`;
}

function showError(msg) {
  const el = document.getElementById('crypto-status-msg');
  el.textContent = msg;
  el.classList.remove('hidden');
}
```

---

## 5. React Native / Expo (WebView approach)

If you are using React Native and the KuvarPay SDK is web-only, embed it in a
`WebView` with the inline checkout HTML injected:

```jsx
import { WebView } from 'react-native-webview';

function KuvarPayWebView({ sessionId, authToken, publishableKey, businessId, onSuccess, onFailed }) {
  const html = `
    <!DOCTYPE html>
    <html>
    <head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <script
        src="https://pay.kuvarpay.com/kuvarpay-sdk.js"
        data-api-key="${publishableKey}"
        data-business-id="${businessId}"
        data-base-url="https://pay.kuvarpay.com"
        data-inline-checkout="true"
      ></script>
    </head>
    <body style="margin:0;padding:0;">
      <div id="kuvarpay-container"></div>
      <script>
        window.addEventListener('load', function () {
          KuvarPay.openPayment(
            { sessionId: '${sessionId}', authToken: '${authToken}' },
            {
              onSuccess: function (sid) {
                window.ReactNativeWebView.postMessage(JSON.stringify({ type: 'success', sessionId: sid }));
              },
              onCancel: function () {
                window.ReactNativeWebView.postMessage(JSON.stringify({ type: 'cancel' }));
              },
              onError: function (err) {
                window.ReactNativeWebView.postMessage(JSON.stringify({ type: 'error', error: err }));
              },
            },
            { theme: 'light' }
          );
        });
      </script>
    </body>
    </html>
  `;

  return (
    <WebView
      originWhitelist={['*']}
      source={{ html }}
      onMessage={(event) => {
        const msg = JSON.parse(event.nativeEvent.data);
        if (msg.type === 'success') onSuccess();
        else onFailed(msg.error);
      }}
      style={{ flex: 1 }}
    />
  );
}
```

After mounting, still **poll `/status/{session_id}`** from your React Native code until
you get `completed` — the `onSuccess` callback is client-side only.

---

## 6. Checkout Screen Integration

The existing checkout has a list of payment methods. Add the crypto option alongside
M-Pesa and card:

```
┌─────────────────────────────────────┐
│  Select Payment Method              │
│                                     │
│  ○  M-Pesa   (+254 7XX XXX XXX)     │
│  ○  Card     (Visa/Mastercard)      │
│  ●  Crypto   (KuvarPay)  ← new      │
│                                     │
│  [Confirm & Pay  KES 4,500]         │
└─────────────────────────────────────┘
```

When "Crypto" is selected, call `initKuvarPayCheckout(bookingId, token)` instead of
the existing payment endpoints. The inline widget appears below the method list in
`#kuvarpay-container`.

---

## 7. Webhook URL to Register in KuvarPay Dashboard

```
https://api.ardena.xyz/api/v1/kuvarpay/webhook
```

**Events to enable:**
- `checkout_session.completed`
- `checkout_session.failed`
- `checkout_session.expired`
- `checkout_session.payment_received`
- `webhook.test` (for testing)

After saving the webhook, copy the **Webhook Secret** into your `.env`:
```
KUVARPAY_WEBHOOK_SECRET=whs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## 8. Environment Variables (server `.env`)

```env
KUVARPAY_SECRET_KEY=sk_live_...          # Backend only — never expose
KUVARPAY_PUBLISHABLE_KEY=pk_live_...     # Returned to frontend in session response
KUVARPAY_BUSINESS_ID=biz_...            # Returned to frontend in session response
KUVARPAY_WEBHOOK_SECRET=whs_...         # Used to verify incoming webhooks
```

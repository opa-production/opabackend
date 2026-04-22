# Host App — Paystack Card Payment for Subscriptions

This document covers how the host app should implement card payments for starter and premium subscriptions using Paystack's hosted checkout page.

**No card details are collected or stored by us.** The host enters their card on Paystack's secure hosted page and is redirected back to the host app when done.

---

## Prerequisites (Server Configuration)

The server team must set these environment variables before card payments work:

```env
PAYSTACK_SECRET_KEY=sk_live_xxxxxxxxxxxxxxxx   # From Paystack dashboard
PAYSTACK_CALLBACK_BASE_URL=https://api.ardena.xyz/api/v1
HOST_FRONTEND_URL=ardenahost://                 # Your host app deep-link scheme
```

The `HOST_FRONTEND_URL` is where Paystack redirects the host after payment. It must match the custom URL scheme registered in the host app (e.g. `ardenahost://`).

---

## Endpoints

### 1. Start Card Checkout

```
POST /api/v1/host/subscription/checkout/card
Authorization: Bearer <host_token>
Content-Type: application/json
```

**Request body:**

```json
{
  "plan": "starter"
}
```

`plan` must be `"starter"` or `"premium"`.

**Success response (200):**

```json
{
  "success": true,
  "message": "Open the authorization_url to complete payment...",
  "plan": "starter",
  "amount_kes": 3500,
  "paystack_reference": "H-SUB-CARD-42-a1b2c3d4",
  "authorization_url": "https://checkout.paystack.com/xxxxxxxxxxxxxx"
}
```

**Save `paystack_reference`** — you need it to poll payment status.

**Error responses:**

| Status | Detail | Cause |
|--------|--------|-------|
| 400 | `"A card checkout is already in progress."` | Previous checkout not yet completed |
| 400 | Invalid plan / price | Misconfigured plan |
| 503 | Card payment not configured | Server missing `PAYSTACK_CALLBACK_BASE_URL` |
| 502 | Paystack error message | Paystack API unreachable or rejected |

---

### 2. Poll Card Payment Status

```
GET /api/v1/host/subscription/card-status?paystack_reference=<ref>
Authorization: Bearer <host_token>
```

**Response:**

```json
{
  "checkout_request_id": null,
  "external_reference": "H-SUB-CARD-42-a1b2c3d4",
  "plan": "starter",
  "amount_kes": 3500.0,
  "status": "completed",
  "message": null,
  "mpesa_receipt_number": null,
  "paystack_reference": "H-SUB-CARD-42-a1b2c3d4",
  "paystack_card_last4": "4081",
  "paystack_card_brand": "visa"
}
```

**Status values:**

| Status | Meaning |
|--------|---------|
| `pending` | Host is on the Paystack page or webhook not yet received |
| `completed` | Payment confirmed — subscription is now active |
| `failed` | Card declined, abandoned, or payment failed |

Poll every **5 seconds** while status is `pending`. Stop on `completed` or `failed`, then refresh `/host/subscription/me` to update the plan UI.

---

## Complete Flow

```
1. Host taps "Pay with Card" for starter or premium
   ↓
2. POST /host/subscription/checkout/card  { plan: "starter" }
   ← { authorization_url, paystack_reference }
   ↓
3. Open authorization_url in browser or in-app WebView
   ↓
4. Host enters card details on Paystack's secure page
   ↓
5. Paystack redirects to GET /paystack/host-callback?reference=...
   → Server redirects host to ardenahost://subscription/result?paystack_reference=...
   ↓
6. Host app handles the deep link, extracts paystack_reference
   ↓
7. Poll GET /host/subscription/card-status?paystack_reference=<ref> every 5 seconds
   ├─ completed → show success, refresh /host/subscription/me
   └─ failed    → show error, allow retry
```

---

## React Native Implementation

### Services

```typescript
// services/subscription.ts

export async function startCardCheckout(plan: 'starter' | 'premium') {
  const res = await api.post('/host/subscription/checkout/card', { plan });
  return res.data as {
    paystack_reference: string;
    authorization_url: string;
    amount_kes: number;
    plan: string;
  };
}

export async function pollCardStatus(paystackReference: string) {
  const res = await api.get('/host/subscription/card-status', {
    params: { paystack_reference: paystackReference },
  });
  return res.data as {
    status: 'pending' | 'completed' | 'failed';
    paystack_card_last4: string | null;
    paystack_card_brand: string | null;
    message: string | null;
  };
}
```

### Opening the Paystack Page

Use `expo-web-browser` or `Linking` to open the URL. `expo-web-browser` is preferred because it allows the deep-link redirect to work reliably on both iOS and Android.

```typescript
import * as WebBrowser from 'expo-web-browser';
import { Linking } from 'react-native';

async function handleCardCheckout(plan: 'starter' | 'premium') {
  const checkout = await startCardCheckout(plan);
  // Store reference before opening browser — used when app resumes
  await AsyncStorage.setItem('pending_paystack_ref', checkout.paystack_reference);

  await WebBrowser.openBrowserAsync(checkout.authorization_url);
  // After browser closes (redirect or user dismisses), start polling
}
```

### Handling the Deep Link Redirect

Register `ardenahost://` as a custom URL scheme in your app. When Paystack redirects after payment:

```
ardenahost://subscription/result?paystack_reference=H-SUB-CARD-42-a1b2c3d4
```

Handle it in your app's linking config:

```typescript
// app/_layout.tsx or App.tsx
import * as Linking from 'expo-linking';

const linking = {
  prefixes: ['ardenahost://'],
  config: {
    screens: {
      SubscriptionResult: 'subscription/result',
    },
  },
};
```

```typescript
// screens/SubscriptionResultScreen.tsx
import { useLocalSearchParams } from 'expo-router';

export default function SubscriptionResultScreen() {
  const { paystack_reference } = useLocalSearchParams<{ paystack_reference: string }>();
  const [status, setStatus] = useState<'pending' | 'completed' | 'failed'>('pending');

  useEffect(() => {
    if (!paystack_reference) return;
    const interval = setInterval(async () => {
      const result = await pollCardStatus(paystack_reference);
      setStatus(result.status);
      if (result.status !== 'pending') {
        clearInterval(interval);
        if (result.status === 'completed') {
          // Refresh subscription state
          await refreshSubscription();
        }
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [paystack_reference]);

  if (status === 'pending') return <ActivityIndicator />;
  if (status === 'completed') return <SuccessScreen />;
  return <ErrorScreen onRetry={() => navigation.navigate('Subscription')} />;
}
```

### Resuming a Pending Checkout on App Open

If the host closes and reopens the app while a card checkout is still in progress, resume polling automatically:

```typescript
// On subscription screen mount
useEffect(() => {
  async function checkPendingCardCheckout() {
    const sub = await getMySubscription();
    if (sub.pending_paystack_reference) {
      // A card checkout was started — resume polling
      navigation.navigate('SubscriptionResult', {
        paystack_reference: sub.pending_paystack_reference,
      });
    }
  }
  checkPendingCardCheckout();
}, []);
```

The `/host/subscription/me` response includes `pending_paystack_reference` when a card checkout is in progress.

---

## Subscription Screen — Which Payment to Show

Show both M-Pesa and card options to the host. Let them choose:

```typescript
const PaymentMethodSelector = ({ plan, onSuccess }) => {
  const [method, setMethod] = useState<'mpesa' | 'card'>('mpesa');

  return (
    <View>
      <Text>Choose payment method:</Text>
      <TouchableOpacity onPress={() => setMethod('mpesa')}>
        <Text style={method === 'mpesa' ? styles.selected : {}}>M-Pesa</Text>
      </TouchableOpacity>
      <TouchableOpacity onPress={() => setMethod('card')}>
        <Text style={method === 'card' ? styles.selected : {}}>Card (Visa / Mastercard)</Text>
      </TouchableOpacity>

      {method === 'mpesa' && <MpesaCheckoutForm plan={plan} onSuccess={onSuccess} />}
      {method === 'card'  && <CardCheckoutButton plan={plan} onSuccess={onSuccess} />}
    </View>
  );
};
```

---

## TypeScript Types

```typescript
interface CardCheckoutResponse {
  success: boolean;
  message: string;
  plan: string;
  amount_kes: number;
  paystack_reference: string;
  authorization_url: string;
}

interface CardStatusResponse {
  checkout_request_id: null;
  external_reference: string;
  plan: string;
  amount_kes: number;
  status: 'pending' | 'completed' | 'failed';
  message: string | null;
  mpesa_receipt_number: null;
  paystack_reference: string | null;
  paystack_card_last4: string | null;
  paystack_card_brand: string | null;
}

// Updated SubscriptionMe — now includes pending_paystack_reference
interface SubscriptionMe {
  plan: 'free' | 'starter' | 'premium';
  expires_at: string | null;
  is_paid_active: boolean;
  is_trial: boolean;
  trial_available: boolean;
  days_remaining: number | null;
  has_pending_checkout: boolean;        // M-Pesa pending
  pending_plan: string | null;
  pending_checkout_request_id: string | null;
  pending_seconds_remaining: number | null;
  stk_pending_window_seconds: number;
  pending_paystack_reference: string | null;  // Card payment pending
}
```

---

## Server Deployment Checklist

Before enabling card payments on production:

1. Add `HOST_FRONTEND_URL=ardenahost://` to `.env` on the server
2. Make sure `PAYSTACK_SECRET_KEY` and `PAYSTACK_CALLBACK_BASE_URL` are set
3. Run `python migrate.py` to apply migration `m009_host_sub_paystack`
4. In the Paystack dashboard → **Settings → Webhooks**, set the webhook URL to:
   ```
   https://api.ardena.xyz/api/v1/paystack/webhook
   ```
   This is the **same webhook** as client payments — the server dispatches by reference prefix.
5. Restart the service

---

## How Card vs M-Pesa Subscriptions Differ

| | M-Pesa (STK Push) | Card (Paystack) |
|---|---|---|
| Endpoint | `POST /host/subscription/checkout` | `POST /host/subscription/checkout/card` |
| Phone needed | Yes | No |
| Host action | Approve prompt on phone | Enter card on browser page |
| Status poll | `GET /host/subscription/payment-status` | `GET /host/subscription/card-status` |
| Timeout | 90 seconds (configurable) | No server-side timeout |
| Receipt | M-Pesa receipt number | Card last4 + brand |
| Webhook | Payhero → `/mpesa/callback` | Paystack → `/paystack/webhook` |

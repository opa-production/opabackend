# Host App — Subscription & Plan Integration Guide

This document covers everything the host mobile app needs to implement subscription plan gating, the free trial flow, and the "Add Car" button visibility logic.

---

## Overview of Plans

| Plan     | Code       | Cost           | Duration |
|----------|------------|----------------|----------|
| Free     | `free`     | KES 0          | Ongoing  |
| Starter  | `starter`  | KES 3,500      | 30 days  |
| Premium  | `premium`  | KES 6,500      | 30 days  |

A host always has one active plan state. Possible states:

| State                  | What it means                                      |
|------------------------|----------------------------------------------------|
| Free (default)         | No subscription, no trial used                     |
| Trial active           | On starter plan via free trial, still within dates |
| Trial expired          | Trial was used and has lapsed — back to free       |
| Paid active            | Paid starter or premium, within expiry dates       |
| Paid expired           | Paid plan lapsed — back to free                   |

---

## Base URL

```
https://api.yourapp.com/api/v1
```

All subscription endpoints require the host JWT token in the `Authorization: Bearer <token>` header.

---

## Endpoints

### 1. Get Current Subscription Status

```
GET /host/subscription/me
```

**Response:**

```json
{
  "plan": "starter",
  "expires_at": "2026-05-21T10:30:00Z",
  "is_paid_active": false,
  "is_trial": true,
  "trial_available": false,
  "days_remaining": 29,
  "has_pending_checkout": false,
  "pending_plan": null,
  "pending_checkout_request_id": null,
  "pending_seconds_remaining": null,
  "stk_pending_window_seconds": 90
}
```

**Field reference:**

| Field                       | Type          | Description                                                              |
|-----------------------------|---------------|--------------------------------------------------------------------------|
| `plan`                      | string        | Current plan code: `"free"`, `"starter"`, or `"premium"`                |
| `expires_at`                | datetime/null | When the current paid/trial plan expires. `null` on free plan.           |
| `is_paid_active`            | bool          | `true` if a paid (non-trial) subscription is currently active            |
| `is_trial`                  | bool          | `true` if the host is currently within a free trial period               |
| `trial_available`           | bool          | `true` if the host has never used a trial and is on the free plan        |
| `days_remaining`            | int/null      | Days left on a paid plan. `null` if on free or trial.                    |
| `has_pending_checkout`      | bool          | `true` if an M-Pesa STK push is currently awaiting PIN                   |
| `pending_plan`              | string/null   | Plan being purchased in the pending checkout                             |
| `pending_checkout_request_id` | string/null | Use this to poll payment status                                          |
| `pending_seconds_remaining` | int/null      | Seconds before the pending checkout auto-expires                         |
| `stk_pending_window_seconds`| int           | Total STK window duration (default 90 seconds)                           |

**Cache:** This response is cached per host for 120 seconds. After activating a trial or completing a payment the cache is invalidated automatically — re-fetch immediately after those actions.

---

### 2. List Subscription Plans

```
GET /host/subscription/plans
```

No authentication required.

**Response:**

```json
{
  "plans": [
    {
      "code": "free",
      "name": "Free",
      "description": "Default plan — list and operate with standard limits.",
      "price_kes": 0,
      "duration_days": 0,
      "features": ["No monthly fee", "Standard host features"]
    },
    {
      "code": "starter",
      "name": "Starter",
      "description": "Paid starter tier for growing hosts.",
      "price_kes": 3500,
      "duration_days": 30,
      "features": ["KES 3,500 per 30 days", "Unlock starter benefits in app"]
    },
    {
      "code": "premium",
      "name": "Premium",
      "description": "Full premium host subscription.",
      "price_kes": 6500,
      "duration_days": 30,
      "features": ["KES 6,500 per 30 days", "Unlock premium benefits in app"]
    }
  ]
}
```

---

### 3. Activate Free Trial

```
POST /host/subscription/trial
```

No request body needed.

**Success response (200):**

```json
{
  "success": true,
  "message": "Your 30-day free trial of the Starter plan is now active. Enjoy!",
  "plan": "starter",
  "expires_at": "2026-05-21T10:30:00Z",
  "days_granted": 30
}
```

**Error responses:**

| Status | Detail                                             | Cause                                       |
|--------|----------------------------------------------------|---------------------------------------------|
| 400    | `"Free trial already used."`                       | Host already activated a trial before       |
| 400    | `"Free trial is only available on the free plan."` | Host is on a paid or active trial plan      |
| 404    | `"Host not found"`                                 | Auth issue — should not normally happen     |

After a successful trial activation, re-fetch `/host/subscription/me` immediately to update the UI.

---

### 4. Start Paid Subscription (M-Pesa STK Push)

```
POST /host/subscription/checkout
```

**Request body:**

```json
{
  "plan": "starter",
  "phone_number": "0712345678"
}
```

- `plan`: `"starter"` or `"premium"`
- `phone_number`: Kenyan number in any common format (`07...`, `+2547...`, `2547...`)

**Success response (200):**

```json
{
  "message": "M-Pesa STK Push sent. Approve on your phone to activate your subscription.",
  "plan": "starter",
  "amount_kes": 3500,
  "checkout_request_id": "ws_CO_...",
  "external_reference": "H-SUB-42",
  "stk_pending_window_seconds": 90
}
```

Save `checkout_request_id` — you need it to poll payment status.

**Error responses:**

| Status | Detail                                              | Cause                                |
|--------|-----------------------------------------------------|--------------------------------------|
| 400    | `"A subscription payment is already in progress…"` | Existing pending STK, wait or retry  |
| 400    | `"Invalid plan price…"`                             | Server env misconfiguration          |
| 400    | M-Pesa error message                                | STK push failed at Payhero           |

---

### 5. Poll Payment Status

```
GET /host/subscription/payment-status?checkout_request_id=<id>
```

**Response:**

```json
{
  "checkout_request_id": "ws_CO_...",
  "external_reference": "H-SUB-42",
  "plan": "starter",
  "amount_kes": 3500,
  "status": "paid",
  "message": null,
  "mpesa_receipt_number": "QHX1234ABC"
}
```

**Status values:**

| Status      | Meaning                                                  |
|-------------|----------------------------------------------------------|
| `pending`   | Awaiting PIN entry or M-Pesa confirmation                |
| `paid`      | Payment successful — subscription is now active          |
| `failed`    | Payment rejected or cancelled                            |
| `expired`   | STK window elapsed without PIN entry — can retry         |

Poll every 5 seconds while status is `pending`. Stop polling on `paid`, `failed`, or `expired`.

---

## Free Trial Flow (Host App)

### Logic

Show the "Start Free Trial" option only when `trial_available === true` from `/me`.

```
trial_available = (host has NEVER used trial) AND (current plan === "free")
```

Once a trial is used, `trial_available` is permanently `false` for that host.

### Implementation Steps

1. On app load / subscription screen open, call `GET /host/subscription/me`
2. If `trial_available === true`, show a "Try Starter Free for 30 Days" button
3. On button tap, call `POST /host/subscription/trial`
4. On success: show a success message using `response.message`, then re-fetch `/me`
5. On 400 error: display `error.detail` to the user

### React Native Example

```typescript
// services/subscription.ts
import api from './api'; // your axios/fetch wrapper

export async function getMySubscription() {
  const res = await api.get('/host/subscription/me');
  return res.data;
}

export async function activateFreeTrial() {
  const res = await api.post('/host/subscription/trial');
  return res.data;
}

export async function startCheckout(plan: 'starter' | 'premium', phone: string) {
  const res = await api.post('/host/subscription/checkout', {
    plan,
    phone_number: phone,
  });
  return res.data;
}

export async function pollPaymentStatus(checkoutRequestId: string) {
  const res = await api.get('/host/subscription/payment-status', {
    params: { checkout_request_id: checkoutRequestId },
  });
  return res.data;
}
```

```typescript
// SubscriptionScreen.tsx (simplified)
const [sub, setSub] = useState(null);

useEffect(() => {
  getMySubscription().then(setSub);
}, []);

const handleActivateTrial = async () => {
  try {
    const result = await activateFreeTrial();
    Alert.alert('Trial Activated', result.message);
    const updated = await getMySubscription();
    setSub(updated);
  } catch (err) {
    Alert.alert('Error', err.response?.data?.detail ?? 'Could not activate trial');
  }
};

// Render
{sub?.trial_available && (
  <TouchableOpacity onPress={handleActivateTrial}>
    <Text>Try Starter Free for 30 Days</Text>
  </TouchableOpacity>
)}
```

---

## "Add Car" Button Visibility

The "Add Car" button (and any other feature that requires a paid or trial plan) should be shown based on the host's current plan state from `/me`.

### Rules

| Condition                               | Show "Add Car"? |
|-----------------------------------------|-----------------|
| `is_paid_active === true`               | YES             |
| `is_trial === true`                     | YES             |
| `plan === "free"` and neither above     | NO              |

A single helper function covers all cases:

```typescript
// utils/subscription.ts
export function hostHasActiveSubscription(sub: SubscriptionMe): boolean {
  return sub.is_paid_active || sub.is_trial;
}
```

### Usage in component

```typescript
import { hostHasActiveSubscription } from '../utils/subscription';

const MyGarage = () => {
  const [sub, setSub] = useState(null);

  useEffect(() => {
    getMySubscription().then(setSub);
  }, []);

  const canAddCar = sub ? hostHasActiveSubscription(sub) : false;

  return (
    <View>
      <CarList />
      {canAddCar ? (
        <TouchableOpacity onPress={navigateToAddCar}>
          <Text>+ Add Car</Text>
        </TouchableOpacity>
      ) : (
        <TouchableOpacity onPress={navigateToSubscription}>
          <Text>Upgrade to Add Cars</Text>
        </TouchableOpacity>
      )}
    </View>
  );
};
```

When the button is hidden, show a prompt such as "Upgrade to add more cars" that links to the subscription screen so the host can activate a trial or purchase a plan.

---

## Complete Subscription Screen Flow

```
Load /me
  ├─ is_paid_active = true  →  Show "Active [Plan] — X days remaining"
  ├─ is_trial = true        →  Show "Free Trial Active — expires [date]"
  │                              Show "Upgrade to Paid" option
  ├─ trial_available = true →  Show "Start Free Trial" + "Buy a Plan" options
  └─ (free, no trial left)  →  Show "Buy a Plan" options only

"Buy a Plan" flow:
  1. User picks starter or premium
  2. User enters M-Pesa phone number
  3. POST /host/subscription/checkout
  4. Show "Check your phone for M-Pesa prompt" + spinner
  5. Poll GET /host/subscription/payment-status every 5 seconds
     ├─ paid    → success screen, refresh /me
     ├─ failed  → show error, allow retry
     └─ expired → show "Timed out — try again", allow retry
```

---

## TypeScript Types

```typescript
interface SubscriptionMe {
  plan: 'free' | 'starter' | 'premium';
  expires_at: string | null;           // ISO 8601 UTC
  is_paid_active: boolean;
  is_trial: boolean;
  trial_available: boolean;
  days_remaining: number | null;
  has_pending_checkout: boolean;
  pending_plan: string | null;
  pending_checkout_request_id: string | null;
  pending_seconds_remaining: number | null;
  stk_pending_window_seconds: number;
}

interface TrialActivateResponse {
  success: boolean;
  message: string;
  plan: string;
  expires_at: string;                  // ISO 8601 UTC
  days_granted: number;
}

interface CheckoutResponse {
  message: string;
  plan: string;
  amount_kes: number;
  checkout_request_id: string;
  external_reference: string;
  stk_pending_window_seconds: number;
}

interface PaymentStatusResponse {
  checkout_request_id: string;
  external_reference: string;
  plan: string;
  amount_kes: number;
  status: 'pending' | 'paid' | 'failed' | 'expired';
  message: string | null;
  mpesa_receipt_number: string | null;
}
```

---

## Edge Cases to Handle

- **Pending checkout on app open:** If `has_pending_checkout === true` and `pending_checkout_request_id` is set, resume polling immediately — the user may have left the app during the M-Pesa prompt.
- **Expired trial:** `is_trial === false`, `trial_available === false`, `plan === "free"` — show only paid plan options.
- **Plan expires while app is open:** Cache TTL is 120 seconds. If `days_remaining === 0`, nudge the user to renew and re-fetch `/me` to confirm expiry.
- **Network error during trial activation:** Retry is safe — the endpoint is idempotent in that a second call will return a 400 (already used), which you can distinguish from a network failure.

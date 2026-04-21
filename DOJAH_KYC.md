# Dojah KYC — Mobile UI Implementation Guide

## Overview

KYC is a two-screen flow followed by a native Dojah widget:

| Step | Screen | API call |
|------|--------|----------|
| 1 | KYC Details screen | `POST /api/v1/client/kyc/lookup` |
| 2 | Dojah widget (document + liveness) | `POST /api/v1/client/kyc/initialize` → launch widget |
| 3 | Status / result screen | `GET /api/v1/client/kyc/status` |

---

## Step 1 — KYC Details Screen

### What the screen does
The user selects their ID type and enters their ID number. On submit, the backend
looks up their government record and returns their official name, DOB, and gender,
which are used to prefill the rest of the form.

### API call

```http
POST /api/v1/client/kyc/lookup
Authorization: Bearer <client_token>
Content-Type: application/json

{
  "id_type": "NATIONAL_ID",   // "NATIONAL_ID" | "PASSPORT" | "DRIVERS_LICENSE"
  "id_number": "12345678",
  "country": "KE"
}
```

**Success response (200):**
```json
{
  "verified_name": "John James Doe",
  "date_of_birth": "1990-01-15",
  "gender": "male",
  "id_number": "12345678",
  "id_type": "NATIONAL_ID",
  "country": "KE"
}
```

**Error responses:**
- `400` — ID not found or unsupported id_type
- `503` — Dojah service misconfigured (backend issue)

### UI behaviour

1. Show a dropdown for ID type: **National ID / Passport / Driver's License**
2. Show a text field for the ID number
3. On "Verify" tap — call the lookup endpoint
4. On success — prefill the name, DOB, and gender fields below the ID fields (read-only, labelled "Verified by government")
5. The user reviews the prefilled details. Show a "Continue" button to proceed to Step 2.
6. The profile is automatically updated by the backend — no extra call needed.

**Note:** The `verified_name` from this response will also update `client.full_name` and
show up in `GET /api/v1/client/profile`.

---

## Step 2 — Document Scan + Liveness (Dojah Widget)

### What happens
Your screen calls the initialize endpoint, which returns the widget credentials.
You then launch the Dojah React Native SDK. The widget handles document photo,
liveness, and face match entirely — no custom camera code needed.

### API call

```http
POST /api/v1/client/kyc/initialize
Authorization: Bearer <client_token>
```

**Success response (201):**
```json
{
  "reference_id": "550e8400-e29b-41d4-a716-446655440000",
  "app_id": "your-dojah-app-id",
  "p_key": "your-dojah-public-key",
  "widget_id": "your-dojah-widget-id"
}
```

### Launching the Dojah widget

Install the Dojah React Native SDK:
```bash
npm install @dojah/react-native-widget
# or
yarn add @dojah/react-native-widget
```

```jsx
import DoJah from '@dojah/react-native-widget';

function KycVerificationScreen({ navigation }) {
  const [widgetCreds, setWidgetCreds] = useState(null);
  const [loading, setLoading] = useState(false);

  const initializeWidget = async () => {
    setLoading(true);
    try {
      const res = await api.post('/api/v1/client/kyc/initialize');
      setWidgetCreds(res.data);
    } catch (err) {
      Alert.alert('Error', 'Could not start verification. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleSuccess = async (data) => {
    // Widget completed — poll status until approved/declined
    navigation.replace('KycStatus');
  };

  const handleError = (error) => {
    console.error('Dojah widget error:', error);
    Alert.alert('Verification failed', 'Please try again.');
  };

  if (!widgetCreds) {
    return (
      <Button title="Start Verification" onPress={initializeWidget} loading={loading} />
    );
  }

  return (
    <DoJah
      appId={widgetCreds.app_id}
      pKey={widgetCreds.p_key}
      config={{
        widget_id: widgetCreds.widget_id,
        reference_id: widgetCreds.reference_id,
        // Optional metadata sent through to Dojah dashboard
        metadata: { platform: 'mobile' },
      }}
      onSuccess={handleSuccess}
      onError={handleError}
      onClose={() => navigation.goBack()}
    />
  );
}
```

**Note:** The widget is a full-screen experience — it handles camera permissions,
liveness instructions, and retries internally.

---

## Step 3 — KYC Status Screen

Poll this endpoint after the widget `onSuccess` fires. Dojah sends the decision to
your backend webhook asynchronously, so the status may still be `"pending"` for a
few seconds.

### API call

```http
GET /api/v1/client/kyc/status
Authorization: Bearer <client_token>
```

**Response:**
```json
{
  "user_id": 7,
  "reference_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "approved",
  "document_type": "national_id",
  "verified_name": "John James Doe",
  "verified_dob": "1990-01-15",
  "face_match_score": 98.5,
  "decision_reason": null,
  "verified_at": "2026-04-18T06:02:44Z"
}
```

**Status values:**
| Value | Meaning |
|-------|---------|
| `not_started` | No KYC attempt yet |
| `pending` | Widget launched, awaiting Dojah decision |
| `approved` | Fully verified ✓ |
| `declined` | Verification failed — show `decision_reason` |

### Polling pattern

```jsx
function KycStatusScreen({ navigation }) {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    const poll = setInterval(async () => {
      const res = await api.get('/api/v1/client/kyc/status');
      setStatus(res.data);
      if (res.data.status === 'approved' || res.data.status === 'declined') {
        clearInterval(poll);
      }
    }, 3000); // poll every 3 seconds

    return () => clearInterval(poll);
  }, []);

  if (!status || status.status === 'pending') {
    return <ActivityIndicator />;
  }

  if (status.status === 'approved') {
    return <SuccessScreen name={status.verified_name} score={status.face_match_score} />;
  }

  return <FailedScreen reason={status.decision_reason} />;
}
```

---

## Profile Prefill — What Updates Automatically

When Step 1 (lookup) succeeds, the backend updates the client record immediately:

| Profile field | Updated from |
|---------------|-------------|
| `full_name` | Government verified name |
| `date_of_birth` | Government DOB |
| `gender` | Government gender |
| `id_number` | The ID number the user entered |

When the Dojah webhook fires (Step 2 complete, status `approved`):

| Profile field | Updated from |
|---------------|-------------|
| `full_name` | Government verified name (webhook data) |
| `date_of_birth` | Government DOB (only if not already set) |
| `gender` | Government gender (only if not already set) |

This means the profile update screen (`PUT /api/v1/client/profile`) will already have
these fields filled when the user navigates to it after KYC.

---

## Host App

The host KYC flow is identical. Replace `/client/` with `/host/` in all URLs and use
the host JWT token. Note: the Host model does not have a `date_of_birth` column, so
the `date_of_birth` field in the lookup response is returned for display only and is
not stored on the host profile.

---

## Backend Environment Variables Required

Add these to your `.env` / server environment:

```env
DOJAH_APP_ID=your_dojah_app_id
DOJAH_SECRET_KEY=your_dojah_secret_key
DOJAH_PUBLIC_KEY=your_dojah_public_key
DOJAH_WIDGET_ID=your_dojah_widget_id
DOJAH_WEBHOOK_SECRET=your_dojah_webhook_secret
```

Set the webhook URL in your Dojah dashboard to:
```
https://api.ardena.xyz/api/v1/dojah/webhook
```

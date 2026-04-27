# Secondary Contact Verification — UI Implementation Guide

## Overview

The client must verify a secondary contact (e.g. next of kin) in two steps:
1. Enter the secondary contact's **phone number** and **full names** (as the client knows them).
2. Enter the secondary contact's **KRA PIN** — the backend calls Gava Connect (KRA), compares the returned registered name with the entered names, and marks the contact as **verified** or **failed**.

> **KRA PIN format:** Starts with `A` or `P`, followed by 9 digits, ends with any letter. Example: `A012345678B`

---

## API Base URL

```
https://api.ardena.xyz/api/v1
```

All endpoints require the client's JWT in the `Authorization: Bearer <token>` header.

---

## Step 1 — Save Phone & Names

**Endpoint:** `POST /client/secondary-contact/info`

**Request body:**
```json
{
  "phone": "0712345678",
  "names": "Jane Achieng Otieno"
}
```

**Success response (200):**
```json
{
  "status": "not_started",
  "phone": "0712345678",
  "names": "Jane Achieng Otieno",
  "official_name": null,
  "kra_pin": null,
  "matched_names": null,
  "verified_at": null,
  "message": "Secondary contact info saved. Please proceed to ID verification."
}
```

**UI action:** On success, navigate to the KRA PIN entry screen (Step 2).

---

## Step 2 — Verify KRA PIN

**Endpoint:** `POST /client/secondary-contact/verify`

**Request body:**
```json
{
  "kra_pin": "A012345678B"
}
```

**Success — verified (200):**
```json
{
  "status": "verified",
  "phone": "0712345678",
  "names": "Jane Achieng Otieno",
  "official_name": "JANE ACHIENG OTIENO",
  "kra_pin": "A012345678B",
  "matched_names": 3,
  "verified_at": "2026-04-27T10:00:00Z",
  "message": "Secondary contact verified successfully."
}
```

**Failure — name mismatch (200):**
```json
{
  "status": "failed",
  "phone": "0712345678",
  "names": "Jane Achieng Otieno",
  "official_name": "JOHN KAMAU MWANGI",
  "kra_pin": "A098765432Z",
  "matched_names": 0,
  "verified_at": null,
  "message": "Name verification failed — only 0 name(s) matched the official record (2 required). Please check the names and try again."
}
```

**Error — KRA PIN not found / inactive (422):**
```json
{
  "detail": "Gava Connect: KRA PIN not found."
}
```

**Error — info not saved yet (400):**
```json
{
  "detail": "Please save secondary contact info (phone + names) first."
}
```

### UI logic on response:
- `status === "verified"` → show success screen, done
- `status === "failed"` → show `message` and offer two options:
  - **Try again** — go back to Step 1 (re-enter names, then re-enter KRA PIN)
  - **Skip for now** — dismiss (if verification is optional)
- `422` error → show the `detail` message (PIN not found), let user re-enter KRA PIN

---

## Check Current Status (optional)

Use this on screen load to resume or skip already-completed steps.

**Endpoint:** `GET /client/secondary-contact/status`

**Response:** Same shape as above.

| `status` value | Meaning |
|---|---|
| `not_started` | Client has not started yet |
| `pending` | KRA PIN submitted, lookup in progress (transient — resolves in the same request) |
| `verified` | Successfully verified |
| `failed` | Name match failed — client may retry |

---

## Recommended Screen Flow

```
[Secondary Contact Screen]
        |
        v
[Screen 1: Enter Phone & Names]
  - Phone number input
  - Full names input (as client knows them)
  - "Continue" → POST /client/secondary-contact/info
        |
        v (on success)
[Screen 2: Enter KRA PIN]
  - KRA PIN input  (hint: e.g. A012345678B)
  - "Verify" → POST /client/secondary-contact/verify
        |
        +--- status: verified --→ [Success Screen ✓]
        |
        +--- status: failed ---→ [Failed Screen]
                                    show message from API
                                    [Try Again] → back to Screen 1
```

---

## Re-entry Behaviour

Calling `POST /client/secondary-contact/info` **resets** all prior verification data. If the user goes back and enters different names, the previous `verified` status is cleared and they must re-enter the KRA PIN.

---

## Testing Checklist

- [ ] Enter valid phone + names → `status: not_started`, navigate to KRA PIN screen
- [ ] Enter matching KRA PIN → `status: verified`, show success
- [ ] Enter KRA PIN whose registered name doesn't match entered names → `status: failed`, show message with retry
- [ ] Enter non-existent KRA PIN → 422 error with detail message
- [ ] Load status screen when already verified → skip verification screens
- [ ] Go back and re-enter info → status resets to `not_started`, must re-verify

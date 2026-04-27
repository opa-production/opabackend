# Secondary Contact Verification — UI Implementation Guide

## Overview

The client verifies a secondary contact (e.g. next of kin) by sending a one-time SMS code to the secondary contact's phone. The secondary contact reads the code back to the client, who enters it in the app.

**OTP:** 5 digits, expires in 2 minutes.

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
  "verified_at": null,
  "message": "Info saved. Tap 'Send OTP' to verify the number."
}
```

**UI action:** On success navigate to OTP screen. Show the phone number so the client can confirm it before sending.

---

## Step 2 — Send OTP

**Endpoint:** `POST /client/secondary-contact/send-otp`

No request body — uses the phone saved in Step 1.

**Success response (200):**
```json
{
  "status": "otp_sent",
  "phone": "0712345678",
  "names": "Jane Achieng Otieno",
  "verified_at": null,
  "message": "OTP sent. Ask your secondary contact to share the code. Valid for 2 minutes."
}
```

**UI action:** Show a 5-digit OTP input field and a 2-minute countdown timer. Show a "Resend OTP" button that re-calls this endpoint (enabled after timer expires).

---

## Step 3 — Verify OTP

**Endpoint:** `POST /client/secondary-contact/verify`

**Request body:**
```json
{
  "otp": "48271"
}
```

**Success — verified (200):**
```json
{
  "status": "verified",
  "phone": "0712345678",
  "names": "Jane Achieng Otieno",
  "verified_at": "2026-04-27T10:00:00Z",
  "message": "Secondary contact verified successfully."
}
```

**Error — wrong OTP (400):**
```json
{
  "detail": "Incorrect OTP. Please try again."
}
```

**Error — expired OTP (400):**
```json
{
  "detail": "OTP has expired. Please request a new one."
}
```

**Error — no OTP requested (400):**
```json
{
  "detail": "No OTP active. Please request a new one."
}
```

---

## Check Current Status

Use on screen load to skip already-completed steps.

**Endpoint:** `GET /client/secondary-contact/status`

**Response:** Same shape as above.

| `status` | Meaning |
|---|---|
| `not_started` | No info saved yet |
| `otp_sent` | OTP has been sent, waiting for input |
| `verified` | Phone verified ✓ |

---

## Screen Flow

```
[Secondary Contact Entry Screen]
        |
        v
[Screen 1: Enter Phone & Names]
  - Phone number input
  - Full names input
  - "Continue" → POST /client/secondary-contact/info
        |
        v (on success)
[Screen 2: OTP Verification]
  - Shows: "OTP sent to 0712 xxx xxx"
  - "Send OTP" button → POST /client/secondary-contact/send-otp
  - 5-digit OTP input (appears after send-otp succeeds)
  - 2-minute countdown timer
  - "Verify" → POST /client/secondary-contact/verify
  - "Resend OTP" (enabled when timer hits 0)
        |
        +--- status: verified --→ [Success Screen ✓]
        |
        +--- wrong/expired ---→ show error inline, allow retry
```

---

## Re-entry Behaviour

Calling `POST /info` again resets all prior verification. The client must re-send and re-verify the OTP.

---

## Testing Checklist

- [ ] Save phone + names → `status: not_started`, navigate to OTP screen
- [ ] Tap Send OTP → `status: otp_sent`, SMS arrives with 5-digit code
- [ ] Enter correct OTP within 2 minutes → `status: verified`
- [ ] Enter wrong OTP → 400 "Incorrect OTP"
- [ ] Wait 2 minutes then enter OTP → 400 "OTP has expired"
- [ ] Tap Resend OTP after expiry → new OTP sent, timer resets
- [ ] Load screen when already verified → skip to success state
- [ ] Change phone number (re-enter info) → status resets to `not_started`

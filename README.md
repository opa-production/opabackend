# Car Rental Backend API

FastAPI backend for a car rental platform with server-side validation and multi-step car listing workflow.

## Setup

1. Make sure you have [UV](https://docs.astral.sh/) on your system:

2.Setup the uv application:
```bash
  uv sync
```

3. Run the application:
```bash
# For local development (localhost only)
uv run uvicorn app.main:app --reload --port 8001

# For network access (Expo Go, mobile devices, etc.)
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

The API will be available at:
- Local: `http://localhost:8001`
- Network: `http://<your-local-ip>:8001` (e.g., `http://192.168.100.69:8001`)
- API Documentation (Swagger): `http://localhost:8001/docs` or `http://<your-local-ip>:8001/docs`
- Alternative docs (ReDoc): `http://localhost:8001/redoc` or `http://<your-local-ip>:8001/redoc`

**Note for Expo Go/Mobile Development:**
- Make sure your computer and phone are on the same WiFi network
- Use your local IP address (not localhost) in your app
- Run the server with `--host 0.0.0.0 --port 8001` to allow network connections
- Find your local IP with: `ipconfig` (Windows) or `ifconfig` (Mac/Linux)
- **Base URL for app:** `http://192.168.100.69:8001/api/v1`

## Database

The application uses SQLite by default. The database file (`car_rental.db`) will be created automatically on first run.

## API Endpoints

### Host Authentication
- `POST /api/v1/host/auth/register` - Register a new host
- `POST /api/v1/host/auth/login` - Login for hosts
- `POST /api/v1/host/auth/logout` - Logout for hosts
- `GET /api/v1/host/me` - Get current authenticated host information
- `PUT /api/v1/host/profile` - Update host profile (bio, mobile_number, id_number)
- `PUT /api/v1/host/change-password` - Change host password (requires current password verification)

### Client Authentication
- `POST /api/v1/client/auth/register` - Register a new client
- `POST /api/v1/client/auth/login` - Login for clients
- `POST /api/v1/client/auth/logout` - Logout for clients
- `GET /api/v1/client/me` - Get current authenticated client profile
- `PUT /api/v1/client/profile` - Update client profile (bio, fun_fact, mobile_number, id_number)
- `PUT /api/v1/client/change-password` - Change client password (requires current password verification)

### Ardena Pay (Stellar wallet – client, requires authentication)
- `GET /api/v1/client/wallet` - Get current client's Stellar wallet (public key, XLM/USDC balances). On testnet, includes `secret_key` for importing into Freighter/Lobstr.
- `POST /api/v1/client/wallet` - Create a Stellar wallet (funded on testnet, USDC trust line added). Fails if wallet already exists.

A wallet is created automatically when a client registers. Optional **.env**: `STELLAR_HORIZON_URL` (default testnet), `STELLAR_USDC_ISSUER_TESTNET`, `STELLAR_SHOW_SECRET_TESTNET=1` to include secret in response.

### Car Management (Host only, requires authentication)
- `POST /api/v1/cars/basics` - Step 1: Create car with basic information
- `PUT /api/v1/cars/{car_id}/specs` - Step 2: Update car technical specifications
- `PUT /api/v1/cars/{car_id}/pricing` - Step 3: Update car pricing and rules
- `PUT /api/v1/cars/{car_id}/location` - Step 4: Update car location and mark as complete
- `GET /api/v1/cars/{car_id}` - Get car details by ID
- `GET /api/v1/cars` - List all cars (with pagination)
- `GET /api/v1/host/cars` - List all cars belonging to authenticated host

### Media Upload (Requires authentication)

#### Client Media Endpoints
- `POST /api/v1/client/upload/avatar` - Upload client profile avatar
- `POST /api/v1/client/upload/document` - Upload client documents (ID or license)

#### Host Media Endpoints
- `POST /api/v1/host/upload/avatar` - Upload host profile avatar
- `POST /api/v1/host/upload/cover` - Upload host profile cover image
- `POST /api/v1/host/upload/document` - Upload host documents (ID or license)
- `POST /api/v1/host/upload/vehicle/{car_id}/images` - Upload vehicle images (up to 10)
- `POST /api/v1/host/upload/vehicle/{car_id}/video` - Upload vehicle video

## Email (SendGrid)

Welcome emails and password-reset emails use [SendGrid](https://sendgrid.com/). Add these to your **.env**:

```env
SENDGRID_API_KEY=SG.xxxxxxxxxxxxxxxxxxxxxxxx
SENDGRID_FROM_EMAIL=Ardena Group Team <hello@ardena.xyz>
```

- **SENDGRID_API_KEY:** Create an API key in [SendGrid Dashboard](https://app.sendgrid.com/settings/api_keys) (e.g. "Restricted Access" → Mail Send only).
- **SENDGRID_FROM_EMAIL:** Use a verified sender (Single Sender or domain-authenticated address like `hello@ardena.xyz`). Default is `Ardena Group Team <hello@ardena.xyz>` if not set.

### Newsletter subscribers

- **Public (website):**
  - `POST /api/v1/subscribe` – body `{ "email": "user@example.com" }` – subscribe to newsletter
  - `POST /api/v1/unsubscribe` – body `{ "email": "user@example.com" }` – unsubscribe
- **Admin (Bearer token):**
  - `GET /api/v1/admin/subscribers` – list subscribers (paginated; optional `subscribed_only=true`)
  - `GET /api/v1/admin/subscribers/count` – total subscribed count
  - `POST /api/v1/admin/subscribers/send` – body `{ "subject": "...", "body_html": "..." }` – send email to all subscribed addresses

Include an unsubscribe link in your newsletter (e.g. `https://yoursite.com/unsubscribe?email={{email}}` that POSTs to `/api/v1/unsubscribe`).  
Admin UI: open or link to **admin-web/subscribers.html** for the subscribers page (count, list, send to all).

### Host KYC (Veriff)

Hosts verify identity via [Veriff](https://www.veriff.com/) (ID, passport, or driver’s licence + liveness). No document images are stored; only status and metadata.

- **.env:**
  - `VERIFF_API_KEY` – required (API key from Veriff, used to create sessions).
  - **Webhook verification** (recommended): set **one** of `VERIFF_WEBHOOK_SECRET`, `SHARED_SECRET_KEY`, or `MASTER_SECRET_KEY` to the value from Veriff Customer Portal → Integration → Auth methods → shared secret / master signature key. The backend verifies `X-HMAC-SIGNATURE` on incoming webhooks so only Veriff can update KYC results.
  - Optional: `VERIFF_BASE_URL` (default `https://stationapi.veriff.com`).
  - **Return to app after verification:** Veriff allows only **HTTPS** callback URLs. If the app sends a deep link (e.g. `ardenahost://kyc/result`) in the session body, set `VERIFF_CALLBACK_URL` to your API's public HTTPS URL for the redirect endpoint, e.g. `https://api.ardena.xyz/api/v1/host/kyc/redirect`. Veriff redirects the user there after verification; the backend then redirects to the app deep link. Optional: `KYC_ALLOWED_RETURN_PREFIXES` (default `ardenahost://,ardena://`).
  - **Local dev with ngrok:** See [Local dev: ngrok for Veriff KYC](#local-dev-ngrok-for-veriff-kyc) below.
- **App flow:** Host taps “Continue to verification” → app calls `POST /api/v1/host/kyc/session` (Bearer) → backend returns `verification_url` → app opens that URL (browser/webview) → user completes Veriff flow.
- **Result:** Veriff sends a decision to your webhook. Set **Webhook decisions URL** in Veriff Customer Portal to `https://api.ardena.xyz/api/v1/veriff/webhook` (or your API base + `/api/v1/veriff/webhook`). Backend updates `host_kycs` and the app can poll `GET /api/v1/host/kyc/status` (Bearer) to show approved/declined/pending.

#### Local dev: ngrok for Veriff KYC

Veriff requires an **HTTPS** callback URL. For local development, expose your backend with ngrok and point `VERIFF_CALLBACK_URL` at the ngrok URL.

1. **Install ngrok** (if needed):
   - **Windows:** Download the Windows 64-bit zip from [ngrok.com/download](https://ngrok.com/download), extract `ngrok.exe` to a folder (e.g. `D:\backend\tools` or `C:\ngrok`). Either add that folder to your PATH or run ngrok with the full path, e.g. `D:\backend\tools\ngrok.exe http 8001`. Alternatively: `winget install ngrok.ngrok` then open a **new** PowerShell (so PATH updates) and run `ngrok http 8001`.
   - **Mac/Linux:** `brew install ngrok` (Mac) or download from ngrok.com.
   - Sign up at [ngrok.com](https://ngrok.com) and add your auth token: `ngrok config add-authtoken YOUR_TOKEN`.
   - **Use port 8001** (your backend), not 3000: `ngrok http 8001`.

2. **Start your backend** (in one terminal):
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
   ```

3. **Start ngrok** (in a second terminal), forwarding to port 8001:
   ```bash
   ngrok http 8001
   ```
   Or from the project root: `scripts\ngrok.bat` (Windows) or `./scripts/ngrok.sh` (Mac/Linux).
   You’ll see a line like:
   ```text
   Forwarding   https://abc123.ngrok-free.app -> http://localhost:8001
   ```

4. **Set the callback URL in `.env`** (use the **HTTPS** URL from ngrok):
   ```env
   VERIFF_CALLBACK_URL=https://YOUR-NGROK-SUBDOMAIN.ngrok-free.app/api/v1/host/kyc/redirect
   ```
   Example: if ngrok shows `https://abc123.ngrok-free.app`, set:
   ```env
   VERIFF_CALLBACK_URL=https://abc123.ngrok-free.app/api/v1/host/kyc/redirect
   ```

5. **Restart the backend** so it picks up the new `VERIFF_CALLBACK_URL`. Your app can keep using your local IP (e.g. `http://192.168.88.x:8001`) for API calls; Veriff will use the ngrok HTTPS URL only for the post-verification redirect.

**Note:** The free ngrok URL changes each time you restart ngrok. Update `VERIFF_CALLBACK_URL` in `.env` and restart the backend whenever you get a new ngrok URL. For a stable URL, use a paid ngrok plan or deploy to a server with a fixed HTTPS URL.

### M-Pesa / Payhero callback (payment status)

After a client pays via M-Pesa STK push, **Payhero** sends a webhook to your backend to confirm success or failure. Payment status (and booking confirmation) is updated only when that callback is received.

- **`PAYHERO_CALLBACK_URL`** in `.env` must be a **public** URL that Payhero’s servers can reach from the internet, e.g.  
  `https://api.ardena.xyz/api/v1/mpesa/callback`  
  If you use a local or LAN URL (e.g. `http://192.168.88.249:8001/api/v1/mpesa/callback` or `http://localhost:8001/...`), Payhero cannot call it, so the status will stay **pending** even after the user has paid.

#### Local testing: ngrok for Payhero (and Veriff)

Use one ngrok tunnel on port 8001 for both Payhero and Veriff callbacks.

1. **Install ngrok** (if you haven’t): see [Local dev: ngrok for Veriff KYC](#local-dev-ngrok-for-veriff-kyc) (same steps). Auth token: `ngrok config add-authtoken YOUR_TOKEN`.

2. **Start your backend** (Terminal 1):
   ```bash
   uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
   ```

3. **Start ngrok** (Terminal 2), from project root:
   ```bash
   scripts\ngrok.bat
   ```
   Or: `ngrok http 8001`. Copy the **HTTPS** URL (e.g. `https://abc123.ngrok-free.app`).

4. **Set in `.env`** (replace `YOUR-SUBDOMAIN` with your ngrok subdomain):
   ```env
   PAYHERO_CALLBACK_URL=https://YOUR-SUBDOMAIN.ngrok-free.app/api/v1/mpesa/callback
   ```
   Optional, for Veriff KYC on the same tunnel:
   ```env
   VERIFF_CALLBACK_URL=https://YOUR-SUBDOMAIN.ngrok-free.app/api/v1/host/kyc/redirect
   ```

5. **Payhero dashboard:** Set the callback URL to the same value as `PAYHERO_CALLBACK_URL` (if Payhero lets you configure it per request, the backend already sends it; otherwise set the default in the dashboard).

6. **Restart the backend** so it loads the new `.env`. Your app can keep using `http://192.168.88.x:8001` for API calls; Payhero will use the ngrok URL for the webhook.

7. **Verify:** After a test payment, check server logs for `[PAYHERO CALLBACK] Received payload:` — if it appears, the callback is working and status will update to completed.

### Pending booking expiry

Unpaid **pending** bookings are automatically cancelled after a set time so the car becomes available again.

- **`PENDING_BOOKING_EXPIRE_MINUTES`** (default: `30`) – Cancel PENDING bookings that have no completed payment and were created more than this many minutes ago.
- **`PENDING_BOOKING_EXPIRE_CHECK_INTERVAL_MINUTES`** (default: `1`) – How often the background task runs to check for expired bookings.

Optional in `.env`:
```env
PENDING_BOOKING_EXPIRE_MINUTES=30
PENDING_BOOKING_EXPIRE_CHECK_INTERVAL_MINUTES=1
```

On startup you’ll see a log like: `[EXPIRE] Pending booking expiry: expire after 30 min, check every 1 min`. When bookings are expired: `[EXPIRE] Expired N unpaid pending booking(s)`.

## Troubleshooting: Backend not reachable

If the admin panel or mobile app can't reach the backend (no logs appear):

1. **Verify backend is running and listening:**
   ```bash
   # Check if port 8001 is listening
   netstat -an | findstr :8001  # Windows
   # or
   lsof -i :8001  # Mac/Linux
   ```
   You should see the port listening on `0.0.0.0:8001` (all interfaces).

2. **Test connectivity from browser/terminal:**
   - Open: `http://localhost:8001/api/v1/ping` → should return JSON
   - Open: `http://192.168.88.249:8001/api/v1/ping` (use your PC's IP) → should return JSON
   - If `localhost` works but IP doesn't, the server might only be listening on `127.0.0.1`. Restart with `--host 0.0.0.0`.

3. **Check Windows Firewall:**
   - Windows Firewall may block incoming connections on port 8001
   - Add an inbound rule to allow port 8001, or temporarily disable firewall to test

4. **Verify IP address:**
   - Run `ipconfig` (Windows) or `ifconfig` (Mac/Linux)
   - Use the IPv4 address shown (e.g., `192.168.88.249`)
   - Ensure your phone/device is on the same WiFi network

5. **Check backend logs:**
   - The backend logs every request with `[REQUEST] METHOD /path from IP`
   - If you see no logs, requests aren't reaching the server (firewall/network issue)
   - If you see logs but the app still fails, check CORS or authentication

6. **Admin panel API detection:**
   - Open `admin-web/index.html` in a browser
   - The login page shows "API: ... ✓ OK" or "✗ unreachable" at the bottom
   - If it shows production URL (`https://api.ardena.xyz`), open from `http://localhost:5500/index.html` instead of `file://`

7. **Expo Go / Mobile app:**
   - Ensure the app's API base URL is `http://YOUR_PC_IP:8001/api/v1` (not `localhost` or production)
   - Test with `curl http://YOUR_PC_IP:8001/api/v1/ping` from your phone's network or another device

## M-Pesa production (live): STK never appears on phone

If **no STK push appears on the customer’s phone** but the callback returns (e.g. 2029), production is almost certainly still using **sandbox**.

- **Sandbox** (`sandbox.safaricom.co.ke`, shortcode `174379`) is for testing only. Real phones on the live M-Pesa network **do not** receive STK pushes from sandbox.
- **Production** must use **live** Daraja credentials and **live** URLs.

**Production `.env` – two ways to configure:**

**Option A – Explicit URLs (any env var names):**
```env
MPESA_TOKEN_URL=https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials
MPESA_STK_URL=https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest
MPESA_CALLBACK_URL=https://api.ardena.xyz/api/v1/mpesa/callback
MPESA_SHORTCODE=6792295
# For STK push, can use MPESA_EXPRESS_SHORTCODE (e.g. 4239478) if different from MPESA_SHORTCODE
MPESA_PASSKEY=<your-live-passkey>
CONSUMER_KEY=<your-live-consumer-key>
CONSUMER_SECRET=<your-live-consumer-secret>
```

**Option B – Use MPESA_ENVIRONMENT (backend picks live URLs):**
```env
MPESA_ENVIRONMENT=production
MPESA_CALLBACK_URL=https://api.ardena.xyz/api/v1/mpesa/callback
MPESA_CONSUMER_KEY=<your-live-consumer-key>
MPESA_CONSUMER_SECRET=<your-live-consumer-secret>
MPESA_PASSKEY=<your-live-passkey>
# Till number: use MPESA_EXPRESS_SHORTCODE for STK (e.g. 4239478), set type for TransactionType
MPESA_EXPRESS_SHORTCODE=4239478
MPESA_SHORTCODE=6792295
MPESA_SHORTCODE_TYPE=till_number
```

- **Credentials:** Either `CONSUMER_KEY`/`CONSUMER_SECRET` or `MPESA_CONSUMER_KEY`/`MPESA_CONSUMER_SECRET`.
- **Shortcode for STK:** Sandbox always uses `MPESA_SHORTCODE` (e.g. 174379). Live uses `MPESA_EXPRESS_SHORTCODE` when set, else `MPESA_SHORTCODE`. For live Till use `MPESA_SHORTCODE_TYPE=till_number`.
- **Callback:** `MPESA_CALLBACK_URL` must be a **public HTTPS** URL (e.g. `https://api.ardena.xyz/api/v1/mpesa/callback`).
- **Sandbox:** Use sandbox URLs or `MPESA_ENVIRONMENT=sandbox` (or leave unset). Do **not** set `MPESA_ENVIRONMENT=production` in the same .env you use for sandbox testing, or the backend will use live URLs and sandbox will fail. For local sandbox you can **omit** `MPESA_CALLBACK_URL`; the backend will use a placeholder so the STK still sends (callbacks won’t reach your app until you set a public URL, e.g. ngrok).
- On startup, the backend warns if it’s using sandbox so you can set `MPESA_ENVIRONMENT=production` or live URLs.

## M-Pesa STK callback result codes

When a payment fails in production, the callback receives a `ResultCode` from Safaricom:

| Code | Meaning | What to do |
|------|---------|------------|
| **0** | Success | Booking is confirmed. |
| **1032** | User cancelled | Customer dismissed the STK prompt. They can retry. |
| **2029** | Unresolved reason (often timeout) | Usually: customer didn’t enter PIN in time (~60s), network/operator issue, or sandbox vs live mismatch. Backend stores a user-friendly message; ensure `MPESA_*` URLs and shortcode match the customer’s network (sandbox vs live). |
| Other | e.g. insufficient funds | Raw `ResultDesc` is stored and returned in `GET /client/payments/status`. |

The backend maps **1032** and **2029** to short, user-friendly messages for the status API so the app can show “Payment cancelled” or “Payment timed out. Please try again.” instead of the raw Safaricom text.

## Production deployment

- **Python 3.9:** The code uses `Optional[X]` instead of `X | None` so it runs on Python 3.9 (e.g. CentOS/RHEL default). If you see `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`, ensure production runs this repo version (those hints were already fixed).
- **Supabase "proxy" error:** If workers fail with `__init__() got an unexpected keyword argument 'proxy'`, it is usually a version mismatch between `supabase-py`, `gotrue`, and `httpx`. The app will still start (Supabase init is caught); media uploads will fail until you pin compatible versions, e.g. `httpx>=0.26` and matching supabase/gotrue. See [supabase-py#949](https://github.com/supabase/supabase-py/issues/949).

## Development

See `guide.md` for the complete development checklist and project requirements.

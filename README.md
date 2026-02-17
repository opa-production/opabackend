# Car Rental Backend API

FastAPI backend for a car rental platform with server-side validation and multi-step car listing workflow.

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
```

2. Activate the virtual environment:
```bash
# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Run the application:
```bash
# For local development (localhost only)
uvicorn app.main:app --reload --port 8001

# For network access (Expo Go, mobile devices, etc.)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
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

## Production deployment

- **Python 3.9:** The code uses `Optional[X]` instead of `X | None` so it runs on Python 3.9 (e.g. CentOS/RHEL default). If you see `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`, ensure production runs this repo version (those hints were already fixed).
- **Supabase "proxy" error:** If workers fail with `__init__() got an unexpected keyword argument 'proxy'`, it is usually a version mismatch between `supabase-py`, `gotrue`, and `httpx`. The app will still start (Supabase init is caught); media uploads will fail until you pin compatible versions, e.g. `httpx>=0.26` and matching supabase/gotrue. See [supabase-py#949](https://github.com/supabase/supabase-py/issues/949).

## Development

See `guide.md` for the complete development checklist and project requirements.


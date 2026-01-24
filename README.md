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

## Development

See `guide.md` for the complete development checklist and project requirements.


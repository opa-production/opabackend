# Admin Module

This module contains all admin-related functionality for the car rental platform.

## Default Super Admin

On first startup, a default super admin account is automatically created:

- **Email:** `admin@carrental.com`
- **Password:** `Admin123!`
- **Role:** `super_admin`

⚠️ **IMPORTANT:** Change this password immediately after first login!

## Admin Authentication

### Login
```bash
POST /api/v1/admin/auth/login
Content-Type: application/json

{
  "email": "admin@carrental.com",
  "password": "Admin123!"
}
```

### Response
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "admin": {
    "id": 1,
    "full_name": "Super Admin",
    "email": "admin@carrental.com",
    "role": "super_admin",
    "is_active": true,
    "created_at": "2026-01-15T10:40:00",
    "updated_at": null
  }
}
```

### Using the Token

Include the token in the Authorization header for all admin endpoints:

```
Authorization: Bearer <access_token>
```

## Available Endpoints

### Authentication
- `POST /api/v1/admin/auth/login` - Admin login
- `POST /api/v1/admin/auth/logout` - Admin logout
- `GET /api/v1/admin/me` - Get current admin info

## Next Steps

See `TODO.md` for the complete list of admin APIs to be implemented.

## File Structure

```
app/admin/
├── __init__.py
├── auth.py          # Admin authentication router
├── TODO.md          # List of admin APIs to implement
└── README.md        # This file
```

# Bug: New users inherit profile photos from deleted accounts

## What's happening

Client avatars are stored in Supabase Storage under the path:
```
client-profile-media/{clientId}/client_{clientId}_avatar_{timestamp}.jpg
```

When DB users are deleted (e.g. during dev/testing), their Supabase storage files are
**not** cleaned up. PostgreSQL then recycles those integer IDs for new accounts.

Result: a brand-new user with recycled ID `42` looks up folder `42/` in Supabase
and finds photos belonging to the old deleted user — showing a stranger's face on
their profile.

---

## How the mobile app retrieves avatars

1. `GET /api/v1/client/me` — returns the client profile, including `avatar_url` (the
   URL saved to the DB when the user last uploaded a photo).
2. The app was previously falling back to a direct Supabase storage listing
   (`supabase.storage.from('client-profile-media').list(clientId)`) if `avatar_url`
   was missing, which is what caused the wrong photo to appear.

**Frontend fix already applied**: `getCurrentClient()` in `authService.js` now trusts
only the `avatar_url` field returned by the backend API. The Supabase storage listing
fallback has been removed entirely.

---

## Backend fixes needed

### Fix 1 — Delete Supabase storage files when a client is deleted

When a `Client` record is deleted (via API, admin panel, or script), add a step that
removes their Supabase storage folder:

```python
from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def delete_client_storage(client_id: int):
    bucket = "client-profile-media"
    folder = str(client_id)

    # List all files under {client_id}/
    files = supabase.storage.from_(bucket).list(folder)
    if files:
        paths = [f"{folder}/{f['name']}" for f in files]
        supabase.storage.from_(bucket).remove(paths)
```

Call this wherever a client is deleted — in the delete endpoint, admin panel, or
migration scripts.

### Fix 2 — Use a stable UUID-based storage path (long-term)

Integer IDs can be recycled. To permanently prevent this, store avatars under a path
that cannot be reused — for example the client's UUID or email hash:

```
client-profile-media/{uuid}/client_{uuid}_avatar_{timestamp}.jpg
```

The UUID should be assigned once at account creation and never reused even if the
account is deleted. This eliminates the recycled-ID problem entirely.

### Fix 3 — Ensure `avatar_url` in the DB is cleared on account delete

If you ever soft-delete or reset a client record, make sure `avatar_url` is set to
`NULL` so the API returns `null` for new users occupying that ID.

---

## Storage bucket details (from mobile codebase)

| Bucket name | Used for |
|---|---|
| `client-profile-media` | Client avatars & identity documents |
| `host-profile-images` | Host avatars |

The client avatar path pattern is:
```
{clientId}/client_{clientId}_avatar_{timestamp}.{ext}
```

---

## Current state after frontend fix

- New users: backend returns `avatar_url: null` → app shows no photo ✓
- Existing users who uploaded a photo: backend has the URL in DB → correct photo ✓
- Recycled IDs: Supabase listing is no longer called, so stale files are never shown ✓

The Supabase cleanup (Fix 1) is still recommended to avoid accumulating orphaned files
in storage.

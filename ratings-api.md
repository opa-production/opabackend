# Ratings API — Client App Integration Guide

## Overview

There are now **two separate rating systems**:

| System | Table | Purpose | Who writes |
|--------|-------|---------|------------|
| **Car Ratings** (primary) | `car_ratings` | Clients rate a specific car after a completed booking | Client |
| **Host Ratings** (secondary, read-only) | derived from `car_ratings` | Aggregate view of a host's rating across all their cars | Nobody writes — computed |

**Key behaviour change:** A host's rating is no longer stored at the host level. It is computed from their cars' ratings. A brand-new car with no ratings does **not** pull the host's average down — it simply has no rating yet.

---

## Base URL

```
/api/v1
```

All authenticated endpoints require the client JWT in the `Authorization: Bearer <token>` header.

---

## 1. Car Ratings API (Primary)

### 1.1 Submit a car rating

**`POST /client/car-ratings`** — Auth required

Submit a rating for a car after a completed booking.

**Request body**

```json
{
  "car_id": 12,
  "booking_id": 45,
  "rating": 5,
  "review": "Amazing car, very clean and smooth ride."
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `car_id` | int | Yes | ID of the car being rated |
| `booking_id` | int | No* | ID of the completed booking. Strongly recommended — enforces one rating per booking |
| `rating` | int | Yes | 1 – 5 stars |
| `review` | string | No | Max 1000 characters |

*If `booking_id` is omitted the rating is still saved, but there is no duplicate-check protection.

**Success response — `201 Created`**

```json
{
  "id": 7,
  "car_id": 12,
  "client_id": 3,
  "booking_id": 45,
  "rating": 5,
  "review": "Amazing car, very clean and smooth ride.",
  "created_at": "2026-04-10T14:30:00Z",
  "updated_at": null,
  "client_name": "Amina Diallo",
  "car_name": "Mercedes C-Class"
}
```

**Error responses**

| Status | `detail` | Cause |
|--------|----------|-------|
| `404` | `"Car not found"` | `car_id` does not exist |
| `404` | `"Booking not found or does not belong to this client and car"` | Wrong `booking_id`, wrong client, or wrong car |
| `400` | `"You can only rate cars for completed bookings"` | Booking status is not `COMPLETED` |
| `400` | `"This booking has already been rated"` | A rating already exists for this `booking_id` |

---

### 1.2 Get my submitted car ratings

**`GET /client/car-ratings`** — Auth required

Returns all ratings the current client has submitted.

**Query params**

| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `skip` | int | `0` | Pagination offset |
| `limit` | int | `20` | Max `100` |
| `car_id` | int | — | Filter to ratings for a specific car |

**Success response — `200 OK`**

```json
{
  "ratings": [
    {
      "id": 7,
      "car_id": 12,
      "client_id": 3,
      "booking_id": 45,
      "rating": 5,
      "review": "Amazing car, very clean and smooth ride.",
      "created_at": "2026-04-10T14:30:00Z",
      "updated_at": null,
      "client_name": "Amina Diallo",
      "car_name": "Mercedes C-Class"
    }
  ],
  "total": 1,
  "average_rating": null
}
```

> `average_rating` is always `null` here — it is not meaningful for the client's own submitted list.

---

### 1.3 Get a specific rating

**`GET /client/car-ratings/{rating_id}`** — Auth required

Returns a single rating that belongs to the current client.

**Success response — `200 OK`** — same shape as a single item in `1.2`.

**Error responses**

| Status | `detail` | Cause |
|--------|----------|-------|
| `404` | `"Rating not found"` | Rating doesn't exist or belongs to another client |

---

### 1.4 Update a rating

**`PUT /client/car-ratings/{rating_id}`** — Auth required

**Request body**

```json
{
  "rating": 4,
  "review": "Updated: great car but AC was a bit weak."
}
```

| Field | Type | Required |
|-------|------|----------|
| `rating` | int | Yes — 1 to 5 |
| `review` | string | No — max 1000 chars |

**Success response — `200 OK`** — same shape as `1.1` response.

**Error responses**

| Status | `detail` | Cause |
|--------|----------|-------|
| `404` | `"Rating not found"` | Rating doesn't exist or belongs to another client |

---

### 1.5 Delete a rating

**`DELETE /client/car-ratings/{rating_id}`** — Auth required

**Success response — `204 No Content`** (empty body)

**Error responses**

| Status | `detail` | Cause |
|--------|----------|-------|
| `404` | `"Rating not found"` | Rating doesn't exist or belongs to another client |

---

### 1.6 Get ratings for a specific car (public)

**`GET /cars/{car_id}/ratings`** — No auth required

Fetch all ratings for a car to display on the car listing page.

**Query params**

| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `skip` | int | `0` | Pagination offset |
| `limit` | int | `20` | Max `100` |

**Success response — `200 OK`**

```json
{
  "ratings": [
    {
      "id": 7,
      "car_id": 12,
      "client_id": 3,
      "booking_id": 45,
      "rating": 5,
      "review": "Amazing car, very clean and smooth ride.",
      "created_at": "2026-04-10T14:30:00Z",
      "updated_at": null,
      "client_name": "Amina Diallo",
      "car_name": "Mercedes C-Class"
    }
  ],
  "total": 8,
  "average_rating": 4.63
}
```

> Use `average_rating` to display the star score on the car card/listing. It is `null` if the car has no ratings yet — show "No ratings yet" in that case.

**Error responses**

| Status | `detail` | Cause |
|--------|----------|-------|
| `404` | `"Car not found"` | Invalid `car_id` |

---

## 2. Host Ratings API (Secondary — Read-Only)

### 2.1 Get ratings for a host (public)

**`GET /hosts/{host_id}/ratings`** — No auth required

Returns all car ratings made across every car owned by this host, aggregated into a single list. The `average_rating` in the response is the host's overall score.

**Why it changed:** Previously, the host rating was its own separate score. Now it is computed from `CarRating` so that a new unrated car does not falsely inherit the host's existing reputation.

**Query params**

| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `skip` | int | `0` | Pagination offset |
| `limit` | int | `20` | Max `100` |

**Success response — `200 OK`**

```json
{
  "ratings": [
    {
      "id": 7,
      "host_id": 2,
      "client_id": 3,
      "booking_id": 45,
      "rating": 5,
      "review": "Amazing car, very clean and smooth ride.",
      "created_at": "2026-04-10T14:30:00Z",
      "updated_at": null,
      "client_name": "Amina Diallo"
    }
  ],
  "total": 23,
  "average_rating": 4.52
}
```

> Each item in `ratings` represents one car-level review. `host_id` is included for convenience. There is no `car_name` in this response — if you need it, call `GET /cars/{car_id}/ratings` instead.
>
> `average_rating` is `null` if the host has no rated cars yet.

**Error responses**

| Status | `detail` | Cause |
|--------|----------|-------|
| `404` | `"Host not found"` | Invalid `host_id` |

---

## 3. Response Shape Reference

### `CarRatingResponse`

```ts
{
  id: number
  car_id: number
  client_id: number
  booking_id: number | null
  rating: number           // 1–5
  review: string | null
  created_at: string       // ISO 8601 datetime
  updated_at: string | null
  client_name: string | null
  car_name: string | null
}
```

### `CarRatingListResponse`

```ts
{
  ratings: CarRatingResponse[]
  total: number
  average_rating: number | null   // null when no ratings exist
}
```

### `HostRatingResponse` (derived from car ratings)

```ts
{
  id: number
  host_id: number | null
  client_id: number
  booking_id: number | null
  rating: number           // 1–5
  review: string | null
  created_at: string       // ISO 8601 datetime
  updated_at: string | null
  client_name: string | null
  // NOTE: no car_name field here
}
```

### `HostRatingListResponse`

```ts
{
  ratings: HostRatingResponse[]
  total: number
  average_rating: number | null
}
```

---

## 4. Integration Checklist for the Client App

- [ ] **Car listing / card**: call `GET /cars/{car_id}/ratings` and display `average_rating` + `total`. Show "No ratings yet" when `average_rating` is `null`.
- [ ] **Host profile**: call `GET /hosts/{host_id}/ratings` for the host's aggregate score (`average_rating`). Display individual reviews from `ratings[]` using `client_name` and `review`.
- [ ] **Post-booking flow**: after a booking reaches `COMPLETED` status, show a "Rate your trip" prompt. Call `POST /client/car-ratings` with `car_id`, `booking_id`, `rating`, and optional `review`.
- [ ] **My ratings screen**: call `GET /client/car-ratings` to list reviews the client has already written.
- [ ] **Edit / delete rating**: use `PUT /client/car-ratings/{id}` or `DELETE /client/car-ratings/{id}`.
- [ ] **Unrated car**: if `GET /cars/{car_id}/ratings` returns `average_rating: null`, do not show a star score — do not fall back to the host's rating for that car.

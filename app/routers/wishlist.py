"""
Client wishlist endpoints.

The client UI has a heart button on car cards:
- Pressing the heart should add/remove the car from the client's wishlist.
- The wishlist screen shows a single summary card with the latest liked car
  image and the total count, and tapping it shows the list of liked cars.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.auth import get_current_client
from app.models import Client, Car, WishlistItem
from app.schemas import WishlistSummaryResponse, WishlistCarItem, WishlistListResponse

router = APIRouter()


@router.post("/client/wishlist/{car_id}", status_code=status.HTTP_201_CREATED)
async def add_to_wishlist(
    car_id: int,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Add a car to the current client's wishlist.

    Idempotent: if the car is already in the wishlist, this returns 201 with no
    duplicate row created.
    """
    car = db.query(Car).filter(Car.id == car_id).first()
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found",
        )

    existing = (
        db.query(WishlistItem)
        .filter(
            WishlistItem.client_id == current_client.id,
            WishlistItem.car_id == car_id,
        )
        .first()
    )
    if existing:
        # Already wishlisted; treat as success
        return {"detail": "Already in wishlist"}

    item = WishlistItem(client_id=current_client.id, car_id=car_id)
    db.add(item)
    db.commit()

    return {"detail": "Added to wishlist"}


@router.delete("/client/wishlist/{car_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_wishlist(
    car_id: int,
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Remove a car from the current client's wishlist.
    """
    item = (
        db.query(WishlistItem)
        .filter(
            WishlistItem.client_id == current_client.id,
            WishlistItem.car_id == car_id,
        )
        .first()
    )
    if not item:
        # Nothing to remove; treat as success
        return None

    db.delete(item)
    db.commit()
    return None


@router.get("/client/wishlist/summary", response_model=WishlistSummaryResponse)
async def get_wishlist_summary(
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    Get a compact summary for the wishlist card:
    - total number of liked cars
    - the most recently liked car's id, name, and cover image
    """
    q = (
        db.query(WishlistItem)
        .options(joinedload(WishlistItem.car))
        .filter(WishlistItem.client_id == current_client.id)
        .order_by(WishlistItem.created_at.desc())
    )
    items = q.all()
    total = len(items)
    if not items:
        return WishlistSummaryResponse(
            total_cars=0,
            latest_car_id=None,
            latest_car_name=None,
            latest_cover_image=None,
        )

    latest = items[0]
    car = latest.car
    cover_image = None
    if car:
        # Prefer new cover_image; fall back to first parsed image_urls
        if getattr(car, "cover_image", None):
            cover_image = car.cover_image
        else:
            try:
                import json

                imgs = json.loads(car.image_urls) if car.image_urls else []
                if isinstance(imgs, list) and imgs:
                    cover_image = imgs[0]
            except Exception:
                cover_image = None

    return WishlistSummaryResponse(
        total_cars=total,
        latest_car_id=car.id if car else None,
        latest_car_name=car.name if car else None,
        latest_cover_image=cover_image,
    )


@router.get("/client/wishlist", response_model=WishlistListResponse)
async def list_wishlist_cars(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of records to return"),
    current_client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """
    List the client's wishlisted cars with basic details for the wishlist screen.
    """
    q = (
        db.query(WishlistItem)
        .options(joinedload(WishlistItem.car))
        .filter(WishlistItem.client_id == current_client.id)
        .order_by(WishlistItem.created_at.desc())
    )
    items = q.offset(skip).limit(limit).all()

    cars: list[WishlistCarItem] = []
    for item in items:
        car = item.car
        if not car:
            continue
        cover_image = None
        if getattr(car, "cover_image", None):
            cover_image = car.cover_image
        else:
            try:
                import json

                imgs = json.loads(car.image_urls) if car.image_urls else []
                if isinstance(imgs, list) and imgs:
                    cover_image = imgs[0]
            except Exception:
                cover_image = None

        cars.append(
            WishlistCarItem(
                car_id=car.id,
                name=car.name,
                model=car.model,
                daily_rate=car.daily_rate,
                cover_image=cover_image,
                location_name=car.location_name,
                created_at=item.created_at,
            )
        )

    return WishlistListResponse(cars=cars)


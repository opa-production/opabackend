"""
Client wishlist endpoints.

The client UI has a heart button on car cards:
- Pressing the heart should add/remove the car from the client's wishlist.
- The wishlist screen shows a single summary card with the latest liked car
  image and the total count, and tapping it shows the list of liked cars.
"""
import json
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.auth import get_current_client
from app.models import Client, Car, WishlistItem
from app.schemas import WishlistSummaryResponse, WishlistCarItem, WishlistListResponse

router = APIRouter()


def _cover_image_for_car(car: Car) -> str | None:
    if getattr(car, "cover_image", None):
        return car.cover_image
    try:
        imgs = json.loads(car.image_urls) if car.image_urls else []
        if isinstance(imgs, list) and imgs:
            return imgs[0]
    except Exception:
        pass
    return None


@router.post("/client/wishlist/{car_id}", status_code=status.HTTP_201_CREATED)
async def add_to_wishlist(
    car_id: int,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Add a car to the current client's wishlist.

    Idempotent: if the car is already in the wishlist, this returns 201 with no
    duplicate row created.
    """
    car_result = await db.execute(select(Car).where(Car.id == car_id))
    car = car_result.scalar_one_or_none()
    if not car:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Car not found",
        )

    existing_result = await db.execute(
        select(WishlistItem).where(
            WishlistItem.client_id == current_client.id,
            WishlistItem.car_id == car_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        return {"detail": "Already in wishlist"}

    item = WishlistItem(client_id=current_client.id, car_id=car_id)
    db.add(item)
    await db.commit()

    return {"detail": "Added to wishlist"}


@router.delete("/client/wishlist/{car_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_wishlist(
    car_id: int,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove a car from the client's wishlist.
    """
    result = await db.execute(
        select(WishlistItem).where(
            WishlistItem.client_id == current_client.id,
            WishlistItem.car_id == car_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        return None

    await db.delete(item)
    await db.commit()
    return None


@router.get("/client/wishlist/summary", response_model=WishlistSummaryResponse)
async def get_wishlist_summary(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a compact summary for the wishlist card:
    - total number of liked cars
    - the most recently liked car's id, name, and cover image
    """
    count_result = await db.execute(
        select(func.count())
        .select_from(WishlistItem)
        .where(WishlistItem.client_id == current_client.id)
    )
    total = count_result.scalar_one()

    if total == 0:
        return WishlistSummaryResponse(
            total_cars=0,
            latest_car_id=None,
            latest_car_name=None,
            latest_cover_image=None,
        )

    latest_result = await db.execute(
        select(WishlistItem)
        .options(joinedload(WishlistItem.car))
        .where(WishlistItem.client_id == current_client.id)
        .order_by(WishlistItem.created_at.desc())
        .limit(1)
    )
    latest = latest_result.scalar_one_or_none()
    if not latest or not latest.car:
        return WishlistSummaryResponse(
            total_cars=total,
            latest_car_id=None,
            latest_car_name=None,
            latest_cover_image=None,
        )

    car = latest.car
    return WishlistSummaryResponse(
        total_cars=total,
        latest_car_id=car.id,
        latest_car_name=car.name,
        latest_cover_image=_cover_image_for_car(car),
    )


@router.get("/client/wishlist", response_model=WishlistListResponse)
async def list_wishlist_cars(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of records to return"),
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    List the client's wishlisted cars with basic details for the wishlist screen.
    """
    result = await db.execute(
        select(WishlistItem)
        .options(joinedload(WishlistItem.car))
        .where(WishlistItem.client_id == current_client.id)
        .order_by(WishlistItem.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    items = result.scalars().unique().all()

    cars: list[WishlistCarItem] = []
    for item in items:
        car = item.car
        if not car:
            continue
        cars.append(
            WishlistCarItem(
                car_id=car.id,
                name=car.name,
                model=car.model,
                daily_rate=car.daily_rate,
                cover_image=_cover_image_for_car(car),
                location_name=car.location_name,
                created_at=item.created_at,
            )
        )

    return WishlistListResponse(cars=cars)

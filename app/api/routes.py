from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from bson import ObjectId
import httpx

from app.core.config import settings
from app.core.db import db
from app.core.rabbitmq import publish

router = APIRouter()
security = HTTPBearer()

# ─────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────

class EventCreate(BaseModel):
    title: str
    description: str
    category: str
    starts_at: datetime
    ends_at: datetime
    location: str
    capacity: int

class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    location: Optional[str] = None
    capacity: Optional[int] = None

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def fix_id(event: dict) -> dict:
    event["id"] = str(event["_id"])
    del event["_id"]
    return event

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Instead of verifying JWT locally, we ask registration-service:
    GET /auth/me  →  returns the user profile if token is valid.
    """
    token = credentials.credentials
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(
                f"{settings.REGISTRATION_SERVICE_URL}/auth/me",
                headers={"Authorization": f"Bearer {token}"}
            )
    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail="Auth service unreachable. Make sure registration-service is running."
        )

    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if response.status_code != 200:
        raise HTTPException(status_code=403, detail="Could not verify user")

    return response.json()  # { id, email, role, ... }

async def require_organizer(user: dict = Depends(get_current_user)):
    """Only allow users with role = organizer."""
    if user.get("role") != "organizer":
        raise HTTPException(
            status_code=403,
            detail="Only organizers can perform this action"
        )
    return user

# ─────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────

@router.post("", status_code=201)
async def create_event(body: EventCreate, user: dict = Depends(require_organizer)):
    """Create event. Calls registration-service to verify organizer role."""
    event = {
        **body.model_dump(),
        "seats_left": body.capacity,
        "organizer_id": user.get("id") or user.get("sub"),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    result = await db["events"].insert_one(event)
    event["_id"] = result.inserted_id

    await publish("event.created", {
        "event_id": str(result.inserted_id),
        "title": body.title,
    })

    return fix_id(event)


@router.get("")
async def list_events(category: Optional[str] = None, date: Optional[str] = None):
    """List all events. Public — no auth needed."""
    query = {}
    if category:
        query["category"] = category
    if date:
        query["starts_at"] = {"$gte": datetime.fromisoformat(date)}

    events = await db["events"].find(query).to_list(100)
    return [fix_id(e) for e in events]


@router.get("/{id}")
async def get_event(id: str):
    """Get one event by ID. Public."""
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid event ID")

    event = await db["events"].find_one({"_id": ObjectId(id)})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    return fix_id(event)


@router.patch("/{id}")
async def update_event(
    id: str, body: EventUpdate, user: dict = Depends(require_organizer)
):
    """Update event. Only the organizer who created it."""
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid event ID")

    event = await db["events"].find_one({"_id": ObjectId(id)})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    organizer_id = user.get("id") or user.get("sub")
    if str(event["organizer_id"]) != str(organizer_id):
        raise HTTPException(status_code=403, detail="You can only update your own events")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updates["updated_at"] = datetime.utcnow()

    await db["events"].update_one({"_id": ObjectId(id)}, {"$set": updates})
    updated = await db["events"].find_one({"_id": ObjectId(id)})

    await publish("event.updated", {
        "event_id": id,
        "changes": list(updates.keys()),
    })

    return fix_id(updated)


@router.delete("/{id}", status_code=204)
async def delete_event(id: str, user: dict = Depends(require_organizer)):
    """Cancel event. Only the organizer who created it."""
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid event ID")

    event = await db["events"].find_one({"_id": ObjectId(id)})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    organizer_id = user.get("id") or user.get("sub")
    if str(event["organizer_id"]) != str(organizer_id):
        raise HTTPException(status_code=403, detail="You can only delete your own events")

    await db["events"].delete_one({"_id": ObjectId(id)})

    await publish("event.cancelled", {"event_id": id})


@router.get("/{id}/availability")
async def get_availability(id: str):
    """Seats left. Called by registration-service."""
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid event ID")

    event = await db["events"].find_one(
        {"_id": ObjectId(id)},
        {"seats_left": 1, "capacity": 1}
    )
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    return {
        "event_id": id,
        "seats_left": event["seats_left"],
        "capacity": event["capacity"],
    }


@router.post("/{id}/reserve", status_code=200)
async def reserve_seat(id: str):
    """Reduce seats_left by 1 atomically."""
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid event ID")

    result = await db["events"].update_one(
        {"_id": ObjectId(id), "seats_left": {"$gt": 0}},
        {"$inc": {"seats_left": -1}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=409, detail="No seats available")

    return {"message": "Seat reserved"}


@router.post("/{id}/release", status_code=200)
async def release_seat(id: str):
    """Add 1 seat back when booking is cancelled."""
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid event ID")

    result = await db["events"].update_one(
        {"_id": ObjectId(id)},
        {"$inc": {"seats_left": 1}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Event not found")

    return {"message": "Seat released"}

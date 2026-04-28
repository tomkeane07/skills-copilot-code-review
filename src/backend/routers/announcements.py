"""
Announcement endpoints for the High School Management System API
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import logging

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..database import announcements_collection, teachers_collection

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)

DATE_FORMAT = "%Y-%m-%d"


class AnnouncementPayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=600)
    expiration_date: str = Field(..., description="Required, YYYY-MM-DD")
    start_date: Optional[str] = Field(None, description="Optional, YYYY-MM-DD")


def _parse_date(value: str, field_name: str) -> datetime:
    try:
        return datetime.strptime(value, DATE_FORMAT)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be a valid date in YYYY-MM-DD format"
        ) from exc


def _validate_signed_in_user(username: Optional[str]) -> Dict[str, Any]:
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required for this action")

    teacher = teachers_collection.find_one({"_id": username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")

    return teacher


def _validate_announcement_dates(start_date: Optional[str], expiration_date: str) -> None:
    expiration = _parse_date(expiration_date, "expiration_date")
    if start_date:
        start = _parse_date(start_date, "start_date")
        if start > expiration:
            raise HTTPException(
                status_code=400,
                detail="start_date cannot be later than expiration_date"
            )


def _serialize_announcement(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "message": doc["message"],
        "start_date": doc.get("start_date"),
        "expiration_date": doc["expiration_date"],
        "created_by": doc.get("created_by", "unknown"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at")
    }


@router.get("", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Get announcements that are currently active and not expired."""
    today = datetime.utcnow().strftime(DATE_FORMAT)

    query = {
        "expiration_date": {"$gte": today},
        "$or": [
            {"start_date": None},
            {"start_date": {"$exists": False}},
            {"start_date": {"$lte": today}}
        ]
    }

    announcements = announcements_collection.find(query).sort("expiration_date", 1)
    return [_serialize_announcement(doc) for doc in announcements]


@router.get("/all", response_model=List[Dict[str, Any]])
def get_all_announcements(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Get all announcements for management views, requires authentication."""
    _validate_signed_in_user(teacher_username)
    announcements = announcements_collection.find({}).sort("created_at", -1)
    return [_serialize_announcement(doc) for doc in announcements]


@router.post("", response_model=Dict[str, Any])
def create_announcement(payload: AnnouncementPayload, teacher_username: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Create a new announcement, requires authentication."""
    teacher = _validate_signed_in_user(teacher_username)
    _validate_announcement_dates(payload.start_date, payload.expiration_date)

    now = datetime.utcnow().strftime(DATE_FORMAT)
    announcement = {
        "message": payload.message.strip(),
        "start_date": payload.start_date,
        "expiration_date": payload.expiration_date,
        "created_by": teacher["_id"],
        "created_at": now,
        "updated_at": now
    }

    try:
        result = announcements_collection.insert_one(announcement)
        created = announcements_collection.find_one({"_id": result.inserted_id})
        return _serialize_announcement(created)
    except Exception:
        logger.exception("Failed to create announcement")
        raise HTTPException(status_code=500, detail="Unable to create announcement right now")


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    payload: AnnouncementPayload,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Update an existing announcement, requires authentication."""
    _validate_signed_in_user(teacher_username)
    _validate_announcement_dates(payload.start_date, payload.expiration_date)

    if not ObjectId.is_valid(announcement_id):
        raise HTTPException(status_code=400, detail="Invalid announcement id")

    now = datetime.utcnow().strftime(DATE_FORMAT)
    updates = {
        "message": payload.message.strip(),
        "start_date": payload.start_date,
        "expiration_date": payload.expiration_date,
        "updated_at": now
    }

    try:
        result = announcements_collection.update_one(
            {"_id": ObjectId(announcement_id)},
            {"$set": updates}
        )
    except Exception:
        logger.exception("Failed to update announcement")
        raise HTTPException(status_code=500, detail="Unable to update announcement right now")

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    updated = announcements_collection.find_one({"_id": ObjectId(announcement_id)})
    return _serialize_announcement(updated)


@router.delete("/{announcement_id}")
def delete_announcement(announcement_id: str, teacher_username: Optional[str] = Query(None)) -> Dict[str, str]:
    """Delete an announcement, requires authentication."""
    _validate_signed_in_user(teacher_username)

    if not ObjectId.is_valid(announcement_id):
        raise HTTPException(status_code=400, detail="Invalid announcement id")

    try:
        result = announcements_collection.delete_one({"_id": ObjectId(announcement_id)})
    except Exception:
        logger.exception("Failed to delete announcement")
        raise HTTPException(status_code=500, detail="Unable to delete announcement right now")

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}

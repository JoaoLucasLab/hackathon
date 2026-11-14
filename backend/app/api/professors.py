"""STUB (ENG-01). Real code: DATA-05 (professors) and AI-03 (favorites)."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from app.api import fixture_data
from app.contracts import FavoriteProfessor, FavoriteUpdate, Professor

router = APIRouter(prefix="/api", tags=["professors"])


@router.get("/professors", response_model=list[Professor])
def list_professors(q: str | None = None) -> list[Professor]:
    profs = fixture_data.professors()
    if not q:
        return profs
    needle = q.lower()
    return [
        p
        for p in profs
        if needle in f"{p.first_name} {p.last_name}".lower()
        or needle in p.department.lower()
        or any(needle in c.lower() for c in p.winter_courses)
    ]


@router.get("/professors/{professor_id}", response_model=Professor)
def get_professor(professor_id: str) -> Professor:
    prof = fixture_data.professor_by_id().get(professor_id)
    if prof is None:
        raise HTTPException(status_code=404, detail="Professor not found")
    return prof


@router.put("/professors/{professor_id}/favorite", response_model=FavoriteProfessor)
def set_favorite(professor_id: str, body: FavoriteUpdate) -> FavoriteProfessor:
    if professor_id not in fixture_data.professor_by_id():
        raise HTTPException(status_code=404, detail="Professor not found")
    # STUB: not persisted; AI-03 stores it per session.
    return FavoriteProfessor(
        professor_id=professor_id, favorite=body.favorite, updated_at=datetime.now(UTC)
    )

"""Professors from `catalog_data` (the Course Search instructors in Postgres, or the
fixtures), with the public directory profile scripts/populate_db.py attached (DATA-05:
bio, sources, research flag, topic tags). Favorites are AI-03.

Favorites live in memory, keyed by the `sid` cookie (the same key as the chat
session), until DATA-01 adds the database. The chat's ToolContext holds the very
same set object, so starring in the UI and through `toggle_favorite_professor`
always agree.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from app.api import catalog_data
from app.contracts import FavoriteProfessor, FavoriteUpdate, Professor

router = APIRouter(prefix="/api", tags=["professors"])

_favorites: dict[str, set[str]] = {}


def session_id(request: Request) -> str:
    return request.cookies.get("sid", "local")


def favorites_for(sid: str) -> set[str]:
    """The live favorite set for a session (shared, not a copy)."""
    return _favorites.setdefault(sid, set())


def find_professors(q: str | None = None) -> list[Professor]:
    profs = catalog_data.professors()
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


def professor_or_404(professor_id: str) -> Professor:
    prof = catalog_data.professor_by_id().get(professor_id)
    if prof is None:
        raise HTTPException(status_code=404, detail="Professor not found")
    return prof


def save_favorite(favorites: set[str], professor_id: str, favorite: bool) -> FavoriteProfessor:
    professor_or_404(professor_id)
    if favorite:
        favorites.add(professor_id)
    else:
        favorites.discard(professor_id)
    return FavoriteProfessor(
        professor_id=professor_id, favorite=favorite, updated_at=datetime.now(UTC)
    )


def marked(prof: Professor, favorites: set[str]) -> Professor:
    return prof.model_copy(update={"is_favorite": prof.id in favorites})


@router.get("/professors", response_model=list[Professor])
def list_professors(request: Request, q: str | None = None) -> list[Professor]:
    favorites = favorites_for(session_id(request))
    return [marked(p, favorites) for p in find_professors(q)]


@router.get("/professors/{professor_id}", response_model=Professor)
def get_professor(professor_id: str, request: Request) -> Professor:
    return marked(professor_or_404(professor_id), favorites_for(session_id(request)))


@router.put("/professors/{professor_id}/favorite", response_model=FavoriteProfessor)
def set_favorite(professor_id: str, body: FavoriteUpdate, request: Request) -> FavoriteProfessor:
    return save_favorite(favorites_for(session_id(request)), professor_id, body.favorite)

from fastapi import APIRouter

from app.api import admin, audit, chat, me, mentors, professors, schedules, session

routers: list[APIRouter] = [
    session.router,
    audit.router,
    chat.router,
    schedules.router,
    professors.router,
    mentors.router,
    me.router,
    admin.router,
]

from fastapi import APIRouter

from app.api import admin, audit, chat, explain, me, mentors, professors, schedules, session

routers: list[APIRouter] = [
    session.router,
    audit.router,
    chat.router,
    schedules.router,
    explain.router,
    professors.router,
    mentors.router,
    me.router,
    admin.router,
]

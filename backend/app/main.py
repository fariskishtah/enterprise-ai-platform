"""ASGI entrypoint for the backend service."""

from app.core.application import create_app

app = create_app()

"""ASGI entrypoint: ``uvicorn deno_api.main:app``."""

from deno_api.app import create_app

app = create_app()

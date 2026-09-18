"""Pydantic schemas for Aetherfall request/response validation.

Phase 1 placeholder.
"""

from pydantic import BaseModel


class HealthCheckResponse(BaseModel):
    status: str
    app: str
    environment: str
    database_configured: bool

"""Dify-to-adapter Bearer authentication."""

import secrets
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.errors import AdapterError

bearer_scheme = HTTPBearer(auto_error=False)


async def authenticate(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    """Require the configured adapter Bearer token."""

    expected = request.app.state.settings.dify_adapter_api_key.get_secret_value()
    supplied = credentials.credentials if credentials is not None else ""
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not secrets.compare_digest(
            supplied,
            expected,
        )
    ):
        raise AdapterError(401, "unauthorized", "Invalid or missing Bearer token")

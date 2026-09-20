"""The signed-in account: profile, data export, deletion (GDPR)."""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Response, status

from deno_api.auth import AuthUser, current_user
from deno_api.deps import Scope
from deno_api.v1.schemas import MeOut
from deno_core.logging import get_logger
from deno_core.settings import get_settings

router = APIRouter(prefix="/me", tags=["account"])
log = get_logger(__name__)


@router.get("")
async def me(scope: Scope, user: Annotated[AuthUser, Depends(current_user)]) -> MeOut:
    profile = await scope.ensure_profile()
    return MeOut(
        id=scope.user_id, email=user.email, display_name=profile.display_name, plan=profile.plan, role=profile.role
    )


@router.get("/export")
async def export_data(scope: Scope) -> dict[str, Any]:
    """Everything Deno stores about you, as JSON."""
    return {"user_id": str(scope.user_id), "tables": await scope.export()}


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(scope: Scope) -> Response:
    """Hard-delete all your data, then your Supabase login.

    The web client signs out first; access tokens already issued expire on their own (short TTL).
    """
    await scope.delete_everything()
    await _delete_auth_user(str(scope.user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _delete_auth_user(user_id: str) -> None:
    settings = get_settings()
    secret = settings.supabase_secret_key.get_secret_value()
    if not settings.supabase_url or not secret:
        log.warning("auth_user_not_deleted_no_admin_key", user_id=user_id)
        return
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.delete(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users/{user_id}",
            headers={"apikey": secret, "Authorization": f"Bearer {secret}"},
        )
    if res.status_code not in (200, 204, 404):
        # Data is already gone (committed with this request); the login removal is retried by ops.
        log.error("auth_user_delete_failed", user_id=user_id, status=res.status_code)

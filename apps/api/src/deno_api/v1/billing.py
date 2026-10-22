"""Billing (ADR-012): Stripe Checkout + Customer Portal + webhooks. Deno never stores card data.

- Checkout and Portal return a Stripe-hosted URL; the browser goes there.
- The webhook is the only thing that changes a plan. It verifies Stripe's signature, records every event
  id in ``stripe_events`` first (idempotent: a replayed event is a no-op) and then updates
  ``subscriptions`` + ``profiles.plan``. A failed payment or cancelled subscription drops the account to
  Free: data stays, Pro limits go.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from deno_api.auth import AuthUser, current_user
from deno_api.deps import Scope, get_session
from deno_core.db import models as m
from deno_core.db.enums import Plan, UsageKind
from deno_core.logging import get_logger
from deno_core.settings import Settings, get_settings

router = APIRouter(prefix="/billing", tags=["billing"])
log = get_logger(__name__)
ACTIVE = {"active", "trialing"}


class UsageLine(BaseModel):
    kind: str
    used: int
    limit: int | None


class BillingOut(BaseModel):
    plan: Plan
    status: str
    current_period_end: datetime | None
    billing_enabled: bool
    usage: list[UsageLine]


class RedirectOut(BaseModel):
    url: str


def settings_of(request: Request) -> Settings:
    return getattr(request.app.state, "settings", None) or get_settings()


def stripe_client(settings: Settings) -> stripe.StripeClient:
    if not settings.billing_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not configured yet.")
    return stripe.StripeClient(settings.stripe_secret_key.get_secret_value())


@router.get("")
async def billing(scope: Scope, request: Request) -> BillingOut:
    profile = await scope.ensure_profile()
    sub = await scope.session.get(m.Subscription, scope.user_id)
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    quotas = {
        q.kind: q.monthly_limit
        for q in (await scope.session.execute(select(m.Quota).where(m.Quota.plan == profile.plan))).scalars()
    }
    usage = [
        UsageLine(kind=kind.value, used=await scope.usage_since(kind, month_start), limit=quotas.get(kind))
        for kind in (UsageKind.VALIDATION_RUN, UsageKind.CONTENT_PLAN, UsageKind.AUDIT)
    ]
    return BillingOut(
        plan=profile.plan,
        status=sub.status if sub else "active",
        current_period_end=sub.current_period_end if sub else None,
        billing_enabled=settings_of(request).billing_enabled,
        usage=usage,
    )


@router.post("/checkout")
async def checkout(scope: Scope, request: Request, user: Annotated[AuthUser, Depends(current_user)]) -> RedirectOut:
    settings = settings_of(request)
    client = stripe_client(settings)
    sub = await scope.session.get(m.Subscription, scope.user_id)
    params: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": settings.stripe_price_pro, "quantity": 1}],
        "client_reference_id": str(scope.user_id),
        "subscription_data": {"metadata": {"user_id": str(scope.user_id)}},
        "success_url": f"{settings.app_url}/app?billing=success",
        "cancel_url": f"{settings.app_url}/app?billing=cancelled",
        "allow_promotion_codes": True,
    }
    if sub and sub.stripe_customer_id:
        params["customer"] = sub.stripe_customer_id
    elif user.email:
        params["customer_email"] = user.email
    session = await client.v1.checkout.sessions.create_async(params=params)  # type: ignore[arg-type]
    if not session.url:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Stripe did not return a checkout page.")
    return RedirectOut(url=session.url)


@router.post("/portal")
async def portal(scope: Scope, request: Request) -> RedirectOut:
    settings = settings_of(request)
    client = stripe_client(settings)
    sub = await scope.session.get(m.Subscription, scope.user_id)
    if not sub or not sub.stripe_customer_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You don't have a paid subscription yet.")
    session = await client.v1.billing_portal.sessions.create_async(
        params={"customer": sub.stripe_customer_id, "return_url": f"{settings.app_url}/app"}
    )
    return RedirectOut(url=session.url)


# ---- webhook -------------------------------------------------------------------------------


async def _apply_subscription(session: AsyncSession, data: dict[str, Any], user_id: uuid.UUID | None) -> None:
    customer = str(data.get("customer") or "")
    existing = None
    if user_id is None and customer:
        existing = (
            await session.execute(select(m.Subscription).where(m.Subscription.stripe_customer_id == customer))
        ).scalar_one_or_none()
        user_id = existing.user_id if existing else None
    if user_id is None:
        log.warning("stripe_subscription_without_user", customer=customer)
        return
    sub_status = str(data.get("status") or "active")
    plan = Plan.PRO if sub_status in ACTIVE else Plan.FREE
    if plan == Plan.FREE and await session.get(m.Profile, user_id) is None:
        # A cancellation for an account that no longer exists (deleted, which cancels the subscription):
        # recording it would recreate a profile for a user who asked to be erased.
        log.info("stripe_subscription_for_deleted_user", status=sub_status)
        return
    period_end = data.get("current_period_end") or (data.get("items", {}).get("data") or [{}])[0].get(
        "current_period_end"
    )
    values = {
        "plan": plan,
        "status": sub_status,
        "stripe_customer_id": customer or None,
        "stripe_subscription_id": str(data.get("id") or "") or None,
        "current_period_end": datetime.fromtimestamp(int(period_end), UTC) if period_end else None,
    }
    await session.execute(
        insert(m.Subscription)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(index_elements=["user_id"], set_=values)
    )
    await session.execute(insert(m.Profile).values(id=user_id).on_conflict_do_nothing())
    profile = await session.get(m.Profile, user_id)
    if profile is not None and profile.plan != Plan.INTERNAL:
        profile.plan = plan
    log.info("subscription_updated", user_id=str(user_id), plan=plan.value, status=sub_status)


@router.post("/webhook", include_in_schema=False)
async def webhook(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> dict[str, str]:
    settings = settings_of(request)
    secret = settings.stripe_webhook_secret.get_secret_value()
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not configured yet.")
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature or "", secret)  # type: ignore[no-untyped-call]
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature.") from None
    inserted = await session.execute(
        insert(m.StripeEvent).values(id=event.id, type=event.type).on_conflict_do_nothing().returning(m.StripeEvent.id)
    )
    if inserted.scalar_one_or_none() is None:
        return {"status": "duplicate"}
    data: dict[str, Any] = (
        event.data.object.to_dict() if hasattr(event.data.object, "to_dict") else dict(event.data.object)
    )
    if event.type == "checkout.session.completed" and data.get("mode") == "subscription":
        ref = data.get("client_reference_id")
        user_id = uuid.UUID(ref) if ref else None
        if user_id and data.get("subscription"):
            client = stripe_client(settings)
            remote = await client.v1.subscriptions.retrieve_async(str(data["subscription"]))
            await _apply_subscription(session, remote.to_dict(), user_id)
    elif event.type in {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        meta = data.get("metadata") or {}
        user_id = uuid.UUID(meta["user_id"]) if meta.get("user_id") else None
        if event.type == "customer.subscription.deleted":
            data = {**data, "status": "canceled"}
        elif data.get("id"):
            # Stripe doesn't deliver events in order: a stale "updated: active" arriving after the
            # cancellation would hand a cancelled customer Pro again. Apply the subscription as it is now.
            remote = await stripe_client(settings).v1.subscriptions.retrieve_async(str(data["id"]))
            data = remote.to_dict()
        await _apply_subscription(session, data, user_id)
    elif event.type == "invoice.payment_failed":
        customer = str(data.get("customer") or "")
        sub = (
            await session.execute(select(m.Subscription).where(m.Subscription.stripe_customer_id == customer))
        ).scalar_one_or_none()
        if sub is not None:
            sub.status = "past_due"
            log.info("payment_failed", user_id=str(sub.user_id))
    event_row = await session.get(m.StripeEvent, event.id)
    if event_row is not None:
        event_row.processed_at = datetime.now(UTC)
    return {"status": "ok"}

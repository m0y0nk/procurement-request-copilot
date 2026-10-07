from __future__ import annotations

from decimal import Decimal, InvalidOperation

from src.contracts import ApprovalRequired
from rules.policy import APPROVAL_TIERS


def annual_amount(value: Decimal | int | str) -> Decimal:
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid annual cost: {value!r}") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("Annual cost must be a finite, non-negative amount.")
    return amount


def business_approval_chain(value: Decimal | int | str) -> list[ApprovalRequired]:
    amount = annual_amount(value)
    tier = next(
        tier for tier in APPROVAL_TIERS
        if tier.maximum_usd is None or amount <= tier.maximum_usd
    )
    return [
        ApprovalRequired(
            role=role,
            reason="Minimum business approver for the annual spend tier.",
            rule_id=tier.rule_id,
        )
        for role in tier.roles
    ]

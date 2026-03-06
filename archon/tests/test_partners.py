"""Tests for partner registry, revenue sharing, and viral loop attribution."""

from __future__ import annotations

import sqlite3
import time
import uuid
from datetime import date
from pathlib import Path

import pytest

from archon.partners.registry import PartnerRegistry
from archon.partners.revenue import RevenueShare
from archon.partners.viral_loop import ViralLoop, visitor_fingerprint


def _temp_path(prefix: str) -> Path:
    base = Path("archon/tests/_tmp_partners")
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{prefix}-{uuid.uuid4().hex[:8]}.sqlite3"


def test_partner_registry_register_unique_codes_and_duplicate_email() -> None:
    registry = PartnerRegistry(path=_temp_path("registry"))

    first = registry.register(name="Partner One", email="one@example.com", tier="affiliate")
    second = registry.register(name="Partner Two", email="two@example.com", tier="reseller")

    assert first.referral_code != second.referral_code
    assert len(first.referral_code) == 8
    assert first.referral_code.isalnum()

    with pytest.raises(ValueError):
        registry.register(name="Partner Dup", email="one@example.com", tier="affiliate")


def test_partner_registry_get_by_referral_code_and_status_update_persists() -> None:
    registry = PartnerRegistry(path=_temp_path("registry-status"))
    partner = registry.register(name="Partner A", email="a@example.com", tier="affiliate")

    found = registry.get_by_referral_code(partner.referral_code)
    assert found is not None
    assert found.partner_id == partner.partner_id

    updated = registry.update_status(partner.partner_id, "active", "KYC verified")
    reloaded = registry.get(partner.partner_id)

    assert updated.status == "active"
    assert reloaded is not None
    assert reloaded.status == "active"
    assert reloaded.metadata.get("status_reason") == "KYC verified"


@pytest.mark.parametrize(
    ("tier", "expected_percent"),
    [
        ("affiliate", 0.10),
        ("reseller", 0.25),
        ("enterprise_partner", 0.40),
    ],
)
def test_revenue_share_commission_percentage_by_tier(tier: str, expected_percent: float) -> None:
    registry = PartnerRegistry(path=_temp_path(f"registry-{tier}"))
    revenue = RevenueShare(registry=registry, path=_temp_path(f"revenue-{tier}"))

    partner = registry.register(name=f"{tier} partner", email=f"{tier}@example.com", tier=tier)
    attribution = revenue.attribute_customer(customer_id=f"customer-{tier}", referral_code=partner.referral_code)
    assert attribution.partner_id == partner.partner_id

    revenue.record_revenue(customer_id=f"customer-{tier}", amount_usd=1000.0, event_type="subscription")
    now = time.time()
    commission = revenue.calculate_commission(partner.partner_id, now - 60, now + 60)

    assert commission.partner_id == partner.partner_id
    assert commission.status == "pending"
    assert commission.amount_usd == round(1000.0 * expected_percent, 2)


def test_revenue_share_mark_paid_and_dashboard_totals() -> None:
    registry = PartnerRegistry(path=_temp_path("registry-dashboard"))
    revenue = RevenueShare(registry=registry, path=_temp_path("revenue-dashboard"))

    partner = registry.register(name="Dash Partner", email="dash@example.com", tier="affiliate")
    revenue.attribute_customer(customer_id="cust-1", referral_code=partner.referral_code)
    revenue.attribute_customer(customer_id="cust-2", referral_code=partner.referral_code)

    revenue.record_revenue(customer_id="cust-1", amount_usd=300.0, event_type="subscription")
    revenue.record_revenue(customer_id="cust-1", amount_usd=100.0, event_type="upsell")

    now = time.time()
    commission = revenue.calculate_commission(partner.partner_id, now - 60, now + 60)
    dashboard_before = revenue.get_dashboard(partner.partner_id)

    assert dashboard_before.attributed_customers == 2
    assert dashboard_before.total_revenue == 400.0
    assert dashboard_before.pending_commission == commission.amount_usd
    assert dashboard_before.paid_commission == 0.0
    assert dashboard_before.conversion_rate == 0.5

    paid = revenue.mark_paid(commission.commission_id, "bank-transfer-001")
    dashboard_after = revenue.get_dashboard(partner.partner_id)

    assert paid.status == "paid"
    assert "bank-transfer-001" in paid.transactions
    assert dashboard_after.pending_commission == 0.0
    assert dashboard_after.paid_commission == commission.amount_usd


def test_viral_loop_record_impression_and_conversion_linking() -> None:
    viral = ViralLoop(path=_temp_path("viral-basic"))

    hashed = visitor_fingerprint("203.0.113.10", "Mozilla/5.0", date(2026, 3, 6))
    impression = viral.record_impression(
        partner_id="partner-1",
        site_url="https://example.com",
        visitor_fingerprint=hashed,
    )
    conversion = viral.record_conversion(impression.impression_id, customer_id="cust-viral")

    assert impression.partner_id == "partner-1"
    assert conversion.impression_id == impression.impression_id
    assert conversion.partner_id == impression.partner_id


def test_viral_loop_conversion_outside_attribution_window_not_counted() -> None:
    db_path = _temp_path("viral-window")
    viral = ViralLoop(path=db_path, attribution_window_hours=72)

    impression = viral.record_impression(
        partner_id="partner-window",
        site_url="https://partner.site",
        visitor_fingerprint=visitor_fingerprint("198.51.100.10", "UA", date(2026, 3, 6)),
    )

    stale_ts = time.time() - (73 * 3600)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE impressions SET timestamp = ? WHERE impression_id = ?",
            (stale_ts, impression.impression_id),
        )

    viral.record_conversion(impression.impression_id, customer_id="cust-old")
    funnel = viral.get_funnel("partner-window")

    assert funnel.impressions == 1
    assert funnel.conversions == 0
    assert funnel.conversion_rate == 0.0


def test_viral_loop_funnel_conversion_rate_and_fingerprint_no_raw_ip() -> None:
    viral = ViralLoop(path=_temp_path("viral-funnel"), attribution_window_hours=72)

    raw_ip = "192.168.1.5"
    ua = "Mozilla/5.0"
    fingerprint = visitor_fingerprint(raw_ip, ua, date(2026, 3, 6))

    assert raw_ip not in fingerprint
    assert len(fingerprint) == 64

    first = viral.record_impression(
        partner_id="partner-funnel",
        site_url="https://alpha.example",
        visitor_fingerprint=fingerprint,
    )
    viral.record_impression(
        partner_id="partner-funnel",
        site_url="https://beta.example",
        visitor_fingerprint=visitor_fingerprint("192.168.1.6", ua, date(2026, 3, 6)),
    )
    viral.record_conversion(first.impression_id, customer_id="cust-1")

    funnel = viral.get_funnel("partner-funnel")
    assert funnel.impressions == 2
    assert funnel.conversions == 1
    assert funnel.conversion_rate == 0.5

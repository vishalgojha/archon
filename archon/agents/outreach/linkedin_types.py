"""LinkedIn outreach shared data models and parsing helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass(slots=True, frozen=True)
class LinkedInProfile:
    """LinkedIn profile model.

    Example: `LinkedInProfile("urn", "Ava", "", "", "", "", [])`.
    """

    urn: str
    name: str
    headline: str
    company: str
    location: str
    summary: str
    skills: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class ConnectionResult:
    """Connection-request result model.

    Example: `ConnectionResult("urn", "sent", "id-1")`.
    """

    to_urn: str
    status: str
    provider_request_id: str | None = None
    error: str | None = None


@dataclass(slots=True, frozen=True)
class SendResult:
    """Direct-message result model.

    Example: `SendResult("urn", "sent", "id-1").ok`.
    """

    to_urn: str
    status: str
    provider_message_id: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Success flag. Example: `SendResult("urn", "sent").ok`."""

        return self.status == "sent"


class NotConnectedError(RuntimeError):
    """Raised when trying to DM someone who is not connected."""

    def __init__(self, to_urn: str) -> None:
        super().__init__(f"Cannot send DM to {to_urn}: not connected.")
        self.to_urn = to_urn


def to_urn(linkedin_url_or_urn: str) -> str:
    """Normalize profile URL/slug/URN to URN. Example: `to_urn("linkedin.com/in/ava")`."""

    raw = str(linkedin_url_or_urn).strip()
    if raw.startswith("urn:li:person:"):
        return raw
    parsed = urlparse(raw)
    path = parsed.path.strip("/")
    slug = path.split("/", 1)[1].strip("/") if path.startswith("in/") else ""
    if not slug and raw and "://" not in raw and "/" not in raw:
        slug = raw
    if not slug and path:
        slug = path.split("/")[-1]
    return raw if raw.startswith("urn:") else f"urn:li:person:{slug or raw}"


def truncate_note(text: str, max_len: int) -> str:
    """Truncate note with ellipsis. Example: `truncate_note("x"*400, 300)`."""

    cleaned = str(text)
    if len(cleaned) <= max_len:
        return cleaned
    if max_len <= 3:
        return cleaned[:max_len]
    return f"{cleaned[: max_len - 3]}..."


def extract_elements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract list payload rows. Example: `extract_elements({"elements":[{}]})`."""

    rows = payload.get("elements")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def profile_from_payload(payload: dict[str, Any], *, fallback_urn: str) -> LinkedInProfile:
    """Parse profile payload. Example: `profile_from_payload({}, fallback_urn="urn")`."""

    first = str(payload.get("firstName") or payload.get("localizedFirstName") or "").strip()
    last = str(payload.get("lastName") or payload.get("localizedLastName") or "").strip()
    skills_raw = payload.get("skills") if isinstance(payload.get("skills"), list) else []
    skills = [
        str(item.get("name") if isinstance(item, dict) else item).strip() for item in skills_raw
    ]
    return LinkedInProfile(
        urn=to_urn(
            str(payload.get("urn") or payload.get("entityUrn") or payload.get("id") or fallback_urn)
        ),
        name=str(payload.get("name") or f"{first} {last}".strip()).strip(),
        headline=str(payload.get("headline") or "").strip(),
        company=str(payload.get("company") or payload.get("companyName") or "").strip(),
        location=str(payload.get("location") or payload.get("locationName") or "").strip(),
        summary=str(payload.get("summary") or "").strip(),
        skills=[item for item in skills if item],
    )


def profile_context(profile: LinkedInProfile) -> dict[str, Any]:
    """Build template context from profile. Example: `profile_context(profile)["name"]`."""

    return {
        "urn": profile.urn,
        "name": profile.name,
        "headline": profile.headline,
        "company": profile.company,
        "location": profile.location,
        "summary": profile.summary,
        "skills": ", ".join(profile.skills),
    }

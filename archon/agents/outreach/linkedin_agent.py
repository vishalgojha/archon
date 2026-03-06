"""Approval-gated LinkedIn outreach orchestrator."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.agents.outreach.email_agent import personalize
from archon.agents.outreach.linkedin_clients import (
    ConnectionAgent,
    MessageAgent,
    ProfileResearcher,
)
from archon.agents.outreach.linkedin_types import (
    ConnectionResult,
    LinkedInProfile,
    NotConnectedError,
    SendResult,
    profile_context,
    to_urn,
)
from archon.core.approval_gate import ApprovalGate
from archon.providers import ProviderRouter


class LinkedInAgent(BaseAgent):
    """Orchestrates profile research, connection requests, and DMs."""

    role = "fast"

    def __init__(
        self,
        router: ProviderRouter,
        approval_gate: ApprovalGate,
        *,
        researcher: ProfileResearcher | None = None,
        connection_agent: ConnectionAgent | None = None,
        message_agent: MessageAgent | None = None,
        campaign_delay_seconds: float = 0.0,
        name: str | None = None,
    ) -> None:
        """Create agent. Example: `LinkedInAgent(router, gate)`."""

        super().__init__(router, name=name or "LinkedInAgent")
        self.approval_gate = approval_gate
        self.researcher = researcher or ProfileResearcher()
        self.connection_agent = connection_agent or ConnectionAgent(
            approval_gate, self.researcher.access_token
        )
        self.message_agent = message_agent or MessageAgent(
            approval_gate,
            self.researcher.access_token,
            status_checker=self.connection_agent.check_connection_status,
        )
        self.campaign_delay_seconds = max(0.0, float(campaign_delay_seconds))
        self.send_log: list[dict[str, Any]] = []
        self._daily_sent: dict[str, int] = {}

    async def research_and_connect(
        self,
        linkedin_url: str,
        note_template: str,
        personalization: dict[str, Any] | None = None,
        *,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> ConnectionResult:
        """Fetch profile, personalize note, and send connection request."""

        profile = await self.researcher.fetch_profile(linkedin_url)
        context = {**profile_context(profile), **(personalization or {})}
        note = personalize(note_template, context)
        result = await self.connection_agent.send_connection_request(
            profile.urn,
            note,
            event_sink=event_sink,
            timeout_seconds=timeout_seconds,
        )
        self._audit(
            "connection_request",
            profile.urn,
            result.status,
            result.provider_request_id,
            result.error,
        )
        return result

    async def research_and_message(
        self,
        linkedin_url: str,
        message_template: str,
        personalization: dict[str, Any] | None = None,
        *,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> SendResult:
        """Fetch profile, personalize body, and send DM when connected."""

        profile = await self.researcher.fetch_profile(linkedin_url)
        context = {**profile_context(profile), **(personalization or {})}
        body = personalize(message_template, context)
        try:
            result = await self.message_agent.send_dm(
                profile.urn,
                body,
                event_sink=event_sink,
                timeout_seconds=timeout_seconds,
            )
        except NotConnectedError as exc:
            result = SendResult(profile.urn, "failed:not_connected", error=str(exc))
        self._audit("dm", profile.urn, result.status, result.provider_message_id, result.error)
        return result

    async def campaign(
        self,
        targets: list[str],
        message_template: str,
        max_per_day: int = 20,
        *,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> list[SendResult]:
        """Run daily-capped bulk outreach where each send is individually gated."""

        limit = max(0, int(max_per_day))
        day_key = datetime.now(timezone.utc).date().isoformat()
        sent_today = self._daily_sent.get(day_key, 0)
        results: list[SendResult] = []
        for idx, target in enumerate(targets):
            if sent_today >= limit:
                skipped = SendResult(to_urn(target), "skipped:daily_cap")
                results.append(skipped)
                self._audit("campaign_skip", skipped.to_urn, skipped.status, None, None)
                continue
            result = await self.research_and_message(
                target,
                message_template,
                personalization=None,
                event_sink=event_sink,
                timeout_seconds=timeout_seconds,
            )
            results.append(result)
            if result.status == "sent":
                sent_today += 1
                self._daily_sent[day_key] = sent_today
            if idx < len(targets) - 1 and self.campaign_delay_seconds > 0:
                await asyncio.sleep(self.campaign_delay_seconds)
        return results

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Run one default message action. Example: `await agent.run("x", ctx, "task")`."""

        del goal, task_id
        result = await self.research_and_message(
            str(context.get("linkedin_url", "")),
            str(context.get("message_template", "")),
            context.get("personalization")
            if isinstance(context.get("personalization"), dict)
            else None,
            event_sink=context.get("event_sink"),
        )
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=f"LinkedIn outreach status: {result.status}",
            confidence=95 if result.ok else 20,
            metadata={"send_result": asdict(result)},
        )

    def _audit(
        self,
        action: str,
        to_urn_value: str,
        status: str,
        message_id: str | None,
        error: str | None,
    ) -> None:
        self.send_log.append(
            {
                "to": to_urn_value,
                "action": action,
                "status": status,
                "provider": "linkedin",
                "message_id": message_id,
                "error": error,
            }
        )


__all__ = [
    "ConnectionAgent",
    "ConnectionResult",
    "LinkedInAgent",
    "LinkedInProfile",
    "MessageAgent",
    "NotConnectedError",
    "ProfileResearcher",
    "SendResult",
]

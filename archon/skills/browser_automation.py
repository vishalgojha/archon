"""Browser automation skill using Page Agent."""

from __future__ import annotations

import shutil
from typing import Any

from archon.agents.base_agent import BaseAgent
from archon.config import ArchonConfig
from archon.providers import ProviderRouter
from archon.skills.skill_registry import SkillDefinition, SkillRegistry

PAGE_AGENT_SCRIPT = """const { PageAgent } = require('page-agent');

async function main() {
    const config = JSON.parse(process.argv[2] || '{}');
    
    const agent = new PageAgent({
        model: config.model || 'qwen3.5-plus',
        baseURL: config.baseURL || 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        apiKey: config.apiKey || process.env.OPENAI_API_KEY,
        language: config.language || 'en-US',
    });

    const result = await agent.execute(config.task);
    console.log(JSON.stringify(result));
}

main().catch(e => {
    console.error(JSON.stringify({ error: e.message }));
    process.exit(1);
});
"""


class BrowserAutomationAgent(BaseAgent):
    """Browser automation agent using Page Agent."""

    role = "browser-automation"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self._check_page_agent()

    def _check_page_agent(self) -> bool:
        """Check if page-agent is available."""
        return shutil.which("npx") is not None

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute browser automation task."""
        task = context.get("task_description", "")
        url = context.get("url", "")

        if not task:
            return "Error: task_description is required"

        # Build the full task with URL if provided
        full_task = task
        if url:
            full_task = f"Go to {url} and {task}"

        # Use LLM to generate Page Agent command
        prompt = f"""Convert this browser task into a step-by-step automation plan:

Task: {full_task}

Provide:
1. URL to navigate to (if any)
2. Actions to perform (click, input, scroll, etc.)
3. Expected result
4. Any data to extract

Be specific about DOM elements (button text, input labels, etc.)."""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a browser automation planner. Convert natural language tasks into precise automation steps for Page Agent.",
        )

        return self._format_response(full_task, response.text, context)

    def _format_response(self, task: str, plan: str, context: dict[str, Any]) -> str:
        """Format the automation response."""
        return f"""🌐 Browser Automation - Page Agent

**Task:** {task}

**Automation Plan:**
{plan}

**To execute with Page Agent:**

```javascript
import {{ PageAgent }} from 'page-agent';

const agent = new PageAgent({{
    model: 'gpt-4o-mini',
    baseURL: process.env.OPENAI_BASE_URL,
    apiKey: process.env.OPENAI_API_KEY,
}});

await agent.execute('{task}');
```

**Or via Chrome Extension:**
1. Install Page Agent extension
2. Open target webpage
3. Type your task in the panel

🔗 Page Agent Docs: https://alibaba.github.io/page-agent/docs/introduction/overview
📦 NPM: https://www.npmjs.com/package/page-agent"""


class BrowserAutomationRegistration:
    """Register browser automation skill."""

    @staticmethod
    def register(
        registry: SkillRegistry, config: ArchonConfig, provider_router: ProviderRouter
    ) -> None:
        skill = SkillDefinition(
            name="browser-automation",
            description="Automate web browser tasks using natural language with Page Agent. Fill forms, click buttons, scrape data.",
            trigger_patterns=[
                "browser automation",
                "fill.*form",
                "click.*button",
                "automate.*browser",
                "web scraping",
                "page agent",
                "interact.*website",
                "navigate.*url",
            ],
            version="1.0.0",
            provider_preference="anthropic",
            cost_tier="standard",
            state="ACTIVE",
        )
        registry.register(skill)

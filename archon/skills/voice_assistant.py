"""Voice Assistant skill using ElevenLabs."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import BaseAgent
from archon.config import ArchonConfig
from archon.providers import ProviderRouter
from archon.skills.skill_registry import SkillDefinition, SkillRegistry


class VoiceAssistantAgent(BaseAgent):
    """Voice assistant agent using ElevenLabs TTS."""

    role = "voice-assistant"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        action = context.get("action", "speak")
        text = context.get("text", "")
        voice = context.get("voice", "rachel")
        language = context.get("language", "english")

        prompt = f"""Voice Assistant Configuration
Action: {action}
Text: {text[:200]}...
Voice: {voice}
Language: {language}

Provide:
1. Optimal voice settings for the content
2. SSML markup if needed (emphasis, breaks, etc.)
3. Token estimate for the text
4. Best practices for the content type"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a voice synthesis expert. Optimize text for speech synthesis with ElevenLabs.",
        )

        return f"""🔊 Voice Assistant - {action}

**Configuration:**
- Voice: {voice}
- Language: {language}
- Text length: {len(text)} characters
- Est. tokens: ~{len(text) // 4}

**Optimization Tips:**
{response.text}

**Usage:**
```python
from archon.voice.elevenlabs import VoiceAssistant

assistant = VoiceAssistant()
await assistant.speak("{text[:50]}...", save_to="output.mp3")
```

**ElevenLabs Quota:**
- Your account: 33M tokens available
- Cost per character: ~0.00001 tokens
- This request: ~{len(text)} tokens

🔗 ElevenLabs Dashboard: https://elevenlabs.io"""


class VoiceAssistantRegistration:
    """Register voice assistant skill."""

    @staticmethod
    def register(registry: SkillRegistry, config: ArchonConfig, provider_router: ProviderRouter) -> None:
        skill = SkillDefinition(
            name="voice-assistant",
            description="Text-to-speech and voice synthesis using ElevenLabs. Convert AI responses to natural speech.",
            trigger_patterns=[
                "voice assistant",
                "text to speech",
                "speak this",
                "elevenlabs",
                "tts",
                "hear.*response",
                "voice output",
            ],
            version="1.0.0",
            provider_preference="fast",
            cost_tier="standard",
            state="ACTIVE",
        )
        registry.register(skill)

"""Unit tests for Phase 1: Configuration, Events, State Machine, Model Abstraction, and Agent."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from jarvis.config import Settings
from jarvis.core.agent import JarvisAgent
from jarvis.core.state import AgentState, InvalidStateTransitionError, StateMachine
from jarvis.events import Event, EventBus, EventType
from jarvis.models.base import AIProvider, ModelResponse, ToolCallRequest, ToolDefinition
from jarvis.models.gemini import GeminiConfigurationError, GeminiProvider


class DummyProvider(AIProvider):
    """Test AIProvider that returns predictable responses."""

    def __init__(self, canned_response: str = "Test response") -> None:
        self.canned_response = canned_response
        self.call_count = 0
        self.last_prompt = ""

    async def generate(self, prompt: str, system_instruction: str | None = None, **kwargs) -> ModelResponse:
        self.call_count += 1
        self.last_prompt = prompt
        return ModelResponse(text=self.canned_response)

    async def stream(self, prompt: str, system_instruction: str | None = None, **kwargs):
        for word in self.canned_response.split():
            yield word + " "

    async def generate_with_tools(self, prompt: str, tools: list[ToolDefinition], **kwargs) -> ModelResponse:
        return ModelResponse(text=self.canned_response)

    async def analyze_image(self, prompt: str, image_bytes: bytes, **kwargs) -> ModelResponse:
        return ModelResponse(text="Analyzed")

    async def create_embedding(self, text: str, **kwargs) -> list[float]:
        return [0.1, 0.2, 0.3]


# ==============================================================================
# 1. Configuration Tests
# ==============================================================================

def test_settings_defaults():
    """Verify default settings configuration."""
    settings = Settings(gemini_api_key="")
    assert settings.jarvis_name == "JARVIS"
    assert settings.user_name == "Sir"
    assert settings.gemini_primary_model == "gemini-2.5-flash"
    assert not settings.is_gemini_configured


def test_settings_secret_masking():
    """Verify API key is masked in string representations to prevent leakage."""
    key = "AIzaSyDummySecretKey123456789012345"
    settings = Settings(gemini_api_key=key)
    assert settings.is_gemini_configured
    assert key not in str(settings)
    assert key not in repr(settings)
    assert settings.get_gemini_api_key() == key


# ==============================================================================
# 2. Event Bus Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_event_bus_publish_subscribe():
    """Verify that event bus dispatches events to registered handlers."""
    bus = EventBus()
    received_events: list[Event] = []

    def sync_handler(event: Event):
        received_events.append(event)

    bus.subscribe(EventType.USER_MESSAGE, sync_handler)
    await bus.emit(EventType.USER_MESSAGE, {"text": "hello"})

    assert len(received_events) == 1
    assert received_events[0].type == EventType.USER_MESSAGE.value
    assert received_events[0].data["text"] == "hello"


@pytest.mark.asyncio
async def test_event_bus_unsubscribe():
    """Verify unsubscribing prevents handler from receiving events."""
    bus = EventBus()
    received: list[Event] = []

    def handler(event: Event):
        received.append(event)

    bus.subscribe(EventType.AI_THINKING, handler)
    bus.unsubscribe(EventType.AI_THINKING, handler)
    await bus.emit(EventType.AI_THINKING, {"query": "test"})

    assert len(received) == 0


# ==============================================================================
# 3. State Machine Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_state_machine_valid_transitions():
    """Verify legal state transitions work and emit events."""
    bus = EventBus()
    transition_log: list[str] = []

    def on_change(event: Event):
        transition_log.append(f"{event.data['old_state']}->{event.data['new_state']}")

    bus.subscribe(EventType.AGENT_STATE_CHANGED, on_change)
    sm = StateMachine(event_bus=bus)

    assert sm.current_state == AgentState.IDLE
    await sm.transition_to(AgentState.THINKING, reason="user asked query")
    assert sm.current_state == AgentState.THINKING

    await sm.transition_to(AgentState.SPEAKING, reason="answer ready")
    assert sm.current_state == AgentState.SPEAKING

    await sm.transition_to(AgentState.IDLE, reason="spoken")
    assert sm.current_state == AgentState.IDLE

    assert transition_log == ["IDLE->THINKING", "THINKING->SPEAKING", "SPEAKING->IDLE"]


@pytest.mark.asyncio
async def test_state_machine_illegal_transition():
    """Verify that illegal transitions raise InvalidStateTransitionError."""
    sm = StateMachine()
    assert sm.current_state == AgentState.IDLE

    # IDLE directly to SPEAKING is illegal without THINKING/LISTENING
    with pytest.raises(InvalidStateTransitionError):
        await sm.transition_to(AgentState.SPEAKING)


# ==============================================================================
# 4. Gemini Provider Tests
# ==============================================================================

def test_gemini_provider_missing_key():
    """Verify GeminiProvider raises GeminiConfigurationError when key is empty."""
    with pytest.raises(GeminiConfigurationError):
        GeminiProvider(api_key="")

    with pytest.raises(GeminiConfigurationError):
        GeminiProvider(api_key="your_gemini_api_key_here")


def test_gemini_provider_response_parsing():
    """Verify Gemini response parsing with text and tool calls."""
    with patch("google.genai.Client"):
        provider = GeminiProvider(api_key="AIzaSyDummyKey12345678901234567890")

        # Mock raw Gemini response object
        raw_mock = MagicMock()
        raw_mock.text = "Here is the answer"
        fc_mock = MagicMock()
        fc_mock.name = "search_files"
        fc_mock.args = {"query": "test"}
        raw_mock.function_calls = [fc_mock]

        parsed = provider._parse_response(raw_mock)
        assert parsed.text == "Here is the answer"
        assert parsed.has_tool_calls
        assert len(parsed.tool_calls) == 1
        assert parsed.tool_calls[0].name == "search_files"
        assert parsed.tool_calls[0].arguments == {"query": "test"}


# ==============================================================================
# 5. JarvisAgent Loop Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_agent_process_turn():
    """Verify full agent conversational turn with state transitions."""
    bus = EventBus()
    states_observed: list[str] = []

    def record_state(event: Event):
        states_observed.append(event.data["new_state"])

    bus.subscribe(EventType.AGENT_STATE_CHANGED, record_state)

    provider = DummyProvider(canned_response="Hello, Sir. Systems optimal.")
    agent = JarvisAgent(ai_provider=provider, event_bus=bus)

    assert agent.current_state == AgentState.IDLE
    response = await agent.process_user_input("Status report")

    assert response == "Hello, Sir. Systems optimal."
    assert agent.current_state == AgentState.IDLE
    assert provider.call_count == 1
    assert "Status report" in provider.last_prompt

    # Verify state cycle: IDLE -> THINKING -> SPEAKING -> IDLE
    assert states_observed == ["THINKING", "SPEAKING", "IDLE"]


@pytest.mark.asyncio
async def test_agent_error_recovery():
    """Verify agent recovers to IDLE when the provider raises an exception."""
    class FailingProvider(AIProvider):
        async def generate(self, prompt: str, **kwargs) -> ModelResponse:
            raise RuntimeError("API Timeout")

        async def stream(self, prompt: str, **kwargs):
            yield ""

        async def generate_with_tools(self, prompt: str, tools: list, **kwargs) -> ModelResponse:
            raise RuntimeError("API Timeout")

        async def analyze_image(self, prompt: str, image_bytes: bytes, **kwargs) -> ModelResponse:
            raise RuntimeError("API Timeout")

        async def create_embedding(self, text: str, **kwargs) -> list[float]:
            raise RuntimeError("API Timeout")

    agent = JarvisAgent(ai_provider=FailingProvider())
    response = await agent.process_user_input("Trigger error")

    assert "encountered an error: API Timeout" in response
    # Agent must recover to IDLE and not stay stuck in ERROR
    assert agent.current_state == AgentState.IDLE


@pytest.mark.asyncio
async def test_agent_streaming():
    """Verify streaming response token collection."""
    provider = DummyProvider(canned_response="The quick brown fox")
    agent = JarvisAgent(ai_provider=provider)

    chunks = []
    async for chunk in agent.stream_user_input("Tell me a story"):
        chunks.append(chunk)

    assert len(chunks) > 0
    assert "".join(chunks).strip() == "The quick brown fox"
    assert agent.current_state == AgentState.IDLE

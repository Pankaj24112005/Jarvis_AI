"""Core JarvisAgent implementation coordinating reasoning, state, and interaction."""

import asyncio
from typing import Any, AsyncIterator
from jarvis.config import Settings, get_settings
from jarvis.core.state import AgentState, StateMachine
from jarvis.events import EventBus, EventType, default_event_bus
from jarvis.models.base import AIProvider, ModelResponse
from jarvis.utils.logging import logger


class JarvisAgent:
    """Primary JARVIS reasoning engine and conversation orchestrator."""

    DEFAULT_SYSTEM_INSTRUCTION = (
        "You are JARVIS (Just A Rather Very Intelligent System), a sophisticated, "
        "autonomous, polite, and highly capable personal AI operating assistant. "
        "You assist the user with intelligence, precision, brevity, and a calm, witty composure. "
        "Address the user respectfully (e.g. as 'Sir' or their configured name). "
        "Keep answers crisp and direct unless detailed technical depth is requested."
    )

    def __init__(
        self,
        ai_provider: AIProvider,
        settings: Settings | None = None,
        state_machine: StateMachine | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.ai_provider = ai_provider
        self.settings = settings or get_settings()
        self.event_bus = event_bus or default_event_bus
        self.state_machine = state_machine or StateMachine(event_bus=self.event_bus)

        # Simple conversational memory for Phase 1 (expanded in Phase 3)
        self.conversation_history: list[dict[str, str]] = []

    @property
    def current_state(self) -> AgentState:
        """Expose current operational state."""
        return self.state_machine.current_state

    def get_system_instruction(self) -> str:
        """Construct the customized system persona instruction."""
        return (
            f"{self.DEFAULT_SYSTEM_INSTRUCTION} "
            f"Your name is {self.settings.jarvis_name}. "
            f"The user's title or preferred name is {self.settings.user_name}."
        )

    async def process_user_input(self, user_text: str) -> str:
        """Process a single user turn, transitioning states and generating a response."""
        text = user_text.strip()
        if not text:
            return ""

        # Emit user message event
        await self.event_bus.emit(EventType.USER_MESSAGE, {"text": text})

        try:
            # Transition to THINKING
            await self.state_machine.transition_to(AgentState.THINKING, reason="Processing user prompt")
            await self.event_bus.emit(EventType.AI_THINKING, {"prompt": text})

            # Format conversation prompt
            prompt_with_context = self._format_conversation_context(text)

            # Generate response from model provider
            response: ModelResponse = await self.ai_provider.generate(
                prompt=prompt_with_context,
                system_instruction=self.get_system_instruction(),
            )

            # Check if model requested tools (designed for Phase 2 integration)
            if response.has_tool_calls:
                await self.state_machine.transition_to(
                    AgentState.TOOL_EXECUTION,
                    reason="Model requested tool execution",
                )
                output_text = await self._handle_tool_calls_phase1_stub(response)
            else:
                output_text = response.text

            # Update conversation history
            self.conversation_history.append({"role": "user", "content": text})
            self.conversation_history.append({"role": "assistant", "content": output_text})

            # Transition to SPEAKING
            await self.state_machine.transition_to(AgentState.SPEAKING, reason="Emitting final response")
            await self.event_bus.emit(EventType.AI_RESPONSE_COMPLETED, {"text": output_text})

            # Transition back to IDLE
            await self.state_machine.transition_to(AgentState.IDLE, reason="Turn finished")
            return output_text

        except Exception as ex:
            logger.error("Error processing agent turn: %s", ex, exc_info=True)
            await self.state_machine.transition_to(AgentState.ERROR, reason=str(ex))
            await self.event_bus.emit(EventType.ERROR_OCCURRED, {"error": str(ex)})
            await self.state_machine.transition_to(AgentState.IDLE, reason="Recovered from error")
            return f"I apologize, {self.settings.user_name}, but I encountered an error: {str(ex)}"

    async def stream_user_input(self, user_text: str) -> AsyncIterator[str]:
        """Stream response tokens for user input."""
        text = user_text.strip()
        if not text:
            return

        await self.event_bus.emit(EventType.USER_MESSAGE, {"text": text})

        try:
            await self.state_machine.transition_to(AgentState.THINKING, reason="Streaming prompt")
            prompt_with_context = self._format_conversation_context(text)

            full_chunks: list[str] = []
            async for chunk in self.ai_provider.stream(
                prompt=prompt_with_context,
                system_instruction=self.get_system_instruction(),
            ):
                full_chunks.append(chunk)
                await self.event_bus.emit(EventType.AI_RESPONSE_CHUNK, {"chunk": chunk})
                yield chunk

            output_text = "".join(full_chunks)
            self.conversation_history.append({"role": "user", "content": text})
            self.conversation_history.append({"role": "assistant", "content": output_text})

            await self.state_machine.transition_to(AgentState.SPEAKING, reason="Finished stream")
            await self.event_bus.emit(EventType.AI_RESPONSE_COMPLETED, {"text": output_text})
            await self.state_machine.transition_to(AgentState.IDLE, reason="Turn finished")

        except Exception as ex:
            logger.error("Error streaming agent turn: %s", ex, exc_info=True)
            await self.state_machine.transition_to(AgentState.ERROR, reason=str(ex))
            await self.state_machine.transition_to(AgentState.IDLE, reason="Recovered")
            yield f"\n[Error: {str(ex)}]"

    def _format_conversation_context(self, current_prompt: str) -> str:
        """Assemble recent conversation turns into the active context prompt."""
        if not self.conversation_history:
            return current_prompt

        # Keep last 10 messages for Phase 1 context window
        recent = self.conversation_history[-10:]
        context_lines: list[str] = []
        for msg in recent:
            role = "User" if msg["role"] == "user" else self.settings.jarvis_name
            context_lines.append(f"{role}: {msg['content']}")
        context_lines.append(f"User: {current_prompt}")
        return "\n".join(context_lines)

    async def _handle_tool_calls_phase1_stub(self, response: ModelResponse) -> str:
        """Phase 1 stub for tool calling - cleanly signals Phase 2 readiness."""
        names = [tc.name for tc in response.tool_calls]
        logger.info("Model requested tool calls (Phase 2 feature): %s", names)
        return (
            f"{response.text}\n"
            f"[Tool Request: {', '.join(names)} - Standardized Tool Execution activates in Phase 2]"
        )

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.conversation_history.clear()
        logger.debug("Cleared conversation history.")

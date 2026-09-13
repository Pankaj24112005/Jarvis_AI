"""Core JarvisAgent implementation coordinating reasoning, state, tools, and interaction."""

import asyncio
from typing import Any, AsyncIterator
from google.genai import types

from jarvis.config import Settings, get_settings
from jarvis.core.state import AgentState, StateMachine
from jarvis.events import EventBus, EventType, default_event_bus
from jarvis.models.base import AIProvider, ModelResponse
from jarvis.models.gemini import GeminiProvider
from jarvis.security.permissions import (
    PermissionController,
    PermissionLevel,
    default_permission_controller,
)
from jarvis.tools.base import ToolResult
from jarvis.tools.registry import ToolRegistry, default_tool_registry
from jarvis.utils.logging import logger


class JarvisAgent:
    """Primary JARVIS reasoning engine and conversation orchestrator with Tool Execution."""

    DEFAULT_SYSTEM_INSTRUCTION = (
        "You are JARVIS (Just A Rather Very Intelligent System), a sophisticated, "
        "autonomous, polite, and highly capable personal AI operating assistant. "
        "You assist the user with intelligence, precision, brevity, and a calm, witty composure. "
        "Address the user respectfully (e.g. as 'Sir' or their configured name). "
        "When performing tasks on the computer, use the tools provided to you. "
        "Never pretend to perform an action if you have a tool available to do it. "
        "If a tool fails or permission is denied, acknowledge the reason gracefully and adjust your plan."
    )

    def __init__(
        self,
        ai_provider: AIProvider,
        settings: Settings | None = None,
        state_machine: StateMachine | None = None,
        event_bus: EventBus | None = None,
        tool_registry: ToolRegistry | None = None,
        permission_controller: PermissionController | None = None,
        max_iterations: int = 10,
    ) -> None:
        self.ai_provider = ai_provider
        self.settings = settings or get_settings()
        self.event_bus = event_bus or default_event_bus
        self.state_machine = state_machine or StateMachine(event_bus=self.event_bus)
        self.tool_registry = tool_registry or default_tool_registry
        self.permission_controller = permission_controller or default_permission_controller
        self.max_iterations = max_iterations

        # Simple conversational memory for Phase 1 & 2
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
        """Process a user turn through reasoning, optional tool calling, and response."""
        text = user_text.strip()
        if not text:
            return ""

        await self.event_bus.emit(EventType.USER_MESSAGE, {"text": text})

        try:
            await self.state_machine.transition_to(AgentState.THINKING, reason="Processing user prompt")
            await self.event_bus.emit(EventType.AI_THINKING, {"prompt": text})

            gemini_tools = self.tool_registry.get_gemini_tools() if self.tool_registry else []

            # Check if live GeminiProvider with tools is active
            if isinstance(self.ai_provider, GeminiProvider) and gemini_tools:
                output_text = await self._run_gemini_tool_loop(text, gemini_tools)
            else:
                output_text = await self._run_standard_generation(text)

            # Update conversation history
            self.conversation_history.append({"role": "user", "content": text})
            self.conversation_history.append({"role": "assistant", "content": output_text})

            await self.state_machine.transition_to(AgentState.SPEAKING, reason="Emitting final response")
            await self.event_bus.emit(EventType.AI_RESPONSE_COMPLETED, {"text": output_text})
            await self.state_machine.transition_to(AgentState.IDLE, reason="Turn finished")
            return output_text

        except Exception as ex:
            logger.error("Error processing agent turn: %s", ex, exc_info=True)
            await self.state_machine.transition_to(AgentState.ERROR, reason=str(ex))
            await self.event_bus.emit(EventType.ERROR_OCCURRED, {"error": str(ex)})
            await self.state_machine.transition_to(AgentState.IDLE, reason="Recovered from error")
            return f"I apologize, {self.settings.user_name}, but I encountered an error: {str(ex)}"

    async def _run_gemini_tool_loop(self, user_prompt: str, gemini_tools: list[types.Tool]) -> str:
        """Run multi-turn tool-calling loop with Google Gemini."""
        provider: GeminiProvider = self.ai_provider  # type: ignore

        chat = provider.create_chat_session(
            tools=gemini_tools,
            system_instruction=self.get_system_instruction(),
        )

        current_message: Any = user_prompt
        final_text = ""
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1
            if iteration > 1:
                await self.state_machine.transition_to(
                    AgentState.THINKING,
                    reason=f"Gemini evaluating tool results (turn {iteration})",
                )

            response: ModelResponse = await provider.send_chat_message(chat, current_message)

            if not response.has_tool_calls:
                final_text = response.text
                break

            # Handle tool calls
            await self.state_machine.transition_to(
                AgentState.TOOL_EXECUTION,
                reason=f"Executing {len(response.tool_calls)} model tool requests",
            )

            tool_response_parts: list[Any] = []
            for tc in response.tool_calls:
                await self.event_bus.emit(EventType.TOOL_REQUESTED, {"tool": tc.name, "arguments": tc.arguments})

                tool_instance = self.tool_registry.get(tc.name)
                # If high-risk or critical, transition to WAITING_FOR_PERMISSION
                if tool_instance and (
                    tool_instance.permission_level >= self.permission_controller.confirmation_threshold
                    or tool_instance.permission_level == PermissionLevel.CRITICAL
                ):
                    await self.state_machine.transition_to(
                        AgentState.WAITING_FOR_PERMISSION,
                        reason=f"Awaiting confirmation for {tc.name}",
                    )

                # Execute tool through registry (evaluates permission & audit logs)
                tool_result: ToolResult = await self.tool_registry.execute(
                    tool_name=tc.name,
                    arguments=tc.arguments,
                    permission_controller=self.permission_controller,
                )

                await self.state_machine.transition_to(AgentState.TOOL_EXECUTION, reason="Tool execution finished")

                if tool_result.success:
                    await self.event_bus.emit(EventType.TOOL_EXECUTED, {"tool": tc.name, "result": tool_result.result})
                else:
                    await self.event_bus.emit(EventType.TOOL_FAILED, {"tool": tc.name, "error": tool_result.error})

                part = types.Part.from_function_response(
                    name=tc.name,
                    response=tool_result.to_dict(),
                )
                tool_response_parts.append(part)

            current_message = tool_response_parts

        if iteration >= self.max_iterations and not final_text:
            final_text = (
                f"I apologize, {self.settings.user_name}, but I reached the maximum "
                f"permitted tool execution limit ({self.max_iterations} steps)."
            )

        return final_text

    async def _run_standard_generation(self, user_prompt: str) -> str:
        """Run single-turn model generation without multi-turn tools."""
        prompt_with_context = self._format_conversation_context(user_prompt)
        response: ModelResponse = await self.ai_provider.generate(
            prompt=prompt_with_context,
            system_instruction=self.get_system_instruction(),
        )

        if response.has_tool_calls and self.tool_registry:
            # Handle mock tool calls if in test/simulation mode
            results = []
            for tc in response.tool_calls:
                res = await self.tool_registry.execute(
                    tool_name=tc.name,
                    arguments=tc.arguments,
                    permission_controller=self.permission_controller,
                )
                results.append(f"[{tc.name}: {'success' if res.success else res.error}]")
            return f"{response.text}\n" + "\n".join(results)

        return response.text

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

        recent = self.conversation_history[-10:]
        context_lines: list[str] = []
        for msg in recent:
            role = "User" if msg["role"] == "user" else self.settings.jarvis_name
            context_lines.append(f"{role}: {msg['content']}")
        context_lines.append(f"User: {current_prompt}")
        return "\n".join(context_lines)

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.conversation_history.clear()
        logger.debug("Cleared conversation history.")

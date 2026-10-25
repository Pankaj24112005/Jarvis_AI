"""Core JarvisAgent implementation coordinating reasoning, state, tools, and interaction."""

import asyncio
from typing import Any, AsyncIterator
from google.genai import types

from jarvis.config import Settings, get_settings
from jarvis.core.state import AgentState, StateMachine
from jarvis.events import EventBus, EventType, default_event_bus
from jarvis.memory import MemoryManager, default_memory_manager
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
    """Primary JARVIS reasoning engine and conversation orchestrator with Tool & Memory Execution."""

    DEFAULT_SYSTEM_INSTRUCTION = (
        "You are JARVIS (Just A Rather Very Intelligent System), a sophisticated, "
        "autonomous, polite, and highly capable personal AI operating assistant. "
        "You assist the user with intelligence, precision, brevity, and a calm, witty composure. "
        "Address the user respectfully (e.g. as 'Sir' or their configured name). "
        "When performing tasks on the computer, use the tools provided to you. "
        "Never pretend to perform an action if you have a tool available to do it. "
        "If a tool fails or permission is denied, acknowledge the reason gracefully and adjust your plan.\n\n"
        "Tool Selection Guidelines:\n"
        "- For closing an application or window gracefully (e.g. 'Close Chrome', 'Close Notepad', 'Close Calculator'), "
        "call 'close_application' with the application name. This is a low-risk graceful window close.\n"
        "- For closing a browser tab (e.g. 'Close this tab', 'Close current tab', 'Close YouTube tab'), call 'browser_control' "
        "with action='close_tab' (or 'youtube_control' with action='close_tab'). NEVER call 'close_application' or kill the browser for tab closures.\n"
        "- For force killing, terminating hung processes, or explicit kill requests (e.g. 'Kill Chrome', 'Force terminate Chrome', "
        "'Terminate process 1234'), call 'terminate_process'. This is a high-risk operation requiring user confirmation.\n"
        "- For inspecting the active window, foreground application, or working context (e.g. 'What application is open?', "
        "'What window am I using?', 'What am I working on?'), call 'get_active_application' or 'get_active_window'.\n"
        "- For inspecting or understanding what is currently on the screen (e.g. 'What is on my screen?', "
        "'Look at my screen and explain this error', 'What do you see on my screen?'), call 'analyze_screen'.\n"
        "- For clicking a specific visible UI element on the screen (e.g. 'Click the Submit button', 'Click the Search box'), "
        "call 'visual_grounding_click' with the target element description."
    )

    def __init__(
        self,
        ai_provider: AIProvider,
        settings: Settings | None = None,
        state_machine: StateMachine | None = None,
        event_bus: EventBus | None = None,
        tool_registry: ToolRegistry | None = None,
        permission_controller: PermissionController | None = None,
        memory_manager: MemoryManager | None = None,
        max_iterations: int = 10,
    ) -> None:
        self.ai_provider = ai_provider
        self.settings = settings or get_settings()
        self.event_bus = event_bus or default_event_bus
        self.state_machine = state_machine or StateMachine(event_bus=self.event_bus)
        self.tool_registry = tool_registry or default_tool_registry
        self.permission_controller = permission_controller or default_permission_controller
        self.memory_manager = memory_manager or default_memory_manager
        self.max_iterations = max_iterations

        # Conversational history synchronized with ShortTermMemory
        self.conversation_history: list[dict[str, str]] = []

    @property
    def current_state(self) -> AgentState:
        """Expose current operational state."""
        return self.state_machine.current_state

    def get_system_instruction(self, additional_context: str = "") -> str:
        """Construct the customized system persona instruction with injected context."""
        base = (
            f"{self.DEFAULT_SYSTEM_INSTRUCTION} "
            f"Your name is {self.settings.jarvis_name}. "
            f"The user's title or preferred name is {self.settings.user_name}."
        )
        if additional_context:
            return f"{base}\n\n{additional_context}"
        return base

    async def process_user_input(self, user_text: str) -> str:
        """Process a user turn through reasoning, optional tool calling, and response."""
        text = user_text.strip()
        if not text:
            return ""

        await self.event_bus.emit(EventType.USER_MESSAGE, {"text": text})

        # 1. Check if input is a direct memory command (e.g. "Remember that...", "What do you remember...")
        memory_cmd_response = self.memory_manager.handle_memory_command(text)
        if memory_cmd_response is not None:
            await self.state_machine.transition_to(AgentState.THINKING, reason="Processing memory command")
            self.memory_manager.record_turn(user_input=text, assistant_response=memory_cmd_response)
            self.conversation_history.append({"role": "user", "content": text})
            self.conversation_history.append({"role": "assistant", "content": memory_cmd_response})
            await self.state_machine.transition_to(AgentState.SPEAKING, reason="Emitting memory command response")
            await self.event_bus.emit(EventType.AI_RESPONSE_COMPLETED, {"text": memory_cmd_response})
            await self.state_machine.transition_to(AgentState.IDLE, reason="Memory command finished")
            return memory_cmd_response

        try:
            await self.state_machine.transition_to(AgentState.THINKING, reason="Processing user prompt")
            await self.event_bus.emit(EventType.AI_THINKING, {"prompt": text})

            # 2. Retrieve relevant memory and workspace context
            memory_context = self.memory_manager.build_augmented_context(text)

            gemini_tools = self.tool_registry.get_gemini_tools() if self.tool_registry else []
            tools_executed: list[str] = []

            # 3. Execute with Gemini
            if isinstance(self.ai_provider, GeminiProvider) and gemini_tools:
                output_text, tools_executed = await self._run_gemini_tool_loop(text, gemini_tools, memory_context)
            else:
                output_text, tools_executed = await self._run_standard_generation(text, memory_context)

            # 4. Record turn and evaluate episodic memory
            self.memory_manager.record_turn(
                user_input=text,
                assistant_response=output_text,
                tools_used=tools_executed,
            )
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

    async def _run_gemini_tool_loop(
        self,
        user_prompt: str,
        gemini_tools: list[types.Tool],
        memory_context: str = "",
    ) -> tuple[str, list[str]]:
        """Run multi-turn tool-calling loop with Google Gemini."""
        provider: GeminiProvider = self.ai_provider  # type: ignore

        chat = provider.create_chat_session(
            tools=gemini_tools,
            system_instruction=self.get_system_instruction(memory_context),
        )

        current_message: Any = user_prompt
        final_text = ""
        iteration = 0
        tools_executed: list[str] = []

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
                tools_executed.append(tc.name)
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

        return final_text, tools_executed

    async def _run_standard_generation(
        self,
        user_prompt: str,
        memory_context: str = "",
    ) -> tuple[str, list[str]]:
        """Run single-turn model generation without multi-turn tools."""
        prompt_with_context = self._format_conversation_context(user_prompt)
        response: ModelResponse = await self.ai_provider.generate(
            prompt=prompt_with_context,
            system_instruction=self.get_system_instruction(memory_context),
        )

        tools_executed: list[str] = []
        if response.has_tool_calls and self.tool_registry:
            # Handle mock tool calls if in test/simulation mode
            results = []
            for tc in response.tool_calls:
                tools_executed.append(tc.name)
                res = await self.tool_registry.execute(
                    tool_name=tc.name,
                    arguments=tc.arguments,
                    permission_controller=self.permission_controller,
                )
                results.append(f"[{tc.name}: {'success' if res.success else res.error}]")
            return f"{response.text}\n" + "\n".join(results), tools_executed

        return response.text, tools_executed

    async def stream_user_input(self, user_text: str) -> AsyncIterator[str]:
        """Stream response tokens for user input."""
        text = user_text.strip()
        if not text:
            return

        await self.event_bus.emit(EventType.USER_MESSAGE, {"text": text})

        memory_cmd_response = self.memory_manager.handle_memory_command(text)
        if memory_cmd_response is not None:
            await self.state_machine.transition_to(AgentState.THINKING, reason="Processing memory command")
            self.memory_manager.record_turn(user_input=text, assistant_response=memory_cmd_response)
            self.conversation_history.append({"role": "user", "content": text})
            self.conversation_history.append({"role": "assistant", "content": memory_cmd_response})
            await self.state_machine.transition_to(AgentState.SPEAKING, reason="Emitting memory command response")
            await self.event_bus.emit(EventType.AI_RESPONSE_CHUNK, {"chunk": memory_cmd_response})
            await self.event_bus.emit(EventType.AI_RESPONSE_COMPLETED, {"text": memory_cmd_response})
            await self.state_machine.transition_to(AgentState.IDLE, reason="Turn finished")
            yield memory_cmd_response
            return

        try:
            await self.state_machine.transition_to(AgentState.THINKING, reason="Streaming prompt")
            memory_context = self.memory_manager.build_augmented_context(text)
            prompt_with_context = self._format_conversation_context(text)

            full_chunks: list[str] = []
            async for chunk in self.ai_provider.stream(
                prompt=prompt_with_context,
                system_instruction=self.get_system_instruction(memory_context),
            ):
                full_chunks.append(chunk)
                await self.event_bus.emit(EventType.AI_RESPONSE_CHUNK, {"chunk": chunk})
                yield chunk

            output_text = "".join(full_chunks)
            self.memory_manager.record_turn(user_input=text, assistant_response=output_text)
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
        # Use short-term memory if available, else local history
        short_term_context = self.memory_manager.short_term.get_formatted_context(
            assistant_name=self.settings.jarvis_name
        )
        if short_term_context:
            return f"{short_term_context}\nUser: {current_prompt}"

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
        """Clear conversation history across memory layers."""
        self.conversation_history.clear()
        self.memory_manager.short_term.clear()
        logger.debug("Cleared conversation history.")


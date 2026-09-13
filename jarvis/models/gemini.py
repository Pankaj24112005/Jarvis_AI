"""Google Gemini Model Provider implementation using the official google-genai SDK."""

import asyncio
from typing import Any, AsyncIterator
from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError

from jarvis.models.base import AIProvider, ModelResponse, ToolCallRequest, ToolDefinition
from jarvis.utils.logging import logger


class GeminiConfigurationError(Exception):
    """Raised when Gemini API key or required configuration is missing or invalid."""
    pass


class GeminiProvider(AIProvider):
    """Concrete AIProvider implementation communicating with Google Gemini via official SDK."""

    def __init__(
        self,
        api_key: str,
        primary_model: str = "gemini-2.5-flash",
        fast_model: str = "gemini-2.0-flash",
        embedding_model: str = "text-embedding-004",
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        if not api_key or not api_key.strip() or api_key.strip() == "your_gemini_api_key_here":
            raise GeminiConfigurationError(
                "GEMINI_API_KEY is missing or unconfigured. "
                "Please add a valid GEMINI_API_KEY to your .env file."
            )

        self.api_key = api_key.strip()
        self.primary_model = primary_model
        self.fast_model = fast_model
        self.embedding_model = embedding_model
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Initialize official Google GenAI Client
        self.client = genai.Client(api_key=self.api_key)
        logger.debug("Initialized GeminiProvider with primary model: %s", self.primary_model)

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Generate complete text response from Gemini."""
        target_model = model or self.primary_model
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
        )

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self.client.aio.models.generate_content(
                    model=target_model,
                    contents=prompt,
                    config=config,
                )
                return self._parse_response(response)
            except ClientError as err:
                logger.error("Gemini client error (non-retryable): %s", err.message if hasattr(err, "message") else str(err))
                raise
            except (APIError, ServerError) as err:
                logger.warning(
                    "Gemini API transient error on attempt %d/%d: %s",
                    attempt,
                    self.max_retries,
                    err.message if hasattr(err, "message") else str(err),
                )
                if attempt == self.max_retries:
                    raise
                await asyncio.sleep(self.retry_delay * (2 ** (attempt - 1)))

        raise RuntimeError("Exceeded maximum retry attempts for Gemini request.")

    async def stream(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream response tokens asynchronously from Gemini."""
        target_model = model or self.primary_model
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
        )

        try:
            stream_response = await self.client.aio.models.generate_content_stream(
                model=target_model,
                contents=prompt,
                config=config,
            )
            async for chunk in stream_response:
                if chunk.text:
                    yield chunk.text
        except Exception as ex:
            logger.error("Error during Gemini stream generation: %s", ex)
            raise

    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        system_instruction: str | None = None,
        temperature: float | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Generate response with structured function declarations."""
        target_model = model or self.primary_model

        # Build tool definitions for Gemini SDK
        function_declarations = []
        for t in tools:
            fd = types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters=t.parameters,
            )
            function_declarations.append(fd)

        gemini_tools = [types.Tool(function_declarations=function_declarations)] if function_declarations else None

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            tools=gemini_tools,
        )

        try:
            response = await self.client.aio.models.generate_content(
                model=target_model,
                contents=prompt,
                config=config,
            )
            return self._parse_response(response)
        except Exception as ex:
            logger.error("Error during Gemini tool-calling generation: %s", ex)
            raise

    async def analyze_image(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        system_instruction: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Analyze multimodal image content with prompt."""
        target_model = model or self.primary_model
        config = types.GenerateContentConfig(system_instruction=system_instruction)

        contents = [
            prompt,
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        ]

        try:
            response = await self.client.aio.models.generate_content(
                model=target_model,
                contents=contents,
                config=config,
            )
            return self._parse_response(response)
        except Exception as ex:
            logger.error("Error during Gemini image analysis: %s", ex)
            raise

    async def create_embedding(self, text: str, **kwargs: Any) -> list[float]:
        """Generate text embeddings using Gemini embedding model."""
        try:
            response = await self.client.aio.models.embed_content(
                model=self.embedding_model,
                contents=text,
            )
            # Response has embeddings attribute
            if hasattr(response, "embeddings") and response.embeddings:
                return response.embeddings[0].values
            return []
        except Exception as ex:
            logger.error("Error generating Gemini embedding: %s", ex)
            raise

    def _parse_response(self, response: Any) -> ModelResponse:
        """Parse raw Gemini response into standardized ModelResponse."""
        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []

        if hasattr(response, "text") and response.text:
            text_parts.append(response.text)

        # Check for function calls in response
        if hasattr(response, "function_calls") and response.function_calls:
            for fc in response.function_calls:
                tool_calls.append(
                    ToolCallRequest(
                        name=fc.name,
                        arguments=dict(fc.args) if fc.args else {},
                    )
                )

        return ModelResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            raw_response=response,
        )

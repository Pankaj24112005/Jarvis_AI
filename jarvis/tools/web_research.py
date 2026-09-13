"""Dedicated Web Research Tools: searching, retrieving, and extracting online information."""

import asyncio
from typing import Any
import httpx
from bs4 import BeautifulSoup
from jarvis.security.permissions import PermissionLevel
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.utils.logging import logger


class WebSearchTool(BaseTool):
    """Performs an internet search and returns relevant result URLs and snippets."""

    name = "web_search"
    description = "Search the internet for queries, topics, documentation, or news."
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Search query keywords or questions"},
                "max_results": {"type": "INTEGER", "description": "Maximum number of search results (default: 5)"},
            },
            "required": ["query"],
        }

    async def execute(self, query: str, max_results: int = 5, **kwargs) -> ToolResult:
        logger.info("Executing web search for: '%s'", query)
        results = []

        try:
            # Try googlesearch-python first
            from googlesearch import search
            loop = asyncio.get_running_loop()

            def do_search():
                urls = []
                for url in search(query, num_results=max_results):
                    urls.append(url)
                    if len(urls) >= max_results:
                        break
                return urls

            found_urls = await loop.run_in_executor(None, do_search)
            for idx, url in enumerate(found_urls, 1):
                results.append({"rank": idx, "url": url})

            return ToolResult(success=True, result={"query": query, "results": results, "count": len(results)})

        except Exception as ex:
            # Fallback to DuckDuckGo HTML endpoint
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://html.duckduckgo.com/html/",
                        params={"q": query},
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    soup = BeautifulSoup(resp.text, "html.parser")
                    links = soup.select(".result__url")[:max_results]
                    for idx, link in enumerate(links, 1):
                        results.append({"rank": idx, "url": link.get_text().strip()})

                return ToolResult(success=True, result={"query": query, "results": results, "count": len(results)})
            except Exception as fallback_err:
                return ToolResult(
                    success=False,
                    error=f"Web search failed for '{query}': {str(ex)} (fallback: {str(fallback_err)})",
                )


class FetchWebContentTool(BaseTool):
    """Fetches article text and structured metadata from a web page."""

    name = "fetch_web_content"
    description = "Fetch main article text, headers, and metadata from an internet URL."
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "URL of the webpage to extract"}
            },
            "required": ["url"],
        }

    async def execute(self, url: str, **kwargs) -> ToolResult:
        try:
            target_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(target_url, headers=headers)
                resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            for elem in soup(["script", "style", "nav", "footer", "header", "aside"]):
                elem.decompose()

            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            paragraphs = [p.get_text().strip() for p in soup.find_all(["p", "h1", "h2", "h3"]) if p.get_text().strip()]
            article_body = "\n\n".join(paragraphs[:30])

            return ToolResult(
                success=True,
                result={"url": target_url, "title": title, "content": article_body[:4000]},
            )
        except Exception as ex:
            return ToolResult(success=False, error=f"Failed to fetch web content from '{url}': {str(ex)}")

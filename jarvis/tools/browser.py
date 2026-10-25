"""Browser Automation Tools for navigating, reading web pages, and web actions."""

import asyncio
import webbrowser
from typing import Any
import httpx
from bs4 import BeautifulSoup
import atexit
from jarvis.security.permissions import PermissionLevel
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.utils.logging import logger

# Lazy singleton for WebDriver session if Selenium is active
_driver_instance = None


def _cleanup_driver() -> None:
    """Terminate any lingering headless browser session on exit."""
    global _driver_instance
    if _driver_instance is not None:
        try:
            _driver_instance.quit()
        except Exception:
            pass
        _driver_instance = None


atexit.register(_cleanup_driver)


class OpenBrowserTool(BaseTool):
    """Opens a URL in the system browser or an automated browser session."""

    name = "browser_open"
    description = "Open a URL in the web browser."
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "URL to open (e.g. https://www.google.com)"}
            },
            "required": ["url"],
        }

    async def execute(self, url: str, **kwargs) -> ToolResult:
        try:
            target_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
            loop = asyncio.get_running_loop()
            opened = await loop.run_in_executor(None, lambda: webbrowser.open(target_url))
            return ToolResult(success=True, result={"url": target_url, "opened": opened})
        except Exception as ex:
            return ToolResult(success=False, error=f"Failed to open browser for '{url}': {str(ex)}")


class ReadWebpageTool(BaseTool):
    """Fetches and extracts clean text content from a web URL."""

    name = "browser_read_page"
    description = "Fetch and read readable text content from a web page URL."
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "Web URL to read content from"},
                "max_chars": {"type": "INTEGER", "description": "Maximum characters to return (default: 5000)"},
            },
            "required": ["url"],
        }

    async def execute(self, url: str, max_chars: int = 5000, **kwargs) -> ToolResult:
        try:
            target_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(target_url, headers=headers)
                resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            # Remove scripts and styles
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()

            text = soup.get_text(separator=" ", strip=True)
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n... [Truncated: {len(text) - max_chars} characters omitted]"

            title = soup.title.string.strip() if soup.title and soup.title.string else ""

            return ToolResult(
                success=True,
                result={"url": target_url, "title": title, "text": text, "status_code": resp.status_code},
            )
        except Exception as ex:
            return ToolResult(success=False, error=f"Failed to read webpage '{url}': {str(ex)}")


class BrowserActionTool(BaseTool):
    """Performs an automated action (click, type, navigate, back) via Selenium if available."""

    name = "browser_action"
    description = "Perform browser interaction (navigate, click, type, back). Gated for safety."
    permission_level = PermissionLevel.MODERATE

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Action: 'navigate', 'click', 'type', or 'back'",
                },
                "target": {
                    "type": "STRING",
                    "description": "URL for navigate, or CSS selector / text for click/type",
                },
                "value": {
                    "type": "STRING",
                    "description": "Text value when action is 'type'",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, target: str = "", value: str = "", **kwargs) -> ToolResult:
        global _driver_instance
        try:
            # We initialize Selenium headless Chrome on demand
            if _driver_instance is None:
                from selenium import webdriver
                from selenium.webdriver.chrome.options import Options

                chrome_options = Options()
                chrome_options.add_argument("--headless=new")
                chrome_options.add_argument("--disable-gpu")
                chrome_options.add_argument("--no-sandbox")
                _driver_instance = webdriver.Chrome(options=chrome_options)

            loop = asyncio.get_running_loop()

            if action == "navigate":
                await loop.run_in_executor(None, lambda: _driver_instance.get(target))
                title = _driver_instance.title
                return ToolResult(success=True, result={"action": "navigate", "url": target, "title": title})

            elif action == "back":
                await loop.run_in_executor(None, lambda: _driver_instance.back())
                return ToolResult(success=True, result={"action": "back", "url": _driver_instance.current_url})

            elif action == "click":
                from selenium.webdriver.common.by import By
                elem = await loop.run_in_executor(
                    None, lambda: _driver_instance.find_element(By.CSS_SELECTOR, target)
                )
                await loop.run_in_executor(None, elem.click)
                return ToolResult(success=True, result={"action": "click", "selector": target})

            elif action == "type":
                from selenium.webdriver.common.by import By
                elem = await loop.run_in_executor(
                    None, lambda: _driver_instance.find_element(By.CSS_SELECTOR, target)
                )
                await loop.run_in_executor(None, lambda: elem.send_keys(value))
                return ToolResult(success=True, result={"action": "type", "selector": target, "value": value})

            else:
                return ToolResult(success=False, error=f"Unknown browser action '{action}'")

        except Exception as ex:
            return ToolResult(success=False, error=f"Browser action '{action}' failed: {str(ex)}")


class BrowserControlTool(BaseTool):
    """Controls desktop browser tabs and navigation without terminating the browser."""

    name = "browser_control"
    description = (
        "Control desktop browser navigation and tabs (e.g., 'close this tab', 'close current tab', "
        "'close YouTube tab', 'new tab', 'refresh', 'back'). "
        "Actions: 'close_tab', 'new_tab', 'refresh', 'back'. "
        "Does NOT close or terminate the browser application."
    )
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Browser tab or navigation action: 'close_tab', 'new_tab', 'refresh', 'back'",
                    "enum": ["close_tab", "new_tab", "refresh", "back"],
                },
                "target": {
                    "type": "STRING",
                    "description": "Optional tab/window title hint (e.g. 'YouTube', 'Chrome', 'GitHub')",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, target: str = "", **kwargs) -> ToolResult:
        norm_action = action.strip().lower()
        try:
            import pygetwindow as gw
            import pyautogui

            # 1. Locate the target browser window
            all_windows = [w for w in gw.getAllWindows() if w.title and w.title.strip()]
            browser_windows = []

            # Known browser indicators
            browser_keys = ["chrome", "edge", "firefox", "brave", "opera", "youtube"]

            target_lower = target.strip().lower() if target else ""

            if target_lower:
                for w in all_windows:
                    if target_lower in w.title.lower():
                        browser_windows.append(w)

            if not browser_windows:
                # Match any open browser window
                for w in all_windows:
                    w_lower = w.title.lower()
                    if any(bk in w_lower for bk in browser_keys):
                        browser_windows.append(w)

            # Fallback to active window
            active_win = gw.getActiveWindow()
            target_win = browser_windows[0] if browser_windows else active_win

            if not target_win:
                return ToolResult(
                    success=False,
                    error="No open browser window detected to execute browser action.",
                )

            # Bring window into focus
            try:
                if target_win.isMinimized:
                    target_win.restore()
                target_win.activate()
                await asyncio.sleep(0.2)
            except Exception:
                pass

            old_title = target_win.title

            if norm_action == "close_tab":
                pyautogui.hotkey("ctrl", "w")
                await asyncio.sleep(0.3)
                return ToolResult(
                    success=True,
                    result={
                        "action": "close_tab",
                        "status": "closed",
                        "target": target or "active_tab",
                        "window_title": old_title,
                        "success": True,
                    },
                )

            elif norm_action == "new_tab":
                pyautogui.hotkey("ctrl", "t")
                return ToolResult(success=True, result={"action": "new_tab", "status": "opened"})

            elif norm_action == "refresh":
                pyautogui.press("f5")
                return ToolResult(success=True, result={"action": "refresh", "status": "refreshed"})

            elif norm_action == "back":
                pyautogui.hotkey("alt", "left")
                return ToolResult(success=True, result={"action": "back", "status": "navigated_back"})

            else:
                return ToolResult(success=False, error=f"Unsupported browser_control action '{action}'.")

        except Exception as ex:
            logger.error("Browser control execution error: %s", ex)
            return ToolResult(success=False, error=f"Browser control failed: {str(ex)}")


"""YouTube & Media Control Tools for browser-based media playback and control."""

import asyncio
import re
import urllib.parse
import urllib.request
import webbrowser
from typing import Any
from jarvis.security.permissions import PermissionLevel
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.utils.logging import logger


class YouTubeControlTool(BaseTool):
    """Controls YouTube media playback in the browser.

    Supports:
    - 'play': searches YouTube, resolves the top video ID, and launches active playback.
    - 'pause': pauses playback on the active YouTube window.
    - 'resume': resumes playback on the active YouTube window.
    - 'stop': pauses or closes the active YouTube playback.
    - 'skip' / 'next': advances to the next YouTube video in playlist or queue.
    """

    name = "youtube_control"
    description = (
        "Control YouTube playback. Actions: 'play' (plays a song/video by search query), "
        "'pause', 'resume', 'stop', 'skip'."
    )
    permission_level = PermissionLevel.LOW_RISK

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Media action to perform: 'play', 'pause', 'resume', 'stop', 'skip', 'close_tab'",
                    "enum": ["play", "pause", "resume", "stop", "skip", "close_tab"],
                },
                "query": {
                    "type": "STRING",
                    "description": "Song title, artist, or video query to search and play (required for action='play')",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, query: str = "", **kwargs) -> ToolResult:
        normalized_action = action.strip().lower()

        try:
            if normalized_action == "play":
                if not query.strip():
                    return ToolResult(
                        success=False,
                        error="Action 'play' requires a 'query' parameter specifying what song or video to play.",
                    )
                return await self._handle_play(query.strip())

            elif normalized_action in ["pause", "resume", "stop", "skip", "close_tab"]:
                return await self._handle_window_control(normalized_action)

            else:
                return ToolResult(
                    success=False,
                    error=f"Unsupported action '{action}'. Supported actions: play, pause, resume, stop, skip, close_tab.",
                )

        except Exception as ex:
            logger.error("YouTubeControlTool execution error: %s", ex)
            return ToolResult(success=False, error=f"YouTube control failed: {str(ex)}")

    async def _handle_play(self, query: str) -> ToolResult:
        """Resolve query to a canonical video ID and launch playback in default browser."""
        # 1. Resolve top video ID from YouTube search endpoint asynchronously
        video_id, video_title = await asyncio.to_thread(self._resolve_top_video, query)

        if video_id:
            watch_url = f"https://www.youtube.com/watch?v={video_id}"
            webbrowser.open(watch_url)

            # Give browser a moment to register window
            await asyncio.sleep(1.0)
            verified = self._is_youtube_window_present()

            return ToolResult(
                success=True,
                result={
                    "action": "play",
                    "query": query,
                    "video_id": video_id,
                    "title": video_title or query,
                    "url": watch_url,
                    "status": "playing",
                    "window_detected": verified,
                    "autoplay_note": (
                        "Playback initiated. If browser autoplay restrictions temporarily pause audio, "
                        "click once on the browser window to enable sound."
                    ),
                },
            )
        else:
            # Fallback: open search results page if video ID could not be parsed
            encoded_query = urllib.parse.quote_plus(query)
            search_url = f"https://www.youtube.com/results?search_query={encoded_query}"
            webbrowser.open(search_url)

            return ToolResult(
                success=True,
                result={
                    "action": "play",
                    "query": query,
                    "url": search_url,
                    "status": "search_results_opened",
                    "requires_user_click": True,
                    "autoplay_note": (
                        "Opened YouTube search results. Please click the desired video to start playback."
                    ),
                },
            )

    def _resolve_top_video(self, query: str) -> tuple[str | None, str | None]:
        """Fetch YouTube search results page and extract the first video ID and title."""
        try:
            encoded_query = urllib.parse.quote_plus(query)
            search_url = f"https://www.youtube.com/results?search_query={encoded_query}"
            req = urllib.request.Request(
                search_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            # Extract video ID matching standard 11-char alphanumeric pattern
            # Ignore short videos or shorts if possible, match standard watch URL
            match = re.search(r'/watch\?v=([a-zA-Z0-9_-]{11})', html)
            video_id = match.group(1) if match else None

            # Attempt to extract title snippet
            title_match = re.search(r'"title":\{"runs":\[\{"text":"([^"]+)"', html)
            video_title = title_match.group(1) if title_match else None

            return video_id, video_title
        except Exception as ex:
            logger.warning("Failed to parse YouTube search page for query '%s': %s", query, ex)
            return None, None

    async def _handle_window_control(self, action: str) -> ToolResult:
        """Send keyboard shortcuts to active YouTube browser window."""
        try:
            import pygetwindow as gw
            import pyautogui
        except ImportError:
            return ToolResult(
                success=False,
                error="pygetwindow or pyautogui is not installed. Media window control unavailable.",
            )

        # Find window containing 'YouTube'
        youtube_windows = [
            w for w in gw.getAllWindows() if w.title and "youtube" in w.title.lower()
        ]

        if not youtube_windows:
            # Fallback: check for media keys
            if action in ["pause", "resume"]:
                try:
                    pyautogui.press("playpause")
                    return ToolResult(
                        success=True,
                        result={"action": action, "status": "sent_media_key", "key": "playpause"},
                    )
                except Exception:
                    pass
            return ToolResult(
                success=False,
                error="No open YouTube window detected in active desktop windows.",
            )

        target_win = youtube_windows[0]
        try:
            if target_win.isMinimized:
                target_win.restore()
            target_win.activate()
            await asyncio.sleep(0.3)
        except Exception:
            pass

        if action in ["pause", "resume"]:
            # 'k' is YouTube's universal pause/play toggle (does not scroll page like spacebar)
            pyautogui.press("k")
            status = "paused" if action == "pause" else "resumed"
        elif action == "stop":
            # Pause playback and optionally minimize
            pyautogui.press("k")
            status = "stopped"
        elif action == "skip":
            # Shift+N advances to next video on YouTube
            pyautogui.hotkey("shift", "n")
            status = "skipped"
        elif action == "close_tab":
            # Close active YouTube tab without closing entire browser
            pyautogui.hotkey("ctrl", "w")
            status = "tab_closed"
        else:
            status = "acknowledged"

        return ToolResult(
            success=True,
            result={
                "action": action,
                "status": status,
                "window_title": target_win.title,
            },
        )

    def _is_youtube_window_present(self) -> bool:
        """Check if any visible window has 'YouTube' in title."""
        try:
            import pygetwindow as gw
            for w in gw.getAllWindows():
                if w.title and "youtube" in w.title.lower():
                    return True
        except Exception:
            pass
        return False

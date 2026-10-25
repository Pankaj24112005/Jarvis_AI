# JARVIS Architectural Decisions

- Adopt official google-genai SDK (v2.8.0) as the exclusive model backend; eliminate any Claude/Anthropic dependency.
- Use gemini-3.8-flash as primary model and gemini-3.6-flash as fast fallback.
- Enforce 5-tier security model (Levels 0 to 4); Levels 3 and 4 strictly require interactive user confirmation before execution.
- Maintain read-only workspace inspection for Git and project state; never mutate Git repository automatically.
- Multi-tier memory separation: short-term (turns), working (task scratchpad), episodic (daily markdown logs), semantic (local knowledge vault), and project (.jarvis metadata).
- Automatic secret redaction for all persistent memory layers (API keys, passwords, bearer tokens).

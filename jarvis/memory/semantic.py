"""Semantic Memory Vault storing persistent facts, user preferences, and knowledge."""

import datetime
import math
import os
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from jarvis.memory.security import redact_secrets
from jarvis.utils.logging import logger

# Recognized semantic vault categories
VALID_CATEGORIES = ["Profile", "Projects", "Preferences", "Skills", "Knowledge"]


@dataclass
class MemoryFact:
    """Represents a discrete semantic fact or preference stored in the knowledge vault."""

    key: str
    category: str
    content: str
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_markdown(self) -> str:
        """Render fact with frontmatter header and body."""
        tags_str = ", ".join(self.tags)
        return (
            f"---\n"
            f"key: {self.key}\n"
            f"category: {self.category}\n"
            f"tags: [{tags_str}]\n"
            f"created_at: {self.created_at}\n"
            f"updated_at: {self.updated_at}\n"
            f"---\n\n"
            f"{self.content.strip()}\n"
        )


class BaseMemoryRetriever(ABC):
    """Abstract interface for memory relevance ranking, allowing future embedding plug-ins."""

    @abstractmethod
    def rank(
        self, query: str, facts: list[MemoryFact], top_k: int = 5
    ) -> list[tuple[float, MemoryFact]]:
        """Rank candidate facts against a query and return top_k (score, fact) pairs."""
        pass


class KeywordRelevanceRetriever(BaseMemoryRetriever):
    """Lightweight term-frequency and keyword-matching relevance ranker."""

    def rank(
        self, query: str, facts: list[MemoryFact], top_k: int = 5
    ) -> list[tuple[float, MemoryFact]]:
        query_clean = re.sub(r"[^\w\s]", " ", query.lower())
        query_terms = [t for t in query_clean.split() if len(t) > 2]

        if not query_terms or not facts:
            return []

        scored: list[tuple[float, MemoryFact]] = []
        for fact in facts:
            score = 0.0
            content_lower = fact.content.lower()
            key_lower = fact.key.lower()
            tags_lower = [t.lower() for t in fact.tags]

            for term in query_terms:
                # Direct key match receives high weight
                if term in key_lower:
                    score += 3.0
                # Tag match receives strong weight
                if any(term == tag for tag in tags_lower):
                    score += 2.5
                # Exact word appearance in body
                occurrences = len(re.findall(rf"\b{re.escape(term)}\b", content_lower))
                if occurrences > 0:
                    score += 1.0 + math.log1p(occurrences)
                elif term in content_lower:
                    score += 0.5

            if score > 0.0:
                scored.append((score, fact))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]


class SemanticMemory:
    """Local-first knowledge vault organizing facts across Profile, Projects, Preferences, Skills, and Knowledge."""

    def __init__(
        self,
        vault_dir: str | Path = "memory",
        retriever: BaseMemoryRetriever | None = None,
    ) -> None:
        self.vault_dir = Path(vault_dir)
        self.retriever = retriever or KeywordRelevanceRetriever()
        self._ensure_categories()

    def _ensure_categories(self) -> None:
        """Create category subdirectories if missing."""
        for cat in VALID_CATEGORIES:
            (self.vault_dir / cat).mkdir(parents=True, exist_ok=True)

    def _sanitize_key(self, key: str) -> str:
        """Convert key to safe filesystem slug."""
        slug = re.sub(r"[^\w\-]", "_", key.strip().lower())
        return slug.strip("_") or "unnamed_fact"

    def _normalize_category(self, category: str) -> str:
        """Match input category to valid title-cased directory name."""
        cat_lower = category.strip().lower()
        for valid in VALID_CATEGORIES:
            if valid.lower() == cat_lower:
                return valid
        return "Knowledge"

    def store_fact(
        self,
        category: str,
        key: str,
        content: str,
        tags: list[str] | None = None,
    ) -> MemoryFact:
        """Store or update a persistent fact, redacting sensitive tokens and deduplicating."""
        clean_content = redact_secrets(content.strip())
        cat = self._normalize_category(category)
        slug = self._sanitize_key(key)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Deduplication check: inspect if existing fact with same slug exists
        file_path = self.vault_dir / cat / f"{slug}.md"
        existing = self.get_fact(cat, slug)

        created_at = existing.created_at if existing else now
        fact_tags = tags or (existing.tags if existing else [])

        # Add key terms to tags if empty
        if not fact_tags:
            fact_tags = [t for t in slug.split("_") if len(t) > 2]

        fact = MemoryFact(
            key=slug,
            category=cat,
            content=clean_content,
            tags=fact_tags,
            created_at=created_at,
            updated_at=now,
        )

        file_path.write_text(fact.to_markdown(), encoding="utf-8")
        logger.info("Stored semantic fact [%s/%s]", cat, slug)
        return fact

    def get_fact(self, category: str, key: str) -> MemoryFact | None:
        """Retrieve a specific fact by category and key."""
        cat = self._normalize_category(category)
        slug = self._sanitize_key(key)
        file_path = self.vault_dir / cat / f"{slug}.md"

        if not file_path.exists():
            return None

        try:
            return self._parse_fact_file(file_path)
        except Exception as ex:
            logger.warning("Error reading fact file %s: %s", file_path, ex)
            return None

    def update_fact(self, category: str, key: str, new_content: str) -> MemoryFact | None:
        """Update the content of an existing fact."""
        cat = self._normalize_category(category)
        slug = self._sanitize_key(key)
        existing = self.get_fact(cat, slug)

        if not existing:
            return None

        return self.store_fact(
            category=cat,
            key=slug,
            content=new_content,
            tags=existing.tags,
        )

    def forget_fact(self, category: str, key: str) -> bool:
        """Delete a persistent fact from the knowledge vault."""
        cat = self._normalize_category(category)
        slug = self._sanitize_key(key)
        file_path = self.vault_dir / cat / f"{slug}.md"

        if file_path.exists():
            try:
                file_path.unlink()
                logger.info("Deleted fact [%s/%s]", cat, slug)
                return True
            except Exception as ex:
                logger.error("Failed to delete fact %s: %s", file_path, ex)
                return False
        return False

    def list_all_facts(self, category: str | None = None) -> list[MemoryFact]:
        """List all facts across the vault or within a specific category."""
        facts: list[MemoryFact] = []
        categories = [self._normalize_category(category)] if category else VALID_CATEGORIES

        for cat in categories:
            cat_dir = self.vault_dir / cat
            if not cat_dir.exists():
                continue
            for path in cat_dir.glob("*.md"):
                try:
                    fact = self._parse_fact_file(path)
                    if fact:
                        facts.append(fact)
                except Exception as ex:
                    logger.debug("Skipping unparseable fact %s: %s", path, ex)

        return facts

    def search(
        self,
        query: str,
        category: str | None = None,
        top_k: int = 5,
    ) -> list[MemoryFact]:
        """Search the vault using the configured relevance ranker."""
        candidates = self.list_all_facts(category=category)
        ranked = self.retriever.rank(query=query, facts=candidates, top_k=top_k)
        return [fact for _, fact in ranked]

    def format_semantic_context(self, facts: list[MemoryFact], max_tokens: int = 800) -> str:
        """Format relevant facts into a concise context block for prompt injection."""
        if not facts:
            return ""

        lines = ["### Persistent Knowledge & User Preferences:"]
        approx_tokens = 0

        for fact in facts:
            line = f"- [{fact.category}/{fact.key}]: {fact.content}"
            tokens = len(line) // 4
            if approx_tokens + tokens > max_tokens:
                break
            lines.append(line)
            approx_tokens += tokens

        return "\n".join(lines)

    def _parse_fact_file(self, file_path: Path) -> MemoryFact | None:
        """Parse frontmatter and content from markdown fact file."""
        text = file_path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            # Plain file without frontmatter
            key = file_path.stem
            cat = file_path.parent.name
            return MemoryFact(key=key, category=cat, content=text.strip())

        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        frontmatter = parts[1]
        body = parts[2].strip()

        key = file_path.stem
        cat = file_path.parent.name
        tags: list[str] = []
        created_at = ""
        updated_at = ""

        for line in frontmatter.splitlines():
            line = line.strip()
            if line.startswith("key:"):
                key = line[4:].strip()
            elif line.startswith("category:"):
                cat = line[9:].strip()
            elif line.startswith("tags:"):
                tag_content = line[5:].strip().strip("[]")
                tags = [t.strip() for t in tag_content.split(",") if t.strip()]
            elif line.startswith("created_at:"):
                created_at = line[11:].strip()
            elif line.startswith("updated_at:"):
                updated_at = line[11:].strip()

        return MemoryFact(
            key=key,
            category=cat,
            content=body,
            tags=tags,
            created_at=created_at,
            updated_at=updated_at,
        )

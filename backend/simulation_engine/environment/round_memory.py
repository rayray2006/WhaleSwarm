"""Sliding-window round memory with LLM-based compaction.

Keeps recent rounds in full detail, compacts older rounds into narrative
summaries using the LLM, and batch-merges ancient rounds into a single
overview.  Compaction runs in a background thread so it never blocks
the simulation loop.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

FULL_DETAIL_WINDOW = 2
COMPACT_WINDOW = 3
MAX_ANCIENT_CHARS = 2000


class RoundMemory:
    """Manages round-level memory with three tiers of detail.

    Tier 1 (recent):  Last ``FULL_DETAIL_WINDOW`` rounds — full action-level detail.
    Tier 2 (compact): Next ``COMPACT_WINDOW`` older rounds — LLM-summarised to 2-3 sentences each.
    Tier 3 (ancient):  Everything older — batch-merged into a single narrative paragraph.
    """

    def __init__(self, llm_complete_fn: Optional[Callable] = None) -> None:
        self._entries: List[Dict[str, Any]] = []
        self._compacted: Dict[int, str] = {}
        self._ancient_summary: str = ""
        self._llm_fn = llm_complete_fn
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._lock = threading.Lock()

    def record(self, round_num: int, summary: str, detail: str) -> None:
        with self._lock:
            self._entries.append({
                "round": round_num,
                "summary": summary,
                "detail": detail,
                "ts": datetime.utcnow().isoformat(),
            })

        if round_num >= FULL_DETAIL_WINDOW and self._llm_fn is not None:
            self._pool.submit(self._compact_older_rounds, round_num)

    def build_context(self) -> str:
        with self._lock:
            entries = list(self._entries)
            compacted = dict(self._compacted)
            ancient = self._ancient_summary

        if not entries:
            return ""

        parts: List[str] = []

        if ancient:
            parts.append(f"=== EARLIER ROUNDS ===\n{ancient}")

        cutoff_compact = max(0, len(entries) - FULL_DETAIL_WINDOW)
        cutoff_ancient = max(0, cutoff_compact - COMPACT_WINDOW)

        for entry in entries[cutoff_ancient:cutoff_compact]:
            rn = entry["round"]
            text = compacted.get(rn, entry["summary"])
            parts.append(f"Round {rn}: {text}")

        for entry in entries[cutoff_compact:]:
            parts.append(f"--- Round {entry['round']} ---\n{entry['detail']}")

        return "\n\n".join(parts)

    def _compact_older_rounds(self, current_round: int) -> None:
        with self._lock:
            entries = list(self._entries)

        cutoff_compact = max(0, len(entries) - FULL_DETAIL_WINDOW)
        cutoff_ancient = max(0, cutoff_compact - COMPACT_WINDOW)

        for entry in entries[cutoff_ancient:cutoff_compact]:
            rn = entry["round"]
            with self._lock:
                if rn in self._compacted:
                    continue

            detail = entry["detail"]
            try:
                summary = self._llm_fn(
                    messages=[
                        {"role": "system", "content": (
                            "Summarise this simulation round in 2-3 sentences. "
                            "Keep key events, price movements, and sentiment shifts. "
                            "Be concise."
                        )},
                        {"role": "user", "content": detail[:3000]},
                    ],
                    smart=False,
                    temperature=0.3,
                    max_tokens=256,
                )
            except Exception:
                logger.debug("Compaction failed for round %d, using raw summary", rn)
                summary = entry["summary"]

            with self._lock:
                self._compacted[rn] = summary

        if cutoff_ancient > 0:
            self._merge_ancient(entries[:cutoff_ancient])

    def _merge_ancient(self, ancient_entries: List[Dict]) -> None:
        with self._lock:
            existing = self._ancient_summary

        if not ancient_entries:
            return

        lines = []
        if existing:
            lines.append(existing)
        for entry in ancient_entries:
            rn = entry["round"]
            with self._lock:
                text = self._compacted.get(rn, entry["summary"])
            lines.append(f"R{rn}: {text}")

        combined = " ".join(lines)

        if len(combined) > MAX_ANCIENT_CHARS and self._llm_fn is not None:
            try:
                combined = self._llm_fn(
                    messages=[
                        {"role": "system", "content": (
                            "Merge these round summaries into a single concise "
                            "paragraph (max 500 chars). Keep only the most "
                            "important events and trends."
                        )},
                        {"role": "user", "content": combined[:4000]},
                    ],
                    smart=False,
                    temperature=0.3,
                    max_tokens=256,
                )
            except Exception:
                combined = combined[:MAX_ANCIENT_CHARS]

        with self._lock:
            self._ancient_summary = combined
            for entry in ancient_entries:
                self._compacted.pop(entry["round"], None)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)

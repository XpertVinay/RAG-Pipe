"""Ultra-low-footprint in-memory L1 cache with bounded LRU eviction and lazy TTL expiration."""

import sys
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def utc_now() -> datetime:
    """Current UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass
class CachedMemoryEntry:
    """Compact in-memory slot representing a hot memory item."""
    id: str
    key: str
    scope: str
    memory_type: str
    user_id: Optional[str]
    room_id: Optional[str]
    document_id: Optional[str]
    document_hash: Optional[str]
    content: str
    importance: float
    expires_at: Optional[datetime]
    revaluated_at: Optional[datetime]
    revaluation_interval_seconds: int
    metadata_payload: Dict[str, Any]
    access_count: int
    last_accessed: float

    def approximate_bytes(self) -> int:
        """Estimate in-memory byte footprint accurately."""
        base_size = sys.getsizeof(self)
        str_sizes = (
            sys.getsizeof(self.id)
            + sys.getsizeof(self.key)
            + sys.getsizeof(self.content)
            + sys.getsizeof(self.scope)
            + sys.getsizeof(self.memory_type)
        )
        if self.user_id:
            str_sizes += sys.getsizeof(self.user_id)
        if self.document_id:
            str_sizes += sys.getsizeof(self.document_id)
        if self.document_hash:
            str_sizes += sys.getsizeof(self.document_hash)
        return base_size + str_sizes

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        """Check if memory has expired."""
        if self.expires_at is None:
            return False
        curr = now or utc_now()
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if curr.tzinfo is None:
            curr = curr.replace(tzinfo=timezone.utc)
        return curr > exp


class LowMemoryLRUCache:
    """Strictly bounded, memory-efficient L1 cache for active memory items."""

    def __init__(self, max_items: int = 512, max_bytes: int = 2 * 1024 * 1024):
        self.max_items = max_items
        self.max_bytes = max_bytes  # e.g., 2MB hard ceiling
        self._entries: OrderedDict[str, CachedMemoryEntry] = OrderedDict()
        self._total_bytes: int = 0
        self.hits: int = 0
        self.misses: int = 0

    def _make_cache_key(self, scope: str, key: str, user_id: Optional[str] = None) -> str:
        """Generate canonical key for L1 cache lookup."""
        uid = user_id or "global"
        return f"{scope}:{uid}:{key}"

    def get(self, scope: str, key: str, user_id: Optional[str] = None) -> Optional[CachedMemoryEntry]:
        """Fetch item from L1 cache with lazy TTL eviction."""
        cache_key = self._make_cache_key(scope, key, user_id)
        entry = self._entries.get(cache_key)

        if not entry:
            self.misses += 1
            return None

        # Check lazy expiration
        if entry.is_expired():
            self._evict_key(cache_key)
            self.misses += 1
            return None

        # Hit: Move to end (most recently used) and increment access
        self._entries.move_to_end(cache_key)
        entry.access_count += 1
        entry.last_accessed = time.time()
        self.hits += 1
        return entry

    def put(self, entry: CachedMemoryEntry) -> None:
        """Insert or update item in L1 cache, enforcing strict low-memory bounds."""
        cache_key = self._make_cache_key(entry.scope, entry.key, entry.user_id)

        # If already exists, evict old footprint before inserting updated
        if cache_key in self._entries:
            self._evict_key(cache_key)

        entry_bytes = entry.approximate_bytes()

        # Enforce capacity constraints
        while (len(self._entries) >= self.max_items or (self._total_bytes + entry_bytes) > self.max_bytes) and self._entries:
            self._evict_one()

        self._entries[cache_key] = entry
        self._total_bytes += entry_bytes

    def _evict_key(self, cache_key: str) -> None:
        """Evict a specific entry and reclaim byte counter."""
        entry = self._entries.pop(cache_key, None)
        if entry:
            self._total_bytes = max(0, self._total_bytes - entry.approximate_bytes())

    def _evict_one(self) -> None:
        """Evict one candidate: prefer expired items, else lowest importance LRU item."""
        now = utc_now()
        # Pass 1: Evict expired if any
        for k, v in list(self._entries.items()):
            if v.is_expired(now):
                self._evict_key(k)
                return

        # Pass 2: Evict least recently used (first item in OrderedDict)
        oldest_key, _ = self._entries.popitem(last=False)
        self._total_bytes = max(0, self._total_bytes - sys.getsizeof(oldest_key))

    def clear(self) -> None:
        """Flush in-memory cache."""
        self._entries.clear()
        self._total_bytes = 0

    def prune_expired(self) -> int:
        """Explicitly purge all expired items from L1 cache."""
        now = utc_now()
        pruned = 0
        for k, v in list(self._entries.items()):
            if v.is_expired(now):
                self._evict_key(k)
                pruned += 1
        return pruned

    def invalidate_document(self, document_id: str) -> int:
        """Invalidate entries tied to an updated or removed document."""
        count = 0
        for k, v in list(self._entries.items()):
            if v.document_id == document_id:
                self._evict_key(k)
                count += 1
        return count

    def get_stats(self) -> Dict[str, Any]:
        """Return low-memory footprint statistics."""
        return {
            "total_items": len(self._entries),
            "max_items": self.max_items,
            "total_bytes": self._total_bytes,
            "max_bytes": self.max_bytes,
            "hits": self.hits,
            "misses": self.misses,
        }

    def list_entries(self, scope: Optional[str] = None, user_id: Optional[str] = None) -> List[CachedMemoryEntry]:
        """Return list of active cached entries filtered by scope and user."""
        results: List[CachedMemoryEntry] = []
        now = utc_now()
        for entry in self._entries.values():
            if entry.is_expired(now):
                continue
            if scope and entry.scope != scope:
                continue
            if user_id is not None and entry.user_id != user_id:
                continue
            results.append(entry)
        return results

"""Memory distribution statistics calculation and performance metrics aggregation."""

from datetime import datetime, timezone
from typing import Any, Dict, List
from app.memory.schemas import MemoryDistributionStats, ScopeDistributionItem
from app.models.memory import MemoryItem, MemoryScope, MemoryType


def utc_now() -> datetime:
    """Current UTC datetime."""
    return datetime.now(timezone.utc)


class MemoryStatsCollector:
    """Computes distribution across memory quadrants, byte sizes, and cache hit metrics."""

    @classmethod
    def calculate_stats(
        cls,
        all_memories: List[MemoryItem],
        l1_stats: Dict[str, Any],
        now: datetime,
    ) -> MemoryDistributionStats:
        """Calculate complete 4-quadrant distribution matrix and memory performance metrics."""
        g_st = ScopeDistributionItem()
        g_lt = ScopeDistributionItem()
        u_st = ScopeDistributionItem()
        u_lt = ScopeDistributionItem()

        active_count = 0
        expired_count = 0
        reval_count = 0

        for m in all_memories:
            is_exp = m.is_expired(now)
            needs_rev = m.needs_revaluation(now=now)

            if is_exp:
                expired_count += 1
            else:
                active_count += 1

            if needs_rev:
                reval_count += 1

            approx_bytes = len(m.key) + len(m.content) + 128

            if m.scope == MemoryScope.GLOBAL.value:
                if m.memory_type == MemoryType.SHORT_TERM.value:
                    g_st.count += 1
                    g_st.estimated_bytes += approx_bytes
                    if len(g_st.sample_keys) < 4:
                        g_st.sample_keys.append(m.key)
                else:
                    g_lt.count += 1
                    g_lt.estimated_bytes += approx_bytes
                    if len(g_lt.sample_keys) < 4:
                        g_lt.sample_keys.append(m.key)
            else:
                if m.memory_type == MemoryType.SHORT_TERM.value:
                    u_st.count += 1
                    u_st.estimated_bytes += approx_bytes
                    if len(u_st.sample_keys) < 4:
                        u_st.sample_keys.append(m.key)
                else:
                    u_lt.count += 1
                    u_lt.estimated_bytes += approx_bytes
                    if len(u_lt.sample_keys) < 4:
                        u_lt.sample_keys.append(m.key)

        return MemoryDistributionStats(
            global_short_term=g_st,
            global_long_term=g_lt,
            user_short_term=u_st,
            user_long_term=u_lt,
            total_memories=len(all_memories),
            active_memories=active_count,
            expired_memories=expired_count,
            needs_revaluation_count=reval_count,
            in_memory_l1_bytes=l1_stats["total_bytes"],
            in_memory_l1_items=l1_stats["total_items"],
            in_memory_l1_max_items=l1_stats["max_items"],
            cache_hits=l1_stats["hits"],
            cache_misses=l1_stats["misses"],
        )


memory_stats_collector = MemoryStatsCollector()

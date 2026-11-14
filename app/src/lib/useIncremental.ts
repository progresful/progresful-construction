import { useEffect, useRef, useState } from 'react';

/**
 * Render a long list in pages: the first `page` items, then more each time the sentinel element
 * scrolls into view. Resets when `resetKey` changes (a new search or filter).
 */
export function useIncremental<T>(items: T[], resetKey: string, page = 200) {
  const [limit, setLimit] = useState(page);
  const sentinel = useRef<HTMLElement | null>(null);

  useEffect(() => setLimit(page), [resetKey, page]);

  useEffect(() => {
    const node = sentinel.current;
    if (!node || limit >= items.length) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) setLimit((l) => l + page);
    });
    io.observe(node);
    return () => io.disconnect();
  }, [limit, items.length, page]);

  return { shown: items.slice(0, limit), more: items.length - Math.min(limit, items.length), sentinel };
}

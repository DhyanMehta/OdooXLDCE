import { useCallback, useEffect, useRef, useState } from "react";

import { subscribe } from "../lib/queryCache";
import { formatApiError } from "../services/api";

type State<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
};

/**
 * Fetch helper with loading/error/empty-safe state and optional cache keys.
 * Does not treat empty arrays as loading.
 */
export function useAsyncResource<T>(
  loader: (() => Promise<T>) | null,
  deps: unknown[],
  options?: { cacheKeys?: string[] },
): State<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(loader));
  const [error, setError] = useState<string | null>(null);
  const gen = useRef(0);
  const cacheKeys = options?.cacheKeys ?? [];
  const cacheKeySig = cacheKeys.join("|");

  const reload = useCallback(async () => {
    if (!loader) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }
    const id = ++gen.current;
    setLoading(true);
    setError(null);
    try {
      const result = await loader();
      if (id === gen.current) {
        setData(result);
      }
    } catch (err) {
      if (id === gen.current) {
        setError(formatApiError(err));
        setData(null);
      }
    } finally {
      if (id === gen.current) setLoading(false);
    }
    // Intentionally driven by caller-provided deps (stable resource identity).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    if (!cacheKeySig) return;
    const keys = cacheKeySig.split("|").filter(Boolean);
    const unsubs = keys.map((key) => subscribe(key, () => void reload()));
    return () => unsubs.forEach((u) => u());
  }, [reload, cacheKeySig]);

  return { data, loading, error, reload };
}

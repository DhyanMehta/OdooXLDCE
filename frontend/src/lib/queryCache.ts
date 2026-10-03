/** Tiny pub/sub cache invalidation for club-scoped server state. */

type Listener = () => void;

const listeners = new Map<string, Set<Listener>>();

export function subscribe(key: string, listener: Listener): () => void {
  let set = listeners.get(key);
  if (!set) {
    set = new Set();
    listeners.set(key, set);
  }
  set.add(listener);
  return () => {
    set!.delete(listener);
  };
}

export function invalidate(...keys: string[]) {
  for (const key of keys) {
    const set = listeners.get(key);
    if (!set) continue;
    for (const listener of [...set]) listener();
  }
}

export function clubKey(clubId: string, resource: string) {
  return `club:${clubId}:${resource}`;
}

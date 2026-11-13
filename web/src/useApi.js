// One data hook: load / error / stale, refetched when an SSE event lands (05 §10:
// rows keep their last values with a stale marker while reconnecting).
import { useCallback, useEffect, useRef, useState } from "react";
import { get } from "./api.js";

export const EVENT = "ironfleet:event";

// State is keyed by path: switching matter (or filter) never shows the previous path's
// data under the new identity — no cross-matter bleed while the new read is in flight.
export function useApi(path, { matter } = {}) {
  const [state, set] = useState({ path, data: undefined, error: null, loading: !!path });
  const seq = useRef(0);
  const load = useCallback(() => {
    if (!path) return;
    const n = ++seq.current;
    set((s) => (s.path === path ? { ...s, loading: s.data === undefined }
      : { path, data: undefined, error: null, loading: true }));
    get(path).then(
      (data) => n === seq.current && set({ path, data, error: null, loading: false }),
      (error) => n === seq.current && set((s) => ({ ...(s.path === path ? s : { data: undefined }), path, error, loading: false })));
  }, [path]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    let t;
    const on = (e) => {
      if (matter && e.detail?.data?.matter_id && e.detail.data.matter_id !== matter) return;
      clearTimeout(t);
      t = setTimeout(load, 150);               // coalesce a burst of events into one read
    };
    addEventListener(EVENT, on);
    return () => { removeEventListener(EVENT, on); clearTimeout(t); };
  }, [load, matter]);
  return { ...forPath(state, path), reload: load };
}

// what a caller of `path` may see: only data loaded for that same path.
// stale = a refetch failed but the last good values are still on screen.
export function forPath(state, path) {
  const cur = state.path === path ? state : { data: undefined, error: null, loading: !!path };
  return { data: cur.data, error: cur.error, loading: cur.loading, stale: !!cur.error && cur.data !== undefined };
}

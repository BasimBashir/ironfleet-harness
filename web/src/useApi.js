// One data hook: load / error / stale, refetched when an SSE event lands (05 §10:
// rows keep their last values with a stale marker while reconnecting).
import { useCallback, useEffect, useRef, useState } from "react";
import { get } from "./api.js";

export const EVENT = "ironfleet:event";

export function useApi(path, { matter } = {}) {
  const [state, set] = useState({ data: undefined, error: null, loading: !!path });
  const seq = useRef(0);
  const load = useCallback(() => {
    if (!path) return;
    const n = ++seq.current;
    set((s) => ({ ...s, loading: s.data === undefined }));
    get(path).then(
      (data) => n === seq.current && set({ data, error: null, loading: false }),
      (error) => n === seq.current && set((s) => ({ ...s, error, loading: false })));
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
  return { ...state, reload: load };
}

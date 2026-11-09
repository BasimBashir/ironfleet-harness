// The ONLY event door: /api/v1/events read with fetch + a stream parser, because
// EventSource cannot send Authorization and a token in the URL leaks into logs.
// Reconnect resumes with Last-Event-ID (04 §5.7); status drives the header dot (05 §10).
import { getToken } from "./api.js";

export function createParser(onEvent) {
  let buf = "";
  let id = null;
  let event = "message";
  let data = [];
  return (chunk) => {
    buf += chunk;
    let i;
    while ((i = buf.search(/\r?\n/)) >= 0) {
      const line = buf.slice(0, i);
      buf = buf.slice(i + (buf[i] === "\r" ? 2 : 1));
      if (line === "") {
        if (data.length) onEvent({ id, event, data: data.join("\n") });
        event = "message";
        data = [];
      } else if (!line.startsWith(":")) {
        const c = line.indexOf(":");
        const field = c < 0 ? line : line.slice(0, c);
        let value = c < 0 ? "" : line.slice(c + 1);
        if (value.startsWith(" ")) value = value.slice(1);
        if (field === "data") data.push(value);
        else if (field === "event") event = value;
        else if (field === "id") id = value;
      }
    }
  };
}

export function subscribe(channels, onEvent,
  { onStatus = () => {}, fetchImpl = fetch, token = getToken, retryMs = 2000 } = {}) {
  let lastId = null;
  let stopped = false;
  let ctrl;
  (async () => {
    while (!stopped) {
      ctrl = new AbortController();
      try {
        const headers = { Authorization: `Bearer ${token()}` };
        if (lastId) headers["Last-Event-ID"] = lastId;
        const res = await fetchImpl(`/api/v1/events?channels=${channels.map(encodeURIComponent).join(",")}`,
          { headers, signal: ctrl.signal });
        if (!res.ok) throw new Error(`events ${res.status}`);
        onStatus("live");
        const feed = createParser((e) => {
          lastId = e.id ?? lastId;
          let d;
          try { d = JSON.parse(e.data); } catch { d = e.data; }
          onEvent({ ...e, data: d });
        });
        const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          feed(value);
        }
      } catch {
        if (stopped) return;
      }
      if (stopped) return;
      onStatus("reconnecting");
      await new Promise((r) => setTimeout(r, retryMs));
    }
  })();
  return () => { stopped = true; ctrl?.abort(); };
}

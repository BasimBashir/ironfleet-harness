// Hash routes — every panel is deep-linkable (05 §1). No router library (plan §0).
const ROUTES = [
  ["board", []],
  ["approvals", []],
  ["new", []],
  ["workspace", ["mid", "tab"], "m", { tab: "overview" }],
  ["case", ["mid", "view"], "case", { view: "home" }],
  ["run", ["rid"], "runs"],
];

export function parseRoute(hash) {
  const parts = (hash || "").replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (!parts.length) return { name: "home", params: {} };
  for (const [name, keys, prefix = name, defaults = {}] of ROUTES) {
    if (parts[0] !== prefix) continue;
    const rest = parts.slice(1);
    if (rest.length > keys.length || rest.length < keys.length - Object.keys(defaults).length) break;
    const params = { ...defaults };
    keys.forEach((k, i) => { if (rest[i] !== undefined) params[k] = rest[i]; });
    return { name, params };
  }
  return { name: "notfound", params: {} };
}

export function href(name, params = {}) {
  const [, keys, prefix = name] = ROUTES.find((r) => r[0] === name);
  return "#/" + [prefix, ...keys.map((k) => params[k]).filter((v) => v !== undefined)]
    .map(encodeURIComponent).join("/");
}

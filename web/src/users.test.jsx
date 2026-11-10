import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { MembersView, UsersView } from "./screens/Users.jsx";

// M10 T5 — users/roles admin + matter membership; 05 §12: no permission ⇒ mutation controls hidden,
// but the reason stays discoverable (lock row, like the Audit tab)
const st = { busy: false, pending: false, error: null };
const users = [{ user_id: "u1", username: "admin", role_id: "admin", is_active: true },
  { user_id: "u2", username: "rita", role_id: "reader", is_active: false }];
const roles = [{ role_id: "admin", name: "Admin", permissions: ["*"] },
  { role_id: "reader", name: "Reader", permissions: ["matter.read"] }];
const uv = (over = {}) => renderToString(<UsersView users={users} roles={roles} canAdmin st={st}
  onCreate={() => {}} onPatch={() => {}} {...over} />);

describe("UsersView", () => {
  it("lists users with role, status, and the roles with their permission keys", () => {
    const h = uv();
    expect(h).toContain("rita");
    expect(h).toContain("Deactivated");
    expect(h).toContain(">Reactivate<");
    expect(h).toContain(">Deactivate<");
    expect(h).toContain("matter.read");
    expect(h).toContain('aria-label="Role for rita"');
    expect(h).toContain(">Create user<");
  });
  it("without user.admin shows a lock row, no data, no controls", () => {
    const h = uv({ canAdmin: false, users: undefined, roles: undefined });
    expect(h).toContain("requires the user.admin permission");
    for (const w of ["Create user", "Deactivate", "<select"]) expect(h).not.toContain(w);
  });
  it("never shows a password column and shows the backend's error", () => {
    expect(uv()).not.toMatch(/pw_hash|Password<\/th>/);
    expect(uv({ st: { ...st, error: { status: 422, code: "validation_failed", message: "unknown role" } } }))
      .toContain("unknown role");
  });
});

// as GET /matters/{mid}/members returns it (service/matters.py members())
const members = [{ user: { user_id: "u1", username: "admin" }, role: "admin" },
  { user: { user_id: "u3", username: "ed" }, role: "editor" }];
const mv = (over = {}) => renderToString(<MembersView members={members} roleIds={["admin", "editor", "reader"]}
  canWrite st={st} onPut={() => {}} onRemove={() => {}} {...over} />);

describe("MembersView (matter membership)", () => {
  it("edits roles, removes, and adds by user id with matter.write", () => {
    const h = mv();
    expect(h).toContain('aria-label="Role for ed on this matter"');
    expect(h).toMatch(/<option value="editor" selected="">editor<\/option>/);
    expect(h).toContain(">u3<");
    expect(h).toContain(">Remove<");
    expect(h).toContain(">Add member<");
  });
  it("is read-only without matter.write: members readable, every mutation hidden", () => {
    const h = mv({ canWrite: false });
    expect(h).toContain("ed");
    expect(h).toContain("editor");
    for (const w of ["Remove", "Add member", "<select"]) expect(h).not.toContain(w);
  });
});

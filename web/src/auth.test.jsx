import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { ChangePassword, Login } from "./App.jsx";
import { UsersView } from "./screens/Users.jsx";

const noop = () => {};

describe("public signup card (B)", () => {
  it("sign-in view offers Request an account", () => {
    const h = renderToString(<Login onDone={noop} />);
    expect(h).toContain("Sign in to IronFleet");
    expect(h).toContain("Request an account");
  });
  it("signup view asks for a username and password", () => {
    const h = renderToString(<Login onDone={noop} initialView="signup" />);
    expect(h).toContain("Request an account</h1>");
    expect(h).toContain("Send request");
    expect(h).toContain("← Back to sign in");
  });
  it("sent view names the approval gate", () => {
    const h = renderToString(<Login onDone={noop} initialView="sent" />);
    expect(h).toContain("An administrator must approve it before you can sign in");
  });
});

describe("forced password change (B default admin/admin)", () => {
  it("renders two password fields and saves", () => {
    const h = renderToString(<ChangePassword onDone={noop} />);
    expect(h).toContain("Set a new password</h1>");
    expect((h.match(/type="password"/g) || []).length).toBe(2);
    expect(h).toContain("Save and continue");
  });
});

describe("Users table state column (B)", () => {
  const users = [
    { user_id: "u1", username: "admin", role_id: "admin", is_active: true,
      must_change_password: true, state: "active" },
    { user_id: "u2", username: "rita", role_id: "reader", is_active: true,
      must_change_password: false, state: "active" },
    { user_id: "u3", username: "newguy", role_id: "reader", is_active: false,
      must_change_password: false, state: "pending" },
    { user_id: "u4", username: "ghost", role_id: "reader", is_active: false,
      must_change_password: false, state: "rejected" },
  ];
  const view = () => renderToString(
    <UsersView users={users} roles={[{ role_id: "reader", permissions: ["matter.read"] }, { role_id: "admin", permissions: ["user.admin"] }]}
      canAdmin st={{ busy: false, error: null }} onCreate={noop} onPatch={noop} />);
  it("labels each state and puts Approve/Reject on pending rows only", () => {
    const h = view();
    expect(h).toContain("Must set password");
    expect(h).toContain("Pending</td>");
    expect(h).toContain("Rejected</td>");
    expect(h).toContain(">Approve</button>");
    expect(h).toContain(">Reject</button>");
    expect((h.match(/>Approve</g) || []).length).toBe(1);
    expect((h.match(/>Reject</g) || []).length).toBe(1);
  });
  it("hides the role select on pending rows (reader until promoted)", () => {
    const h = view();
    expect((h.match(/<select aria-label="Role for/g) || []).length).toBe(3);
    expect(h).toContain("reader</td>");  // pending row shows the role as text
  });
});

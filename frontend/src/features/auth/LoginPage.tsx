import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Feedback } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { safeNextPath } from "../../lib/format";
import { ApiError, formatApiError } from "../../services/api";

const QUICK_ACCOUNTS = [
  { email: "member@techclub.edu", label: "Member" },
  { email: "admin@techclub.edu", label: "Admin" },
  { email: "events@techclub.edu", label: "Events" },
  { email: "comms@techclub.edu", label: "Comms" },
];

export function LoginPage() {
  const { login, register, me } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNextPath(params.get("next"));

  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (me) {
    return (
      <Feedback tone="ok">
        You are already signed in. <Link to={next}>Continue</Link>
      </Feedback>
    );
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, fullName);
      navigate(next);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Invalid email or password.");
      } else {
        setError(formatApiError(err));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="stack" style={{ maxWidth: 480 }}>
      <div className="hero-block">
        <h1>{mode === "login" ? "Log in" : "Create account"}</h1>
        <p className="muted">
          {mode === "login" ? "Sign in to manage memberships and tickets." : "Register to join clubs."}
        </p>
      </div>

      <div className="row">
        <button
          type="button"
          className={`btn ${mode === "login" ? "" : "btn--ghost"}`}
          onClick={() => setMode("login")}
        >
          Log in
        </button>
        <button
          type="button"
          className={`btn ${mode === "register" ? "" : "btn--ghost"}`}
          onClick={() => setMode("register")}
        >
          Register
        </button>
      </div>

      <form className="panel form" onSubmit={onSubmit}>
        {mode === "register" && (
          <label>
            Full name
            <input value={fullName} onChange={(e) => setFullName(e.target.value)} required />
          </label>
        )}
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
          />
        </label>
        {error && <Feedback tone="danger">{error}</Feedback>}
        <button className="btn" disabled={busy} type="submit">
          {busy ? "Working…" : mode === "login" ? "Log in" : "Register"}
        </button>
      </form>

      {mode === "login" && (
        <div className="panel stack">
          <p className="muted small">Optional demo quick-fill (seed accounts):</p>
          <div className="row">
            {QUICK_ACCOUNTS.map((account) => (
              <button
                key={account.email}
                type="button"
                className="btn btn--ghost"
                onClick={() => {
                  setEmail(account.email);
                  setPassword("Password123!");
                }}
              >
                {account.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

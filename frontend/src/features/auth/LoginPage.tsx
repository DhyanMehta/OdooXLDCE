import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { Feedback } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { ApiError } from "../../services/api";

export function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("member@techclub.edu");
  const [password, setPassword] = useState("Password123!");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const quickAccounts = [
    { email: "member@techclub.edu", label: "Member" },
    { email: "admin@techclub.edu", label: "Admin" },
    { email: "events@techclub.edu", label: "Events" },
    { email: "comms@techclub.edu", label: "Comms" },
  ];

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, fullName);
      navigate("/home");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Authentication failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="stack" style={{ maxWidth: 480 }}>
      <div className="hero-block">
        <h1>{mode === "login" ? "Log in" : "Create account"}</h1>
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
      <div className="row">
        {quickAccounts.map((account) => (
          <button
            key={account.email}
            type="button"
            className="btn btn--ghost"
            onClick={() => {
              setMode("login");
              setEmail(account.email);
              setPassword("Password123!");
            }}
          >
            {account.label}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="btn btn--ghost"
        onClick={() => setMode(mode === "login" ? "register" : "login")}
      >
        {mode === "login" ? "Need an account? Register" : "Back to login"}
      </button>
    </section>
  );
}

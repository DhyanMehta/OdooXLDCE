import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { Feedback, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { formatApiError } from "../../services/api";

export function ProfilePage() {
  const { me, loading, updateProfile } = useAuth();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!me) return;
    setFullName(me.user.full_name);
    setEmail(me.user.email);
  }, [me]);

  if (loading) return <Spinner />;
  if (!me) {
    return (
      <Feedback tone="warn">
        Please <Link to="/login?next=/profile">log in</Link> to edit your profile.
      </Feedback>
    );
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const body: {
        full_name?: string;
        email?: string;
        current_password?: string;
        new_password?: string;
      } = {};
      if (fullName.trim() && fullName.trim() !== me!.user.full_name) {
        body.full_name = fullName.trim();
      }
      if (email.trim() && email.trim() !== me!.user.email) {
        body.email = email.trim();
      }
      if (newPassword) {
        body.new_password = newPassword;
        body.current_password = currentPassword;
      }
      if (Object.keys(body).length === 0) {
        setMessage("Nothing to update.");
        return;
      }
      await updateProfile(body);
      setCurrentPassword("");
      setNewPassword("");
      setMessage("Profile updated.");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ maxWidth: 520 }}>
      <div className="hero-block">
        <h1>Profile</h1>
        <p className="muted">Update your name, email, or password.</p>
      </div>
      <form className="panel form" onSubmit={onSubmit}>
        <label>
          Full name
          <input
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            required
            minLength={1}
            maxLength={200}
          />
        </label>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Current password (required to change password)
          <input
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>
        <label>
          New password
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            minLength={8}
            autoComplete="new-password"
          />
        </label>
        {error && <Feedback tone="danger">{error}</Feedback>}
        {message && <Feedback tone="ok">{message}</Feedback>}
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save changes"}
        </button>
      </form>
    </div>
  );
}

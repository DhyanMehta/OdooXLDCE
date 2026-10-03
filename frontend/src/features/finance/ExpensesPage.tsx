import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { openExpenseReceipt } from "../../lib/receiptDownload";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";
import type { components } from "../../types/openapi";

type ExpenseOut = components["schemas"]["ExpenseOut"];

const CATEGORIES = [
  "general",
  "supplies",
  "travel",
  "food",
  "equipment",
  "other",
] as const;

export function ExpensesPage() {
  const { me, activeClub } = useAuth();
  const [params] = useSearchParams();
  const clubId = params.get("club") ?? activeClub?.club.id ?? null;
  const clubName =
    activeClub?.club.id === clubId
      ? activeClub.club.name
      : me?.clubs.find((c) => c.club.id === clubId)?.club.name;

  const [amount, setAmount] = useState("");
  const [expenseDate, setExpenseDate] = useState(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [category, setCategory] = useState<string>("general");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionId, setActionId] = useState<string | null>(null);

  const expensesRes = useAsyncResource(
    me && clubId
      ? () =>
          api.get("/api/v1/clubs/{club_id}/expenses", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [me?.user.id, clubId],
    { cacheKeys: clubId ? [clubKey(clubId, "expenses")] : [] },
  );

  if (!clubId) {
    return (
      <Feedback tone="warn">
        Pick a club first from the <Link to="/clubs">clubs directory</Link>.
      </Feedback>
    );
  }
  if (!me) {
    return (
      <Feedback tone="warn">
        Please{" "}
        <Link to={`/login?next=${encodeURIComponent(`/expenses?club=${clubId}`)}`}>log in</Link> to
        submit expenses.
      </Feedback>
    );
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      await api.post("/api/v1/clubs/{club_id}/expenses", {
        params: { path: { club_id: clubId! } },
        body: {
          amount,
          category,
          description,
          expense_date: expenseDate,
        },
      });
      setAmount("");
      setDescription("");
      setMessage("Expense saved as draft.");
      invalidate(clubKey(clubId!, "expenses"));
      await expensesRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitExpense(expenseId: string) {
    setActionId(expenseId);
    setError(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/expenses/{expense_id}/submit", {
        params: { path: { club_id: clubId!, expense_id: expenseId } },
      });
      setMessage("Submitted for review.");
      invalidate(clubKey(clubId!, "expenses"));
      await expensesRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setActionId(null);
    }
  }

  async function onUploadReceipt(expense: ExpenseOut, file: File | null) {
    if (!file) return;
    setActionId(expense.id);
    setError(null);
    try {
      await api.uploadExpenseReceipt(clubId!, expense.id, file);
      setMessage("Receipt uploaded.");
      invalidate(clubKey(clubId!, "expenses"));
      await expensesRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setActionId(null);
    }
  }

  async function onOpenReceipt(expenseId: string, attachmentId: string) {
    setError(null);
    try {
      await openExpenseReceipt(clubId!, expenseId, attachmentId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed");
    }
  }

  const expenses = expensesRes.data ?? [];

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Expense claims</h1>
        <p className="muted">
          {clubName ?? "Club"} — bookkeeping only. CampusOS records claims and approvals; it does
          not move money from your bank.
        </p>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      {message && <Feedback tone="ok">{message}</Feedback>}

      <form className="panel form" onSubmit={onCreate}>
        <h2>New expense</h2>
        <label>
          Amount (₹)
          <input value={amount} onChange={(e) => setAmount(e.target.value)} required />
        </label>
        <label>
          Date
          <input
            type="date"
            value={expenseDate}
            onChange={(e) => setExpenseDate(e.target.value)}
            required
          />
        </label>
        <label>
          Category
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label>
          Description
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
          />
        </label>
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save draft"}
        </button>
      </form>

      <section className="panel stack">
        <h2>Your expenses</h2>
        <PageState
          loading={expensesRes.loading}
          error={expensesRes.error}
          empty={expenses.length === 0}
          emptyMessage="No expenses yet."
        >
          {expenses.map((exp) => (
            <article key={exp.id} className="stack" style={{ borderTop: "1px solid var(--border)", paddingTop: "1rem" }}>
              <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
                <div>
                  <strong>₹{exp.amount}</strong> · {exp.category} · {exp.expense_date}
                  <p className="muted small">{exp.description}</p>
                </div>
                <span className={statusBadgeClass(exp.status)}>{exp.status}</span>
              </div>
              {(exp.status === "draft" || exp.status === "submitted") && (
                <div className="row">
                  <button
                    type="button"
                    className="btn btn--ghost"
                    disabled={actionId === exp.id || exp.status !== "draft"}
                    onClick={() => void submitExpense(exp.id)}
                  >
                    {actionId === exp.id ? "…" : "Submit for review"}
                  </button>
                  <label className="btn btn--ghost">
                    Upload receipt
                    <input
                      type="file"
                      hidden
                      accept="image/*,.pdf"
                      disabled={actionId === exp.id}
                      onChange={(e) => void onUploadReceipt(exp, e.target.files?.[0] ?? null)}
                    />
                  </label>
                </div>
              )}
              {(exp.attachments?.length ?? 0) > 0 && (
                <div className="stack">
                  <p className="small muted">Receipts</p>
                  {exp.attachments!.map((att) => (
                    <button
                      key={att.id}
                      type="button"
                      className="btn btn--ghost"
                      onClick={() => void onOpenReceipt(exp.id, att.id)}
                    >
                      {att.original_filename}
                    </button>
                  ))}
                </div>
              )}
              {(exp.approvals?.length ?? 0) > 0 && (
                <div className="stack">
                  <p className="small muted">Approval history</p>
                  <ul className="muted small">
                    {exp.approvals!.map((a) => (
                      <li key={a.id}>
                        {new Date(a.created_at).toLocaleString()} — {a.decision}
                        {a.reason ? `: ${a.reason}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {exp.reimbursement && (
                <p className="muted small">
                  Reimbursed {new Date(exp.reimbursement.paid_at).toLocaleString()} · ref{" "}
                  {exp.reimbursement.payment_reference}
                </p>
              )}
            </article>
          ))}
        </PageState>
      </section>

      <Feedback tone="info">
        <Link to="/my-refunds">View your refund requests</Link>
      </Feedback>
    </div>
  );
}

import { useState } from "react";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { openExpenseReceipt } from "../../lib/receiptDownload";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";
import type { components } from "../../types/openapi";

type ExpenseOut = components["schemas"]["ExpenseOut"];
type PendingItem = components["schemas"]["PendingReimbursementOut"];

export function AdminExpenseReviewPage() {
  const { activeClub, hasPermission } = useAuth();
  const clubId = activeClub?.club.id ?? null;
  const canReview = hasPermission("review_expenses");
  const canReimburse = hasPermission("record_reimbursement");
  const canAccess = canReview || canReimburse;

  const [queueStatus, setQueueStatus] = useState<string>("submitted");
  const [reasonById, setReasonById] = useState<Record<string, string>>({});
  const [payRefById, setPayRefById] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const queueRes = useAsyncResource(
    clubId && canReview
      ? () =>
          api.get("/api/v1/clubs/{club_id}/expenses/queue", {
            params: {
              path: { club_id: clubId },
              query: { status: queueStatus || "submitted" },
            },
          })
      : null,
    [clubId, canReview, queueStatus],
    { cacheKeys: clubId ? [clubKey(clubId, "expense-queue")] : [] },
  );

  const pendingRes = useAsyncResource(
    clubId && canReimburse
      ? () =>
          api.get("/api/v1/clubs/{club_id}/finance/pending-reimbursements", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [clubId, canReimburse],
    { cacheKeys: clubId ? [clubKey(clubId, "pending-reimbursements")] : [] },
  );

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!canAccess) return <Feedback tone="danger">Forbidden</Feedback>;

  function bump() {
    invalidate(
      clubKey(activeClub!.club.id, "expense-queue"),
      clubKey(activeClub!.club.id, "pending-reimbursements"),
      clubKey(activeClub!.club.id, "expenses"),
    );
  }

  async function decide(expense: ExpenseOut, decision: "approved" | "rejected") {
    if (!clubId) return;
    setBusyId(expense.id);
    setError(null);
    setMessage(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/expenses/{expense_id}/decide", {
        params: { path: { club_id: clubId, expense_id: expense.id } },
        body: { decision, reason: reasonById[expense.id] ?? "" },
      });
      setMessage(`Expense ${decision}.`);
      bump();
      await queueRes.reload();
      await pendingRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusyId(null);
    }
  }

  async function reimburse(expenseId: string) {
    if (!clubId) return;
    const payment_reference = payRefById[expenseId]?.trim();
    if (!payment_reference) {
      setError("Payment reference is required.");
      return;
    }
    setBusyId(expenseId);
    setError(null);
    setMessage(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/expenses/{expense_id}/reimburse", {
        params: { path: { club_id: clubId, expense_id: expenseId } },
        body: { payment_reference },
      });
      setMessage("Reimbursement recorded.");
      bump();
      await queueRes.reload();
      await pendingRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusyId(null);
    }
  }

  async function onOpenReceipt(expenseId: string, attachmentId: string) {
    if (!clubId) return;
    setError(null);
    try {
      await openExpenseReceipt(clubId, expenseId, attachmentId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed");
    }
  }

  const queue = queueRes.data ?? [];
  const pendingItems: PendingItem[] = pendingRes.data?.items ?? [];

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Expense review</h1>
        <p className="muted">
          Approve or reject claims, then record reimbursements you paid outside CampusOS.
        </p>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      {message && <Feedback tone="ok">{message}</Feedback>}

      {canReview && (
        <section className="panel stack">
          <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
            <h2>Review queue</h2>
            <label>
              Status filter
              <select value={queueStatus} onChange={(e) => setQueueStatus(e.target.value)}>
                <option value="submitted">Submitted</option>
                <option value="approved">Approved</option>
                <option value="rejected">Rejected</option>
                <option value="all">All</option>
              </select>
            </label>
          </div>
          <PageState
            loading={queueRes.loading}
            error={queueRes.error}
            empty={queue.length === 0}
            emptyMessage="Nothing in this queue."
          >
            {queue.map((exp) => (
              <article
                key={exp.id}
                className="stack"
                style={{ borderTop: "1px solid var(--border)", paddingTop: "1rem" }}
              >
                <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
                  <div>
                    <strong>₹{exp.amount}</strong> · {exp.category} · {exp.expense_date}
                    <p className="muted small">{exp.description}</p>
                  </div>
                  <span className={statusBadgeClass(exp.status)}>{exp.status}</span>
                </div>
                {(exp.attachments?.length ?? 0) > 0 && (
                  <div className="row">
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
                {exp.status === "submitted" && (
                  <>
                    <label>
                      Reason (optional for approve)
                      <input
                        value={reasonById[exp.id] ?? ""}
                        onChange={(e) =>
                          setReasonById((m) => ({ ...m, [exp.id]: e.target.value }))
                        }
                      />
                    </label>
                    <div className="row">
                      <button
                        type="button"
                        className="btn"
                        disabled={busyId === exp.id}
                        onClick={() => void decide(exp, "approved")}
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        disabled={busyId === exp.id}
                        onClick={() => void decide(exp, "rejected")}
                      >
                        Reject
                      </button>
                    </div>
                  </>
                )}
                {exp.status === "approved" && canReimburse && !exp.reimbursement && (
                  <div className="row">
                    <label style={{ flex: 1 }}>
                      Payment reference
                      <input
                        value={payRefById[exp.id] ?? ""}
                        onChange={(e) =>
                          setPayRefById((m) => ({ ...m, [exp.id]: e.target.value }))
                        }
                        placeholder="UPI / bank ref"
                      />
                    </label>
                    <button
                      type="button"
                      className="btn"
                      disabled={busyId === exp.id}
                      onClick={() => void reimburse(exp.id)}
                    >
                      Record reimbursement
                    </button>
                  </div>
                )}
              </article>
            ))}
          </PageState>
        </section>
      )}

      {canReimburse && (
        <section className="panel stack">
          <h2>Pending reimbursements</h2>
          <p className="muted small">
            Approved expenses awaiting payout confirmation · total ₹
            {pendingRes.data?.total ?? "0"}
          </p>
          <PageState
            loading={pendingRes.loading}
            error={pendingRes.error}
            empty={pendingItems.length === 0}
            emptyMessage="No pending reimbursements."
          >
            <table>
              <thead>
                <tr>
                  <th>Submitter</th>
                  <th>Amount</th>
                  <th>Category</th>
                  <th>Description</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {pendingItems.map((item) => (
                  <tr key={item.expense_id}>
                    <td>{item.submitter_name}</td>
                    <td>
                      ₹{item.amount} {item.currency}
                    </td>
                    <td>{item.category}</td>
                    <td className="muted small">{item.description}</td>
                    <td>
                      <label className="stack">
                        <input
                          value={payRefById[item.expense_id] ?? ""}
                          onChange={(e) =>
                            setPayRefById((m) => ({
                              ...m,
                              [item.expense_id]: e.target.value,
                            }))
                          }
                          placeholder="Payment ref"
                        />
                        <button
                          type="button"
                          className="btn btn--ghost"
                          disabled={busyId === item.expense_id}
                          onClick={() => void reimburse(item.expense_id)}
                        >
                          Record paid
                        </button>
                      </label>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </PageState>
        </section>
      )}
    </div>
  );
}

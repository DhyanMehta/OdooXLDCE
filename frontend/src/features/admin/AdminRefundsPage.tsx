import { useState, type FormEvent } from "react";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";
import type { components } from "../../types/openapi";

type RefundOut = components["schemas"]["RefundOut"];

export function AdminRefundsPage() {
  const { activeClub, hasPermission } = useAuth();
  const clubId = activeClub?.club.id ?? null;
  const canRecord = hasPermission("record_refunds");

  const [statusFilter, setStatusFilter] = useState<string>("pending");
  const [reasonById, setReasonById] = useState<Record<string, string>>({});
  const [manualRefById, setManualRefById] = useState<Record<string, string>>({});
  const [ackById, setAckById] = useState<Record<string, boolean>>({});
  const [physicalById, setPhysicalById] = useState<Record<string, boolean>>({});
  const [staffOrderId, setStaffOrderId] = useState("");
  const [staffReason, setStaffReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refundsRes = useAsyncResource(
    clubId && canRecord
      ? () =>
          api.get("/api/v1/clubs/{club_id}/refunds", {
            params: {
              path: { club_id: clubId },
              query: { status: statusFilter || null },
            },
          })
      : null,
    [clubId, canRecord, statusFilter],
    { cacheKeys: clubId ? [clubKey(clubId, "refunds-admin")] : [] },
  );

  const refundableRes = useAsyncResource(
    clubId && canRecord
      ? () =>
          api.get("/api/v1/clubs/{club_id}/orders/refundable", {
            params: { path: { club_id: clubId }, query: { limit: 50 } },
          })
      : null,
    [clubId, canRecord],
    { cacheKeys: clubId ? [clubKey(clubId, "orders-refundable")] : [] },
  );

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!canRecord) return <Feedback tone="danger">Forbidden</Feedback>;

  function bump() {
    invalidate(
      clubKey(activeClub!.club.id, "refunds-admin"),
      clubKey(activeClub!.club.id, "refunds-mine"),
      clubKey(activeClub!.club.id, "orders-refundable"),
      "orders",
    );
  }

  async function decide(refund: RefundOut, decision: "approved" | "rejected") {
    if (!clubId) return;
    setBusyId(refund.id);
    setError(null);
    setMessage(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/refunds/{refund_id}/decide", {
        params: { path: { club_id: clubId, refund_id: refund.id } },
        body: { decision, reason: reasonById[refund.id] ?? "" },
      });
      setMessage(`Refund ${decision}.`);
      bump();
      await refundsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusyId(null);
    }
  }

  async function complete(refund: RefundOut) {
    if (!clubId) return;
    const manual_reference = manualRefById[refund.id]?.trim();
    if (!manual_reference) {
      setError("Manual reference is required.");
      return;
    }
    setBusyId(refund.id);
    setError(null);
    setMessage(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/refunds/{refund_id}/complete", {
        params: { path: { club_id: clubId, refund_id: refund.id } },
        body: {
          manual_reference,
          acknowledge_used: ackById[refund.id] ?? false,
          physical_return: physicalById[refund.id] ?? false,
        },
      });
      setMessage("Refund marked complete.");
      bump();
      await refundsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusyId(null);
    }
  }

  async function staffRequest(e: FormEvent) {
    e.preventDefault();
    if (!clubId) return;
    setError(null);
    setMessage(null);
    setBusyId("staff-request");
    try {
      await api.post("/api/v1/clubs/{club_id}/refunds", {
        params: { path: { club_id: clubId } },
        body: { order_id: staffOrderId.trim(), reason: staffReason },
      });
      setStaffOrderId("");
      setStaffReason("");
      setMessage("Refund request created.");
      bump();
      await refundsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusyId(null);
    }
  }

  const refunds = refundsRes.data ?? [];

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Refunds</h1>
        <p className="muted">
          Manual refund recording — CampusOS does not transfer money. Staff confirm payouts they
          made outside the app.
        </p>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      {message && <Feedback tone="ok">{message}</Feedback>}

      <form className="panel form" onSubmit={staffRequest}>
        <h2>Staff: request refund by order</h2>
        <p className="muted">
          Includes paid and refund_required orders (e.g. after event cancel). CampusOS does not move
          money — this only starts the manual refund record.
        </p>
        <label>
          Order
          <select
            value={staffOrderId}
            onChange={(e) => setStaffOrderId(e.target.value)}
            required
          >
            <option value="">Select an order…</option>
            {(refundableRes.data ?? []).map((o) => {
              const title = o.items?.[0]?.title_snapshot ?? o.id.slice(0, 8);
              const buyer = o.buyer_email ?? o.buyer_name ?? "buyer";
              return (
                <option key={o.id} value={o.id}>
                  {o.status} · ₹{o.total_amount} · {title} · {buyer}
                </option>
              );
            })}
          </select>
        </label>
        <label>
          Reason
          <input value={staffReason} onChange={(e) => setStaffReason(e.target.value)} />
        </label>
        <button
          className="btn btn--ghost"
          type="submit"
          disabled={busyId === "staff-request" || !staffOrderId}
        >
          Create request
        </button>
        {refundableRes.error && <Feedback tone="danger">{refundableRes.error}</Feedback>}
      </form>

      <section className="panel stack">
        <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
          <h2>Refund queue</h2>
          <label>
            Status
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="completed">Completed</option>
              <option value="rejected">Rejected</option>
              <option value="">All</option>
            </select>
          </label>
        </div>
        <PageState
          loading={refundsRes.loading}
          error={refundsRes.error}
          empty={refunds.length === 0}
          emptyMessage="No refunds in this filter."
        >
          {refunds.map((ref) => (
            <article
              key={ref.id}
              className="stack"
              style={{ borderTop: "1px solid var(--border)", paddingTop: "1rem" }}
            >
              <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
                <div>
                  <strong>₹{ref.amount}</strong> · order {ref.order_id.slice(0, 8)}…
                  <p className="muted small">{ref.reason}</p>
                </div>
                <span className={statusBadgeClass(ref.status)}>{ref.status}</span>
              </div>
              {ref.status === "pending" && (
                <>
                  <label>
                    Decision note
                    <input
                      value={reasonById[ref.id] ?? ""}
                      onChange={(e) =>
                        setReasonById((m) => ({ ...m, [ref.id]: e.target.value }))
                      }
                    />
                  </label>
                  <div className="row">
                    <button
                      type="button"
                      className="btn"
                      disabled={busyId === ref.id}
                      onClick={() => void decide(ref, "approved")}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      className="btn btn--ghost"
                      disabled={busyId === ref.id}
                      onClick={() => void decide(ref, "rejected")}
                    >
                      Reject
                    </button>
                  </div>
                </>
              )}
              {ref.status === "approved" && (
                <div className="stack">
                  <label>
                    Manual reference
                    <input
                      value={manualRefById[ref.id] ?? ""}
                      onChange={(e) =>
                        setManualRefById((m) => ({ ...m, [ref.id]: e.target.value }))
                      }
                    />
                  </label>
                  <label className="row">
                    <input
                      type="checkbox"
                      checked={ackById[ref.id] ?? false}
                      onChange={(e) =>
                        setAckById((m) => ({ ...m, [ref.id]: e.target.checked }))
                      }
                    />
                    Acknowledge used (ticket/merch consumed)
                  </label>
                  <label className="row">
                    <input
                      type="checkbox"
                      checked={physicalById[ref.id] ?? false}
                      onChange={(e) =>
                        setPhysicalById((m) => ({ ...m, [ref.id]: e.target.checked }))
                      }
                    />
                    Physical return received
                  </label>
                  <button
                    type="button"
                    className="btn"
                    disabled={busyId === ref.id}
                    onClick={() => void complete(ref)}
                  >
                    Mark complete
                  </button>
                </div>
              )}
              {ref.manual_reference && (
                <p className="muted small">Ref: {ref.manual_reference}</p>
              )}
            </article>
          ))}
        </PageState>
      </section>
    </div>
  );
}

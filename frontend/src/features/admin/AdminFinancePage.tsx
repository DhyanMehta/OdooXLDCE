import { useState, type FormEvent } from "react";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";

const BUDGET_CATEGORIES = [
  "general",
  "supplies",
  "travel",
  "food",
  "equipment",
  "other",
] as const;

export function AdminFinancePage() {
  const { activeClub, hasPermission } = useAuth();
  const clubId = activeClub?.club.id ?? null;
  const canView = hasPermission("view_finance");
  const canBudget = hasPermission("manage_budgets");

  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [includeDemo, setIncludeDemo] = useState(false);
  const [budgetCategory, setBudgetCategory] = useState<string>("general");
  const [budgetLimit, setBudgetLimit] = useState("");
  const [budgetStart, setBudgetStart] = useState("");
  const [budgetEnd, setBudgetEnd] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const query = {
    start: start || null,
    end: end || null,
    include_demo: includeDemo,
  };

  const incomeRes = useAsyncResource(
    clubId && canView
      ? () =>
          api.get("/api/v1/clubs/{club_id}/finance/income", {
            params: { path: { club_id: clubId }, query },
          })
      : null,
    [clubId, canView, start, end, includeDemo],
    { cacheKeys: clubId ? [clubKey(clubId, "finance-income")] : [] },
  );

  const spendingRes = useAsyncResource(
    clubId && canView
      ? () =>
          api.get("/api/v1/clubs/{club_id}/finance/spending", {
            params: { path: { club_id: clubId }, query },
          })
      : null,
    [clubId, canView, start, end, includeDemo],
    { cacheKeys: clubId ? [clubKey(clubId, "finance-spending")] : [] },
  );

  const balancesRes = useAsyncResource(
    clubId && canView
      ? () =>
          api.get("/api/v1/clubs/{club_id}/finance/cash-balances", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [clubId, canView],
    { cacheKeys: clubId ? [clubKey(clubId, "finance-balances")] : [] },
  );

  const budgetVsActualRes = useAsyncResource(
    clubId && canView
      ? () =>
          api.get("/api/v1/clubs/{club_id}/finance/budget-vs-actual", {
            params: { path: { club_id: clubId }, query: { start: start || null, end: end || null } },
          })
      : null,
    [clubId, canView, start, end],
    { cacheKeys: clubId ? [clubKey(clubId, "finance-budget-actual")] : [] },
  );

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!canView) return <Feedback tone="danger">Forbidden</Feedback>;

  async function onBudgetSubmit(e: FormEvent) {
    e.preventDefault();
    if (!clubId || !canBudget) return;
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      await api.post("/api/v1/clubs/{club_id}/finance/budgets", {
        params: { path: { club_id: clubId } },
        body: {
          category: budgetCategory,
          limit_amount: budgetLimit,
          period_start: budgetStart,
          period_end: budgetEnd,
        },
      });
      setMessage("Budget created.");
      invalidate(clubKey(clubId, "finance-budget-actual"));
      await budgetVsActualRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  const loading =
    incomeRes.loading || spendingRes.loading || balancesRes.loading || budgetVsActualRes.loading;

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Finance reports</h1>
        <p className="muted">Cash-basis club ledger (simulated demo clearing where noted).</p>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      {message && <Feedback tone="ok">{message}</Feedback>}

      <section className="panel row" style={{ flexWrap: "wrap", gap: "1rem" }}>
        <label>
          Start
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          End
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <label className="row">
          <input
            type="checkbox"
            checked={includeDemo}
            onChange={(e) => setIncludeDemo(e.target.checked)}
          />
          Include demo payments
        </label>
      </section>

      {loading && <Feedback tone="info">Loading reports…</Feedback>}

      <div className="grid-2">
        <section className="panel stack">
          <h2>Income</h2>
          {incomeRes.error && <Feedback tone="danger">{incomeRes.error}</Feedback>}
          {(incomeRes.data?.rows ?? []).length === 0 && !incomeRes.loading ? (
            <p className="muted">No income in range.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Amount</th>
                </tr>
              </thead>
              <tbody>
                {(incomeRes.data?.rows ?? []).map((row) => (
                  <tr key={`${row.category}-${row.name}`}>
                    <td>{row.name || row.category}</td>
                    <td>
                      ₹{row.amount} {row.currency}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="panel stack">
          <h2>Spending</h2>
          {spendingRes.error && <Feedback tone="danger">{spendingRes.error}</Feedback>}
          {(spendingRes.data?.rows ?? []).length === 0 && !spendingRes.loading ? (
            <p className="muted">No spending in range.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Amount</th>
                </tr>
              </thead>
              <tbody>
                {(spendingRes.data?.rows ?? []).map((row) => (
                  <tr key={`${row.category}-${row.name}`}>
                    <td>{row.name || row.category}</td>
                    <td>
                      ₹{row.amount} {row.currency}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      <section className="panel stack">
        <h2>Cash balances</h2>
        {balancesRes.error && <Feedback tone="danger">{balancesRes.error}</Feedback>}
        <PageState
          loading={balancesRes.loading}
          error={null}
          empty={(balancesRes.data?.balances ?? []).length === 0}
          emptyMessage="No balance rows."
        >
          <table>
            <thead>
              <tr>
                <th>Account</th>
                <th>Balance</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {(balancesRes.data?.balances ?? []).map((b) => (
                <tr key={b.code}>
                  <td>
                    {b.name} ({b.code})
                  </td>
                  <td>
                    ₹{b.balance} {b.currency}
                  </td>
                  <td className="muted small">
                    {b.simulated ? "Simulated demo clearing" : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </PageState>
      </section>

      <section className="panel stack">
        <h2>Budget vs actual</h2>
        {budgetVsActualRes.error && <Feedback tone="danger">{budgetVsActualRes.error}</Feedback>}
        {(budgetVsActualRes.data?.rows ?? []).length === 0 && !budgetVsActualRes.loading ? (
          <p className="muted">No budget rows for this period.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Category</th>
                <th>Period</th>
                <th>Limit</th>
                <th>Actual</th>
                <th>Remaining</th>
                <th>% used</th>
              </tr>
            </thead>
            <tbody>
              {(budgetVsActualRes.data?.rows ?? []).map((row) => (
                <tr key={row.budget_id}>
                  <td>{row.category}</td>
                  <td className="muted small">
                    {row.period_start} – {row.period_end}
                  </td>
                  <td>₹{row.limit_amount}</td>
                  <td>₹{row.actual_amount}</td>
                  <td>₹{row.remaining_amount}</td>
                  <td>{row.percent_used}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {canBudget && (
        <form className="panel form" onSubmit={onBudgetSubmit}>
          <h2>Create budget</h2>
          <label>
            Category
            <select
              value={budgetCategory}
              onChange={(e) => setBudgetCategory(e.target.value)}
            >
              {BUDGET_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label>
            Limit amount
            <input value={budgetLimit} onChange={(e) => setBudgetLimit(e.target.value)} required />
          </label>
          <label>
            Period start
            <input
              type="date"
              value={budgetStart}
              onChange={(e) => setBudgetStart(e.target.value)}
              required
            />
          </label>
          <label>
            Period end
            <input
              type="date"
              value={budgetEnd}
              onChange={(e) => setBudgetEnd(e.target.value)}
              required
            />
          </label>
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Saving…" : "Create budget"}
          </button>
        </form>
      )}
    </div>
  );
}

import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";

export function MerchandisePage() {
  const { me, activeClub } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const clubId = params.get("club") ?? activeClub?.club.id ?? null;
  const clubName =
    activeClub?.club.id === clubId
      ? activeClub.club.name
      : me?.clubs.find((c) => c.club.id === clubId)?.club.name;
  const [busyVariantId, setBusyVariantId] = useState<string | null>(null);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const productsRes = useAsyncResource(
    clubId
      ? () =>
          api.get("/api/v1/clubs/{club_id}/products", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [clubId],
    { cacheKeys: clubId ? [clubKey(clubId, "products")] : [] },
  );
  if (!clubId) {
    return (
      <Feedback tone="warn">
        Pick a club first from the <Link to="/clubs">clubs directory</Link>.
      </Feedback>
    );
  }
  const catalog = (productsRes.data ?? []).filter((p) => p.status === "active");
  async function buy(variantId: string, maxQty: number) {
    if (!clubId) return;
    if (!me) {
      navigate(`/login?next=${encodeURIComponent(`/shop?club=${clubId}`)}`);
      return;
    }
    const raw = quantities[variantId] ?? "1";
    const quantity = Math.max(1, Math.min(maxQty, Number(raw) || 1));
    if (maxQty <= 0) return;
    setBusyVariantId(variantId);
    setError(null);
    try {
      const order = await api.post("/api/v1/clubs/{club_id}/orders/merchandise", {
        params: { path: { club_id: clubId } },
        body: { product_variant_id: variantId, quantity },
      });
      invalidate(clubKey(clubId, "products"), "orders", "my-merchandise");
      navigate(`/orders/${order.id}`);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusyVariantId(null);
    }
  }
  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Club shop</h1>
        <p className="muted">{clubName ?? "Club"} — merchandise and club gear.</p>
      </div>
      {(error || productsRes.error) && (
        <Feedback tone="danger">{error ?? productsRes.error}</Feedback>
      )}
      <PageState
        loading={productsRes.loading}
        error={null}
        empty={catalog.length === 0}
        emptyMessage="No products available right now."
      >
        <div className="grid-2">
          {catalog.map((product) => (
            <article key={product.id} className="panel stack">
              <h2>{product.name}</h2>
              {product.description && <p className="muted">{product.description}</p>}
              <div className="stack">
                {product.variants
                  .filter((v) => v.is_active)
                  .map((variant) => {
                    const available = variant.quantity_available ?? 0;
                    const unavailable = available <= 0;
                    return (
                      <div key={variant.id} className="row" style={{ justifyContent: "space-between" }}>
                        <div>
                          <strong>{variant.label}</strong>
                          <div className="muted small">
                            ₹{variant.price} · {available} available
                            {variant.sku ? ` · ${variant.sku}` : ""}
                          </div>
                        </div>
                        <div className="row">
                          <label className="muted small">
                            Qty
                            <input
                              type="number"
                              min={1}
                              max={Math.max(1, available)}
                              value={quantities[variant.id] ?? "1"}
                              disabled={unavailable}
                              onChange={(e) =>
                                setQuantities((q) => ({ ...q, [variant.id]: e.target.value }))
                              }
                              style={{ width: "4rem", marginLeft: "0.25rem" }}
                            />
                          </label>
                          <button
                            className="btn"
                            type="button"
                            disabled={unavailable || busyVariantId === variant.id}
                            onClick={() => void buy(variant.id, available)}
                          >
                            {busyVariantId === variant.id ? "Starting…" : unavailable ? "Sold out" : "Buy"}
                          </button>
                        </div>
                      </div>
                    );
                  })}
              </div>
            </article>
          ))}
        </div>
      </PageState>
      <section className="panel row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2>My purchases</h2>
          <p className="muted">Track fulfillment and open orders for merch you bought.</p>
        </div>
        {me ? (
          <Link className="btn btn--ghost" to="/my-merch">
            View my merch
          </Link>
        ) : (
          <Link className="btn btn--ghost" to={`/login?next=${encodeURIComponent("/my-merch")}`}>
            Log in to view
          </Link>
        )}
      </section>
    </div>
  );
}

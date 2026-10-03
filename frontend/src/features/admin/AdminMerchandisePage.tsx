import { useState, type FormEvent } from "react";
import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";
import type { components } from "../../types/openapi";

type ProductOut = components["schemas"]["ProductOut"];

export function AdminMerchandisePage() {
  const { activeClub, hasPermission } = useAuth();
  const clubId = activeClub?.club.id ?? null;
  const canManage = hasPermission("manage_merchandise");
  const canFulfill = hasPermission("fulfill_merchandise");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [editProductId, setEditProductId] = useState<string | null>(null);
  const [variantProductId, setVariantProductId] = useState<string | null>(null);
  const [variantLabel, setVariantLabel] = useState("");
  const [variantSku, setVariantSku] = useState("");
  const [variantPrice, setVariantPrice] = useState("100");
  const [stockQty, setStockQty] = useState<Record<string, string>>({});
  const [adjustDelta, setAdjustDelta] = useState<Record<string, string>>({});
  const [adjustNote, setAdjustNote] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const productsRes = useAsyncResource(
    clubId && canManage
      ? () =>
          api.get("/api/v1/clubs/{club_id}/products", {
            params: {
              path: { club_id: clubId },
              query: { include_archived: true },
            },
          })
      : null,
    [clubId, canManage],
    { cacheKeys: clubId ? [clubKey(clubId, "products")] : [] },
  );
  const fulfillmentRes = useAsyncResource(
    clubId && canFulfill
      ? () =>
          api.get("/api/v1/clubs/{club_id}/merchandise/fulfillment", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [clubId, canFulfill],
    { cacheKeys: clubId ? [clubKey(clubId, "fulfillment")] : [] },
  );
  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!canManage && !canFulfill) return <Feedback tone="danger">Forbidden</Feedback>;
  function bumpProducts() {
    invalidate(clubKey(activeClub!.club.id, "products"), clubKey(activeClub!.club.id, "fulfillment"), "my-merchandise");
  }
  async function reloadAll() {
    if (canManage) await productsRes.reload();
    if (canFulfill) await fulfillmentRes.reload();
  }
  function startEditProduct(p: ProductOut) {
    setEditProductId(p.id);
    setName(p.name);
    setDescription(p.description);
  }
  function resetProductForm() {
    setEditProductId(null);
    setName("");
    setDescription("");
  }
  async function onProductSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canManage || !clubId) return;
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      if (editProductId) {
        await api.patch("/api/v1/clubs/{club_id}/products/{product_id}", {
          params: { path: { club_id: clubId, product_id: editProductId } },
          body: { name, description },
        });
        setMessage("Product updated.");
      } else {
        await api.post("/api/v1/clubs/{club_id}/products", {
          params: { path: { club_id: clubId } },
          body: { name, description },
        });
        setMessage("Product created.");
      }
      resetProductForm();
      bumpProducts();
      await productsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }
  async function setProductStatus(productId: string, status: string) {
    if (!clubId) return;
    setError(null);
    try {
      await api.patch("/api/v1/clubs/{club_id}/products/{product_id}", {
        params: { path: { club_id: clubId, product_id: productId } },
        body: { status },
      });
      bumpProducts();
      await productsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    }
  }
  async function addVariant(e: FormEvent) {
    e.preventDefault();
    if (!clubId || !variantProductId) return;
    setError(null);
    setBusy(true);
    try {
      await api.post("/api/v1/clubs/{club_id}/products/{product_id}/variants", {
        params: { path: { club_id: clubId, product_id: variantProductId } },
        body: { label: variantLabel, sku: variantSku, price: variantPrice },
      });
      setVariantLabel("");
      setVariantSku("");
      setVariantPrice("100");
      setVariantProductId(null);
      setMessage("Variant added.");
      bumpProducts();
      await productsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }
  async function receiveStock(variantId: string) {
    if (!clubId) return;
    const quantity = Number(stockQty[variantId] ?? "0");
    if (!quantity || quantity <= 0) return;
    setError(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/variants/{variant_id}/receive", {
        params: { path: { club_id: clubId, variant_id: variantId } },
        body: { quantity, note: "" },
      });
      bumpProducts();
      await productsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    }
  }
  async function adjustStock(variantId: string) {
    if (!clubId) return;
    const delta = Number(adjustDelta[variantId] ?? "0");
    const note = adjustNote[variantId]?.trim() ?? "";
    if (!delta || !note) {
      setError("Adjustment requires a delta and note.");
      return;
    }
    setError(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/variants/{variant_id}/adjust", {
        params: { path: { club_id: clubId, variant_id: variantId } },
        body: { delta_on_hand: delta, note },
      });
      bumpProducts();
      await productsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    }
  }
  async function collect(orderItemId: string) {
    if (!clubId) return;
    setError(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/merchandise/collect/{order_item_id}", {
        params: { path: { club_id: clubId, order_item_id: orderItemId } },
      });
      bumpProducts();
      await reloadAll();
      setMessage("Marked collected.");
    } catch (err) {
      setError(formatApiError(err));
    }
  }
  const products = productsRes.data ?? [];
  const queue = fulfillmentRes.data ?? [];
  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Merchandise</h1>
        <p className="muted">
          {canManage ? "Manage catalog and inventory. " : ""}
          {canFulfill ? "Fulfill paid orders at pickup." : ""}
        </p>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      {message && <Feedback tone="ok">{message}</Feedback>}
      {canManage && (
        <>
          <form className="panel form" onSubmit={onProductSubmit}>
            <h2>{editProductId ? "Edit product" : "Create product"}</h2>
            <label>
              Name
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </label>
            <label>
              Description
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} />
            </label>
            <div className="row">
              <button className="btn" type="submit" disabled={busy}>
                {busy ? "Saving…" : editProductId ? "Save product" : "Create product"}
              </button>
              {editProductId && (
                <button className="btn btn--ghost" type="button" onClick={resetProductForm}>
                  Cancel edit
                </button>
              )}
            </div>
          </form>
          <PageState
            loading={productsRes.loading}
            error={productsRes.error}
            empty={products.length === 0}
            emptyMessage="No products yet."
          >
            <section className="panel stack">
              {products.map((p) => (
                <div key={p.id} className="stack">
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <div>
                      <strong>{p.name}</strong>{" "}
                      <span className={statusBadgeClass(p.status)}>{p.status}</span>
                      <div className="muted small">{p.description}</div>
                    </div>
                    <div className="row">
                      <button className="btn btn--ghost" type="button" onClick={() => startEditProduct(p)}>
                        Edit
                      </button>
                      {p.status === "active" ? (
                        <button
                          className="btn btn--danger"
                          type="button"
                          onClick={() => {
                            if (window.confirm("Archive this product?")) {
                              void setProductStatus(p.id, "archived");
                            }
                          }}
                        >
                          Archive
                        </button>
                      ) : (
                        <button
                          className="btn btn--ghost"
                          type="button"
                          onClick={() => void setProductStatus(p.id, "active")}
                        >
                          Restore
                        </button>
                      )}
                      <button
                        className="btn btn--ghost"
                        type="button"
                        onClick={() => setVariantProductId(p.id)}
                      >
                        Add variant
                      </button>
                    </div>
                  </div>
                  {p.variants.map((v) => (
                    <div key={v.id} className="row muted small" style={{ justifyContent: "space-between" }}>
                      <span>
                        {v.label} · ₹{v.price} · on hand {v.quantity_on_hand} · available{" "}
                        {v.quantity_available}
                        {!v.is_active && " · inactive"}
                      </span>
                      <div className="row">
                        <input
                          type="number"
                          placeholder="Receive qty"
                          value={stockQty[v.id] ?? ""}
                          onChange={(e) => setStockQty((s) => ({ ...s, [v.id]: e.target.value }))}
                          style={{ width: "5rem" }}
                        />
                        <button className="btn btn--ghost" type="button" onClick={() => void receiveStock(v.id)}>
                          Receive
                        </button>
                        <input
                          type="number"
                          placeholder="Δ"
                          value={adjustDelta[v.id] ?? ""}
                          onChange={(e) => setAdjustDelta((s) => ({ ...s, [v.id]: e.target.value }))}
                          style={{ width: "4rem" }}
                        />
                        <input
                          placeholder="Note"
                          value={adjustNote[v.id] ?? ""}
                          onChange={(e) => setAdjustNote((s) => ({ ...s, [v.id]: e.target.value }))}
                          style={{ width: "8rem" }}
                        />
                        <button className="btn btn--ghost" type="button" onClick={() => void adjustStock(v.id)}>
                          Adjust
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </section>
          </PageState>
          {variantProductId && (
            <form className="panel form" onSubmit={addVariant}>
              <h2>New variant</h2>
              <label>
                Label
                <input value={variantLabel} onChange={(e) => setVariantLabel(e.target.value)} required />
              </label>
              <label>
                SKU
                <input value={variantSku} onChange={(e) => setVariantSku(e.target.value)} required />
              </label>
              <label>
                Price
                <input value={variantPrice} onChange={(e) => setVariantPrice(e.target.value)} required />
              </label>
              <div className="row">
                <button className="btn" type="submit" disabled={busy}>
                  Add variant
                </button>
                <button className="btn btn--ghost" type="button" onClick={() => setVariantProductId(null)}>
                  Cancel
                </button>
              </div>
            </form>
          )}
        </>
      )}
      {canFulfill && (
        <section className="panel stack">
          <h2>Fulfillment queue</h2>
          <PageState
            loading={fulfillmentRes.loading}
            error={fulfillmentRes.error}
            empty={queue.length === 0}
            emptyMessage="Nothing waiting for pickup."
          >
            <table>
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Qty</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {queue.map((row) => (
                  <tr key={row.id}>
                    <td>{row.title_snapshot}</td>
                    <td>{row.quantity}</td>
                    <td>
                      <span className={statusBadgeClass(row.fulfillment_status ?? "pending")}>
                        {row.fulfillment_status ?? "—"}
                      </span>
                    </td>
                    <td>
                      <button className="btn btn--ghost" type="button" onClick={() => void collect(row.id)}>
                        Collect
                      </button>
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

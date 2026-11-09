import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { CatalogueItem } from "../../api";
import { rupees } from "../../format";
import { useApi, useCart } from "../../state";
import { Alert, Badge, Button, Empty, ErrorState, ProductThumb, QtyStepper, StockBadge } from "../../ui";

export function gstLabel(item: Pick<CatalogueItem, "gst_inclusive" | "gst_rate">) {
  return item.gst_inclusive ? `incl. ${Number(item.gst_rate)}% GST` : `excl. GST · ${Number(item.gst_rate)}% added at checkout`;
}

function ProductCard({ item }: { item: CatalogueItem }) {
  const { items, setQty } = useCart();
  const qty = items[item.sku_code] ?? 0;
  const out = item.stock_status === "out_of_stock";
  return (
    <li className="card p-3.5">
      <div className="flex gap-3">
        <ProductThumb name={item.name} />
        <div className="min-w-0 flex-1">
          <p className="font-medium leading-snug">{item.name}</p>
          <p className="mt-0.5 text-xs text-muted">
            {item.sku_code} · {item.pack_size} pack · {item.units_per_case} per case
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <StockBadge status={item.stock_status} cases={out ? undefined : item.available_cases} />
            {item.scheme && <Badge tone="blue">{item.scheme.description}</Badge>}
          </div>
        </div>
      </div>
      <div className="mt-3 flex items-end justify-between gap-3 border-t border-line pt-3">
        <div>
          <p className="tabular text-lg font-semibold leading-none">
            {rupees(item.dealer_price)}
            <span className="text-sm font-normal text-muted"> / case</span>
          </p>
          <p className="mt-1 text-xs text-muted">{gstLabel(item)}</p>
        </div>
        {out ? (
          <Button variant="secondary" size="md" disabled>
            Unavailable
          </Button>
        ) : qty > 0 ? (
          <QtyStepper label={item.name} value={qty} max={item.available_cases} onChange={(n) => setQty(item.sku_code, n)} />
        ) : (
          <Button variant="secondary" onClick={() => setQty(item.sku_code, 1)}>
            Add
          </Button>
        )}
      </div>
    </li>
  );
}

export default function Catalogue() {
  const { data, error, loading, reload } = useApi<{ items: CatalogueItem[]; gst_note: string }>("/retailer/catalogue");
  const { count } = useCart();
  const [q, setQ] = useState("");
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!data) return [];
    if (!needle) return data.items;
    return data.items.filter((i) => `${i.name} ${i.sku_code} ${i.description}`.toLowerCase().includes(needle));
  }, [data, q]);

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Catalogue</h1>
        <Link to="/ai" className="text-sm font-medium text-brand-700">
          Paste a WhatsApp order →
        </Link>
      </div>
      <input
        type="search"
        className="field"
        placeholder="Search biscuit, detergent, tea…"
        aria-label="Search products"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {data && <p className="mt-2 text-xs text-muted">{data.gst_note}</p>}

      <div className="mt-4">
        {loading && !data ? (
          <ul className="grid gap-3" aria-busy="true" aria-label="Loading products">
            {[0, 1, 2].map((i) => (
              <li key={i} className="card p-3.5">
                <div className="flex gap-3">
                  <div className="skeleton h-14 w-14" />
                  <div className="flex-1 space-y-2">
                    <div className="skeleton h-4 w-3/4" />
                    <div className="skeleton h-3 w-1/2" />
                  </div>
                </div>
                <div className="skeleton mt-4 h-9 w-full" />
              </li>
            ))}
          </ul>
        ) : error ? (
          <ErrorState message={error.message} onRetry={reload} />
        ) : filtered.length === 0 ? (
          <Empty title="No products found">Try a different word, like “biscuit” or “chai”.</Empty>
        ) : (
          <ul className="grid gap-3">
            {filtered.map((item) => (
              <ProductCard key={item.sku_code} item={item} />
            ))}
          </ul>
        )}
      </div>

      {count > 0 && (
        <div className="sticky bottom-[calc(4.75rem+env(safe-area-inset-bottom))] mt-4">
          <Link
            to="/cart"
            className="flex min-h-12 items-center justify-between rounded-xl bg-brand-700 px-4 text-white shadow-lg shadow-brand-900/10"
          >
            <span className="font-medium">
              {count} product{count === 1 ? "" : "s"} in cart
            </span>
            <span className="font-semibold">Review order →</span>
          </Link>
        </div>
      )}
      {data && data.items.some((i) => i.data_source !== "client_brief") && (
        <div className="mt-4">
          <Alert tone="blue">Some products are synthetic demo records.</Alert>
        </div>
      )}
    </div>
  );
}

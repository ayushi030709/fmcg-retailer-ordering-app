import { useState } from "react";
import { Link } from "react-router-dom";
import type { OrderStatus, OrderSummary } from "../../api";
import { rupees, STATUS_LABEL, when } from "../../format";
import { useApi } from "../../state";
import { Badge, cx, Empty, ErrorState, PageHeader, Spinner, StatusBadge } from "../../ui";

const TABS: (OrderStatus | "")[] = ["", "pending_review", "on_hold", "approved", "exported", "rejected"];

export default function Queue() {
  const [status, setStatus] = useState<OrderStatus | "">("pending_review");
  const [retailerId, setRetailerId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [q, setQ] = useState("");
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (retailerId) params.set("retailer_id", retailerId);
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  if (q.trim()) params.set("q", q.trim());
  const { data, error, loading, reload } = useApi<{ items: OrderSummary[]; total: number; counts: Record<string, number> }>(
    `/desk/orders?${params.toString()}`,
  );
  const retailers = useApi<{ id: number; code: string; shop_name: string }[]>("/desk/retailers");
  const allCount = data ? Object.values(data.counts).reduce((a, b) => a + b, 0) : undefined;

  return (
    <div>
      <PageHeader
        title="Order queue"
        subtitle="Review orders, resolve holds, and approve them for Tally export."
        action={loading && <Spinner className="h-5 w-5 text-muted" />}
      />

      <div className="flex gap-1 overflow-x-auto border-b border-line" role="tablist">
        {TABS.map((t) => {
          const n = t ? data?.counts[t] ?? 0 : allCount;
          return (
            <button
              key={t || "all"}
              role="tab"
              aria-selected={status === t}
              onClick={() => setStatus(t)}
              className={cx(
                "-mb-px whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium",
                status === t ? "border-brand-700 text-brand-800" : "border-transparent text-muted hover:text-ink",
              )}
            >
              {t ? STATUS_LABEL[t] : "All"}
              {n !== undefined && <span className="tabular ml-1.5 rounded-full bg-canvas px-1.5 text-xs text-muted">{n}</span>}
            </button>
          );
        })}
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-4">
        <input className="field" type="search" placeholder="Order no. or shop" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
        <select className="field" value={retailerId} onChange={(e) => setRetailerId(e.target.value)} aria-label="Retailer">
          <option value="">All retailers</option>
          {retailers.data?.map((r) => (
            <option key={r.id} value={r.id}>
              {r.shop_name}
            </option>
          ))}
        </select>
        <input className="field" type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From date" />
        <input className="field" type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To date" />
      </div>

      <div className="mt-4">
        {error ? (
          <ErrorState message={error.status === 403 ? "You don't have access to the order desk." : error.message} onRetry={reload} />
        ) : !data ? (
          <div className="card space-y-3 p-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton h-10" />
            ))}
          </div>
        ) : data.items.length === 0 ? (
          <Empty title="No orders here">Try another status tab or clear the filters.</Empty>
        ) : (
          <>
            <div className="card hidden overflow-x-auto md:block">
              <table className="w-full text-sm">
                <thead className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Order</th>
                    <th className="px-4 py-2.5 font-medium">Retailer</th>
                    <th className="px-4 py-2.5 font-medium">Placed</th>
                    <th className="px-4 py-2.5 font-medium">Source</th>
                    <th className="px-4 py-2.5 text-right font-medium">Amount</th>
                    <th className="px-4 py-2.5 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {data.items.map((o) => (
                    <tr key={o.id} className="hover:bg-canvas/60">
                      <td className="px-4 py-3">
                        <Link to={`/desk/orders/${o.id}`} className="tabular font-medium text-brand-700 hover:underline">
                          {o.order_number}
                        </Link>
                        <p className="text-xs text-muted">{o.line_count} line{o.line_count === 1 ? "" : "s"}</p>
                      </td>
                      <td className="px-4 py-3">{o.retailer.shop_name}</td>
                      <td className="px-4 py-3 text-muted">{when(o.created_at)}</td>
                      <td className="px-4 py-3">{o.source === "ai" ? <Badge tone="blue">AI</Badge> : <span className="text-muted">Manual</span>}</td>
                      <td className="tabular px-4 py-3 text-right font-medium">{rupees(o.grand_total)}</td>
                      <td className="px-4 py-3">
                        <StatusBadge status={o.status} />
                        {o.hold_reason && o.status === "on_hold" && (
                          <p className="mt-1 max-w-xs text-xs text-amber-800" title={o.hold_reason}>
                            {o.hold_reason.split(":")[0]}
                          </p>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="grid gap-2.5 md:hidden">
              {data.items.map((o) => (
                <li key={o.id}>
                  <Link to={`/desk/orders/${o.id}`} className="card block p-3.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="tabular font-medium">{o.order_number}</span>
                      <StatusBadge status={o.status} />
                    </div>
                    <p className="mt-1 text-sm">{o.retailer.shop_name}</p>
                    <div className="mt-1 flex justify-between text-sm text-muted">
                      <span>
                        {when(o.created_at)} {o.source === "ai" && "· AI"}
                      </span>
                      <span className="tabular font-medium text-ink">{rupees(o.grand_total)}</span>
                    </div>
                    {o.hold_reason && o.status === "on_hold" && <p className="mt-1 text-xs text-amber-800">{o.hold_reason.split(":")[0]}</p>}
                  </Link>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted">
              Showing {data.items.length} of {data.total}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

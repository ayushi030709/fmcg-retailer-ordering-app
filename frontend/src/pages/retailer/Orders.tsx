import { Link, useLocation, useParams } from "react-router-dom";
import type { Order, OrderSummary } from "../../api";
import { cases, pct, rupees, STATUS_HELP, when } from "../../format";
import { useApi } from "../../state";
import { Alert, Badge, Button, Empty, ErrorState, PageHeader, Row, StatusBadge } from "../../ui";

export function OrdersList() {
  const { data, error, loading, reload } = useApi<{ items: OrderSummary[] }>("/retailer/orders");
  return (
    <div>
      <PageHeader title="My orders" />
      {loading && !data ? (
        <div className="grid gap-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card space-y-2 p-4">
              <div className="skeleton h-4 w-1/3" />
              <div className="skeleton h-3 w-1/2" />
            </div>
          ))}
        </div>
      ) : error ? (
        <ErrorState message={error.message} onRetry={reload} />
      ) : !data?.items.length ? (
        <Empty title="No orders yet" action={<Link to="/"><Button>Start an order</Button></Link>} />
      ) : (
        <ul className="grid gap-2.5">
          {data.items.map((o) => (
            <li key={o.id}>
              <Link to={`/orders/${o.id}`} className="card block p-4 hover:border-brand-200">
                <div className="flex items-center justify-between gap-3">
                  <span className="tabular font-medium">{o.order_number}</span>
                  <StatusBadge status={o.status} />
                </div>
                <div className="mt-1.5 flex items-center justify-between gap-3 text-sm text-muted">
                  <span>
                    {when(o.created_at)} · {o.line_count} item{o.line_count === 1 ? "" : "s"}
                    {o.source === "ai" && " · via AI"}
                  </span>
                  <span className="tabular font-semibold text-ink">{rupees(o.grand_total)}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function OrderDetail() {
  const { id } = useParams();
  const location = useLocation();
  const placed = (location.state as { placed?: boolean; message?: string } | null) ?? null;
  const { data: order, error, loading, reload } = useApi<Order>(`/retailer/orders/${id}`);

  if (loading && !order) return <div className="card skeleton h-48" />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!order) return null;

  return (
    <div className="grid gap-4">
      {placed?.placed && (
        <Alert tone={order.status === "on_hold" ? "amber" : "green"} title={`Order ${order.order_number} placed`}>
          {placed.message} Keep this reference for any questions.
        </Alert>
      )}
      <div className="card p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs text-muted">Order reference</p>
            <p className="tabular text-xl font-semibold">{order.order_number}</p>
            <p className="mt-0.5 text-sm text-muted">
              {when(order.created_at)} · {order.source === "ai" ? "Captured with AI, confirmed by you" : "Placed from catalogue"}
            </p>
          </div>
          <StatusBadge status={order.status} />
        </div>
        <p className="mt-3 text-sm text-muted">{STATUS_HELP[order.status]}</p>
        {order.hold_reason && order.status === "on_hold" && (
          <div className="mt-3">
            <Alert tone="amber" title="Why it's on hold">
              {order.hold_reason}
            </Alert>
          </div>
        )}
        {order.status_note && order.status !== "on_hold" && <p className="mt-2 text-sm">Note from order desk: {order.status_note}</p>}
      </div>

      <ul className="card divide-y divide-line">
        {order.items.map((i) => (
          <li key={i.id} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium leading-snug">{i.product_name}</p>
                <p className="tabular mt-0.5 text-sm text-muted">
                  {cases(i.paid_qty)} × {rupees(i.unit_price)}
                  {i.free_qty > 0 && <span className="text-brand-700"> + {cases(i.free_qty)} free</span>}
                  {Number(i.discount_amount) > 0 && <> · {pct(i.discount_percent)} off</>}
                </p>
                {i.original_phrase && <p className="mt-1 text-xs text-muted">You wrote: “{i.original_phrase}”</p>}
              </div>
              <p className="tabular shrink-0 font-semibold">{rupees(i.line_total)}</p>
            </div>
            {i.scheme_applied && <Badge tone="blue" className="mt-2">{i.scheme_applied}</Badge>}
          </li>
        ))}
      </ul>

      <div className="card p-4">
        <Row label="Subtotal" value={rupees(order.subtotal)} />
        {Number(order.discount_total) > 0 && <Row label="Scheme discount" value={`− ${rupees(order.discount_total)}`} />}
        <Row label="Taxable value" value={rupees(order.taxable_total)} muted />
        <Row label="GST" value={rupees(order.tax_total)} muted />
        <div className="mt-1 border-t border-line pt-2">
          <Row label="Total" value={rupees(order.grand_total)} strong />
        </div>
      </div>
      <Link to="/orders" className="text-center text-sm font-medium text-brand-700">
        ← All orders
      </Link>
    </div>
  );
}

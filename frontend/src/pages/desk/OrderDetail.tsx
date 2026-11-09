import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, type DeskOrderDetail, type OrderItem } from "../../api";
import { pct, rupees, when } from "../../format";
import { useApi } from "../../state";
import { Alert, Badge, Button, cx, ErrorState, Row, Spinner, StatusBadge } from "../../ui";

type Action = "approve" | "hold" | "release" | "reject";

const ACTION_LABEL: Record<Action, string> = { approve: "Approve", hold: "Put on hold", release: "Release hold", reject: "Reject" };

interface ProductOption {
  sku_code: string;
  name: string;
  pack_size: string;
  available_cases: number;
}

function CorrectionForm({
  item,
  version,
  orderId,
  products,
  onDone,
  onCancel,
}: {
  products: ProductOption[];
  item: OrderItem;
  version: number;
  orderId: number;
  onDone: (d: DeskOrderDetail) => void;
  onCancel: () => void;
}) {
  const [sku, setSku] = useState(item.sku_code);
  const [qty, setQty] = useState(String(item.paid_qty));
  const [reason, setReason] = useState("");
  const [saveAlias, setSaveAlias] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const qtyNum = /^\d+$/.test(qty) ? parseInt(qty, 10) : NaN;
  const changed = sku !== item.sku_code || qtyNum !== item.paid_qty;

  async function save() {
    if (!(qtyNum >= 1 && qtyNum <= 5000)) return setError("Quantity must be a whole number of cases (1–5000).");
    if (reason.trim().length < 3) return setError("Add a short reason for the audit trail.");
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { version, reason, save_alias: saveAlias && sku !== item.sku_code };
      if (qtyNum !== item.paid_qty) body.paid_qty = qtyNum;
      if (sku !== item.sku_code) body.sku_code = sku;
      onDone(await api<DeskOrderDetail>(`/desk/orders/${orderId}/items/${item.id}`, { method: "PATCH", body }));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 grid gap-2 rounded-lg bg-canvas p-3">
      <div className="grid gap-2 sm:grid-cols-[1fr_8rem]">
        <select className="field" value={sku} onChange={(e) => setSku(e.target.value)} aria-label="Product">
          {products.map((p) => (
            <option key={p.sku_code} value={p.sku_code}>
              {p.name} ({p.available_cases} cases free)
            </option>
          ))}
        </select>
        <input className="field tabular" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, ""))} aria-label="Paid cases" />
      </div>
      <input className="field" placeholder="Reason (e.g. retailer called to change)" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Reason" />
      {item.original_phrase && sku !== item.sku_code && (
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1 h-4 w-4 accent-brand-700" checked={saveAlias} onChange={(e) => setSaveAlias(e.target.checked)} />
          <span>Remember “{item.original_phrase}” → this product for this retailer</span>
        </label>
      )}
      {error && <p className="text-sm text-red-700">{error}</p>}
      <div className="flex gap-2">
        <Button size="sm" onClick={save} busy={busy} disabled={!changed}>
          Save correction
        </Button>
        <Button size="sm" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function describe(e: DeskOrderDetail["audit"][number]): string {
  const map: Record<string, string> = {
    created: "Order placed",
    approve: "Approved",
    approve_override: "Approved from hold (override)",
    hold: "Put on hold",
    release: "Hold released",
    reject: "Rejected",
    line_corrected: "Line corrected",
    exported: "Exported to Tally CSV",
  };
  return map[e.action] ?? e.action;
}

function diff(before: Record<string, unknown> | null, after: Record<string, unknown> | null): string | null {
  if (!before || !after) return null;
  const keys = Object.keys(after).filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]));
  if (!keys.length) return null;
  return keys.map((k) => `${k}: ${String(before[k] ?? "—")} → ${String(after[k] ?? "—")}`).join(", ");
}

export default function DeskOrderDetailPage() {
  const { id } = useParams();
  const { data, setData, error, loading, reload } = useApi<DeskOrderDetail>(`/desk/orders/${id}`);
  const [pending, setPending] = useState<Action | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const products = useApi<ProductOption[]>("/desk/products", [data?.order.version]);

  if (loading && !data)
    return (
      <div className="flex justify-center py-16 text-muted">
        <Spinner />
      </div>
    );
  if (error) return <ErrorState message={error.status === 404 ? "Order not found." : error.message} onRetry={reload} />;
  if (!data) return null;
  const { order, retailer, credit } = data;
  const fromHold = order.status === "on_hold";
  const needsReason = pending === "hold" || pending === "reject" || (pending === "approve" && fromHold);

  async function run(action: Action) {
    setBusy(true);
    setActionError(null);
    try {
      const res = await api<DeskOrderDetail>(`/desk/orders/${order.id}`, {
        method: "PATCH",
        body: { action, version: order.version, reason: reason.trim() || null },
      });
      setData(res);
      setPending(null);
      setReason("");
    } catch (e) {
      setActionError(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  const actions = data.allowed_actions.filter((a): a is Action => a in ACTION_LABEL);

  return (
    <div>
      <Link to="/desk" className="text-sm font-medium text-brand-700">
        ← Order queue
      </Link>
      <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="tabular text-xl font-semibold">{order.order_number}</h1>
            <StatusBadge status={order.status} />
            {order.source === "ai" && <Badge tone="blue">AI-captured</Badge>}
          </div>
          <p className="mt-0.5 text-sm text-muted">
            {retailer.shop_name} ({retailer.code}) · placed {when(order.created_at)} · version {order.version}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {actions.map((a) => (
            <Button
              key={a}
              variant={a === "approve" ? "primary" : a === "reject" ? "danger" : "secondary"}
              size="sm"
              onClick={() => {
                setPending(a);
                setReason("");
                setActionError(null);
              }}
            >
              {ACTION_LABEL[a]}
            </Button>
          ))}
        </div>
      </div>

      {pending && (
        <div className="card mt-3 p-4">
          <p className="font-medium">
            {ACTION_LABEL[pending]} {order.order_number}?
          </p>
          {pending === "approve" && fromHold && (
            <p className="mt-1 text-sm text-amber-800">This order is on hold. Approving it overrides the hold — add a note explaining why.</p>
          )}
          {(needsReason || pending === "release") && (
            <textarea
              className="field mt-2"
              rows={2}
              placeholder={needsReason ? "Reason (required)" : "Note (optional)"}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-label="Reason"
            />
          )}
          <div className="mt-3 flex gap-2">
            <Button size="sm" variant={pending === "reject" ? "danger" : "primary"} busy={busy} disabled={needsReason && reason.trim().length < 3} onClick={() => run(pending)}>
              Confirm {ACTION_LABEL[pending].toLowerCase()}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setPending(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
      {actionError && (
        <div className="mt-3">
          <Alert
            tone={actionError.code === "stale_order" ? "amber" : "red"}
            title={actionError.code === "stale_order" ? "Someone else updated this order" : "Action failed"}
            action={actionError.code === "stale_order" && (
              <Button size="sm" variant="secondary" onClick={() => { setActionError(null); setPending(null); reload(); }}>
                Reload latest
              </Button>
            )}
          >
            {actionError.message}
          </Alert>
        </div>
      )}
      {order.status === "on_hold" && order.hold_reason && (
        <div className="mt-3">
          <Alert tone="amber" title="On hold">
            {order.hold_reason}
          </Alert>
        </div>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_20rem]">
        <div className="grid content-start gap-4">
          {data.ai_message && (
            <div className="card p-4">
              <p className="text-xs font-medium uppercase tracking-wide text-muted">Original AI message · {data.ai_message.provider}</p>
              <p className="mt-1 whitespace-pre-wrap">{data.ai_message.message}</p>
            </div>
          )}
          <div className="card divide-y divide-line">
            {order.items.map((i) => {
              const available = data.stock[String(i.product_id)];
              return (
                <div key={i.id} className="p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-medium">{i.product_name}</p>
                      <p className="text-xs text-muted">
                        {i.sku_code} · {available !== undefined ? `${available} cases available after reservations` : ""}
                      </p>
                      {i.original_phrase && <p className="mt-1 text-sm">Retailer wrote: “{i.original_phrase}”</p>}
                    </div>
                    <div className="text-right">
                      <p className="tabular font-semibold">{rupees(i.line_total)}</p>
                      {data.allowed_actions.includes("correct") && editing !== i.id && (
                        <button className="mt-1 text-sm font-medium text-brand-700" onClick={() => setEditing(i.id)}>
                          Correct line
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="tabular mt-2 grid grid-cols-2 gap-x-4 text-sm text-muted sm:grid-cols-4">
                    <span>Paid: <span className="text-ink">{i.paid_qty}</span></span>
                    <span>Free: <span className={cx(i.free_qty ? "text-brand-700" : "text-ink")}>{i.free_qty}</span></span>
                    <span>Rate: <span className="text-ink">{rupees(i.unit_price)}</span></span>
                    <span>Disc: <span className="text-ink">{Number(i.discount_amount) ? `${pct(i.discount_percent)} ${rupees(i.discount_amount)}` : "—"}</span></span>
                    <span>Taxable: <span className="text-ink">{rupees(i.taxable_amount)}</span></span>
                    <span>GST {pct(i.gst_rate)}: <span className="text-ink">{rupees(i.tax_amount)}</span></span>
                  </div>
                  {i.scheme_applied && <Badge tone="blue" className="mt-2">{i.scheme_applied}</Badge>}
                  {editing === i.id && (
                    <CorrectionForm
                      item={i}
                      version={order.version}
                      orderId={order.id}
                      products={products.data ?? []}
                      onCancel={() => setEditing(null)}
                      onDone={(d) => {
                        setData(d);
                        setEditing(null);
                      }}
                    />
                  )}
                </div>
              );
            })}
          </div>

          <div className="card p-4">
            <p className="text-sm font-medium">History</p>
            <ol className="mt-2 space-y-3">
              {data.audit.map((e) => (
                <li key={e.id} className="border-l-2 border-line pl-3 text-sm">
                  <p>
                    <span className="font-medium">{describe(e)}</span>
                    <span className="text-muted"> · {e.actor ?? "system"} · {when(e.created_at)}</span>
                  </p>
                  {e.action === "line_corrected" && diff(e.before, e.after) && <p className="tabular text-xs text-muted">{diff(e.before, e.after)}</p>}
                  {e.note && <p className="text-xs text-muted">{e.note}</p>}
                </li>
              ))}
            </ol>
          </div>
        </div>

        <div className="grid content-start gap-4">
          <div className="card p-4">
            <p className="text-sm font-medium">Credit check</p>
            <Row label="Credit limit" value={rupees(credit.credit_limit)} />
            <Row label="Outstanding" value={rupees(credit.outstanding_balance)} />
            <Row label="Other open orders" value={rupees(credit.open_orders_total)} />
            <Row label="Available" value={rupees(credit.available_credit)} />
            <Row label="This order" value={rupees(credit.order_total)} />
            <div className="mt-2">
              {credit.within_limit ? <Badge tone="green">Within limit</Badge> : <Badge tone="red">Exceeds available credit</Badge>}
            </div>
            {retailer.is_demo_data && <p className="mt-2 text-xs text-muted">Synthetic demo credit data.</p>}
          </div>
          <div className="card p-4">
            <Row label="Subtotal" value={rupees(order.subtotal)} />
            <Row label="Discount" value={`− ${rupees(order.discount_total)}`} />
            <Row label="Taxable" value={rupees(order.taxable_total)} muted />
            <Row label="GST" value={rupees(order.tax_total)} muted />
            <div className="mt-1 border-t border-line pt-2">
              <Row label="Total" value={rupees(order.grand_total)} strong />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

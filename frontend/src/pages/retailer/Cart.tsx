import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, newRequestId, type Issue, type Order, type Preview } from "../../api";
import { rupees } from "../../format";
import { useAuth, useCart } from "../../state";
import { Alert, Button, Empty, ErrorState, PageHeader, QtyStepper, Spinner, StockBadge } from "../../ui";
import { CreditNote, LineBreakdown, TotalsCard } from "./OrderSummary";

export default function Cart() {
  const { items, setQty, remove, clear } = useCart();
  const { refresh } = useAuth();
  const navigate = useNavigate();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<ApiError | null>(null);
  const [tick, setTick] = useState(0);

  const lines = useMemo(
    () => Object.entries(items).map(([sku_code, paid_qty]) => ({ sku_code, paid_qty })),
    [items],
  );
  const cartKey = JSON.stringify(lines);
  // One idempotency key per cart content: a retried submit after a dropped
  // connection cannot create a duplicate order.
  const requestId = useMemo(() => newRequestId(), [cartKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (lines.length === 0) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const t = setTimeout(() => {
      api<Preview>("/orders/preview", { method: "POST", body: { lines } })
        .then((p) => {
          if (!cancelled) {
            setPreview(p);
            setError(null);
          }
        })
        .catch((e: ApiError) => !cancelled && setError(e))
        .finally(() => !cancelled && setLoading(false));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [cartKey, tick]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await api<{ order: Order; created: boolean; message: string }>("/orders", {
        method: "POST",
        body: { client_request_id: requestId, lines },
      });
      clear();
      void refresh();
      navigate(`/orders/${res.order.id}`, { state: { placed: true, message: res.message } });
    } catch (e) {
      setSubmitError(e as ApiError);
      setTick((t) => t + 1);
    } finally {
      setSubmitting(false);
    }
  }

  if (lines.length === 0)
    return (
      <div>
        <PageHeader title="Cart" />
        <Empty
          title="Your cart is empty"
          action={
            <div className="flex gap-2">
              <Link to="/">
                <Button variant="secondary">Browse catalogue</Button>
              </Link>
              <Link to="/ai">
                <Button>Paste an order</Button>
              </Link>
            </div>
          }
        >
          Add products from the catalogue, or paste a WhatsApp message and let AI fill the order for you to check.
        </Empty>
      </div>
    );

  const issuesBySku = new Map<string, Issue[]>();
  for (const i of preview?.issues ?? []) {
    if (i.sku_code) issuesBySku.set(i.sku_code, [...(issuesBySku.get(i.sku_code) ?? []), i]);
  }
  const generalIssues = (preview?.issues ?? []).filter((i) => !i.sku_code);
  const submitDetails = Array.isArray(submitError?.details) ? (submitError?.details as Issue[]) : [];

  return (
    <div>
      <PageHeader
        title="Cart"
        subtitle="Review quantities. Prices, schemes, stock and credit are checked by the server."
        action={loading && <Spinner className="h-5 w-5 text-muted" />}
      />

      {error && !preview ? (
        <ErrorState message={error.message} onRetry={() => setTick((t) => t + 1)} />
      ) : !preview ? (
        <div className="grid gap-3" aria-busy="true">
          {lines.map((l) => (
            <div key={l.sku_code} className="card space-y-2 p-4">
              <div className="skeleton h-4 w-2/3" />
              <div className="skeleton h-3 w-1/2" />
            </div>
          ))}
        </div>
      ) : (
        <div className={loading ? "opacity-70 transition-opacity" : ""}>
          {error && (
            <div className="mb-3">
              <Alert tone="red">Couldn't refresh prices: {error.message}</Alert>
            </div>
          )}
          <ul className="grid gap-3">
            {lines.map(({ sku_code, paid_qty }) => {
              const line = preview.lines.find((l) => l.sku_code === sku_code);
              const issues = issuesBySku.get(sku_code) ?? [];
              return (
                <li key={sku_code} className="card p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-medium leading-snug">{line?.name ?? sku_code}</p>
                      {line && (
                        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                          <span>{rupees(line.unit_price)} / case</span>
                          <StockBadge status={line.stock_status} cases={line.available_cases} />
                        </div>
                      )}
                    </div>
                    <button onClick={() => remove(sku_code)} className="shrink-0 rounded px-2 py-1 text-sm text-muted hover:bg-canvas hover:text-red-700">
                      Remove
                    </button>
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-3">
                    <QtyStepper label={line?.name ?? sku_code} value={paid_qty} onChange={(n) => setQty(sku_code, n)} />
                    {line && <p className="tabular font-semibold">{rupees(line.line_total)}</p>}
                  </div>
                  {line?.scheme_applied && <p className="mt-2 text-xs font-medium text-brand-700">Scheme applied: {line.scheme_applied}</p>}
                  {line && <LineBreakdown line={line} />}
                  {issues.map((i) => (
                    <div key={i.code} className="mt-2">
                      <Alert tone="red">{i.message}</Alert>
                    </div>
                  ))}
                </li>
              );
            })}
          </ul>

          <div className="mt-4 grid gap-3">
            {generalIssues.map((i) => (
              <Alert key={i.code} tone="red">
                {i.message}
              </Alert>
            ))}
            {preview.warnings.map((w) => (
              <Alert key={w} tone="amber" title="Credit review needed">
                {w}
              </Alert>
            ))}
            <TotalsCard totals={preview.totals} lines={preview.lines} />
            <CreditNote credit={preview.credit} willBeHeld={preview.will_be_held} />
            {submitError && (
              <Alert tone="red" title="Order not placed">
                {submitError.message}
                {submitDetails.length > 0 && (
                  <ul className="mt-1 list-disc pl-5">
                    {submitDetails.map((d) => (
                      <li key={`${d.code}-${d.sku_code}`}>{d.message}</li>
                    ))}
                  </ul>
                )}
              </Alert>
            )}
            <Button size="lg" onClick={submit} busy={submitting} disabled={!preview.can_submit || loading}>
              {preview.will_be_held ? "Place order for credit review" : "Place order"} · {rupees(preview.totals.grand_total)}
            </Button>
            {!preview.can_submit && <p className="text-center text-sm text-red-700">Fix the highlighted lines to continue.</p>}
          </div>
        </div>
      )}
    </div>
  );
}

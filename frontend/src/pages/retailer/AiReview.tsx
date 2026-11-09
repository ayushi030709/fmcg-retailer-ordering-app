import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  api,
  ApiError,
  newRequestId,
  type CatalogueItem,
  type ExtractedLine,
  type Extraction,
  type Issue,
  type Order,
  type OrderLineIn,
  type Preview,
} from "../../api";
import { rupees } from "../../format";
import { useApi, useAuth } from "../../state";
import { Alert, Badge, Button, ConfidenceBadge, cx, ErrorState, PageHeader, Spinner, StockBadge } from "../../ui";
import { CreditNote, LineBreakdown, TotalsCard } from "./OrderSummary";

interface LineState {
  removed: boolean;
  sku: string | null;
  qty: string;
  unitAnswer: "auto" | "yes" | "no" | null; // auto = already confirmed by explicit word or saved alias
  rememberUnit: boolean;
  qtyChecked: boolean;
  productTouched: boolean;
  rememberProduct: boolean;
}

function initialState(line: ExtractedLine): LineState {
  return {
    removed: false,
    sku: line.candidate && !line.needs_sku_choice ? line.candidate.sku_code : null,
    qty: line.quantity ? String(line.quantity) : "",
    unitAnswer: line.unit_confirmed ? "auto" : null,
    rememberUnit: true,
    qtyChecked: !line.clarifications.some((c) => c.type === "quantity"),
    productTouched: false,
    rememberProduct: false,
  };
}

function parseQty(raw: string): number | null {
  if (!/^\d+$/.test(raw.trim())) return null;
  const n = parseInt(raw, 10);
  return n >= 1 && n <= 5000 ? n : null;
}

/** What still needs the retailer's attention on a line. Empty = ready. */
function problems(line: ExtractedLine, s: LineState, products: Map<string, CatalogueItem>, dupes: Set<string>): string[] {
  if (s.removed) return [];
  const out: string[] = [];
  if (!s.sku) out.push(line.candidate ? "Confirm which product you meant" : "Choose a product or remove this line");
  else if (products.get(s.sku)?.stock_status === "out_of_stock") out.push("Out of stock — remove this line or pick another product");
  if (s.sku && dupes.has(s.sku)) out.push("This product is on another line too — remove one");
  if (parseQty(s.qty) === null) out.push("Enter a whole number of cases (1–5000)");
  if (!s.unitAnswer) out.push("Answer the unit question");
  if (!s.qtyChecked) out.push("Check the quantity");
  return out;
}

function LineCard({
  line,
  state,
  set,
  products,
  issues,
  problemsList,
}: {
  line: ExtractedLine;
  state: LineState;
  set: (patch: Partial<LineState>) => void;
  products: CatalogueItem[];
  issues: Issue[];
  problemsList: string[];
}) {
  const chosen = products.find((p) => p.sku_code === state.sku) ?? null;
  const unitQ = line.clarifications.find((c) => c.type === "unit");
  const qtyQ = line.clarifications.find((c) => c.type === "quantity");
  const skuQ = line.clarifications.find((c) => c.type === "sku");
  const ready = !state.removed && problemsList.length === 0;

  if (state.removed)
    return (
      <li className="card flex items-center justify-between gap-3 border-dashed p-3.5 text-sm text-muted">
        <span className="min-w-0 truncate line-through">“{line.original_text}”</span>
        <Button variant="ghost" size="sm" onClick={() => set({ removed: false })}>
          Undo
        </Button>
      </li>
    );

  return (
    <li className={cx("card p-4", ready ? "border-brand-200" : "border-amber-200")}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-muted">You wrote</p>
          <p className="mt-0.5 text-[15px] font-medium leading-snug">“{line.original_text}”</p>
        </div>
        {ready ? <Badge tone="green">Ready</Badge> : <Badge tone="amber">Needs you</Badge>}
      </div>

      {/* Product */}
      <div className="mt-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">Product</span>
          <ConfidenceBadge band={line.confidence_band} score={line.confidence} />
        </div>
        {line.evidence.length > 0 && <p className="mt-1 text-xs text-muted">Why: {line.evidence.join(" · ")}</p>}
        {skuQ && !state.productTouched && <p className="mt-1.5 text-sm text-amber-800">{skuQ.question}</p>}
        <select
          className="field mt-2"
          aria-label={`Product for “${line.original_text}”`}
          value={state.sku ?? ""}
          onChange={(e) => {
            const sku = e.target.value || null;
            set({ sku, productTouched: true, rememberProduct: !!sku && sku !== line.candidate?.sku_code });
          }}
        >
          <option value="">Choose a product…</option>
          {products.map((p) => (
            <option key={p.sku_code} value={p.sku_code}>
              {p.name}
              {p.stock_status === "out_of_stock" ? " — out of stock" : ""}
            </option>
          ))}
        </select>
        {line.alternatives.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-muted">{line.candidate ? "Or did you mean:" : "Closest products:"}</span>
            {[...(line.candidate && line.needs_sku_choice ? [{ sku_code: line.candidate.sku_code, name: line.candidate.name, score: line.confidence }] : []), ...line.alternatives].map((a) => (
              <button
                key={a.sku_code}
                type="button"
                onClick={() => set({ sku: a.sku_code, productTouched: true, rememberProduct: a.sku_code !== line.candidate?.sku_code })}
                className={cx(
                  "rounded-full border px-2.5 py-1 hover:border-brand-600",
                  state.sku === a.sku_code ? "border-brand-600 bg-brand-50 text-brand-800" : "border-line bg-white",
                )}
              >
                {a.name}{" "}
                <span className="tabular text-muted">{a.score < 0.3 ? "unlikely" : `${Math.round(a.score * 100)}%`}</span>
              </button>
            ))}
          </div>
        )}
        {chosen && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted">
            <span className="tabular">{rupees(chosen.dealer_price)} / case</span>
            <StockBadge status={chosen.stock_status} cases={chosen.stock_status === "out_of_stock" ? undefined : chosen.available_cases} />
            {chosen.scheme && <Badge tone="blue">{chosen.scheme.description}</Badge>}
          </div>
        )}
        {chosen?.stock_status === "out_of_stock" && (
          <div className="mt-2">
            <Alert tone="red">
              {chosen.name} is out of stock. Remove this line or choose another product — it can't be ordered.
            </Alert>
          </div>
        )}
        {chosen && line.product_phrase && (state.sku !== line.candidate?.sku_code || line.confidence_band !== "high") && (
          <label className="mt-2 flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1 h-4 w-4 accent-brand-700"
              checked={state.rememberProduct}
              onChange={(e) => set({ rememberProduct: e.target.checked })}
            />
            <span>
              Remember that “{line.product_phrase}” means {chosen.name} for my future orders
            </span>
          </label>
        )}
      </div>

      {/* Quantity + unit */}
      <div className="mt-4">
        <label className="text-sm font-medium" htmlFor={`qty-${line.line_id}`}>
          Quantity (cases)
        </label>
        <div className="mt-1.5 flex items-center gap-2">
          <input
            id={`qty-${line.line_id}`}
            inputMode="numeric"
            className="field tabular w-28"
            value={state.qty}
            onChange={(e) => set({ qty: e.target.value.replace(/\D/g, "").slice(0, 4) })}
          />
          <span className="text-sm text-muted">cases{chosen ? ` of ${chosen.units_per_case}` : ""}</span>
        </div>
        {qtyQ && (
          <label className="mt-2 flex items-start gap-2 rounded-lg bg-amber-50 p-2.5 text-sm text-amber-900">
            <input type="checkbox" className="mt-1 h-4 w-4 accent-brand-700" checked={state.qtyChecked} onChange={(e) => set({ qtyChecked: e.target.checked })} />
            <span>
              {qtyQ.question} <span className="font-medium">I've checked the quantity.</span>
            </span>
          </label>
        )}

        {unitQ && state.unitAnswer === null && (
          <div className="mt-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
            <p className="font-medium">{unitQ.question}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {line.unit === "unknown" && (
                <Button size="sm" onClick={() => set({ unitAnswer: "yes" })}>
                  {line.unit_text ? `Yes, 1 ${line.unit_text} = 1 case` : "Yes, it's in cases"}
                </Button>
              )}
              <Button size="sm" variant="secondary" onClick={() => set({ unitAnswer: "no" })}>
                {line.unit === "unknown" ? "No — I've entered cases above" : "I've entered cases above"}
              </Button>
            </div>
          </div>
        )}
        {state.unitAnswer === "auto" && (
          <p className="mt-1.5 text-xs text-muted">
            Unit: case{line.unit_source === "retailer_alias" ? ` (you've told us “${line.unit_text}” means a case)` : ""}
          </p>
        )}
        {(state.unitAnswer === "yes" || state.unitAnswer === "no") && (
          <div className="mt-1.5 text-xs text-muted">
            ✓ Quantity confirmed in cases.{" "}
            <button type="button" className="font-medium text-brand-700" onClick={() => set({ unitAnswer: null })}>
              Change
            </button>
          </div>
        )}
        {state.unitAnswer === "yes" && line.unit_text && (
          <label className="mt-2 flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1 h-4 w-4 accent-brand-700" checked={state.rememberUnit} onChange={(e) => set({ rememberUnit: e.target.checked })} />
            <span>Remember that “{line.unit_text}” means one case for my future orders</span>
          </label>
        )}
      </div>

      {issues.filter((i) => i.code !== "out_of_stock").map((i) => (
        <div key={i.code} className="mt-3">
          <Alert tone="red">{i.message}</Alert>
        </div>
      ))}

      {problemsList.length > 0 && (
        <ul className="mt-3 space-y-0.5 text-xs text-amber-800">
          {problemsList.filter((p) => !p.startsWith("Out of stock")).map((p) => (
            <li key={p}>• {p}</li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex items-center justify-between border-t border-line pt-3">
        {line.ai_reasoning ? <p className="min-w-0 truncate pr-2 text-xs text-muted" title={line.ai_reasoning}>AI note: {line.ai_reasoning}</p> : <span />}
        <Button variant="ghost" size="sm" onClick={() => set({ removed: true })}>
          Don't order this
        </Button>
      </div>
    </li>
  );
}

export default function AiReview() {
  const { id } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const passed = location.state as Extraction | null;
  const fromState = passed && String(passed.extraction_id) === id ? passed : null;
  const fetched = useApi<Extraction>(fromState ? null : `/ai/extractions/${id}`);
  const extraction = fromState ?? fetched.data;
  const catalogue = useApi<{ items: CatalogueItem[] }>("/retailer/catalogue");
  const products = useMemo(() => catalogue.data?.items ?? [], [catalogue.data]);
  const productMap = useMemo(() => new Map(products.map((p) => [p.sku_code, p])), [products]);

  const [states, setStates] = useState<Record<number, LineState>>({});
  useEffect(() => {
    if (extraction) setStates(Object.fromEntries(extraction.lines.map((l) => [l.line_id, initialState(l)])));
  }, [extraction]);

  const kept = extraction?.lines.filter((l) => states[l.line_id] && !states[l.line_id].removed) ?? [];
  const skuCounts = new Map<string, number>();
  kept.forEach((l) => {
    const sku = states[l.line_id].sku;
    if (sku) skuCounts.set(sku, (skuCounts.get(sku) ?? 0) + 1);
  });
  const dupes = new Set([...skuCounts].filter(([, n]) => n > 1).map(([s]) => s));
  const problemMap = new Map(
    (extraction?.lines ?? []).filter((l) => states[l.line_id]).map((l) => [l.line_id, problems(l, states[l.line_id], productMap, dupes)]),
  );
  const unresolved = kept.filter((l) => (problemMap.get(l.line_id) ?? []).length > 0).length;

  const payload: OrderLineIn[] = useMemo(
    () =>
      kept
        .filter((l) => states[l.line_id].sku && parseQty(states[l.line_id].qty))
        .map((l) => {
          const s = states[l.line_id];
          return {
            sku_code: s.sku!,
            paid_qty: parseQty(s.qty)!,
            original_phrase: l.original_text,
            unit_confirmed: s.unitAnswer !== null,
            unit_alias: s.unitAnswer === "yes" ? l.unit_text : null,
            remember_unit_alias: s.unitAnswer === "yes" && s.rememberUnit,
            remember_product_alias: s.rememberProduct,
          };
        }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(states), extraction],
  );
  const payloadKey = JSON.stringify(payload);
  const requestId = useMemo(() => newRequestId(), [payloadKey]);

  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  useEffect(() => {
    if (!payload.length || dupes.size) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    setPreviewing(true);
    const t = setTimeout(() => {
      api<Preview>("/orders/preview", { method: "POST", body: { lines: payload.map(({ sku_code, paid_qty }) => ({ sku_code, paid_qty })) } })
        .then((p) => !cancelled && setPreview(p))
        .catch(() => !cancelled && setPreview(null))
        .finally(() => !cancelled && setPreviewing(false));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [payloadKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<ApiError | null>(null);

  async function confirm() {
    if (!extraction) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await api<{ order: Order; message: string }>("/orders", {
        method: "POST",
        body: { client_request_id: requestId, ai_extraction_id: extraction.extraction_id, lines: payload },
      });
      try {
        sessionStorage.removeItem("fmcg.ai.draft");
      } catch {
        /* ignore */
      }
      void refresh();
      navigate(`/orders/${res.order.id}`, { replace: true, state: { placed: true, message: res.message } });
    } catch (e) {
      setSubmitError(e as ApiError);
    } finally {
      setSubmitting(false);
    }
  }

  if (!extraction) {
    if (fetched.error) return <ErrorState message={fetched.error.message} onRetry={fetched.reload} />;
    return (
      <div className="flex justify-center py-16 text-muted">
        <Spinner />
      </div>
    );
  }

  if (extraction.status === "confirmed")
    return (
      <Alert tone="green" title="Already placed" action={extraction.order_id && <Link className="font-medium underline" to={`/orders/${extraction.order_id}`}>View the order</Link>}>
        These lines were already confirmed as an order.
      </Alert>
    );

  const issuesBySku = new Map<string, Issue[]>();
  (preview?.issues ?? []).forEach((i) => i.sku_code && issuesBySku.set(i.sku_code, [...(issuesBySku.get(i.sku_code) ?? []), i]));
  const canConfirm = kept.length > 0 && unresolved === 0 && !!preview?.can_submit && !previewing;
  const submitDetails = Array.isArray(submitError?.details) ? (submitError!.details as Issue[]) : [];

  return (
    <div>
      <PageHeader
        title="Check the AI's suggestions"
        subtitle="Nothing is ordered until you confirm. Fix anything marked “Needs you”."
        action={
          <Link to="/ai" className="whitespace-nowrap pt-1 text-sm font-medium text-brand-700">
            Edit message
          </Link>
        }
      />

      <div className="card bg-canvas/60 p-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted">Your message</p>
          <Badge tone={extraction.is_fallback ? "amber" : "green"}>
            {extraction.is_fallback ? "Fallback parser · no AI key" : `AI · ${extraction.model}`}
          </Badge>
        </div>
        <p className="mt-1 whitespace-pre-wrap text-[15px]">{extraction.original_message}</p>
      </div>

      {extraction.warnings.length > 0 && (
        <div className="mt-3 grid gap-2">
          {extraction.warnings.map((w) => (
            <Alert key={w} tone="blue">
              {w}
            </Alert>
          ))}
        </div>
      )}

      {catalogue.error && (
        <div className="mt-3">
          <ErrorState message={catalogue.error.message} onRetry={catalogue.reload} />
        </div>
      )}

      {extraction.lines.length === 0 ? (
        <div className="mt-4">
          <Alert tone="amber" title="No order lines found" action={<Link to="/ai" className="font-medium underline">Edit the message</Link>}>
            We couldn't find any products or quantities in this message.
          </Alert>
        </div>
      ) : (
        <ul className="mt-4 grid gap-3">
          {extraction.lines.map((line) =>
            states[line.line_id] ? (
              <LineCard
                key={line.line_id}
                line={line}
                state={states[line.line_id]}
                set={(patch) => setStates((s) => ({ ...s, [line.line_id]: { ...s[line.line_id], ...patch } }))}
                products={products}
                issues={(states[line.line_id].sku && issuesBySku.get(states[line.line_id].sku!)) || []}
                problemsList={problemMap.get(line.line_id) ?? []}
              />
            ) : null,
          )}
        </ul>
      )}

      <div className="mt-5 grid gap-3">
        {preview && unresolved === 0 && (
          <>
            {preview.lines.length > 0 && (
              <div className="card p-4">
                <p className="text-sm font-medium">Order lines</p>
                {preview.lines.map((l) => (
                  <div key={l.sku_code} className="mt-2 border-t border-line pt-2 first:border-0 first:pt-0">
                    <p className="text-sm">{l.name}</p>
                    <LineBreakdown line={l} />
                  </div>
                ))}
              </div>
            )}
            {preview.warnings.map((w) => (
              <Alert key={w} tone="amber" title="Credit review needed">
                {w}
              </Alert>
            ))}
            <TotalsCard totals={preview.totals} lines={preview.lines} />
            <CreditNote credit={preview.credit} willBeHeld={preview.will_be_held} />
          </>
        )}
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
        <div className="sticky bottom-[calc(4.75rem+env(safe-area-inset-bottom))] rounded-xl bg-white/95 p-1 backdrop-blur">
          <Button size="lg" className="w-full" disabled={!canConfirm} busy={submitting} onClick={confirm}>
            {unresolved > 0
              ? `${unresolved} line${unresolved === 1 ? "" : "s"} need${unresolved === 1 ? "s" : ""} your answer`
              : kept.length === 0
                ? "No lines to order"
                : previewing || !preview
                  ? "Checking prices…"
                  : `Confirm and place order · ${rupees(preview.totals.grand_total)}`}
          </Button>
        </div>
      </div>
    </div>
  );
}

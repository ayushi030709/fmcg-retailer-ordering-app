import type { Credit, PricedLine, Totals } from "../../api";
import { cases, pct, rupees } from "../../format";
import { Row } from "../../ui";

/** Server-calculated totals. The browser never computes prices, schemes or tax. */
export function TotalsCard({ totals, lines }: { totals: Totals; lines: PricedLine[] }) {
  const gstRates = Array.from(new Set(lines.map((l) => Number(l.gst_rate))));
  const inclusive = lines.some((l) => l.gst_inclusive);
  return (
    <div className="card p-4">
      <Row label={`Subtotal · ${cases(totals.paid_cases)}`} value={rupees(totals.subtotal)} />
      {Number(totals.discount_total) > 0 && (
        <Row label="Scheme discount" value={<span className="text-brand-700">− {rupees(totals.discount_total)}</span>} />
      )}
      {totals.free_cases > 0 && <Row label="Free cases (scheme)" value={<span className="text-brand-700">{cases(totals.free_cases)}</span>} />}
      <Row label="Taxable value" value={rupees(totals.taxable_total)} muted />
      <Row
        label={`GST${gstRates.length === 1 ? ` @ ${pct(gstRates[0])}` : ""}${inclusive ? " (included)" : ""}`}
        value={rupees(totals.tax_total)}
        muted
      />
      <div className="mt-1 border-t border-line pt-2">
        <Row label="Total payable" value={rupees(totals.grand_total)} strong />
      </div>
      <p className="mt-2 text-xs text-muted">
        Calculated by the server. GST rate is a demo assumption; dealer prices exclude GST.
      </p>
    </div>
  );
}

export function LineBreakdown({ line }: { line: PricedLine }) {
  return (
    <div className="tabular mt-2 space-y-0.5 text-xs text-muted">
      <p>
        {cases(line.paid_qty)} × {rupees(line.unit_price)} = {rupees(line.gross_amount)}
        {Number(line.discount_amount) > 0 && <> · {pct(line.discount_percent)} off − {rupees(line.discount_amount)}</>}
      </p>
      {line.free_qty > 0 && (
        <p className="text-brand-700">
          + {cases(line.free_qty)} free · {line.fulfil_qty} cases delivered
        </p>
      )}
      <p>
        GST {pct(line.gst_rate)} {rupees(line.tax_amount)} · line total <span className="font-medium text-ink">{rupees(line.line_total)}</span>
      </p>
      {line.hints.map((h) => (
        <p key={h} className="text-sky-800">
          Tip: {h}
        </p>
      ))}
    </div>
  );
}

export function CreditNote({ credit, willBeHeld }: { credit: Credit; willBeHeld: boolean }) {
  return (
    <p className={willBeHeld ? "text-sm text-amber-800" : "text-xs text-muted"}>
      Available credit {rupees(credit.available_credit)} (limit {rupees(credit.credit_limit)}, outstanding{" "}
      {rupees(credit.outstanding_balance)}, open orders {rupees(credit.open_orders_total)}).
    </p>
  );
}

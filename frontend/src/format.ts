import type { OrderStatus } from "./api";

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2 });

/** Display-only formatting of a decimal string from the API. */
export function rupees(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return inr.format(Number(value));
}

export function pct(value: string | number): string {
  return `${Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 })}%`;
}

const dateFmt = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });

export const when = (iso: string | null | undefined) => (iso ? dateFmt.format(new Date(iso)) : "—");
export const day = (iso: string | null | undefined) => (iso ? dayFmt.format(new Date(iso)) : "—");

export const STATUS_LABEL: Record<OrderStatus, string> = {
  pending_review: "Pending review",
  on_hold: "On hold",
  approved: "Approved",
  rejected: "Rejected",
  exported: "Sent to Tally",
};

export const STATUS_HELP: Record<OrderStatus, string> = {
  pending_review: "The order desk will check stock and credit, then approve it.",
  on_hold: "The order desk is reviewing this order before it can proceed.",
  approved: "Approved and queued for billing.",
  rejected: "This order was not accepted. Reserved stock has been released.",
  exported: "Approved and exported to the billing system.",
};

export function cases(n: number): string {
  return `${n} case${n === 1 ? "" : "s"}`;
}

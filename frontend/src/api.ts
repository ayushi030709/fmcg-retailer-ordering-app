// Typed API client. Money arrives as decimal strings from the backend and is
// only converted to Number for display formatting — never for calculations.

export const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "/api";
const TOKEN_KEY = "fmcg.token";

export type Money = string;
export type Role = "retailer" | "order_desk";
export type OrderStatus = "pending_review" | "on_hold" | "approved" | "rejected" | "exported";

export interface Credit {
  credit_limit: Money;
  outstanding_balance: Money;
  open_orders_total: Money;
  available_credit: Money;
  order_total: Money;
  within_limit: boolean;
}

export interface RetailerProfile {
  id: number;
  code: string;
  shop_name: string;
  owner_name: string;
  city: string;
  credit_limit: Money;
  outstanding_balance: Money;
  is_demo_data: boolean;
}

export interface Me {
  id: number;
  name: string;
  role: Role;
  phone: string | null;
  email: string | null;
  retailer: RetailerProfile | null;
  credit: Credit | null;
}

export interface Scheme {
  type: "buy_x_get_y_free" | "percent_discount";
  description: string;
  threshold_qty: number;
  free_qty: number | null;
  discount_percent: Money | null;
}

export type StockStatus = "in_stock" | "low_stock" | "out_of_stock";

export interface CatalogueItem {
  product_id: number;
  sku_code: string;
  name: string;
  description: string;
  pack_size: string;
  units_per_case: number;
  sell_unit: string;
  dealer_price: Money;
  gst_rate: Money;
  gst_inclusive: boolean;
  image_url: string | null;
  available_cases: number;
  stock_status: StockStatus;
  scheme: Scheme | null;
  data_source: string;
}

export interface OrderLineIn {
  sku_code: string;
  paid_qty: number;
  original_phrase?: string | null;
  unit_confirmed?: boolean;
  remember_product_alias?: boolean;
  unit_alias?: string | null;
  remember_unit_alias?: boolean;
}

export interface PricedLine {
  sku_code: string;
  product_id: number;
  name: string;
  pack_size: string;
  paid_qty: number;
  free_qty: number;
  fulfil_qty: number;
  unit_price: Money;
  gross_amount: Money;
  discount_percent: Money;
  discount_amount: Money;
  taxable_amount: Money;
  gst_rate: Money;
  gst_inclusive: boolean;
  tax_amount: Money;
  line_total: Money;
  scheme_applied: string | null;
  hints: string[];
  available_cases: number;
  stock_status: StockStatus;
  original_phrase: string | null;
}

export interface Issue {
  code: string;
  message: string;
  sku_code: string | null;
  blocking: boolean;
}

export interface Totals {
  subtotal: Money;
  discount_total: Money;
  taxable_total: Money;
  tax_total: Money;
  grand_total: Money;
  paid_cases: number;
  free_cases: number;
}

export interface Preview {
  lines: PricedLine[];
  issues: Issue[];
  totals: Totals;
  credit: Credit;
  can_submit: boolean;
  will_be_held: boolean;
  warnings: string[];
}

export interface OrderItem {
  id: number;
  product_id: number;
  sku_code: string;
  product_name: string;
  paid_qty: number;
  free_qty: number;
  unit_price: Money;
  gross_amount: Money;
  discount_percent: Money;
  discount_amount: Money;
  taxable_amount: Money;
  gst_rate: Money;
  gst_inclusive: boolean;
  tax_amount: Money;
  line_total: Money;
  scheme_applied: string | null;
  original_phrase: string | null;
}

export interface Order {
  id: number;
  order_number: string;
  status: OrderStatus;
  source: "manual" | "ai";
  subtotal: Money;
  discount_total: Money;
  taxable_total: Money;
  tax_total: Money;
  grand_total: Money;
  hold_reason: string | null;
  status_note: string | null;
  created_at: string;
  approved_at: string | null;
  exported_at: string | null;
  version: number;
  items: OrderItem[];
}

export interface OrderSummary {
  id: number;
  order_number: string;
  status: OrderStatus;
  source: "manual" | "ai";
  grand_total: Money;
  hold_reason: string | null;
  created_at: string;
  line_count: number;
  retailer: { id: number; code: string; shop_name: string; city: string };
}

export interface Clarification {
  type: "unit" | "sku" | "quantity";
  question: string;
  unit_text?: string | null;
}

export interface Alternative {
  sku_code: string;
  name: string;
  pack_size: string;
  score: number;
  stock_status: StockStatus;
  available_cases: number;
}

export type Band = "high" | "medium" | "low" | "none";

export interface ExtractedLine {
  line_id: number;
  original_text: string;
  product_phrase: string;
  ai_description: string | null;
  ai_reasoning: string | null;
  ai_suggested_sku: string | null;
  quantity: number | null;
  unit: "case" | "piece" | "unknown";
  unit_text: string | null;
  unit_confirmed: boolean;
  unit_source: string;
  candidate: CatalogueItem | null;
  confidence: number;
  confidence_band: Band;
  evidence: string[];
  alternatives: Alternative[];
  needs_sku_choice: boolean;
  clarifications: Clarification[];
  out_of_stock: boolean;
  status: "ready" | "needs_attention" | "no_match" | "out_of_stock";
}

export interface Extraction {
  extraction_id: number;
  provider: string;
  model: string | null;
  is_fallback: boolean;
  message_language: string | null;
  original_message: string;
  lines: ExtractedLine[];
  warnings: string[];
  status: string;
  order_id: number | null;
}

export interface AuditEvent {
  id: number;
  action: string;
  actor: string | null;
  actor_role: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  note: string | null;
  created_at: string;
}

export interface DeskOrderDetail {
  order: Order;
  retailer: RetailerProfile;
  credit: Credit;
  audit: AuditEvent[];
  ai_message: { message: string; provider: string; model: string | null } | null;
  stock: Record<string, number>;
  allowed_actions: string[];
}

export interface ExportPreview {
  orders: { id: number; order_number: string; shop_name: string; grand_total: Money; line_count: number; approved_at: string | null }[];
  order_count: number;
  row_count: number;
  total_amount: Money;
  columns: string[];
  csv_preview: string;
}

export interface ExportBatch {
  id: number;
  batch_number: string;
  created_at: string;
  created_by: string | null;
  order_count: number;
  row_count: number;
  total_amount: Money;
  order_numbers: string[];
  file_name: string;
}

export interface Alias {
  id: number;
  kind: "sku" | "unit";
  retailer_id: number;
  shop_name: string;
  alias_text: string;
  target: string;
  source: string;
  confirmed_by: string | null;
  created_at: string;
  is_active: boolean;
}

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export const tokenStore = {
  get: () => {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (t: string) => {
    try {
      localStorage.setItem(TOKEN_KEY, t);
    } catch {
      /* storage unavailable: session lasts for this tab only */
    }
  },
  clear: () => {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
  },
};

type Options = { method?: string; body?: unknown; timeoutMs?: number; raw?: boolean };

async function send(path: string, { method = "GET", body, timeoutMs = 20000 }: Options): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (e) {
    const timedOut = (e as Error).name === "AbortError";
    throw new ApiError(
      0,
      timedOut ? "timeout" : "network",
      timedOut
        ? "The server is taking too long to respond. Check your connection and try again."
        : "Could not reach the server. Check your connection and try again.",
    );
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let payload: { error?: { code?: string; message?: string; details?: unknown } } = {};
    try {
      payload = await res.json();
    } catch {
      /* non-JSON error */
    }
    if (res.status === 401 && token) {
      tokenStore.clear();
      window.dispatchEvent(new Event("auth:expired"));
    }
    throw new ApiError(
      res.status,
      payload.error?.code ?? "http_error",
      payload.error?.message ??
        (path.startsWith("/") && res.status >= 500
          ? `The API server isn't responding correctly (HTTP ${res.status}). Check that the backend is running on port 8000.`
          : `Request failed (HTTP ${res.status}).`),
      payload.error?.details,
    );
  }
  return res;
}

export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const res = await send(path, opts);
  return (await res.json()) as T;
}

export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const res = await send(path, { timeoutMs: 30000 });
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID().replace(/-/g, "");
  return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
}

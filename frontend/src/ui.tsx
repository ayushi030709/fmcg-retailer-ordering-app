import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Band, OrderStatus, StockStatus } from "./api";
import { STATUS_LABEL } from "./format";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-700 text-white hover:bg-brand-800 disabled:bg-brand-700/40",
  secondary: "bg-white text-ink border border-line hover:bg-canvas disabled:text-muted/60",
  ghost: "text-brand-700 hover:bg-brand-50 disabled:text-muted/60",
  danger: "bg-white text-red-700 border border-red-200 hover:bg-red-50 disabled:text-red-300",
};

export function Button({
  variant = "primary",
  size = "md",
  busy,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg"; busy?: boolean }) {
  return (
    <button
      {...rest}
      disabled={disabled || busy}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed",
        size === "sm" && "min-h-9 px-3 text-sm",
        size === "md" && "min-h-11 px-4 text-[15px]",
        size === "lg" && "min-h-12 px-5 text-base",
        VARIANTS[variant],
        className,
      )}
    >
      {busy && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  );
}

export function Spinner({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg className={cx("animate-spin", className)} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

type Tone = "neutral" | "green" | "amber" | "red" | "blue";
const TONES: Record<Tone, string> = {
  neutral: "bg-canvas text-muted ring-line",
  green: "bg-brand-50 text-brand-800 ring-brand-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  blue: "bg-sky-50 text-sky-800 ring-sky-200",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function StockBadge({ status, cases }: { status: StockStatus; cases?: number }) {
  if (status === "out_of_stock") return <Badge tone="red">Out of stock</Badge>;
  if (status === "low_stock") return <Badge tone="amber">Low stock{cases !== undefined ? ` · ${cases} cases` : ""}</Badge>;
  return <Badge tone="green">In stock{cases !== undefined ? ` · ${cases} cases` : ""}</Badge>;
}

const STATUS_TONE: Record<OrderStatus, Tone> = {
  pending_review: "blue",
  on_hold: "amber",
  approved: "green",
  rejected: "red",
  exported: "neutral",
};

export function StatusBadge({ status }: { status: OrderStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Badge>;
}

export function ConfidenceBadge({ band, score }: { band: Band; score: number }) {
  const label = { high: "High match", medium: "Check match", low: "Unsure", none: "No match" }[band];
  const tone: Tone = { high: "green", medium: "amber", low: "red", none: "red" }[band] as Tone;
  return (
    <Badge tone={tone} className="tabular">
      {label}
      {band !== "none" && <span className="opacity-70">· {Math.round(score * 100)}%</span>}
    </Badge>
  );
}

export function Alert({
  tone = "amber",
  title,
  children,
  action,
}: {
  tone?: "amber" | "red" | "blue" | "green";
  title?: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const styles = {
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    red: "border-red-200 bg-red-50 text-red-900",
    blue: "border-sky-200 bg-sky-50 text-sky-900",
    green: "border-brand-200 bg-brand-50 text-brand-800",
  }[tone];
  return (
    <div className={cx("rounded-lg border px-3.5 py-3 text-sm", styles)} role={tone === "red" ? "alert" : "status"}>
      {title && <p className="font-semibold">{title}</p>}
      {children && <div className={cx(title && "mt-0.5", "leading-relaxed")}>{children}</div>}
      {action && <div className="mt-2.5">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Alert
      tone="red"
      title="Something went wrong"
      action={onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    >
      {message}
    </Alert>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="card px-6 py-10 text-center">
      <p className="font-semibold">{title}</p>
      {children && <p className="mx-auto mt-1 max-w-sm text-sm text-muted">{children}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function ProductThumb({ name }: { name: string }) {
  // Lightweight placeholder instead of product photos: nothing to download on slow 3G.
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
  return (
    <div
      aria-hidden="true"
      className="flex h-14 w-14 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-sm font-semibold text-brand-700 ring-1 ring-inset ring-brand-100"
    >
      {initials}
    </div>
  );
}

export function QtyStepper({
  value,
  onChange,
  max = 5000,
  label,
  disabled,
}: {
  value: number;
  onChange: (n: number) => void;
  max?: number;
  label: string;
  disabled?: boolean;
}) {
  const btn =
    "flex h-11 w-11 items-center justify-center text-lg font-semibold text-brand-700 hover:bg-brand-50 disabled:text-muted/40 disabled:hover:bg-transparent";
  return (
    <div className="inline-flex items-center overflow-hidden rounded-lg border border-line bg-white">
      <button type="button" className={btn} aria-label={`Decrease ${label}`} disabled={disabled || value <= 0} onClick={() => onChange(value - 1)}>
        −
      </button>
      <input
        aria-label={`${label} quantity in cases`}
        inputMode="numeric"
        className="tabular h-11 w-14 border-x border-line text-center text-[15px] focus:outline-none"
        value={value}
        disabled={disabled}
        onChange={(e) => {
          const n = parseInt(e.target.value.replace(/\D/g, "") || "0", 10);
          onChange(Math.min(n, max));
        }}
      />
      <button type="button" className={btn} aria-label={`Increase ${label}`} disabled={disabled || value >= max} onClick={() => onChange(value + 1)}>
        +
      </button>
    </div>
  );
}

export function Row({ label, value, strong, muted }: { label: ReactNode; value: ReactNode; strong?: boolean; muted?: boolean }) {
  return (
    <div className={cx("flex items-baseline justify-between gap-4 py-1 text-sm", strong && "text-base font-semibold", muted && "text-muted")}>
      <span>{label}</span>
      <span className="tabular text-right">{value}</span>
    </div>
  );
}

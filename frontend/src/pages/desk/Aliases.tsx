import { useState } from "react";
import { api, ApiError, type Alias } from "../../api";
import { when } from "../../format";
import { useApi } from "../../state";
import { Alert, Badge, Button, Empty, ErrorState, PageHeader, Spinner } from "../../ui";

const SOURCE: Record<string, string> = {
  retailer_confirmed: "Confirmed by retailer",
  desk_correction: "Desk correction",
  seed_demo: "Demo seed",
};

export default function Aliases() {
  const [showInactive, setShowInactive] = useState(false);
  const { data, error, loading, reload } = useApi<Alias[]>(`/desk/aliases?include_inactive=${showInactive}`);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function deactivate(a: Alias) {
    setBusyId(`${a.kind}-${a.id}`);
    setActionError(null);
    try {
      await api(`/desk/aliases/${a.kind}/${a.id}`, { method: "PATCH", body: { is_active: false } });
      reload();
    } catch (e) {
      setActionError((e as ApiError).message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <PageHeader
        title="Retailer phrases"
        subtitle="Words each retailer uses for products and units, learned only from confirmed corrections. Deactivate any that are wrong."
        action={loading && <Spinner className="h-5 w-5 text-muted" />}
      />
      <label className="mb-3 flex items-center gap-2 text-sm text-muted">
        <input type="checkbox" className="h-4 w-4 accent-brand-700" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
        Show deactivated
      </label>
      {actionError && (
        <div className="mb-3">
          <Alert tone="red">{actionError}</Alert>
        </div>
      )}
      {error ? (
        <ErrorState message={error.message} onRetry={reload} />
      ) : !data ? (
        <div className="skeleton h-24" />
      ) : data.length === 0 ? (
        <Empty title="No saved phrases yet">They appear when a retailer confirms an AI suggestion or the desk corrects a line.</Empty>
      ) : (
        <ul className="card divide-y divide-line">
          {data.map((a) => (
            <li key={`${a.kind}-${a.id}`} className="flex flex-wrap items-center justify-between gap-3 p-4">
              <div className="min-w-0">
                <p>
                  <span className="font-medium">“{a.alias_text}”</span> <span className="text-muted">→</span> {a.target}
                </p>
                <p className="mt-0.5 text-xs text-muted">
                  {a.shop_name} · {SOURCE[a.source] ?? a.source}
                  {a.confirmed_by && ` by ${a.confirmed_by}`} · {when(a.created_at)}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={a.kind === "unit" ? "blue" : "neutral"}>{a.kind === "unit" ? "Unit" : "Product"}</Badge>
                {a.is_active ? (
                  <Button size="sm" variant="danger" busy={busyId === `${a.kind}-${a.id}`} onClick={() => deactivate(a)}>
                    Deactivate
                  </Button>
                ) : (
                  <Badge>Inactive</Badge>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

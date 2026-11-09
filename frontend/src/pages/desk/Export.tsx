import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, downloadFile, type ExportBatch, type ExportPreview } from "../../api";
import { rupees, when } from "../../format";
import { useApi } from "../../state";
import { Alert, Button, Empty, ErrorState, PageHeader, Spinner } from "../../ui";

export default function Export() {
  const preview = useApi<ExportPreview>("/desk/exports/preview");
  const history = useApi<ExportBatch[]>("/desk/exports");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState<ExportBatch | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  useEffect(() => {
    if (preview.data) setSelected(new Set(preview.data.orders.map((o) => o.id)));
  }, [preview.data]);

  async function download(b: ExportBatch) {
    setDownloadError(null);
    try {
      await downloadFile(`/desk/exports/${b.id}/download`, b.file_name);
    } catch (e) {
      setDownloadError((e as ApiError).message);
    }
  }

  async function runExport() {
    if (!preview.data || selected.size === 0) return;
    setBusy(true);
    setError(null);
    try {
      const all = selected.size === preview.data.orders.length;
      const batch = await api<ExportBatch>("/desk/exports", { method: "POST", body: all ? {} : { order_ids: [...selected] } });
      setDone(batch);
      await download(batch);
      preview.reload();
      history.reload();
    } catch (e) {
      setError(e as ApiError);
      preview.reload();
    } finally {
      setBusy(false);
    }
  }

  const p = preview.data;
  const selectedTotal = p?.orders.filter((o) => selected.has(o.id)).reduce((sum, o) => sum + Number(o.grand_total), 0) ?? 0;

  return (
    <div>
      <PageHeader
        title="Tally export"
        subtitle="Export approved orders as CSV. Each order can be exported once; held or unapproved orders are never included."
      />

      {done && (
        <div className="mb-4">
          <Alert tone="green" title={`Exported ${done.batch_number}`}>
            {done.order_count} orders · {done.row_count} rows · {rupees(done.total_amount)}. The file downloaded as {done.file_name}.
          </Alert>
        </div>
      )}
      {downloadError && (
        <div className="mb-4">
          <Alert tone="red">Download failed: {downloadError} You can download it again from the history below.</Alert>
        </div>
      )}

      {preview.error ? (
        <ErrorState message={preview.error.message} onRetry={preview.reload} />
      ) : !p ? (
        <div className="flex justify-center py-10 text-muted">
          <Spinner />
        </div>
      ) : p.order_count === 0 ? (
        <Empty title="Nothing waiting for export" action={<Link to="/desk"><Button variant="secondary">Go to order queue</Button></Link>}>
          Approve orders in the queue and they'll appear here.
        </Empty>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="w-10 px-4 py-2.5">
                    <input
                      type="checkbox"
                      aria-label="Select all"
                      className="h-4 w-4 accent-brand-700"
                      checked={selected.size === p.orders.length}
                      onChange={(e) => setSelected(e.target.checked ? new Set(p.orders.map((o) => o.id)) : new Set())}
                    />
                  </th>
                  <th className="px-2 py-2.5 font-medium">Order</th>
                  <th className="px-2 py-2.5 font-medium">Retailer</th>
                  <th className="px-2 py-2.5 font-medium">Approved</th>
                  <th className="px-4 py-2.5 text-right font-medium">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {p.orders.map((o) => (
                  <tr key={o.id}>
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        aria-label={`Include ${o.order_number}`}
                        className="h-4 w-4 accent-brand-700"
                        checked={selected.has(o.id)}
                        onChange={(e) => {
                          const next = new Set(selected);
                          if (e.target.checked) next.add(o.id);
                          else next.delete(o.id);
                          setSelected(next);
                        }}
                      />
                    </td>
                    <td className="px-2 py-3">
                      <Link className="tabular font-medium text-brand-700 hover:underline" to={`/desk/orders/${o.id}`}>
                        {o.order_number}
                      </Link>
                      <p className="text-xs text-muted">{o.line_count} line{o.line_count === 1 ? "" : "s"}</p>
                    </td>
                    <td className="px-2 py-3">{o.shop_name}</td>
                    <td className="px-2 py-3 text-muted">{when(o.approved_at)}</td>
                    <td className="tabular px-4 py-3 text-right">{rupees(o.grand_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card content-start p-4">
            <p className="text-sm text-muted">Selected</p>
            <p className="tabular text-2xl font-semibold">{rupees(selectedTotal)}</p>
            <p className="text-sm text-muted">
              {selected.size} of {p.order_count} orders
            </p>
            {error && (
              <div className="mt-3">
                <Alert tone="red">{error.message}</Alert>
              </div>
            )}
            <Button className="mt-4 w-full" onClick={runExport} busy={busy} disabled={selected.size === 0}>
              Export {selected.size} order{selected.size === 1 ? "" : "s"} to CSV
            </Button>
            <p className="mt-2 text-xs text-muted">
              Exported orders move to “Sent to Tally” and can't be exported again. Column mapping must be confirmed against
              the client's Tally setup.
            </p>
          </div>
          <details className="card p-4 lg:col-span-2">
            <summary className="cursor-pointer text-sm font-medium">CSV preview ({p.row_count} rows, first 20 shown)</summary>
            <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-canvas p-3 text-xs leading-relaxed">{p.csv_preview}</pre>
          </details>
        </div>
      )}

      <h2 className="mt-8 text-base font-semibold">Export history</h2>
      <div className="mt-2">
        {history.error ? (
          <ErrorState message={history.error.message} onRetry={history.reload} />
        ) : !history.data ? (
          <div className="skeleton h-16" />
        ) : history.data.length === 0 ? (
          <p className="text-sm text-muted">No exports yet.</p>
        ) : (
          <ul className="card divide-y divide-line">
            {history.data.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
                <div className="min-w-0">
                  <p className="tabular font-medium">{b.batch_number}</p>
                  <p className="text-sm text-muted">
                    {when(b.created_at)} · {b.created_by ?? "—"} · {b.order_count} orders · {b.row_count} rows · {rupees(b.total_amount)}
                  </p>
                  <p className="tabular truncate text-xs text-muted">{b.order_numbers.join(", ")}</p>
                </div>
                <Button size="sm" variant="secondary" onClick={() => download(b)}>
                  Download again
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

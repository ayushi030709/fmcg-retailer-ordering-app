import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, type Extraction } from "../../api";
import { useApi } from "../../state";
import { Alert, Badge, Button, PageHeader, Spinner } from "../../ui";

const DRAFT_KEY = "fmcg.ai.draft";
const MAX = 1000;

interface AiStatus {
  provider: string;
  model: string | null;
  configured: boolean;
  sample_message: string;
}

function readDraft(): string {
  try {
    return sessionStorage.getItem(DRAFT_KEY) ?? "";
  } catch {
    return "";
  }
}

export default function AiCapture() {
  const navigate = useNavigate();
  const { data: status } = useApi<AiStatus>("/ai/status");
  const [message, setMessage] = useState(readDraft);
  const [hint, setHint] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    try {
      sessionStorage.setItem(DRAFT_KEY, message);
    } catch {
      /* draft only kept in memory */
    }
  }, [message]);

  const empty = message.trim().length === 0;

  async function extract() {
    setTouched(true);
    if (empty || message.length > MAX) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api<Extraction>("/ai/extract-text", {
        method: "POST",
        body: { message, language_hint: hint || null },
        timeoutMs: 40000,
      });
      navigate(`/ai/review/${res.extraction_id}`, { state: res });
    } catch (e) {
      setError(e as ApiError); // the typed message is kept for retry
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="AI order capture"
        subtitle="Paste a WhatsApp-style order in Hindi, Hinglish or English. You'll check every line before anything is ordered."
      />

      <div className="card p-4">
        <div className="flex items-center justify-between gap-2">
          <label htmlFor="msg" className="text-sm font-medium">
            Order message
          </label>
          {status && (
            <Badge tone={status.configured ? "green" : "amber"}>
              {status.configured ? `AI: ${status.provider} · ${status.model}` : "Fallback parser (no AI key configured)"}
            </Badge>
          )}
        </div>
        <textarea
          id="msg"
          rows={6}
          maxLength={MAX + 200}
          className="field mt-2 resize-y leading-relaxed"
          placeholder="e.g. bhaiya 5 peti biscuit, 2 peti washing powder 1 kilo…"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          disabled={busy}
          aria-invalid={touched && (empty || message.length > MAX)}
        />
        <div className="mt-1.5 flex items-center justify-between text-xs">
          <span className="text-red-700">
            {touched && empty && "Type or paste an order message first."}
            {message.length > MAX && `Please shorten the message to ${MAX} characters.`}
          </span>
          <span className={message.length > MAX ? "text-red-700" : "text-muted"}>
            {message.length}/{MAX}
          </span>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {status && (
            <Button variant="secondary" size="sm" onClick={() => setMessage(status.sample_message)} disabled={busy}>
              Use sample message
            </Button>
          )}
          <label className="flex items-center gap-2 text-sm text-muted">
            Language
            <select className="field w-auto py-1.5 text-sm" value={hint} onChange={(e) => setHint(e.target.value)} disabled={busy}>
              <option value="">Auto-detect</option>
              <option value="hi-Latn">Hinglish</option>
              <option value="hi">Hindi</option>
              <option value="en">English</option>
            </select>
          </label>
        </div>

        <Button size="lg" className="mt-4 w-full" onClick={extract} busy={busy}>
          {busy ? "Reading your message…" : "Extract order lines"}
        </Button>
        {busy && (
          <p className="mt-2 flex items-center justify-center gap-2 text-xs text-muted">
            <Spinner className="h-3.5 w-3.5" /> This can take a few seconds on a slow connection.
          </p>
        )}
      </div>

      {error && (
        <div className="mt-4">
          <Alert
            tone="red"
            title="Couldn't read the message"
            action={
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={extract}>
                  Try again
                </Button>
                <Link to="/">
                  <Button size="sm" variant="secondary">
                    Order from catalogue instead
                  </Button>
                </Link>
              </div>
            }
          >
            {error.message}
          </Alert>
        </div>
      )}

      <div className="mt-4 rounded-xl bg-brand-50 p-4 text-sm text-brand-800">
        <p className="font-medium">How this works</p>
        <ol className="mt-1.5 list-decimal space-y-1 pl-5">
          <li>AI suggests products and quantities, keeping your original words for each line.</li>
          <li>If a unit like “peti” or a product is unclear, you'll be asked — nothing is guessed.</li>
          <li>Prices, schemes, GST and stock are calculated by the server, not the AI.</li>
          <li>No order is placed until you press Confirm.</li>
        </ol>
      </div>
    </div>
  );
}

import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { api, ApiError, type Me } from "../api";
import { useAuth } from "../state";
import { Alert, Button } from "../ui";

interface OtpRequestResponse {
  challenge_id: string;
  expires_in: number;
  message: string;
  demo_mode: boolean;
  demo_hint: string | null;
}

const DEMO_ACCOUNTS = [
  { label: "Retailer A", id: "9000000001", note: "No saved vocabulary yet" },
  { label: "Retailer B", id: "9000000002", note: "Low credit · knows “peti”" },
  { label: "Order desk", id: "9000000009", note: "Review, approve, export" },
];

export default function SignIn() {
  const { me, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [identifier, setIdentifier] = useState("");
  const [challenge, setChallenge] = useState<OtpRequestResponse | null>(null);
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (me) return <Navigate to={me.role === "retailer" ? "/" : "/desk"} replace />;

  async function requestOtp(e?: FormEvent, value = identifier) {
    e?.preventDefault();
    if (value.trim().length < 3) return setError("Enter your registered mobile number or email.");
    setBusy(true);
    setError(null);
    try {
      setChallenge(await api<OtpRequestResponse>("/auth/request-otp", { method: "POST", body: { identifier: value } }));
      setOtp("");
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    if (!challenge) return;
    if (!/^\d{4,8}$/.test(otp)) return setError("Enter the code using digits only.");
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ access_token: string; user: Me }>("/auth/verify-otp", {
        method: "POST",
        body: { challenge_id: challenge.challenge_id, otp },
      });
      signIn(res.access_token, res.user);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/signin" ? from : res.user.role === "retailer" ? "/" : "/desk", { replace: true });
    } catch (err) {
      const apiErr = err as ApiError;
      setError(apiErr.message);
      if (apiErr.code === "otp_expired" || apiErr.code === "otp_locked") setChallenge(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <img src="/icon.svg" alt="" className="mx-auto h-12 w-12" />
          <h1 className="mt-3 text-2xl font-semibold tracking-tight">Sign in to order</h1>
          <p className="mt-1 text-sm text-muted">Use your registered mobile number. We'll send a one-time code.</p>
        </div>

        <div className="card p-5">
          {!challenge ? (
            <form onSubmit={requestOtp} noValidate>
              <label htmlFor="identifier" className="text-sm font-medium">
                Mobile number or email
              </label>
              <input
                id="identifier"
                className="field mt-1.5"
                inputMode="tel"
                autoComplete="username"
                placeholder="10-digit mobile number"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
              />
              {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
              <Button type="submit" className="mt-4 w-full" busy={busy}>
                Send code
              </Button>
            </form>
          ) : (
            <form onSubmit={verify} noValidate>
              <p className="text-sm text-muted">
                Code sent to <span className="font-medium text-ink">{identifier}</span>.{" "}
                <button type="button" className="font-medium text-brand-700" onClick={() => setChallenge(null)}>
                  Change
                </button>
              </p>
              {challenge.demo_hint && (
                <div className="mt-3">
                  <Alert tone="blue">{challenge.demo_hint}</Alert>
                </div>
              )}
              <label htmlFor="otp" className="mt-4 block text-sm font-medium">
                One-time code
              </label>
              <input
                id="otp"
                className="field tabular mt-1.5 text-center text-lg tracking-[0.4em]"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={8}
                autoFocus
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
              />
              {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
              <Button type="submit" className="mt-4 w-full" busy={busy}>
                Verify and sign in
              </Button>
              <button type="button" className="mt-3 w-full text-sm text-muted hover:text-ink" onClick={() => requestOtp()}>
                Send a new code
              </button>
            </form>
          )}
        </div>

        <div className="mt-6">
          <p className="text-xs font-medium uppercase tracking-wide text-muted">Reviewer demo accounts (synthetic)</p>
          <div className="mt-2 grid gap-2">
            {DEMO_ACCOUNTS.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => {
                  setIdentifier(a.id);
                  void requestOtp(undefined, a.id);
                }}
                className="card flex items-center justify-between px-3.5 py-2.5 text-left hover:border-brand-200 hover:bg-brand-50/40"
              >
                <span>
                  <span className="block text-sm font-medium">{a.label}</span>
                  <span className="block text-xs text-muted">{a.note}</span>
                </span>
                <span className="tabular text-sm text-muted">{a.id}</span>
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">Demo OTP is shown after you request a code. No SMS is sent.</p>
        </div>
      </div>
    </div>
  );
}

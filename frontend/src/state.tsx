import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, tokenStore, type Me } from "./api";

// ---------------- Auth ----------------
interface AuthState {
  me: Me | null;
  loading: boolean;
  signIn: (token: string, me: Me) => void;
  signOut: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState<boolean>(!!tokenStore.get());

  const refresh = useCallback(async () => {
    if (!tokenStore.get()) {
      setMe(null);
      setLoading(false);
      return;
    }
    try {
      setMe(await api<Me>("/me"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const onExpired = () => setMe(null);
    window.addEventListener("auth:expired", onExpired);
    return () => window.removeEventListener("auth:expired", onExpired);
  }, [refresh]);

  const value = useMemo<AuthState>(
    () => ({
      me,
      loading,
      refresh,
      signIn: (token, user) => {
        tokenStore.set(token);
        setMe(user);
      },
      signOut: () => {
        tokenStore.clear();
        setMe(null);
      },
    }),
    [me, loading, refresh],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

// ---------------- Cart (client-side; the server re-prices everything) ----------------
type CartMap = Record<string, number>;

interface CartState {
  items: CartMap;
  count: number;
  setQty: (sku: string, qty: number) => void;
  remove: (sku: string) => void;
  clear: () => void;
}

const CartContext = createContext<CartState | null>(null);

export function CartProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  const key = me?.retailer ? `fmcg.cart.${me.retailer.id}` : null;
  const [items, setItems] = useState<CartMap>({});

  useEffect(() => {
    if (!key) return setItems({});
    try {
      const raw = localStorage.getItem(key);
      setItems(raw ? (JSON.parse(raw) as CartMap) : {});
    } catch {
      setItems({});
    }
  }, [key]);

  const persist = useCallback(
    (next: CartMap) => {
      setItems(next);
      if (key) {
        try {
          localStorage.setItem(key, JSON.stringify(next));
        } catch {
          /* storage unavailable — cart lives in memory only */
        }
      }
    },
    [key],
  );

  const value = useMemo<CartState>(
    () => ({
      items,
      count: Object.keys(items).length,
      setQty: (sku, qty) => {
        const n = Math.max(0, Math.min(5000, Math.floor(qty)));
        const next = { ...items };
        if (n === 0) delete next[sku];
        else next[sku] = n;
        persist(next);
      },
      remove: (sku) => {
        const next = { ...items };
        delete next[sku];
        persist(next);
      },
      clear: () => persist({}),
    }),
    [items, persist],
  );
  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart(): CartState {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error("useCart outside CartProvider");
  return ctx;
}

// ---------------- Data loading hook ----------------
export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!path) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api<T>(path)
      .then((d) => !cancelled && setData(d))
      .catch((e: ApiError) => !cancelled && setError(e))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, ...deps]);

  return { data, setData, error, loading, reload: () => setTick((t) => t + 1) };
}

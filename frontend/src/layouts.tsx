import type { ReactNode } from "react";
import { Navigate, NavLink, Outlet, useLocation } from "react-router-dom";
import type { Role } from "./api";
import { rupees } from "./format";
import { useAuth, useCart } from "./state";
import { cx, Spinner } from "./ui";

export function RequireRole({ role, children }: { role: Role; children: ReactNode }) {
  const { me, loading } = useAuth();
  const location = useLocation();
  if (loading)
    return (
      <div className="flex min-h-dvh items-center justify-center text-muted">
        <Spinner />
      </div>
    );
  if (!me) return <Navigate to="/signin" replace state={{ from: location.pathname }} />;
  if (me.role !== role) return <Navigate to={me.role === "retailer" ? "/" : "/desk"} replace />;
  return <>{children}</>;
}

function SignOut() {
  const { signOut } = useAuth();
  return (
    <button onClick={signOut} className="rounded-md px-2 py-1 text-sm text-muted hover:bg-canvas hover:text-ink">
      Sign out
    </button>
  );
}

const icons = {
  shop: "M4 7h16l-1.2 11.2A2 2 0 0 1 16.8 20H7.2a2 2 0 0 1-2-1.8L4 7Zm4 0V6a4 4 0 0 1 8 0v1",
  spark: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6",
  cart: "M3 4h2l2.4 11.2a1 1 0 0 0 1 .8h9.2a1 1 0 0 0 1-.8L20 8H6.2M9 20.5h.01M17 20.5h.01",
  list: "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01",
};

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

export function RetailerLayout() {
  const { me } = useAuth();
  const { count } = useCart();
  const tabs = [
    { to: "/", label: "Catalogue", icon: icons.shop, end: true },
    { to: "/ai", label: "AI order", icon: icons.spark },
    { to: "/cart", label: "Cart", icon: icons.cart, badge: count },
    { to: "/orders", label: "Orders", icon: icons.list },
  ];
  return (
    <div className="min-h-dvh pb-[calc(4.5rem+env(safe-area-inset-bottom))]">
      <header className="sticky top-0 z-20 border-b border-line bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-2xl items-center justify-between gap-3 px-4 py-2.5">
          <div className="min-w-0">
            <p className="truncate text-[15px] font-semibold">{me?.retailer?.shop_name}</p>
            {me?.credit && (
              <p className="tabular truncate text-xs text-muted">
                Available credit {rupees(me.credit.available_credit)}
                {me.retailer?.is_demo_data && " · demo account"}
              </p>
            )}
          </div>
          <SignOut />
        </div>
      </header>
      <main className="mx-auto max-w-2xl px-4 py-4">
        <Outlet />
      </main>
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-white pb-[env(safe-area-inset-bottom)]"
      >
        <div className="mx-auto grid max-w-2xl grid-cols-4">
          {tabs.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              end={t.end}
              className={({ isActive }) =>
                cx(
                  "relative flex min-h-16 flex-col items-center justify-center gap-0.5 text-xs font-medium",
                  isActive ? "text-brand-700" : "text-muted hover:text-ink",
                )
              }
            >
              <Icon d={t.icon} />
              {t.label}
              {!!t.badge && (
                <span className="tabular absolute right-[calc(50%-1.4rem)] top-2 min-w-5 rounded-full bg-brand-700 px-1.5 text-center text-[11px] leading-5 text-white">
                  {t.badge}
                </span>
              )}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}

export function DeskLayout() {
  const { me } = useAuth();
  const links = [
    { to: "/desk", label: "Order queue", end: true },
    { to: "/desk/export", label: "Tally export" },
    { to: "/desk/aliases", label: "Retailer phrases" },
  ];
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-20 border-b border-line bg-white">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-2.5">
          <span className="hidden text-[15px] font-semibold sm:block">Order desk</span>
          <nav className="flex min-w-0 flex-1 gap-1 overflow-x-auto" aria-label="Desk">
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.end}
                className={({ isActive }) =>
                  cx(
                    "whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium",
                    isActive ? "bg-brand-50 text-brand-800" : "text-muted hover:bg-canvas hover:text-ink",
                  )
                }
              >
                {l.label}
              </NavLink>
            ))}
          </nav>
          <span className="hidden text-sm text-muted md:block">{me?.name}</span>
          <SignOut />
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-5">
        <Outlet />
      </main>
    </div>
  );
}

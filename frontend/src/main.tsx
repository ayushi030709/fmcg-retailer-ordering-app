import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import { DeskLayout, RequireRole, RetailerLayout } from "./layouts";
import AiCapture from "./pages/retailer/AiCapture";
import AiReview from "./pages/retailer/AiReview";
import Cart from "./pages/retailer/Cart";
import Catalogue from "./pages/retailer/Catalogue";
import { OrderDetail, OrdersList } from "./pages/retailer/Orders";
import SignIn from "./pages/SignIn";
import { AuthProvider, CartProvider } from "./state";
import { Spinner } from "./ui";

// Desk screens are split out so retailers on slow connections never download them.
const Queue = lazy(() => import("./pages/desk/Queue"));
const DeskOrderDetail = lazy(() => import("./pages/desk/OrderDetail"));
const Export = lazy(() => import("./pages/desk/Export"));
const Aliases = lazy(() => import("./pages/desk/Aliases"));

const loading = (
  <div className="flex min-h-dvh items-center justify-center text-muted">
    <Spinner />
  </div>
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <CartProvider>
          <Suspense fallback={loading}>
          <Routes>
            <Route path="/signin" element={<SignIn />} />
            <Route
              element={
                <RequireRole role="retailer">
                  <RetailerLayout />
                </RequireRole>
              }
            >
              <Route index element={<Catalogue />} />
              <Route path="cart" element={<Cart />} />
              <Route path="ai" element={<AiCapture />} />
              <Route path="ai/review/:id" element={<AiReview />} />
              <Route path="orders" element={<OrdersList />} />
              <Route path="orders/:id" element={<OrderDetail />} />
            </Route>
            <Route
              path="desk"
              element={
                <RequireRole role="order_desk">
                  <DeskLayout />
                </RequireRole>
              }
            >
              <Route index element={<Queue />} />
              <Route path="orders/:id" element={<DeskOrderDetail />} />
              <Route path="export" element={<Export />} />
              <Route path="aliases" element={<Aliases />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          </Suspense>
        </CartProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);

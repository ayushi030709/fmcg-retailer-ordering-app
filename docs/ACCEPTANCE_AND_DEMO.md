# Acceptance checklist and client demo script

How to verify every requirement in the project brief (Problem 5) and how to present the build.
Section numbers (§) refer to the brief.

## 0. Status at a glance

| Area | Status |
|---|---|
| Mandatory core build (§2.1, items 1–6) | **Built and tested** |
| User journeys A, B, C (§3) and the 8 screens with their states (§4) | **Built** |
| Seed data, sample message, scheme engine, GST policy (§5–6) | **Built and unit-tested** |
| AI design: constrained extraction, validation, deterministic confidence, clarifications, aliases, failure handling (§7) | **Built and tested.** Uses a mocked LLM in automated tests; **verify once with a real Groq key** (section 1.4) |
| Architecture, data model, API, security (§8–11) | **Built** |
| Tests (§12) | 104 pass on SQLite and 105 on PostgreSQL (the extra one is the concurrency test), plus a browser walkthrough (`e2e/walkthrough.cjs`) |
| TDD + deployment.md (§15) | **Written.** The live URL is still a placeholder |
| Live deployment | **Not done yet.** Needs your Render + Vercel accounts (see `deployment.md`) |
| Public GitHub repo | **Check this**: the repository must be public |
| Optional scope (§2.2: OCR, voice, salesman/offline, full PWA, dashboards) | Not built, by design (scope control) |

## 1. Before you start

1. Reset the demo data so every state exists. In `backend/`, run `python -m app.seed --reset` (Windows: `.venv\Scripts\python.exe -m app.seed --reset`). Then restart the API.
2. Demo accounts (synthetic). After requesting a code, the OTP is **123456**.
   - Retailer A `9000000001`: no saved vocabulary.
   - Retailer B `9000000002`: low credit; knows "peti"; synthetic negotiated detergent price.
   - Order desk `9000000009`.
3. For a phone-sized view on a PC, press F12 in Chrome, click the device toolbar icon, and pick a phone.
4. **Real LLM (needed once for the final checklist item):**
   1. Create a free API key at console.groq.com.
   2. Put it in `backend/.env` as `AI_PROVIDER_API_KEY=...` and restart the API.
   3. The AI screen badge should change from "Fallback parser" to "AI: groq · <model>".
   4. If extraction then says "AI service unavailable", check that `AI_MODEL` names a model your Groq account currently offers (default `llama-3.3-70b-versatile`).

## 2. Requirement checklist: what to do and what you should see

### 2.1 Mandatory core (§2.1)

| # | Requirement | How to check | Expected |
|---|---|---|---|
| 1 | Retailer auth and role; a retailer only sees their own data | Sign in as Retailer A. Open **Orders**. Sign out, sign in as B, open **Orders** | Each sees only their own orders. Header shows their own shop and credit |
| 1b | Role comes from the server, not a dropdown | Sign in as a retailer, then type `/desk` in the address bar | You are sent back to the catalogue. The API returns 403 for desk endpoints (tests: `test_auth.py`) |
| 1c | Mock OTP clearly labelled | Request a code | Blue note: "Demo mode: no SMS is sent. Use the reviewer code 123456." |
| 2 | Catalogue: SKUs, dealer price, stock, scheme, GST label | Catalogue screen | 3 SKUs from the brief: ₹8.10 / ₹101.50 / ₹118.00 per case, each labelled "excl. GST · 18% added at checkout". Stock 340 / 85 / out of stock. Badges "Buy 10 cases, get 1 free" and "3% off 5 or more cases". Tea shows "Unavailable" |
| 3 | Cart: add/remove, quantities, schemes, totals, stock and credit validation, submit | Add biscuit ×10 and detergent ×5, open **Cart** | Biscuit: "+1 case free · 11 cases delivered". Detergent: "3% off − ₹15.23". Total **₹676.46**. Change quantities and the totals update. **Remove** works |
| 4 | AI text capture: extract, map to SKUs, show original wording, confidence, alternatives, clarifications | **AI order → Use sample message → Extract order lines** | 3 lines, each quoting "You wrote: …", with a confidence badge, a "Why: …" explanation, alternatives on the uncertain biscuit line, and a "Does 'peti' mean one case…?" question |
| 5 | Human confirmation: AI never places an order | After extracting, open **Orders** | No new order. The confirm button stays disabled until every line is resolved |
| 6 | Order desk: view, inspect, correct, hold/approve, export CSV | Sign in as desk | Queue, detail, Correct line, Approve / Put on hold / Release / Reject, **Tally export** |

### 2.2 Journeys (§3)

| Journey | Steps | Expected |
|---|---|---|
| **A: manual order** | Retailer A: catalogue → add → cart → **Place order** | Confirmation page with an order reference (`ORD-…`) and status "Pending review". The server re-checks everything; stock drops by paid + free cases |
| **B: AI order** | Sample message → answer "Yes, 1 peti = 1 case" on biscuit and detergent → tea shows "out of stock — can't be ordered" → **Don't order this** on tea → **Confirm and place order** | Order created with source "via AI". Each line keeps its original phrase (visible on the order and to the desk) |
| B: learning | Extract the sample message again | "peti" is understood ("you've told us 'peti' means a case") and those lines show **Ready** |
| B: retailer-specific vocabulary | Sign in as Retailer B and extract the sample message | "peti" is already known, and "biscuit chhota" matches at ≥95% from B's saved phrase |
| **C: desk** | Desk: **On hold** tab → open the order | Hold reason ("Credit limit exceeded…") and a credit panel (limit, outstanding, open orders, available) |
| C: approve with override | **Approve** → enter a note → confirm | Status Approved. History shows "Approved from hold (override)" with your name and the note |
| C: correction | Open an AI order → **Correct line** → change quantity → give a reason → save | Totals recalculate. History shows "Line corrected · Demo Order Desk", the before → after values and the reason |
| C: export | **Tally export** → **Export N orders to CSV** | CSV downloads. Batch appears in Export history (time, user, order numbers). The orders show "Sent to Tally" |
| C: no duplicate export | Export again | "Nothing waiting for export". Past batches can only be re-downloaded, not re-exported |

### 2.3 Screen states (§4)

| Screen | State | How to trigger |
|---|---|---|
| Sign in | Invalid OTP / lockout | Enter `000000`: "That code is not correct". After 5 wrong tries: "Too many wrong attempts" |
| Sign in | Expired OTP | Wait more than 5 minutes after requesting a code, then verify |
| Catalogue | No results | Search "xyz" |
| Catalogue | Loading / API error / slow network | DevTools → Network → "Slow 3G" (skeleton cards). Stop the API to see the error panel with **Try again** |
| Cart | Empty cart | Remove all lines |
| Cart | Insufficient stock | Biscuit quantity above available stock: line shows "Only N cases… needs M (paid + free)" and submit is disabled |
| Cart | Credit hold | As Retailer B, add any order: amber "Credit review needed"; the button reads "Place order for credit review" |
| AI capture | Empty input | Click Extract with an empty box: "Type or paste an order message first" |
| AI capture | AI unavailable / timeout / invalid response | Set `AI_PROVIDER_API_KEY=wrong`, restart the API, extract: red error with **Try again** and **Order from catalogue instead**; your text is kept. Use `AI_TIMEOUT_SECONDS=0.001` for the timeout variant. All three cases are also automated tests |
| AI review | Low confidence / no match | Message `3 case maggi noodles`: "We could not match…", pick a product or remove |
| AI review | Ambiguous unit | Any "peti", "box" or "dabba": unit question. `10 pcs biscuit`: "looks like pieces… sold by the case" |
| AI review | Partial extraction | LLM path: any text the AI skipped is added as a line with a warning (automated test `test_partial_extraction_surfaces_missed_text`) |
| Desk queue | Filters / no orders | Status tabs with counts, shop search, retailer and date filters. The Rejected tab is empty: "No orders here" |
| Desk detail | Concurrent update | Open the same order in two tabs. Approve in tab 1, then act in tab 2: "Someone else updated this order", with **Reload latest** |
| Export | No eligible orders | Export everything, then reopen: "Nothing waiting for export" |

### 2.4 Business rules (§5–6), all computed on the server

| Rule | Check | Expected |
|---|---|---|
| Biscuit buy 10 get 1 | Quantities 9 / 10 / 20 / 25 | Free 0 / 1 / 2 / 2. At 9 a tip says "Add 1 more case to get 1 more free" |
| Detergent 3% off at 5+ | Quantities 4 / 5 | 4: no discount, plus a tip. 5: −₹15.23 (brief example 15.225 rounded half-up) |
| Tea no scheme, zero stock | Catalogue and AI line | Cannot be added; the AI line is flagged and blocks confirmation |
| Free goods consume stock | Desk queue: stock "available after reservations" | 10 paid biscuit = 11 cases reserved |
| GST policy labelled | Every price | "excl. GST", with GST shown separately at checkout (assumption A1, demo 18%) |
| Sample-message interpretation (§5.1) | AI sample | BS-075 ×5, DT-1KG ×2, TE-250 ×1 (flagged), with "peti" asked, never assumed |

### 2.5 Security and data (§11, §14), mostly covered by automated tests

- Retailer A cannot open B's order: `/orders/<B's id>` shows "Order not found" (404, so it is not revealed that the order exists).
- Retailer B's negotiated price (₹99.00 detergent) is visible only to B; A still sees ₹101.50.
- No secrets in git: only `.env.example` files with placeholders. The LLM key stays on the server.
- Run the tests in `backend/`: `pytest -q`. The suite covers auth, ownership, scheme boundaries, pricing, stock, credit, AI failures and export.

### 2.6 Submission (§15, §19)

- [ ] Repository is **public** on GitHub.
- [ ] App deployed. Live URLs filled into `docs/TDD.md` (top and §1) and `deployment.md`, PDF rebuilt (`bash docs/pdf/build.sh`).
- [ ] AI extraction verified once with a real Groq key (section 1.4).
- [ ] ZIP contains exactly `Technical_Design_Document.pdf` and `deployment.md`.

## 3. Showcasing to the client (about 12 minutes)

**Set-up:** reset the data, set the Groq key, open two browser windows (one phone-sized for the retailer, one desktop for the desk), and keep `export.csv` ready to open in Excel. To demo on a real phone on the same Wi-Fi, run `npm run dev -- --host` and open `http://<your-PC-IP>:5173` on the phone (allow it through Windows Firewall).

1. **The problem (1 min).** 1,800 kirana shops order by WhatsApp text, photos and voice notes. Six staff retype orders into Tally the next morning. The brief estimates a 5% error rate and ~₹52.5 lakh a year in avoidable cost. Goal: faster ordering and fewer entry errors.
2. **Retailer orders from the catalogue (2 min).** On the phone view: their own price per case, the GST label, stock, schemes, and out-of-stock tea. Add 10 biscuit cases: the free case appears, calculated by the server. Place the order and show the reference.
3. **AI order capture (3 min). This is the highlight.** Paste the WhatsApp sample. Point out:
   - every line keeps the retailer's own words;
   - the confidence badge and the reason behind it;
   - "peti" is *asked*, not guessed;
   - tea is blocked as out of stock;
   - nothing is ordered until the retailer presses Confirm.

   Confirm, then paste the same message again: the system has learned this retailer's "peti". Key line: *the AI only reads the message; prices, schemes, GST, stock and credit are calculated by the server.*
4. **Credit control (1 min).** Retailer B's order is accepted but put on hold for credit review instead of being rejected outright.
5. **Order desk (3 min).**
   - Queue tabs with counts.
   - The held order: credit panel, then approve with an override note, which is audited.
   - The AI order: the original WhatsApp text is visible. Correct a quantity and show the before/after in History.
   - Export to CSV and open it in Excel: paid vs free cases, discount, taxable value, GST. Export again to show it's blocked.
6. **Close (2 min).** What's built, the assumptions you need them to confirm, and next steps.

**Questions to ask the client (assumptions to confirm):**

1. Are dealer prices per case or per pack? The brief's example treats them per case, but ₹8.10 for 96 biscuits looks per-pack.
2. Are prices GST-exclusive, and what is the rate per product?
3. What exact column layout does your Tally import need?
4. Does "peti" always mean a case for your retailers?
5. What should happen when a retailer is over their credit limit: hold, or block?
6. Should exported orders keep counting against credit until Tally updates the outstanding balance?

**Likely questions and short answers:**

- *What if the AI is wrong?* It only proposes lines. Confidence comes from checkable evidence (keywords, pack size, the retailer's confirmed phrases), not the model's opinion. Anything unclear becomes a question, and a person confirms every order.
- *What if the AI service is down?* The retailer sees an error with retry, their text is kept, and they can order from the catalogue. No order is affected.
- *Can two orders oversell the last stock?* No. Stock rows are locked during submission; an automated PostgreSQL test runs two simultaneous orders and only one succeeds.
- *Can one shop see another's prices or orders?* No. Ownership is checked on the server for every request, and this is tested.
- *Double-tap on Place order?* Each submission carries an idempotency key, so a retry returns the same order.
- *How fast on 3G?* Measured locally with Chrome network throttling and 4× CPU slowdown: about 2.1 s on a ~750 kbps 3G-like profile and about 4.5 s on a slower 400 kbps / 400 ms profile. The 3-second target holds on the first profile but not the slower one; the TDD explains why and how to improve it.
- *What's next?* Photo/voice ordering, salesman mode with offline capture, real SMS OTP, a Tally sync for outstanding balances, and admin screens for prices, stock and schemes.

# Automatic subscription payments with Square

## What it does
An Organisation Admin adds a card (Settings > Business Setup > Organisation > Subscription), chooses monthly or yearly and presses "Pay now and renew automatically".
AccFino takes the first payment immediately and then charges the organisation's plan (+ add-ons) at the start of every period, with no action from them.
- Price = the plan price for the period + add-ons (a year is charged as 11 months: one month free), AUD incl. GST, read from the plans you edit in Admin Console > Pricing.
- Square emails the receipt. A history with receipt links is shown to the organisation.
- A declined card: the organisation is emailed, the plan is "past due" (still working through the 7-day grace period), AccFino retries after 3 and 6 days, then stops. Saving a new card fixes it at once.
- Cards are typed into Square's secure form. AccFino never sees or stores card numbers - only Square's ids and the last 4 digits.

## One-time set-up (AccFino administrator)
1. Square Developer Dashboard (developer.squareup.com) > create an application. Copy the **Application ID**, an **Access token** and your **Location ID** (an Australian location; AccFino bills in AUD).
2. Admin Console > API Keys > Payment Card Setup > Square: paste them, choose **Sandbox** first, Save, **Test connection**.
3. Sign in as an Organisation Admin, add Square's sandbox test card (4111 1111 1111 1111, any future expiry, CVV 111, postcode 94103) and press Subscribe. Check the payment in the Square sandbox dashboard.
4. When happy, replace the three values with your **Production** ones and set Environment to Production.
   (Square credentials saved here replace anything saved earlier in the old Square screen: that older storage is not used for billing.)

## Environment variables (optional)
- `SQUARE_ACCESS_TOKEN`, `SQUARE_APPLICATION_ID`, `SQUARE_LOCATION_ID`, `SQUARE_ENVIRONMENT` - override the Admin screen.
- `BILLING_AUTORUN=0` - stop the automatic renewal loop on this server. `BILLING_INTERVAL_MIN=30` - how often it checks (minimum 5).

## Things to know
- Renewals are driven by a background loop inside the web app (one worker at a time). Admin Console > Payment Card Setup > Square > "Run billing now" runs it on demand.
- If a server restarts mid-charge, the next pass completes it safely (same idempotency key: Square never charges twice).
- Refunds and disputes are handled in your Square dashboard; AccFino does not yet change a plan when you refund.
- Tax invoices: Square's receipt shows the amount paid. AccFino does not yet issue its own GST tax invoice for subscriptions.
- Every plan is for 1 user. More users are a user pack (an add-on) that the AccFino team arranges and prices for each organisation - it is then charged with the plan.
- Seat or add-on changes take effect at the next charge (no part-period proration).

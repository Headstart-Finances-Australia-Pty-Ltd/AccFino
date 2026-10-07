# 06 – Lodgement, declarations and tax-agent sign-off

## How products like Lodgeit lodge, and why AccFino does not (yet)
Direct electronic lodgement with the ATO is done by **Digital Service Providers (DSPs)** over **Standard Business Reporting (SBR)**. To do it a provider must: register and meet the ATO's **DSP Operational Security Framework** (encryption, unique user logins, multi-factor authentication, entity validation); build and test against the ATO's **EVTE (SBR2)** environment; obtain a **Product ID** and pass conformance testing; be **whitelisted** for production; and sign transactions with a **myID machine credential**. Even then the declaration is always made by a person: the taxpayer, or a registered tax or BAS agent. The ATO's DSP conditions of use also **exclude services that let individuals lodge a basic income tax return themselves without an agent**, which is why such returns normally go through an agent.

AccFino is not a DSP, so it cannot honestly "lodge". Nothing in AccFino contacts the ATO unless an accredited gateway adapter is plugged in (below). What it does provide, working end to end:

| Route | What it does | Reaches the ATO? |
|---|---|---|
| **Manual record** | You or your agent lodge through ATO Online services, myTax or practice software, then record the receipt reference | Not through AccFino |
| **Agent hand-off pack** | A zip for the agent who will lodge: figures (labels in ATO form order, whole dollars), working, sign-offs, evidence with SHA-256, checklist | No: nothing is sent anywhere |
| **Gateway** | Submits through an ATO-accredited SBR/DSP adapter configured by the operator | Yes, only when an adapter is configured and ready |
| **Simulation** | Made-up receipt for trying the screens. Off by default; **never marks the document lodged** | No |

## Declarations and agent sign-off
Recording lodgement, or submitting through a provider, **requires a declaration** on the exact figures:
- **Taxpayer / authorised person**: any user with the Accountant or Organisation Admin role can declare for the organisation.
- **Registered tax agent** or **registered BAS agent**: an Accountant-role user (for example the agent, invited as a member) signs off with their **8-digit registration number**. AccFino records the number as declared and does **not** verify it: check it on the Tax Practitioners Board public register. Entering a Tax File Number is refused by format.

A declaration is bound to the document's calculation fingerprint. If the ledger, payroll, adjustments, inputs or CGT events change, signing is refused as stale; if the document is returned to draft, voided or amended, existing sign-offs are superseded and the people must sign again. A sign-off can be revoked (with a reason) until lodgement is recorded. The declaration text says AccFino records the declaration only and that the ATO's own declaration is made in the channel that actually lodges: AccFino does not reproduce the ATO's wording.

**Policy** (Rates & Settings > Tax profile > Lodgement policy): *the taxpayer or a registered agent may sign off* (default), or *a registered tax / BAS agent must sign off*. Under the strict policy a taxpayer declaration is recorded but does not unlock lodgement.

Sequence: prepared → approved (a different person, unless self-approval is enabled) → **declaration or agent sign-off** → lodge by one of the routes → lodgement recorded with the ATO receipt → paid. Every step is in the hash-chained audit trail (`signoff.taxpayer`, `signoff.tax_agent`, `signoff.revoked`, `lodgement.<provider>.<status>`).

## Plugging in an accredited gateway
Implement a class with two methods and set `ACCFINO_TAX_GATEWAY_ADAPTER=your.module.YourAdapter`:
```python
class YourAdapter:
    def ready(self):                      # (bool, reason): credentials present, connectivity, whitelisting
        return True, ""
    def submit(self, payload: dict, doc_type: str) -> dict:
        # payload: entity, period, labels / return / fbt figures, sign-offs, figures_fingerprint (see build_payload).
        # Map it onto the ATO's SBR schemas, sign with the machine credential, send, and return:
        return dict(status="accepted", receipt_reference="<ATO receipt>", message="...")   # or submitted / rejected / failed
```
Rules enforced by AccFino: the adapter is only called after approval, a valid declaration (and an agent sign-off if the policy requires it) and a still-current fingerprint; an `accepted` answer **without a receipt reference is treated as failed**; a rejected or failed answer never marks the document lodged; an adapter that cannot be loaded makes the gateway unavailable with the reason shown. An accepted submission records the lodgement with method `gateway`. `AccFino_Testing/tests/_support/fake_gateway.py` is a test double that proves this path.

The onboarding itself (DSP registration, security questionnaire, EVTE testing, Product ID, whitelisting, myID machine credential) is the operator's and cannot be done in code.

## Simulation
`ACCFINO_TAX_LODGEMENT_SANDBOX=1` shows a "Run simulation" route for test and demonstration servers. It returns a receipt starting `SIM-`, records the attempt as **simulated**, and leaves the document unlodged. Never enable it where real lodgement is expected.

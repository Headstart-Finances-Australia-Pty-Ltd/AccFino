"""Declarations, tax-agent sign-off and lodgement providers.

HOW THIS RELATES TO REAL LODGEMENT
Direct electronic lodgement with the ATO is done by Digital Service Providers (DSPs) over Standard Business Reporting (SBR): the provider must meet the ATO's DSP Operational
Security Framework, test in the ATO's EVTE environment, hold a Product ID and be whitelisted, and transactions are signed with a myID machine credential. The ATO's DSP conditions
of use also exclude services that let individuals lodge a basic income tax return themselves without an agent. AccFino is not a DSP, so nothing here talks to the ATO unless an
accredited gateway adapter is plugged in. What IS built and works end to end:
  * a DECLARATION by the taxpayer / authorised person, or a distinct SIGN-OFF by a registered tax agent or BAS agent, bound to the exact figures (their fingerprint);
  * an organisation POLICY that can require agent sign-off before lodgement can be recorded;
  * a provider interface: manual (record what you lodged elsewhere), agent hand-off pack (everything the agent needs, as a zip), sandbox (SIMULATION ONLY, off by default) and an
    SBR/DSP gateway slot that stays unavailable until an accredited adapter is configured.
AccFino records the declaration; the ATO's own declaration is made in whichever channel actually lodges."""
import csv
import hashlib
import importlib
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from accfino.modules.taxation.engine import bas as BE, rules as R
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import bas as B, core, fbt as F, profile as P, returns as RT, workpapers as W
from accfino.modules.taxation.services.core import Conflict, NotFound, TaxError

DECL_VERSION = "2026.1"
DECLARATIONS = {
    "taxpayer": ("I declare that the figures in this document were prepared from the records of the entity named on it and, to the best of my knowledge, are true and correct. "
                 "I have read the findings and items marked 'Needs review' and they have been resolved or accepted. I understand that AccFino records this declaration only: the declaration "
                 "required by the ATO is made when the document is actually lodged through the ATO's own channel."),
    "tax_agent": ("As a registered tax agent (registration number shown) I have reviewed this document, its workpapers and supporting evidence and I am satisfied it may be lodged on behalf of "
                  "the client. I have considered the items marked 'Needs review'. AccFino records this sign-off only; the declaration required by the ATO is made in the lodgement channel."),
    "bas_agent": ("As a registered BAS agent (registration number shown) I have reviewed this document, its workpapers and supporting evidence and I am satisfied it may be lodged on behalf of "
                  "the client. AccFino records this sign-off only; the declaration required by the ATO is made in the lodgement channel."),
}
AGENT_NO = re.compile(r"^\d{8}$")
DOC_LABEL = {"bas_statement": "Activity statement", "tax_return": "Income tax return", "fbt_return": "FBT return"}


# ---------------------------------------------------------------------------------------------------------------------- documents
@dataclass
class Doc:
    type: str
    obj: Any
    status: str
    calc_hash: Optional[str]
    title: str


def load_doc(db, ctx, doc_type: str, doc_id: int) -> Doc:
    if doc_type == "bas_statement":
        s = B.get(db, ctx, doc_id)
        return Doc(doc_type, s, s.status, s.calc_hash, f"{s.kind.upper()} {s.period_start} to {s.period_end}")
    if doc_type == "tax_return":
        r = RT.get(db, ctx, doc_id)
        return Doc(doc_type, r, r.status, r.calc_hash, f"Income tax return {r.fy} v{r.version}")
    if doc_type == "fbt_return":
        r = F.get_return(db, ctx, doc_id)
        return Doc(doc_type, r, r.status, r.calc_hash, f"FBT return {r.fbt_year}")
    raise TaxError(f"doc_type must be one of {', '.join(T.SIGNOFF_DOC_TYPES)}")


def current_hash(db, ctx, d: Doc) -> Optional[str]:
    """Fingerprint of the figures as they are NOW (the same recomputation approval uses). A sign-off is only good while this equals the fingerprint it was bound to."""
    p = P.get(db, ctx)
    if d.type == "bas_statement":
        return B._hash(db, ctx, d.obj, p)
    if d.type == "tax_return":
        return RT._hash(RT._sources(db, ctx, d.obj, p), d.obj.inputs or {}, p)
    return F._hash(dict(F.summary(db, ctx, d.obj.fbt_year), findings=None))


def so_dict(s: T.TaxSignoff) -> dict:
    return dict(id=s.id, doc_type=s.doc_type, doc_id=s.doc_id, capacity=s.capacity, signer_name=s.signer_name, agent_number=s.agent_number, status=s.status, declaration_version=s.declaration_version,
                declaration_text=s.declaration_text, signed_at=core.plain(s.signed_at), ended_at=core.plain(s.ended_at), end_reason=s.end_reason, note=s.note, doc_hash=s.doc_hash[:12])


# ---------------------------------------------------------------------------------------------------------------------- sign-off
def sign(db, ctx, a: core.Access, doc_type: str, doc_id: int, capacity: str, typed_name: str, confirmed: bool, agent_number: str = "", note: str = "") -> T.TaxSignoff:
    a.require("lodge")
    if capacity not in T.SIGNOFF_CAPACITIES:
        raise TaxError(f"capacity must be one of {', '.join(T.SIGNOFF_CAPACITIES)}")
    d = load_doc(db, ctx, doc_type, doc_id)
    if d.status != "approved":
        raise Conflict(f"Only an approved document can be signed off (status is {d.status}).")
    if not confirmed:
        raise TaxError("You must confirm the declaration")
    name = (typed_name or "").strip()
    if len(name) < 3:
        raise TaxError("Type your full name to sign")
    num = re.sub(r"\s", "", agent_number or "")
    if capacity in ("tax_agent", "bas_agent"):
        if not AGENT_NO.match(num):
            raise TaxError("Enter the agent's registration number (8 digits). Never enter a Tax File Number. AccFino records the number as declared: verify it on the Tax Practitioners Board public register.")
    else:
        num = ""
    if current_hash(db, ctx, d) != d.calc_hash:
        raise Conflict("The ledger, payroll, adjustments or inputs changed after this document was approved. Return it to draft, recalculate and approve again before signing off.", "stale")
    dup = db.query(T.TaxSignoff).filter_by(org_id=ctx.org.id, doc_type=doc_type, doc_id=doc_id, capacity=capacity, signer_user_id=ctx.user_id, status="valid").first()
    if dup and dup.doc_hash == d.calc_hash:
        raise Conflict("You have already signed off this document in that capacity.", "already_signed")
    s = T.TaxSignoff(org_id=ctx.org.id, doc_type=doc_type, doc_id=doc_id, capacity=capacity, signer_user_id=ctx.user_id, signer_name=name[:200], agent_number=num or None,
                     declaration_version=DECL_VERSION, declaration_text=DECLARATIONS[capacity], doc_hash=d.calc_hash, status="valid", note=(note or "")[:500] or None)
    db.add(s)
    db.flush()
    core.record(db, ctx, f"signoff.{capacity}", doc_type, doc_id, f"{DOC_LABEL[doc_type]} signed off by {name} as {capacity.replace('_', ' ')}{' (agent no. ' + num + ', not verified by AccFino)' if num else ''}",
                None, dict(signoff_id=s.id, doc_hash=d.calc_hash[:12], version=DECL_VERSION))
    return s


def revoke(db, ctx, a: core.Access, signoff_id: int, reason: str) -> T.TaxSignoff:
    a.require("lodge")
    s = db.query(T.TaxSignoff).filter_by(org_id=ctx.org.id, id=signoff_id).first()
    if s is None:
        raise NotFound("Sign-off")
    if s.status != "valid":
        raise Conflict(f"That sign-off is already {s.status}.")
    d = load_doc(db, ctx, s.doc_type, s.doc_id)
    if d.status in ("lodged", "paid"):
        raise Conflict("The document has been recorded as lodged: a sign-off can no longer be revoked here.", "lodged")
    if not reason or len(reason.strip()) < 5:
        raise TaxError("A reason (at least 5 characters) is required")
    s.status, s.ended_at, s.ended_by, s.end_reason = "revoked", datetime.utcnow(), ctx.user_id, reason.strip()[:300]
    core.record(db, ctx, "signoff.revoked", s.doc_type, s.doc_id, f"Sign-off by {s.signer_name} revoked: {reason.strip()[:150]}", None, None)
    return s


# ---------------------------------------------------------------------------------------------------------------------- payload & pack
def build_payload(db, ctx, doc_type: str, doc_id: int) -> dict:
    """What AccFino hands to a provider. It is NOT an ATO SBR message: an accredited gateway adapter maps it onto the ATO's schemas. No Tax File Number is ever included."""
    d = load_doc(db, ctx, doc_type, doc_id)
    p = P.get(db, ctx)
    org = ctx.org
    body: Dict[str, Any] = dict(entity=dict(name=org.name, legal_name=getattr(org, "legal_name", None), abn=p.abn or org.abn, entity_type=p.entity_type, gst_registered=p.gst_registered, gst_basis=p.gst_basis),
                                document=dict(type=doc_type, id=doc_id, title=d.title, status=d.status, figures_fingerprint=d.calc_hash))
    if doc_type == "bas_statement":
        s = d.obj
        body["period"] = dict(start=s.period_start.isoformat(), end=s.period_end.isoformat(), kind=s.kind, frequency=s.frequency)
        body["labels"] = {k: s.final[k]["value"] for k in BE.ordered_labels(s.final or {})}
        fig = BE.lodgement_figures(s.final or {})
        body["labels_whole_dollars"] = {k: fig[k] for k in BE.ordered_labels(s.final or {}) if k in fig}
    elif doc_type == "tax_return":
        r = d.obj
        c = r.computation or {}
        body["period"] = dict(income_year=r.fy, version=r.version)
        body["return"] = {k: c.get(k) for k in ("entity", "taxable_income", "income_tax", "offsets", "medicare_levy", "tax_assessed", "credits", "balance", "rule_set")}
        body["return"]["inputs"] = r.inputs or {}
        body["return"]["steps"] = [dict(label=s_["label"], amount=s_["amount"], basis=s_["kind"]) for s_ in c.get("steps", [])]
    else:
        r = d.obj
        body["period"] = dict(fbt_year=r.fbt_year)
        body["fbt"] = {k: (r.summary or {}).get(k) for k in ("type1_taxable", "type2_taxable", "type1_grossed_up", "type2_grossed_up", "aggregate_fringe_benefits_amount", "fbt_rate", "fbt_payable", "employees")}
    body["signoffs"] = [so_dict(s) for s in db.query(T.TaxSignoff).filter_by(org_id=ctx.org.id, doc_type=doc_type, doc_id=doc_id, status="valid").order_by(T.TaxSignoff.id) if s.doc_hash == d.calc_hash]
    body["generated_by"] = "AccFino Taxation & Compliance"
    body["notice"] = "Prepared by AccFino for lodgement through an ATO channel. This is not an ATO SBR message and AccFino has not lodged it."
    return core.plain(body)


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def build_pack(db, ctx, doc_type: str, doc_id: int) -> Tuple[str, bytes]:
    """Hand-off pack for the registered agent who will lodge: figures, working, sign-offs, evidence (with SHA-256) and a checklist, as one zip."""
    d = load_doc(db, ctx, doc_type, doc_id)
    payload = build_payload(db, ctx, doc_type, doc_id)
    buf = io.BytesIO()
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", d.title)[:60]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", (f"AccFino lodgement hand-off pack\n{d.title}\nEntity: {payload['entity']['name']} (ABN {payload['entity']['abn']})\n\n"
                                  "This pack was prepared by AccFino for a registered tax or BAS agent (or the taxpayer) to lodge through ATO Online services or practice software.\n"
                                  "AccFino has NOT lodged anything with the ATO. The declaration required by the ATO is made when you lodge.\n"
                                  "Contents: summary.json (everything below in one file), figures.csv, signoffs.json, evidence/ (files and manifest.csv with SHA-256), checklist.txt.\n"
                                  "Items marked 'review' in the working need professional judgement. No Tax File Number is held or included.\n"))
        z.writestr("summary.json", json.dumps(payload, indent=2))             # insertion order kept (labels in ATO form order); only the HASH uses sorted keys
        rows = []
        if doc_type == "bas_statement":
            rows = [(k, payload["labels"][k], payload["labels_whole_dollars"].get(k, "")) for k in payload["labels"]]
            head = ("label", "value", "whole_dollars_to_key")
        elif doc_type == "tax_return":
            rows = [(s_["label"], s_["amount"], s_["basis"]) for s_ in payload["return"]["steps"]]
            head = ("working", "amount", "basis")
        else:
            rows = [(k, v, "") for k, v in payload["fbt"].items() if k != "employees"]
            head = ("item", "value", "")
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(head)
        for r_ in rows:
            w.writerow([("'" + str(c)) if str(c)[:1] in ("=", "+", "-", "@") and not _isnum(c) else c for c in r_])
        z.writestr("figures.csv", out.getvalue())
        z.writestr("signoffs.json", json.dumps(payload["signoffs"], indent=2))
        ev = W.evidence_for(db, ctx, linked_type=doc_type, linked_id=doc_id)
        for wp in W.listing(db, ctx):
            if wp["linked_type"] == doc_type and wp["linked_id"] == doc_id:
                ev += W.evidence_for(db, ctx, workpaper_id=wp["id"])
                z.writestr(f"workpapers/{wp['reference'] or wp['id']}.json", json.dumps(core.plain(W.w_dict(W.get(db, ctx, wp["id"]))), indent=2))
        man = io.StringIO()
        mw = csv.writer(man)
        mw.writerow(("title", "kind", "detail", "sha256", "size"))
        for e in ev:
            mw.writerow((e["title"], e["kind"], e["url"] or e["ledger_ref"] or e["note"] or "", e["sha256"] or "", e["size"] or ""))
            if e["kind"] == "file":
                f = W.evidence_file(db, ctx, e["id"])
                z.writestr(f"evidence/{e['id']}_{re.sub(r'[^A-Za-z0-9_.-]+', '_', f.file_name or 'file')}", f.data)
        z.writestr("evidence/manifest.csv", man.getvalue())
        sig = payload["signoffs"]
        z.writestr("checklist.txt", "\n".join([
            f"[{'x' if d.status in ('approved', 'lodged', 'paid') else ' '}] Document approved in AccFino", f"[{'x' if sig else ' '}] Declaration / sign-off recorded ({', '.join(s['capacity'] for s in sig) or 'none'})",
            f"[{'x' if ev else ' '}] Evidence attached ({len(ev)} item(s))", "[ ] Figures keyed or imported into the ATO channel", "[ ] Declaration made in the ATO channel",
            "[ ] Receipt reference recorded back in AccFino (Sign-off & lodgement panel > Record lodgement)", "", "AccFino has not lodged this document."]))
    return f"accfino_handoff_{safe}.zip", buf.getvalue()


def _isnum(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------------------------------------------------- providers
@dataclass
class Result:
    status: str                                  # handed_off | submitted | accepted | rejected | failed | simulated
    message: str = ""
    receipt_reference: Optional[str] = None
    simulated: bool = False
    response: dict = field(default_factory=dict)


class Provider:
    name = ""
    label = ""
    real = False                                 # True only when a submission can reach the ATO
    description = ""

    def available(self) -> Tuple[bool, str]:
        return True, ""

    def submit(self, payload: dict, doc: Doc, pack: Optional[Tuple[str, bytes]]) -> Result:
        raise TaxError("This provider does not submit; use it from the Sign-off & lodgement panel", 409, "not_applicable")


class ManualProvider(Provider):
    name, label = "manual", "Lodge elsewhere, then record it here"
    description = "You (or your agent) lodge through ATO Online services, myTax or practice software, then record the receipt reference. Needs the declaration first."


class AgentPackProvider(Provider):
    name, label = "agent_pack", "Hand off to my tax agent (download pack)"
    description = "Produces a zip with figures, working, sign-offs and evidence for the agent who will lodge. Nothing is sent anywhere."

    def submit(self, payload, doc, pack):
        return Result("handed_off", "Hand-off pack prepared. Nothing has been lodged: the agent lodges, then the receipt reference is recorded here.", response=dict(pack=pack[0], bytes=len(pack[1]), sha256=hashlib.sha256(pack[1]).hexdigest()))


class SandboxProvider(Provider):
    name, label = "sandbox", "Simulated lodgement (testing only)"
    description = "SIMULATION. Returns a made-up receipt so the screens and workflow can be tried. Nothing reaches the ATO and the document is NOT marked lodged."

    def available(self):
        if os.environ.get("ACCFINO_TAX_LODGEMENT_SANDBOX", "").strip().lower() in ("1", "true", "yes"):
            return True, ""
        return False, "Disabled. Set ACCFINO_TAX_LODGEMENT_SANDBOX=1 on a test or demo server to enable the simulation. It must never be enabled where real lodgement is expected."

    def submit(self, payload, doc, pack):
        h = payload_hash(payload)
        return Result("simulated", "SIMULATED: nothing was sent to the ATO.", receipt_reference="SIM-" + h[:10].upper(), simulated=True, response=dict(note="simulation", payload_hash=h))


ONBOARDING = ("Direct lodgement needs an accredited Digital Service Provider adapter: (1) register with the ATO as a DSP and meet the DSP Operational Security Framework, (2) build and test against the "
              "ATO's EVTE (SBR2) environment, (3) obtain a Product ID and complete conformance testing, (4) be whitelisted for production and hold a myID machine credential, "
              "(5) implement GatewayAdapter (see docs/taxation/06) and set ACCFINO_TAX_GATEWAY_ADAPTER to its dotted path. The ATO's DSP conditions of use also exclude services that let individuals "
              "lodge a basic income tax return without an agent.")


class GatewayProvider(Provider):
    name, label, real = "sbr_gateway", "Lodge with the ATO through an accredited gateway", True
    description = "Submits through an ATO-accredited SBR/DSP adapter configured by the operator of this AccFino installation."

    def _adapter(self):
        path = os.environ.get("ACCFINO_TAX_GATEWAY_ADAPTER", "").strip()
        if not path:
            return None, "No accredited gateway adapter is configured. " + ONBOARDING
        try:
            mod, _, cls = path.rpartition(".")
            return getattr(importlib.import_module(mod), cls)(), ""
        except Exception as e:                                           # a broken adapter must be visible, not silent
            return None, f"The configured gateway adapter could not be loaded ({type(e).__name__}: {e})."

    def available(self):
        ad, why = self._adapter()
        if ad is None:
            return False, why
        ok = getattr(ad, "ready", lambda: (True, ""))()
        return (bool(ok[0]), ok[1]) if isinstance(ok, tuple) else (bool(ok), "")

    def submit(self, payload, doc, pack):
        ad, why = self._adapter()
        if ad is None:
            raise TaxError(why, 409, "gateway_unavailable")
        res = ad.submit(payload, doc.type)
        if not isinstance(res, dict) or res.get("status") not in ("submitted", "accepted", "rejected", "failed"):
            return Result("failed", "The gateway adapter returned an unrecognised response.", response=dict(raw=str(res)[:300]))
        if res["status"] == "accepted" and not res.get("receipt_reference"):
            return Result("failed", "The gateway reported acceptance without an ATO receipt reference: not treated as lodged.", response=core.plain(res))
        return Result(res["status"], str(res.get("message") or "")[:480], receipt_reference=res.get("receipt_reference"), simulated=False, response=core.plain(res))


PROVIDERS: Dict[str, Provider] = {p.name: p for p in (ManualProvider(), AgentPackProvider(), SandboxProvider(), GatewayProvider())}


def providers() -> List[dict]:
    out = []
    for p in PROVIDERS.values():
        ok, why = p.available()
        out.append(dict(name=p.name, label=p.label, description=p.description, real=p.real, available=ok, reason=why))
    return out


# ---------------------------------------------------------------------------------------------------------------------- state & submission
def lodg_dict(l: T.TaxLodgement) -> dict:
    return dict(id=l.id, doc_type=l.doc_type, doc_id=l.doc_id, provider=l.provider, status=l.status, simulated=l.simulated, receipt_reference=l.receipt_reference, message=l.message,
                submitted_at=core.plain(l.submitted_at), signoff_id=l.signoff_id, payload_hash=(l.payload_hash or "")[:12])


def state(db, ctx, doc_type: str, doc_id: int) -> dict:
    d = load_doc(db, ctx, doc_type, doc_id)
    decl = core.declaration_status(db, ctx, doc_type, doc_id, d.calc_hash)
    sos = [so_dict(s) for s in db.query(T.TaxSignoff).filter_by(org_id=ctx.org.id, doc_type=doc_type, doc_id=doc_id).order_by(T.TaxSignoff.id)]
    for s in sos:
        s["counts"] = s["status"] == "valid" and s["id"] in decl["valid"]
    lg = [lodg_dict(l) for l in db.query(T.TaxLodgement).filter_by(org_id=ctx.org.id, doc_type=doc_type, doc_id=doc_id).order_by(T.TaxLodgement.id.desc())]
    return dict(doc_type=doc_type, doc_id=doc_id, doc_status=d.status, title=d.title, policy=decl["policy"], declaration_ok=decl["ok"], requirement=decl["requirement"], agent_signed=decl["agent_signed"],
                signoffs=sos, lodgements=lg, providers=providers(), declarations={k: dict(version=DECL_VERSION, text=v) for k, v in DECLARATIONS.items()},
                has_tax_agent=bool(P.get(db, ctx).has_tax_agent), agent_name=P.get(db, ctx).tax_agent_name, agent_number=P.get(db, ctx).tax_agent_number,
                can_lodge_now=d.status == "approved" and decl["ok"], not_a_dsp=ONBOARDING)


def submit(db, ctx, a: core.Access, doc_type: str, doc_id: int, provider_name: str) -> dict:
    a.require("lodge")
    prov = PROVIDERS.get(provider_name)
    if prov is None:
        raise TaxError(f"provider must be one of {', '.join(PROVIDERS)}")
    if provider_name == "manual":
        raise TaxError("The manual provider is used by recording the receipt on the document (Record lodgement).", 409, "not_applicable")
    d = load_doc(db, ctx, doc_type, doc_id)
    if d.status != "approved":
        raise Conflict(f"Only an approved document can be handed to a provider (status is {d.status}).")
    decl = core.check_declaration(db, ctx, doc_type, doc_id, d.calc_hash)
    if current_hash(db, ctx, d) != d.calc_hash:
        raise Conflict("The figures changed after approval. Return the document to draft, recalculate, approve and sign off again.", "stale")
    ok, why = prov.available()
    if not ok:
        raise Conflict(why or "That provider is not available.", "provider_unavailable")
    payload = build_payload(db, ctx, doc_type, doc_id)
    pack = build_pack(db, ctx, doc_type, doc_id) if provider_name == "agent_pack" else None
    res = prov.submit(payload, d, pack)
    row = T.TaxLodgement(org_id=ctx.org.id, doc_type=doc_type, doc_id=doc_id, provider=provider_name, status=res.status, simulated=bool(res.simulated), signoff_id=(decl["valid"] or [None])[-1],
                         payload_hash=payload_hash(payload), receipt_reference=res.receipt_reference, message=res.message[:500], response=core.plain(res.response), submitted_by=ctx.user_id)
    db.add(row)
    db.flush()
    core.record(db, ctx, f"lodgement.{provider_name}.{res.status}", doc_type, doc_id, f"{DOC_LABEL[doc_type]} via {prov.label}: {res.status}" + (f" ref {res.receipt_reference}" if res.receipt_reference else ""),
                None, dict(lodgement_id=row.id, simulated=bool(res.simulated), payload_hash=row.payload_hash[:12]))
    if prov.real and res.status == "accepted" and res.receipt_reference and not res.simulated:
        body = dict(reference=res.receipt_reference, method="gateway")
        {"bas_statement": B.record_lodged, "tax_return": RT.record_lodged, "fbt_return": F.record_lodged}[doc_type](db, ctx, a, doc_id, body)
    return lodg_dict(row)

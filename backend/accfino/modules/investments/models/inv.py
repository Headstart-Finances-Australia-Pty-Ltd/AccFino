"""
accfino.modules.investments.models.inv
--------------------------------------
Assets, Investments & Wealth tables (prefix inv_). Every row belongs to an organisation (org_id). Money is NUMERIC(18,2); quantities and unit prices NUMERIC(24,8).
Principles: the TRANSACTION is the source of truth. Holdings, parcels (lots), cost base, realised/unrealised gains, income and returns are all CALCULATED from the transactions and prices
by the engine, never stored, so they cannot drift and every figure can be explained back to the rows it came from. Voided transactions stay (audited) but are ignored. A Tax File Number is never stored.
"""
from datetime import datetime

from sqlalchemy import (JSON, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint)

from accfino.shared.db.base import Base
from accfino.shared.db.types import MONEY

QTY = Numeric(24, 8)
_ORG = lambda: Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


SECURITY_KINDS = ("share", "etf", "crypto", "managed_fund", "bond", "term_deposit")
ASSET_CLASSES = ("au_equity", "intl_equity", "listed_property", "fixed_interest", "cash", "crypto", "alternatives", "other")
ACCOUNT_KINDS = ("broker", "exchange", "fund_platform", "bank_term", "other")
CGT_METHODS = ("fifo", "lifo", "hifo")
TXN_TYPES = ("buy", "sell", "dividend", "distribution", "interest", "fee", "split", "bonus", "drp", "return_of_capital", "cost_base_adjustment", "income_in_kind", "transfer_out", "transfer_in")
PROPERTY_TYPES = ("house", "unit", "townhouse", "land", "commercial", "rural", "other")
PROPERTY_USES = ("main_residence", "investment", "holiday", "vacant", "development")
ENTRY_KINDS = ("rent_income", "expense", "capital_improvement", "loan_interest", "capital_works_claimed", "depreciation_claimed")
EXPENSE_CATEGORIES = ("agent_fees", "rates", "water", "insurance", "repairs", "land_tax", "strata", "advertising", "legal", "pest_control", "cleaning", "other")
LIABILITY_KINDS = ("mortgage", "investment_loan", "margin_loan", "personal_loan", "credit_card", "other")
OTHER_ASSET_KINDS = ("vehicle", "collectable", "superannuation", "business_interest", "term_deposit", "other")
VALUATION_OWNERS = ("property", "other_asset", "liability")
DOC_OWNERS = ("account", "security", "transaction", "property", "liability", "other_asset")
HOLDERS = ("individual", "company", "trust", "super")


class InvSettings(Base):
    __tablename__ = "inv_settings"
    org_id = Column(Integer, ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True)
    cgt_method = Column(String(8), nullable=False, default="fifo")
    holder = Column(String(12), nullable=False, default="individual")               # drives the CGT discount: individual/trust 50%, super 33.33%, company none
    ledger_map = Column(JSON)                                                         # account codes used when posting to the ledger
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (CheckConstraint(_in("cgt_method", CGT_METHODS), name="ck_inv_set_method"), CheckConstraint(_in("holder", HOLDERS), name="ck_inv_set_holder"))


class InvAccount(Base):
    """A broker (CHESS/HIN), exchange wallet, fund platform or term-deposit provider holding investments. Parcels are tracked per account."""
    __tablename__ = "inv_accounts"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    name = Column(String(120), nullable=False)
    kind = Column(String(14), nullable=False, default="broker")
    institution = Column(String(120))
    identifier = Column(String(40))                                                   # e.g. HIN ending, wallet label: never a TFN
    holder_note = Column(String(120))                                                 # whose name it is held in (joint / trust / SMSF)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_inv_acc_name"), CheckConstraint(_in("kind", ACCOUNT_KINDS), name="ck_inv_acc_kind"))


class InvSecurity(Base):
    """An instrument: listed share or ETF, crypto token, managed fund, bond or term deposit."""
    __tablename__ = "inv_securities"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    kind = Column(String(14), nullable=False)
    code = Column(String(24), nullable=False)
    name = Column(String(160), nullable=False)
    exchange = Column(String(24))
    isin = Column(String(16))
    asset_class = Column(String(16), nullable=False, default="other")
    sector = Column(String(60))
    country = Column(String(40))
    currency = Column(String(3), nullable=False, default="AUD")
    # funds
    mer_pct = Column(Numeric(7, 4))                                                   # management expense ratio, % p.a.
    amit = Column(Boolean, nullable=False, default=False)
    # bonds / term deposits
    face_value = Column(Numeric(18, 2))
    coupon_rate = Column(Numeric(9, 6))                                               # annual, as a fraction (0.0425)
    coupon_freq = Column(Integer)                                                     # payments per year: 1, 2, 4, 12
    issue_date = Column(Date)
    maturity_date = Column(Date)
    day_count = Column(String(8), default="act/act")
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "kind", "code", name="uq_inv_sec_code"), CheckConstraint(_in("kind", SECURITY_KINDS), name="ck_inv_sec_kind"),
                      CheckConstraint(_in("asset_class", ASSET_CLASSES), name="ck_inv_sec_class"))


class InvTransaction(Base):
    __tablename__ = "inv_transactions"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    account_id = Column(Integer, ForeignKey("inv_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    security_id = Column(Integer, ForeignKey("inv_securities.id", ondelete="RESTRICT"), nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    txn_type = Column(String(22), nullable=False)
    quantity = Column(QTY, nullable=False, default=0)            # units; for split: new-for-old numerator; for bonus: bonus units
    price = Column(QTY)                                          # unit price; for split: the old-for-new denominator
    amount = Column(MONEY, nullable=False, default=0)            # gross AUD: buy cost excl fees / sale proceeds excl fees / cash income / ROC amount
    fees = Column(MONEY, nullable=False, default=0)              # brokerage, exchange or transaction fees (AUD, GST inclusive as paid)
    franked = Column(MONEY, nullable=False, default=0)           # dividends and distributions
    unfranked = Column(MONEY, nullable=False, default=0)
    franking_credits = Column(MONEY, nullable=False, default=0)
    foreign_income = Column(MONEY, nullable=False, default=0)
    foreign_tax_paid = Column(MONEY, nullable=False, default=0)
    cg_discount_part = Column(MONEY, nullable=False, default=0)  # capital gain components of a distribution (grossed-up discount component / other)
    cg_other_part = Column(MONEY, nullable=False, default=0)
    tax_deferred = Column(MONEY, nullable=False, default=0)      # reduces cost base (non-AMIT) : not income
    cost_base_adj = Column(MONEY, nullable=False, default=0)     # AMIT cost base net amount: + increases, - decreases
    withholding_tax = Column(MONEY, nullable=False, default=0)
    lot_ref = Column(Integer)                                    # specific identification: the BUY transaction id being sold from (sells only)
    reference = Column(String(80))                               # broker confirmation, transfer pair id, tx hash
    notes = Column(String(500))
    source = Column(String(12), nullable=False, default="manual")  # manual | import | ledger
    source_key = Column(String(64))                              # idempotency key for imports
    voided = Column(Boolean, nullable=False, default=False)
    void_reason = Column(String(300))
    linked_journal_id = Column(Integer)                          # ledger journal this posted to / was reconciled with
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "source_key", name="uq_inv_txn_source"), CheckConstraint(_in("txn_type", TXN_TYPES), name="ck_inv_txn_type"),
                      CheckConstraint("quantity >= 0 AND fees >= 0", name="ck_inv_txn_pos"), Index("ix_inv_txn_acc_sec", "org_id", "account_id", "security_id", "trade_date"))


class InvPrice(Base):
    __tablename__ = "inv_prices"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    security_id = Column(Integer, ForeignKey("inv_securities.id", ondelete="CASCADE"), nullable=False, index=True)
    price_date = Column(Date, nullable=False)
    price = Column(QTY, nullable=False)
    source = Column(String(12), nullable=False, default="manual")
    __table_args__ = (UniqueConstraint("org_id", "security_id", "price_date", name="uq_inv_price"), CheckConstraint("price >= 0", name="ck_inv_price_pos"))


class InvProperty(Base):
    __tablename__ = "inv_properties"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    name = Column(String(120), nullable=False)
    address = Column(String(200))
    suburb = Column(String(80))
    state = Column(String(3))
    postcode = Column(String(4))
    property_type = Column(String(12), nullable=False, default="house")
    use = Column(String(14), nullable=False, default="investment")
    ownership_pct = Column(Numeric(6, 3), nullable=False, default=100)        # your share (joint tenants / tenants in common)
    contract_date = Column(Date)                                              # the CGT event date for a purchase is the contract date
    settlement_date = Column(Date)
    purchase_price = Column(MONEY, nullable=False, default=0)
    stamp_duty = Column(MONEY, nullable=False, default=0)
    legal_costs = Column(MONEY, nullable=False, default=0)
    other_acq_costs = Column(MONEY, nullable=False, default=0)               # inspections, valuation, borrowing costs treated as cost base
    depreciating_assets_value = Column(MONEY, nullable=False, default=0)     # plant and equipment inside the price: NOT part of the cost base
    construction_cost = Column(MONEY, nullable=False, default=0)             # basis for capital works deductions
    construction_date = Column(Date)
    capital_works_rate = Column(Numeric(5, 4), nullable=False, default=0.025)
    main_residence_from = Column(Date)
    main_residence_until = Column(Date)
    first_income_date = Column(Date)                                         # date first rented (starts the 6-year absence rule clock)
    value_when_first_income = Column(MONEY)                                  # market value then (needed for a partial main residence exemption)
    sale_contract_date = Column(Date)
    sale_price = Column(MONEY)
    selling_costs = Column(MONEY, nullable=False, default=0)
    loan_liability_id = Column(Integer, ForeignKey("inv_liabilities.id", ondelete="SET NULL"))
    notes = Column(String(500))
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_inv_prop_name"), CheckConstraint(_in("property_type", PROPERTY_TYPES), name="ck_inv_prop_type"),
                      CheckConstraint(_in("use", PROPERTY_USES), name="ck_inv_prop_use"), CheckConstraint("ownership_pct > 0 AND ownership_pct <= 100", name="ck_inv_prop_own"))


class InvPropertyEntry(Base):
    __tablename__ = "inv_property_entries"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    property_id = Column(Integer, ForeignKey("inv_properties.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_date = Column(Date, nullable=False, index=True)
    kind = Column(String(24), nullable=False)
    category = Column(String(16))
    amount = Column(MONEY, nullable=False)
    description = Column(String(200))
    reference = Column(String(80))
    source = Column(String(12), nullable=False, default="manual")
    source_key = Column(String(64))
    voided = Column(Boolean, nullable=False, default=False)
    linked_journal_id = Column(Integer)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "source_key", name="uq_inv_pe_source"), CheckConstraint(_in("kind", ENTRY_KINDS), name="ck_inv_pe_kind"), CheckConstraint("amount >= 0", name="ck_inv_pe_pos"))


class InvLiability(Base):
    __tablename__ = "inv_liabilities"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    name = Column(String(120), nullable=False)
    kind = Column(String(16), nullable=False, default="mortgage")
    lender = Column(String(120))
    limit_amount = Column(MONEY)
    interest_rate = Column(Numeric(7, 4))                                    # % p.a.
    ledger_account_id = Column(Integer)                                      # if the balance is already in the ledger, it is read from there (never counted twice)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_inv_liab_name"), CheckConstraint(_in("kind", LIABILITY_KINDS), name="ck_inv_liab_kind"))


class InvOtherAsset(Base):
    __tablename__ = "inv_other_assets"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    name = Column(String(120), nullable=False)
    kind = Column(String(18), nullable=False, default="other")
    notes = Column(String(300))
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_inv_oa_name"), CheckConstraint(_in("kind", OTHER_ASSET_KINDS), name="ck_inv_oa_kind"))


class InvValuation(Base):
    """Dated value of a property, other asset, or the balance of a liability. The latest on or before a date is the value at that date."""
    __tablename__ = "inv_valuations"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    owner_type = Column(String(12), nullable=False)
    owner_id = Column(Integer, nullable=False)
    as_at = Column(Date, nullable=False)
    value = Column(MONEY, nullable=False)
    basis = Column(String(40))                                               # e.g. bank valuation, agent appraisal, statement balance, own estimate
    source = Column(String(12), nullable=False, default="manual")
    created_by = Column(Integer)
    __table_args__ = (UniqueConstraint("org_id", "owner_type", "owner_id", "as_at", name="uq_inv_val"), CheckConstraint(_in("owner_type", VALUATION_OWNERS), name="ck_inv_val_owner"),
                      CheckConstraint("value >= 0", name="ck_inv_val_pos"), Index("ix_inv_val_owner", "org_id", "owner_type", "owner_id", "as_at"))


class InvSnapshot(Base):
    __tablename__ = "inv_networth_snapshots"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    as_at = Column(Date, nullable=False)
    total_assets = Column(MONEY, nullable=False)
    total_liabilities = Column(MONEY, nullable=False)
    net_worth = Column(MONEY, nullable=False)
    detail = Column(JSON)
    source = Column(String(8), nullable=False, default="auto")
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("org_id", "as_at", name="uq_inv_snap"),)


class InvDocument(Base):
    """Supporting record (contract note, AMMA / distribution statement, contract of sale, loan statement...). Stored with a SHA-256 and checked on every download."""
    __tablename__ = "inv_documents"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    owner_type = Column(String(14), nullable=False)
    owner_id = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    file_name = Column(String(200))
    content_type = Column(String(80))
    size = Column(Integer)
    sha256 = Column(String(64))
    data = Column(LargeBinary)
    uploaded_by = Column(Integer)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (CheckConstraint(_in("owner_type", DOC_OWNERS), name="ck_inv_doc_owner"), Index("ix_inv_doc_owner", "org_id", "owner_type", "owner_id"))


class InvAudit(Base):
    __tablename__ = "inv_audit"
    id = Column(Integer, primary_key=True)
    org_id = _ORG()
    seq = Column(Integer, nullable=False)
    at = Column(DateTime, nullable=False)
    user_id = Column(Integer)
    username = Column(String(120))
    action = Column(String(60), nullable=False)
    entity_type = Column(String(40), nullable=False)
    entity_id = Column(String(40))
    summary = Column(String(500))
    before = Column(JSON)
    after = Column(JSON)
    prev_hash = Column(String(64), nullable=False, default="")
    hash = Column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("org_id", "seq", name="uq_inv_audit_seq"), Index("ix_inv_audit_entity", "org_id", "entity_type", "entity_id"))


INV_TABLES = [m.__table__ for m in (InvSettings, InvAccount, InvSecurity, InvTransaction, InvPrice, InvProperty, InvPropertyEntry, InvLiability, InvOtherAsset, InvValuation, InvSnapshot, InvDocument, InvAudit)]

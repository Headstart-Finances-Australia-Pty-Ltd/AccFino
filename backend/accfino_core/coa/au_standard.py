"""
accfino_core.coa.au_standard
----------------------------
Australian standard chart of accounts and GST tax codes, seeded per organisation.

The template keeps every account (same code and name) from the legacy
main_app/data/ChartOfAccounts.csv so existing GL coding on bank transactions
maps 1:1 into the ledger. It adds the balance sheet and control accounts the
legacy COA lacked (AR, AP, GST, PAYG, super, retained earnings, suspense ...).
"""

# code, name, rate, applies_to, bas_labels
# Names deliberately match the legacy gst_category strings used by the classifier.
TAX_CODES = [
    ("OUTPUT",       "GST on Income",       "0.10", "sales",     {"base": ["G1"], "tax": "1A"}),
    ("EXEMPTOUTPUT", "GST Free Income",     "0",    "sales",     {"base": ["G1", "G3"]}),
    ("EXPORT",       "GST on Exports",      "0",    "sales",     {"base": ["G1", "G2"]}),
    ("INPUTTAXEDS",  "Input Taxed Sales",   "0",    "sales",     {"base": ["G1", "G4"]}),
    ("INPUT",        "GST on Expenses",     "0.10", "purchases", {"base": ["G11"], "tax": "1B"}),
    ("EXEMPTEXP",    "GST Free Expenses",   "0",    "purchases", {"base": ["G11", "G14"]}),
    ("CAPEXINPUT",   "GST on Capital",      "0.10", "purchases", {"base": ["G10"], "tax": "1B"}),
    ("EXEMPTCAP",    "GST Free Capital",    "0",    "purchases", {"base": ["G10", "G14"]}),
    ("INPUTTAXEDP",  "Input Taxed Purchases", "0",  "purchases", {"base": ["G11", "G13"]}),
    ("GSTONIMPORTS", "GST on Imports",      "0",    "purchases", {"tax": "1B"}),
    ("BASEXCLUDED",  "BAS Excluded",        "0",    "both",      {}),
]

# code, name, account_type, default tax code name, system_key
ACCOUNTS = [
    # ---------------- Revenue
    ("200", "Services", "revenue", "GST on Income", None),
    ("201", "Product Sales", "revenue", "GST on Income", None),
    ("260", "Other Revenue", "revenue", "GST on Income", None),
    ("270", "Interest Income", "other_income", "GST Free Income", None),
    # ---------------- Direct costs
    ("309", "Project Purchases", "direct_costs", "GST on Expenses", None),
    ("310", "Cost of Goods Sold", "direct_costs", "GST on Expenses", None),
    ("313", "Subcontractors", "direct_costs", "GST on Expenses", None),
    # ---------------- Expenses
    ("311", "Donation", "expense", "GST Free Expenses", None),
    ("401", "Marketing & Advertisement", "expense", "GST on Expenses", None),
    ("402", "Staff recruitment", "expense", "GST on Expenses", None),
    ("403", "Assets Immediate Write off", "expense", "GST on Expenses", None),
    ("404", "Bank Fees", "expense", "GST Free Expenses", None),
    ("405", "Staff Amenities", "expense", "GST on Expenses", None),
    ("406", "Entertainment", "expense", "GST Free Expenses", None),
    ("408", "Cleaning", "expense", "GST on Expenses", None),
    ("411", "Client Gifts", "expense", "GST on Expenses", None),
    ("412", "Consulting & Accounting", "expense", "GST on Expenses", None),
    ("416", "Depreciation", "expense", "BAS Excluded", None),
    ("418", "Filing Fee", "expense", "GST Free Expenses", None),
    ("420", "Formation Costs Write Off", "expense", "BAS Excluded", None),
    ("421", "Client Sales Meeting", "expense", "GST on Expenses", None),
    ("422", "Staff Training", "expense", "GST on Expenses", None),
    ("423", "Business Development", "expense", "GST on Expenses", None),
    ("425", "Freight & Courier", "expense", "GST on Expenses", None),
    ("433", "Insurance", "expense", "GST on Expenses", None),
    ("437", "Interest Expense", "expense", "GST Free Expenses", None),
    ("441", "Legal expenses", "expense", "GST on Expenses", None),
    ("445", "Light, Power, Heating", "expense", "GST on Expenses", None),
    ("447", "Materials & Consumables", "expense", "GST on Expenses", None),
    ("449", "MV - Fuel", "expense", "GST on Expenses", None),
    ("450", "MV - Registration & Insurance", "expense", "GST on Expenses", None),
    ("451", "MV - Repair & Maintenance", "expense", "GST on Expenses", None),
    ("453", "Office Expenses", "expense", "GST on Expenses", None),
    ("457", "Parking & Tolls", "expense", "GST on Expenses", None),
    ("461", "Printing & Stationery", "expense", "GST on Expenses", None),
    ("469", "Rent", "expense", "GST on Expenses", None),
    ("473", "Repairs and Maintenance", "expense", "GST on Expenses", None),
    ("477", "Wages and Salaries", "expense", "BAS Excluded", None),
    ("478", "Superannuation", "expense", "BAS Excluded", None),
    ("485", "Subscriptions", "expense", "GST on Expenses", None),
    ("489", "Telephone & Internet", "expense", "GST on Expenses", None),
    ("493", "Travel - National", "expense", "GST on Expenses", None),
    ("494", "Travel - International", "expense", "GST Free Expenses", None),
    ("496", "Uniforms", "expense", "GST on Expenses", None),
    ("499", "General Expenses", "expense", "GST on Expenses", None),
    ("505", "Income Tax Expense", "other_expense", "BAS Excluded", None),
    # ---------------- Current assets
    ("610", "Accounts Receivable", "current_asset", "BAS Excluded", "ar_control"),
    ("611", "Less Provision for Doubtful Debts", "current_asset", "BAS Excluded", None),
    ("615", "Undeposited Funds", "current_asset", "BAS Excluded", "undeposited_funds"),
    ("620", "Prepayments", "current_asset", "BAS Excluded", None),
    ("630", "Inventory", "inventory", "BAS Excluded", "inventory"),
    ("640", "Loans to Directors / Shareholders", "current_asset", "BAS Excluded", None),
    # ---------------- Fixed assets
    ("710", "Office Equipment", "fixed_asset", "GST on Capital", None),
    ("711", "Less Accumulated Depreciation on Office Equipment", "fixed_asset", "BAS Excluded", None),
    ("720", "Computer Equipment", "fixed_asset", "GST on Capital", None),
    ("721", "Less Accumulated Depreciation on Computer Equipment", "fixed_asset", "BAS Excluded", None),
    ("730", "Motor Vehicles", "fixed_asset", "GST on Capital", None),
    ("731", "Less Accumulated Depreciation on Motor Vehicles", "fixed_asset", "BAS Excluded", None),
    # ---------------- Current liabilities
    ("800", "Accounts Payable", "current_liability", "BAS Excluded", "ap_control"),
    ("801", "Unpaid Expense Claims", "current_liability", "BAS Excluded", "expense_claims"),
    ("804", "Wages Payable - Payroll", "current_liability", "BAS Excluded", "wages_payable"),
    ("820", "GST", "current_liability", "BAS Excluded", "gst"),
    ("825", "PAYG Withholdings Payable", "current_liability", "BAS Excluded", "payg_withholding"),
    ("826", "Superannuation Payable", "current_liability", "BAS Excluded", "super_payable"),
    ("830", "Income Tax Payable", "current_liability", "BAS Excluded", "income_tax_payable"),
    ("840", "Historical Adjustment", "current_liability", "BAS Excluded", "historical_adjustment"),
    ("850", "Suspense", "current_liability", "BAS Excluded", "suspense"),
    ("855", "Transfers Clearing", "current_liability", "BAS Excluded", "transfer_clearing"),
    ("860", "Rounding", "current_liability", "BAS Excluded", "rounding"),
    # ---------------- Non-current liabilities
    ("900", "Business Loan", "non_current_liability", "BAS Excluded", None),
    ("910", "Loans from Directors / Shareholders", "non_current_liability", "BAS Excluded", None),
    # ---------------- Equity
    ("880", "Owner A Drawings", "equity", "BAS Excluded", None),
    ("881", "Owner A Funds Introduced", "equity", "BAS Excluded", None),
    ("960", "Retained Earnings", "equity", "BAS Excluded", "retained_earnings"),
    ("970", "Owner A Share Capital", "equity", "BAS Excluded", None),
    ("981", "Dividends", "equity", "BAS Excluded", None),
]

# Legacy chart_of_accounts.type -> ledger account_type (for accounts users added themselves)
LEGACY_TYPE_MAP = {
    "revenue": "revenue",
    "direct costs": "direct_costs",
    "expense": "expense",
    "fixed asset": "fixed_asset",
    "inventory": "inventory",
    "equity": "equity",
    "gst": "current_liability",
    "current asset": "current_asset",
    "current liability": "current_liability",
    "bank": "bank",
    "other income": "other_income",
}

"""
Smart Lending — Transaction Classifier  (v2)

Implements the exact classification logic from the original Saar/Expense-v10-4.py:

    expenseClass() — for each transaction description:
      1. If keyword length < 5: match as "keyword " or "keyword, " or " keyword"
         (adds padding to avoid false substring matches on short words)
      2. Else: match as keyword.upper() in description.upper()
      3. First match wins (keywords sorted by weight/confidence descending)
      4. No match → category='Others', exp_type='D', in_or_out='I'

Classification DB:
  - 2,433 entries from Saar SQL transaction_masterclassification table
  - 43 keywords from the original Expense-Class.csv
  - Additional AU-specific keywords (banks, utilities, insurance, etc.)
  Total: ~2,458 unique keywords across 43 categories

Categories from original Saar system:
  Food & Groceries, Recreation, Clothing & Personal, Goods, Rent, Services Charge,
  Active Life, Air Travel, Childcare, Health & Medical, Medicines and Supplements,
  Fuel, Gambling, Home Services, Income, Transport, Public Services & Government,
  Education, General Insurance, Hotel & Travel, Fund Transfer, Internet, Phone Bill,
  Health Insurance, Beauty & Spas, Loans, Electricity, Maintenance, Gas Bills, Pets,
  Life Insurance, TV Subscription, Car Parking, Council Rates, Cash Out,
  Religious Services, Holiday, Toll Fee, Water Bills, Membership Fee, Real Estate

Fields per entry:
  keyword   — string to match (case-insensitive substring)
  category  — expense category
  exp_type  — 'M' (Mandatory) or 'D' (Discretionary)
  in_or_out — 'I' (money out/expense) or 'O' (money in/income)
  weight    — confidence score (higher = try first)
"""
import json
import os
from typing import List, Dict, Optional

# ── Category → HEM group mapping (for metrics engine) ─────────────────────────
HEM_GROUP_MAP = {
    'Food & Groceries':             'food_groceries',
    'Goods':                        'goods_household',
    'Rent':                         'housing',
    'Home Services':                'housing',
    'Maintenance':                  'housing',
    'Council Rates':                'housing',
    'Real Estate':                  'investment',
    'Electricity':                  'utilities',
    'Gas Bills':                    'utilities',
    'Water Bills':                  'utilities',
    'Phone Bill':                   'utilities',
    'Internet':                     'utilities',
    'Fuel':                         'transport',
    'Transport':                    'transport',
    'Car Parking':                  'transport',
    'Toll Fee':                     'transport',
    'Air Travel':                   'travel',
    'Hotel & Travel':               'travel',
    'Holiday':                      'travel',
    'Health & Medical':             'health_medical',
    'Medicines and Supplements':    'health_medical',
    'Health Insurance':             'insurance',
    'Life Insurance':               'insurance',
    'General Insurance':            'insurance',
    'Childcare':                    'childcare_education',
    'Education':                    'childcare_education',
    'Recreation':                   'recreation_entertainment',
    'Active Life':                  'recreation_entertainment',
    'Entertainment':                'recreation_entertainment',
    'Clothing & Personal':          'clothing_personal',
    'Beauty & Spas':                'personal_care',
    'Pets':                         'other',
    'Gambling':                     'gambling',
    'Loans':                        'loans_debt',
    'Interest Payment':             'loans_debt',
    'Credit Card Payment':          'loans_debt',
    'Income':                       'income',
    'Fund Transfer':                'transfers',
    'Cash Out':                     'cash',
    'Services Charge':              'services',
    'TV Subscription':              'subscriptions',
    'Membership Fee':               'subscriptions',
    'Public Services & Government': 'government',
    'Religious Services':           'other',
    'Donation':                     'other',
    'Others':                       'other',
}

# ── Load classification DB ─────────────────────────────────────────────────────
_DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "lending_classifications.json"
)

_DB: List[Dict] = []

def _load_db():
    global _DB
    if _DB:
        return
    try:
        raw = json.load(open(_DATA_PATH, encoding='utf-8'))
        # Pre-build match variants exactly as in the original expenseClass():
        # "if len(keyword) < 5: use keyword+'  ' or keyword+', ' or ' '+keyword"
        for entry in raw:
            kw = entry['keyword'].strip().upper()
            entry['_kw'] = kw
            if len(kw) < 5:
                entry['_variants'] = [kw + ' ', kw + ', ', ' ' + kw]
            else:
                entry['_variants'] = [kw]
        _DB = raw
    except Exception as e:
        _DB = []


# ── Core classification (exact Saar expenseClass() logic) ─────────────────────
def classify_transaction(description: str) -> Dict:
    """
    Classify a single transaction description using the original Saar matching logic.
    Returns {category, exp_type, in_or_out, hem_group, is_income, matched_keyword, confidence}
    """
    _load_db()
    desc_upper = description.strip().upper()

    if not desc_upper:
        return _unknown()

    for entry in _DB:
        # Original logic: check all variants (space-padded for short keywords)
        for variant in entry['_variants']:
            if variant in desc_upper:
                cat = entry['category']
                md  = entry['exp_type']    # M or D
                io  = entry['in_or_out']   # I (out/expense) or O (in/income)
                return {
                    'category':        cat,
                    'exp_type':        md,
                    'in_or_out':       io,
                    'hem_group':       HEM_GROUP_MAP.get(cat, 'other'),
                    'is_income':       (cat == 'Income' or io == 'O'),
                    'matched_keyword': entry['keyword'],
                    'confidence':      min(0.99, 0.5 + entry.get('weight', 5) / 50),
                }

    return _unknown()


def _unknown() -> Dict:
    return {
        'category':        'Others',
        'exp_type':        'D',
        'in_or_out':       'I',
        'hem_group':       'other',
        'is_income':       False,
        'matched_keyword': None,
        'confidence':      0.1,
    }


# ── Batch classification ───────────────────────────────────────────────────────
def classify_transactions(transactions: List[Dict]) -> List[Dict]:
    """
    Classify a list of transaction dicts.
    Input fields: date, description, debit, credit
    Preserved fields: balance, source_file, bank, _source_file, _bank
    """
    _load_db()
    results = []
    for txn in transactions:
        desc     = txn.get('description', '')
        debit    = float(txn.get('debit')  or 0)
        credit   = float(txn.get('credit') or 0)
        is_debit = debit > 0
        amount   = debit if is_debit else credit

        clf = classify_transaction(desc)

        results.append({
            # Original transaction fields
            'date':          txn.get('date', ''),
            'description':   desc,
            'debit':         debit,
            'credit':        credit,
            'balance':       txn.get('balance'),          # from bank parser
            'source_file':   txn.get('_source_file', txn.get('source_file', '')),
            'bank':          txn.get('_bank',         txn.get('bank', '')),
            # Classification (Saar fields)
            'category':      clf['category'],
            'exp_type':      clf['exp_type'],             # M or D
            'in_or_out':     clf['in_or_out'],            # I or O
            'hem_group':     clf['hem_group'],
            'is_income':     clf['is_income'],
            'is_debit':      is_debit,
            'amount':        amount,
            'matched_keyword': clf['matched_keyword'],
            'confidence':    clf['confidence'],
        })
    return results


# ── Statistics helper (for metrics engine) ────────────────────────────────────
def get_classification_stats(classified: List[Dict]) -> Dict:
    """Return summary stats used by both the results panel and metrics engine."""
    total      = len(classified)
    classified_n = sum(1 for t in classified if t['category'] != 'Others')
    income     = [t for t in classified if t['is_income']]
    expenses   = [t for t in classified if not t['is_income']]
    mandatory  = [t for t in expenses if t['exp_type'] == 'M']
    discretionary = [t for t in expenses if t['exp_type'] == 'D']

    return {
        'total':              total,
        'classified':         classified_n,
        'unclassified':       total - classified_n,
        'classification_pct': round(classified_n / max(total, 1) * 100, 1),
        'income_count':       len(income),
        'expense_count':      len(expenses),
        'mandatory_count':    len(mandatory),
        'discretionary_count': len(discretionary),
    }

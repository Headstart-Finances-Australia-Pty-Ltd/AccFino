"""Single source of truth for the A1 conversion of legacy floating-point columns to exact NUMERIC.
Used by the ORM edit (fresh databases) and by money_migration (existing databases)."""

MONEY, UNIT, QTY, PCT, HOURS, FX, INT = "MoneyF", "UnitF", "QtyF", "PctF", "HoursF", "FxF", "Integer"

# type name -> (postgres type, scale)
PG = {MONEY: ("NUMERIC(18,2)", 2), UNIT: ("NUMERIC(18,4)", 4), QTY: ("NUMERIC(18,4)", 4), PCT: ("NUMERIC(9,4)", 4),
      HOURS: ("NUMERIC(9,2)", 2), FX: ("NUMERIC(18,8)", 8), INT: ("INTEGER", 0)}

PLAN = {
    "accounting_documents": {"subtotal": MONEY, "tax_percent": PCT, "tax_amount": MONEY, "discount_amount": MONEY, "total_amount": MONEY},
    "accounting_line_items": {"quantity": QTY, "unit_price": UNIT, "line_total": MONEY},
    "invoices": {"subtotal": MONEY, "tax_amount": MONEY, "tax_percent": PCT, "discount_amount": MONEY, "total_amount": MONEY},
    "invoice_items": {"quantity": QTY, "unit_price": UNIT, "line_total": MONEY},
    "account_balances": {"balance": MONEY},
    "rdr_rules": {"debit_gt": MONEY, "credit_gt": MONEY},
    "transactions": {"debit": MONEY, "credit": MONEY, "bank_balance": MONEY, "amount_original": MONEY, "exchange_rate": FX,
                     "gst": MONEY, "loan_principal": MONEY, "loan_interest": MONEY, "loan_interest_rate": PCT},
    "payroll_employees": {"annual_salary": MONEY, "hourly_rate": UNIT},
    "payroll_timesheets": {c: HOURS for c in ("ordinary_hours", "overtime_hours_1_5x", "overtime_hours_2x", "public_holiday_hours",
                                              "annual_leave_hours", "sick_leave_hours", "long_service_leave_hours", "unpaid_leave_hours")},
    "payroll_runs": {"total_gross": MONEY, "total_tax": MONEY, "total_net": MONEY, "total_super": MONEY, "employee_count": INT},
    "payslips": {**{c: HOURS for c in ("ordinary_hours", "overtime_hours_1_5x", "overtime_hours_2x", "annual_leave_hours", "sick_leave_hours")},
                 **{c: MONEY for c in ("annual_salary", "ordinary_pay", "overtime_pay_1_5x", "overtime_pay_2x", "annual_leave_pay", "sick_leave_pay",
                                       "gross_earnings", "payg_tax", "medicare_levy", "total_tax", "net_pay", "super_guarantee",
                                       "ytd_gross", "ytd_tax", "ytd_super")}, "hourly_rate": UNIT},
    "stp_submissions": {"employee_count": INT, "total_gross": MONEY, "total_super": MONEY, "total_tax": MONEY},
}

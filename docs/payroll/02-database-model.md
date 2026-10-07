# Payroll database model

_Generated from the models by `generate_reference.py`. Every table carries `org_id` (organisation scope) unless noted. Money is NUMERIC(18,2); hours NUMERIC(12,4)._

**29 tables.** Legacy tables (`payroll_employees`, `payroll_runs`, `payroll_timesheets`, `payslips`, `stp_submissions`) are left in place, unused, so a rollback loses nothing.

## `pay_audit`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `occurred_at` | DATETIME | required |
| `user_id` | INTEGER |  |
| `username` | VARCHAR(255) |  |
| `action` | VARCHAR(60) | required |
| `entity_type` | VARCHAR(40) | required |
| `entity_id` | VARCHAR(40) |  |
| `entity_label` | VARCHAR(200) |  |
| `summary` | VARCHAR(500) |  |
| `before` | JSON |  |
| `after` | JSON |  |

Indexes: `ix_pay_audit_occurred_at`, `ix_pay_audit_entity`, `ix_pay_audit_org_id`, `ix_pay_audit_action`

## `pay_calendars`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `name` | VARCHAR(100) | required |
| `frequency` | VARCHAR(12) | required |
| `anchor_start` | DATE | required |
| `pay_offset_days` | INTEGER | required |
| `is_default` | BOOLEAN | required |
| `is_active` | BOOLEAN | required |

Constraints: `uq_pay_cal_name`, `ck_pay_cal_freq`

Indexes: `ix_pay_calendars_org_id`

## `pay_departments`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `code` | VARCHAR(20) | required |
| `name` | VARCHAR(100) | required |
| `is_active` | BOOLEAN | required |

Constraints: `uq_pay_dept_code`

Indexes: `ix_pay_departments_org_id`

## `pay_employee_bank`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `employee_id` | INTEGER | required, FK -> pay_employees.id (CASCADE) |
| `account_name` | VARCHAR(100) | required |
| `bsb` | VARCHAR(7) | required |
| `account_enc` | TEXT | required, **sealed (encrypted) at rest** |
| `account_last4` | VARCHAR(4) | required |
| `allocation_type` | VARCHAR(10) | required |
| `allocation_value` | NUMERIC(18, 2) | required |
| `priority` | INTEGER | required |
| `reference` | VARCHAR(18) |  |
| `is_active` | BOOLEAN | required |

Constraints: `ck_pay_bank_alloc`

Indexes: `ix_pay_employee_bank_org_id`, `ix_pay_employee_bank_employee_id`

## `pay_employee_items`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `employee_id` | INTEGER | required, FK -> pay_employees.id (CASCADE) |
| `pay_item_id` | INTEGER | required, FK -> pay_items.id (RESTRICT) |
| `amount` | NUMERIC(18, 2) |  |
| `rate` | NUMERIC(18, 4) |  |
| `hours` | NUMERIC(12, 4) |  |
| `effective_from` | DATE |  |
| `effective_to` | DATE |  |
| `note` | VARCHAR(200) |  |
| `is_active` | BOOLEAN | required |

Indexes: `ix_pay_employee_items_employee_id`, `ix_pay_employee_items_org_id`

## `pay_employee_super`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `employee_id` | INTEGER | required, FK -> pay_employees.id (CASCADE) |
| `fund_id` | INTEGER | required, FK -> pay_super_funds.id (RESTRICT) |
| `member_number` | VARCHAR(40) |  |
| `allocation_pct` | NUMERIC(6, 2) | required |
| `is_default_fund` | BOOLEAN | required |
| `choice_form_date` | DATE |  |
| `effective_from` | DATE |  |
| `is_active` | BOOLEAN | required |

Indexes: `ix_pay_employee_super_employee_id`, `ix_pay_employee_super_org_id`

## `pay_employee_tax`

| Column | Type | Notes |
|---|---|---|
| `employee_id` | INTEGER | PK, FK -> pay_employees.id (CASCADE) |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `tfn_enc` | TEXT | **sealed (encrypted) at rest** |
| `tfn_last3` | VARCHAR(3) |  |
| `tfn_status` | VARCHAR(12) | required |
| `residency` | VARCHAR(20) | required |
| `claims_tft` | BOOLEAN | required |
| `has_study_loan` | BOOLEAN | required |
| `study_loan_type` | VARCHAR(20) |  |
| `medicare_variation` | VARCHAR(8) | required |
| `tax_offset_annual` | NUMERIC(18, 2) | required |
| `variation_pct` | NUMERIC(6, 2) |  |
| `extra_withholding` | NUMERIC(18, 2) | required |
| `declaration_date` | DATE |  |
| `ytd_opening` | JSON |  |

Constraints: `ck_pay_tax_tfn`, `ck_pay_tax_med`, `ck_pay_tax_res`

Indexes: `ix_pay_employee_tax_org_id`

## `pay_employees`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `user_id` | INTEGER | FK -> users.id (SET NULL) |
| `employee_number` | VARCHAR(30) | required |
| `first_name` | VARCHAR(100) | required |
| `middle_name` | VARCHAR(100) |  |
| `last_name` | VARCHAR(100) | required |
| `preferred_name` | VARCHAR(100) |  |
| `date_of_birth` | DATE |  |
| `email` | VARCHAR(255) |  |
| `phone` | VARCHAR(40) |  |
| `address_line1` | VARCHAR(200) |  |
| `address_line2` | VARCHAR(200) |  |
| `suburb` | VARCHAR(100) |  |
| `state` | VARCHAR(3) |  |
| `postcode` | VARCHAR(4) |  |
| `start_date` | DATE | required |
| `end_date` | DATE |  |
| `termination_reason` | VARCHAR(200) |  |
| `status` | VARCHAR(12) | required |
| `employment_type` | VARCHAR(12) | required |
| `position` | VARCHAR(150) |  |
| `department_id` | INTEGER | FK -> pay_departments.id (SET NULL) |
| `location_id` | INTEGER | FK -> pay_locations.id (SET NULL) |
| `manager_id` | INTEGER | FK -> pay_employees.id (SET NULL) |
| `calendar_id` | INTEGER | FK -> pay_calendars.id (SET NULL) |
| `pay_frequency` | VARCHAR(12) | required |
| `pay_basis` | VARCHAR(10) | required |
| `annual_salary` | NUMERIC(18, 2) |  |
| `hourly_rate` | NUMERIC(18, 4) |  |
| `hours_per_week` | NUMERIC(6, 2) | required |
| `work_pattern` | JSON |  |
| `pay_standard_hours` | BOOLEAN | required |
| `is_demo` | BOOLEAN | required |
| `created_at` | DATETIME |  |
| `updated_at` | DATETIME |  |

Constraints: `ck_pay_emp_basis`, `uq_pay_emp_number`, `ck_pay_emp_type`, `ck_pay_emp_freq`, `ck_pay_emp_status`

Indexes: `ix_pay_employees_manager_id`, `ix_pay_employees_user_id`, `ix_pay_employees_org_id`, `ix_pay_emp_org_status`

## `pay_items`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `code` | VARCHAR(20) | required |
| `name` | VARCHAR(100) | required |
| `kind` | VARCHAR(30) | required |
| `description` | VARCHAR(300) |  |
| `calc_method` | VARCHAR(20) | required |
| `rate` | NUMERIC(18, 4) |  |
| `multiplier` | NUMERIC(9, 4) | required |
| `default_amount` | NUMERIC(18, 2) |  |
| `percent` | NUMERIC(9, 4) |  |
| `taxable` | BOOLEAN | required |
| `payg_treatment` | VARCHAR(20) | required |
| `super_treatment` | VARCHAR(10) | required |
| `reportable_fringe` | BOOLEAN | required |
| `expense_account_id` | INTEGER | FK -> ledger_accounts.id (SET NULL) |
| `leave_type_id` | INTEGER |  |
| `is_system` | BOOLEAN | required |
| `is_default` | BOOLEAN | required |
| `is_active` | BOOLEAN | required |
| `sort` | INTEGER | required |

Constraints: `ck_pay_item_kind`, `uq_pay_item_code`

Indexes: `ix_pay_items_org_id`

## `pay_journal_lines`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `pay_journal_id` | INTEGER | required, FK -> pay_journals.id (CASCADE) |
| `component` | VARCHAR(30) | required |
| `account_id` | INTEGER | required |
| `account_code` | VARCHAR(20) |  |
| `account_name` | VARCHAR(200) |  |
| `employee_id` | INTEGER |  |
| `run_employee_id` | INTEGER |  |
| `pay_item_id` | INTEGER |  |
| `txn_ref` | VARCHAR(60) |  |
| `debit` | NUMERIC(18, 2) | required |
| `credit` | NUMERIC(18, 2) | required |
| `description` | VARCHAR(300) |  |

Indexes: `ix_pay_journal_lines_pay_journal_id`, `ix_pay_journal_lines_org_id`, `ix_pay_journal_lines_employee_id`

## `pay_journals`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `run_id` | INTEGER | required, FK -> pay_runs.id (RESTRICT) |
| `ledger_journal_id` | INTEGER | required |
| `reversal_journal_id` | INTEGER |  |
| `status` | VARCHAR(10) | required |
| `total_debit` | NUMERIC(18, 2) | required |
| `total_credit` | NUMERIC(18, 2) | required |
| `posted_at` | DATETIME |  |
| `posted_by` | INTEGER |  |

Indexes: `ix_pay_journals_org_id`

## `pay_leave_requests`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `employee_id` | INTEGER | required, FK -> pay_employees.id (CASCADE) |
| `leave_type_id` | INTEGER | required, FK -> pay_leave_types.id (RESTRICT) |
| `start_date` | DATE | required |
| `end_date` | DATE | required |
| `hours` | NUMERIC(12, 4) | required |
| `reason` | VARCHAR(300) |  |
| `status` | VARCHAR(12) | required |
| `requested_by` | INTEGER |  |
| `decided_by` | INTEGER |  |
| `decided_at` | DATETIME |  |
| `decision_note` | VARCHAR(300) |  |
| `paid_run_id` | INTEGER | FK -> pay_runs.id (SET NULL) |
| `created_at` | DATETIME |  |

Constraints: `ck_pay_leave_status`

Indexes: `ix_pay_leave_requests_employee_id`, `ix_pay_leave_requests_org_id`, `ix_pay_leave_status`

## `pay_leave_txns`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `employee_id` | INTEGER | required, FK -> pay_employees.id (CASCADE) |
| `leave_type_id` | INTEGER | required, FK -> pay_leave_types.id (RESTRICT) |
| `txn_date` | DATE | required |
| `txn_type` | VARCHAR(12) | required |
| `hours` | NUMERIC(12, 4) | required |
| `pay_run_id` | INTEGER | FK -> pay_runs.id (SET NULL) |
| `leave_request_id` | INTEGER | FK -> pay_leave_requests.id (SET NULL) |
| `note` | VARCHAR(300) |  |
| `created_by` | INTEGER |  |
| `created_at` | DATETIME |  |

Constraints: `ck_pay_leave_txn_type`

Indexes: `ix_pay_leave_txns_org_id`, `ix_pay_leave_txn_bal`

## `pay_leave_types`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `code` | VARCHAR(20) | required |
| `name` | VARCHAR(100) | required |
| `category` | VARCHAR(20) | required |
| `is_paid` | BOOLEAN | required |
| `accrual_method` | VARCHAR(20) | required |
| `accrual_annual_hours` | NUMERIC(12, 4) | required |
| `accrue_on_paid_leave` | BOOLEAN | required |
| `applies_to` | JSON |  |
| `loading_pct` | NUMERIC(6, 2) | required |
| `max_balance` | NUMERIC(12, 4) |  |
| `min_service_years` | NUMERIC(5, 2) | required |
| `allow_negative` | BOOLEAN | required |
| `is_active` | BOOLEAN | required |

Constraints: `uq_pay_leave_code`

Indexes: `ix_pay_leave_types_org_id`

## `pay_locations`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `code` | VARCHAR(20) | required |
| `name` | VARCHAR(100) | required |
| `state` | VARCHAR(3) |  |
| `is_active` | BOOLEAN | required |

Constraints: `uq_pay_loc_code`

Indexes: `ix_pay_locations_org_id`

## `pay_payment_items`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `payment_id` | INTEGER | required, FK -> pay_payments.id (CASCADE) |
| `run_employee_id` | INTEGER | required, FK -> pay_run_employees.id (RESTRICT) |
| `employee_id` | INTEGER | required |
| `bank_id` | INTEGER | FK -> pay_employee_bank.id (SET NULL) |
| `account_name` | VARCHAR(100) |  |
| `bsb` | VARCHAR(7) |  |
| `account_last4` | VARCHAR(4) |  |
| `amount` | NUMERIC(18, 2) | required |
| `reference` | VARCHAR(18) |  |
| `status` | VARCHAR(10) | required |
| `paid_at` | DATETIME |  |
| `failure_reason` | VARCHAR(200) |  |
| `reconciliation` | VARCHAR(12) | required |
| `reconciled_at` | DATETIME |  |
| `reconciled_by` | INTEGER |  |

Constraints: `ck_pay_pi_status`

Indexes: `ix_pay_payment_items_payment_id`, `ix_pay_payment_items_org_id`, `ix_pay_payment_items_employee_id`

## `pay_payments`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `run_id` | INTEGER | required, FK -> pay_runs.id (RESTRICT) |
| `batch_ref` | VARCHAR(40) | required |
| `status` | VARCHAR(12) | required |
| `method` | VARCHAR(10) | required |
| `payment_date` | DATE | required |
| `total` | NUMERIC(18, 2) | required |
| `item_count` | INTEGER | required |
| `created_by` | INTEGER |  |
| `created_at` | DATETIME |  |
| `completed_at` | DATETIME |  |
| `completed_by` | INTEGER |  |
| `journal_id` | INTEGER |  |
| `cancel_reason` | VARCHAR(300) |  |

Constraints: `uq_pay_batch`, `ck_pay_payment_status`

Indexes: `ix_pay_payments_org_id`, `ix_pay_payments_run_id`, `uq_pay_payment_live` (unique, partial)

## `pay_payslips`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `run_id` | INTEGER | required, FK -> pay_runs.id (CASCADE) |
| `run_employee_id` | INTEGER | required, FK -> pay_run_employees.id (CASCADE) |
| `employee_id` | INTEGER | required |
| `payslip_no` | VARCHAR(40) | required |
| `pay_date` | DATE | required |
| `snapshot` | JSON | required |
| `generated_at` | DATETIME |  |
| `generated_by` | INTEGER |  |

Constraints: `uq_pay_payslip_no`

Indexes: `ix_pay_payslips_employee_id`, `ix_pay_payslips_run_id`, `ix_pay_payslips_org_id`

## `pay_run_employees`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `run_id` | INTEGER | required, FK -> pay_runs.id (CASCADE) |
| `employee_id` | INTEGER | required, FK -> pay_employees.id (RESTRICT) |
| `employee_number` | VARCHAR(30) |  |
| `employee_name` | VARCHAR(220) |  |
| `department_id` | INTEGER |  |
| `status` | VARCHAR(10) | required |
| `exclusion_reason` | VARCHAR(300) |  |
| `pay_basis` | VARCHAR(10) |  |
| `rate_snapshot` | NUMERIC(18, 2) |  |
| `tax_scale` | VARCHAR(2) |  |
| `ordinary_hours` | NUMERIC(12, 4) | required |
| `overtime_hours` | NUMERIC(12, 4) | required |
| `leave_hours` | NUMERIC(12, 4) | required |
| `gross` | NUMERIC(18, 2) | required |
| `taxable` | NUMERIC(18, 2) | required |
| `payg` | NUMERIC(18, 2) | required |
| `study_loan` | NUMERIC(18, 2) | required |
| `pretax_deductions` | NUMERIC(18, 2) | required |
| `posttax_deductions` | NUMERIC(18, 2) | required |
| `sacrifice_super` | NUMERIC(18, 2) | required |
| `reimbursements` | NUMERIC(18, 2) | required |
| `net` | NUMERIC(18, 2) | required |
| `qualifying_earnings` | NUMERIC(18, 2) | required |
| `etp_taxable` | NUMERIC(18, 2) | required |
| `super_guarantee` | NUMERIC(18, 2) | required |
| `super_additional` | NUMERIC(18, 2) | required |
| `super_total` | NUMERIC(18, 2) | required |
| `employer_cost` | NUMERIC(18, 2) | required |
| `ytd` | JSON |  |
| `accruals` | JSON |  |
| `errors` | JSON |  |
| `warnings` | JSON |  |
| `inputs_hash` | VARCHAR(64) |  |
| `manual_note` | VARCHAR(300) |  |

Constraints: `uq_pay_run_emp`, `ck_pay_re_status`

Indexes: `ix_pay_run_employees_run_id`, `ix_pay_run_employees_org_id`, `ix_pay_run_employees_employee_id`

## `pay_run_inputs`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `run_id` | INTEGER | required, FK -> pay_runs.id (CASCADE) |
| `employee_id` | INTEGER | required, FK -> pay_employees.id (CASCADE) |
| `pay_item_id` | INTEGER | required, FK -> pay_items.id (RESTRICT) |
| `hours` | NUMERIC(12, 4) |  |
| `rate` | NUMERIC(18, 4) |  |
| `amount` | NUMERIC(18, 2) |  |
| `periods` | INTEGER |  |
| `leave_pre1993` | BOOLEAN | required |
| `genuine_redundancy` | BOOLEAN | required |
| `note` | VARCHAR(300) |  |
| `created_by` | INTEGER |  |

Indexes: `ix_pay_run_inputs_run_id`, `ix_pay_run_inputs_org_id`

## `pay_run_lines`

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `run_id` | INTEGER | required, FK -> pay_runs.id (CASCADE) |
| `run_employee_id` | INTEGER | required, FK -> pay_run_employees.id (CASCADE) |
| `employee_id` | INTEGER | required |
| `line_no` | INTEGER | required |
| `txn_ref` | VARCHAR(60) | required |
| `pay_item_id` | INTEGER |  |
| `code` | VARCHAR(20) | required |
| `name` | VARCHAR(100) | required |
| `kind` | VARCHAR(30) | required |
| `hours` | NUMERIC(12, 4) |  |
| `rate` | NUMERIC(18, 4) |  |
| `amount` | NUMERIC(18, 2) | required |
| `taxable` | BOOLEAN | required |
| `payg_treatment` | VARCHAR(20) |  |
| `super_treatment` | VARCHAR(10) |  |
| `leave_type_id` | INTEGER |  |
| `source` | VARCHAR(60) |  |
| `note` | VARCHAR(300) |  |

Constraints: `uq_pay_line_ref`

Indexes: `ix_pay_run_lines_run_employee_id`, `ix_pay_run_lines_employee_id`, `ix_pay_run_lines_run_id`, `ix_pay_run_lines_org_id`

## `pay_runs`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `run_no` | VARCHAR(30) | required |
| `name` | VARCHAR(150) |  |
| `run_type` | VARCHAR(12) | required |
| `calendar_id` | INTEGER | FK -> pay_calendars.id (SET NULL) |
| `frequency` | VARCHAR(12) | required |
| `period_start` | DATE | required |
| `period_end` | DATE | required |
| `pay_date` | DATE | required |
| `status` | VARCHAR(12) | required |
| `rule_set` | VARCHAR(20) |  |
| `employee_count` | INTEGER | required |
| `total_gross` | NUMERIC(18, 2) | required |
| `total_taxable` | NUMERIC(18, 2) | required |
| `total_payg` | NUMERIC(18, 2) | required |
| `total_study_loan` | NUMERIC(18, 2) | required |
| `total_deductions` | NUMERIC(18, 2) | required |
| `total_sacrifice` | NUMERIC(18, 2) | required |
| `total_reimbursements` | NUMERIC(18, 2) | required |
| `total_net` | NUMERIC(18, 2) | required |
| `total_super` | NUMERIC(18, 2) | required |
| `total_employer_cost` | NUMERIC(18, 2) | required |
| `error_count` | INTEGER | required |
| `warning_count` | INTEGER | required |
| `calculated_at` | DATETIME |  |
| `approved_at` | DATETIME |  |
| `approved_by` | INTEGER |  |
| `finalised_at` | DATETIME |  |
| `finalised_by` | INTEGER |  |
| `paid_at` | DATETIME |  |
| `voided_at` | DATETIME |  |
| `voided_by` | INTEGER |  |
| `void_reason` | VARCHAR(300) |  |
| `reverses_run_id` | INTEGER | FK -> pay_runs.id (NO ACTION) |
| `reversed_by_run_id` | INTEGER |  |
| `result_hash` | VARCHAR(64) |  |
| `notes` | TEXT |  |
| `created_by` | INTEGER |  |
| `created_at` | DATETIME |  |

Constraints: `uq_pay_run_no`, `ck_pay_run_status`, `ck_pay_run_type`

Indexes: `ix_pay_run_pay_date`, `uq_pay_run_period` (unique, partial), `ix_pay_runs_org_id`

## `pay_settings`

| Column | Type | Notes |
|---|---|---|
| `org_id` | INTEGER | PK, FK -> organisations.id (CASCADE) |
| `employer_name` | VARCHAR(255) |  |
| `abn` | VARCHAR(20) |  |
| `default_frequency` | VARCHAR(12) | required |
| `standard_hours_per_week` | NUMERIC(6, 2) | required |
| `employee_prefix` | VARCHAR(10) | required |
| `next_employee_no` | INTEGER | required |
| `run_prefix` | VARCHAR(10) | required |
| `next_run_no` | INTEGER | required |
| `payslip_config` | JSON |  |
| `payment_config` | JSON |  |
| `accounting_map` | JSON |  |
| `stp_config` | JSON |  |
| `leave_config` | JSON |  |
| `controls` | JSON |  |
| `updated_at` | DATETIME |  |

## `pay_stp_events`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `event_type` | VARCHAR(20) | required |
| `run_id` | INTEGER | FK -> pay_runs.id (SET NULL) |
| `fy` | VARCHAR(7) | required |
| `status` | VARCHAR(14) | required |
| `payload` | JSON | required |
| `mock_reference` | VARCHAR(40) |  |
| `created_by` | INTEGER |  |
| `created_at` | DATETIME |  |
| `submitted_at` | DATETIME |  |

Constraints: `ck_pay_stp_status`

Indexes: `ix_pay_stp_events_org_id`

## `pay_stp_final`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `employee_id` | INTEGER | required, FK -> pay_employees.id (CASCADE) |
| `fy` | VARCHAR(7) | required |
| `gross` | NUMERIC(18, 2) | required |
| `tax` | NUMERIC(18, 2) | required |
| `super_total` | NUMERIC(18, 2) | required |
| `finalised_at` | DATETIME |  |
| `finalised_by` | INTEGER |  |

Constraints: `uq_pay_stp_final`

Indexes: `ix_pay_stp_final_org_id`

## `pay_super_contribs`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `run_id` | INTEGER | required, FK -> pay_runs.id (CASCADE) |
| `run_employee_id` | INTEGER | required, FK -> pay_run_employees.id (CASCADE) |
| `employee_id` | INTEGER | required |
| `fund_id` | INTEGER | required, FK -> pay_super_funds.id (RESTRICT) |
| `component` | VARCHAR(20) | required |
| `amount` | NUMERIC(18, 2) | required |
| `qualifying_earnings` | NUMERIC(18, 2) | required |
| `due_date` | DATE | required |
| `status` | VARCHAR(10) | required |
| `paid_at` | DATETIME |  |
| `payment_ref` | VARCHAR(60) |  |

Constraints: `ck_pay_sc_comp`, `ck_pay_sc_status`

Indexes: `ix_pay_super_contribs_org_id`, `ix_pay_sc_due`, `ix_pay_super_contribs_employee_id`, `ix_pay_super_contribs_run_id`

## `pay_super_funds`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `name` | VARCHAR(150) | required |
| `fund_type` | VARCHAR(10) | required |
| `usi` | VARCHAR(30) |  |
| `abn` | VARCHAR(20) |  |
| `smsf_bsb` | VARCHAR(7) |  |
| `smsf_account` | VARCHAR(20) |  |
| `smsf_account_name` | VARCHAR(100) |  |
| `esa` | VARCHAR(50) |  |
| `is_default` | BOOLEAN | required |
| `is_active` | BOOLEAN | required |

Constraints: `ck_pay_fund_type`, `uq_pay_fund_name`

Indexes: `ix_pay_super_funds_org_id`

## `pay_timesheet_lines`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `timesheet_id` | INTEGER | required, FK -> pay_timesheets.id (CASCADE) |
| `work_date` | DATE | required |
| `pay_item_id` | INTEGER | required, FK -> pay_items.id (RESTRICT) |
| `leave_type_id` | INTEGER | FK -> pay_leave_types.id (SET NULL) |
| `hours` | NUMERIC(12, 4) | required |
| `break_minutes` | INTEGER | required |
| `start_time` | VARCHAR(5) |  |
| `end_time` | VARCHAR(5) |  |
| `notes` | VARCHAR(300) |  |
| `processed_run_id` | INTEGER | FK -> pay_runs.id (SET NULL) |

Indexes: `ix_pay_timesheet_lines_timesheet_id`, `ix_pay_timesheet_lines_org_id`

## `pay_timesheets`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `org_id` | INTEGER | required, FK -> organisations.id (CASCADE) |
| `employee_id` | INTEGER | required, FK -> pay_employees.id (CASCADE) |
| `week_start` | DATE | required |
| `week_end` | DATE | required |
| `status` | VARCHAR(12) | required |
| `notes` | TEXT |  |
| `submitted_at` | DATETIME |  |
| `submitted_by` | INTEGER |  |
| `decided_at` | DATETIME |  |
| `decided_by` | INTEGER |  |
| `reject_reason` | VARCHAR(300) |  |
| `processed_run_id` | INTEGER | FK -> pay_runs.id (SET NULL) |
| `created_by` | INTEGER |  |
| `created_at` | DATETIME |  |

Constraints: `uq_pay_ts_week`, `ck_pay_ts_status`

Indexes: `ix_pay_ts_status`, `ix_pay_timesheets_employee_id`, `ix_pay_timesheets_org_id`

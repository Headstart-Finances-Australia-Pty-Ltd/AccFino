# Mock data

`csv/` holds 16 numbered CSV files for a fictional Sydney IT-services and hardware company (1 Jul 2025 – 30 Sep 2026). Load them in number order.

Full instructions (install, load order, where to click, expected figures and how to review performance): **`docs/CSV_IMPORT.md`**.

* `generate_mock_data.py` regenerates the files (`--today`, `--bank-code`); standard library only.
* The files are internally consistent: receipts/payments settle exactly what is owing, asset cost and depreciation are in the ledger before the register is loaded, and every bank movement is on the statement.

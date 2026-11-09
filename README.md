# B2B EDI Data Integration Pipeline

A lightweight Python integration pipeline simulating an Electronic Data Interchange (EDI) workflow: parsing B2B XML invoices, enforcing business rules (Modulo 11 Greek AFM checksum and line-item financial reconciliation), and persisting data into an ACID-compliant SQLite relational database.

## Architecture & Features
- **XML Parsing:** Ingests hierarchical XML documents using `xml.etree.ElementTree`, separating multi-level structures into document Headers and Line Items.
- **Business Rule Validations:**
  - Greek Tax ID (AFM) verification using the **Modulo 11** checksum algorithm.
  - Header totals check (`TotalNet + TotalVAT == TotalGross`).
  - Line-by-line reconciliation (`Qty * UnitPrice == NetAmount` and line totals matching header totals).
  - High-precision financial calculations using Python's `decimal.Decimal`.
- **Database Persistence:** Relational schema (`Invoices` 1-to-N `Invoice_Lines`) in SQLite with atomic commit and rollback handling.

## How to Run
1. Ensure Python 3.8+ is installed.
2. Run the script:
   ```bash
   python integration_pipeline.py

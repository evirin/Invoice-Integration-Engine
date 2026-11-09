import sqlite3
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP



def validate_greek_afm(afm: str) -> bool:
    
    if not afm.isdigit() or len(afm) != 9:
        return False

    digits = [int(d) for d in afm]
    # Το άθροισμα των πρώτων 8 ψηφίων πολλαπλασιασμένων με δυνάμεις του 2 (2^8 έως 2^1)
    weights = [256, 128, 64, 32, 16, 8, 4, 2]
    total_sum = sum(d * w for d, w in zip(digits[:8], weights))

    remainder = total_sum % 11
    check_digit = remainder % 10

    return check_digit == digits[8]


def parse_and_validate(xml_file_path: str) -> dict:
   
    tree = ET.parse(xml_file_path)
    root = tree.getroot()

    header_node = root.find("Header")
    lines_node = root.find("Lines")

    if header_node is None or lines_node is None:
        raise ValueError("Μη έγκυρη δομή XML: Λείπει το Header ή το Lines tag.")

    
    header = {
        "invoice_id": header_node.findtext("InvoiceID"),
        "issue_date": header_node.findtext("IssueDate"),
        "issuer_afm": header_node.findtext("IssuerAFM"),
        "customer_afm": header_node.findtext("CustomerAFM"),
        "currency": header_node.findtext("Currency"),
        "total_net": Decimal(header_node.findtext("TotalNetAmount")),
        "total_vat": Decimal(header_node.findtext("TotalVatAmount")),
        "total_gross": Decimal(header_node.findtext("TotalGrossAmount")),
    }

    
    for afm_field in ["issuer_afm", "customer_afm"]:
        afm_val = header[afm_field]
        if not validate_greek_afm(afm_val):
            raise ValueError(f"Αποτυχία επικύρωσης ΑΦΜ ({afm_field}: {afm_val}). Μη έγκυρο Modulo 11 checksum.")

    
    calculated_gross = header["total_net"] + header["total_vat"]
    if calculated_gross != header["total_gross"]:
        raise ValueError(
            f"Ασυμφωνία στο Header: Net ({header['total_net']}) + VAT ({header['total_vat']}) = "
            f"{calculated_gross}, αλλά δηλώθηκε Gross = {header['total_gross']}"
        )

    # Εξαγωγή & Validation Lines
    lines = []
    sum_lines_net = Decimal("0.00")
    sum_lines_vat = Decimal("0.00")

    for line_elem in lines_node.findall("Line"):
        qty = Decimal(line_elem.findtext("Quantity"))
        price = Decimal(line_elem.findtext("UnitPrice"))
        net = Decimal(line_elem.findtext("NetAmount"))
        vat_rate = Decimal(line_elem.findtext("VatRate"))
        vat_amount = Decimal(line_elem.findtext("VatAmount"))

        # Έλεγχος γραμμής: Qty * Price == Net
        expected_net = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if expected_net != net:
            raise ValueError(f"Σφάλμα γραμμής {line_elem.findtext('LineNumber')}: Qty * Price != NetAmount")

        # Έλεγχος υπολογισμού ΦΠΑ γραμμής: Net * (Rate / 100) == VatAmount
        expected_vat = (net * (vat_rate / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if expected_vat != vat_amount:
            raise ValueError(f"Σφάλμα γραμμής {line_elem.findtext('LineNumber')}: Υπολογισμός ΦΠΑ μη ακριβής")

        sum_lines_net += net
        sum_lines_vat += vat_amount

        lines.append({
            "line_number": int(line_elem.findtext("LineNumber")),
            "item_code": line_elem.findtext("ItemCode"),
            "quantity": float(qty),
            "unit_price": float(price),
            "net_amount": float(net),
            "vat_rate": float(vat_rate),
            "vat_amount": float(vat_amount),
        })

    # 3. Reconciliation: Άθροισμα γραμμών με Header Totals
    if sum_lines_net != header["total_net"] or sum_lines_vat != header["total_vat"]:
        raise ValueError(
            f"Σφάλμα ασυμφωνίας συνόλων: "
            f"Sum(Lines Net)={sum_lines_net} vs Header Net={header['total_net']}, "
            f"Sum(Lines VAT)={sum_lines_vat} vs Header VAT={header['total_vat']}"
        )

    return {"header": header, "lines": lines}




def init_db(conn: sqlite3.Connection):
    """Δημιουργεί το σχεσιακό σχήμα στη βάση."""
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Invoices (
        InvoiceID TEXT PRIMARY KEY,
        IssueDate TEXT NOT NULL,
        IssuerAFM TEXT NOT NULL,
        CustomerAFM TEXT NOT NULL,
        Currency TEXT NOT NULL,
        TotalNetAmount REAL NOT NULL,
        TotalVatAmount REAL NOT NULL,
        TotalGrossAmount REAL NOT NULL,
        CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Invoice_Lines (
        LineID INTEGER PRIMARY KEY AUTOINCREMENT,
        InvoiceID TEXT NOT NULL,
        LineNumber INTEGER NOT NULL,
        ItemCode TEXT NOT NULL,
        Quantity REAL NOT NULL,
        UnitPrice REAL NOT NULL,
        NetAmount REAL NOT NULL,
        VatRate REAL NOT NULL,
        VatAmount REAL NOT NULL,
        FOREIGN KEY (InvoiceID) REFERENCES Invoices(InvoiceID) ON DELETE CASCADE,
        UNIQUE (InvoiceID, LineNumber)
    );
    """)
    conn.commit()


def save_to_db(data: dict, db_path: str = "erp_integration.db"):
   
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    
    init_db(conn)

    header = data["header"]
    lines = data["lines"]

    try:
        with conn:  # Context manager διαχειρίζεται αυτόματα το BEGIN/COMMIT/ROLLBACK
            cursor = conn.cursor()
            
            # Εισαγωγή Header
            cursor.execute("""
                INSERT INTO Invoices (
                    InvoiceID, IssueDate, IssuerAFM, CustomerAFM, Currency,
                    TotalNetAmount, TotalVatAmount, TotalGrossAmount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                header["invoice_id"],
                header["issue_date"],
                header["issuer_afm"],
                header["customer_afm"],
                header["currency"],
                float(header["total_net"]),
                float(header["total_vat"]),
                float(header["total_gross"])
            ))

            # Εισαγωγή Lines
            line_records = [
                (
                    header["invoice_id"],
                    line["line_number"],
                    line["item_code"],
                    line["quantity"],
                    line["unit_price"],
                    line["net_amount"],
                    line["vat_rate"],
                    line["vat_amount"]
                )
                for line in lines
            ]

            cursor.executemany("""
                INSERT INTO Invoice_Lines (
                    InvoiceID, LineNumber, ItemCode, Quantity,
                    UnitPrice, NetAmount, VatRate, VatAmount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, line_records)

        print(f"Επιτυχής εισαγωγή παραστατικού {header['invoice_id']} με {len(lines)} γραμμές.")

    except sqlite3.IntegrityError as e:
        print(f"Σφάλμα ακεραιότητας βάσης (Integrity Error): {e}")
    except Exception as e:
        print(f"Σφάλμα κατά την εγγραφή στη βάση: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    xml_path = "invoice_sample.xml"
    print(f"Εκκίνηση ανάγνωσης & επικύρωσης αρχείου: {xml_path}...")
    
    try:
        validated_data = parse_and_validate(xml_path)
        print("Οι έλεγχοι επικύρωσης (ΑΦΜ, Math Check, Line Reconciliation) πέρασαν επιτυχώς")
        
        print("Εισαγωγή δεδομένων στη βάση δεδομένων SQLite")
        save_to_db(validated_data)
        
    except ValueError as err:
        print(f"Validation Error: {err}")
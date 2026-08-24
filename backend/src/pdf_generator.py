from fpdf import FPDF


def table_to_pdf(headers: list, rows: list, output_path: str):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Tabla extraída", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    n = max(len(headers), max((len(r) for r in rows), default=0))
    col_width = min((pdf.w - 20) / max(n, 1), 40)
    pdf.set_font("Helvetica", "B", 8)
    for h in headers:
        pdf.cell(col_width, 7, str(h)[:25], border=1)
    pdf.ln()
    pdf.set_font("Helvetica", "", 8)
    for row in rows:
        for cell in row:
            pdf.cell(col_width, 7, str(cell)[:25], border=1)
        pdf.ln()
    pdf.output(output_path)

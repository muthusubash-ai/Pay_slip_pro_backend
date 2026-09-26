import base64
import io
import logging

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.company import Company
from app.models.salary_slip import SalarySlip

logger = logging.getLogger(__name__)

MONTH_NAMES = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def _fmt(value: float) -> str:
    return f"{float(value):,.2f}"


def _make_color_palette(hex_color: str) -> dict:
    """Generate a balanced color palette from a single hex color."""
    try:
        primary = colors.HexColor(hex_color)
        r, g, b = primary.red, primary.green, primary.blue
    except Exception:
        primary = colors.HexColor("#000000")
        r, g, b = 0, 0, 0

    # Dark variant (for headers) — darken by 30%
    dark = colors.Color(r * 0.7, g * 0.7, b * 0.7)

    # Light variant (for subtle backgrounds) — 90% toward white
    light = colors.Color(
        min(1, r + 0.9 * (1 - r)),
        min(1, g + 0.9 * (1 - g)),
        min(1, b + 0.9 * (1 - b)),
    )

    # Medium variant (for totals row) — 75% toward white
    medium = colors.Color(
        min(1, r + 0.75 * (1 - r)),
        min(1, g + 0.75 * (1 - g)),
        min(1, b + 0.75 * (1 - b)),
    )

    # Row stripe — very subtle tint
    stripe = colors.Color(
        min(1, r + 0.95 * (1 - r)),
        min(1, g + 0.95 * (1 - g)),
        min(1, b + 0.95 * (1 - b)),
    )

    return {
        "primary": primary,
        "dark": dark,
        "light": light,
        "medium": medium,
        "stripe": stripe,
    }


def _get_logo_image(logo_data: str, max_height: float = 22 * mm, max_width: float = 55 * mm) -> Image | None:
    """Convert base64 logo to ReportLab Image, sized flexibly."""
    try:
        b64_part = logo_data.split(",", 1)[1] if "," in logo_data else logo_data
        img_bytes = base64.b64decode(b64_part)
        img_buffer = io.BytesIO(img_bytes)
        img = Image(img_buffer)

        # Calculate aspect ratio and scale to fit within bounds
        aspect = img.imageWidth / img.imageHeight if img.imageHeight > 0 else 1

        if aspect >= 1:
            # Landscape or square — constrain by width
            img.drawWidth = min(max_width, max_height * aspect)
            img.drawHeight = img.drawWidth / aspect
        else:
            # Portrait — constrain by height
            img.drawHeight = max_height
            img.drawWidth = max_height * aspect

        # Ensure it doesn't exceed either bound
        if img.drawWidth > max_width:
            img.drawWidth = max_width
            img.drawHeight = img.drawWidth / aspect
        if img.drawHeight > max_height:
            img.drawHeight = max_height
            img.drawWidth = img.drawHeight * aspect

        return img
    except Exception:
        logger.warning("Failed to load logo for PDF")
        return None


def generate_pdf_bytes(
    slip: SalarySlip,
    company: Company | None = None,
    include_doj: bool = True,
) -> bytes:
    employee = slip.employee
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    elements = []

    # --- Color palette from company logo ---
    hex_color = "#000000"
    if company and company.primary_color:
        hex_color = company.primary_color
    pal = _make_color_palette(hex_color)

    # --- Styles ---
    company_name_style = ParagraphStyle(
        "CompanyName", parent=styles["Title"],
        fontSize=20, leading=24, alignment=TA_LEFT,
        spaceAfter=1 * mm, textColor=pal["dark"],
    )
    company_addr_style = ParagraphStyle(
        "CompanyAddr", parent=styles["Normal"],
        fontSize=9, alignment=TA_LEFT,
        textColor=colors.HexColor("#666666"), spaceAfter=1 * mm,
    )
    slip_title_style = ParagraphStyle(
        "SlipTitle", parent=styles["Heading2"],
        fontSize=13, alignment=TA_CENTER,
        textColor=colors.white, spaceAfter=0, spaceBefore=0,
    )
    section_style = ParagraphStyle(
        "Section", parent=styles["Heading3"],
        fontSize=11, textColor=pal["dark"],
        spaceBefore=5 * mm, spaceAfter=2 * mm,
    )
    footer_style = ParagraphStyle(
        "Footer", parent=styles["Normal"],
        fontSize=8, alignment=TA_CENTER,
        textColor=colors.HexColor("#999999"), spaceBefore=8 * mm,
    )
    right_align = ParagraphStyle(
        "RightAlign", parent=styles["Normal"], fontSize=9, alignment=TA_RIGHT,
    )

    # ==========================================
    # 1. HEADER — Logo + Company Name + Address
    # ==========================================
    company_name = company.company_name if company else "Company Name"
    company_address = ""
    if company:
        parts = [p for p in [company.address, company.city, company.state, company.zip_code] if p]
        company_address = ", ".join(parts)

    logo_img = None
    if company and company.logo_data:
        logo_img = _get_logo_image(company.logo_data, max_height=25 * mm, max_width=60 * mm)

    if logo_img:
        # Logo left + Company name & address right
        name_para = Paragraph(company_name, company_name_style)
        addr_para = Paragraph(company_address, company_addr_style) if company_address else Paragraph("", company_addr_style)

        # Stack name + address in a sub-table
        info_table = Table(
            [[name_para], [addr_para]],
            colWidths=[doc.width - 65 * mm],
        )
        info_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ]))

        header_data = [[logo_img, info_table]]
        header_table = Table(header_data, colWidths=[65 * mm, doc.width - 65 * mm])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ]))
        elements.append(header_table)
    else:
        elements.append(Paragraph(company_name, company_name_style))
        if company_address:
            elements.append(Paragraph(company_address, company_addr_style))

    # Colored separator bar
    elements.append(Spacer(1, 2 * mm))
    month_name = MONTH_NAMES[slip.month] if 1 <= slip.month <= 12 else str(slip.month)
    title_data = [[Paragraph(f"Pay Slip — {month_name} {slip.year}", slip_title_style)]]
    title_table = Table(title_data, colWidths=[doc.width])
    title_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), pal["primary"]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    elements.append(title_table)

    # ==========================================
    # 2. EMPLOYEE DETAILS
    # ==========================================
    elements.append(Paragraph("Employee Details", section_style))

    emp_data = [
        ["Employee Name", employee.full_name, "Employee ID", employee.employee_code],
        ["Department", employee.department or "N/A", "Designation", employee.designation or "N/A"],
    ]
    if include_doj:
        emp_data.append(["Date of Joining", str(employee.date_of_joining), "PAN", employee.pan_number or "N/A"])
    else:
        emp_data.append(["PAN", employee.pan_number or "N/A", "", ""])
    emp_data.append(["Bank Name", employee.bank_name or "N/A", "Account No.", employee.bank_account_number or "N/A"])

    col_w = doc.width / 4
    emp_table = Table(emp_data, colWidths=[col_w * 0.8, col_w * 1.2, col_w * 0.8, col_w * 1.2])
    emp_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), pal["light"]),
        ("BACKGROUND", (2, 0), (2, -1), pal["light"]),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#333333")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(emp_table)

    # ==========================================
    # 3. EARNINGS & DEDUCTIONS
    # ==========================================
    elements.append(Paragraph("Earnings &amp; Deductions", section_style))

    earnings = [
        ("Basic Salary", slip.basic_salary),
        ("HRA", slip.hra),
        ("Conveyance Allowance", slip.conveyance_allowance),
        ("Medical Allowance", slip.medical_allowance),
        ("Special Allowance", slip.special_allowance),
    ]
    deductions = [
        ("Provident Fund (PF)", slip.pf_deduction),
        ("Professional Tax", slip.professional_tax),
        ("TDS", slip.tds),
        ("ESI", slip.esi),
    ]

    leave_days = getattr(slip, "leave_days", 0) or 0
    leave_ded = getattr(slip, "leave_deduction", 0) or 0
    if leave_days > 0:
        deductions.append((f"Leave Deduction ({leave_days} days)", leave_ded))

    max_rows = max(len(earnings), len(deductions))
    while len(earnings) < max_rows:
        earnings.append(("", 0))
    while len(deductions) < max_rows:
        deductions.append(("", 0))

    # Header
    salary_data = [["Earnings", "Amount (Rs.)", "Deductions", "Amount (Rs.)"]]

    for i in range(max_rows):
        e_label, e_val = earnings[i]
        d_label, d_val = deductions[i]
        salary_data.append([
            e_label,
            Paragraph(_fmt(e_val), right_align) if e_label else "",
            d_label,
            Paragraph(_fmt(d_val), right_align) if d_label else "",
        ])

    # Totals
    all_deductions = float(slip.total_deductions) + float(leave_ded)
    salary_data.append([
        "Gross Salary",
        Paragraph(_fmt(slip.gross_salary), right_align),
        "Total Deductions",
        Paragraph(_fmt(all_deductions), right_align),
    ])

    half_w = doc.width / 2
    salary_table = Table(
        salary_data,
        colWidths=[half_w * 0.6, half_w * 0.4, half_w * 0.6, half_w * 0.4],
    )
    salary_table.setStyle(TableStyle([
        # Header — primary color
        ("BACKGROUND", (0, 0), (-1, 0), pal["primary"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ALIGNMENT", (1, 0), (1, 0), "RIGHT"),
        ("ALIGNMENT", (3, 0), (3, 0), "RIGHT"),
        # Data
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        # Totals row — medium tint + bold
        ("BACKGROUND", (0, -1), (-1, -1), pal["medium"]),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        # Alternate row stripe
        *[
            ("BACKGROUND", (0, i), (-1, i), pal["stripe"])
            for i in range(2, max_rows + 1, 2)
        ],
    ]))
    elements.append(salary_table)

    # ==========================================
    # 4. NET PAY BOX — primary color
    # ==========================================
    elements.append(Spacer(1, 5 * mm))

    net_style = ParagraphStyle(
        "NetPay", parent=styles["Normal"],
        fontSize=15, alignment=TA_CENTER,
        textColor=colors.white, fontName="Helvetica-Bold",
    )
    net_data = [[Paragraph(f"Net Pay: Rs. {_fmt(slip.net_pay)}", net_style)]]
    net_table = Table(net_data, colWidths=[doc.width])
    net_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), pal["dark"]),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
    ]))
    elements.append(net_table)

    # ==========================================
    # 5. FOOTER
    # ==========================================
    elements.append(Paragraph(
        "This is a computer-generated document. No signature required.",
        footer_style,
    ))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    logger.info(
        "PDF generated for %s - %s/%s (%d bytes)",
        employee.employee_code, slip.month, slip.year, len(pdf_bytes),
    )
    return pdf_bytes

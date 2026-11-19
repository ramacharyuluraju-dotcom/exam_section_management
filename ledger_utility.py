import io
from pathlib import Path
import re
import zipfile

import pandas as pd
import streamlit as st
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docxtpl import DocxTemplate
from jinja2 import Template

# Optional ReportLab import for direct A4 PDF label sheet generation
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

try:
    st.set_page_config(page_title="COE Appointment & Address Packager", page_icon="📦", layout="wide")
except Exception:
    pass

st.title("📦 COE Appointment & Envelope Address Packager")
st.markdown(
    "Generates personalized **Appointment Orders**, **QP Templates**, **Subject-Matched Syllabus Copies**, "
    "and **Printable Envelope Address Cut-Out Sheets** from your Mail Merge CSV."
)


# ==============================================================================
# HELPERS: SYLLABUS INDEXING, CSV DECODING & SANITIZATION
# ==============================================================================
def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", str(value or "").strip())
    cleaned = re.sub(r"[\s_]+", "_", cleaned)
    return cleaned.strip("_") or "Unnamed"


def normalize_code(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def split_subject_codes(raw_value: str) -> list[str]:
    text = str(raw_value or "").strip()
    if not text:
        return []
    return [p.strip() for p in re.split(r"[,;/\n]+", text) if p.strip()]


def read_csv_safely(uploaded_csv) -> pd.DataFrame:
    raw_bytes = uploaded_csv.getvalue()
    if raw_bytes.startswith(b"data:text/csv"):
        raw_bytes = raw_bytes.split(b",", 1)[1]

    last_err = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            text = raw_bytes.decode(enc)
            df = pd.read_csv(
                io.StringIO(text),
                on_bad_lines="skip",
                engine="python",
                dtype=str,
                keep_default_na=False,
            )
            df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
            return df
        except Exception as err:
            last_err = err
    raise ValueError(f"Could not decode CSV file: {last_err}")


def register_syllabus_entry(exact_map, norm_map, prefix_list, filename, pdf_bytes=None, file_path=None):
    stem = Path(filename).stem.strip()
    entry = {"name": Path(filename).name, "bytes": pdf_bytes, "path": file_path}
    exact_map[stem.lower()] = entry
    norm_key = normalize_code(stem)
    if norm_key:
        norm_map[norm_key] = entry
        prefix_list.append((norm_key, entry))


def build_syllabus_index(uploaded_items, folder_path_str):
    exact_map = {}
    norm_map = {}
    prefix_list = []

    if folder_path_str and folder_path_str.strip():
        base_dir = Path(folder_path_str.strip()).expanduser()
        if base_dir.is_dir():
            for entry in sorted(base_dir.rglob("*")):
                if entry.is_file() and entry.suffix.lower() == ".pdf" and not entry.name.startswith("._"):
                    register_syllabus_entry(exact_map, norm_map, prefix_list, entry.name, file_path=entry)

    if uploaded_items:
        for item in uploaded_items:
            fname = item.name
            ext = Path(fname).suffix.lower()
            if ext == ".pdf":
                register_syllabus_entry(exact_map, norm_map, prefix_list, fname, pdf_bytes=item.getvalue())
            elif ext == ".zip":
                try:
                    with zipfile.ZipFile(io.BytesIO(item.getvalue()), "r") as zf:
                        for info in zf.infolist():
                            if info.is_dir():
                                continue
                            inner_name = Path(info.filename).name
                            if not inner_name or inner_name.startswith("._") or "__MACOSX" in info.filename:
                                continue
                            if Path(inner_name).suffix.lower() == ".pdf":
                                register_syllabus_entry(
                                    exact_map,
                                    norm_map,
                                    prefix_list,
                                    inner_name,
                                    pdf_bytes=zf.read(info.filename),
                                )
                except zipfile.BadZipFile:
                    st.sidebar.error(f"Invalid ZIP file: `{fname}`")

    return exact_map, norm_map, prefix_list


def find_matching_syllabus(subject_code, exact_map, norm_map, prefix_list):
    clean = str(subject_code or "").strip()
    if not clean:
        return None
    low = clean.lower()
    if low in exact_map:
        return exact_map[low]
    norm = normalize_code(clean)
    if norm in norm_map:
        return norm_map[norm]
    if norm:
        for stem_norm, entry in prefix_list:
            if stem_norm.startswith(norm):
                return entry
    return None


def get_syllabus_bytes(entry):
    if entry["bytes"] is not None:
        return entry["bytes"]
    return entry["path"].read_bytes()


def format_syllabus_filename(original_name: str) -> str:
    if original_name.lower().startswith("syllabus"):
        return original_name
    return f"Syllabus_{original_name}"


# ==============================================================================
# SIDEBAR: FILE UPLOADS (SECTIONS 1 TO 5)
# ==============================================================================
st.sidebar.header("Upload Files")
uploaded_csv = st.sidebar.file_uploader("1. Upload Mail Merge Data (.csv)", type=["csv"])
uploaded_appointment_template = st.sidebar.file_uploader("2. Upload Appointment Order Template (.docx)", type=["docx"])
uploaded_qp_template = st.sidebar.file_uploader("3. Upload QP Format Template (.docx)", type=["docx"])
uploaded_attachments = st.sidebar.file_uploader(
    "4. Upload Static Attachments (Remuneration Bill, Declaration, etc.)",
    accept_multiple_files=True,
)

st.sidebar.divider()
st.sidebar.subheader("5. Syllabus PDFs (Subject-Code Matched)")

syllabus_mode = st.sidebar.radio(
    "Provide Syllabus PDFs via:",
    options=["Folder Path (Recommended)", "Upload PDFs / ZIP"],
    help="Folder Path is fastest when running locally with many <SubjectCode>.pdf files.",
)

syllabus_folder_path = None
uploaded_syllabus_files = None

if syllabus_mode == "Folder Path (Recommended)":
    syllabus_folder_path = st.sidebar.text_input(
        "Syllabus Folder Path",
        placeholder="/Users/rajuramacharyalu/Documents/Syllabus_PDFs",
        help="Folder containing PDFs named by subject code (e.g., 1BECC102.pdf). Subfolders are scanned automatically.",
    )
    if syllabus_folder_path and syllabus_folder_path.strip():
        folder_check = Path(syllabus_folder_path.strip()).expanduser()
        if folder_check.is_dir():
            pdf_count = sum(
                1
                for p in folder_check.rglob("*")
                if p.is_file() and p.suffix.lower() == ".pdf" and not p.name.startswith("._")
            )
            st.sidebar.success(f"Found {pdf_count} syllabus PDF(s)")
        else:
            st.sidebar.error("Folder path not found.")
else:
    uploaded_syllabus_files = st.sidebar.file_uploader(
        "Upload Syllabus PDFs or a .zip folder",
        type=["pdf", "zip"],
        accept_multiple_files=True,
        help="Upload individual <SubjectCode>.pdf files or a single .zip containing your syllabus folder.",
    )

has_syllabus_input = bool(
    (syllabus_folder_path and syllabus_folder_path.strip()) or uploaded_syllabus_files
)

if "prev_has_syllabus" not in st.session_state:
    st.session_state["prev_has_syllabus"] = False
if has_syllabus_input and not st.session_state["prev_has_syllabus"]:
    st.session_state["include_syllabus_sidebar"] = True
elif not has_syllabus_input:
    st.session_state["include_syllabus_sidebar"] = False
st.session_state["prev_has_syllabus"] = has_syllabus_input

include_syllabus = st.sidebar.checkbox(
    "Attach matched Syllabus PDF in each setter's ZIP",
    key="include_syllabus_sidebar",
    disabled=not has_syllabus_input,
)


# --- HELPER: BUILD NORMALIZED CONTEXT FROM CSV ROW ---
def build_row_context(row, index=0):
    raw_context = {
        str(k).strip().replace(" ", "_"): ("" if pd.isna(v) else str(v).strip())
        for k, v in row.to_dict().items()
    }
    context = {**raw_context}

    # Case-insensitive lookup map for flexible CSV column matching
    lower_map = {k.lower(): v for k, v in context.items() if v}

    def pick_first(*keys, default=""):
        for k in keys:
            if k in context and context[k]:
                return context[k]
            if k.lower() in lower_map:
                return lower_map[k.lower()]
        return default

    # Smart bridging for templates & address labels
    context["Setter_Name"] = pick_first("Setter_Name", "Name", "Faculty_Name", "Examiner_Name", default=f"Setter_{index + 1}")
    context["Name"] = context["Setter_Name"]
    context["Email"] = pick_first("Email", "Email_ID", "Mail", "Setter_Email", default="")
    context["Course_Code"] = pick_first("Course_Code", "Course", "Sub_Code", "Subject_Code", default="")
    context["Course_Title"] = pick_first("Course_Title", "Course_Name", "Subject_Name", "Subject", default="")
    context["Course_Name"] = context["Course_Title"]
    context["Academic_Year"] = pick_first("Academic_Year", "AY", default="")
    context["AY"] = context["Academic_Year"]

    if "ODD_EVEN" in context:
        context["Odd_Even"] = context["ODD_EVEN"]
        context["Semester_Type"] = context["ODD_EVEN"]

    # Address-specific smart fields
    context["Designation"] = pick_first("Designation", "Role", "Post", default="")
    context["Department"] = pick_first("Department", "Dept", "Branch", "Offering_Department", default="")
    context["College"] = pick_first(
        "College", "College_Name", "Institute", "Institution", "Organization", "University", default=""
    )
    context["Address"] = pick_first(
        "Address", "Postal_Address", "College_Address", "Communication_Address", "Residential_Address", "Street", default=""
    )
    context["City"] = pick_first("City", "Place", "Location", "District", default="")
    context["Pincode"] = pick_first("Pincode", "Pin", "Pin_Code", "Zip", default="")
    context["Phone"] = pick_first("Phone", "Mobile", "Mobile_No", "Contact", "Contact_No", "Phone_No", default="")
    context["Ref_No"] = pick_first("Ref_No", "Reference_No", "Order_No", default="")

    return context


# --- HELPER: SET XML BORDERS & CELL MARGINS IN PYTHON-DOCX ---
def style_docx_address_cell(cell, top_pt=6, bottom_pt=6, left_pt=8, right_pt=8):
    tcPr = cell._tc.get_or_add_tcPr()

    # 1. Outer dashed cut border around the address box
    tcBorders = OxmlElement("w:tcBorders")
    for border_name in ["top", "left", "bottom", "right"]:
        border = OxmlElement(f"w:{border_name}")
        border.set(qn("w:val"), "dashed")
        border.set(qn("w:sz"), "8")  # 1 pt width
        border.set(qn("w:space"), "0")
        border.set(qn("w:color"), "1E293B")
        tcBorders.append(border)
    tcPr.append(tcBorders)

    # 2. Inner cell padding so text never touches the scissor cut line
    tcMar = OxmlElement("w:tcMar")
    for side, pt_val in [("top", top_pt), ("bottom", bottom_pt), ("left", left_pt), ("right", right_pt)]:
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(int(pt_val * 20)))  # dxa (1 pt = 20 dxa)
        node.set(qn("w:type"), "dxa")
        tcMar.append(node)
    tcPr.append(tcMar)


# --- HELPER: GENERATE WORD (.DOCX) ADDRESS CUT-OUT GRID ---
def generate_address_labels_docx(contexts, to_template_str, from_text, header_badge, boxes_per_page=8):
    doc = Document()

    for section in doc.sections:
        section.page_width = Inches(8.27)
        section.page_height = Inches(11.69)
        section.top_margin = Inches(0.4)
        section.bottom_margin = Inches(0.4)
        section.left_margin = Inches(0.4)
        section.right_margin = Inches(0.4)

    rows_per_page = boxes_per_page // 2
    row_height_in = 10.6 / rows_per_page
    jinja_tpl = Template(to_template_str)

    for page_start in range(0, len(contexts), boxes_per_page):
        page_items = contexts[page_start:page_start + boxes_per_page]
        num_rows = (len(page_items) + 1) // 2

        table = doc.add_table(rows=num_rows, cols=2)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False

        for r_idx in range(num_rows):
            row = table.rows[r_idx]
            row.height = Inches(row_height_in)

            for c_idx in range(2):
                item_idx = r_idx * 2 + c_idx
                cell = row.cells[c_idx]
                cell.width = Inches(3.7)
                cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP

                if item_idx >= len(page_items):
                    continue

                ctx = page_items[item_idx]
                style_docx_address_cell(cell)

                p_top = cell.paragraphs[0]
                p_top.paragraph_format.space_before = Pt(0)
                p_top.paragraph_format.space_after = Pt(4)

                tag_right = ctx.get("Course_Code") or ctx.get("Ref_No") or ""
                header_line = header_badge.strip()
                if tag_right:
                    header_line = f"{header_line}   |   [{tag_right}]" if header_line else f"[{tag_right}]"

                if header_line:
                    run_hdr = p_top.add_run(header_line)
                    run_hdr.bold = True
                    run_hdr.font.name = "Arial"
                    run_hdr.font.size = Pt(8.5)
                    run_hdr.font.color.rgb = RGBColor(30, 58, 138)

                rendered_to = jinja_tpl.render(**ctx)
                to_lines = [line.strip() for line in rendered_to.splitlines() if line.strip()]

                p_to = cell.add_paragraph()
                p_to.paragraph_format.space_before = Pt(2)
                p_to.paragraph_format.space_after = Pt(6)
                p_to.paragraph_format.line_spacing = 1.15

                run_to_label = p_to.add_run("TO:\n")
                run_to_label.bold = True
                run_to_label.font.name = "Arial"
                run_to_label.font.size = Pt(9.5)

                for l_i, line in enumerate(to_lines):
                    run_line = p_to.add_run(line + ("\n" if l_i < len(to_lines) - 1 else ""))
                    run_line.font.name = "Arial"
                    if l_i == 0:
                        run_line.bold = True
                        run_line.font.size = Pt(10.5)
                    else:
                        run_line.font.size = Pt(9.5)

                if from_text.strip():
                    p_from = cell.add_paragraph()
                    p_from.paragraph_format.space_before = Pt(4)
                    p_from.paragraph_format.space_after = Pt(0)
                    p_from.paragraph_format.line_spacing = 1.1
                    run_from = p_from.add_run("─" * 38 + "\n" + from_text.strip())
                    run_from.font.name = "Arial"
                    run_from.font.size = Pt(8)
                    run_from.font.color.rgb = RGBColor(71, 85, 105)

        if page_start + boxes_per_page < len(contexts):
            doc.add_page_break()

    out_stream = io.BytesIO()
    doc.save(out_stream)
    out_stream.seek(0)
    return out_stream


# --- HELPER: GENERATE A4 PDF ADDRESS CUT-OUT GRID (REPORTLAB) ---
def generate_address_labels_pdf(contexts, to_template_str, from_text, header_badge, boxes_per_page=8):
    if not HAS_REPORTLAB:
        return None

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    styles = getSampleStyleSheet()
    hdr_style = ParagraphStyle(
        "HdrStyle", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.HexColor("#1e3a8a")
    )
    to_style = ParagraphStyle(
        "ToStyle", parent=styles["Normal"], fontName="Helvetica", fontSize=9.5, leading=12.5, textColor=colors.black
    )
    from_style = ParagraphStyle(
        "FromStyle", parent=styles["Normal"], fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=colors.HexColor("#334155")
    )

    rows_per_page = boxes_per_page // 2
    box_width = 93 * mm
    box_height = (275 * mm) / rows_per_page
    jinja_tpl = Template(to_template_str)

    def esc_xml(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    table_rows = []
    current_row = []

    for ctx in contexts:
        cell_flowables = []
        tag_right = ctx.get("Course_Code") or ctx.get("Ref_No") or ""
        header_line = header_badge.strip()
        if tag_right:
            header_line = f"{header_line} &nbsp;&nbsp;|&nbsp;&nbsp; [{tag_right}]" if header_line else f"[{tag_right}]"

        if header_line:
            cell_flowables.append(Paragraph(f"✂ {header_line}", hdr_style))
            cell_flowables.append(Spacer(1, 1.5 * mm))

        rendered_to = jinja_tpl.render(**ctx)
        to_lines = [esc_xml(line.strip()) for line in rendered_to.splitlines() if line.strip()]
        if to_lines:
            to_lines[0] = f"<b>{to_lines[0]}</b>"
        to_html = "<b>TO:</b><br/>" + "<br/>".join(to_lines)
        cell_flowables.append(Paragraph(to_html, to_style))

        if from_text.strip():
            cell_flowables.append(Spacer(1, 2 * mm))
            from_lines = [esc_xml(line.strip()) for line in from_text.strip().splitlines() if line.strip()]
            if from_lines:
                from_lines[0] = f"<b>{from_lines[0]}</b>"
            from_html = "________________________________________<br/>" + "<br/>".join(from_lines)
            cell_flowables.append(Paragraph(from_html, from_style))

        current_row.append(cell_flowables)
        if len(current_row) == 2:
            table_rows.append(current_row)
            current_row = []

    if len(current_row) == 1:
        current_row.append([])
        table_rows.append(current_row)

    row_heights = [box_height] * len(table_rows)
    grid_table = Table(table_rows, colWidths=[box_width, box_width], rowHeights=row_heights)
    grid_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.8, colors.HexColor("#1e293b"), None, (3, 3)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    doc.build([grid_table])
    buffer.seek(0)
    return buffer


# ==============================================================================
# MAIN WORKFLOW
# ==============================================================================
if uploaded_csv:
    try:
        df = read_csv_safely(uploaded_csv)

        st.subheader("1. Data Preview")
        st.dataframe(df, use_container_width=True)

        detected_cols = [str(c).strip().replace(" ", "_") for c in df.columns]
        st.info(
            f"**Detected CSV Variables ({len(detected_cols)}):** "
            + ", ".join([f"`{{{{ {c} }}}}`" for c in detected_cols])
        )

        # Build contexts for all rows in CSV
        all_row_contexts = [build_row_context(row, idx) for idx, row in df.iterrows()]

        # Index Syllabus PDFs (if provided & enabled in sidebar)
        exact_map, norm_map, prefix_list = (
            build_syllabus_index(uploaded_syllabus_files, syllabus_folder_path)
            if include_syllabus
            else ({}, {}, [])
        )
        syllabus_ready = include_syllabus and len(exact_map) > 0

        # ======================================================================
        # SECTION 2: ENVELOPE ADDRESS LABEL GENERATOR (PRINT, CUT & PASTE BOXES)
        # ======================================================================
        st.divider()
        st.subheader("🏷️ 2. Printable Envelope Address Packaging (Cut & Paste Boxes)")
        st.markdown(
            "Generates a **2-column A4 grid of bordered address boxes** ready to print, cut along the dashed lines, "
            "and paste onto dispatch envelopes."
        )

        col_cfg1, col_cfg2, col_cfg3 = st.columns([1.2, 1.2, 1])
        with col_cfg1:
            default_to_template = (
                "{{ Setter_Name }}\n"
                "{% if Designation %}{{ Designation }}{% if Department %}, Dept. of {{ Department }}{% endif %}\n{% endif %}"
                "{% if College %}{{ College }}\n{% endif %}"
                "{% if Address %}{{ Address }}\n{% endif %}"
                "{% if City %}{{ City }}{% if Pincode %} - {{ Pincode }}{% endif %}\n{% endif %}"
                "{% if Phone %}Ph: {{ Phone }}{% endif %}"
            )
            to_template_input = st.text_area(
                "TO Address Box Template (uses your CSV column names):",
                value=default_to_template,
                height=145,
                help="You can type any {{ Column_Name }} from your CSV here.",
            )

        with col_cfg2:
            default_from_address = (
                "FROM: The Controller of Examinations\n"
                "AMC Engineering College (Autonomous)\n"
                "18th KM, Bannerghatta Main Road, Bengaluru - 560083"
            )
            from_address_input = st.text_area(
                "FROM Return Address (printed at bottom of each box):",
                value=default_from_address,
                height=100,
            )
            header_badge_input = st.text_input(
                "Top Header Stamp inside Box:",
                value="CONFIDENTIAL — EXAMINATION WORK",
            )

        with col_cfg3:
            boxes_per_page = st.selectbox(
                "Boxes per A4 Sheet:",
                options=[8, 10, 6],
                index=0,
                format_func=lambda x: f"{x} Boxes per A4 Sheet (2 × {x // 2} Grid)",
            )
            only_valid_emails = st.checkbox(
                "Only include rows with valid Email",
                value=False,
                help="Uncheck to print address boxes for all rows in the CSV even if Email is blank.",
            )

            filtered_label_contexts = [
                c for c in all_row_contexts
                if not only_valid_emails or ("@" in str(c.get("Email", "")))
            ]

            st.metric("Total Address Boxes", len(filtered_label_contexts))

        if filtered_label_contexts:
            sample_ctx = filtered_label_contexts[0]
            try:
                sample_rendered = Template(to_template_input).render(**sample_ctx)
                sample_lines = [l.strip() for l in sample_rendered.splitlines() if l.strip()]
                with st.expander("👁️ Preview First Envelope Cut-Out Box", expanded=False):
                    tag_preview = sample_ctx.get("Course_Code") or sample_ctx.get("Ref_No") or ""
                    st.markdown(
                        f"""
                        <div style="border: 2px dashed #1e293b; padding: 14px 18px; border-radius: 4px; max-width: 440px; background: #ffffff; color: #0f172a; font-family: Arial, sans-serif;">
                            <div style="font-size: 11px; font-weight: bold; color: #1e3a8a; margin-bottom: 6px;">
                                ✂ {header_badge_input} {f'&nbsp;|&nbsp; [{tag_preview}]' if tag_preview else ''}
                            </div>
                            <div style="font-size: 13px; line-height: 1.45;">
                                <strong>TO:</strong><br/>
                                {'<br/>'.join([f'<strong>{sample_lines[0]}</strong>'] + sample_lines[1:]) if sample_lines else '<em>(Empty — check column names)</em>'}
                            </div>
                            <hr style="margin: 8px 0; border: none; border-top: 1px solid #cbd5e1;" />
                            <div style="font-size: 11px; color: #475569; line-height: 1.35;">
                                {'<br/>'.join(from_address_input.strip().splitlines())}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            except Exception as tpl_err:
                st.warning(f"Template syntax check: {tpl_err}")

            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                docx_labels_stream = generate_address_labels_docx(
                    filtered_label_contexts,
                    to_template_input,
                    from_address_input,
                    header_badge_input,
                    boxes_per_page=boxes_per_page,
                )
                st.download_button(
                    label=f"📄 Download Printable Address Labels (.docx) — {len(filtered_label_contexts)} Boxes",
                    data=docx_labels_stream,
                    file_name="Envelope_Address_Labels.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                )

            with btn_col2:
                if HAS_REPORTLAB:
                    pdf_labels_stream = generate_address_labels_pdf(
                        filtered_label_contexts,
                        to_template_input,
                        from_address_input,
                        header_badge_input,
                        boxes_per_page=boxes_per_page,
                    )
                    st.download_button(
                        label=f"🖨️ Download Printable Address Labels (.pdf) — {len(filtered_label_contexts)} Boxes",
                        data=pdf_labels_stream,
                        file_name="Envelope_Address_Labels.pdf",
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True,
                    )
                else:
                    st.info("Tip: Run `pip install reportlab` if you also want direct PDF export alongside the Word (.docx) label sheet.")

        # ======================================================================
        # SECTION 3: INDIVIDUAL SETTER ZIP PACKAGER (+ MATCHED SYLLABUS + LABELS)
        # ======================================================================
        st.divider()
        st.subheader("📦 3. Generate Individual Setter ZIP Packages")

        # Syllabus Pre-Flight Match Summary
        if include_syllabus:
            if syllabus_ready:
                matched_rows = 0
                missing_preview = set()
                for ctx in all_row_contexts:
                    codes = split_subject_codes(ctx.get("Course_Code", ""))
                    if not codes:
                        continue
                    all_ok = True
                    for code in codes:
                        if not find_matching_syllabus(code, exact_map, norm_map, prefix_list):
                            missing_preview.add(code)
                            all_ok = False
                    if all_ok:
                        matched_rows += 1

                m1, m2, m3 = st.columns(3)
                m1.metric("CSV Rows", len(all_row_contexts))
                m2.metric("Syllabus PDFs Loaded", len(exact_map))
                m3.metric("Syllabus Matched Rows", f"{matched_rows} / {len(all_row_contexts)}")

                if missing_preview:
                    st.warning(
                        f"⚠️ No syllabus PDF found for **{len(missing_preview)}** subject code(s): "
                        + ", ".join(sorted(missing_preview))
                    )
                else:
                    st.success("✅ All subject codes in the CSV match a syllabus PDF!")
            else:
                st.warning("⚠️ Syllabus attachment is enabled in the sidebar, but no PDFs were found yet.")
        else:
            st.info("ℹ️ Optional: Provide Syllabus PDFs in **Sidebar Step 5** to auto-attach each faculty member's subject syllabus.")

        require_valid_email_pkg = st.checkbox(
            "Only generate packages for rows with a valid Email address",
            value=True,
            help="Uncheck if you want ZIP packages generated for all rows even when Email is blank.",
        )

        if uploaded_appointment_template and uploaded_qp_template:
            st.write(
                "Generates personalized Appointment Orders, QP Templates, Static Attachments, "
                + ("**Subject-Matched Syllabus PDFs**, " if syllabus_ready else "")
                + "and the master Envelope Address Label sheets."
            )

            if st.button("🚀 Generate Setter Packages & Address Sheet (Master ZIP)", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()

                try:
                    appointment_bytes = uploaded_appointment_template.getvalue()
                    qp_bytes = uploaded_qp_template.getvalue()
                    static_files = {att.name: att.getvalue() for att in uploaded_attachments} if uploaded_attachments else {}

                    master_zip_buffer = io.BytesIO()
                    total_setters = len(df)
                    processed_count = 0
                    matched_syllabus_count = 0
                    missing_syllabi = set()
                    packaged_contexts = []

                    with zipfile.ZipFile(master_zip_buffer, "w", zipfile.ZIP_DEFLATED) as master_zip:
                        for index, row in df.iterrows():
                            context = build_row_context(row, index)
                            name = context["Setter_Name"]
                            email = context["Email"]
                            course = context["Course_Code"] or f"Course_{index + 1}"

                            if require_valid_email_pkg and ("@" not in email):
                                continue

                            status_text.text(f"Packaging files for {name} ({course})...")
                            packaged_contexts.append(context)

                            # A. Generate Personalized Appointment Order (autoescape prevents & / < / > XML errors)
                            doc_appt = DocxTemplate(io.BytesIO(appointment_bytes))
                            doc_appt.render(context, autoescape=True)
                            appt_stream = io.BytesIO()
                            doc_appt.save(appt_stream)

                            # B. Generate Personalized QP Template
                            doc_qp = DocxTemplate(io.BytesIO(qp_bytes))
                            doc_qp.render(context, autoescape=True)
                            qp_stream = io.BytesIO()
                            doc_qp.save(qp_stream)

                            # C. Create Individual Setter Zip
                            setter_zip_buffer = io.BytesIO()
                            safe_course = sanitize_filename(course)
                            safe_name = sanitize_filename(name)

                            with zipfile.ZipFile(setter_zip_buffer, "w", zipfile.ZIP_DEFLATED) as setter_zip:
                                setter_zip.writestr(f"Appointment_Order_{safe_course}_{safe_name}.docx", appt_stream.getvalue())
                                setter_zip.writestr(f"QP_Format_{safe_course}_{safe_name}.docx", qp_stream.getvalue())

                                # Attach matched Syllabus PDF(s) for this setter's Course_Code
                                if syllabus_ready:
                                    seen_pdf_names = set()
                                    for code in split_subject_codes(context["Course_Code"]):
                                        syl_entry = find_matching_syllabus(code, exact_map, norm_map, prefix_list)
                                        if syl_entry:
                                            syl_fname = format_syllabus_filename(syl_entry["name"])
                                            if syl_fname not in seen_pdf_names:
                                                setter_zip.writestr(syl_fname, get_syllabus_bytes(syl_entry))
                                                seen_pdf_names.add(syl_fname)
                                                matched_syllabus_count += 1
                                        else:
                                            missing_syllabi.add(code)

                                for file_name, file_data in static_files.items():
                                    setter_zip.writestr(file_name, file_data)

                            # D. Add Setter Zip to Master Zip
                            package_name = f"Confidential_{safe_course}_{safe_name}.zip"
                            master_zip.writestr(package_name, setter_zip_buffer.getvalue())

                            processed_count += 1
                            progress_bar.progress(min(1.0, processed_count / max(1, total_setters)))

                        # E. Bundle the Printable Envelope Address Label Sheets at the root of the Master ZIP
                        if packaged_contexts:
                            docx_sheet = generate_address_labels_docx(
                                packaged_contexts, to_template_input, from_address_input, header_badge_input, boxes_per_page
                            )
                            master_zip.writestr("00_PRINT_Envelope_Address_Labels.docx", docx_sheet.getvalue())

                            if HAS_REPORTLAB:
                                pdf_sheet = generate_address_labels_pdf(
                                    packaged_contexts, to_template_input, from_address_input, header_badge_input, boxes_per_page
                                )
                                master_zip.writestr("00_PRINT_Envelope_Address_Labels.pdf", pdf_sheet.getvalue())

                    status_text.text("Finalizing master package...")
                    progress_bar.progress(1.0)
                    status_text.empty()

                    st.session_state["ledger_master_zip"] = master_zip_buffer.getvalue()
                    st.session_state["ledger_master_summary"] = {
                        "processed": processed_count,
                        "matched_syllabi": matched_syllabus_count,
                        "syllabus_ready": syllabus_ready,
                        "missing_syllabi": sorted(missing_syllabi),
                    }

                except Exception as e:
                    st.error(f"Failed during document generation: {str(e)}")

            if "ledger_master_zip" in st.session_state:
                s = st.session_state["ledger_master_summary"]
                st.success(
                    f"✅ Packaged **{s['processed']}** appointment folders"
                    + (f" + **{s['matched_syllabi']}** matched syllabus PDF(s)" if s["syllabus_ready"] else "")
                    + " + Printable Envelope Address Sheets!"
                )
                if s["missing_syllabi"]:
                    st.warning(
                        "⚠️ No matching syllabus PDF found for subject code(s): "
                        + ", ".join(s["missing_syllabi"])
                    )
                st.download_button(
                    label="⬇️ Download All Packages + Address Labels (Master ZIP)",
                    data=st.session_state["ledger_master_zip"],
                    file_name="All_Setter_Packages_With_Labels.zip",
                    mime="application/zip",
                    type="primary",
                    use_container_width=True,
                )
        else:
            st.info("Upload the Appointment Order Template (.docx) and QP Format Template (.docx) in the sidebar when you are ready to generate the individual `.zip` packages.")

    except Exception as e:
        st.error(f"Failed to read the uploaded CSV file. Make sure it is a valid CSV. Error: {str(e)}")
else:
    st.warning("Please upload your Mail Merge CSV in the sidebar to begin (you can print envelope address labels immediately from just the CSV, or upload the .docx templates to generate full packages).")

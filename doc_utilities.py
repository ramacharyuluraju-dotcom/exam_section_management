import io
from pathlib import Path
import re
import zipfile

from docxtpl import DocxTemplate
import pandas as pd
import streamlit as st

# Note: st.set_page_config is removed because app.py handles it globally


def sanitize_filename(value: str) -> str:
    """Removes characters that are invalid in file/folder names."""
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", str(value or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned.strip("_") or "Unnamed"


def extract_template_tags(uploaded_file) -> list[str]:
    """Reads all undeclared {{ tags }} from an uploaded .docx template."""
    if not uploaded_file:
        return []
    uploaded_file.seek(0)
    doc = DocxTemplate(uploaded_file)
    try:
        return sorted(list(doc.get_undeclared_template_variables()))
    except Exception as e:
        st.error(f"Error reading tags from `{uploaded_file.name}`: {e}")
        return []


def render_docx_bytes(uploaded_file, context: dict) -> bytes:
    """Renders a docxtpl template with the given context and returns raw bytes."""
    uploaded_file.seek(0)
    doc = DocxTemplate(uploaded_file)
    doc.render(context)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_syllabus_lookup(uploaded_pdfs, folder_path_str: str) -> dict[str, dict]:
    """
    Builds a case-insensitive lookup:
        normalized_subject_code (lowercase) -> {"name": filename, "bytes": raw_bytes}
    Supports both browser-uploaded PDFs and a local folder path.
    """
    lookup = {}

    # 1. Load from local folder path if provided
    if folder_path_str and folder_path_str.strip():
        base_dir = Path(folder_path_str.strip()).expanduser()
        if base_dir.is_dir():
            for entry in base_dir.iterdir():
                if entry.is_file() and entry.suffix.lower() == ".pdf":
                    key = entry.stem.strip().lower()
                    lookup[key] = {"name": entry.name, "path": entry, "bytes": None}

    # 2. Load from browser-uploaded PDFs (takes precedence if duplicate)
    if uploaded_pdfs:
        for pdf in uploaded_pdfs:
            key = Path(pdf.name).stem.strip().lower()
            lookup[key] = {"name": pdf.name, "path": None, "bytes": pdf.getvalue()}

    return lookup


def get_syllabus_bytes(entry: dict) -> bytes:
    """Returns PDF bytes from either memory or disk."""
    if entry["bytes"] is not None:
        return entry["bytes"]
    return entry["path"].read_bytes()


def auto_pick_column(columns: list[str], keywords: tuple[str, ...], fallback: int = 0) -> int:
    """Finds the best matching column index for a list of keywords."""
    for idx, col in enumerate(columns):
        col_norm = col.lower().replace("_", " ").strip()
        if any(kw in col_norm for kw in keywords):
            return idx
    return fallback


# ============================================================================
# PAGE UI
# ============================================================================
st.title("📦 Faculty Appointment Order & QP Kit Generator")
st.markdown(
    "Generate personalized **Appointment Orders** and **QP Formats** from a CSV mail merge, "
    "bundle common **Static Attachments**, and automatically attach each faculty member's "
    "**Subject-Code Matched Syllabus PDF**."
)

st.subheader("Upload Files")

col1, col2 = st.columns(2)
with col1:
    csv_file = st.file_uploader("1. Upload Mail Merge Data (.csv)", type=["csv"])
    qp_format_file = st.file_uploader(
        "3. Upload QP Format Template (.docx) — Optional",
        type=["docx"],
        help="Leave empty if you only want to generate Appointment Orders."
    )

with col2:
    appt_order_file = st.file_uploader("2. Upload Appointment Order Template (.docx)", type=["docx"])
    static_files = st.file_uploader(
        "4. Upload Static Attachments (Remuneration Bill, Declaration, etc.)",
        accept_multiple_files=True,
        help="These files will be included in every faculty member's kit."
    )

st.markdown("#### 5. Upload Syllabus PDFs (Dynamic — Matched by Subject Code)")
syl_col1, syl_col2 = st.columns(2)
with syl_col1:
    syllabus_uploads = st.file_uploader(
        "Upload Syllabus PDFs (named by Subject Code, e.g., 1BECC102.pdf)",
        type=["pdf"],
        accept_multiple_files=True,
        help="Select all syllabus PDFs at once. Each faculty member gets only the PDF matching their Subject Code."
    )
with syl_col2:
    syllabus_folder_path = st.text_input(
        "Or Enter Local Syllabus Folder Path (Optional)",
        placeholder="/Users/rajuramacharyalu/Documents/Syllabus_PDFs",
        help="Useful when running locally on macOS/Windows with a large folder of <SubjectCode>.pdf files."
    )
    if syllabus_folder_path.strip():
        folder_check = Path(syllabus_folder_path.strip()).expanduser()
        if folder_check.is_dir():
            pdf_count = sum(1 for p in folder_check.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
            st.caption(f"✅ Folder found ({pdf_count} PDF files detected)")
        else:
            st.error(f"Folder not found: `{syllabus_folder_path}`")


# ============================================================================
# TAG MAPPING & GENERATION WORKFLOW
# ============================================================================
if csv_file and appt_order_file:
    try:
        df = pd.read_csv(csv_file)
        csv_columns = df.columns.tolist()
    except Exception as e:
        st.error(f"Error reading CSV: {e}")
        st.stop()

    appt_tags = extract_template_tags(appt_order_file)
    qp_tags = extract_template_tags(qp_format_file) if qp_format_file else []
    all_tags = sorted(list(set(appt_tags + qp_tags)))

    if not all_tags:
        st.warning(
            "No `{{ tags }}` were detected in the uploaded Word template(s). "
            "Add Jinja tags like `{{ Faculty_Name }}` or `{{ Course_Code }}` to your `.docx` file."
        )
        st.stop()

    st.divider()
    st.subheader("6. Map Word Template Tags to CSV Columns")
    st.info(
        f"Found **{len(all_tags)}** unique tag(s) across your uploaded template(s). "
        "Verify the column mappings below."
    )

    mapping = {}
    map_cols = st.columns(3)
    for i, tag in enumerate(all_tags):
        with map_cols[i % 3]:
            default_idx = 0
            tag_norm = tag.lower().replace("_", "").replace(" ", "")
            for idx, col in enumerate(csv_columns):
                col_norm = col.lower().replace("_", "").replace(" ", "")
                if col_norm == tag_norm:
                    default_idx = idx
                    break

            mapping[tag] = st.selectbox(
                f"Word Tag: **`{tag}`**",
                options=csv_columns,
                index=default_idx,
                key=f"map_{tag}"
            )

    st.divider()
    st.subheader("7. Naming, Syllabus Matching & Packaging Options")

    opt_col1, opt_col2, opt_col3 = st.columns(3)
    with opt_col1:
        faculty_name_col = st.selectbox(
            "Faculty Name / Identifier Column (for folder & file naming)",
            options=csv_columns,
            index=auto_pick_column(csv_columns, ("name", "faculty", "setter", "staff"))
        )

    with opt_col2:
        subject_code_col = st.selectbox(
            "Subject / Course Code Column (for Syllabus PDF matching)",
            options=csv_columns,
            index=auto_pick_column(csv_columns, ("course code", "subject code", "sub code", "code"))
        )

    with opt_col3:
        packaging_mode = st.selectbox(
            "ZIP Packaging Structure",
            options=[
                "Folder per Faculty (inside 1 Master ZIP)",
                "Individual ZIP per Faculty (inside 1 Master ZIP)"
            ],
            help=(
                "'Folder per Faculty' creates clean subfolders. "
                "'Individual ZIP per Faculty' creates ready-to-email .zip attachments for each setter."
            )
        )

    # Build Syllabus Lookup & Show Live Match Status
    syllabus_lookup = build_syllabus_lookup(syllabus_uploads, syllabus_folder_path)
    has_syllabus_source = len(syllabus_lookup) > 0

    st.markdown("#### Review / Edit Mail Merge Data")
    edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

    # Pre-flight Syllabus Match Preview
    if has_syllabus_source:
        codes_in_csv = [
            str(val).strip()
            for val in edited_df[subject_code_col].tolist()
            if not pd.isna(val) and str(val).strip()
        ]
        matched_count = sum(1 for c in codes_in_csv if c.lower() in syllabus_lookup)
        missing_preview = sorted({c for c in codes_in_csv if c.lower() not in syllabus_lookup})

        m1, m2, m3 = st.columns(3)
        m1.metric("Total Faculty Rows", len(edited_df))
        m2.metric("Syllabus PDFs Loaded", len(syllabus_lookup))
        m3.metric("Matched Rows", f"{matched_count} / {len(codes_in_csv)}")

        if missing_preview:
            st.warning(
                f"⚠️ No syllabus PDF found for **{len(missing_preview)}** subject code(s): "
                + ", ".join(missing_preview)
            )
        else:
            st.success("✅ All subject codes in the CSV match a syllabus PDF!")
    else:
        st.info("ℹ️ No syllabus PDFs uploaded or folder path provided. Kits will be generated without syllabus copies.")

    st.divider()

    if st.button("🚀 Generate Faculty Kits (.zip)", type="primary"):
        with st.spinner("Generating documents, attaching static files, and matching syllabus PDFs..."):
            master_zip_buffer = io.BytesIO()
            missing_syllabi = set()
            matched_syllabi_count = 0
            generated_rows = 0

            # Pre-read static attachment bytes once so we don't re-read streams inside the loop
            static_payloads = []
            if static_files:
                for sf in static_files:
                    static_payloads.append((sf.name, sf.getvalue()))

            with zipfile.ZipFile(master_zip_buffer, "w", zipfile.ZIP_DEFLATED) as master_zip:
                for index, row in edited_df.iterrows():
                    # Build docxtpl context
                    context = {}
                    for tag in all_tags:
                        val = row[mapping[tag]]
                        context[tag] = "" if pd.isna(val) else val

                    raw_fac = "" if pd.isna(row[faculty_name_col]) else str(row[faculty_name_col]).strip()
                    raw_code = "" if pd.isna(row[subject_code_col]) else str(row[subject_code_col]).strip()

                    safe_fac = sanitize_filename(raw_fac)
                    safe_code = sanitize_filename(raw_code)
                    kit_label = f"{index + 1:02d}_{safe_code}_{safe_fac}"

                    # 1. Render Appointment Order (.docx)
                    appt_bytes = render_docx_bytes(appt_order_file, context)
                    appt_filename = f"Appointment_Order_{safe_code}_{safe_fac}.docx"

                    # 2. Render QP Format (.docx) if uploaded
                    qp_bytes = None
                    qp_filename = f"QP_Format_{safe_code}.docx"
                    if qp_format_file:
                        qp_bytes = render_docx_bytes(qp_format_file, context)

                    # 3. Look up matching Syllabus PDF
                    syl_entry = syllabus_lookup.get(raw_code.lower()) if (has_syllabus_source and raw_code) else None
                    syl_bytes = None
                    syl_filename = None
                    if syl_entry:
                        syl_bytes = get_syllabus_bytes(syl_entry)
                        syl_filename = f"Syllabus_{syl_entry['name']}"
                        matched_syllabi_count += 1
                    elif has_syllabus_source and raw_code:
                        missing_syllabi.add(raw_code)

                    # 4. Write into Master ZIP (either as subfolder or individual nested ZIP)
                    if packaging_mode == "Folder per Faculty (inside 1 Master ZIP)":
                        master_zip.writestr(f"{kit_label}/{appt_filename}", appt_bytes)
                        if qp_bytes:
                            master_zip.writestr(f"{kit_label}/{qp_filename}", qp_bytes)
                        if syl_bytes:
                            master_zip.writestr(f"{kit_label}/{syl_filename}", syl_bytes)
                        for s_name, s_bytes in static_payloads:
                            master_zip.writestr(f"{kit_label}/{s_name}", s_bytes)
                    else:
                        inner_buf = io.BytesIO()
                        with zipfile.ZipFile(inner_buf, "w", zipfile.ZIP_DEFLATED) as inner_zip:
                            inner_zip.writestr(appt_filename, appt_bytes)
                            if qp_bytes:
                                inner_zip.writestr(qp_filename, qp_bytes)
                            if syl_bytes:
                                inner_zip.writestr(syl_filename, syl_bytes)
                            for s_name, s_bytes in static_payloads:
                                inner_zip.writestr(s_name, s_bytes)
                        master_zip.writestr(f"{kit_label}.zip", inner_buf.getvalue())

                    generated_rows += 1

            st.success(
                f"✅ Generated **{generated_rows}** faculty kit(s)"
                + (f" | Attached **{matched_syllabi_count}** matched syllabus PDF(s)" if has_syllabus_source else "")
                + (f" | Included **{len(static_payloads)}** static attachment(s) per kit" if static_payloads else "")
                + "."
            )

            if missing_syllabi:
                st.warning(
                    "⚠️ The following subject code(s) had no matching `<SubjectCode>.pdf` and were skipped for syllabus attachment: "
                    + ", ".join(sorted(missing_syllabi))
                )

            st.download_button(
                label="📥 Download All Faculty Kits (.zip)",
                data=master_zip_buffer.getvalue(),
                file_name="Faculty_Appointment_Kits.zip",
                mime="application/zip",
                type="primary"
            )
elif csv_file or appt_order_file:
    st.info("Upload both **1. Mail Merge Data (.csv)** and **2. Appointment Order Template (.docx)** to continue.")

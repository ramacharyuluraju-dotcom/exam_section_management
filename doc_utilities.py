import io
from pathlib import Path
import re
import zipfile

from docxtpl import DocxTemplate
import pandas as pd
import streamlit as st

# Note: st.set_page_config is omitted because app.py handles it globally


def sanitize_filename(value: str) -> str:
    """Removes characters that are invalid in file/folder names."""
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", str(value or "").strip())
    cleaned = re.sub(r"[\s_]+", "_", cleaned)
    return cleaned.strip("_") or "Unnamed"


def normalize_code(value: str) -> str:
    """Normalizes a subject code for reliable case- and space-insensitive matching."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def split_subject_codes(raw_value: str) -> list[str]:
    """Splits single or comma/semicolon/slash-separated subject codes cleanly."""
    text = str(raw_value or "").strip()
    if not text:
        return []
    parts = re.split(r"[,;/\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def read_csv_safely(uploaded_csv) -> pd.DataFrame:
    """Reads CSV with UTF-8-BOM / Latin-1 fallback and preserves all values as clean strings."""
    raw_bytes = uploaded_csv.getvalue()
    last_error = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            df = pd.read_csv(
                io.BytesIO(raw_bytes),
                encoding=enc,
                dtype=str,
                keep_default_na=False,
            )
            df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
            return df
        except Exception as err:
            last_error = err
    raise ValueError(f"Could not decode CSV file: {last_error}")


def extract_template_tags(docx_bytes: bytes | None, filename: str = "") -> list[str]:
    """Reads all undeclared {{ tags }} from .docx bytes."""
    if not docx_bytes:
        return []
    try:
        doc = DocxTemplate(io.BytesIO(docx_bytes))
        return sorted(list(doc.get_undeclared_template_variables()))
    except Exception as e:
        st.error(f"Error reading tags from `{filename}`: {e}")
        return []


def render_docx_bytes(docx_bytes: bytes, context: dict) -> bytes:
    """Renders a docxtpl template with XML autoescape enabled (prevents & / < / > corruption)."""
    doc = DocxTemplate(io.BytesIO(docx_bytes))
    doc.render(context, autoescape=True)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def register_syllabus_entry(
    exact_map: dict,
    norm_map: dict,
    prefix_list: list[tuple[str, dict]],
    filename: str,
    pdf_bytes: bytes | None = None,
    file_path: Path | None = None,
) -> None:
    """Registers a syllabus PDF into exact, normalized, and prefix lookup structures."""
    stem = Path(filename).stem.strip()
    entry = {"name": Path(filename).name, "bytes": pdf_bytes, "path": file_path}
    exact_map[stem.lower()] = entry
    norm_key = normalize_code(stem)
    if norm_key:
        norm_map[norm_key] = entry
        prefix_list.append((norm_key, entry))


def build_syllabus_index(uploaded_items, folder_path_str: str) -> tuple[dict, dict, list]:
    """
    Indexes syllabus PDFs from:
      1. A local folder path (recursively scans subfolders too)
      2. Uploaded individual .pdf files AND/OR a .zip archive containing syllabus PDFs
    """
    exact_map: dict[str, dict] = {}
    norm_map: dict[str, dict] = {}
    prefix_list: list[tuple[str, dict]] = []

    # 1. Local folder path (recursive)
    if folder_path_str and folder_path_str.strip():
        base_dir = Path(folder_path_str.strip()).expanduser()
        if base_dir.is_dir():
            for entry in sorted(base_dir.rglob("*")):
                if entry.is_file() and entry.suffix.lower() == ".pdf" and not entry.name.startswith("._"):
                    register_syllabus_entry(exact_map, norm_map, prefix_list, entry.name, file_path=entry)

    # 2. Browser uploads (.pdf or .zip of PDFs) - overrides local if duplicate
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
                    st.error(f"Uploaded syllabus archive `{fname}` is not a valid ZIP file.")

    return exact_map, norm_map, prefix_list


def find_matching_syllabus(
    subject_code: str,
    exact_map: dict,
    norm_map: dict,
    prefix_list: list[tuple[str, dict]],
) -> dict | None:
    """
    Matches a subject code against indexed syllabus PDFs:
      1. Exact stem match (case-insensitive), e.g., 1BECC102 -> 1BECC102.pdf
      2. Normalized alphanumeric match, e.g., 1BECC-102 -> 1BECC102.pdf
      3. Prefix match, e.g., 1BECC102 -> 1BECC102_Syllabus.pdf
    """
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


def get_syllabus_bytes(entry: dict) -> bytes:
    """Returns PDF bytes from memory or disk."""
    if entry["bytes"] is not None:
        return entry["bytes"]
    return entry["path"].read_bytes()


def format_syllabus_filename(original_name: str) -> str:
    """Avoids double-prefixing Syllabus_ if the PDF name already starts with Syllabus."""
    if original_name.lower().startswith("syllabus"):
        return original_name
    return f"Syllabus_{original_name}"


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
        help="Leave empty if you only want to generate Appointment Orders.",
    )

with col2:
    appt_order_file = st.file_uploader("2. Upload Appointment Order Template (.docx)", type=["docx"])
    static_files = st.file_uploader(
        "4. Upload Static Attachments (Remuneration Bill, Declaration, etc.)",
        accept_multiple_files=True,
        help="These files will be included identically in every faculty member's kit.",
    )

st.markdown("#### 5. Upload Syllabus PDFs (Dynamic — Matched by Subject Code)")
syl_col1, syl_col2 = st.columns(2)
with syl_col1:
    syllabus_uploads = st.file_uploader(
        "Upload Syllabus PDFs or a ZIP of Syllabus PDFs (e.g., 1BECC102.pdf or Syllabus_Folder.zip)",
        type=["pdf", "zip"],
        accept_multiple_files=True,
        help="Upload individual <SubjectCode>.pdf files or zip your entire syllabus folder and upload the .zip here.",
    )
with syl_col2:
    syllabus_folder_path = st.text_input(
        "Or Enter Local Syllabus Folder Path (Optional — Local Runs Only)",
        placeholder="/Users/rajuramacharyalu/Documents/Syllabus_PDFs",
        help="Recursively scans this local folder and its subfolders for <SubjectCode>.pdf files.",
    )
    if syllabus_folder_path.strip():
        folder_check = Path(syllabus_folder_path.strip()).expanduser()
        if folder_check.is_dir():
            pdf_count = sum(
                1
                for p in folder_check.rglob("*")
                if p.is_file() and p.suffix.lower() == ".pdf" and not p.name.startswith("._")
            )
            st.caption(f"✅ Folder found ({pdf_count} PDF files detected across folder & subfolders)")
        else:
            st.error(f"Folder not found: `{syllabus_folder_path}`")


# ============================================================================
# TAG MAPPING & GENERATION WORKFLOW
# ============================================================================
if csv_file and appt_order_file:
    try:
        df = read_csv_safely(csv_file)
        csv_columns = df.columns.tolist()
    except Exception as e:
        st.error(f"Error reading CSV: {e}")
        st.stop()

    if not csv_columns:
        st.error("The uploaded CSV has no columns.")
        st.stop()

    appt_raw_bytes = appt_order_file.getvalue()
    qp_raw_bytes = qp_format_file.getvalue() if qp_format_file else None

    appt_tags = extract_template_tags(appt_raw_bytes, appt_order_file.name)
    qp_tags = extract_template_tags(qp_raw_bytes, qp_format_file.name) if qp_raw_bytes else []
    all_tags = sorted(list(set(appt_tags + qp_tags)))

    mapping: dict[str, str] = {}
    if all_tags:
        st.divider()
        st.subheader("6. Map Word Template Tags to CSV Columns")
        st.info(
            f"Found **{len(all_tags)}** unique tag(s) across your uploaded template(s). "
            "Verify the column mappings below."
        )

        map_cols = st.columns(3)
        for i, tag in enumerate(all_tags):
            with map_cols[i % 3]:
                default_idx = 0
                tag_norm = normalize_code(tag)
                for idx, col in enumerate(csv_columns):
                    if normalize_code(col) == tag_norm:
                        default_idx = idx
                        break

                mapping[tag] = st.selectbox(
                    f"Word Tag: **`{tag}`**",
                    options=csv_columns,
                    index=default_idx,
                    key=f"map_{tag}",
                )
    else:
        st.warning(
            "No `{{ tags }}` were detected in the uploaded Word template(s). "
            "Documents will still be copied as-is into each faculty kit."
        )

    st.divider()
    st.subheader("7. Naming, Syllabus Matching & Packaging Options")

    opt_col1, opt_col2, opt_col3 = st.columns(3)
    with opt_col1:
        faculty_name_col = st.selectbox(
            "Faculty Name / Identifier Column (for folder & file naming)",
            options=csv_columns,
            index=auto_pick_column(csv_columns, ("name", "faculty", "setter", "staff")),
        )

    with opt_col2:
        subject_code_col = st.selectbox(
            "Subject / Course Code Column (for Syllabus PDF matching)",
            options=csv_columns,
            index=auto_pick_column(csv_columns, ("course code", "subject code", "sub code", "code")),
        )

    with opt_col3:
        packaging_mode = st.selectbox(
            "ZIP Packaging Structure",
            options=[
                "Folder per Faculty (inside 1 Master ZIP)",
                "Individual ZIP per Faculty (inside 1 Master ZIP)",
            ],
            help=(
                "'Folder per Faculty' creates clean subfolders. "
                "'Individual ZIP per Faculty' creates ready-to-email .zip attachments for each setter."
            ),
        )

    # Build Syllabus Lookup Index
    exact_map, norm_map, prefix_list = build_syllabus_index(syllabus_uploads, syllabus_folder_path)
    has_syllabus_source = len(exact_map) > 0

    st.markdown("#### Review / Edit Mail Merge Data")
    edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

    # Filter out completely blank rows from data_editor
    valid_df = edited_df[
        edited_df.apply(lambda r: any(str(v).strip() != "" for v in r), axis=1)
    ].copy()

    # Pre-flight Syllabus Match Preview
    if has_syllabus_source:
        all_codes = []
        matched_rows = 0
        missing_preview = set()

        for _, row in valid_df.iterrows():
            row_codes = split_subject_codes(row.get(subject_code_col, ""))
            if not row_codes:
                continue
            row_all_matched = True
            for c in row_codes:
                all_codes.append(c)
                if not find_matching_syllabus(c, exact_map, norm_map, prefix_list):
                    missing_preview.add(c)
                    row_all_matched = False
            if row_all_matched:
                matched_rows += 1

        m1, m2, m3 = st.columns(3)
        m1.metric("Total Faculty Rows", len(valid_df))
        m2.metric("Syllabus PDFs Loaded", len(exact_map))
        m3.metric("Fully Matched Rows", f"{matched_rows} / {len(valid_df)}")

        if missing_preview:
            st.warning(
                f"⚠️ No syllabus PDF found for **{len(missing_preview)}** subject code(s): "
                + ", ".join(sorted(missing_preview))
            )
        else:
            st.success("✅ All subject codes in the CSV match a syllabus PDF!")
    else:
        st.info("ℹ️ No syllabus PDFs uploaded or folder path provided. Kits will be generated without syllabus copies.")

    st.divider()

    if st.button("🚀 Generate Faculty Kits (.zip)", type="primary"):
        if valid_df.empty:
            st.error("No non-empty rows found in the CSV table.")
        else:
            with st.spinner("Generating documents, attaching static files, and matching syllabus PDFs..."):
                master_zip_buffer = io.BytesIO()
                missing_syllabi = set()
                matched_syllabi_count = 0
                generated_rows = 0

                static_payloads = [(sf.name, sf.getvalue()) for sf in (static_files or [])]

                with zipfile.ZipFile(master_zip_buffer, "w", zipfile.ZIP_DEFLATED) as master_zip:
                    for row_num, (_, row) in enumerate(valid_df.iterrows(), start=1):
                        context = {
                            tag: str(row.get(mapping[tag], "")).strip()
                            for tag in all_tags
                        }

                        raw_fac = str(row.get(faculty_name_col, "")).strip()
                        raw_code_cell = str(row.get(subject_code_col, "")).strip()
                        row_codes = split_subject_codes(raw_code_cell)

                        safe_fac = sanitize_filename(raw_fac)
                        safe_code = sanitize_filename(row_codes[0] if row_codes else raw_code_cell)
                        kit_label = f"{row_num:02d}_{safe_code}_{safe_fac}"

                        # 1. Render Appointment Order (.docx)
                        appt_bytes = render_docx_bytes(appt_raw_bytes, context)
                        appt_filename = f"Appointment_Order_{safe_code}_{safe_fac}.docx"

                        # 2. Render QP Format (.docx) if uploaded
                        qp_bytes = None
                        qp_filename = f"QP_Format_{safe_code}.docx"
                        if qp_raw_bytes:
                            qp_bytes = render_docx_bytes(qp_raw_bytes, context)

                        # 3. Look up matching Syllabus PDF(s)
                        matched_pdfs: list[tuple[str, bytes]] = []
                        if has_syllabus_source:
                            seen_pdf_names = set()
                            for code in row_codes:
                                syl_entry = find_matching_syllabus(code, exact_map, norm_map, prefix_list)
                                if syl_entry:
                                    syl_fname = format_syllabus_filename(syl_entry["name"])
                                    if syl_fname not in seen_pdf_names:
                                        matched_pdfs.append((syl_fname, get_syllabus_bytes(syl_entry)))
                                        seen_pdf_names.add(syl_fname)
                                        matched_syllabi_count += 1
                                else:
                                    missing_syllabi.add(code)

                        # 4. Write into Master ZIP
                        if packaging_mode == "Folder per Faculty (inside 1 Master ZIP)":
                            master_zip.writestr(f"{kit_label}/{appt_filename}", appt_bytes)
                            if qp_bytes:
                                master_zip.writestr(f"{kit_label}/{qp_filename}", qp_bytes)
                            for syl_fname, syl_bytes in matched_pdfs:
                                master_zip.writestr(f"{kit_label}/{syl_fname}", syl_bytes)
                            for s_name, s_bytes in static_payloads:
                                master_zip.writestr(f"{kit_label}/{s_name}", s_bytes)
                        else:
                            inner_buf = io.BytesIO()
                            with zipfile.ZipFile(inner_buf, "w", zipfile.ZIP_DEFLATED) as inner_zip:
                                inner_zip.writestr(appt_filename, appt_bytes)
                                if qp_bytes:
                                    inner_zip.writestr(qp_filename, qp_bytes)
                                for syl_fname, syl_bytes in matched_pdfs:
                                    inner_zip.writestr(syl_fname, syl_bytes)
                                for s_name, s_bytes in static_payloads:
                                    inner_zip.writestr(s_name, s_bytes)
                            master_zip.writestr(f"{kit_label}.zip", inner_buf.getvalue())

                        generated_rows += 1

                # Store in session_state so download button click doesn't wipe out results on rerun
                st.session_state["generated_kit_zip"] = master_zip_buffer.getvalue()
                st.session_state["generated_kit_summary"] = {
                    "rows": generated_rows,
                    "matched_syllabi": matched_syllabi_count,
                    "has_syllabus_source": has_syllabus_source,
                    "static_count": len(static_payloads),
                    "missing_syllabi": sorted(missing_syllabi),
                }

    if "generated_kit_zip" in st.session_state:
        summary = st.session_state["generated_kit_summary"]
        st.success(
            f"✅ Generated **{summary['rows']}** faculty kit(s)"
            + (f" | Attached **{summary['matched_syllabi']}** matched syllabus PDF(s)" if summary["has_syllabus_source"] else "")
            + (f" | Included **{summary['static_count']}** static attachment(s) per kit" if summary["static_count"] else "")
            + "."
        )
        if summary["missing_syllabi"]:
            st.warning(
                "⚠️ The following subject code(s) had no matching syllabus PDF and were skipped: "
                + ", ".join(summary["missing_syllabi"])
            )
        st.download_button(
            label="📥 Download All Faculty Kits (.zip)",
            data=st.session_state["generated_kit_zip"],
            file_name="Faculty_Appointment_Kits.zip",
            mime="application/zip",
            type="primary",
        )

elif csv_file or appt_order_file:
    st.info("Upload both **1. Mail Merge Data (.csv)** and **2. Appointment Order Template (.docx)** to continue.")

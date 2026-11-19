from __future__ import annotations

import io
from pathlib import Path
import re
import zipfile

from docxtpl import DocxTemplate
import pandas as pd
import streamlit as st

# Note: st.set_page_config is omitted because app.py handles it globally


def clean_cell(value) -> str:
    """Safely converts a DataFrame cell to a stripped string without turning None/NaN into 'None'."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def sanitize_filename(value: str) -> str:
    """Removes characters that are invalid in file/folder names."""
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", str(value or "").strip())
    cleaned = re.sub(r"[\s_]+", "_", cleaned)
    return cleaned.strip("_") or "Unnamed"


def normalize_code(value: str) -> str:
    """Normalizes a subject code for reliable case- and punctuation-insensitive matching."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def split_subject_codes(raw_value) -> list[str]:
    """Splits single or comma/semicolon/slash-separated subject codes cleanly."""
    text = clean_cell(raw_value)
    if not text:
        return []
    parts = re.split(r"[,;/\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def read_csv_safely(uploaded_csv) -> pd.DataFrame:
    """Reads CSV with UTF-8-BOM / cp1252 / latin1 fallback and keeps all fields as clean strings."""
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
    """Extracts all undeclared {{ tags }} from .docx bytes."""
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


def build_syllabus_index(uploaded_items, folder_path_str: str | None) -> tuple[dict, dict, list]:
    """
    Indexes syllabus PDFs from either a local folder path (recursively)
    or uploaded individual .pdf files / .zip archive of PDFs.
    """
    exact_map: dict[str, dict] = {}
    norm_map: dict[str, dict] = {}
    prefix_list: list[tuple[str, dict]] = []

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
                    st.error(f"Uploaded archive `{fname}` is not a valid ZIP file.")

    return exact_map, norm_map, prefix_list


def find_matching_syllabus(
    subject_code: str,
    exact_map: dict,
    norm_map: dict,
    prefix_list: list[tuple[str, dict]],
) -> dict | None:
    """
    Matches a subject code against indexed syllabus PDFs:
      1. Exact case-insensitive stem match (1BECC102 -> 1BECC102.pdf)
      2. Normalized alphanumeric match (1BECC-102 -> 1BECC102.pdf)
      3. Prefix match (1BECC102 -> 1BECC102_Syllabus.pdf)
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
    "attach common **Static Attachments**, and automatically match each faculty member's "
    "**Subject-Code Syllabus PDF**."
)

st.subheader("Upload Files")

col1, col2 = st.columns(2)

with col1:
    csv_file = st.file_uploader(
        "1. Upload Mail Merge Data (.csv)",
        type=["csv"],
        help="CSV containing faculty details and subject codes",
    )

    appointment_template = st.file_uploader(
        "2. Upload Appointment Order Template (.docx)",
        type=["docx"],
    )

with col2:
    qp_template = st.file_uploader(
        "3. Upload QP Format Template (.docx) — Optional",
        type=["docx"],
        help="Leave empty if you only need Appointment Orders.",
    )

    static_files = st.file_uploader(
        "4. Upload Static Attachments (Remuneration Bill, Declaration, etc.)",
        type=["pdf", "docx"],
        accept_multiple_files=True,
        help="Common files included for every faculty kit.",
    )

st.divider()

# ---------- SECTION 5: SYLLABUS PDFs ----------
st.subheader("5. Syllabus PDFs (Optional)")

syllabus_mode = st.radio(
    "How do you want to provide syllabus PDFs?",
    options=["Folder Path (Recommended)", "Upload Individual PDFs / ZIP"],
    horizontal=True,
)

syllabus_folder = None
uploaded_syllabus_files = None

if syllabus_mode == "Folder Path (Recommended)":
    syllabus_folder = st.text_input(
        "Syllabus Folder Path",
        placeholder="/Users/rajuramacharyalu/Documents/Syllabus_PDFs",
        help="Folder containing PDFs named as subject codes (e.g. 1BECC102.pdf, BCS502.pdf). Subfolders are scanned automatically.",
    )
    if syllabus_folder and syllabus_folder.strip():
        folder_check = Path(syllabus_folder.strip()).expanduser()
        if folder_check.is_dir():
            pdf_count = sum(
                1
                for p in folder_check.rglob("*")
                if p.is_file() and p.suffix.lower() == ".pdf" and not p.name.startswith("._")
            )
            st.caption(f"✅ Folder found ({pdf_count} PDF file(s) detected)")
        else:
            st.error(f"Folder not found: `{syllabus_folder}`")
else:
    uploaded_syllabus_files = st.file_uploader(
        "Upload Syllabus PDFs (named as SubjectCode.pdf) or a .zip of PDFs",
        type=["pdf", "zip"],
        accept_multiple_files=True,
        help="Files should be named like 1BECC102.pdf, BCS502.pdf, etc. You can also upload a single .zip containing the folder.",
    )

has_syllabus_input = bool(
    (syllabus_folder and syllabus_folder.strip()) or uploaded_syllabus_files
)

# Sync checkbox automatically when a syllabus source is first provided
if "prev_has_syllabus_input" not in st.session_state:
    st.session_state["prev_has_syllabus_input"] = False
if has_syllabus_input and not st.session_state["prev_has_syllabus_input"]:
    st.session_state["include_syllabus_chk"] = True
elif not has_syllabus_input:
    st.session_state["include_syllabus_chk"] = False
st.session_state["prev_has_syllabus_input"] = has_syllabus_input

include_syllabus = st.checkbox(
    "Include matching syllabus PDFs in the final ZIP",
    key="include_syllabus_chk",
    disabled=not has_syllabus_input,
)

# ============================================================================
# SECTIONS 6 & 7 (HEADERS ALWAYS VISIBLE)
# ============================================================================
st.divider()
st.subheader("6. Map Word Template Tags to CSV Columns")

if not (csv_file and appointment_template):
    st.info(
        "Upload both **1. Mail Merge Data (.csv)** and **2. Appointment Order Template (.docx)** "
        "above to unlock tag mapping."
    )
    st.divider()
    st.subheader("7. Naming, Syllabus Matching & ZIP Structure")
    st.info("Once Step 6 is loaded, your editable preview table, syllabus match check, and ZIP generator will appear here.")
else:
    try:
        df = read_csv_safely(csv_file)
        csv_columns = df.columns.tolist()
    except Exception as e:
        st.error(f"Error reading CSV: {e}")
        st.stop()

    if not csv_columns:
        st.error("The uploaded CSV has no columns.")
        st.stop()

    appt_raw_bytes = appointment_template.getvalue()
    qp_raw_bytes = qp_template.getvalue() if qp_template else None

    appt_tags = extract_template_tags(appt_raw_bytes, appointment_template.name)
    qp_tags = extract_template_tags(qp_raw_bytes, qp_template.name) if qp_raw_bytes else []
    all_tags = sorted(list(set(appt_tags + qp_tags)))

    mapping: dict[str, str] = {}
    if all_tags:
        st.info(
            f"Detected **{len(all_tags)}** unique `{{{{ tag }}}}` placeholder(s). "
            "Confirm each tag maps to the right CSV column."
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
            "Templates will be copied as-is into the ZIP."
        )

    st.divider()
    st.subheader("7. Naming, Syllabus Matching & ZIP Structure")

    opt_col1, opt_col2, opt_col3 = st.columns(3)
    with opt_col1:
        faculty_name_col = st.selectbox(
            "Faculty Name / ID Column (for naming)",
            options=csv_columns,
            index=auto_pick_column(csv_columns, ("name", "faculty", "setter", "staff")),
        )

    with opt_col2:
        subject_code_col = st.selectbox(
            "Subject Code Column (for Syllabus PDF matching)",
            options=csv_columns,
            index=auto_pick_column(csv_columns, ("course code", "subject code", "sub code", "code")),
        )

    with opt_col3:
        zip_layout = st.selectbox(
            "ZIP Output Layout",
            options=[
                "Folder per Faculty (with matched Syllabus inside)",
                "Shared Syllabus/ Folder + Documents/ Folder",
                "Individual ZIP per Faculty (ready to email)",
            ],
            help=(
                "Choose whether each faculty gets their own folder/ZIP with their syllabus, "
                "or all matched syllabi are grouped inside one top-level Syllabus/ folder."
            ),
        )

    st.markdown("#### Review / Edit Mail Merge Data")
    edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

    valid_df = edited_df[
        edited_df.apply(lambda r: any(clean_cell(v) != "" for v in r), axis=1)
    ].copy()

    # Build Syllabus Index & Live Pre-flight Check
    exact_map, norm_map, prefix_list = (
        build_syllabus_index(uploaded_syllabus_files, syllabus_folder)
        if include_syllabus
        else ({}, {}, [])
    )
    syllabus_ready = include_syllabus and len(exact_map) > 0

    if include_syllabus:
        if syllabus_ready:
            matched_rows = 0
            missing_preview = set()
            for _, row in valid_df.iterrows():
                row_codes = split_subject_codes(row.get(subject_code_col, ""))
                if not row_codes:
                    continue
                all_ok = True
                for code in row_codes:
                    if not find_matching_syllabus(code, exact_map, norm_map, prefix_list):
                        missing_preview.add(code)
                        all_ok = False
                if all_ok:
                    matched_rows += 1

            m1, m2, m3 = st.columns(3)
            m1.metric("Faculty Rows", len(valid_df))
            m2.metric("Syllabus PDFs Indexed", len(exact_map))
            m3.metric("Fully Matched Rows", f"{matched_rows} / {len(valid_df)}")

            if missing_preview:
                st.warning(
                    f"⚠️ Missing syllabus PDF for **{len(missing_preview)}** subject code(s): "
                    + ", ".join(sorted(missing_preview))
                )
            else:
                st.success("✅ Every subject code in the CSV matches a syllabus PDF.")
        else:
            st.warning("⚠️ Syllabus inclusion is checked, but no PDFs were found in the specified folder or upload.")

    st.divider()

    if st.button("🚀 Generate ZIP Package", type="primary"):
        if valid_df.empty:
            st.error("No non-empty rows found in the CSV table.")
        else:
            with st.spinner("Generating documents and bundling syllabus PDFs..."):
                master_zip_buffer = io.BytesIO()
                static_payloads = [(sf.name, sf.getvalue()) for sf in (static_files or [])]

                missing_syllabi = set()
                shared_syllabi_added = set()
                matched_syllabi_count = 0
                generated_rows = 0

                with zipfile.ZipFile(master_zip_buffer, "w", zipfile.ZIP_DEFLATED) as master_zip:
                    if zip_layout == "Shared Syllabus/ Folder + Documents/ Folder" and static_payloads:
                        for s_name, s_bytes in static_payloads:
                            master_zip.writestr(f"Static_Attachments/{s_name}", s_bytes)

                    for row_num, (_, row) in enumerate(valid_df.iterrows(), start=1):
                        context = {
                            tag: clean_cell(row.get(mapping[tag], ""))
                            for tag in all_tags
                        }

                        raw_fac = clean_cell(row.get(faculty_name_col, ""))
                        raw_code_cell = clean_cell(row.get(subject_code_col, ""))
                        row_codes = split_subject_codes(raw_code_cell)

                        safe_fac = sanitize_filename(raw_fac)
                        safe_code = sanitize_filename(row_codes[0] if row_codes else raw_code_cell)
                        kit_label = f"{row_num:02d}_{safe_code}_{safe_fac}"

                        appt_bytes = render_docx_bytes(appt_raw_bytes, context)
                        appt_filename = f"Appointment_Order_{safe_code}_{safe_fac}.docx"

                        qp_bytes = render_docx_bytes(qp_raw_bytes, context) if qp_raw_bytes else None
                        qp_filename = f"QP_Format_{safe_code}_{safe_fac}.docx"

                        row_syllabi: list[tuple[str, str, bytes]] = []
                        if syllabus_ready:
                            seen_for_row = set()
                            for code in row_codes:
                                syl_entry = find_matching_syllabus(code, exact_map, norm_map, prefix_list)
                                if syl_entry:
                                    orig_name = syl_entry["name"]
                                    if orig_name not in seen_for_row:
                                        row_syllabi.append(
                                            (orig_name, format_syllabus_filename(orig_name), get_syllabus_bytes(syl_entry))
                                        )
                                        seen_for_row.add(orig_name)
                                else:
                                    missing_syllabi.add(code)

                        if zip_layout == "Shared Syllabus/ Folder + Documents/ Folder":
                            master_zip.writestr(f"Documents/{appt_filename}", appt_bytes)
                            if qp_bytes:
                                master_zip.writestr(f"Documents/{qp_filename}", qp_bytes)
                            for orig_name, _, syl_bytes in row_syllabi:
                                if orig_name.lower() not in shared_syllabi_added:
                                    master_zip.writestr(f"Syllabus/{orig_name}", syl_bytes)
                                    shared_syllabi_added.add(orig_name.lower())
                                    matched_syllabi_count += 1

                        elif zip_layout == "Folder per Faculty (with matched Syllabus inside)":
                            master_zip.writestr(f"{kit_label}/{appt_filename}", appt_bytes)
                            if qp_bytes:
                                master_zip.writestr(f"{kit_label}/{qp_filename}", qp_bytes)
                            for _, syl_fname, syl_bytes in row_syllabi:
                                master_zip.writestr(f"{kit_label}/{syl_fname}", syl_bytes)
                                matched_syllabi_count += 1
                            for s_name, s_bytes in static_payloads:
                                master_zip.writestr(f"{kit_label}/{s_name}", s_bytes)

                        else:
                            inner_buf = io.BytesIO()
                            with zipfile.ZipFile(inner_buf, "w", zipfile.ZIP_DEFLATED) as inner_zip:
                                inner_zip.writestr(appt_filename, appt_bytes)
                                if qp_bytes:
                                    inner_zip.writestr(qp_filename, qp_bytes)
                                for _, syl_fname, syl_bytes in row_syllabi:
                                    inner_zip.writestr(syl_fname, syl_bytes)
                                    matched_syllabi_count += 1
                                for s_name, s_bytes in static_payloads:
                                    inner_zip.writestr(s_name, s_bytes)
                            master_zip.writestr(f"{kit_label}.zip", inner_buf.getvalue())

                        generated_rows += 1

                st.session_state["kit_zip_bytes"] = master_zip_buffer.getvalue()
                st.session_state["kit_zip_summary"] = {
                    "rows": generated_rows,
                    "matched_syllabi": matched_syllabi_count,
                    "syllabus_ready": syllabus_ready,
                    "static_count": len(static_payloads),
                    "missing_syllabi": sorted(missing_syllabi),
                    "layout": zip_layout,
                }

    if "kit_zip_bytes" in st.session_state:
        summary = st.session_state["kit_zip_summary"]
        st.success(
            f"✅ Generated **{summary['rows']}** faculty package(s)"
            + (f" | Bundled **{summary['matched_syllabi']}** matched syllabus PDF(s)" if summary["syllabus_ready"] else "")
            + (f" | Static attachments: **{summary['static_count']}**" if summary["static_count"] else "")
            + "."
        )

        if summary["missing_syllabi"]:
            st.warning(
                "⚠️ No matching syllabus PDF found for subject code(s): "
                + ", ".join(summary["missing_syllabi"])
            )

        st.download_button(
            label="📥 Download Generated ZIP",
            data=st.session_state["kit_zip_bytes"],
            file_name="Faculty_Appointment_Kits_with_Syllabus.zip",
            mime="application/zip",
            type="primary",
        )

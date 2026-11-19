import io
from pathlib import Path
import zipfile

from docxtpl import DocxTemplate
import pandas as pd
import streamlit as st

# Note: st.set_page_config is removed because app.py handles it globally

st.title("🖨️ Universal Document Generator")
st.markdown(
    "Upload any Word template (`.docx`) with `{{ tags }}` and a CSV file. "
    "Optionally include matching syllabus PDFs (`<SubjectCode>.pdf`) from a local folder inside the ZIP export."
)

col1, col2 = st.columns(2)

with col1:
    template_file = st.file_uploader("1. Upload Word Template (.docx)", type=["docx"])

with col2:
    csv_file = st.file_uploader("2. Upload Data (.csv)", type=["csv"])

syllabus_folder_input = st.text_input(
    "3. Syllabus PDF Folder Path (Optional)",
    placeholder="/Users/rajuramacharyalu/Documents/Syllabus_PDFs",
    help="Folder containing individual PDFs named by subject code, e.g., 1BECC102.pdf"
)

include_syllabus = st.checkbox(
    "Include matching syllabus PDFs in the ZIP file",
    value=bool(syllabus_folder_input.strip()),
    disabled=not bool(syllabus_folder_input.strip())
)


def find_syllabus_pdf(folder_path: str, subject_code: str) -> Path | None:
    """Finds <subject_code>.pdf in folder_path using exact then case-insensitive matching."""
    clean_code = str(subject_code or "").strip()
    if not clean_code or not folder_path:
        return None

    base_dir = Path(folder_path).expanduser()
    if not base_dir.exists() or not base_dir.is_dir():
        return None

    exact_match = base_dir / f"{clean_code}.pdf"
    if exact_match.is_file():
        return exact_match

    target_lower = f"{clean_code.lower()}.pdf"
    for entry in base_dir.iterdir():
        if entry.is_file() and entry.name.lower() == target_lower:
            return entry

    return None


if template_file and csv_file:
    # 1. Load the CSV and get headers
    try:
        df = pd.read_csv(csv_file)
        csv_columns = df.columns.tolist()
    except Exception as e:
        st.error(f"Error reading CSV: {e}")
        st.stop()

    # 2. Load the Template and extract all {{ tags }}
    template_file.seek(0)
    doc = DocxTemplate(template_file)

    try:
        template_tags = list(doc.get_undeclared_template_variables())
    except Exception as e:
        st.error(f"Error reading template tags. Ensure they are formatted as {{{{ tag }}}}. Error: {e}")
        template_tags = []

    if template_tags:
        st.divider()
        st.subheader("4. Map Template Tags to CSV Columns")
        st.info("Match the tags found in your Word document to the correct columns in your CSV.")

        mapping = {}
        map_cols = st.columns(3)
        for i, tag in enumerate(template_tags):
            with map_cols[i % 3]:
                default_index = 0
                for idx, col in enumerate(csv_columns):
                    if col.lower() == tag.lower():
                        default_index = idx
                        break

                mapping[tag] = st.selectbox(
                    f"Word Tag: **{tag}**",
                    options=csv_columns,
                    index=default_index,
                    key=f"map_{tag}"
                )

        st.divider()
        st.subheader("5. Review Data & Generate")

        name_col1, name_col2 = st.columns(2)
        with name_col1:
            file_name_col = st.selectbox(
                "Which CSV column should be used to name the generated files?",
                options=csv_columns
            )

        with name_col2:
            default_sub_idx = 0
            for idx, col in enumerate(csv_columns):
                if any(k in col.lower() for k in ("sub", "course", "code")):
                    default_sub_idx = idx
                    break
            subject_code_col = st.selectbox(
                "Which CSV column holds the Subject Code for syllabus PDF matching?",
                options=csv_columns,
                index=default_sub_idx,
                disabled=not include_syllabus
            )

        if include_syllabus and not Path(syllabus_folder_input).expanduser().is_dir():
            st.error(f"Syllabus folder not found: `{syllabus_folder_input}`")

        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

        if st.button("Generate Documents", type="primary"):
            with st.spinner("Merging documents and bundling syllabus PDFs..."):
                zip_buffer = io.BytesIO()
                added_syllabi = set()
                missing_syllabi = set()

                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED, False) as zip_file:
                    for index, row in edited_df.iterrows():
                        template_file.seek(0)
                        current_doc = DocxTemplate(template_file)

                        context = {}
                        for tag in template_tags:
                            val = row[mapping[tag]]
                            context[tag] = "" if pd.isna(val) else val

                        current_doc.render(context)
                        doc_buffer = io.BytesIO()
                        current_doc.save(doc_buffer)

                        safe_name = str(row[file_name_col]).replace("/", "_").replace("\\", "_").strip()
                        docx_name = f"Documents/Document_{safe_name}_{index + 1}.docx"
                        zip_file.writestr(docx_name, doc_buffer.getvalue())

                        if include_syllabus:
                            raw_code = "" if pd.isna(row[subject_code_col]) else str(row[subject_code_col]).strip()
                            if raw_code:
                                matched_pdf = find_syllabus_pdf(syllabus_folder_input, raw_code)
                                if matched_pdf:
                                    code_key = raw_code.upper()
                                    if code_key not in added_syllabi:
                                        zip_file.write(matched_pdf, arcname=f"Syllabus/{matched_pdf.name}")
                                        added_syllabi.add(code_key)
                                else:
                                    missing_syllabi.add(raw_code)

                st.success(
                    f"✅ Successfully generated {len(edited_df)} documents!"
                    + (f" Included {len(added_syllabi)} syllabus PDF(s)." if include_syllabus else "")
                )

                if missing_syllabi:
                    st.warning(
                        "⚠️ Missing syllabus PDF in folder for subject code(s): "
                        + ", ".join(sorted(missing_syllabi))
                    )

                st.download_button(
                    label="📥 Download All Documents (.zip)",
                    data=zip_buffer.getvalue(),
                    file_name="Generated_Documents.zip",
                    mime="application/zip",
                    type="primary"
                )
    else:
        st.warning("No `{{ tags }}` found in the uploaded Word document. Please add tags like `{{ StudentName }}` to your Word file.")

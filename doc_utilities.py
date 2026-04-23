import streamlit as st
import pandas as pd
from docxtpl import DocxTemplate
import zipfile
import io

# Note: st.set_page_config is removed because app.py handles it globally

st.title("🖨️ Universal Document Generator")
st.markdown("Upload any Word template (`.docx`) with `{{ tags }}` and a CSV file. The system will map your data and generate a batch of custom Word documents.")

col1, col2 = st.columns(2)

with col1:
    template_file = st.file_uploader("1. Upload Word Template (.docx)", type=["docx"])

with col2:
    csv_file = st.file_uploader("2. Upload Data (.csv)", type=["csv"])

if template_file and csv_file:
    # 1. Load the CSV and get headers
    try:
        df = pd.read_csv(csv_file)
        csv_columns = df.columns.tolist()
    except Exception as e:
        st.error(f"Error reading CSV: {e}")
        st.stop()
    
    # 2. Load the Template and extract all {{ tags }}
    # We must "rewind" the file before reading it
    template_file.seek(0)
    doc = DocxTemplate(template_file)
    
    try:
        template_tags = list(doc.get_undeclared_template_variables())
    except Exception as e:
        st.error(f"Error reading template tags. Ensure they are formatted as {{{{ tag }}}}. Error: {e}")
        template_tags = []

    if template_tags:
        st.divider()
        st.subheader("3. Map Template Tags to CSV Columns")
        st.info("Match the tags found in your Word document to the correct columns in your CSV.")
        
        # Create a dictionary to store the user's mapping choices
        mapping = {}
        
        # Display the mapping UI in columns for a cleaner look
        map_cols = st.columns(3)
        for i, tag in enumerate(template_tags):
            with map_cols[i % 3]:
                # Try to auto-select if the names match exactly (ignoring case)
                default_index = 0
                for idx, col in enumerate(csv_columns):
                    if col.lower() == tag.lower():
                        default_index = idx
                        break
                        
                # Create a dropdown for each tag
                mapping[tag] = st.selectbox(
                    f"Word Tag: **{tag}**", 
                    options=csv_columns, 
                    index=default_index,
                    key=f"map_{tag}"
                )
        
        st.divider()
        st.subheader("4. Review Data & Generate")
        
        # Name the output files based on a specific column
        file_name_col = st.selectbox("Which CSV column should be used to name the generated files?", options=csv_columns)
        
        # Show a preview of the editable data
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

        if st.button("Generate Documents", type="primary"):
            with st.spinner("Merging documents..."):
                zip_buffer = io.BytesIO()
                
                with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                    for index, row in edited_df.iterrows():
                        
                        # Rewind the file stream for every new document generation
                        template_file.seek(0)
                        current_doc = DocxTemplate(template_file)
                        
                        # Create the context dictionary using the USER'S MAPPING
                        # Handle NaN values smoothly
                        context = {}
                        for tag in template_tags:
                            val = row[mapping[tag]]
                            context[tag] = "" if pd.isna(val) else val
                        
                        # Render and save
                        current_doc.render(context)
                        doc_buffer = io.BytesIO()
                        current_doc.save(doc_buffer)
                        
                        # Clean the file name to avoid invalid characters
                        safe_name = str(row[file_name_col]).replace("/", "_").replace("\\", "_")
                        file_name = f"Document_{safe_name}_{index+1}.docx"
                        
                        zip_file.writestr(file_name, doc_buffer.getvalue())

                st.success(f"✅ Successfully generated {len(edited_df)} documents!")
                
                st.download_button(
                    label="📥 Download All Documents (.zip)",
                    data=zip_buffer.getvalue(),
                    file_name="Generated_Documents.zip",
                    mime="application/zip",
                    type="primary"
                )
    else:
        st.warning("No `{{ tags }}` found in the uploaded Word document. Please add tags like `{{ StudentName }}` to your Word file.")
import streamlit as st
import pandas as pd
import io
import zipfile
from docxtpl import DocxTemplate

st.set_page_config(page_title="COE Appointment Packager", page_icon="📦", layout="wide")

st.title("📦 COE Appointment Packager")
st.markdown("Generates personalized **Appointment Orders** and **QP Templates**, bundling them into ready-to-email `.zip` folders for dispatch.")

# --- FILE UPLOADS ---
st.sidebar.header("Upload Files")
uploaded_csv = st.sidebar.file_uploader("1. Upload Mail Merge Data (.csv)", type=["csv"])
uploaded_appointment_template = st.sidebar.file_uploader("2. Upload Appointment Order Template (.docx)", type=["docx"])
uploaded_qp_template = st.sidebar.file_uploader("3. Upload QP Format Template (.docx)", type=["docx"])
uploaded_attachments = st.sidebar.file_uploader("4. Upload Static Attachments (Remuneration Bill, Declaration, etc.)", accept_multiple_files=True)

if uploaded_csv and uploaded_appointment_template and uploaded_qp_template:
    try:
        # 1. Safely read and clean the CSV file to strictly prevent Pandas ParserErrors
        file_content = uploaded_csv.read().decode("utf-8")
        if file_content.startswith("data:text/csv"):
            file_content = file_content.split(",", 1)[1] # Instantly strip corrupted URI header
            
        df = pd.read_csv(io.StringIO(file_content), on_bad_lines='skip', engine='python')
        
        st.subheader("Data Preview")
        st.dataframe(df, use_container_width=True)
        
        st.info("""
        **How variables work:**
        Every column header in your CSV is now a usable variable in your Word documents! 
        For example, if your CSV has a column named `Last_date`, you can type `{{ Last_date }}` anywhere in either `.docx` file.
        """)

        # --- EXECUTION ---
        st.subheader("Package Files")
        st.write("Click below to generate a zip file containing individual setter packages.")
        
        if st.button("🚀 Generate Setter Packages", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            try:
                # 1. Read templates and attachments into memory once
                appointment_bytes = uploaded_appointment_template.read()
                qp_bytes = uploaded_qp_template.read()
                static_files = {att.name: att.read() for att in uploaded_attachments} if uploaded_attachments else {}
                
                # 2. Create the MASTER zip file in memory
                master_zip_buffer = io.BytesIO()
                
                total_setters = len(df)
                processed_count = 0
                
                with zipfile.ZipFile(master_zip_buffer, "w", zipfile.ZIP_DEFLATED) as master_zip:
                    
                    for index, row in df.iterrows():
                        # Extract core info for naming files (Fallback if names differ in CSV)
                        name = str(row.get('Setter_Name', row.get('Name', f'Setter_{index}'))).strip()
                        email = str(row.get('Email', '')).strip()
                        course = str(row.get('Course_Code', row.get('Course', f'Course_{index}'))).strip()
                        
                        if pd.isna(email) or "@" not in email:
                            continue
                            
                        status_text.text(f"Packaging files for {name} ({course})...")
                        
                        # Convert row to dict, automatically replacing spaces in CSV headers with underscores
                        raw_context = {str(k).strip().replace(' ', '_'): ('' if pd.isna(v) else str(v)) for k, v in row.to_dict().items()}
                        
                        context = {**raw_context}
                        
                        # --- SMART BRIDGING FOR MISMATCHED TEMPLATES ---
                        if 'Name' in context and 'Setter_Name' not in context: 
                            context['Setter_Name'] = context['Name']
                        if 'Course_Name' in context and 'Course_Title' not in context: 
                            context['Course_Title'] = context['Course_Name']
                        elif 'Course_Title' in context and 'Course_Name' not in context: 
                            context['Course_Name'] = context['Course_Title']
                        if 'AY' in context and 'Academic_Year' not in context: 
                            context['Academic_Year'] = context['AY']
                        elif 'Academic_Year' in context and 'AY' not in context: 
                            context['AY'] = context['Academic_Year']
                        if 'ODD_EVEN' in context:
                            context['Odd_Even'] = context['ODD_EVEN']
                            context['Semester_Type'] = context['ODD_EVEN']
                        
                        # --- A. Generate Personalized Appointment Order ---
                        doc_appt = DocxTemplate(io.BytesIO(appointment_bytes))
                        doc_appt.render(context)
                        appt_stream = io.BytesIO()
                        doc_appt.save(appt_stream)
                        
                        # --- B. Generate Personalized QP Template ---
                        doc_qp = DocxTemplate(io.BytesIO(qp_bytes))
                        doc_qp.render(context)
                        qp_stream = io.BytesIO()
                        doc_qp.save(qp_stream)
                        
                        # --- C. Create Individual Setter Zip ---
                        setter_zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(setter_zip_buffer, "w", zipfile.ZIP_DEFLATED) as setter_zip:
                            safe_course = course.replace("/", "_").replace("\\", "_")
                            safe_name = name.replace(" ", "_").replace("/", "_")
                            
                            # Add customized Word Docs
                            setter_zip.writestr(f"Appointment_Order_{safe_course}_{safe_name}.docx", appt_stream.getvalue())
                            setter_zip.writestr(f"QP_Format_{safe_course}_{safe_name}.docx", qp_stream.getvalue())
                            
                            # Add Static Attachments
                            for file_name, file_data in static_files.items():
                                setter_zip.writestr(file_name, file_data)
                        
                        # --- D. Add Setter Zip to Master Zip ---
                        package_name = f"Confidential_{safe_course}_{safe_name}.zip"
                        master_zip.writestr(package_name, setter_zip_buffer.getvalue())
                        
                        processed_count += 1
                        progress_bar.progress(processed_count / total_setters)

                status_text.text("Finalizing master package...")
                master_zip_buffer.seek(0)
                
                progress_bar.progress(1.0)
                status_text.empty()
                st.success(f"✅ Successfully packaged {processed_count} appointment folders!")
                
                # 3. Provide Download Button
                st.download_button(
                    label="⬇️ Download All Packages (Master ZIP)",
                    data=master_zip_buffer,
                    file_name="All_Setter_Packages.zip",
                    mime="application/zip",
                    type="primary",
                    use_container_width=True
                )
                
            except Exception as e:
                st.error(f"Failed during document generation: {str(e)}")
    except Exception as e:
        st.error(f"Failed to read the uploaded CSV file. Make sure it is a valid CSV. Error: {str(e)}")
else:
    st.warning("Please upload the CSV, the Appointment Order Template, and the QP Format Template in the sidebar to begin.")

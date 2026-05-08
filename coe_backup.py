import streamlit as st
import pandas as pd
import io
import zipfile
import datetime
from utils import init_db

# ==========================================
# 1. SETUP
# ==========================================
supabase = init_db()

st.title("💾 Master Data Backup Engine")
st.markdown("#### 🏢 Disaster Recovery & Offline Storage")
st.info("This utility securely pulls your entire University ERP database (Students, Courses, Registrations, Results, Timetables, and Audit Logs) and packages it into a single, highly compressed ZIP file for offline storage.")

# ==========================================
# 2. UNIVERSAL FETCH FUNCTION
# ==========================================
def fetch_all_records(table_name, select_query="*"):
    """Fetches all records from a Supabase table, bypassing the 1000-row limit."""
    all_data = []
    start = 0
    step = 1000
    while True:
        try:
            res = supabase.table(table_name).select(select_query).range(start, start + step - 1).execute()
            if not res.data:
                break
            all_data.extend(res.data)
            if len(res.data) < step:
                break
            start += step
        except Exception as e:
            st.error(f"Error fetching table {table_name}: {e}")
            break
    return all_data

# ==========================================
# 3. BACKUP LOGIC
# ==========================================
st.write("### Prepare Backup")

if st.button("🚀 Generate Master Database Backup", type="primary"):
    # Define every critical table in your ERP ecosystem
    tables_to_backup = [
        "master_students", 
        "master_courses", 
        "master_branches", 
        "master_fees",
        "exam_cycles",
        "exam_timetable",
        "course_registrations",
        "student_results",
        "marks_audit_log"
    ]
    
    # Create an empty progress bar and status text
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Create an in-memory ZIP file buffer (so we don't save files to the server's hard drive)
    zip_buffer = io.BytesIO()
    
    try:
        # Open the ZIP file in write mode
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            total_tables = len(tables_to_backup)
            
            for index, table in enumerate(tables_to_backup):
                # Update UI
                status_text.text(f"Extracting {table}... ({index + 1}/{total_tables})")
                
                # Fetch data
                data = fetch_all_records(table)
                
                if data:
                    # Convert JSON data to pandas DataFrame, then to CSV string
                    df = pd.DataFrame(data)
                    csv_string = df.to_csv(index=False)
                    
                    # Write the CSV directly into the ZIP archive
                    zf.writestr(f"{table}_backup.csv", csv_string)
                else:
                    # If table is empty, write a placeholder so the admin knows it wasn't skipped
                    zf.writestr(f"{table}_backup_EMPTY.csv", "No data currently exists in this table.")
                
                # Update progress bar
                progress_bar.progress((index + 1) / total_tables)
                
        # Finalize filename with current timestamp
        timestamp = datetime.datetime.now().strftime("%Y_%m_%d_%H%M")
        zip_filename = f"AMC_ERP_Master_Backup_{timestamp}.zip"
        
        status_text.success("✅ Database compiled successfully! Ready for download.")
        
        # Display the actual download button
        st.download_button(
            label="📥 Download Master Backup (ZIP)",
            data=zip_buffer.getvalue(),
            file_name=zip_filename,
            mime="application/zip",
            type="primary",
            use_container_width=True
        )
        
    except Exception as e:
        status_text.error(f"🚨 Backup generation failed: {e}")

import streamlit as st
import pandas as pd
import io
import zipfile
import datetime
from utils import init_db, clean_data_for_db

# --- CONFIGURATION ---
# Note: st.set_page_config removed because app.py handles it
supabase = init_db()

st.title("🏛️ Institutional Command Center")
st.sidebar.markdown("### Permanent Setup Phase")

# --- GLOBAL CONTEXT ---
# Pulls the active cycle directly from the session state managed by app.py
active_cycle_id = st.session_state.get('active_cycle_id')

if not active_cycle_id:
    st.sidebar.info("💡 Create and activate an exam cycle in the 'Exam Lifecycle' module to begin operations.")

# --- NAVIGATION ---
tabs = st.tabs([
    "⚙️ Global Settings", 
    "🏫 Infrastructure", 
    "👥 Stakeholders", 
    "🎓 Academic Master",
    "💾 Data Backup" # 🟢 NEW TAB ADDED
])

# ==========================================
# 0. GLOBAL SETTINGS
# ==========================================
with tabs[0]:
    st.header("Step 0: Global Configuration")
    try:
        res = supabase.table("global_settings").select("*").execute()
        curr = {r['setting_key']: r['setting_value'] for r in res.data}
    except: curr = {}
    
    with st.form("global_form"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Institution Name", value=curr.get('college_name', ''))
        univ = c1.text_input("University", value=curr.get('university', ''))
        scheme = c2.selectbox("Syllabus Scheme", ["2022 Scheme (NEP)", "2021 Scheme (CBCS)", "2018 Scheme"])
        
        if st.form_submit_button("Save Global Settings"):
            data = [
                {"setting_key": "college_name", "setting_value": name},
                {"setting_key": "university", "setting_value": univ},
                {"setting_key": "current_scheme", "setting_value": scheme}
            ]
            supabase.table("global_settings").upsert(data).execute()
            st.success("Global Settings Updated!")

# ==========================================
# 1. INFRASTRUCTURE (ROOMS)
# ==========================================
with tabs[1]:
    st.header("Step 1: Exam Halls / Infrastructure")
    
    col_i1, col_i2 = st.columns(2)
    with col_i1:
        st.subheader("Bulk Upload Rooms")
        f_rooms = st.file_uploader("Upload CSV (room_number, capacity, block_name)", type='csv')
        if f_rooms and st.button("Upload Rooms"):
            df = pd.read_csv(f_rooms)
            expected = ['room_number', 'capacity', 'block_name']
            data = clean_data_for_db(df, expected)
            try:
                supabase.table("master_rooms").upsert(data).execute()
                st.success(f"Added {len(data)} rooms successfully.")
            except Exception as e: st.error(f"Error: {e}")
            
    with col_i2:
        st.subheader("Manual Entry")
        with st.form("room_manual"):
            r_num = st.text_input("Room Number (e.g. 201A)")
            r_cap = st.number_input("Capacity", 10, 100, 40)
            r_block = st.text_input("Block Name")
            if st.form_submit_button("Add/Update Room"):
                supabase.table("master_rooms").upsert({"room_number": r_num, "capacity": r_cap, "block_name": r_block}).execute()
                st.success(f"Room {r_num} saved.")

# ==========================================
# 2. STAKEHOLDERS (STUDENTS & EVALUATORS)
# ==========================================
with tabs[2]:
    st.header("Step 2: Stakeholder Master Data")
    st_tabs = st.tabs(["Students", "Evaluators"])
    
    with st_tabs[0]:
        st.subheader("Student Database Enrollment")
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            f_stu = st.file_uploader("Upload CSV (usn, full_name, branch_code, current_sem, batch_year)", type='csv')
            if f_stu and st.button("Upload Students"):
                df = pd.read_csv(f_stu)
                expected = ['usn', 'full_name', 'branch_code', 'current_sem', 'batch_year']
                data = clean_data_for_db(df, expected)
                try:
                    supabase.table("master_students").upsert(data).execute()
                    st.success(f"Enrolled {len(data)} students.")
                except Exception as e: st.error(f"Error: {e}")
        
        with col_s2:
            st.info("Uploading Photos? Go to the 'Pre-Exam Docs' module for the bulk photo uploader.")

    with st_tabs[1]:
        st.subheader("Faculty / Evaluators")
        col_e1, col_e2 = st.columns(2)
        with col_e1:
            f_fac = st.file_uploader("Upload CSV (faculty_id, name, department)", type='csv')
            if f_fac and st.button("Upload Faculty"):
                df = pd.read_csv(f_fac)
                expected = ['faculty_id', 'name', 'department']
                data = clean_data_for_db(df, expected)
                try:
                    supabase.table("master_evaluators").upsert(data).execute()
                    st.success(f"Added {len(data)} faculty members.")
                except Exception as e: st.error(f"Error: {e}")
        with col_e2:
            with st.form("fac_manual"):
                f_id = st.text_input("Faculty ID")
                f_name = st.text_input("Full Name")
                f_dep = st.text_input("Department")
                if st.form_submit_button("Add/Update Faculty"):
                    supabase.table("master_evaluators").upsert({"faculty_id": f_id, "name": f_name, "department": f_dep}).execute()
                    st.success("Saved.")

# ==========================================
# 3. ACADEMIC MASTER (COURSES & BRANCHES)
# ==========================================
with tabs[3]:
    st.header("Step 3: Academic Schema")
    ac_tabs = st.tabs(["Branches / Programs", "Course Syllabus / Scheme"])
    
    with ac_tabs[0]:
        c_b1, c_b2 = st.columns(2)
        with c_b1:
            f_br = st.file_uploader("Upload CSV (branch_code, branch_name, program_type)", type='csv')
            if f_br and st.button("Upload Branches"):
                df = pd.read_csv(f_br)
                expected = ['branch_code', 'branch_name', 'program_type']
                data = clean_data_for_db(df, expected)
                try:
                    supabase.table("master_branches").upsert(data).execute()
                    st.success(f"Added {len(data)} branches.")
                except Exception as e: st.error(f"Error: {e}")
        with c_b2:
            with st.form("branch_manual"):
                b_c = st.text_input("Branch Code (e.g. CS)")
                b_n = st.text_input("Branch Name (e.g. Computer Science)")
                b_p = st.selectbox("Program Type", ["UG", "PG", "PHD"])
                if st.form_submit_button("Save Branch"):
                    supabase.table("master_branches").upsert({"branch_code": b_c, "branch_name": b_n, "program_type": b_p}).execute()
                    st.success("Saved.")

    with ac_tabs[1]:
        st.info("The Master Course table defines every subject taught, its credits, and its max marks. This is critical for the grading engine.")
        c_m1, c_m2 = st.columns(2)
        
        with c_m1:
            f_crs = st.file_uploader("Upload Scheme CSV (course_code, title, branch_code, semester_id, credits, max_cie, max_see, total_marks)", type='csv')
            if f_crs and st.button("Upload Scheme"):
                df = pd.read_csv(f_crs)
                expected = ['course_code', 'title', 'branch_code', 'semester_id', 'credits', 'max_cie', 'max_see', 'total_marks']
                data = clean_data_for_db(df, expected)
                try:
                    supabase.table("master_courses").upsert(data).execute()
                    st.success("✅ Scheme Updated Successfully.")
                except Exception as e:
                    # This will print the exact DB complaint (e.g., missing Foreign Key)
                    st.error(f"🚨 RAW DATABASE ERROR: {e}")
                    
        with c_m2:
            with st.form("course_manual"):
                col1, col2 = st.columns(2)
                cc = col1.text_input("Course Code")
                ct = col2.text_input("Title")
                cbc = col1.text_input("Branch Code")
                cs = col2.number_input("Semester ID", 1, 8, 1)
                ccr = col1.number_input("Credits", 0, 5, 4)
                
                if st.form_submit_button("💾 Add/Update Course"):
                    try:
                        supabase.table("master_courses").upsert({"course_code": cc, "title": ct, "branch_code": cbc, "semester_id": cs, "credits": ccr}).execute()
                        st.success("✅ Course saved.")
                    except Exception as e:
                        st.error(f"🚨 RAW DATABASE ERROR: {e}")
                        
                if st.form_submit_button("🗑️ Delete Course"):
                    try:
                        supabase.table("master_courses").delete().eq("course_code", cc).execute()
                        st.warning("Course removed.")
                    except Exception as e:
                        st.error(f"🚨 RAW DATABASE ERROR: {e}")

# ==========================================
# 4. MASTER BACKUP & DISASTER RECOVERY
# ==========================================
with tabs[4]:
    st.header("Step 4: Master Data Backup Engine")
    st.info("This utility securely pulls your entire University ERP database (Students, Courses, Registrations, Results, Timetables, and Audit Logs) and packages it into a single, highly compressed ZIP file for offline storage.")

    # Helper function to bypass the 1000-row limit for backups
    def fetch_backup_records(table_name):
        all_data = []
        start = 0
        step = 1000
        while True:
            try:
                res = supabase.table(table_name).select("*").range(start, start + step - 1).execute()
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

    st.write("### Prepare Offline Backup")

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
        
        # Create UI elements for progress tracking
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Create an in-memory ZIP file buffer
        zip_buffer = io.BytesIO()
        
        try:
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                total_tables = len(tables_to_backup)
                
                for index, table in enumerate(tables_to_backup):
                    # Update UI
                    status_text.text(f"Extracting {table}... ({index + 1}/{total_tables})")
                    
                    # Fetch data
                    data = fetch_backup_records(table)
                    
                    if data:
                        # Convert to CSV string and write to ZIP
                        df = pd.DataFrame(data)
                        csv_string = df.to_csv(index=False)
                        zf.writestr(f"{table}_backup.csv", csv_string)
                    else:
                        # Placeholder for empty tables
                        zf.writestr(f"{table}_backup_EMPTY.csv", "No data currently exists in this table.")
                    
                    # Update progress bar
                    progress_bar.progress((index + 1) / total_tables)
                    
            # Finalize filename
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

import streamlit as st
import pandas as pd
import io
import zipfile
import datetime
from utils import init_db, clean_data_for_db

# --- CONFIGURATION ---
supabase = init_db()

st.title("🏛️ Institutional Command Center")
st.sidebar.markdown("### Permanent Setup Phase")

# --- GLOBAL CONTEXT ---
active_cycle_id = st.session_state.get('active_cycle_id')

if not active_cycle_id:
    st.sidebar.info("💡 Create and activate an exam cycle in the 'Exam Lifecycle' module to begin operations.")

# --- NAVIGATION ---
tabs = st.tabs([
    "⚙️ Global Settings", 
    "🏫 Infrastructure", 
    "👥 Stakeholders", 
    "🎓 Academic Master",
    "💾 Data Backup"
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
    st_tabs = st.tabs(["Students", "Evaluators", "🔄 USN Migration", "🛑 Status Manager"])
    
    with st_tabs[0]:
        st.subheader("Student Database Enrollment")
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            # 🟢 UPDATED: Swapped batch_year for scheme_batch
            f_stu = st.file_uploader("Upload CSV (usn, full_name, branch_code, current_sem, scheme_batch)", type='csv')
            if f_stu and st.button("Upload Students"):
                df = pd.read_csv(f_stu)
                expected = ['usn', 'full_name', 'branch_code', 'current_sem', 'scheme_batch']
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

    with st_tabs[2]:
        st.subheader("Temp-to-Official USN Migration Tool")
        st.info("When VTU releases official USNs, upload a CSV mapping the Temporary Admission Numbers to the Official USNs.")
        
        with st.expander("View CSV Template Guide"):
            st.code("temp_usn,official_usn\nTMP-ADM4059,1AM26CS001\nLAT-ADM9021,1AM26CS002")
            
        f_mig = st.file_uploader("Upload Migration CSV (temp_usn, official_usn)", type='csv')
        
        if f_mig and st.button("🚀 Execute USN Migration", type="primary"):
            df_mig = pd.read_csv(f_mig)
            df_mig.columns = [str(c).strip().lower() for c in df_mig.columns]
            
            if 'temp_usn' not in df_mig.columns or 'official_usn' not in df_mig.columns:
                st.error("❌ CSV must contain exact headers: 'temp_usn' and 'official_usn'.")
            else:
                with st.spinner("Migrating student records across the database..."):
                    success_count = 0
                    error_count = 0
                    error_logs = []
                    migrations = df_mig.to_dict('records')
                    progress_bar = st.progress(0)
                    
                    for idx, row in enumerate(migrations):
                        old_usn = str(row['temp_usn']).strip().upper()
                        new_usn = str(row['official_usn']).strip().upper()
                        
                        try:
                            old_stu_res = supabase.table("master_students").select("*").eq("usn", old_usn).execute()
                            if not old_stu_res.data:
                                error_count += 1
                                error_logs.append(f"{old_usn}: Not found.")
                                continue
                                
                            new_stu_data = old_stu_res.data[0].copy()
                            new_stu_data['usn'] = new_usn
                            new_stu_data['admission_number'] = old_usn
                            
                            supabase.table("master_students").upsert(new_stu_data).execute()
                            supabase.table("course_registrations").update({"usn": new_usn}).eq("usn", old_usn).execute()
                            supabase.table("student_results").update({"usn": new_usn}).eq("usn", old_usn).execute()
                            
                            try:
                                supabase.table("marks_audit_log").update({"usn": new_usn}).eq("usn", old_usn).execute()
                            except: pass
                                
                            supabase.table("master_students").delete().eq("usn", old_usn).execute()
                            success_count += 1
                            
                        except Exception as e:
                            error_count += 1
                            error_logs.append(f"{old_usn} -> {new_usn}: {str(e)}")
                            
                        progress_bar.progress((idx + 1) / len(migrations))
                        
                    if success_count > 0:
                        st.success(f"✅ Successfully migrated {success_count} students to their official USNs!")
                    if error_count > 0:
                        st.error(f"⚠️ Failed to migrate {error_count} records.")
                        with st.expander("View Error Logs"):
                            for err in error_logs: st.write(err)

    with st_tabs[3]:
        st.subheader("Student Status Management")
        st.warning("Marking a student as 'DETAINED' or 'DISCONTINUED' will freeze their profile and prevent them from appearing in future registrations, OMR generation, and seating allotments.")
        
        col_m1, col_m2 = st.columns(2)
        
        with col_m1:
            st.markdown("**Single Student Update**")
            search_usn = st.text_input("Enter USN").strip().upper()
            
            if search_usn:
                stu_res = supabase.table("master_students").select("usn, full_name, status").eq("usn", search_usn).execute()
                
                if stu_res.data:
                    student = stu_res.data[0]
                    raw_status = student.get('status')
                    current_status = str(raw_status).strip().upper() if raw_status else "ACTIVE"
                    
                    if current_status not in ["ACTIVE", "DETAINED", "DISCONTINUED"]:
                        current_status = "ACTIVE"
                        
                    st.info(f"👤 **{student['full_name']}** | Current Status: **{current_status}**")
                    
                    with st.form("status_update_form"):
                        valid_options = ["ACTIVE", "DETAINED", "DISCONTINUED"]
                        new_status = st.selectbox("Update Status To:", valid_options, index=valid_options.index(current_status))
                        
                        if st.form_submit_button("Apply Status Change"):
                            supabase.table("master_students").update({"status": new_status}).eq("usn", search_usn).execute()
                            st.success(f"Status for {search_usn} updated to {new_status}!")
                else:
                    st.error("Student not found in database.")

        with col_m2:
            st.markdown("**Bulk Status Update**")
            st.caption("Upload a CSV to process Detained lists quickly.")
            with st.expander("View CSV Template Guide"):
                st.code("usn,status\n1AM24CS001,DETAINED\n1AM24AI015,DISCONTINUED")
                
            f_stat = st.file_uploader("Upload Status CSV (usn, status)", type='csv')
            if f_stat and st.button("Execute Bulk Update"):
                df_stat = pd.read_csv(f_stat)
                df_stat.columns = [str(c).strip().lower() for c in df_stat.columns]
                
                if 'usn' not in df_stat.columns or 'status' not in df_stat.columns:
                    st.error("❌ CSV must contain exact headers: 'usn' and 'status'.")
                else:
                    with st.spinner("Updating statuses..."):
                        updates = df_stat.to_dict('records')
                        for row in updates:
                            clean_usn = str(row['usn']).strip().upper()
                            clean_status = str(row['status']).strip().upper()
                            if clean_status in ["ACTIVE", "DETAINED", "DISCONTINUED"]:
                                supabase.table("master_students").update({"status": clean_status}).eq("usn", clean_usn).execute()
                    st.success(f"✅ Successfully processed {len(updates)} status updates.")

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
            # 🟢 UPDATED: Added course_type and scheme_batch to CSV processor
            f_crs = st.file_uploader("Upload Scheme CSV (course_code, title, branch_code, semester_id, credits, max_cie, max_see, total_marks, course_type, scheme_batch)", type='csv')
            if f_crs and st.button("Upload Scheme"):
                df = pd.read_csv(f_crs)
                expected = ['course_code', 'title', 'branch_code', 'semester_id', 'credits', 'max_cie', 'max_see', 'total_marks', 'course_type', 'scheme_batch']
                data = clean_data_for_db(df, expected)
                try:
                    supabase.table("master_courses").upsert(data).execute()
                    st.success("✅ Scheme Updated Successfully.")
                except Exception as e:
                    st.error(f"🚨 RAW DATABASE ERROR: {e}")
                    
        with c_m2:
            with st.form("course_manual"):
                col1, col2 = st.columns(2)
                cc = col1.text_input("Course Code")
                ct = col2.text_input("Title")
                
                # 🟢 UPDATED: Explaining the Comma Separated arrays for shared subjects
                cbc = col1.text_input("Branch Code(s)", help="Use comma separation for shared subjects (e.g., 'CS, IS, AI'). Use 'ALL' for universal subjects.")
                cs = col2.number_input("Semester ID", 1, 10, 1)
                ccr = col1.number_input("Credits", 0, 5, 4)
                
                # 🟢 UPDATED: Core / PE / OE selector and Scheme Batch
                ctype = col2.selectbox("Course Type", ["CORE", "PE", "OE"])
                c_scheme = col1.number_input("Scheme Batch (Year)", 20, 99, 25, help="Enter the 2-digit batch year this syllabus applies to (e.g., 25, 26).")
                
                if st.form_submit_button("💾 Add/Update Course"):
                    try:
                        # Ensures branch codes are capitalized and stripped of weird spaces
                        clean_branches = ", ".join([b.strip().upper() for b in cbc.split(",")])
                        
                        payload = {
                            "course_code": cc, "title": ct, 
                            "branch_code": clean_branches, "semester_id": cs, 
                            "credits": ccr, "course_type": ctype, 
                            "scheme_batch": c_scheme
                        }
                        supabase.table("master_courses").upsert(payload).execute()
                        st.success("✅ Course saved.")
                    except Exception as e:
                        st.error(f"🚨 RAW DATABASE ERROR: {e}")
                        
                if st.form_submit_button("🗑️ Delete Course"):
                    try:
                        supabase.table("master_courses").delete().eq("course_code", cc).execute()
                        st.warning("Course removed.")
                    except Exception as e:
                        st.error(f"🚨 RAW DATABASE ERROR: {e}")
        
        # 🟢 UPDATED: Re-added the Export Engine for Department Portals
        st.divider()
        st.markdown("### 📥 Export Master Syllabus for Department Reference")
        st.caption("Download the complete schema for offline review or distribution.")
        
        if st.button("🚀 Generate Master Syllabus CSV", type="primary"):
            with st.spinner("Fetching comprehensive curriculum..."):
                try:
                    res = supabase.table("master_courses").select("*").execute()
                    if res.data:
                        df_export = pd.DataFrame(res.data)
                        cols = ['course_code', 'title', 'branch_code', 'semester_id', 'credits', 'course_type', 'scheme_batch', 'max_cie', 'max_see', 'total_marks']
                        df_export = df_export[[c for c in cols if c in df_export.columns]]
                        csv = df_export.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="⬇️ Download Master_Courses_Schema.csv",
                            data=csv,
                            file_name=f"Master_Courses_Schema_{datetime.date.today()}.csv",
                            mime="text/csv"
                        )
                    else:
                        st.warning("No courses found in the database.")
                except Exception as e:
                    st.error(f"Failed to export data: {e}")

# ==========================================
# 4. MASTER BACKUP & DISASTER RECOVERY
# ==========================================
with tabs[4]:
    st.header("Step 4: Master Data Backup Engine")
    st.info("This utility securely pulls your entire University ERP database and packages it into a single, highly compressed ZIP file for offline storage.")

    def fetch_backup_records(table_name):
        all_data = []
        start = 0
        step = 1000
        while True:
            try:
                res = supabase.table(table_name).select("*").range(start, start + step - 1).execute()
                if not res.data: break
                all_data.extend(res.data)
                if len(res.data) < step: break
                start += step
            except Exception as e:
                st.error(f"Error fetching table {table_name}: {e}")
                break
        return all_data

    st.write("### Prepare Offline Backup")

    if st.button("🚀 Generate Master Database Backup", type="primary"):
        tables_to_backup = [
            "master_students", "master_courses", "master_branches", "master_fees",
            "exam_cycles", "exam_timetable", "course_registrations",
            "student_results", "marks_audit_log"
        ]
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        zip_buffer = io.BytesIO()
        
        try:
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                total_tables = len(tables_to_backup)
                
                for index, table in enumerate(tables_to_backup):
                    status_text.text(f"Extracting {table}... ({index + 1}/{total_tables})")
                    data = fetch_backup_records(table)
                    
                    if data:
                        df = pd.DataFrame(data)
                        csv_string = df.to_csv(index=False)
                        zf.writestr(f"{table}_backup.csv", csv_string)
                    else:
                        zf.writestr(f"{table}_backup_EMPTY.csv", "No data currently exists in this table.")
                    
                    progress_bar.progress((index + 1) / total_tables)
                    
            timestamp = datetime.datetime.now().strftime("%Y_%m_%d_%H%M")
            zip_filename = f"AMC_ERP_Master_Backup_{timestamp}.zip"
            
            status_text.success("✅ Database compiled successfully! Ready for download.")
            
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

import streamlit as st
import pandas as pd
import io
import zipfile
import datetime
import random
import re
from collections import defaultdict
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
        
        schemes = ["2022 Scheme (NEP)", "2021 Scheme (CBCS)", "2018 Scheme"]
        curr_scheme = curr.get('current_scheme', '2022 Scheme (NEP)')
        scheme = c2.selectbox("Syllabus Scheme", schemes, index=schemes.index(curr_scheme) if curr_scheme in schemes else 0)
        
        st.divider()
        st.markdown("### 📅 Active Academic Term (For Regular Course Registrations)")
        st.info("Set the current academic session. Departments will register students into this term, completely independent of when exams actually happen.")
        
        col_t1, col_t2 = st.columns(2)
        active_ay = col_t1.text_input("Active Academic Year", value=curr.get('active_academic_year', '2026-27'), help="e.g., 2026-27")
        active_term = col_t2.selectbox("Active Semester Type", ["ODD", "EVEN"], index=0 if curr.get('active_term', 'ODD') == 'ODD' else 1)
        
        if st.form_submit_button("💾 Save Global Settings", type="primary"):
            data = [
                {"setting_key": "college_name", "setting_value": name},
                {"setting_key": "university", "setting_value": univ},
                {"setting_key": "current_scheme", "setting_value": scheme},
                {"setting_key": "active_academic_year", "setting_value": active_ay},
                {"setting_key": "active_term", "setting_value": active_term}
            ]
            try:
                supabase.table("global_settings").upsert(data).execute()
                st.success("✅ Global Settings Updated! The Department Portal is now anchored to this Academic Term.")
            except Exception as e:
                st.error(f"Database Error: {e}")

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
            
            # Deduplicate by room number to prevent Postgres 21000 Error
            unique_rooms = {str(d.get('room_number')).strip(): d for d in data if d.get('room_number')}
            final_data = list(unique_rooms.values())
            
            try:
                supabase.table("master_rooms").upsert(final_data).execute()
                st.success(f"Added {len(final_data)} rooms successfully.")
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
    st_tabs = st.tabs(["Students", "Staff & Evaluators", "🔄 USN Migration", "🛑 Status Manager"])
    
    with st_tabs[0]:
        st.subheader("Student Database Enrollment")
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            upload_mode = st.radio(
                "Select Upload Behavior:", 
                ["🟢 Safe Mode: Only insert NEW students (Ignore existing)", 
                 "🔴 Overwrite Mode: Update EXISTING students (Danger)"],
                help="Safe mode prevents accidental overwrites of existing student records and statuses."
            )
            
            st.info("💡 **Pro Tip:** Leave 'usn' blank for 1st Years. Use `student_category` to define: Regular, Lateral Entry, Year Back Student, College Change, or Change of Branch.")
            f_stu = st.file_uploader("Upload CSV (usn, full_name, branch_code, current_sem, section, scheme_batch, contact, email, dob, student_category)", type='csv')
            
            if f_stu and st.button("Upload Students", type="primary"):
                df = pd.read_csv(f_stu)
                df.columns = [str(c).strip().lower() for c in df.columns]
                df.rename(columns={'email_id': 'email', 'phone': 'contact', 'category': 'student_category'}, inplace=True)
                
                if 'usn' not in df.columns:
                    df['usn'] = ''
                if 'student_category' not in df.columns:
                    df['student_category'] = 'REGULAR'
                
                df['full_name'] = df['full_name'].fillna('').astype(str).str.strip()
                df['branch_code'] = df['branch_code'].fillna('GEN').astype(str).str.strip().str.upper()
                df = df.sort_values(by=['branch_code', 'full_name'], ascending=[True, True]).reset_index(drop=True)
                
                expected = ['usn', 'full_name', 'branch_code', 'current_sem', 'section', 'scheme_batch', 'contact', 'email', 'dob', 'student_category']
                data = clean_data_for_db(df, expected)
                
                with st.spinner("Analyzing full database (bypassing 1,000-row cap) and generating sequences..."):
                    try:
                        all_existing_students = []
                        start = 0
                        step = 1000
                        while True:
                            res = supabase.table("master_students").select("usn, full_name, branch_code, current_sem, photo_pin").range(start, start + step - 1).execute()
                            if not res.data:
                                break
                            all_existing_students.extend(res.data)
                            if len(res.data) < step:
                                break
                            start += step
                        
                        branch_max_seq = defaultdict(int)
                        existing_data = {}
                        existing_identity_map = {}
                        
                        for r in all_existing_students:
                            u = str(r.get('usn', '')).strip().upper()
                            if not u:
                                continue
                            existing_data[u] = r.get('photo_pin')
                            
                            f_name = str(r.get('full_name', '')).strip().upper()
                            b_code = str(r.get('branch_code', '')).strip().upper()
                            c_sem = str(r.get('current_sem', '')).strip()
                            if f_name and b_code:
                                existing_identity_map[(f_name, b_code, c_sem)] = u
                            
                            if u.startswith("TMP-"):
                                parts = u.split('-')
                                if len(parts) >= 3:
                                    try:
                                        seq = int(parts[-1])
                                        br = '-'.join(parts[1:-1])
                                        if seq > branch_max_seq[br]:
                                            branch_max_seq[br] = seq
                                    except ValueError:
                                        pass
                                
                        for d in data:
                            raw_usn = str(d.get('usn') or '').strip().upper()
                            branch = str(d.get('branch_code') or 'GEN').strip().upper()
                            full_name_clean = str(d.get('full_name') or '').strip().upper()
                            sem_clean = str(d.get('current_sem') or '').strip()
                            
                            d['full_name'] = full_name_clean
                            d['branch_code'] = branch
                            
                            if raw_usn in ['', 'NAN', 'NONE', 'NULL']:
                                identity_key = (full_name_clean, branch, sem_clean)
                                if identity_key in existing_identity_map:
                                    d['usn'] = existing_identity_map[identity_key]
                                else:
                                    branch_max_seq[branch] += 1
                                    d['usn'] = f"TMP-{branch}-{branch_max_seq[branch]:03d}"
                            else:
                                d['usn'] = raw_usn

                            if 'section' in d and pd.notna(d.get('section')) and str(d.get('section')).strip() != '':
                                d['section'] = str(d['section']).strip().upper()
                            else:
                                d['section'] = None
                                
                            cat_val = str(d.get('student_category', 'REGULAR')).strip().upper()
                            if cat_val in ['', 'NAN', 'NONE', 'NULL']: cat_val = 'REGULAR'
                            d['student_category'] = cat_val
                            
                            if 'contact' in d and pd.notna(d.get('contact')) and str(d['contact']).strip() != '':
                                d['contact'] = str(d['contact']).split('.')[0].strip()
                                
                            if 'email' in d and pd.notna(d.get('email')):
                                d['email'] = str(d['email']).strip().lower()
                                
                            if 'dob' in d and pd.notna(d.get('dob')):
                                d['dob'] = str(d['dob']).strip()
                        
                        unique_data = {d['usn']: d for d in data}
                        data = list(unique_data.values())
                        
                        existing_usns_set = set(existing_data.keys())
                        
                        for d in data:
                            if d['usn'] in existing_data and existing_data[d['usn']]:
                                d['photo_pin'] = existing_data[d['usn']] 
                            else:
                                d['photo_pin'] = str(random.randint(1000, 9999)) 
                        
                        new_records = [d for d in data if d['usn'] not in existing_usns_set]
                        existing_records = [d for d in data if d['usn'] in existing_usns_set]
                        
                        if "Safe Mode" in upload_mode:
                            if new_records:
                                for i in range(0, len(new_records), 500):
                                    supabase.table("master_students").insert(new_records[i:i+500]).execute()
                                assigned_preview = ", ".join([f"{r['full_name']} ({r['usn']})" for r in new_records[:5]])
                                st.success(f"✅ Successfully enrolled {len(new_records)} NEW students: {assigned_preview}{'...' if len(new_records) > 5 else ''}")
                            else:
                                st.info("No new students to add.")
                                
                            if existing_records:
                                ignored_preview = ", ".join([f"{r['full_name']} ({r['usn']})" for r in existing_records[:5]])
                                st.warning(f"🛡️ Safely ignored {len(existing_records)} students already in the database: {ignored_preview}{'...' if len(existing_records) > 5 else ''}")
                        
                        elif "Overwrite Mode" in upload_mode:
                            for i in range(0, len(data), 500):
                                supabase.table("master_students").upsert(data[i:i+500]).execute()
                            st.success(f"⚠️ Overwrite Complete! {len(data)} students processed. Existing PINs were protected.")
                            
                    except Exception as e:
                        st.error(f"Database Error: {e}")
        
        with col_s2:
            st.info("Uploading Photos? Go to the 'Pre-Exam Docs' module for the bulk photo uploader.")

    with st_tabs[1]:
        st.subheader("Staff & Evaluators Provisioning")
        st.info("Upload Faculty without an ID. The system will use their 'branch' to auto-generate a sequential ID (e.g., CD2601) and a 4-digit PIN.")
        
        # 🟢 BULLETPROOF ROLE LIST (Exhaustive Match based on user data)
        valid_roles = [
            'Principal', 'Vice Principal & Professor', 'Principal & Professor', 'Principal& Professor', 
            'Controller of Examinations (COE)', 'Professor & HOD', 'Associate Professor & HOD', 
            'Professor & Academic Advisor', 'HOD', 'Professor', 'Associate Professor', 'Assistant Professor',
            'Associate Professor & Resident Engineer', 'Associate Professor & Resident  Engineer',
            'Assistant Professor - G1', 'Assistant Professor - G2', 'Assistant Professor - G3',
            'Lab Instructor', 'LAB', 'Librarian', 'First Division Assistant (FDA)', 'FDA',
            'Second Division Assistant (SDA)', 'SDA', 'Office Superintendent', 'Office Executive', 
            'Office Staff', 'Physical Education', 'PE', 'NCC', 'IT', 'Exam Section',
            'Attender', 'Faculty', 'Staff', 'Executive', 'Senior Executive'
        ]

        col_e1, col_e2 = st.columns(2)
        with col_e1:
            st.markdown("**Bulk Account Creation (CSV)**")
            f_fac = st.file_uploader("Upload CSV (full_name, role, dept, branch, is_evaluator)", type='csv')
            
            if f_fac and st.button("Upload Staff & Generate PINs", type="primary"):
                df = pd.read_csv(f_fac)
                df.columns = [str(c).strip().lower() for c in df.columns]
                
                if 'faculty_id' not in df.columns: df['faculty_id'] = 'MISSING'
                if 'full_name' not in df.columns: df['full_name'] = 'Unknown'
                if 'role' not in df.columns: df['role'] = 'Faculty'
                if 'dept' not in df.columns: df['dept'] = 'GEN'
                if 'branch' not in df.columns: df['branch'] = df.get('dept', 'GEN')
                if 'is_evaluator' not in df.columns: df['is_evaluator'] = False
                if 'email' not in df.columns: df['email'] = 'none'
                
                df['faculty_id'] = df['faculty_id'].fillna('MISSING').astype(str).str.strip().str.upper()
                df['full_name'] = df['full_name'].fillna('Unknown').astype(str).str.strip()
                df['dept'] = df['dept'].fillna('GEN').astype(str).str.strip().str.upper()
                df['branch'] = df['branch'].fillna(df['dept']).astype(str).str.strip().str.upper()
                df['email'] = df['email'].fillna('none').astype(str).str.strip().str.lower()
                
                def parse_bool(val):
                    if pd.isna(val): return False
                    return str(val).strip().lower() in ['true', 'yes', '1', 'y', 't']
                
                df['is_evaluator'] = df['is_evaluator'].apply(parse_bool)
                data = df.to_dict('records')
                
                existing_staff_res = supabase.table("master_staff").select("staff_id, faculty_id, staff_pin").execute()
                existing_fac_map = {r['faculty_id'].strip().upper(): r for r in existing_staff_res.data if r.get('faculty_id')} if existing_staff_res.data else {}
                
                current_year = str(datetime.date.today().year)[-2:]
                dept_seq = defaultdict(int)
                
                for fid in existing_fac_map.keys():
                    if fid[:-2].isdigit() and fid[-4:-2] == current_year:
                        branch_prefix = fid[:-4]
                        try:
                            seq = int(fid[-2:])
                            if seq > dept_seq[branch_prefix]: 
                                dept_seq[branch_prefix] = seq
                        except: pass
                
                unique_staff_map = {}
                
                for d in data:
                    dept = str(d.get('dept', 'GEN')).strip().upper()
                    branch = str(d.get('branch', '')).strip().upper()
                    if not branch or branch in ['NAN', 'NONE']: branch = dept if dept not in ['NAN', 'NONE'] else 'GEN'
                    
                    d['branch'] = branch
                    d['dept'] = dept if dept not in ['NAN', 'NONE'] else 'GEN'
                    
                    raw_fid = str(d.get('faculty_id', '')).strip().upper()
                    if raw_fid in ['MISSING', 'NAN', 'NONE', '']: 
                        dept_seq[branch] += 1
                        raw_fid = f"{branch}{current_year}{dept_seq[branch]:02d}"
                        
                    d['faculty_id'] = raw_fid
                    em = str(d.get('email', '')).strip().lower()
                    d['email'] = em if em not in ['nan', 'none', ''] else None
                    
                    # 🟢 FORCE PRECISE ROLE MATCHING
                    raw_role = str(d.get('role', 'Faculty')).strip()
                    # Try to find an exact match (ignoring case)
                    matched_role = next((r for r in valid_roles if r.lower() == raw_role.lower()), None)
                    
                    # If they uploaded a role that isn't in our list at all, default them to 'Faculty'
                    if not matched_role:
                        matched_role = 'Faculty'
                        
                    d['role'] = matched_role
                    
                    if raw_fid in existing_fac_map:
                        d['staff_id'] = existing_fac_map[raw_fid]['staff_id']
                        d['staff_pin'] = existing_fac_map[raw_fid].get('staff_pin') or str(random.randint(1000, 9999))
                    else:
                        d['staff_pin'] = str(random.randint(1000, 9999))
                        
                    unique_staff_map[raw_fid] = d
                
                final_staff_data = list(unique_staff_map.values())
                
                if final_staff_data:
                    try:
                        for i in range(0, len(final_staff_data), 500):
                            supabase.table("master_staff").upsert(final_staff_data[i:i+500], on_conflict="faculty_id").execute()
                        st.success(f"✅ Successfully processed and uploaded **{len(final_staff_data)}** staff members with accurate roles!")
                        
                        with st.expander("Preview Uploaded Staff"):
                            preview_df = pd.DataFrame(final_staff_data)[['full_name', 'faculty_id', 'branch', 'staff_pin', 'role', 'dept']]
                            st.dataframe(preview_df, use_container_width=True, hide_index=True)
                            
                    except Exception as e: 
                        st.error(f"Upload Error: {e}")
                else:
                    st.warning("No valid staff records found in the uploaded file.")
                    
        with col_e2:
            st.markdown("**Single Staff Entry**")
            with st.form("fac_manual"):
                f_name = st.text_input("Full Name")
                f_id = st.text_input("Faculty ID", help="Leave blank to auto-generate").strip().upper()
                
                # 🟢 DYNAMIC DROPDOWN USING BULLETPROOF LIST
                default_idx = valid_roles.index('Assistant Professor') if 'Assistant Professor' in valid_roles else 0
                f_role = st.selectbox("Role / Designation", valid_roles, index=default_idx)
                
                f_dept = st.text_input("Parent Department (e.g., CSE)").strip().upper()
                f_branch = st.text_input("Branch Code (e.g., CD, AI, CS)").strip().upper()
                f_eval = st.checkbox("Is Evaluator?", value=False)
                
                if st.form_submit_button("Add/Update Staff Account"):
                    if f_name and (f_dept or f_branch):
                        try:
                            if not f_branch: f_branch = f_dept if f_dept else "GEN"
                            if not f_dept: f_dept = f_branch
                            
                            if not f_id:
                                existing_staff_res = supabase.table("master_staff").select("faculty_id").execute()
                                current_year = str(datetime.date.today().year)[-2:]
                                max_seq = 0
                                if existing_staff_res.data:
                                    for r in existing_staff_res.data:
                                        if r.get('faculty_id', '').startswith(f"{f_branch}{current_year}"):
                                            try:
                                                seq = int(r['faculty_id'][-2:])
                                                if seq > max_seq: max_seq = seq
                                            except: pass
                                f_id = f"{f_branch}{current_year}{max_seq + 1:02d}"
                                st.info(f"Auto-generated Faculty ID: **{f_id}**")
                            
                            existing = supabase.table("master_staff").select("staff_id, staff_pin").eq("faculty_id", f_id).execute()
                            payload = {
                                "full_name": f_name,
                                "faculty_id": f_id,
                                "role": f_role,
                                "dept": f_dept,
                                "branch": f_branch,
                                "is_evaluator": f_eval
                            }
                            
                            if existing.data:
                                payload['staff_id'] = existing.data[0]['staff_id']
                                payload['staff_pin'] = existing.data[0].get('staff_pin') or str(random.randint(1000, 9999))
                            else:
                                payload['staff_pin'] = str(random.randint(1000, 9999))
                                
                            supabase.table("master_staff").upsert(payload, on_conflict="faculty_id").execute()
                            st.success(f"✅ Saved Profile & Created Login PIN for {f_id}")
                        except Exception as e:
                            st.error(f"Error: {e}")
                    else:
                        st.error("Full Name and Department/Branch are mandatory.")

    with st_tabs[2]:
        st.subheader("Temp-to-Official USN Migration Tool")
        st.info("When VTU releases official USNs, upload a CSV mapping the Temporary Admission Numbers to the Official USNs.")
        
        with st.expander("View CSV Template Guide"):
            st.code("temp_usn,official_usn\nTMP-CSE-001,1AM26CS001\nTMP-CSE-002,1AM26CS002")
            
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
                
                unique_branches = {str(d.get('branch_code')).strip(): d for d in data if d.get('branch_code')}
                final_data = list(unique_branches.values())
                
                try:
                    supabase.table("master_branches").upsert(final_data).execute()
                    st.success(f"Added {len(final_data)} branches.")
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
        st.info("The Master Course table defines every subject taught, its offering department, its credits, and its max marks. This is critical for the grading and auto-registration engines.")
        c_m1, c_m2 = st.columns(2)
        
        with c_m1:
            st.markdown("""
            ### 📝 CSV Upload Guidelines
            For the Auto-Registration engine to work perfectly, please ensure the **`course_type`** column in your CSV strictly uses these terms:
            *   **`CORE`** (Regular Theory subjects)
            *   **`LAB`** (Practical Sessions)
            *   **`PROJECT`** (Project-based learning & Internships)
            *   **`NON CREDIT`** (Mandatory zero-credit subjects)
            *   **`LATERAL`** (Additional Math for diploma entry students)
            *   **`PE`** (Professional Electives)
            *   **`OE`** (Open Electives)
            *   **`OMR`** (OMR-based evaluations, like Kannada/Constitution)
            """)
            
            f_crs = st.file_uploader(
                "Upload Scheme CSV (course_code, title, branch_code, semester_id, credits, max_cie, max_see, total_marks, course_type, scheme_batch, offering_department)", 
                type='csv'
            )
            if f_crs and st.button("Upload Scheme"):
                df = pd.read_csv(f_crs)
                df.columns = [str(c).strip().lower() for c in df.columns]
                
                if 'branch_code' in df.columns:
                    df['branch_code'] = df['branch_code'].astype(str).apply(
                        lambda x: ", ".join([b.strip().upper() for b in x.split(",") if b.strip()])
                    )
                
                if 'course_type' in df.columns:
                    df['course_type'] = df['course_type'].astype(str).str.strip().str.upper()
                    
                if 'offering_department' in df.columns:
                    df['offering_department'] = df['offering_department'].fillna('').astype(str).str.strip().str.upper()
                
                expected = [
                    'course_code', 'title', 'branch_code', 'semester_id', 
                    'credits', 'max_cie', 'max_see', 'total_marks', 
                    'course_type', 'scheme_batch', 'offering_department'
                ]
                data = clean_data_for_db(df, expected)
                
                unique_courses = {str(d.get('course_code')).strip(): d for d in data if d.get('course_code')}
                final_data = list(unique_courses.values())
                
                try:
                    for i in range(0, len(final_data), 500):
                        supabase.table("master_courses").upsert(final_data[i:i+500]).execute()
                    st.success(f"✅ Scheme Updated Successfully ({len(final_data)} unique courses processed).")
                except Exception as e:
                    st.error(f"🚨 RAW DATABASE ERROR: {e}")
                    
        with c_m2:
            with st.form("course_manual"):
                col1, col2 = st.columns(2)
                cc = col1.text_input("Course Code")
                ct = col2.text_input("Title")
                
                cbc = col1.text_input("Branch Code(s)", help="Use comma separation for shared subjects (e.g., 'CS, IS, AI'). Use 'ALL' for universal subjects.")
                c_off_dept = col2.text_input("Offering Department", help="Department teaching this course (e.g., 'CS', 'MAT', 'PHY', 'ME').")
                
                cs = col1.number_input("Semester ID", 1, 10, 1)
                ccr = col2.number_input("Credits", 0, 5, 4)
                
                ctype = col1.selectbox("Course Type", ["CORE", "LAB", "PROJECT", "NON CREDIT", "LATERAL", "PE", "OE", "OMR"])
                c_scheme = col2.number_input("Scheme Batch (Year)", 20, 99, 25, help="Enter the 2-digit batch year this syllabus applies to (e.g., 25, 26).")
                
                m_cie = col1.number_input("Max CIE Marks", 0, 100, 50)
                m_see = col2.number_input("Max SEE Marks", 0, 100, 50)
                t_marks = col1.number_input("Total Marks", 0, 200, 100)
                
                if st.form_submit_button("💾 Add/Update Course"):
                    try:
                        clean_branches = ", ".join([b.strip().upper() for b in cbc.split(",") if b.strip()])
                        clean_off_dept = c_off_dept.strip().upper() if c_off_dept else None
                        
                        payload = {
                            "course_code": cc.strip().upper(),
                            "title": ct.strip(), 
                            "branch_code": clean_branches,
                            "offering_department": clean_off_dept,
                            "semester_id": cs, 
                            "credits": ccr,
                            "max_cie": m_cie,
                            "max_see": m_see,
                            "total_marks": t_marks,
                            "course_type": ctype, 
                            "scheme_batch": c_scheme
                        }
                        supabase.table("master_courses").upsert(payload).execute()
                        st.success("✅ Course saved.")
                    except Exception as e:
                        st.error(f"🚨 RAW DATABASE ERROR: {e}")
                        
                if st.form_submit_button("🗑️ Delete Course"):
                    try:
                        supabase.table("master_courses").delete().eq("course_code", cc.strip().upper()).execute()
                        st.warning("Course removed.")
                    except Exception as e:
                        st.error(f"🚨 RAW DATABASE ERROR: {e}")
        
        st.divider()
        st.markdown("### 📥 Export Master Syllabus for Department Reference")
        st.caption("Download the complete schema for offline review or distribution.")
        
        if st.button("🚀 Generate Master Syllabus CSV", type="primary"):
            with st.spinner("Fetching comprehensive curriculum..."):
                try:
                    res = supabase.table("master_courses").select("*").execute()
                    if res.data:
                        df_export = pd.DataFrame(res.data)
                        cols = [
                            'course_code', 'title', 'branch_code', 'offering_department',
                            'semester_id', 'credits', 'course_type', 'scheme_batch', 
                            'max_cie', 'max_see', 'total_marks'
                        ]
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
            "student_results", "marks_audit_log", "master_staff"
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

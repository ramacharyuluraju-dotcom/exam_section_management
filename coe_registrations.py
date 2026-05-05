import streamlit as st
import pandas as pd
import os
from utils import init_db, clean_data_for_db

# --- CONFIGURATION ---
supabase = init_db()

st.title("📝 Semester Course Registration")
st.sidebar.markdown("### Operational Phase")

# --- HELPER FUNCTION ---
def fetch_all_records(table_name, select_query="*", filters=None):
    """Fetches all records from Supabase bypassing the 1000 row limit."""
    all_data = []
    step = 1000
    current_start = 0
    while True:
        query = supabase.table(table_name).select(select_query)
        if filters:
            for col, val in filters.items(): 
                query = query.eq(col, val)
                
        query = query.range(current_start, current_start + step - 1)
        res = query.execute()
        
        if not res.data: break
        all_data.extend(res.data)
        if len(res.data) < step: break
        current_start += step
    return all_data

def safe_float(val, default=0.0):
    try: return float(val) if val and pd.notna(val) else default
    except: return default

# --- GLOBAL CONTEXT ---
selected_cycle_id = st.session_state.get('active_cycle_id')

if not selected_cycle_id:
    st.warning("⚠️ Please select an Active Exam Cycle in the Sidebar to proceed.")
    st.stop()

st.info(f"🔵 Currently Registering Students for Cycle: **{st.session_state.get('active_cycle_name')}**")

# ==========================================
# NAVIGATION TABS
# ==========================================
reg_tabs = st.tabs([
    "📤 Bulk Registration", 
    "📝 Manual Mapping", 
    "🔍 View Registrations", 
    "📸 Photo Backup", 
    "📥 Arrear Extractor",
    "🚑 Make-up Extractor" # 🟢 NEW TAB ADDED
])

# ==========================================
# 1. BULK REGISTRATION (CSV)
# ==========================================
with reg_tabs[0]:
    st.header("Step 2.1: Bulk Course Mapping")
    f_reg = st.file_uploader("Upload Registration CSV", type='csv', key="reg_bulk")
    
    if f_reg and st.button("Execute Bulk Registration"):
        df = pd.read_csv(f_reg)
        expected = ['usn', 'course_code', 'academic_year', 'semester_type', 'semester']
        data = clean_data_for_db(df, expected)
        
        for row in data: 
            row['cycle_id'] = selected_cycle_id
            
        try:
            supabase.table("course_registrations").upsert(data).execute()
            st.success(f"✅ Successfully registered {len(data)} student-course mappings for this cycle.")
        except Exception as e:
            st.error(f"Registration failed: {e}")

# ==========================================
# 2. MANUAL MAPPING
# ==========================================
with reg_tabs[1]:
    st.header("Step 2.2: Individual Student Mapping")
    with st.form("manual_reg_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        r_usn = col1.text_input("Student USN")
        r_course = col2.text_input("Course Code")
        r_ay = col1.text_input("Academic Year", value="2025-26")
        r_sem_type = col2.selectbox("Semester Type", ["ODD", "EVEN"])
        r_semester = col1.number_input("Semester", min_value=1, max_value=10, value=2)
        
        c1, c2 = st.columns(2)
        if c1.form_submit_button("💾 Register Course"):
            reg_data = {
                "cycle_id": selected_cycle_id, 
                "usn": r_usn.strip().upper(), 
                "course_code": r_course.strip().upper(), 
                "academic_year": r_ay, 
                "semester_type": r_sem_type,
                "semester": r_semester
            }
            try: 
                supabase.table("course_registrations").upsert(reg_data).execute()
                st.success(f"✅ Registered {r_course} for {r_usn}")
            except Exception as e: 
                st.error(f"Error: {e}")
                
        if c2.form_submit_button("🗑️ Remove Registration"):
            try: 
                supabase.table("course_registrations").delete().match({"cycle_id": selected_cycle_id, "usn": r_usn.strip().upper(), "course_code": r_course.strip().upper()}).execute()
                st.warning(f"Removed registration.")
            except Exception as e: 
                st.error(f"Error: {e}")

# ==========================================
# 3. VIEW REGISTRATIONS
# ==========================================
with reg_tabs[2]:
    st.header(f"🔍 Current Course Mappings for {st.session_state.get('active_cycle_name')}")
    search_usn = st.text_input("Filter by USN (Optional)")
    
    if st.button("Fetch Registration Data"):
        query = supabase.table("course_registrations").select("*").eq("cycle_id", selected_cycle_id)
        if search_usn: 
            query = query.eq("usn", search_usn.strip().upper())
            
        res = query.execute()
        if res.data: 
            st.dataframe(pd.DataFrame(res.data), use_container_width=True)
            st.write(f"Total Records: {len(res.data)}")
        else: 
            st.write("No registration records found.")

# ==========================================
# 4. PHOTO BACKUP UTILITY (ZIP DOWNLOAD)
# ==========================================
with reg_tabs[3]:
    st.header("📸 Student Photo Server Backup")
    st.info("Grabs all student photos from your Supabase cloud and packages them into a single ZIP file.")
    BUCKET_NAME = "StakeHolders_Photos"
    
    if st.button("🚀 Prepare Photo Backup (ZIP)", type="primary"):
        status_text = st.empty()
        progress_bar = st.progress(0)
        status_text.info(f"📡 Scanning Supabase bucket '{BUCKET_NAME}'...")
        
        try:
            import requests
            import io
            import zipfile
            
            supabase_url = supabase.supabase_url
            supabase_key = supabase.supabase_key
            
            base_url_string = str(supabase_url).rstrip('/')
            api_url = f"{base_url_string}/storage/v1/object/list/{BUCKET_NAME}"
            
            headers = {"Authorization": f"Bearer {supabase_key}", "apikey": supabase_key, "Content-Type": "application/json"}
            all_files, current_offset, batch_limit = [], 0, 1000  
            
            while True:
                response = requests.post(api_url, headers=headers, json={"prefix": "", "limit": batch_limit, "offset": current_offset})
                if response.status_code != 200: raise Exception(f"API Error: {response.text}")
                batch = response.json()
                if not batch: break
                all_files.extend(batch)
                if len(batch) < batch_limit: break
                current_offset += batch_limit
                
            if not all_files:
                status_text.warning("⚠️ No files found in the bucket.")
            else:
                valid_files = [f for f in all_files if f.get('name') and not f.get('name').startswith('.')]
                total_files = len(valid_files)
                status_text.info(f"✅ Found {total_files} photos. Zipping them up now...")
                
                zip_buffer = io.BytesIO()
                success_count, error_count = 0, 0
                
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for index, file_info in enumerate(valid_files, start=1):
                        file_name = file_info.get('name')
                        try:
                            file_bytes = supabase.storage.from_(BUCKET_NAME).download(file_name)
                            zf.writestr(file_name, file_bytes)
                            success_count += 1
                        except Exception:
                            error_count += 1
                        progress_bar.progress(index / total_files)
                        status_text.markdown(f"**Progress:** Zipping photo {index} of {total_files}...")
                
                status_text.success("🎉 ZIP file created successfully!")
                st.download_button(label="📥 Download All Photos (ZIP)", data=zip_buffer.getvalue(), file_name="Student_Photos_Backup.zip", mime="application/zip", type="primary")
        except Exception as e:
            status_text.error(f"🚨 Critical Error: {e}")

# ==========================================
# 5. ARREAR EXTRACTOR
# ==========================================
with reg_tabs[4]:
    st.header("📥 Extract Active Arrear Courses")
    st.info("Generates a CSV of pending subjects for students based on their latest exam results.")

    col1, col2 = st.columns(2)
    target_prog = col1.selectbox("Target Program", ["UG", "PG"], key="arrear_prog")
    target_sems = col2.multiselect("Target Semesters for Arrears", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], default=[1, 2], key="arrear_sems")

    if st.button("🔍 Generate Arrear CSV", type="primary"):
        with st.spinner("Analyzing historical exam data to find active backlogs..."):
            try:
                branches_res = fetch_all_records("master_branches", "branch_code, program_type")
                students_res = fetch_all_records("master_students", "usn, branch_code")
                courses_res = fetch_all_records("master_courses", "course_code, title, semester_id")
                
                prog_map = {b['branch_code']: b['program_type'] for b in branches_res}
                usn_to_prog = {s['usn']: prog_map.get(s['branch_code'], 'Unknown') for s in students_res}
                course_map = {c['course_code']: {"title": c.get('title', 'Unknown'), "sem": int(c.get('semester_id', 0))} for c in courses_res}

                results_res = fetch_all_records("student_results", "usn, course_code, is_pass, cycle_id, grade")
                results_res.sort(key=lambda x: int(x.get('cycle_id', 0)))

                latest_results = {}
                for r in results_res:
                    usn = r['usn']
                    cc = r['course_code']
                    if usn not in latest_results: latest_results[usn] = {}
                    latest_results[usn][cc] = {"is_pass": r.get('is_pass', False), "grade": r.get('grade', 'F')}

                arrear_list = []
                for usn, courses in latest_results.items():
                    if usn_to_prog.get(usn) == target_prog:
                        for cc, data in courses.items():
                            if not data['is_pass']: 
                                c_info = course_map.get(cc, {})
                                c_sem = c_info.get("sem", 0)
                                if c_sem in target_sems:
                                    arrear_list.append({
                                        "usn": usn, "semester": c_sem, "course_code": cc,
                                        "course_title": c_info.get("title", "Unknown"), "grade": data['grade'],
                                        "academic_year": st.session_state.get('active_academic_year', '2025-26'), "semester_type": "BOTH"
                                    })

                if not arrear_list:
                    st.success(f"No active {target_prog} backlogs found for semesters {target_sems}.")
                else:
                    df_arrears = pd.DataFrame(arrear_list)[['usn', 'semester', 'course_code', 'course_title', 'grade', 'academic_year', 'semester_type']]
                    df_arrears = df_arrears.sort_values(by=['semester', 'course_code', 'usn'])
                    st.success(f"✅ Found {len(df_arrears)} active backlog registrations.")
                    st.dataframe(df_arrears, use_container_width=True)
                    csv = df_arrears.to_csv(index=False).encode('utf-8')
                    st.download_button(label=f"📥 Download {target_prog}_Arrear_Courses.csv", data=csv, file_name=f"{target_prog}_Arrear_Courses_Sem_{'_'.join(map(str, target_sems))}.csv", mime="text/csv")
            except Exception as e:
                st.error(f"Error generating arrear list: {e}")

# ==========================================
# 6. MAKE-UP EXAM EXTRACTOR
# ==========================================
with reg_tabs[5]:
    st.header("🚑 Extract Eligible Make-up Candidates")
    st.info("Hunts for two scenarios: 1. Absent students with valid internals (Medical). 2. Failed students with >= 90% internals (X-Grade).")

    col1, col2 = st.columns(2)
    x_grade_thresh = col1.slider("🌟 X-Grade CIE Threshold (%)", min_value=70, max_value=100, value=90, step=5, help="Failed students with CIE above this get an automatic X-Grade (Make-up).")
    med_thresh = col2.slider("🏥 Medical Absentee CIE Threshold (%)", min_value=30, max_value=60, value=40, step=5, help="Absent students with CIE above this qualify for Make-up (pending proof).")

    if st.button("🔍 Find Make-up Candidates", type="primary"):
        with st.spinner("Scanning internal marks and attendance records..."):
            try:
                courses_res = fetch_all_records("master_courses", "course_code, title, semester_id, max_cie")
                results_res = fetch_all_records("student_results", "usn, course_code, grade, cie_marks, cycle_id")
                
                course_map = {
                    c['course_code']: {
                        "max_cie": safe_float(c.get('max_cie'), 50.0), 
                        "title": c.get('title', 'Unknown'),
                        "sem": c.get('semester_id', 0)
                    } for c in courses_res
                }
                
                results_res.sort(key=lambda x: int(x.get('cycle_id', 0)))
                
                latest_results = {}
                for r in results_res:
                    usn = r['usn']
                    cc = r['course_code']
                    if usn not in latest_results:
                        latest_results[usn] = {}
                    latest_results[usn][cc] = {
                        "grade": str(r.get('grade', '')).strip().upper(),
                        "cie_marks": safe_float(r.get('cie_marks'), 0.0)
                    }

                makeup_candidates = []
                
                for usn, courses in latest_results.items():
                    for cc, data in courses.items():
                        grade = data['grade']
                        
                        # We only care about Absent or Failed students
                        if grade in ['AB', 'F']:
                            c_info = course_map.get(cc, {"max_cie": 50.0, "title": "Unknown", "sem": 0})
                            max_cie = c_info['max_cie']
                            cie_obtained = data['cie_marks']
                            
                            cie_percentage = (cie_obtained / max_cie) * 100 if max_cie > 0 else 0
                            
                            eligibility_category = None
                            
                            # SCENARIO 1: The Academic Safety Net (Failed but brilliant internals)
                            if grade == 'F' and cie_percentage >= x_grade_thresh:
                                eligibility_category = "⭐ X-Grade: Failed but High CIE"
                                
                            # SCENARIO 2: The Medical Case (Absent with valid passing internals)
                            elif grade == 'AB' and cie_percentage >= med_thresh:
                                eligibility_category = "🏥 I-Grade: Absent (Pending Medical)"
                            
                            if eligibility_category:
                                makeup_candidates.append({
                                    "usn": usn,
                                    "semester": c_info['sem'],
                                    "course_code": cc,
                                    "course_title": c_info['title'],
                                    "previous_grade": grade,
                                    "cie_marks_obtained": cie_obtained,
                                    "max_cie": max_cie,
                                    "cie_percentage": f"{cie_percentage:.1f}%",
                                    "eligibility_category": eligibility_category,
                                    "academic_year": st.session_state.get('active_academic_year', '2025-26'),
                                    "semester_type": "BOTH"
                                })
                
                if not makeup_candidates:
                    st.warning("No students met the criteria for Make-up exams.")
                else:
                    df_makeup = pd.DataFrame(makeup_candidates)
                    df_makeup = df_makeup[['usn', 'semester', 'course_code', 'course_title', 'previous_grade', 'cie_marks_obtained', 'cie_percentage', 'eligibility_category', 'academic_year', 'semester_type']]
                    df_makeup = df_makeup.sort_values(by=['eligibility_category', 'semester', 'course_code', 'usn'])
                    
                    st.success(f"✅ Found {len(df_makeup)} eligible candidates for Make-up exams.")
                    
                    def highlight_categories(val):
                        if 'X-Grade' in str(val): return 'color: #4CAF50; font-weight: bold' # Green for auto-approve
                        elif 'I-Grade' in str(val): return 'color: #FF9800; font-weight: bold' # Orange for pending review
                        return ''
                        
                    st.dataframe(df_makeup.style.map(highlight_categories, subset=['eligibility_category']), use_container_width=True)
                    
                    csv = df_makeup.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Download Make-up Registrations (CSV)", 
                        data=csv, 
                        file_name="Makeup_Eligible_Candidates.csv", 
                        mime="text/csv"
                    )
            except Exception as e:
                st.error(f"Error processing make-up candidates: {e}")

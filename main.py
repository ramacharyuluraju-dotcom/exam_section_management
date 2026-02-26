import streamlit as st
import pandas as pd
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
    "🎓 Academic Master"
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
        scheme = c2.selectbox("Syllabus Type", ["OBE", "CBCS"], index=0)
        addr = st.text_area("Full Address", value=curr.get('address', ''))
        
        if st.form_submit_button("💾 Save Institutional DNA"):
            settings = {'college_name': name, 'university': univ, 'scheme_type': scheme, 'address': addr}
            data = [{'setting_key': k, 'setting_value': v} for k, v in settings.items()]
            supabase.table("global_settings").upsert(data).execute()
            st.success("Global Settings Updated!")

# ==========================================
# 1. INFRASTRUCTURE (ROOMS)
# ==========================================
with tabs[1]:
    st.header("Step 1.1: Block & Room Master")
    st.info("Note: Further infrastructure logic will be added later.")
    
    with st.expander("Show CSV Format Guide"):
        st.markdown("Required Columns: `room_no, block_name, capacity, bench_type, priority_order`")
        st.markdown("**Note:** The system automatically maps 'Two Seater' to 'Double' to match database rules.")
        
    f_room = st.file_uploader("Upload Room CSV", type='csv', key="room")
    if f_room and st.button("Register Rooms"):
        df = pd.read_csv(f_room)
        
        # --- FIX: TRANSLATE BENCH TYPES TO DB ALLOWED VALUES ---
        if 'bench_type' in df.columns:
            # Clean string (remove accidental spaces)
            df['bench_type'] = df['bench_type'].astype(str).str.strip().str.title()
            
            # Map CSV phrases to the exact words Supabase expects
            mapping = {
                'Two Seater': 'Double',
                'Two_Seater': 'Double',
                'Single Seater': 'Single',
                'One Seater': 'Single',
                'Gallery': 'Gallery'
            }
            df['bench_type'] = df['bench_type'].replace(mapping)
            
        expected = ['room_no', 'block_name', 'capacity', 'bench_type', 'priority_order']
        data = clean_data_for_db(df, expected, numeric_cols=['capacity', 'priority_order'])
        
        try:
            supabase.table("master_rooms").upsert(data).execute()
            st.success(f"✅ Infrastructure Saved! {len(data)} rooms registered successfully.")
        except Exception as e:
            error_msg = str(e)
            if "master_rooms_bench_type_check" in error_msg:
                st.error("❌ Database rejected the 'bench_type'. Allowed values are only: 'Single', 'Double', 'Gallery'.")
            else:
                st.error(f"❌ Upload Failed: {error_msg}")

# ==========================================
# 2. STAKEHOLDERS (STAFF/FACULTY)
# ==========================================
with tabs[2]:
    st.header("Step 1.2: Faculty & Staff Master")
    m_t1, m_t2 = st.tabs(["📤 Bulk Upload", "📝 Individual Manage"])
    
    with m_t1:
        st.markdown("**CSV Required Columns:** `staff_id, name, role, dept, is_evaluator, phone, email`")
        f_staff = st.file_uploader("Upload Stakeholders CSV", type='csv', key="staff_bulk")
        if f_staff and st.button("Bulk Register Stakeholders"):
            df = pd.read_csv(f_staff)
            expected = ['staff_id', 'name', 'role', 'dept', 'is_evaluator', 'phone', 'email']
            data = clean_data_for_db(df, expected)
            supabase.table("master_stakeholders").upsert(data).execute()
            st.success("Stakeholders Registered!")

    with m_t2:
        with st.form("staff_individual"):
            col1, col2 = st.columns(2)
            s_id = col1.text_input("Staff ID (Primary Key)")
            s_name = col2.text_input("Full Name")
            s_role = col1.selectbox("Role", ["Faculty", "Admin", "COE", "Super User"])
            s_dept = col2.text_input("Department")
            s_phone = col1.text_input("Phone")
            s_email = col2.text_input("Email")
            s_eval = col1.checkbox("Is Evaluator?")
            
            c1, c2, c3 = st.columns(3)
            if c1.form_submit_button("💾 Add/Update Staff"):
                s_data = {"staff_id": s_id, "name": s_name, "role": s_role, "dept": s_dept, "phone": s_phone, "email": s_email, "is_evaluator": s_eval}
                supabase.table("master_stakeholders").upsert(s_data).execute()
                st.success(f"Staff {s_id} updated.")
            
            if c3.form_submit_button("🗑️ Delete Staff"):
                supabase.table("master_stakeholders").delete().eq("staff_id", s_id).execute()
                st.warning(f"Staff {s_id} removed.")

# ==========================================
# 3. ACADEMIC MASTER
# ==========================================
with tabs[3]:
    st.header("Step 1.3: Core Academic Records")
    ac_t1, ac_t2, ac_t3 = st.tabs(["🏗️ Branches", "👥 Students", "📖 Course Scheme"])
    
    with ac_t1:
        st.subheader("Manual Branch Management")
        with st.form("branch_manage"):
            col1, col2 = st.columns(2)
            b_code = col1.text_input("Branch Code (Primary Key)")
            b_name = col2.text_input("Branch Name")
            p_type = col1.selectbox("Program Type", ["UG", "PG", "PhD"])
            d_type = col2.text_input("Degree Type (e.g. B.E.)")
            dept_n = col1.text_input("Department Name")
            
            c1, c2, c3 = st.columns(3)
            if c1.form_submit_button("💾 Save/Update Branch"):
                b_data = {"branch_code": b_code, "branch_name": b_name, "program_type": p_type, "degree_type": d_type, "dept_name": dept_n}
                supabase.table("master_branches").upsert(b_data).execute()
                st.success(f"Branch {b_code} Saved.")
            if c3.form_submit_button("🗑️ Delete Branch"):
                supabase.table("master_branches").delete().eq("branch_code", b_code).execute()
                st.warning(f"Branch {b_code} deleted.")

    with ac_t2:
        st.subheader("Student Admissions")
        s_m1, s_m2 = st.tabs(["📤 Bulk", "📝 Manual"])
        with s_m1:
            st.markdown("**CSV Required Columns:** `usn, full_name, branch_code, current_sem, section, email, phone, dob, contact, status`")
            f_stu = st.file_uploader("Upload Student CSV", type='csv')
            if f_stu and st.button("Bulk Admissions"):
                df = pd.read_csv(f_stu).rename(columns={'name': 'full_name', 'sem': 'current_sem'})
                expected = ['usn', 'full_name', 'branch_code', 'current_sem', 'section', 'email', 'phone', 'dob', 'contact', 'status']
                data = clean_data_for_db(df, expected, numeric_cols=['current_sem'])
                supabase.table("master_students").upsert(data).execute()
                st.success("Students loaded.")
        with s_m2:
            with st.form("stu_manual"):
                col1, col2 = st.columns(2)
                st_usn = col1.text_input("USN")
                st_name = col2.text_input("Full Name")
                st_bc = col1.text_input("Branch Code")
                st_sem = col2.number_input("Current Sem", 1, 8, 1)
                if st.form_submit_button("💾 Add/Update Student"):
                    supabase.table("master_students").upsert({"usn": st_usn, "full_name": st_name, "branch_code": st_bc, "current_sem": st_sem}).execute()
                    st.success("Student updated.")
                if st.form_submit_button("🗑️ Delete Student"):
                    supabase.table("master_students").delete().eq("usn", st_usn).execute()
                    st.warning("Student removed.")

    with ac_t3:
        st.subheader("Course Scheme Repository")
        c_m1, c_m2 = st.tabs(["📤 Bulk", "📝 Manual"])
        with c_m1:
            st.markdown("**CSV Required Columns:** `course_code, title, branch_code, semester_id, credits, max_cie, max_see, is_lab, is_integrated, type, course_type, is_elective, l_hours, t_hours, p_hours, saae_hours, exam_duration_hours, total_marks`")
            f_sch = st.file_uploader("Upload Scheme CSV", type='csv')
            if f_sch and st.button("Save Full Scheme"):
                df = pd.read_csv(f_sch).rename(columns={'course_title': 'title'})
                expected = ['course_code', 'title', 'branch_code', 'semester_id', 'credits', 'max_cie', 'max_see', 'is_lab', 'is_integrated', 'type', 'course_type', 'is_elective', 'l_hours', 't_hours', 'p_hours', 'saae_hours', 'exam_duration_hours', 'total_marks']
                nums = ['semester_id', 'credits', 'max_cie', 'max_see', 'total_marks', 'l_hours', 't_hours', 'p_hours', 'saae_hours', 'exam_duration_hours']
                data = clean_data_for_db(df, expected, numeric_cols=nums)
                supabase.table("master_courses").upsert(data).execute()
                st.success("Scheme Updated Successfully.")
        with c_m2:
            with st.form("course_manual"):
                col1, col2 = st.columns(2)
                cc = col1.text_input("Course Code")
                ct = col2.text_input("Title")
                cbc = col1.text_input("Branch Code")
                cs = col2.number_input("Semester ID", 1, 8, 1)
                ccr = col1.number_input("Credits", 0, 5, 4)
                if st.form_submit_button("💾 Add/Update Course"):
                    supabase.table("master_courses").upsert({"course_code": cc, "title": ct, "branch_code": cbc, "semester_id": cs, "credits": ccr}).execute()
                    st.success("Course saved.")
                if st.form_submit_button("🗑️ Delete Course"):
                    supabase.table("master_courses").delete().eq("course_code", cc).execute()
                    st.warning("Course removed.")
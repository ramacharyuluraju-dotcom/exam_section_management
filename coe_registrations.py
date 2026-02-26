import streamlit as st
import pandas as pd
from utils import init_db, clean_data_for_db

# --- CONFIGURATION ---
# Note: st.set_page_config removed because app.py handles it
supabase = init_db()

st.title("📝 Semester Course Registration")
st.sidebar.markdown("### Operational Phase")

# --- GLOBAL CONTEXT ---
# Pulls the active cycle directly from the session state managed by app.py
selected_cycle_id = st.session_state.get('active_cycle_id')

if not selected_cycle_id:
    st.warning("⚠️ Please select an Active Exam Cycle in the Sidebar to proceed.")
    st.stop()

st.info(f"🔵 Currently Registering Students for Cycle: **{st.session_state.get('active_cycle_name')}**")

# --- NAVIGATION ---
reg_tabs = st.tabs(["📤 Bulk Registration", "📝 Manual Mapping", "🔍 View Registrations"])

# ==========================================
# 1. BULK REGISTRATION (CSV)
# ==========================================
with reg_tabs[0]:
    st.header("Step 2.1: Bulk Course Mapping")
    st.info("Upload a CSV to map multiple students to their respective courses.")
    
    # Show Column Guide for user clarity
    st.markdown("**CSV Required Columns:** `usn, course_code, academic_year, semester_type`")
    st.caption("Note: The system will automatically link these to the currently active Exam Cycle.")
    
    f_reg = st.file_uploader("Upload Registration CSV", type='csv', key="reg_bulk")
    
    if f_reg and st.button("Execute Bulk Registration"):
        df = pd.read_csv(f_reg)
        
        # Exact columns from your 'course_registrations' schema
        expected = ['usn', 'course_code', 'academic_year', 'semester_type']
        
        # Clean data (Registration table has no specific numeric columns other than ID)
        data = clean_data_for_db(df, expected)
        
        # --- NEW: ATTACH TO ACTIVE CYCLE ---
        for row in data:
            row['cycle_id'] = selected_cycle_id
            
        try:
            # course_registrations table
            supabase.table("course_registrations").upsert(data).execute()
            st.success(f"✅ Successfully registered {len(data)} student-course mappings for this cycle.")
        except Exception as e:
            st.error(f"Registration failed: {e}")
            st.warning("Ensure the USN exists in 'master_students' and Course Code exists in 'master_courses'.")

# ==========================================
# 2. MANUAL MAPPING (Individual)
# ==========================================
with reg_tabs[1]:
    st.header("Step 2.2: Individual Student Mapping")
    
    with st.form("manual_reg_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        r_usn = col1.text_input("Student USN")
        r_course = col2.text_input("Course Code")
        r_ay = col1.text_input("Academic Year", value="2025-26")
        r_sem = col2.selectbox("Semester Type", ["ODD", "EVEN"])
        
        c1, c2 = st.columns(2)
        if c1.form_submit_button("💾 Register Course"):
            reg_data = {
                "cycle_id": selected_cycle_id, # Attached to Active Cycle
                "usn": r_usn.strip().upper(),
                "course_code": r_course.strip().upper(),
                "academic_year": r_ay,
                "semester_type": r_sem
            }
            try:
                supabase.table("course_registrations").upsert(reg_data).execute()
                st.success(f"✅ Registered {r_course} for {r_usn}")
            except Exception as e:
                st.error(f"Error: {e}")

        if c2.form_submit_button("🗑️ Remove Registration"):
            try:
                # Must match both cycle AND student/course to delete safely
                supabase.table("course_registrations").delete().match({
                    "cycle_id": selected_cycle_id,
                    "usn": r_usn.strip().upper(), 
                    "course_code": r_course.strip().upper()
                }).execute()
                st.warning(f"Removed registration for {r_usn} in this cycle.")
            except Exception as e:
                st.error(f"Error: {e}")

# ==========================================
# 3. VIEW REGISTRATIONS
# ==========================================
with reg_tabs[2]:
    st.header(f"🔍 Current Course Mappings for {st.session_state.get('active_cycle_name')}")
    search_usn = st.text_input("Filter by USN (Optional)")
    
    if st.button("Fetch Registration Data"):
        # Filter strictly by the active cycle
        query = supabase.table("course_registrations").select("*").eq("cycle_id", selected_cycle_id)
        
        if search_usn:
            query = query.eq("usn", search_usn.strip().upper())
        
        res = query.execute()
        if res.data:
            view_df = pd.DataFrame(res.data)
            st.dataframe(view_df, use_container_width=True)
            st.write(f"Total Records in this cycle: {len(view_df)}")
        else:
            st.write("No registration records found for this cycle.")
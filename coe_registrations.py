import streamlit as st
import pandas as pd
import base64
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

# --- HELPER FUNCTIONS ---
@st.cache_data(ttl=3600)
def fetch_student_photo_b64(usn):
    """Securely fetches photo bytes from Supabase and converts to base64 for HTML embedding."""
    clean_usn = str(usn).strip().upper()
    for ext in ['.jpg', '.jpeg', '.png', '.webp', '.JPG', '.PNG', '.JPEG', '.WEBP']:
        try:
            res = supabase.storage.from_("StakeHolders_Photos").download(f"{clean_usn}{ext}")
            if res:
                return base64.b64encode(res).decode('utf-8')
        except Exception:
            continue
    return None

def fetch_all_records(table_name, select_query="*", filters=None):
    all_data = []
    start, step = 0, 1000
    while True:
        query = supabase.table(table_name).select(select_query)
        if filters:
            for col, val in filters.items(): 
                query = query.eq(col, val)
        query = query.range(start, start + step - 1)
        res = query.execute()
        if not res.data: break
        all_data.extend(res.data)
        if len(res.data) < step: break
        start += step
    return all_data

# --- NAVIGATION ---
reg_tabs = st.tabs(["📤 Bulk Registration", "📝 Manual Mapping", "🔍 View Registrations", "📄 Generate PG Forms"])

# ==========================================
# 1. BULK REGISTRATION (CSV)
# ==========================================
with reg_tabs[0]:
    st.header("Step 2.1: Bulk Course Mapping")
    st.info("Upload a CSV to map multiple students to their respective courses.")
    
    st.markdown("**CSV Required Columns:** `usn, course_code, academic_year, semester_type`")
    st.caption("Note: The system will automatically link these to the currently active Exam Cycle.")
    
    f_reg = st.file_uploader("Upload Registration CSV", type='csv', key="reg_bulk")
    
    if f_reg and st.button("Execute Bulk Registration"):
        df = pd.read_csv(f_reg)
        expected = ['usn', 'course_code', 'academic_year', 'semester_type']
        data = clean_data_for_db(df, expected)
        
        for row in data:
            row['cycle_id'] = selected_cycle_id
            
        try:
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
                "cycle_id": selected_cycle_id, 
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

# ==========================================
# 4. GENERATE PG FORMS (DETACHED TOOL)
# ==========================================
with reg_tabs[3]:
    st.header("📄 Generate Print-Ready PG Registration Forms")
    st.info("This utility uses your uploaded Student List and downloads their official photos directly from Supabase Storage.")
    
    c_col1, c_col2 = st.columns(2)
    target_sem = c_col1.number_input("Target Semester", min_value=1, max_value=8, value=2)
    academic_year = c_col2.text_input("Academic Year (for header)", value="2025-2026")
    
    col_s, col_c = st.columns(2)
    with col_s:
        f_students = st.file_uploader("1. Upload Students CSV", type=['csv'])
        with st.expander("Required Format"):
            st.code("usn,name,branch\n1AM25MBA01,John Doe,MBA")
    with col_c:
        f_courses = st.file_uploader("2. Upload Courses CSV", type=['csv'])
        with st.expander("Required Format"):
            st.code("Course_code,Course_title,Credits,Branch\n25MBA201,HR Management,4,MBA")

    if f_students and f_courses and st.button("⚙️ Fetch Photos & Generate Forms", type="primary"):
        with st.spinner("Building layout and downloading photos from Supabase..."):
            try:
                df_s = pd.read_csv(f_students)
                df_c = pd.read_csv(f_courses)
                
                df_s.columns = [str(c).strip().lower() for c in df_s.columns]
                df_c.columns = [str(c).strip().lower() for c in df_c.columns]
                
                if not all(k in df_s.columns for k in ['usn', 'name', 'branch']):
                    st.error("Student CSV is missing required columns ('usn', 'name', 'branch').")
                    st.stop()
                if not all(k in df_c.columns for k in ['course_code', 'course_title', 'credits', 'branch']):
                    st.error("Courses CSV is missing required columns ('course_code', 'course_title', 'credits', 'branch').")
                    st.stop()

                branch_courses = {}
                for branch, group in df_c.groupby('branch'):
                    branch_courses[str(branch).strip().upper()] = group.to_dict('records')

                # Generate HTML Boilerplate
                html_content = """
                <html>
                <head>
                <style>
                    @page { size: A4; margin: 15mm; }
                    body { font-family: 'Times New Roman', serif; font-size: 14px; color: #000; }
                    .page-break { page-break-after: always; }
                    
                    /* Header Section */
                    .header-container { text-align: center; border-bottom: 2px solid #000; padding-bottom: 10px; margin-bottom: 20px; }
                    .header-container h2 { margin: 0; font-size: 22px; font-weight: bold; }
                    .header-container p { margin: 4px 0; font-size: 14px; }
                    .form-title { font-weight: bold; font-size: 16px; margin-top: 10px; text-decoration: underline; }
                    
                    /* Student Info Section */
                    .info-section { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
                    .info-table { width: 75%; border-collapse: collapse; }
                    .info-table td { padding: 6px 0; font-size: 14px; border: none; }
                    .info-label { font-weight: bold; width: 150px; }
                    
                    /* Photo Box */
                    .photo-container { width: 25%; display: flex; justify-content: flex-end; }
                    .photo-box { width: 110px; height: 140px; border: 1px solid #000; display: flex; align-items: center; justify-content: center; text-align: center; font-size: 12px; color: #666; overflow: hidden; }
                    .photo-box img { width: 100%; height: 100%; object-fit: cover; }
                    
                    /* Course Table */
                    .course-table { width: 100%; border-collapse: collapse; margin-bottom: 40px; }
                    .course-table th, .course-table td { border: 1px solid #000; padding: 8px; text-align: center; font-size: 13px; }
                    .course-table th { font-weight: bold; background-color: #f9f9f9; }
                    .course-table td.left-align { text-align: left; }
                    
                    /* Signatures */
                    .signatures { margin-top: 100px; display: flex; justify-content: space-between; font-weight: bold; font-size: 13px; }
                    .sig-block { text-align: center; width: 22%; border-top: 1px dashed #000; padding-top: 8px; }
                </style>
                </head>
                <body>
                """
                
                generated_count = 0
                for _, student in df_s.iterrows():
                    branch = str(student.get('branch', '')).strip().upper()
                    usn = str(student.get('usn', '')).strip().upper()
                    name = str(student.get('name', '')).strip().title()
                    
                    courses = branch_courses.get(branch, [])
                    
                    if courses:
                        generated_count += 1
                        
                        # 🟢 Fetch Photo securely from Supabase
                        photo_b64 = fetch_student_photo_b64(usn)
                        if photo_b64:
                            img_html = f'<img src="data:image/jpeg;base64,{photo_b64}" alt="Photo"/>'
                        else:
                            img_html = 'Affix<br>Passport<br>Size Photo'
                        
                        html_content += f"""
                        <div class="header-container">
                            <h2>AMC ENGINEERING COLLEGE</h2>
                            <p>Autonomous Institution affiliated to VTU, Belagavi.</p>
                            <p>Bannerghatta Road, Bengaluru - 560083.</p>
                            <div class="form-title">COURSE REGISTRATION FORM - PG PROGRAM</div>
                        </div>
                        
                        <div class="info-section">
                            <table class="info-table">
                                <tr><td class="info-label">Academic Year:</td><td>{academic_year}</td></tr>
                                <tr><td class="info-label">Semester:</td><td>{target_sem}</td></tr>
                                <tr><td class="info-label">USN:</td><td>{usn}</td></tr>
                                <tr><td class="info-label">Name:</td><td>{name}</td></tr>
                                <tr><td class="info-label">Programme:</td><td>PG</td></tr>
                                <tr><td class="info-label">Branch:</td><td>{branch}</td></tr>
                            </table>
                            <div class="photo-container">
                                <div class="photo-box">
                                    {img_html}
                                </div>
                            </div>
                        </div>
                        
                        <table class="course-table">
                            <thead>
                                <tr>
                                    <th style="width: 8%;">Sl. No.</th>
                                    <th style="width: 20%;">Course Code</th>
                                    <th style="width: 60%;">Course Title</th>
                                    <th style="width: 12%;">Credit</th>
                                </tr>
                            </thead>
                            <tbody>
                        """
                        
                        total_credits = 0
                        for idx, crs in enumerate(courses, 1):
                            ccode = str(crs.get('course_code', '')).upper()
                            ctitle = str(crs.get('course_title', '')).title()
                            
                            try:
                                cred = float(crs.get('credits', 0))
                                if cred.is_integer(): cred = int(cred)
                                total_credits += cred
                            except:
                                cred = crs.get('credits', '')
                            
                            html_content += f"""
                                <tr>
                                    <td>{idx}</td>
                                    <td>{ccode}</td>
                                    <td class="left-align">{ctitle}</td>
                                    <td>{cred}</td>
                                </tr>
                            """
                        
                        html_content += f"""
                                <tr>
                                    <td colspan="3" style="text-align: right; font-weight: bold; padding-right: 15px;">Total Credits:</td>
                                    <td style="font-weight: bold;">{total_credits}</td>
                                </tr>
                            </tbody>
                        </table>
                        
                        <div class="signatures">
                            <div class="sig-block">Student Signature</div>
                            <div class="sig-block">Signature of<br>Faculty Advisor</div>
                            <div class="sig-block">Signature of<br>HOD</div>
                            <div class="sig-block">Signature of<br>Principal</div>
                        </div>
                        
                        <div class="page-break"></div>
                        """
                
                html_content += """
                </body>
                </html>
                """
                
                if generated_count > 0:
                    st.success(f"🎉 Successfully generated A4 Registration Forms for {generated_count} PG students!")
                    st.download_button(
                        label="📥 Download Printable Forms (HTML)",
                        data=html_content,
                        file_name=f"PG_Sem{target_sem}_Registration_Forms.html",
                        mime="text/html",
                        type="primary"
                    )
                    st.info("💡 **Printing Instructions:** Open the downloaded HTML file in Chrome or Edge, press `Ctrl+P`, set margins to 'None', and click 'Save as PDF' or print directly.")
                else:
                    st.warning("No students matched the branches found in your Courses CSV.")
                    
            except Exception as e:
                st.error(f"Processing error: {e}")

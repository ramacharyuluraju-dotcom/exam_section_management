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
reg_tabs = st.tabs(["📤 Bulk Registration", "📝 Manual Mapping", "🔍 View Registrations", "📄 Generate PG Forms"])

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

# ==========================================
# 4. GENERATE PG FORMS (DETACHED TOOL)
# ==========================================
with reg_tabs[3]:
    st.header("📄 Generate PG Course Registration Forms")
    st.info("This is a detached utility. It generates printable A4 HTML forms for students without altering the database.")
    
    st.write("Upload the Student List and the Course List to generate forms.")
    
    col1, col2 = st.columns(2)
    with col1:
        f_students = st.file_uploader("1. Upload Students CSV", type=['csv'])
        with st.expander("Required Student CSV Format"):
            st.code("usn,name,branch\n1AM25MBA01,John Doe,MBA\n1AM25MC034,Jane Smith,MCA")
            
    with col2:
        f_courses = st.file_uploader("2. Upload Courses CSV (e.g. Sheet1.csv)", type=['csv'])
        with st.expander("Required Courses CSV Format"):
            st.code("Course_code,Course_title,Credits,Branch\n25MBA201,Human Resource Management,4,MBA")

    if f_students and f_courses:
        if st.button("⚙️ Generate Registration Forms", type="primary"):
            with st.spinner("Generating A4 print-ready forms..."):
                try:
                    df_s = pd.read_csv(f_students)
                    df_c = pd.read_csv(f_courses)
                    
                    # Normalize columns to lowercase for safe mapping
                    df_s.columns = [str(c).strip().lower() for c in df_s.columns]
                    df_c.columns = [str(c).strip().lower() for c in df_c.columns]
                    
                    if not all(k in df_s.columns for k in ['usn', 'name', 'branch']):
                        st.error("Student CSV is missing required columns. Ensure it has 'usn', 'name', and 'branch'.")
                    elif not all(k in df_c.columns for k in ['course_code', 'course_title', 'credits', 'branch']):
                        st.error("Courses CSV is missing required columns. Ensure it has 'course_code', 'course_title', 'credits', and 'branch'.")
                    else:
                        # Group courses by branch for fast lookup
                        branch_courses = {}
                        for branch, group in df_c.groupby('branch'):
                            branch_courses[str(branch).strip().upper()] = group.to_dict('records')
                            
                        # Generate HTML Boilerplate
                        html_content = """
                        <html>
                        <head>
                        <style>
                            @page { size: A4; margin: 20mm; }
                            body { font-family: Arial, sans-serif; font-size: 14px; }
                            .page-break { page-break-after: always; }
                            .header { text-align: center; margin-bottom: 20px; }
                            .header h2 { margin: 0; padding: 0; }
                            .header h4 { margin: 5px 0; font-weight: normal; }
                            .student-info { margin-bottom: 20px; border: 1px solid #000; padding: 10px; font-size: 15px;}
                            table { width: 100%; border-collapse: collapse; margin-bottom: 30px; }
                            th, td { border: 1px solid #000; padding: 10px; text-align: left; }
                            th { background-color: #f2f2f2; }
                            .signatures { margin-top: 60px; display: flex; justify-content: space-between; }
                            .sig-block { text-align: center; width: 30%; }
                            .sig-line { border-top: 1px dashed #000; margin-top: 60px; padding-top: 5px; font-weight: bold;}
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
                                
                                html_content += f"""
                                <div class="header">
                                    <h2>AMC ENGINEERING COLLEGE</h2>
                                    <h4>Autonomous Institution Affiliated to VTU, Belagavi</h4>
                                    <h3>POST GRADUATE COURSE REGISTRATION FORM</h3>
                                    <h4>Semester: 2 | Academic Year: 2025-26</h4>
                                </div>
                                
                                <div class="student-info">
                                    <strong>USN:</strong> {usn} &nbsp;&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;&nbsp; 
                                    <strong>Name:</strong> {name} &nbsp;&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;&nbsp; 
                                    <strong>Branch/Program:</strong> {branch}
                                </div>
                                
                                <table>
                                    <thead>
                                        <tr>
                                            <th style="width: 5%; text-align: center;">Sl.No</th>
                                            <th style="width: 15%;">Course Code</th>
                                            <th style="width: 50%;">Course Title</th>
                                            <th style="width: 10%; text-align: center;">Credits</th>
                                            <th style="width: 20%; text-align: center;">Faculty Signature</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                """
                                
                                total_credits = 0
                                for idx, crs in enumerate(courses, 1):
                                    ccode = str(crs.get('course_code', '')).upper()
                                    ctitle = str(crs.get('course_title', '')).title()
                                    
                                    # Handle numeric credits vs string credits (e.g. 'PP' for Seminar)
                                    try:
                                        cred = float(crs.get('credits', 0))
                                        if cred.is_integer(): cred = int(cred)
                                        total_credits += cred
                                    except:
                                        cred = crs.get('credits', '')
                                    
                                    html_content += f"""
                                        <tr>
                                            <td style="text-align: center;">{idx}</td>
                                            <td>{ccode}</td>
                                            <td>{ctitle}</td>
                                            <td style="text-align: center;">{cred}</td>
                                            <td></td>
                                        </tr>
                                    """
                                
                                html_content += f"""
                                        <tr>
                                            <td colspan="3" style="text-align: right; font-weight: bold;">Total Credits:</td>
                                            <td style="text-align: center; font-weight: bold;">{total_credits}</td>
                                            <td></td>
                                        </tr>
                                    </tbody>
                                </table>
                                
                                <div class="signatures">
                                    <div class="sig-block">
                                        <div class="sig-line">Signature of the Student</div>
                                    </div>
                                    <div class="sig-block">
                                        <div class="sig-line">Signature of HOD</div>
                                    </div>
                                    <div class="sig-block">
                                        <div class="sig-line">Signature of Principal</div>
                                    </div>
                                </div>
                                
                                <div class="page-break"></div>
                                """
                        
                        html_content += """
                        </body>
                        </html>
                        """
                        
                        if generated_count > 0:
                            st.success(f"🎉 Successfully generated A4 Registration Forms for {generated_count} students!")
                            st.download_button(
                                label="📥 Download Printable Forms (HTML)",
                                data=html_content,
                                file_name="PG_Sem2_Registration_Forms.html",
                                mime="text/html",
                                type="primary"
                            )
                            st.info("💡 **Printing Instructions:** Open the downloaded HTML file in Chrome or Edge, press `Ctrl+P` (or `Cmd+P`), set margins to 'None' or 'Minimum', and click 'Save as PDF' or print directly to an A4 printer.")
                        else:
                            st.warning("No matching branches were found between your Students CSV and your Courses CSV.")
                            
                except Exception as e:
                    st.error(f"Processing error: {e}")

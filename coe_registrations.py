import streamlit as st
import pandas as pd
import io
import zipfile
from utils import init_db, clean_data_for_db

# --- REPORTLAB IMPORTS FOR PDF GENERATION ---
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

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

# --- PDF GENERATOR FUNCTION FOR REGISTRATION FORMS ---
def generate_registration_form(buffer, student, courses_list, academic_year, semester):
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    elements = []
    styles = getSampleStyleSheet()
    
    style_center = ParagraphStyle('Center', parent=styles['Heading1'], alignment=1, fontSize=14, spaceAfter=5)
    style_sub = ParagraphStyle('Sub', parent=styles['Heading3'], alignment=1, fontSize=10, spaceAfter=20)
    
    # Header
    elements.append(Paragraph("AMC ENGINEERING COLLEGE", style_center))
    elements.append(Paragraph("Autonomous Institution Affiliated to VTU, Belagavi", style_sub))
    elements.append(Paragraph(f"<b>SEMESTER COURSE REGISTRATION FORM (Academic Year: {academic_year})</b>", style_center))
    elements.append(Spacer(1, 15))
    
    # Student Details
    s_data = [
        ["USN:", student['usn'], "Name:", student.get('full_name', '')],
        ["Branch:", student.get('branch_code', ''), "Semester:", str(semester)]
    ]
    t_info = Table(s_data, colWidths=[60, 180, 60, 180])
    t_info.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
        ('BACKGROUND', (2,0), (2,-1), colors.lightgrey),
        ('PADDING', (0,0), (-1,-1), 6)
    ]))
    elements.append(t_info)
    elements.append(Spacer(1, 20))
    
    # Instructions
    elements.append(Paragraph("<i>Instructions: Please tick (✓) the box next to the courses you are registering for. Core courses are mandatory. Ensure credit limits are met.</i>", styles['Normal']))
    elements.append(Spacer(1, 10))
    
    # Courses Table
    c_data = [["Sl", "Course Code", "Course Title", "Type", "Credits", "Opted (✓)"]]
    
    for i, c in enumerate(courses_list):
        c_type = c.get('type', 'Core')
        is_elec = c.get('is_elective', False)
        display_type = "Elective" if is_elec else c_type
        
        c_data.append([
            str(i+1),
            c['course_code'],
            Paragraph(c.get('title', ''), styles['Normal']),
            display_type,
            str(c.get('credits', 0)),
            "" # Empty box for ticking
        ])
        
    t_courses = Table(c_data, colWidths=[30, 80, 220, 60, 45, 60])
    t_courses.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (0,-1), 'CENTER'), # Sl
        ('ALIGN', (3,0), (5,-1), 'CENTER'), # Type, Credits, Opted
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 6)
    ]))
    elements.append(t_courses)
    elements.append(Spacer(1, 40))
    
    # Signatures
    sig_data = [
        ["________________________", "________________________", "________________________"],
        ["Signature of the Student", "Signature of Faculty Advisor", "Signature of HOD"],
        ["Date:", "Date:", "Date:"]
    ]
    t_sig = Table(sig_data, colWidths=[160, 160, 160])
    t_sig.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10)
    ]))
    elements.append(t_sig)
    
    doc.build(elements)


# --- GLOBAL CONTEXT ---
selected_cycle_id = st.session_state.get('active_cycle_id')

if not selected_cycle_id:
    st.warning("⚠️ Please select an Active Exam Cycle in the Sidebar to proceed.")
    st.stop()

st.info(f"🔵 Currently Managing Registrations for Cycle: **{st.session_state.get('active_cycle_name')}**")

# ==========================================
# NAVIGATION TABS
# ==========================================
reg_tabs = st.tabs([
    "📄 Generate Forms",
    "📤 Bulk Upload", 
    "📝 Interactive Mapping", 
    "🔍 View Registrations", 
    "📸 Photo Backup", 
    "📥 Arrear Extractor",
    "🚑 Make-up Extractor" 
])

# ==========================================
# 1. GENERATE REGISTRATION FORMS (DAY 1)
# ==========================================
with reg_tabs[0]:
    st.header("Step 1: Generate Physical Registration Forms")
    st.info("Generates PDF forms listing all available courses for a specific semester/branch. Distribute these to students for physical signature before doing data entry.")
    
    col_f1, col_f2, col_f3 = st.columns(3)
    f_ay = col_f1.text_input("Academic Year for Form", value=st.session_state.get('active_academic_year', '2025-26'))
    
    branches_data = fetch_all_records("master_branches", "branch_code, branch_name")
    # Filter out COMMON from the UI dropdown
    branch_list = [b['branch_code'] for b in branches_data if str(b['branch_code']).upper() != 'COMMON']
    f_branch = col_f2.selectbox("Select Branch", ["-- Select --"] + branch_list)
    
    f_sem = col_f3.number_input("Target Semester", min_value=1, max_value=10, value=1)
    
    if st.button("🖨️ Generate PDF Forms (ZIP)", type="primary"):
        if f_branch == "-- Select --":
            st.error("Please select a valid branch.")
        else:
            with st.spinner(f"Compiling courses and generating forms for {f_branch} Semester {f_sem}..."):
                try:
                    # 1. Fetch Students for this branch and sem
                    students = fetch_all_records("master_students", "*", {"branch_code": f_branch, "current_sem": str(f_sem)})
                    
                    if not students:
                        st.warning(f"No students found currently enrolled in {f_branch} Semester {f_sem}.")
                    else:
                        # 2. Fetch Courses for this branch/sem AND COMMON
                        courses_res = fetch_all_records("master_courses", "course_code, title, branch_code, credits, type, is_elective", {"semester_id": f_sem})
                        
                        # Filter down to specific branch + COMMON
                        valid_courses = [c for c in courses_res if c['branch_code'] in [f_branch, 'COMMON']]
                        
                        if not valid_courses:
                            st.warning(f"No courses found in the Master Syllabus for {f_branch} or COMMON in Semester {f_sem}. Please update the Academic Master first.")
                        else:
                            # 3. Generate ZIP of PDFs
                            zip_buffer = io.BytesIO()
                            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                                progress_bar = st.progress(0)
                                total_stu = len(students)
                                
                                for i, stu in enumerate(students):
                                    pdf_buf = io.BytesIO()
                                    generate_registration_form(pdf_buf, stu, valid_courses, f_ay, f_sem)
                                    zf.writestr(f"Registration_Form_{stu['usn']}.pdf", pdf_buf.getvalue())
                                    progress_bar.progress((i + 1) / total_stu)
                                    
                            st.success(f"✅ Generated {len(students)} personalized Registration Forms!")
                            
                            st.download_button(
                                label=f"📥 Download {f_branch}_Sem{f_sem}_RegForms.zip",
                                data=zip_buffer.getvalue(),
                                file_name=f"Reg_Forms_{f_branch}_Sem{f_sem}_{f_ay}.zip",
                                mime="application/zip",
                                type="primary"
                            )
                except Exception as e:
                    st.error(f"Generation Error: {e}")

# ==========================================
# 2. BULK REGISTRATION (CSV)
# ==========================================
with reg_tabs[1]:
    st.header("Step 2.1: Bulk Course Mapping")
    st.info("Download a pre-filled template containing all students and courses for a branch. Open it in Excel, delete rows for courses the student did NOT select on their physical form, and upload it back.")
    
    col_b1, col_b2 = st.columns(2)
    
    with col_b1:
        st.subheader("A. Download Pre-filled Template")
        
        # Fetch branches and filter out COMMON
        try:
            b_data = fetch_all_records("master_branches", "branch_code")
            tmpl_branches = [b['branch_code'] for b in b_data if str(b['branch_code']).upper() != 'COMMON']
        except:
            tmpl_branches = []
            
        t_branch = st.selectbox("Target Branch", ["-- Select --"] + tmpl_branches, key="t_branch")
        t_sem = st.number_input("Target Semester", min_value=1, max_value=10, value=1, key="t_sem")
        t_ay = st.text_input("Academic Year", value=st.session_state.get('active_academic_year', '2025-26'), key="t_ay")
        t_type = st.selectbox("Semester Type", ["ODD", "EVEN", "BOTH"], key="t_type")
        
        if st.button("📥 Generate CSV Template", type="secondary"):
            if t_branch == "-- Select --":
                st.error("Please select a branch.")
            else:
                with st.spinner("Building master template..."):
                    # Fetch students in this branch/sem
                    stu_data = fetch_all_records("master_students", "usn", {"branch_code": t_branch, "current_sem": str(t_sem)})
                    # Fetch courses for this sem
                    crs_data = fetch_all_records("master_courses", "course_code, branch_code", {"semester_id": t_sem})
                    # Filter valid courses (Branch specific + COMMON)
                    valid_crs = [c['course_code'] for c in crs_data if c['branch_code'] in [t_branch, 'COMMON']]
                    
                    if not stu_data:
                        st.warning(f"No students found in {t_branch} Semester {t_sem}.")
                    elif not valid_crs:
                        st.warning(f"No courses found for {t_branch} / COMMON in Semester {t_sem}.")
                    else:
                        # Cross-join students and courses
                        template_rows = []
                        for s in stu_data:
                            for c in valid_crs:
                                template_rows.append({
                                    "usn": s['usn'],
                                    "course_code": c,
                                    "academic_year": t_ay,
                                    "semester_type": t_type,
                                    "semester": t_sem
                                })
                        
                        df_tmpl = pd.DataFrame(template_rows)
                        csv_bytes = df_tmpl.to_csv(index=False).encode('utf-8')
                        
                        st.success("✅ Template generated! Edit this file, then upload it on the right.")
                        st.download_button(
                            label=f"📥 Download {t_branch} Sem {t_sem} Template",
                            data=csv_bytes,
                            file_name=f"Registration_Template_{t_branch}_Sem{t_sem}.csv",
                            mime="text/csv",
                            type="primary"
                        )

    with col_b2:
        st.subheader("B. Upload Finalized Registrations")
        f_reg = st.file_uploader("Upload Edited CSV", type='csv', key="reg_bulk")
        
        if f_reg and st.button("🚀 Execute Bulk Registration", type="primary"):
            df = pd.read_csv(f_reg)
            expected = ['usn', 'course_code', 'academic_year', 'semester_type', 'semester']
            data = clean_data_for_db(df, expected)
            
            if not data:
                st.error("Invalid CSV format. Please ensure all columns are present.")
            else:
                with st.spinner("Processing registrations..."):
                    try:
                        # Safety feature: Find all USNs in the upload and wipe their old registrations 
                        # for this cycle. This ensures that if you deleted a row in the CSV, it actually 
                        # gets removed from the database.
                        uploaded_usns = list(set([r['usn'] for r in data]))
                        
                        # Delete in batches to avoid URL length errors
                        for i in range(0, len(uploaded_usns), 100):
                            batch_usns = uploaded_usns[i:i+100]
                            supabase.table("course_registrations").delete().eq("cycle_id", selected_cycle_id).in_("usn", batch_usns).execute()
                        
                        # Insert the new, finalized data
                        for row in data: 
                            row['cycle_id'] = selected_cycle_id
                            
                        # Insert in batches
                        for i in range(0, len(data), 500):
                            supabase.table("course_registrations").insert(data[i:i+500]).execute()
                            
                        st.success(f"✅ Successfully registered {len(data)} student-course mappings!")
                    except Exception as e:
                        st.error(f"Registration failed: {e}")


# ==========================================
# 3. INTERACTIVE INDIVIDUAL MAPPING
# ==========================================
with reg_tabs[2]:
    st.header("Step 2.2: Interactive Individual Registration")
    st.info("Select a branch and student to dynamically load applicable courses based on the syllabus.")
    
    col1, col2 = st.columns(2)
    
    branch_list_interactive = []
    try:
        branches_data_int = fetch_all_records("master_branches", "branch_code, branch_name")
        # Filter out COMMON from the UI dropdown
        branch_list_interactive = [b['branch_code'] for b in branches_data_int if str(b['branch_code']).upper() != 'COMMON']
    except: pass
    
    selected_branch = col1.selectbox("1. Select Branch", ["-- Select --"] + branch_list_interactive, key="int_branch")
    
    if selected_branch != "-- Select --":
        students_data = fetch_all_records("master_students", "usn, full_name", {"branch_code": selected_branch})
        
        if not students_data:
            st.warning(f"No students found in the database for branch: {selected_branch}")
        else:
            student_options = {f"{s['usn']} - {s['full_name']}": s['usn'] for s in students_data}
            selected_student_label = col2.selectbox("2. Select Student", ["-- Select --"] + list(student_options.keys()))
            
            if selected_student_label != "-- Select --":
                selected_usn = student_options[selected_student_label]
                
                courses_data = fetch_all_records("master_courses", "course_code, title, branch_code")
                applicable_courses = [c for c in courses_data if c['branch_code'] in [selected_branch, 'COMMON']]
                
                if not applicable_courses:
                    st.warning("No courses mapped to this branch or 'COMMON'.")
                else:
                    st.markdown("### 3. Select Subjects to Register")
                    
                    existing_regs = fetch_all_records("course_registrations", "course_code", {
                        "cycle_id": selected_cycle_id, 
                        "usn": selected_usn
                    })
                    already_registered = [r['course_code'] for r in existing_regs]
                    
                    with st.form("dynamic_registration_form"):
                        c1, c2 = st.columns(2)
                        r_ay = c1.text_input("Academic Year", value=st.session_state.get('active_academic_year', '2025-26'))
                        r_sem_type = c2.selectbox("Semester Type", ["ODD", "EVEN", "BOTH"])
                        r_semester = c1.number_input("Semester (for these subjects)", min_value=1, max_value=10, value=1)
                        
                        st.divider()
                        
                        selected_course_codes = []
                        for course in applicable_courses:
                            is_checked = course['course_code'] in already_registered
                            if st.checkbox(f"{course['course_code']} - {course['title']}", value=is_checked):
                                selected_course_codes.append(course['course_code'])
                        
                        if st.form_submit_button("💾 Save Registrations", type="primary"):
                            with st.spinner("Updating records..."):
                                try:
                                    supabase.table("course_registrations").delete().match({
                                        "cycle_id": selected_cycle_id, 
                                        "usn": selected_usn
                                    }).execute()
                                    
                                    if selected_course_codes:
                                        payload = []
                                        for cc in selected_course_codes:
                                            payload.append({
                                                "cycle_id": selected_cycle_id, 
                                                "usn": selected_usn, 
                                                "course_code": cc, 
                                                "academic_year": r_ay, 
                                                "semester_type": r_sem_type,
                                                "semester": r_semester
                                            })
                                        supabase.table("course_registrations").insert(payload).execute()
                                        
                                    st.success(f"✅ Successfully updated registrations for {selected_usn}! Total subjects mapped: {len(selected_course_codes)}")
                                except Exception as e:
                                    st.error(f"Database Error: {e}")

# ==========================================
# 4. VIEW REGISTRATIONS
# ==========================================
with reg_tabs[3]:
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
# 5. PHOTO BACKUP UTILITY (ZIP DOWNLOAD)
# ==========================================
with reg_tabs[4]:
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
# 6. ARREAR EXTRACTOR
# ==========================================
with reg_tabs[5]:
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
# 7. MAKE-UP EXAM EXTRACTOR
# ==========================================
with reg_tabs[6]:
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
                        
                        if grade in ['AB', 'F']:
                            c_info = course_map.get(cc, {"max_cie": 50.0, "title": "Unknown", "sem": 0})
                            max_cie = c_info['max_cie']
                            cie_obtained = data['cie_marks']
                            
                            cie_percentage = (cie_obtained / max_cie) * 100 if max_cie > 0 else 0
                            
                            eligibility_category = None
                            
                            if grade == 'F' and cie_percentage >= x_grade_thresh:
                                eligibility_category = "⭐ X-Grade: Failed but High CIE"
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
                        if 'X-Grade' in str(val): return 'color: #4CAF50; font-weight: bold' 
                        elif 'I-Grade' in str(val): return 'color: #FF9800; font-weight: bold' 
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

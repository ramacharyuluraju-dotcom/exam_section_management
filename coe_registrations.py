import streamlit as st
import pandas as pd
import io
import zipfile
import datetime
import os
import re
import concurrent.futures
from PIL import Image as PILImage
from utils import init_db, clean_data_for_db

# --- REPORTLAB IMPORTS FOR PDF GENERATION ---
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# --- CONFIGURATION ---
LOGO_FILENAME = "College_logo.png"       
NAAC_FILENAME = "NAAC_A_Logo.jpg"        
WATERMARK_FILENAME = "AMC_watermark.png" 
supabase = init_db()

st.title("📝 Semester Course Registration")
st.sidebar.markdown("### Operational Phase")

# --- HELPER FUNCTIONS ---
def fetch_all_records(table_name, select_query="*", filters=None):
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

def get_checkbox():
    """Generates a perfect square box for the table cells"""
    t = Table([[""]], colWidths=[12], rowHeights=[12])
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.8, colors.black),
        ('BACKGROUND', (0,0), (-1,-1), colors.white)
    ]))
    return t

def course_sort_key(s):
    """
    Extracts the main 3-digit course number (e.g., 201, 202) for perfect numeric sorting.
    It finds all numbers in the string and uses the last one as the primary sort key.
    """
    code_str = str(s).strip().upper()
    numbers = re.findall(r'\d+', code_str)
    # The course number is almost always the last set of digits in the code (e.g. '1BESC204C' -> 204)
    main_num = int(numbers[-1]) if numbers else 9999
    return (main_num, code_str)

# ==========================================
# PHOTO BUCKET MAPPING UTILS 
# ==========================================
def fetch_complete_bucket_map(bucket_name):
    file_map = {}
    limit = 1000; offset = 0
    while True:
        try:
            files = supabase.storage.from_(bucket_name).list("", options={"limit": limit, "offset": offset})
            if not files: break
            for f in files:
                fname = f.get('name', '')
                if not fname or fname == '.emptyFolderPlaceholder': continue
                basename = os.path.basename(fname)
                key = re.sub(r'[^A-Z0-9]', '', os.path.splitext(basename)[0].upper())
                file_map[key] = fname
            if len(files) < limit: break
            offset += limit
        except: break
    return file_map

def download_photo_worker(args):
    usn, file_map = args
    clean_usn = re.sub(r'[^A-Z0-9]', '', usn.upper())
    
    if clean_usn in file_map:
        try:
            res = supabase.storage.from_("StakeHolders_Photos").download(file_map[clean_usn])
            if res:
                img = PILImage.open(io.BytesIO(res))
                if img.mode != 'RGB': img = img.convert('RGB')
                clean_io = io.BytesIO()
                img.save(clean_io, format='JPEG', quality=95)
                clean_io.seek(0)
                return usn, clean_io
        except: pass

    for ext in ['.webp', '.jpg', '.jpeg', '.png', '.WEBP', '.JPG', '.PNG']:
        try:
            res = supabase.storage.from_("StakeHolders_Photos").download(f"{clean_usn}{ext}")
            if res:
                img = PILImage.open(io.BytesIO(res))
                if img.mode != 'RGB': img = img.convert('RGB')
                clean_io = io.BytesIO()
                img.save(clean_io, format='JPEG', quality=95)
                clean_io.seek(0)
                return usn, clean_io
        except: pass
            
    return usn, None

# ==========================================
# 🟢 EXACT REPLICA PDF GENERATOR ENGINE
# ==========================================
def draw_header(c, w, y_start, assets):
    margin = 35
    if assets.get("logo"):
        c.drawImage(ImageReader(assets["logo"]), margin, y_start - 35, width=60, height=60, mask='auto', preserveAspectRatio=True)
    if assets.get("naac"):
        c.drawImage(ImageReader(assets["naac"]), w - margin - 60, y_start - 35, width=60, height=60, mask='auto', preserveAspectRatio=True)

    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(w/2, y_start, "AMC ENGINEERING COLLEGE")
    c.setFont("Helvetica", 9)
    c.drawCentredString(w/2, y_start - 15, "AMC Campus, Bannerghatta Road, Bengaluru, Karnataka - 560083")
    c.drawCentredString(w/2, y_start - 27, "Autonomous Institution Affiliated to VTU, Belagavi | NAAC A+ Accredited")
    
    c.setLineWidth(1)
    c.line(margin, y_start - 45, w - margin, y_start - 45)
    return y_start - 65

def draw_registration_page(c, w, h, student, courses, assets, photo_io, form_title, sem, date_str, prog_type):
    margin = 35
    content_w = w - (2 * margin) 
    
    if assets.get("watermark"):
        c.saveState()
        c.setFillAlpha(0.08)
        c.drawImage(ImageReader(assets["watermark"]), w/2 - 175, h/2 - 175, width=350, height=350, mask='auto', preserveAspectRatio=True)
        c.restoreState()

    y = draw_header(c, w, h - margin, assets)
    
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(w/2, y, form_title)
    y -= 25

    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "Student Details")
    y -= 5

    if photo_io:
        photo_io.seek(0)
        p_img = RLImage(photo_io, width=55, height=70)
        p_img.hAlign = 'CENTER'
        p_img.vAlign = 'MIDDLE'
        s_data = [
            ["USN", "Student Name", "Branch", "Type", "Photo"],
            [student['usn'], student.get('full_name',''), student.get('branch_code',''), prog_type, p_img]
        ]
        style_cmds = [
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE')
        ]
    else:
        p_img = Paragraph("<para align=center>PHOTO</para>", getSampleStyleSheet()['Normal'])
        s_data = [
            ["USN", "Student Name", "Branch", "Type", p_img],
            [student['usn'], student.get('full_name',''), student.get('branch_code',''), prog_type, ""]
        ]
        style_cmds = [
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('SPAN', (4, 0), (4, 1))
        ]

    t1 = Table(s_data, colWidths=[70, 205.27, 60, 90, 100], rowHeights=[20, 75])
    t1.setStyle(TableStyle(style_cmds))
    t1.wrapOn(c, w, h)
    _, t1_h = t1.wrap(w, h)
    t1.drawOn(c, margin, y - t1_h)
    y -= (t1_h + 20)

    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, f"Semester: {sem}")
    y -= 20

    c.drawString(margin, y, "Courses offered")
    y -= 5

    c_data = [["Course code", "Course title", "Credits", "Select"]]
    total_cr = 0
    for crs in courses:
        cr_val = safe_float(crs.get('credits', 0))
        total_cr += cr_val
        c_data.append([
            crs['course_code'],
            Paragraph(crs.get('title',''), getSampleStyleSheet()['Normal']),
            str(int(cr_val) if cr_val.is_integer() else cr_val),
            get_checkbox()
        ])
    c_data.append(["", Paragraph("<b>Total Credits</b>", getSampleStyleSheet()['Normal']), str(int(total_cr)), ""])

    t2 = Table(c_data, colWidths=[80, 315.27, 60, 70])
    t2.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (0,-1), 'CENTER'), 
        ('ALIGN', (2,0), (-1,-1), 'CENTER'), 
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    t2.wrapOn(c, w, h)
    _, t2_h = t2.wrap(w, h)
    t2.drawOn(c, margin, y - t2_h)
    y -= (t2_h + 25)

    # 🟢 FOUR STUDENT UNDERTAKINGS FIRST
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "STUDENT UNDERTAKING:")
    y -= 15

    c.setLineWidth(1)
    c.setFont("Helvetica", 9)
    
    undertakings = [
        "I will follow the AMCEC / VTU autonomy guidelines.",
        "I have paid the full tuition fees and examination fees for the current semester.",
        "I am aware that I must maintain a minimum of 85% attendance to appear for SEE.",
        "I have verified that my selected credits align with the academic regulations."
    ]
    
    for u in undertakings:
        c.rect(margin, y - 8, 10, 10) 
        c.drawString(margin + 18, y - 6, u)
        y -= 18

    y -= 10
    
    # 🟢 DECLARATION SECOND
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "DECLARATION:")
    y -= 15
    
    p_style = getSampleStyleSheet()['Normal']
    p_style.fontSize = 9
    decl = Paragraph("I hereby declare that the information provided is true to the best of my knowledge. I have carefully selected the courses listed above and I request to be registered for the same in the current semester.", p_style)
    decl.wrapOn(c, content_w, 50)
    _, decl_h = decl.wrap(content_w, 50)
    decl.drawOn(c, margin, y - decl_h)
    y -= (decl_h + 30)

    # 🟢 SIGNATURES (Date Left, Student Right)
    sig_data = [
        [f"Date: {date_str}", "________________________"],
        ["", "Signature of the Student"]
    ]
    t_sig = Table(sig_data, colWidths=[content_w/2, content_w/2])
    t_sig.setStyle(TableStyle([
        ('ALIGN', (0,0), (0,-1), 'LEFT'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
    ]))
    t_sig.wrapOn(c, content_w, 50)
    _, sig_h = t_sig.wrap(content_w, 50)
    t_sig.drawOn(c, margin, y - sig_h)


# --- GLOBAL CONTEXT ---
selected_cycle_id = st.session_state.get('active_cycle_id')
if not selected_cycle_id:
    st.warning("⚠️ Please select an Active Exam Cycle in the Sidebar to proceed.")
    st.stop()

st.info(f"🔵 Currently Managing Registrations for Cycle: **{st.session_state.get('active_cycle_name')}**")

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
# 1. GENERATE REGISTRATION FORMS
# ==========================================
with reg_tabs[0]:
    st.header("Step 1: Generate Physical Registration Forms")
    st.info("Generates a single, bulk PDF containing registration forms for the entire branch. Automatically maps Logos, Watermarks, and Student Photos from the cloud.")
    
    col_f1, col_f2, col_f3 = st.columns(3)
    f_title = col_f1.text_input("Form Header Title", value="Course Registration - Second Semester 2025-26")
    
    branches_data = fetch_all_records("master_branches", "branch_code, branch_name, program_type")
    branch_prog_map = {b['branch_code']: b.get('program_type', 'UG') for b in branches_data}
    branch_list = [b['branch_code'] for b in branches_data if str(b['branch_code']).upper() != 'COMMON']
    
    f_branch = col_f2.selectbox("Target Branch", ["-- Select --", "ALL BRANCHES"] + branch_list)
    f_sem = col_f3.number_input("Target Semester", min_value=1, max_value=10, value=1)
    
    st.markdown("#### Course Source")
    f_csv = st.file_uploader("Override Syllabus with Custom CSV (Optional - Filters by 'Streams')", type="csv", key="pdf_csv_upload")
    
    if st.button("🖨️ Generate Master PDF", type="primary"):
        if f_branch == "-- Select --":
            st.error("Please select a target branch.")
        else:
            with st.spinner(f"Fetching cloud assets and compiling batch PDF..."):
                try:
                    if f_branch == "ALL BRANCHES":
                        students = fetch_all_records("master_students", "*", {"current_sem": str(f_sem)})
                    else:
                        students = fetch_all_records("master_students", "*", {"branch_code": f_branch, "current_sem": str(f_sem)})
                    
                    if not students:
                        st.warning(f"No students found for this criteria.")
                    else:
                        branch_courses_dict = {}
                        
                        if f_csv is not None:
                            df_crs = pd.read_csv(f_csv)
                            col_map = {c.strip().upper(): c for c in df_crs.columns}
                            
                            code_col = col_map.get('COURSE CODE', df_crs.columns[0])
                            title_col = col_map.get('COURSE NAME', col_map.get('TITLE', df_crs.columns[1] if len(df_crs.columns) > 1 else df_crs.columns[0]))
                            stream_col = col_map.get('STREAMS', col_map.get('BRANCH', None))
                            cred_col = col_map.get('CREDITS', None)
                            
                            for _, r in df_crs.iterrows():
                                br = str(r[stream_col]).strip().upper() if stream_col else "COMMON"
                                if br not in branch_courses_dict: branch_courses_dict[br] = []
                                branch_courses_dict[br].append({
                                    'course_code': str(r[code_col]).strip(),
                                    'title': str(r[title_col]),
                                    'credits': r[cred_col] if cred_col else '-'
                                })
                        else:
                            all_courses = fetch_all_records("master_courses", "course_code, title, branch_code, credits", {"semester_id": f_sem})
                            for c in all_courses:
                                br = str(c['branch_code']).strip().upper()
                                if br not in branch_courses_dict: branch_courses_dict[br] = []
                                branch_courses_dict[br].append(c)

                        system_assets = {"logo": None, "naac": None, "watermark": None}
                        sys_map = {"logo": LOGO_FILENAME, "naac": NAAC_FILENAME, "watermark": WATERMARK_FILENAME}
                        for k, f in sys_map.items():
                            try:
                                res = supabase.storage.from_("College_Logos").download(f)
                                if res: system_assets[k] = io.BytesIO(res) 
                            except: pass
                        
                        photo_file_map = fetch_complete_bucket_map("StakeHolders_Photos")
                        
                        final_pdf_buffer = io.BytesIO()
                        c = canvas.Canvas(final_pdf_buffer, pagesize=A4)
                        progress_bar = st.progress(0)
                        total_stu = len(students)
                        
                        batch_photos = {}
                        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                            futures = {executor.submit(download_photo_worker, (s['usn'], photo_file_map)): s['usn'] for s in students}
                            for future in concurrent.futures.as_completed(futures):
                                u, p_stream = future.result()
                                if p_stream: batch_photos[u] = p_stream

                        date_str = datetime.date.today().strftime('%d-%m-%Y')

                        for i, stu in enumerate(students):
                            s_br = str(stu['branch_code']).upper()
                            prog_type = branch_prog_map.get(s_br, "UG")
                            
                            raw_courses = branch_courses_dict.get(s_br, []) + branch_courses_dict.get("COMMON", [])
                            # 🟢 NEW: Sorted perfectly by the numeric 3-digit course number (201, 202, 203)
                            raw_courses = sorted(raw_courses, key=lambda x: course_sort_key(x['course_code']))
                            
                            seen = set()
                            dedup_courses = []
                            for crs in raw_courses:
                                if crs['course_code'] not in seen:
                                    seen.add(crs['course_code'])
                                    dedup_courses.append(crs)
                            
                            photo_stream = batch_photos.get(stu['usn'])
                            draw_registration_page(c, A4[0], A4[1], stu, dedup_courses, system_assets, photo_stream, f_title, f_sem, date_str, prog_type)
                            c.showPage() 
                            progress_bar.progress((i + 1) / total_stu)
                            
                        c.save()
                        for stream in batch_photos.values(): stream.close()
                                
                        st.success(f"✅ Generated {total_stu} pages into a single Master PDF!")
                        
                        dl_name = f"Batch_Registrations_ALL_Sem{f_sem}.pdf" if f_branch == "ALL BRANCHES" else f"Batch_Registrations_{f_branch}_Sem{f_sem}.pdf"
                        st.download_button(
                            label=f"📥 Download Master PDF",
                            data=final_pdf_buffer.getvalue(),
                            file_name=dl_name,
                            mime="application/pdf",
                            type="primary"
                        )
                except Exception as e:
                    st.error(f"Generation Error: {e}")

# ==========================================
# 2. BULK REGISTRATION (CSV)
# ==========================================
with reg_tabs[1]:
    st.header("Step 2.1: Bulk Course Mapping")
    
    col_b1, col_b2 = st.columns(2)
    
    with col_b1:
        st.subheader("A. Download Universal Template")
        st.info("Upload your syllabus CSV here. We will generate ONE massive template containing ALL students mapped to their respective subjects based on the 'Streams' column!")
        
        t_sem = st.number_input("Target Semester", min_value=1, max_value=10, value=1, key="t_sem_tmpl")
        t_ay = st.text_input("Academic Year", value=st.session_state.get('active_academic_year', '2025-26'), key="t_ay_tmpl")
        t_type = st.selectbox("Semester Type", ["ODD", "EVEN", "BOTH"], key="t_type_tmpl")
        t_csv = st.file_uploader("Upload Universal Syllabus (CSV)", type="csv", key="t_csv_tmpl")
        
        if st.button("📥 Generate Universal CSV Template", type="secondary"):
            if t_csv is None:
                st.error("Please upload your Course Syllabus CSV to map the subjects.")
            else:
                with st.spinner("Building universal template for all students..."):
                    stu_data = fetch_all_records("master_students", "usn, branch_code", {"current_sem": str(t_sem)})
                    
                    df_crs = pd.read_csv(t_csv)
                    col_map = {c.strip().upper(): c for c in df_crs.columns}
                    code_col = col_map.get('COURSE CODE', df_crs.columns[0])
                    stream_col = col_map.get('STREAMS', col_map.get('BRANCH', None))
                    
                    if not stream_col:
                        st.error("Your uploaded CSV must contain a 'Streams' or 'Branch' column!")
                    elif not stu_data:
                        st.warning(f"No students found in Semester {t_sem}.")
                    else:
                        branch_courses = {}
                        for _, r in df_crs.iterrows():
                            br = str(r[stream_col]).strip().upper()
                            cc = str(r[code_col]).strip()
                            if br not in branch_courses: branch_courses[br] = []
                            branch_courses[br].append(cc)
                            
                        template_rows = []
                        for s in stu_data:
                            s_branch = str(s['branch_code']).upper()
                            
                            my_courses = branch_courses.get(s_branch, []) + branch_courses.get("COMMON", []) + branch_courses.get("FIRST_YEAR", [])
                            # 🟢 NEW: Courses are sorted perfectly by their numeric values (201, 202, 203)
                            my_courses = sorted(list(set(my_courses)), key=course_sort_key)
                            
                            for c in my_courses:
                                template_rows.append({"usn": s['usn'], "course_code": c, "academic_year": t_ay, "semester_type": t_type, "semester": t_sem})
                        
                        if template_rows:
                            df_tmpl = pd.DataFrame(template_rows)
                            st.success(f"✅ Universal Template generated containing {len(stu_data)} students!")
                            st.download_button(label=f"📥 Download Universal Sem {t_sem} Template", data=df_tmpl.to_csv(index=False).encode('utf-8'), file_name=f"Universal_Registration_Template_Sem{t_sem}.csv", mime="text/csv", type="primary")
                        else:
                            st.error("Failed to map any subjects. Check if the branch codes in 'Streams' match the database.")

    with col_b2:
        st.subheader("B. Upload Finalized Registrations")
        st.markdown("⚠️ **Expected Columns:** `usn`, `course_code`, `academic_year`, `semester_type`, `semester`")
        f_reg = st.file_uploader("Upload Edited CSV", type='csv', key="reg_bulk_upload")
        
        if f_reg and st.button("🚀 Execute Bulk Registration", type="primary"):
            df = pd.read_csv(f_reg)
            data = clean_data_for_db(df, ['usn', 'course_code', 'academic_year', 'semester_type', 'semester'])
            
            if data:
                with st.spinner("Processing registrations..."):
                    try:
                        uploaded_usns = list(set([r['usn'] for r in data]))
                        for i in range(0, len(uploaded_usns), 100):
                            supabase.table("course_registrations").delete().eq("cycle_id", selected_cycle_id).in_("usn", uploaded_usns[i:i+100]).execute()
                        
                        for row in data: row['cycle_id'] = selected_cycle_id
                        for i in range(0, len(data), 500):
                            supabase.table("course_registrations").insert(data[i:i+500]).execute()
                            
                        st.success(f"✅ Successfully registered {len(data)} student-course mappings!")
                    except Exception as e: st.error(f"Registration failed: {e}")

# ==========================================
# 3. INTERACTIVE INDIVIDUAL MAPPING
# ==========================================
with reg_tabs[2]:
    st.header("Step 2.2: Interactive Individual Registration")
    st.info("Select a branch and student to dynamically load applicable courses based on the syllabus.")
    
    col1, col2 = st.columns(2)
    try:
        branches_data_int = fetch_all_records("master_branches", "branch_code")
        branch_list_int = [b['branch_code'] for b in branches_data_int if str(b['branch_code']).upper() != 'COMMON']
    except: branch_list_int = []
    
    selected_branch = col1.selectbox("1. Select Branch", ["-- Select --"] + branch_list_int, key="int_branch_select")
    
    if selected_branch != "-- Select --":
        students_data = fetch_all_records("master_students", "usn, full_name", {"branch_code": selected_branch})
        if not students_data: st.warning(f"No students found in {selected_branch}")
        else:
            student_options = {f"{s['usn']} - {s['full_name']}": s['usn'] for s in students_data}
            selected_student_label = col2.selectbox("2. Select Student", ["-- Select --"] + list(student_options.keys()))
            
            if selected_student_label != "-- Select --":
                selected_usn = student_options[selected_student_label]
                applicable_courses = [c for c in fetch_all_records("master_courses", "course_code, title, branch_code") if c['branch_code'] in [selected_branch, 'COMMON']]
                # 🟢 NEW: Sorted mathematically using numeric course sort
                applicable_courses = sorted(applicable_courses, key=lambda x: course_sort_key(x['course_code']))
                
                if not applicable_courses: st.warning("No courses mapped to this branch.")
                else:
                    st.markdown("### 3. Select Subjects to Register")
                    already_registered = [r['course_code'] for r in fetch_all_records("course_registrations", "course_code", {"cycle_id": selected_cycle_id, "usn": selected_usn})]
                    
                    with st.form("dynamic_registration_form"):
                        c1, c2 = st.columns(2)
                        r_ay = c1.text_input("Academic Year", value=st.session_state.get('active_academic_year', '2025-26'), key="int_ay")
                        r_sem_type = c2.selectbox("Semester Type", ["ODD", "EVEN", "BOTH"], key="int_type")
                        r_semester = c1.number_input("Semester (for these subjects)", min_value=1, max_value=10, value=1, key="int_sem")
                        st.divider()
                        
                        selected_course_codes = []
                        for course in applicable_courses:
                            if st.checkbox(f"{course['course_code']} - {course['title']}", value=(course['course_code'] in already_registered)):
                                selected_course_codes.append(course['course_code'])
                        
                        if st.form_submit_button("💾 Save Registrations", type="primary"):
                            with st.spinner("Updating records..."):
                                try:
                                    supabase.table("course_registrations").delete().match({"cycle_id": selected_cycle_id, "usn": selected_usn}).execute()
                                    if selected_course_codes:
                                        payload = [{"cycle_id": selected_cycle_id, "usn": selected_usn, "course_code": cc, "academic_year": r_ay, "semester_type": r_sem_type, "semester": r_semester} for cc in selected_course_codes]
                                        supabase.table("course_registrations").insert(payload).execute()
                                    st.success(f"✅ Successfully updated {len(selected_course_codes)} registrations for {selected_usn}!")
                                except Exception as e: st.error(f"Database Error: {e}")

# ==========================================
# 4. VIEW REGISTRATIONS
# ==========================================
with reg_tabs[3]:
    st.header(f"🔍 Current Course Mappings for {st.session_state.get('active_cycle_name')}")
    search_usn = st.text_input("Filter by USN (Optional)", key="view_usn")
    if st.button("Fetch Registration Data", key="view_btn"):
        query = supabase.table("course_registrations").select("*").eq("cycle_id", selected_cycle_id)
        if search_usn: query = query.eq("usn", search_usn.strip().upper())
        res = query.execute()
        if res.data: st.dataframe(pd.DataFrame(res.data), use_container_width=True)
        else: st.write("No records found.")

# ==========================================
# 5. PHOTO BACKUP UTILITY
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

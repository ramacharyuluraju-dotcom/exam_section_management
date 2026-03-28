import streamlit as st
import pandas as pd
import io
import concurrent.futures
from utils import init_db, clean_data_for_db

# --- REPORTLAB IMPORTS FOR EXACT PDF GENERATION ---
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm

# --- CONFIGURATION ---
# Note: st.set_page_config removed because app.py handles it
supabase = init_db()

st.title("📝 Semester Course Registration")
st.sidebar.markdown("### Operational Phase")

# --- GLOBAL CONTEXT ---
selected_cycle_id = st.session_state.get('active_cycle_id')

if not selected_cycle_id:
    st.warning("⚠️ Please select an Active Exam Cycle in the Sidebar to proceed.")
    st.stop()

st.info(f"🔵 Currently Registering Students for Cycle: **{st.session_state.get('active_cycle_name')}**")

# --- HELPER FUNCTIONS ---
@st.cache_data(ttl=3600)
def fetch_student_photo_bytes(usn):
    """Securely fetches raw photo bytes from Supabase for native PDF embedding."""
    clean_usn = str(usn).strip().upper()
    for ext in ['.jpg', '.jpeg', '.png', '.webp', '.JPG', '.PNG']:
        try:
            res = supabase.storage.from_("StakeHolders_Photos").download(f"{clean_usn}{ext}")
            if res:
                return res
        except Exception:
            continue
    return None

# ==========================================
# NAVIGATION TABS
# ==========================================
reg_tabs = st.tabs(["📤 Bulk Registration", "📝 Manual Mapping", "🔍 View Registrations", "📄 Generate PG Forms (PDF)"])

# ==========================================
# 1. BULK REGISTRATION (CSV)
# ==========================================
with reg_tabs[0]:
    st.header("Step 2.1: Bulk Course Mapping")
    f_reg = st.file_uploader("Upload Registration CSV", type='csv', key="reg_bulk")
    if f_reg and st.button("Execute Bulk Registration"):
        df = pd.read_csv(f_reg)
        expected = ['usn', 'course_code', 'academic_year', 'semester_type']
        data = clean_data_for_db(df, expected)
        for row in data: row['cycle_id'] = selected_cycle_id
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
        r_sem = col2.selectbox("Semester Type", ["ODD", "EVEN"])
        c1, c2 = st.columns(2)
        if c1.form_submit_button("💾 Register Course"):
            reg_data = {"cycle_id": selected_cycle_id, "usn": r_usn.strip().upper(), "course_code": r_course.strip().upper(), "academic_year": r_ay, "semester_type": r_sem}
            try: supabase.table("course_registrations").upsert(reg_data).execute(); st.success(f"✅ Registered {r_course} for {r_usn}")
            except Exception as e: st.error(f"Error: {e}")
        if c2.form_submit_button("🗑️ Remove Registration"):
            try: supabase.table("course_registrations").delete().match({"cycle_id": selected_cycle_id, "usn": r_usn.strip().upper(), "course_code": r_course.strip().upper()}).execute(); st.warning(f"Removed registration.")
            except Exception as e: st.error(f"Error: {e}")

# ==========================================
# 3. VIEW REGISTRATIONS
# ==========================================
with reg_tabs[2]:
    st.header(f"🔍 Current Course Mappings for {st.session_state.get('active_cycle_name')}")
    search_usn = st.text_input("Filter by USN (Optional)")
    if st.button("Fetch Registration Data"):
        query = supabase.table("course_registrations").select("*").eq("cycle_id", selected_cycle_id)
        if search_usn: query = query.eq("usn", search_usn.strip().upper())
        res = query.execute()
        if res.data: st.dataframe(pd.DataFrame(res.data), use_container_width=True); st.write(f"Total Records: {len(res.data)}")
        else: st.write("No registration records found.")

# ==========================================
# 4. GENERATE PG FORMS (EXACT PDF REPLICA)
# ==========================================
with reg_tabs[3]:
    st.header("📄 Generate Print-Ready PG Registration Forms (PDF)")
    st.info("This tool generates an exact PDF replica of the official format. It uses your uploaded Student/Course lists and securely fetches photos from Supabase.")
    
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

    if f_students and f_courses and st.button("⚡ Generate PDF Forms", type="primary"):
        with st.spinner("Downloading photos concurrently and compiling precise PDF layouts..."):
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

                # 🟢 MULTI-THREADED PHOTO FETCHING (Raw Bytes for PDF) 🟢
                unique_usns = list(set(df_s['usn'].astype(str).str.strip().str.upper()))
                photo_cache = {}
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                    future_to_usn = {executor.submit(fetch_student_photo_bytes, usn): usn for usn in unique_usns}
                    for future in concurrent.futures.as_completed(future_to_usn):
                        usn = future_to_usn[future]
                        try: photo_cache[usn] = future.result()
                        except: photo_cache[usn] = None

                # 🟢 REPORTLAB PDF CONSTRUCTION 🟢
                pdf_buffer = io.BytesIO()
                doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
                elements = []
                styles = getSampleStyleSheet()
                
                # Exact Font Styles
                style_center = ParagraphStyle('Center', parent=styles['Normal'], alignment=1, fontName='Times-Bold', fontSize=15, spaceAfter=2)
                style_sub_center = ParagraphStyle('SubCenter', parent=styles['Normal'], alignment=1, fontName='Times-Roman', fontSize=11, spaceAfter=2)
                style_title = ParagraphStyle('Title', parent=styles['Normal'], alignment=1, fontName='Times-Bold', fontSize=13, spaceAfter=15)
                style_normal = ParagraphStyle('Normal_Times', parent=styles['Normal'], fontName='Times-Roman', fontSize=11)
                style_bold = ParagraphStyle('Bold_Times', parent=styles['Normal'], fontName='Times-Bold', fontSize=11)

                generated_count = 0

                for _, student in df_s.iterrows():
                    branch = str(student.get('branch', '')).strip().upper()
                    usn = str(student.get('usn', '')).strip().upper()
                    name = str(student.get('name', '')).strip().title()
                    
                    courses = branch_courses.get(branch, [])
                    
                    if courses:
                        generated_count += 1
                        
                        # 1. Header block
                        elements.append(Paragraph("AMC ENGINEERING COLLEGE", style_center))
                        elements.append(Paragraph("Autonomous Institution affiliated to VTU, Belagavi.", style_sub_center))
                        elements.append(Paragraph("Bannerghatta Road, Bengaluru - 560083.", style_sub_center))
                        elements.append(Spacer(1, 10))
                        elements.append(Paragraph("<u>COURSE REGISTRATION FORM - PG PROGRAM</u>", style_title))
                        
                        # 2. Student Info & Photo Layout
                        info_data = [
                            [Paragraph("<b>Academic Year:</b>", style_normal), Paragraph(academic_year, style_normal)],
                            [Paragraph("<b>Semester:</b>", style_normal), Paragraph(str(target_sem), style_normal)],
                            [Paragraph("<b>USN:</b>", style_normal), Paragraph(usn, style_bold)],
                            [Paragraph("<b>Name:</b>", style_normal), Paragraph(name, style_bold)],
                            [Paragraph("<b>Programme:</b>", style_normal), Paragraph("PG", style_normal)],
                            [Paragraph("<b>Branch:</b>", style_normal), Paragraph(branch, style_normal)]
                        ]
                        
                        info_table = Table(info_data, colWidths=[90, 250])
                        info_table.setStyle(TableStyle([
                            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
                            ('TOPPADDING', (0,0), (-1,-1), 3),
                        ]))
                        
                        photo_bytes = photo_cache.get(usn)
                        if photo_bytes:
                            img = Image(io.BytesIO(photo_bytes), width=1.1*inch, height=1.4*inch)
                        else:
                            img = Table([["Affix\nPassport\nSize Photo"]], colWidths=[1.1*inch], rowHeights=[1.4*inch])
                            img.setStyle(TableStyle([
                                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                                ('GRID', (0,0), (-1,-1), 1, colors.black),
                                ('FONTNAME', (0,0), (-1,-1), 'Times-Roman'),
                                ('FONTSIZE', (0,0), (-1,-1), 9)
                            ]))
                            
                        top_layout = Table([[info_table, img]], colWidths=[380, 110])
                        top_layout.setStyle(TableStyle([
                            ('ALIGN', (0,0), (0,0), 'LEFT'),
                            ('ALIGN', (1,0), (1,0), 'RIGHT'),
                            ('VALIGN', (0,0), (-1,-1), 'TOP'),
                        ]))
                        
                        elements.append(top_layout)
                        elements.append(Spacer(1, 15))
                        
                        # 3. Course Table
                        course_data = [['Sl. No.', 'Course Code', 'Course Title', 'Credit']]
                        total_credits = 0
                        
                        for idx, crs in enumerate(courses, 1):
                            ccode = str(crs.get('course_code', '')).upper()
                            ctitle = str(crs.get('course_title', '')).title()
                            try:
                                cred = float(crs.get('credits', 0))
                                if cred.is_integer(): cred = int(cred)
                                total_credits += cred
                            except: cred = crs.get('credits', '')
                            
                            course_data.append([str(idx), ccode, ctitle, str(cred)])
                            
                        # Add Total Credits Row
                        course_data.append(['', '', 'Total Credits:', str(total_credits)])
                        
                        course_table = Table(course_data, colWidths=[40, 90, 310, 60])
                        course_table.setStyle(TableStyle([
                            ('GRID', (0,0), (-1,-2), 0.5, colors.black), # Grid for all but last row
                            ('GRID', (2,-1), (-1,-1), 0.5, colors.black), # Grid for total credits section
                            ('ALIGN', (0,0), (-1,0), 'CENTER'), # Header center
                            ('ALIGN', (0,1), (0,-2), 'CENTER'), # Sl no center
                            ('ALIGN', (1,1), (1,-2), 'CENTER'), # Code center
                            ('ALIGN', (2,1), (2,-2), 'LEFT'),   # Title left
                            ('ALIGN', (3,1), (3,-1), 'CENTER'), # Credit center
                            ('ALIGN', (2,-1), (2,-1), 'RIGHT'), # Total credits text right
                            ('FONTNAME', (0,0), (-1,0), 'Times-Bold'),
                            ('FONTNAME', (0,1), (-1,-2), 'Times-Roman'),
                            ('FONTNAME', (2,-1), (-1,-1), 'Times-Bold'),
                            ('FONTSIZE', (0,0), (-1,-1), 10),
                            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                            ('TOPPADDING', (0,0), (-1,-1), 6),
                        ]))
                        
                        elements.append(course_table)
                        elements.append(Spacer(1, 80)) # Space for signatures
                        
                        # 4. Signature Blocks
                        sig_data = [
                            ["___________________", "___________________", "___________________", "___________________"],
                            ["Student Signature", "Signature of\nFaculty Advisor", "Signature of\nHOD", "Signature of\nPrincipal"]
                        ]
                        sig_table = Table(sig_data, colWidths=[125, 125, 125, 125])
                        sig_table.setStyle(TableStyle([
                            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                            ('VALIGN', (0,0), (-1,-1), 'TOP'),
                            ('FONTNAME', (0,0), (-1,-1), 'Times-Bold'),
                            ('FONTSIZE', (0,0), (-1,-1), 10),
                            ('BOTTOMPADDING', (0,0), (-1,0), 2),
                        ]))
                        
                        elements.append(sig_table)
                        elements.append(PageBreak())

                # Build PDF
                doc.build(elements)

                if generated_count > 0:
                    st.success(f"🎉 Successfully generated A4 PDF Registration Forms for {generated_count} PG students!")
                    st.download_button(
                        label="📥 Download Master PDF",
                        data=pdf_buffer.getvalue(),
                        file_name=f"PG_Sem{target_sem}_Registration_Forms.pdf",
                        mime="application/pdf",
                        type="primary"
                    )
                else:
                    st.warning("No students matched the branches found in your Courses CSV.")
                    
            except Exception as e:
                st.error(f"Processing error: {e}")

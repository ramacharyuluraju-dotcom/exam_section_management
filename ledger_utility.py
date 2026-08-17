import streamlit as st
import pandas as pd
import io
import datetime

# --- PDF LIBRARIES ---
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

from utils import init_db

# --- CONFIGURATION ---
supabase = init_db()

st.title("🖨️ Central Document & Ledger Hub")
st.info("🏛️ **Historical Read-Only Mode:** You can generate ledgers, marks cards, and hall tickets for ANY cycle here, including archived/closed cycles. Make-up marks are automatically resolved.")

# ==========================================
# 1. HISTORICAL CYCLE SELECTOR
# ==========================================
st.markdown("### 1️⃣ Select Academic Context")

@st.cache_data(ttl=60)
def get_all_cycles():
    res = supabase.table("exam_cycles").select("cycle_id, cycle_name, academic_year, is_active").order("created_at", desc=True).execute()
    return res.data

all_cycles = get_all_cycles()
if not all_cycles:
    st.error("No exam cycles found in the database.")
    st.stop()

# Group by Academic Year for a clean UI
ay_list = sorted(list(set([c['academic_year'] for c in all_cycles if c.get('academic_year')])), reverse=True)
col1, col2 = st.columns(2)
selected_ay = col1.selectbox("Filter by Academic Year", ay_list)

filtered_cycles = [c for c in all_cycles if c['academic_year'] == selected_ay]
cycle_options = {f"{c['cycle_name']} ({'ACTIVE' if c['is_active'] else 'CLOSED'})": c['cycle_id'] for c in filtered_cycles}

selected_cycle_name = col2.selectbox("Select Target Exam Cycle", list(cycle_options.keys()))
target_cycle_id = cycle_options[selected_cycle_name]

st.divider()

# ==========================================
# 2. CORE DATA FETCHER (WITH MAKE-UP LOGIC)
# ==========================================
def fetch_resolved_results(parent_cycle_id):
    """
    Fetches results for the parent cycle AND any linked child (Make-up) cycles.
    It returns a resolved Pandas DataFrame where Make-up grades have replaced 'I' or 'X' grades.
    """
    # 1. Fetch Parent Results
    parent_res = supabase.table("student_results").select("*").eq("cycle_id", parent_cycle_id).execute()
    if not parent_res.data:
        return pd.DataFrame()
    
    df_parent = pd.DataFrame(parent_res.data)
    
    # 2. Check for Linked Child Cycles (Make-ups / Supplementary)
    child_cycles = supabase.table("exam_cycles").select("cycle_id").eq("parent_cycle_id", parent_cycle_id).execute()
    
    if child_cycles.data:
        child_ids = [c['cycle_id'] for c in child_cycles.data]
        
        # 3. Fetch Child Results
        # Using a loop to safely fetch if there are many records
        child_data = []
        for c_id in child_ids:
            c_res = supabase.table("student_results").select("*").eq("cycle_id", c_id).execute()
            if c_res.data:
                child_data.extend(c_res.data)
                
        if child_data:
            df_child = pd.DataFrame(child_data)
            
            # 4. 🟢 THE MAGIC MERGE (Pandas equivalent of COALESCE)
            # We set the index to USN + Course Code so we can easily update matching rows
            df_parent.set_index(['usn', 'course_code'], inplace=True)
            df_child.set_index(['usn', 'course_code'], inplace=True)
            
            # Update the parent dataframe with child records that actually have a grade
            valid_child_updates = df_child[~df_child['grade'].isin(['PND', 'PENDING', 'FROZEN', '', None])]
            df_parent.update(valid_child_updates)
            
            df_parent.reset_index(inplace=True)
            
    return df_parent

# ==========================================
# 3. TABBED UI FOR GENERATORS
# ==========================================
t1, t2, t3 = st.tabs(["📊 Consolidated Ledgers", "🪪 Semester Marks Cards", "🎟️ Hall Tickets"])

# ------------------------------------------------------------------
# TAB 1: CONSOLIDATED LEDGERS (EXCEL)
# ------------------------------------------------------------------
with t1:
    st.subheader("Generate Master Tabulation Ledger")
    st.write("Generates a comprehensive Excel sheet detailing every student's performance across all subjects in the selected cycle. Automatically includes Make-up upgrades.")
    
    l_col1, l_col2 = st.columns(2)
    l_prog = l_col1.selectbox("Program Type", ["UG", "PG"], key="ledger_prog")
    
    # Fetch branches dynamically based on program
    all_branches = supabase.table("master_branches").select("branch_code, program_type").execute().data
    valid_branches = [b['branch_code'] for b in all_branches if b.get('program_type') == l_prog]
    
    l_branch = l_col2.selectbox("Select Branch", ["ALL BRANCHES"] + valid_branches, key="ledger_branch")
    
    if st.button("📥 Generate Excel Ledger", type="primary"):
        with st.spinner("Compiling results and resolving Make-up exam upgrades..."):
            df_results = fetch_resolved_results(target_cycle_id)
            
            if df_results.empty:
                st.error("No results found for this cycle.")
            else:
                # Fetch Students to filter by Branch
                stu_res = supabase.table("master_students").select("usn, full_name, branch_code").execute()
                df_stu = pd.DataFrame(stu_res.data)
                
                if l_branch != "ALL BRANCHES":
                    df_stu = df_stu[df_stu['branch_code'] == l_branch]
                    
                # Merge Student Info into Results
                df_merged = pd.merge(df_results, df_stu, on="usn", how="inner")
                
                if df_merged.empty:
                    st.warning(f"No results found for {l_branch} in this cycle.")
                else:
                    # Clean up the dataframe for Excel presentation
                    display_cols = [
                        'usn', 'full_name', 'branch_code', 'course_code', 
                        'cie_marks', 'see_raw', 'total_marks', 'grade', 'is_pass'
                    ]
                    
                    # Ensure columns exist before filtering
                    available_cols = [c for c in display_cols if c in df_merged.columns]
                    df_ledger = df_merged[available_cols].copy()
                    
                    df_ledger.rename(columns={
                        'usn': 'USN', 'full_name': 'Student Name', 'branch_code': 'Branch',
                        'course_code': 'Course Code', 'cie_marks': 'CIE', 'see_raw': 'SEE (Raw)',
                        'total_marks': 'Total Marks', 'grade': 'Final Grade', 'is_pass': 'Passed?'
                    }, inplace=True)
                    
                    # Sort logically
                    df_ledger = df_ledger.sort_values(by=['Branch', 'USN', 'Course Code'])
                    
                    # Generate Excel File in memory
                    excel_buffer = io.BytesIO()
                    with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                        df_ledger.to_excel(writer, sheet_name='Consolidated_Ledger', index=False)
                        
                        # Auto-adjust column widths
                        worksheet = writer.sheets['Consolidated_Ledger']
                        for i, col in enumerate(df_ledger.columns):
                            max_len = max(df_ledger[col].astype(str).map(len).max(), len(col)) + 2
                            worksheet.set_column(i, i, max_len)

                    st.success("✅ Ledger compiled successfully!")
                    st.download_button(
                        label="💾 Download Excel Ledger",
                        data=excel_buffer.getvalue(),
                        file_name=f"Consolidated_Ledger_{selected_cycle_name.split(' ')[0]}_{l_branch}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )

# ------------------------------------------------------------------
# TAB 2: MARKS CARDS (PDF)
# ------------------------------------------------------------------
with t2:
    st.subheader("Generate Official Semester Marks Cards")
    st.write("Generates individual PDF grade cards for students. Resolves all transitional grades based on connected Make-up cycles.")
    
    m_col1, m_col2 = st.columns(2)
    m_usn_input = m_col1.text_input("Enter specific USN (Leave blank for whole branch)")
    m_branch = m_col2.selectbox("Select Branch (If USN is blank)", valid_branches, key="marks_branch")
    
    if st.button("🖨️ Generate PDF Marks Cards", type="primary"):
        with st.spinner("Rendering PDFs..."):
            df_results = fetch_resolved_results(target_cycle_id)
            
            if df_results.empty:
                st.error("No results found for this cycle.")
            else:
                # Apply filters
                if m_usn_input:
                    df_results = df_results[df_results['usn'] == m_usn_input.strip().upper()]
                else:
                    stu_res = supabase.table("master_students").select("usn").eq("branch_code", m_branch).execute()
                    branch_usns = [s['usn'] for s in stu_res.data]
                    df_results = df_results[df_results['usn'].isin(branch_usns)]
                
                if df_results.empty:
                    st.warning("No data matches your filter criteria.")
                else:
                    # Fetch extra details for the PDF
                    course_res = supabase.table("master_courses").select("course_code, title, credits").execute()
                    course_map = {c['course_code']: c for c in course_res.data}
                    
                    student_usns = df_results['usn'].unique().tolist()
                    stu_res = supabase.table("master_students").select("*").in_("usn", student_usns).execute()
                    stu_map = {s['usn']: s for s in stu_res.data}
                    
                    # Try to load logos
                    left_logo, right_logo = "", ""
                    try:
                        res_l = supabase.storage.from_("College_Logos").download("College_logo.png")
                        if res_l: left_logo = Image(io.BytesIO(res_l), width=0.8*inch, height=0.8*inch)
                        res_r = supabase.storage.from_("College_Logos").download("NAAC_A_Logo.jpg")
                        if res_r: right_logo = Image(io.BytesIO(res_r), width=0.8*inch, height=0.8*inch)
                    except: pass

                    # BUILD THE PDF
                    pdf_buffer = io.BytesIO()
                    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, topMargin=40, bottomMargin=40, leftMargin=40, rightMargin=40)
                    elements = []
                    styles = getSampleStyleSheet()
                    
                    title_style = ParagraphStyle('Title', parent=styles['Heading2'], alignment=1, fontName='Helvetica-Bold')
                    normal_bold = ParagraphStyle('NB', parent=styles['Normal'], fontName='Helvetica-Bold')
                    center_text = ParagraphStyle('CT', parent=styles['Normal'], alignment=1)
                    
                    grouped = df_results.groupby('usn')
                    
                    for usn, group in grouped:
                        student = stu_map.get(usn, {})
                        stu_name = student.get('full_name', 'Unknown')
                        branch_name = student.get('branch_code', 'Unknown Branch')
                        
                        # --- Header ---
                        header_text = """<center>
                            <font size="14"><b>AMC ENGINEERING COLLEGE</b></font><br/>
                            <font size="9">Autonomous Institution Affiliated to VTU, Belagavi | NAAC A+ Accredited</font><br/>
                            <font size="10"><b>SEMESTER END EXAMINATION GRADE CARD</b></font>
                        </center>"""
                        
                        t_header = Table([[left_logo, Paragraph(header_text, styles['Normal']), right_logo]], colWidths=[1*inch, 4.5*inch, 1*inch])
                        t_header.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (0,0), (0,0), 'LEFT'), ('ALIGN', (2,0), (2,0), 'RIGHT')]))
                        elements.append(t_header)
                        elements.append(Spacer(1, 15))
                        
                        # --- Student Info ---
                        info_data = [
                            [Paragraph("<b>USN:</b>", normal_bold), usn, Paragraph("<b>Date:</b>", normal_bold), datetime.datetime.now().strftime("%d-%m-%Y")],
                            [Paragraph("<b>Name:</b>", normal_bold), stu_name, Paragraph("<b>Branch:</b>", normal_bold), branch_name]
                        ]
                        t_info = Table(info_data, colWidths=[0.8*inch, 3*inch, 0.8*inch, 2*inch])
                        t_info.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('PADDING', (0,0), (-1,-1), 6), ('BACKGROUND', (0,0), (0,-1), colors.whitesmoke), ('BACKGROUND', (2,0), (2,-1), colors.whitesmoke)]))
                        elements.append(t_info)
                        elements.append(Spacer(1, 20))
                        
                        # --- Marks Table ---
                        marks_data = [[
                            Paragraph("<b>Course Code</b>", center_text), Paragraph("<b>Course Title</b>", center_text), 
                            Paragraph("<b>Credits</b>", center_text), Paragraph("<b>Grade</b>", center_text)
                        ]]
                        
                        total_credits = 0
                        total_points = 0
                        
                        for _, row in group.iterrows():
                            c_code = row['course_code']
                            c_data = course_map.get(c_code, {})
                            credits = float(c_data.get('credits', 0))
                            grade = row.get('grade', 'F')
                            
                            # Simple SGPA math for demo
                            gp_map = {'O': 10, 'A+': 9, 'A': 8, 'B+': 7, 'B': 6, 'C': 5, 'P': 4, 'F': 0, 'AB': 0}
                            gp = gp_map.get(grade, 0)
                            
                            if grade not in ['F', 'AB', 'I', 'W', 'X', 'PND']:
                                total_credits += credits
                                total_points += (credits * gp)
                                
                            marks_data.append([
                                Paragraph(c_code, center_text), 
                                Paragraph(c_data.get('title', 'Unknown'), styles['Normal']),
                                Paragraph(str(credits), center_text),
                                Paragraph(f"<b>{grade}</b>", center_text)
                            ])
                            
                        t_marks = Table(marks_data, colWidths=[1.2*inch, 3.5*inch, 0.8*inch, 1*inch])
                        t_marks.setStyle(TableStyle([
                            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                            ('PADDING', (0,0), (-1,-1), 6)
                        ]))
                        elements.append(t_marks)
                        elements.append(Spacer(1, 15))
                        
                        # --- SGPA Footer ---
                        sgpa = (total_points / total_credits) if total_credits > 0 else 0
                        sgpa_text = f"<b>Semester Grade Point Average (SGPA):</b> {sgpa:.2f}"
                        elements.append(Paragraph(sgpa_text, styles['Normal']))
                        elements.append(Spacer(1, 40))
                        
                        # --- Signatures ---
                        sig_data = [["_______________________", "_______________________"], ["Controller of Examinations", "Principal"]]
                        t_sig = Table(sig_data, colWidths=[3.2*inch, 3.2*inch])
                        t_sig.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
                        elements.append(t_sig)
                        
                        elements.append(PageBreak())
                        
                    doc.build(elements)
                    
                    st.success("✅ PDF Marks Cards Generated!")
                    filename = f"Marks_Cards_{m_usn_input}.pdf" if m_usn_input else f"Batch_Marks_Cards_{m_branch}.pdf"
                    st.download_button(label="📥 Download PDF Marks Cards", data=pdf_buffer.getvalue(), file_name=filename, mime="application/pdf", type="primary")

# ------------------------------------------------------------------
# TAB 3: HALL TICKETS
# ------------------------------------------------------------------
with t3:
    st.subheader("Admit Cards / Hall Tickets")
    st.info("Since Hall Tickets are generated *before* exams occur, this tool fetches registered subjects directly from the Timetable mapping.")
    st.write("*(Coming Soon - Awaiting final confirmation on Barcode vs QR code format for the AMC Admit Cards)*")

import streamlit as st
import pandas as pd
import io
import datetime
import math
import zipfile
import string
import random
from itertools import zip_longest
from utils import init_db
from PIL import Image as PILImage

# --- PDF LIBRARIES ---
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.utils import ImageReader

# --- EXCEL UTILS ---
from xlsxwriter.utility import xl_rowcol_to_cell

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
LOGO_FILENAME = "College_logo.png"
NAAC_FILENAME = "NAAC_A_Logo.jpg"
supabase = init_db()

# --- GLOBAL CONTEXT ---
selected_cycle_id = st.session_state.get('active_cycle_id')
active_cycle_name = st.session_state.get('active_cycle_name', 'Unknown Cycle')

@st.cache_data
def load_pdf_assets():
    """Fetches logos once to prevent slowing down PDF generation"""
    assets = {}
    for k, f in [("logo", LOGO_FILENAME), ("naac", NAAC_FILENAME)]:
        try:
            res = supabase.storage.from_("College_Logos").download(f)
            if res: assets[k] = res
        except: pass
    return assets

def resize_image_for_excel(img_bytes, target_height=50):
    """Physically resizes the image to a fixed height before giving it to Excel."""
    try:
        with PILImage.open(io.BytesIO(img_bytes)) as img:
            w_percent = (target_height / float(img.size[1]))
            target_width = int(float(img.size[0]) * float(w_percent))
            
            # Resize and convert to RGBA to ensure PNG compatibility
            resized_img = img.resize((target_width, target_height), PILImage.LANCZOS)
            if resized_img.mode != 'RGBA':
                resized_img = resized_img.convert('RGBA')
                
            out_io = io.BytesIO()
            resized_img.save(out_io, format='PNG')
            out_io.seek(0)
            return out_io
    except Exception as e:
        return io.BytesIO(img_bytes) # Fallback

def generate_dummy_ids(count):
    """Generates a sequential series of IDs per bundle (e.g., AB1 to AB20)."""
    prefix = "".join(random.choices(string.ascii_uppercase, k=2))
    return [f"{prefix}{i+1}" for i in range(count)]

def clean_str(val):
    return str(val).strip().upper() if pd.notna(val) else ""

# ==========================================
# 2. DATA FETCHING
# ==========================================

def fetch_exam_sessions(cycle_id):
    if not cycle_id: return []
    res = supabase.table("exam_timetable").select("exam_date, session").eq("cycle_id", cycle_id).execute()
    df = pd.DataFrame(res.data)
    if df.empty: return []
    df['label'] = df['exam_date'] + " | " + df['session']
    return df.sort_values('exam_date')['label'].unique().tolist()

def fetch_exam_data(cycle_id, date_str, session_str):
    tt_res = supabase.table("exam_timetable").select("course_code").eq("cycle_id", cycle_id).eq("exam_date", date_str).eq("session", session_str).execute()
    course_codes = [r['course_code'] for r in tt_res.data]
    if not course_codes: return pd.DataFrame()
    
    start = 0; limit = 1000; all_regs = []
    while True:
        res = supabase.table("course_registrations").select("usn, course_code").eq("cycle_id", cycle_id).in_("course_code", course_codes).range(start, start + limit - 1).execute()
        if not res.data: break
        all_regs.extend(res.data)
        if len(res.data) < limit: break
        start += limit
        
    if not all_regs: return pd.DataFrame()
    df_regs = pd.DataFrame(all_regs)
    
    usns = df_regs['usn'].unique().tolist()
    start = 0; all_stus = []
    while True:
        res = supabase.table("master_students").select("usn, full_name, branch_code").in_("usn", usns).range(start, start + limit - 1).execute()
        if not res.data: break
        all_stus.extend(res.data)
        if len(res.data) < limit: break
        start += limit
        
    df_stus = pd.DataFrame(all_stus)
    df_stus['Branch'] = df_stus['branch_code']
    
    df_merged = pd.merge(df_regs, df_stus, on='usn', how='left')
    df_merged.rename(columns={'usn': 'USN', 'full_name': 'Student Name', 'course_code': 'Subject Code'}, inplace=True)
    
    courses_res = supabase.table("master_courses").select("course_code, title").in_("course_code", course_codes).execute()
    course_dict = {r['course_code']: r['title'] for r in courses_res.data}
    df_merged['Subject Name'] = df_merged['Subject Code'].map(lambda x: course_dict.get(x, x))
    
    return df_merged

def fetch_rooms():
    res = supabase.table("master_rooms").select("*").order("priority_order").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

# ==========================================
# 3. ALLOCATION ENGINE (Anti-Fragmentation)
# ==========================================

def run_allocation(df_students, df_rooms):
    branches = df_students['Branch'].unique()
    branch_queues = {b: df_students[df_students['Branch'] == b].sort_values('USN').to_dict('records') for b in branches}
    
    def get_candidate(exclude_list, needed_space, diff_code=None):
        cands = [b for b in branch_queues if len(branch_queues[b]) > 0 and b not in exclude_list]
        if not cands: return None
        
        if diff_code:
            diff_cands = [b for b in cands if branch_queues[b][0]['Subject Code'] != diff_code]
            if diff_cands: cands = diff_cands
            
        good_cands = [b for b in cands if not (len(branch_queues[b]) <= 20 and len(branch_queues[b]) > needed_space)]
        
        if good_cands: return max(good_cands, key=lambda x: len(branch_queues[x]))
        else: return None

    allotment_rows = []
    
    for _, room in df_rooms.iterrows():
        room_no = room['room_no']
        capacity = int(room['capacity'])
        half_cap = capacity // 2
        
        if all(len(q) == 0 for q in branch_queues.values()): break

        pile_1 = []
        while len(pile_1) < half_cap:
            needed = half_cap - len(pile_1)
            curr_left = get_candidate(exclude_list=[], needed_space=needed)
            if not curr_left: break 
            take = min(needed, len(branch_queues[curr_left]))
            pile_1.extend(branch_queues[curr_left][:take])
            del branch_queues[curr_left][:take]

        pile_2 = []
        left_code = pile_1[0]['Subject Code'] if pile_1 else None
        
        while len(pile_2) < (capacity - len(pile_1)):
            needed = (capacity - len(pile_1)) - len(pile_2)
            curr_right = get_candidate(exclude_list=[], needed_space=needed, diff_code=left_code)
            if not curr_right: break 
            take = min(needed, len(branch_queues[curr_right]))
            pile_2.extend(branch_queues[curr_right][:take])
            del branch_queues[curr_right][:take]

        room_students = []
        for s1, s2 in zip_longest(pile_1, pile_2):
            if s1: room_students.append(s1)
            if s2: room_students.append(s2)

        for idx, s in enumerate(room_students):
            allotment_rows.append({
                'RoomNo': room_no, 'SeatNo': idx+1, 
                'USN': s['USN'], 'Student Name': s['Student Name'], 
                'Branch': s['Branch'], 'Subject Code': s['Subject Code'], 
                'Subject Name': s['Subject Name']
            })

    return pd.DataFrame(allotment_rows)

# ==========================================
# 4. DOCUMENT GENERATORS
# ==========================================

def get_header_drawer(assets):
    """Dynamically injects the official College Logos and Header Text into every PDF page"""
    def draw_header(c, doc):
        c.saveState()
        y_start = A4[1] - 35
        
        if "logo" in assets:
            c.drawImage(ImageReader(io.BytesIO(assets["logo"])), 35, y_start - 35, width=50, height=50, mask='auto', preserveAspectRatio=True)
            
        if "naac" in assets:
            c.drawImage(ImageReader(io.BytesIO(assets["naac"])), A4[0] - 85, y_start - 35, width=50, height=50, mask='auto', preserveAspectRatio=True)

        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(A4[0]/2, y_start, "AMC ENGINEERING COLLEGE")
        c.setFont("Helvetica", 9)
        c.drawCentredString(A4[0]/2, y_start - 15, "AMC Campus, Bannerghatta Road, Bengaluru - 560083")
        c.drawCentredString(A4[0]/2, y_start - 27, "Autonomous Institution Affiliated to VTU, Belagavi")
        c.drawCentredString(A4[0]/2, y_start - 39, "Approved by AICTE, New Delhi | NAAC A+ Accredited")
        
        c.setLineWidth(1)
        c.line(30, y_start - 48, A4[0] - 30, y_start - 48)
        c.restoreState()
    return draw_header

def gen_posters(df, date, session, assets):
    buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=95, bottomMargin=15)
    elements = []; styles = getSampleStyleSheet()
    s_seat = ParagraphStyle('S', parent=styles['Normal'], fontSize=8, alignment=TA_CENTER, textColor=colors.gray)
    s_usn = ParagraphStyle('U', parent=styles['Normal'], fontSize=11, fontName='Helvetica-Bold', alignment=TA_CENTER)
    s_sub = ParagraphStyle('Sub', parent=styles['Normal'], fontSize=7, alignment=TA_CENTER)
    
    for room_no, data in df.groupby('RoomNo'):
        elements.append(Paragraph(f"ROOM: {room_no} | Date: {date} | Session: {session}", styles['Heading2']))
        elements.append(Spacer(1, 5))
        
        students = data.sort_values('SeatNo').to_dict('records')
        grid = []; row_buf = []
        for s in students:
            row_buf.append([Paragraph(f"Seat: {s['SeatNo']}", s_seat), Spacer(1,1), Paragraph(s['USN'], s_usn), Spacer(1,1), Paragraph(s['Subject Code'], s_sub)])
            if len(row_buf) == 4: grid.append(row_buf); row_buf = []
        if row_buf:
            while len(row_buf) < 4: row_buf.append("")
            grid.append(row_buf)
            
        t = Table(grid, colWidths=[1.8*inch]*4)
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (0,0), (-1,-1), 'CENTER')]))
        elements.append(t); elements.append(PageBreak())
        
    doc.build(elements, onFirstPage=get_header_drawer(assets), onLaterPages=get_header_drawer(assets))
    return buf.getvalue()

def gen_form_b(df, date, session, assets):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=90, leftMargin=35, rightMargin=35, bottomMargin=15)
    elements = []
    styles = getSampleStyleSheet()
    
    sub_title_style = ParagraphStyle('SubTitle', parent=styles['Normal'], alignment=TA_CENTER, fontName='Helvetica-Bold', fontSize=10)
    meta_style = ParagraphStyle('Meta', parent=styles['Normal'], fontSize=9, leading=12)
    th_style = ParagraphStyle('th', parent=styles['Normal'], alignment=TA_CENTER, fontName='Helvetica-Bold', fontSize=8)
    td_style_c = ParagraphStyle('td_c', parent=styles['Normal'], alignment=TA_CENTER, fontSize=9)
    td_style_l = ParagraphStyle('td_l', parent=styles['Normal'], alignment=TA_LEFT, fontSize=8)
    
    for (room, code), group in df.groupby(['RoomNo', 'Subject Code']):
        course_name = group['Subject Name'].iloc[0] if 'Subject Name' in group.columns else code
        branch_val = group['Branch'].iloc[0] if 'Branch' in group.columns else "N/A"
        
        elements.append(Spacer(1, 5))
        elements.append(Paragraph("ATTENDANCE & ROOM SUPERINTENDENT’S/EXAMINERS REPORT (In Triplicate)", sub_title_style))
        elements.append(Spacer(1, 8))
        
        m_data = [
            [Paragraph(f"<b>B.E./B.Arch./MCA/MBA/M.Tech:</b> {branch_val}", meta_style), Paragraph(f"<b>Semester Examination:</b> {date}", meta_style), Paragraph(f"<b>Block No:</b> {room}", meta_style)],
            [Paragraph(f"<b>Branch / Title of the course:</b> {branch_val}", meta_style), Paragraph(f"<b>Subject Code:</b> {code}", meta_style), ""],
            [Paragraph(f"<b>Subject:</b> {course_name}", meta_style), "", ""],
            [Paragraph(f"<b>Centre:</b> AMC ENGINEERING COLLEGE", meta_style), Paragraph(f"<b>Seat No's from:</b> {group['USN'].min()} <b>TO</b> {group['USN'].max()}", meta_style), ""],
            [Paragraph(f"<b>Date:</b> {date}", meta_style), "", Paragraph(f"<b>Time:</b> {session}", meta_style)]
        ]
        
        m_table = Table(m_data, colWidths=[2.7*inch, 2.7*inch, 2.0*inch])
        m_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('SPAN', (0,2), (2,2)), 
            ('BOTTOMPADDING', (0,0), (-1,-1), 4)
        ]))
        elements.append(m_table)
        elements.append(Spacer(1, 5))
        
        t_data = [[
            Paragraph("<b>ROLL NO</b>", th_style),
            Paragraph("<b>Seat Number of the Candidate</b>", th_style),
            Paragraph("<b>Answer Book/Main Drawing Sheet Number</b>", th_style),
            Paragraph("<b>Signature of the Candidate</b>", th_style),
            Paragraph("<b>Additional/Drawing/ Graph Sheet Numbers</b>", th_style),
            Paragraph("<b>Total</b>", th_style)
        ]]
        
        for _, r in group.sort_values('SeatNo').iterrows():
            t_data.append([Paragraph(r['USN'], td_style_c), Paragraph(str(r['Student Name']), td_style_l), "", "", "", ""])
            
        t = Table(t_data, colWidths=[1.1*inch, 2.1*inch, 1.3*inch, 1.3*inch, 1.1*inch, 0.5*inch])
        t.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2), 
            ('TOPPADDING', (0,0), (-1,-1), 2),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 10))
        
        f_data = [
            [Paragraph("<b>Seat Number of the candidates absent:</b> ____________________________________________________________________", meta_style), "", ""],
            [Paragraph("<b>Seat Number of the candidates booked under Malpractice:</b> ________________________________________________________", meta_style), "", ""],
            [Paragraph(f"<b>Total Number of students:</b> {len(group)}", meta_style), Paragraph("<b>Total Present:</b> ________", meta_style), Paragraph("<b>Total Absent:</b> ________", meta_style)],
            ["\n\nSignature of Room Superintendent", "", "\n\nSignature of Chief Superintendent"]
        ]
        f_table = Table(f_data, colWidths=[3.6*inch, 1.9*inch, 1.9*inch])
        f_table.setStyle(TableStyle([
            ('SPAN', (0,0), (2,0)), 
            ('SPAN', (0,1), (2,1)), 
            ('ALIGN', (0,3), (2,3), 'CENTER'), 
            ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5)
        ]))
        elements.append(f_table)
        elements.append(PageBreak())
        
    doc.build(elements, onFirstPage=get_header_drawer(assets), onLaterPages=get_header_drawer(assets))
    return buf.getvalue()

def gen_form_a(df, date, session, assets):
    buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=95)
    elements = []; styles = getSampleStyleSheet()
    
    for (branch, code), group in df.groupby(['Branch', 'Subject Code']):
        elements.append(Paragraph(f"<b>FORM A - ABSENTEES & BUNDLE DISPATCH</b>", styles['Heading2']))
        elements.append(Paragraph(f"Branch/Dept: {branch} | Date: {date} | Session: {session} | Course: {code}", styles['Normal']))
        elements.append(Spacer(1, 15))
        
        total = len(group)
        absentees = group[group['Status'] == 'ABSENT']['USN'].tolist()
        malpractice = group[group['Status'] == 'MALPRACTICE']['USN'].tolist()
        present = total - len(absentees) - len(malpractice)
        
        sorted_usns = sorted(group['USN'].tolist())
        usn_range = f"{sorted_usns[0]} TO {sorted_usns[-1]}" if sorted_usns else "NIL"
        
        sum_data = [
            ["Total Allotted", str(total)],
            ["Total Present", str(present)],
            ["Total Absent", str(len(absentees))],
            ["Absentee USNs", ", ".join(absentees) if absentees else "NIL"],
            ["Malpractice USNs", ", ".join(malpractice) if malpractice else "NIL"],
            ["Bundle Range (USNs)", usn_range]
        ]
        
        t = Table(sum_data, colWidths=[2*inch, 4.5*inch])
        t.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black), 
            ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE')
        ]))
        elements.append(t); elements.append(Spacer(1, 40))
        
        c_sig = Table([["Chief Superintendent / Dept Coordinator", "Signature of COE"]], colWidths=[3.25*inch, 3.25*inch])
        c_sig.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
        elements.append(c_sig)
        elements.append(PageBreak())
        
    doc.build(elements, onFirstPage=get_header_drawer(assets), onLaterPages=get_header_drawer(assets))
    return buf.getvalue()

def gen_qpds(df, date, session, assets):
    buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=95)
    elements = []; styles = getSampleStyleSheet()
    elements.append(Paragraph("<b>QP INDENT (ROOM WISE)</b>", styles['Heading2']))
    elements.append(Paragraph(f"Date: {date} | Session: {session}", styles['Normal']))
    elements.append(Spacer(1, 15))
    
    for room, data in df.groupby('RoomNo'):
        elements.append(Paragraph(f"<b>ROOM: {room}</b>", styles['Heading3']))
        counts = data.groupby('Subject Code').size().reset_index(name='Qty')
        t_data = [['Course Code', 'Quantity']]
        for _, r in counts.iterrows(): t_data.append([r['Subject Code'], str(r['Qty'])])
        t_data.append(['TOTAL', str(counts['Qty'].sum())])
        
        t = Table(t_data, colWidths=[2*inch, 1*inch])
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black)]))
        elements.append(t); elements.append(Spacer(1, 10))
        
    doc.build(elements, onFirstPage=get_header_drawer(assets), onLaterPages=get_header_drawer(assets))
    return buf.getvalue()

def gen_smart_excel(df, date, session):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
        df_sorted = df.sort_values(['Branch', 'USN'])
        df_sorted.to_excel(writer, sheet_name='Appearing_List', index=False, columns=['RoomNo', 'SeatNo', 'USN', 'Student Name', 'Branch', 'Subject Code'])
        summary = df.groupby(['RoomNo', 'Subject Code']).size().reset_index(name='Count')
        summary.to_excel(writer, sheet_name='Room_Summary', index=False)
    return buf.getvalue()

def create_locked_bundle(df, course_code, course_name, room_no, bundle_seq, total_bundles, cycle_name, assets):
    out = io.BytesIO()
    is_mba = 'MBA' in course_code.upper()
    
    with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
        wb = writer.book
        ws_marks = wb.add_worksheet('Marks Entry')
        ws_print = wb.add_worksheet('Print')
        
        fmt_title = wb.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'font_size': 14})
        fmt_sub = wb.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'font_size': 11})
        fmt_head = wb.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#f0f0f0', 'text_wrap': True})
        fmt_locked = wb.add_format({'locked': True, 'align': 'center', 'valign': 'vcenter', 'border': 1})
        fmt_locked_gray = wb.add_format({'locked': True, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#e0e0e0'})
        fmt_edit = wb.add_format({'locked': False, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#FFFFCC'})
        fmt_abs = wb.add_format({'locked': True, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'bold': True})
        fmt_footer = wb.add_format({'bold': True, 'font_size': 11, 'valign': 'vcenter'})
        
        # ==========================================
        # SHEET 1: MARKS ENTRY (USN Masked!)
        # ==========================================
        ws_marks.protect('admin123')
        ws_marks.merge_range('A1:AT1', 'AMC Engineering College', fmt_title)
        ws_marks.merge_range('A2:AT2', 'AMC Campus Bannerghatta Road, Bengaluru', fmt_sub)
        ws_marks.merge_range('A3:AT3', 'Autonomous Institution under VTU, Belagavi | NAAC A+ Accredited', fmt_sub)
        ws_marks.merge_range('A5:AT5', f'Semester End Examination - {cycle_name} | CBCS Scheme', fmt_sub)
        ws_marks.merge_range('A6:AT6', f'Evaluation & Marks Allotment | Course: {course_code} - {course_name} | Bundle {bundle_seq}/{total_bundles}', fmt_sub)
        
        ws_marks.merge_range('A8:A9', 'Sl. No.', fmt_head)
        ws_marks.merge_range('B8:B9', 'Coding No.', fmt_head)
        
        col_idx = 2
        for q in range(1, 11):
            ws_marks.merge_range(7, col_idx, 7, col_idx+2, f'Q. {q}', fmt_head)
            ws_marks.write(8, col_idx, 'a', fmt_head)
            ws_marks.write(8, col_idx+1, 'b', fmt_head)
            ws_marks.write(8, col_idx+2, 'c', fmt_head)
            ws_marks.merge_range(7, col_idx+3, 8, col_idx+3, f'Q.{q} Total', fmt_head)
            col_idx += 4
            
        ws_marks.merge_range(7, col_idx, 8, col_idx, 'Total SEE Marks (100)', fmt_head)
        ws_marks.merge_range(7, col_idx+1, 8, col_idx+1, 'Total Moderation', fmt_head)
        ws_marks.merge_range(7, col_idx+2, 8, col_idx+2, 'Marks Difference', fmt_head)
        ws_marks.merge_range(7, col_idx+3, 8, col_idx+3, 'Final SEE Marks (100)', fmt_head)
        
        row_idx = 9
        for i, s in df.iterrows():
            ws_marks.write(row_idx, 0, i+1, fmt_locked)
            ws_marks.write(row_idx, 1, s['Dummy_ID'], fmt_locked) 
            
            if s['Status'] != "PRESENT":
                for c in range(2, col_idx+3):
                    ws_marks.write(row_idx, c, "", fmt_locked_gray)
                ws_marks.write(row_idx, col_idx+3, s['Status'], fmt_abs)
            else:
                c = 2
                for q in range(1, 11):
                    if is_mba and q > 8:
                        ws_marks.write(row_idx, c, "", fmt_locked_gray)
                        ws_marks.write(row_idx, c+1, "", fmt_locked_gray)
                        ws_marks.write(row_idx, c+2, "", fmt_locked_gray)
                        ws_marks.write(row_idx, c+3, "", fmt_locked_gray)
                    else:
                        ws_marks.write(row_idx, c, "", fmt_edit)
                        ws_marks.write(row_idx, c+1, "", fmt_edit)
                        ws_marks.write(row_idx, c+2, "", fmt_edit)
                        cell_a = xl_rowcol_to_cell(row_idx, c)
                        cell_c = xl_rowcol_to_cell(row_idx, c+2)
                        ws_marks.write_formula(row_idx, c+3, f'=SUM({cell_a}:{cell_c})', fmt_locked)
                    c += 4
                
                r = row_idx + 1
                if is_mba:
                    q1_7_cells = f"F{r},J{r},N{r},R{r},V{r},Z{r},AD{r}"
                    formula_see = f"=IFERROR(LARGE(({q1_7_cells}),1),0)+IFERROR(LARGE(({q1_7_cells}),2),0)+IFERROR(LARGE(({q1_7_cells}),3),0)+IFERROR(LARGE(({q1_7_cells}),4),0)+AH{r}"
                else:
                    formula_see = f"=MAX(F{r},J{r})+MAX(N{r},R{r})+MAX(V{r},Z{r})+MAX(AD{r},AH{r})+MAX(AL{r},AP{r})"
                
                ws_marks.write_formula(row_idx, col_idx, formula_see, fmt_locked)
                ws_marks.write(row_idx, col_idx+1, "", fmt_edit) 
                
                formula_diff = f'=IF(AR{r}>0,AQ{r}-AR{r},"")'
                ws_marks.write_formula(row_idx, col_idx+2, formula_diff, fmt_locked)
                
                formula_final = f"=MAX(AQ{r},AR{r})"
                ws_marks.write_formula(row_idx, col_idx+3, formula_final, fmt_locked)

            row_idx += 1
            
        ws_marks.set_column('A:A', 8)
        ws_marks.set_column('B:B', 12)
        ws_marks.set_column('C:AP', 5)
        ws_marks.set_column('AQ:AT', 14)
        
        # ==========================================
        # SHEET 2: PRINT
        # ==========================================
        ws_print.protect('admin123')
        ws_print.set_row(0, 45) # Make Header Row 60 pixels high
        
        ws_print.merge_range('A1:D1', 'AMC Engineering College', fmt_title)
        ws_print.merge_range('A2:D2', f'Semester End Examination - {cycle_name}', fmt_sub)
        ws_print.merge_range('A3:D3', f'Course Code: {course_code} | Course Title: {course_name}', fmt_sub)
        
        # 🟢 BULLETPROOF IMAGE RESIZING 🟢
        # Physically resizes the images to exactly 50 pixels high before insertion
        if "logo" in assets:
            resized_logo = resize_image_for_excel(assets["logo"], target_height=50)
            ws_print.insert_image('A1', 'logo.png', {'image_data': resized_logo, 'x_offset': 10, 'y_offset': 5})
            
        if "naac" in assets:
            resized_naac = resize_image_for_excel(assets["naac"], target_height=50)
            # x_offset 180 places it cleanly on the far right of the wide 'D' column
            ws_print.insert_image('D1', 'naac.png', {'image_data': resized_naac, 'x_offset': 180, 'y_offset': 5})

        headers_print = ['Sl. No.', 'Answer Booklet Code', 'SEE Marks in Figures (100)', 'SEE Marks in Words']
        for c, h in enumerate(headers_print):
            ws_print.write(4, c, h, fmt_head)
            
        row_idx = 5
        for idx, s in df.iterrows():
            ws_print.write(row_idx, 0, idx+1, fmt_locked)
            ws_print.write(row_idx, 1, s['Dummy_ID'], fmt_locked)
            
            if s['Status'] != "PRESENT":
                ws_print.write(row_idx, 2, s['Status'], fmt_abs)
                ws_print.write(row_idx, 3, "-", fmt_locked_gray)
            else:
                final_marks_cell = xl_rowcol_to_cell(9 + idx, col_idx+3) 
                ws_print.write_formula(row_idx, 2, f"='Marks Entry'!{final_marks_cell}", fmt_locked)
                ws_print.write(row_idx, 3, "", fmt_edit)
                
            row_idx += 1
            
        ws_print.set_column('A:A', 8)
        ws_print.set_column('B:B', 20)
        ws_print.set_column('C:C', 25)
        ws_print.set_column('D:D', 35)

        row_idx += 3
        ws_print.write(row_idx, 1, "Evaluator Name: _________________________", fmt_footer)
        ws_print.write(row_idx, 3, "Evaluator Signature with date: _________________________", fmt_footer)

    return out.getvalue()

def gen_marks_bundles(df, assets):
    zip_buf = io.BytesIO()
    key_log = []
    
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for (room, cc), group in df.groupby(['RoomNo', 'Subject Code']):
            group = group.sort_values('SeatNo').reset_index(drop=True)
            n_chunks = math.ceil(len(group) / 20)
            
            for i in range(n_chunks):
                chunk = group.iloc[i*20 : (i+1)*20].copy()
                chunk['Dummy_ID'] = generate_dummy_ids(len(chunk))
                
                b_id = f"{room}_{cc}_{str(i+1).zfill(2)}"
                course_name = chunk['Subject Name'].iloc[0] if 'Subject Name' in chunk.columns else cc
                
                for _, s in chunk.iterrows():
                    key_log.append({
                        'Bundle_ID': b_id, 'Room': room, 'USN': s['USN'], 
                        'Subject': cc, 'Dummy_ID': s['Dummy_ID'], 'Status': s['Status']
                    })
                
                excel_bytes = create_locked_bundle(chunk, cc, course_name, room, i+1, n_chunks, active_cycle_name, assets)
                zf.writestr(f"Bundles/{b_id}.xlsx", excel_bytes)
                
        kdf = pd.DataFrame(key_log)
        out_k = io.BytesIO()
        kdf.to_excel(out_k, index=False)
        zf.writestr("MASTER_SECRET_KEY.xlsx", out_k.getvalue())
        
    return zip_buf.getvalue()

# ==========================================
# 5. UI FLOW
# ==========================================

if not selected_cycle_id:
    st.warning("⚠️ Please select an Active Exam Cycle in the Sidebar to proceed.")
    st.stop()

pdf_assets = load_pdf_assets()

st.title("🚀 Exam Day Operations")

sessions = fetch_exam_sessions(selected_cycle_id)
if not sessions:
    st.error("No timetable records found for this cycle.")
    st.stop()

def clear_allocation():
    if "alloc_df" in st.session_state: del st.session_state["alloc_df"]

selected_slot = st.selectbox("📅 Select Date & Session", sessions, on_change=clear_allocation)

date_str, sess_str = selected_slot.split(" | ")
df_stus = fetch_exam_data(selected_cycle_id, date_str, sess_str)
df_rooms_master = fetch_rooms()

if df_stus.empty:
    st.error("No students registered for this session.")
elif df_rooms_master.empty:
    st.error("No rooms defined in Infrastructure master.")
else:
    total_students = len(df_stus)
    st.info(f"👨‍🎓 **Total Students to Allocate:** {total_students}")

    st.markdown("---")
    st.subheader("🏢 Select Exam Blocks & Rooms")
    
    with st.form("room_selector_form"):
        df_rooms_master.insert(0, 'Select', False) 
        display_cols = ['Select', 'block_name', 'room_no', 'capacity', 'bench_type']
        
        edited_rooms = st.data_editor(
            df_rooms_master[display_cols],
            column_config={
                "Select": st.column_config.CheckboxColumn("Use Room", default=False),
                "block_name": st.column_config.TextColumn("Block Name", disabled=True),
                "room_no": st.column_config.TextColumn("Room No.", disabled=True),
                "capacity": st.column_config.NumberColumn("Capacity", disabled=True)
            },
            hide_index=True, use_container_width=True
        )

        selected_rooms_df = edited_rooms[edited_rooms['Select'] == True]
        selected_capacity = selected_rooms_df['capacity'].sum()
        
        st.write(f"**Selected Capacity:** {selected_capacity} / {total_students} needed.")
        
        submitted_allocation = st.form_submit_button("⚙️ Run Allocation Algorithm", type="primary")
        
        if submitted_allocation:
            if selected_capacity < total_students:
                st.error("⚠️ Not enough capacity! Please select more rooms.")
            else:
                with st.spinner("Assigning seats..."):
                    df_alloc = run_allocation(df_stus, selected_rooms_df)
                    df_alloc['Status'] = "PRESENT" 
                    st.session_state.alloc_df = df_alloc
                    st.success(f"✅ Allocated {len(df_alloc)} students successfully!")
                    st.rerun()

if "alloc_df" in st.session_state and not st.session_state.alloc_df.empty:
    df_a = st.session_state.alloc_df
    
    st.markdown("---")
    st.subheader("📝 1. Mark Absentees / Malpractice")
    st.write("Enter USNs separated by commas or new lines. This updates Form A and locks them out of evaluation bundles.")
    
    with st.form("absentee_form"):
        col1, col2 = st.columns(2)
        with col1:
            abs_text = st.text_area("Absentee USNs", placeholder="e.g. 1AM25CS001, 1AM25CS002\n1AM25CS003", height=100)
        with col2:
            mal_text = st.text_area("Malpractice USNs", placeholder="e.g. 1AM25ME045", height=100)
            
        if st.form_submit_button("💾 Apply Status Updates", type="secondary"):
            absent_list = [x.strip().upper() for x in abs_text.replace('\n', ',').split(',') if x.strip()]
            mal_list = [x.strip().upper() for x in mal_text.replace('\n', ',').split(',') if x.strip()]
            
            df_a['Status'] = "PRESENT"
            df_a.loc[df_a['USN'].isin(absent_list), 'Status'] = "ABSENT"
            df_a.loc[df_a['USN'].isin(mal_list), 'Status'] = "MALPRACTICE"
            
            st.session_state.alloc_df = df_a
            st.success(f"Updated! {len(absent_list)} Absentees, {len(mal_list)} Malpractice.")
    
    st.markdown("---")
    st.subheader("🖨️ 2. Download Exam Documents")
    
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.download_button("📌 Room Posters", gen_posters(df_a, date_str, sess_str, pdf_assets), f"Posters_{date_str}.pdf")
    with c2: st.download_button("📝 Form B", gen_form_b(df_a, date_str, sess_str, pdf_assets), f"FormB_{date_str}.pdf")
    with c3: st.download_button("📦 Form A", gen_form_a(df_a, date_str, sess_str, pdf_assets), f"FormA_{date_str}.pdf")
    with c4: st.download_button("📋 QPDS", gen_qpds(df_a, date_str, sess_str, pdf_assets), f"QPDS_{date_str}.pdf")
    with c5: st.download_button("📊 Appearing List", gen_smart_excel(df_a, date_str, sess_str), f"Appearing_{date_str}.xlsx")
        
    st.markdown("---")
    st.subheader("🔐 3. Post-Exam Processing")
    st.info("Generates secure Evaluation Excel bundles. Maximum 20 papers per bundle. Absentees are dynamically locked. USNs are completely masked from Evaluators.")
    
    if st.button("📦 Generate Locked Marks Bundles (.zip)", type="primary"):
        with st.spinner("Encrypting bundles and generating Secret Key..."):
            zip_bytes = gen_marks_bundles(df_a, pdf_assets)
            st.download_button("📥 Click to Download ZIP", zip_bytes, f"Evaluation_Bundles_{date_str}.zip", "application/zip")

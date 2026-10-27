import streamlit as st
import pandas as pd
import io
import datetime
import math
import zipfile
import string
import random
import json
import qrcode
from collections import defaultdict
from utils import init_db
from PIL import Image as PILImage

# --- PDF LIBRARIES ---
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.utils import ImageReader

# --- EXCEL UTILS ---
from xlsxwriter.utility import xl_rowcol_to_cell, xl_col_to_name

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
    assets = {}
    for k, f in [("logo", LOGO_FILENAME), ("naac", NAAC_FILENAME)]:
        try:
            res = supabase.storage.from_("College_Logos").download(f)
            if res: assets[k] = res
        except: pass
    return assets

def resize_image_for_excel(img_bytes, target_height=50):
    try:
        with PILImage.open(io.BytesIO(img_bytes)) as img:
            w_percent = (target_height / float(img.size[1]))
            target_width = int(float(img.size[0]) * float(w_percent))
            
            resized_img = img.resize((target_width, target_height), PILImage.LANCZOS)
            if resized_img.mode != 'RGBA':
                resized_img = resized_img.convert('RGBA')
                
            out_io = io.BytesIO()
            resized_img.save(out_io, format='PNG')
            out_io.seek(0)
            return out_io
    except Exception as e:
        return io.BytesIO(img_bytes)

# 🟢 RESTORED ORIGINAL DUMMY ID GENERATOR (e.g. AA1, AA2)
USED_PREFIXES = set()

def generate_dummy_ids(count):
    global USED_PREFIXES
    while True:
        prefix = "".join(random.choices(string.ascii_uppercase, k=2))
        if prefix not in USED_PREFIXES:
            USED_PREFIXES.add(prefix)
            break
    return [f"{prefix}{i+1}" for i in range(count)]

# ==========================================
# 2. DATA FETCHING & DB HELPERS
# ==========================================

def fetch_exam_sessions(cycle_id):
    if not cycle_id: return []
    res = supabase.table("exam_timetable").select("exam_date, session").eq("cycle_id", cycle_id).execute()
    df = pd.DataFrame(res.data)
    if df.empty: return []
    df['label'] = df['exam_date'] + " | " + df['session']
    return df.sort_values('exam_date')['label'].unique().tolist()

def fetch_exam_data(cycle_id, date_str, session_str, exam_type='Regular'):
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
        res = supabase.table("master_students").select("usn, full_name, branch_code, status").in_("usn", usns).range(start, start + limit - 1).execute()
        if not res.data: break
        all_stus.extend(res.data)
        if len(res.data) < limit: break
        start += limit
        
    df_stus = pd.DataFrame(all_stus)
    if df_stus.empty: return pd.DataFrame()
    
    df_stus['status'] = df_stus['status'].fillna('ACTIVE').astype(str).str.strip().str.upper()
    if str(exam_type).strip().upper() == 'REGULAR':
        df_stus = df_stus[df_stus['status'] == 'ACTIVE'].copy()
    else:
        df_stus = df_stus[df_stus['status'].isin(['ACTIVE', 'DETAINED'])].copy()
    
    if df_stus.empty: return pd.DataFrame()
    
    df_stus['Branch'] = df_stus['branch_code']
    df_merged = pd.merge(df_regs, df_stus, on='usn', how='inner')
    df_merged.rename(columns={'usn': 'USN', 'full_name': 'Student Name', 'course_code': 'Subject Code'}, inplace=True)
    
    courses_res = supabase.table("master_courses").select("course_code, title").in_("course_code", course_codes).execute()
    course_dict = {r['course_code']: r['title'] for r in courses_res.data}
    df_merged['Subject Name'] = df_merged['Subject Code'].map(lambda x: course_dict.get(x, x))
    
    return df_merged

def fetch_rooms():
    res = supabase.table("master_rooms").select("*").order("priority_order").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

def fetch_seating_allocation(cycle_id, date_str, session_str):
    res = supabase.table("exam_seating_allocations").select("*").eq("cycle_id", cycle_id).eq("exam_date", date_str).eq("session", session_str).execute()
    if not res.data: return pd.DataFrame()
    
    df = pd.DataFrame(res.data)
    df.rename(columns={
        'room_no': 'RoomNo', 'seat_no': 'SeatNo', 'usn': 'USN', 
        'student_name': 'Student Name', 'branch': 'Branch', 
        'course_code': 'Subject Code', 'course_name': 'Subject Name', 'status': 'Status'
    }, inplace=True)
    return df

# ==========================================
# 3. ALLOCATION ENGINE
# ==========================================

def run_allocation(df_students, df_rooms):
    subj_map = {
        '1BKSK109': '1BKSK209', '1BKBK109': '1BKBK209',
        '1BENG106': '1BENG206'
    }
    df_students['AllocCode'] = df_students['Subject Code'].replace(subj_map)

    branch_counts = df_students.groupby(['AllocCode', 'Branch']).size().to_dict()
    df_students['BranchSize'] = df_students.apply(lambda x: branch_counts[(x['AllocCode'], x['Branch'])], axis=1)
    
    df_students = df_students.sort_values(['AllocCode', 'BranchSize', 'Branch', 'USN'], ascending=[True, False, True, True])

    OMR_SUBJECTS = ['1BKSK209', '1BKBK209', '1BENG206']
    allotment_rows = []
    
    df_rooms = df_rooms.sort_values('room_no')
    rooms_list = df_rooms.to_dict('records')
    room_idx = 0

    def get_next_room():
        nonlocal room_idx
        if room_idx < len(rooms_list):
            r = rooms_list[room_idx]
            room_idx += 1
            return r['room_no'], int(r['capacity'])
        return None, 0

    current_room_no, current_capacity = get_next_room()
    
    # --- OMR ALLOCATION ---
    df_omr = df_students[df_students['AllocCode'].isin(OMR_SUBJECTS)]
    if not df_omr.empty:
        students = df_omr.to_dict('records')
        current_seat = 1
        
        while students:
            if not current_room_no: break
            if current_seat > current_capacity:
                current_room_no, current_capacity = get_next_room()
                current_seat = 1
                if not current_room_no: break

            s = students.pop(0)
            allotment_rows.append({
                'RoomNo': current_room_no, 'SeatNo': current_seat,
                'USN': s['USN'], 'Student Name': s['Student Name'],
                'Branch': s['Branch'], 'Subject Code': s['Subject Code'],
                'Subject Name': s['Subject Name']
            })
            current_seat += 1

        if current_seat > 1:
            current_room_no, current_capacity = get_next_room()

    # --- REGULAR ALLOCATION ---
    df_reg = df_students[~df_students['AllocCode'].isin(OMR_SUBJECTS)]
    if not df_reg.empty:
        subj_queues = {}
        for code in df_reg['AllocCode'].unique():
            subj_queues[code] = df_reg[df_reg['AllocCode'] == code].to_dict('records')

        active_subjs = sorted(subj_queues.keys(), key=lambda k: len(subj_queues[k]), reverse=True)

        while active_subjs and current_room_no:
            subj_A = active_subjs[0]
            subj_B = active_subjs[1] if len(active_subjs) > 1 else None

            for seat in range(1, current_capacity + 1):
                target_subj = subj_A if seat % 2 != 0 else (subj_B or subj_A)

                if target_subj and not subj_queues[target_subj]:
                    target_subj = subj_B if target_subj == subj_A else subj_A

                if target_subj is None or not subj_queues[target_subj]:
                    active_subjs = [s for s in active_subjs if subj_queues[s]]
                    if not active_subjs: break
                    subj_A = active_subjs[0]
                    subj_B = active_subjs[1] if len(active_subjs) > 1 else None
                    target_subj = subj_A 

                student = subj_queues[target_subj].pop(0)
                allotment_rows.append({
                    'RoomNo': current_room_no, 'SeatNo': seat,
                    'USN': student['USN'], 'Student Name': student['Student Name'],
                    'Branch': student['Branch'], 'Subject Code': student['Subject Code'],
                    'Subject Name': student['Subject Name']
                })

                if not subj_queues[target_subj]:
                    active_subjs = [s for s in active_subjs if subj_queues[s]]
                    if active_subjs:
                        subj_A = active_subjs[0]
                        subj_B = active_subjs[1] if len(active_subjs) > 1 else None

            current_room_no, current_capacity = get_next_room()

    return pd.DataFrame(allotment_rows)
    
# ==========================================
# 4. DOCUMENT GENERATORS (Posters & Forms)
# ==========================================

def get_header_drawer(assets):
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
        
        c.setLineWidth(1)
        c.line(30, y_start - 40, A4[0] - 30, y_start - 40)
        c.restoreState()
    return draw_header

def gen_posters(df, date, session, assets):
    buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=90, bottomMargin=15)
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
    elements = []; styles = getSampleStyleSheet()
    
    sub_title_style = ParagraphStyle('SubTitle', parent=styles['Normal'], alignment=TA_CENTER, fontName='Helvetica-Bold', fontSize=10)
    meta_style = ParagraphStyle('Meta', parent=styles['Normal'], fontSize=9, leading=12)
    th_style = ParagraphStyle('th', parent=styles['Normal'], alignment=TA_CENTER, fontName='Helvetica-Bold', fontSize=8)
    td_style_c = ParagraphStyle('td_c', parent=styles['Normal'], alignment=TA_CENTER, fontSize=9)
    td_style_l = ParagraphStyle('td_l', parent=styles['Normal'], alignment=TA_LEFT, fontSize=8)
    
    for (room, code), group in df.groupby(['RoomNo', 'Subject Code']):
        course_name = group['Subject Name'].iloc[0] if 'Subject Name' in group.columns else code
        branch_val = group['Branch'].iloc[0] if 'Branch' in group.columns else "N/A"
        
        elements.append(Paragraph("ATTENDANCE & ROOM SUPERINTENDENT’S REPORT", sub_title_style))
        elements.append(Spacer(1, 8))
        
        m_data = [
            [Paragraph(f"<b>Branch:</b> {branch_val}", meta_style), Paragraph(f"<b>Date:</b> {date}", meta_style), Paragraph(f"<b>Room No:</b> {room}", meta_style)],
            [Paragraph(f"<b>Course:</b> {course_name}", meta_style), Paragraph(f"<b>Course Code:</b> {code}", meta_style), Paragraph(f"<b>Session:</b> {session}", meta_style)],
        ]
        m_table = Table(m_data, colWidths=[2.7*inch, 2.7*inch, 2.0*inch])
        m_table.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'LEFT'), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('BOTTOMPADDING', (0,0), (-1,-1), 4)]))
        elements.append(m_table)
        elements.append(Spacer(1, 5))
        
        t_data = [[
            Paragraph("<b>USN</b>", th_style), Paragraph("<b>Candidate Name</b>", th_style),
            Paragraph("<b>Booklet No.</b>", th_style), Paragraph("<b>Signature</b>", th_style)
        ]]
        for _, r in group.sort_values('SeatNo').iterrows():
            t_data.append([Paragraph(r['USN'], td_style_c), Paragraph(str(r['Student Name']), td_style_l), "", ""])
            
        t = Table(t_data, colWidths=[1.5*inch, 2.5*inch, 1.5*inch, 1.5*inch])
        t.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)
        ]))
        elements.append(t)
        elements.append(PageBreak())
        
    doc.build(elements, onFirstPage=get_header_drawer(assets), onLaterPages=get_header_drawer(assets))
    return buf.getvalue()

# 🟢 RESTORED QPDS GENERATOR
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

# 🟢 RESTORED SMART EXCEL GENERATOR (Appearing List)
def gen_smart_excel(df, date, session):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
        df_sorted = df.sort_values(['Branch', 'USN'])
        df_sorted.to_excel(writer, sheet_name='Appearing_List', index=False, columns=['RoomNo', 'SeatNo', 'USN', 'Student Name', 'Branch', 'Subject Code'])
        summary = df.groupby(['RoomNo', 'Subject Code']).size().reset_index(name='Count')
        summary.to_excel(writer, sheet_name='Room_Summary', index=False)
    return buf.getvalue()

def gen_form_a(df, date, session, assets, cycle_name):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=90, leftMargin=35, rightMargin=35, bottomMargin=30)
    elements = []; styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('Title', parent=styles['Heading3'], alignment=TA_CENTER, fontName='Helvetica-Bold', fontSize=12)
    meta_style = ParagraphStyle('Meta', parent=styles['Normal'], fontSize=10, leading=14)
    th_style = ParagraphStyle('th', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10)
    td_style_l = ParagraphStyle('td_l', parent=styles['Normal'], fontSize=9, leading=14, alignment=TA_LEFT)
    td_style_c = ParagraphStyle('td_c', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER, fontName='Helvetica-Bold')
    
    for (branch, code), group in df.groupby(['Branch', 'Subject Code']):
        course_name = group['Subject Name'].iloc[0] if 'Subject Name' in group.columns else code
        
        elements.append(Paragraph("FORM - A (CONSOLIDATED ATTENDANCE REPORT)", title_style))
        elements.append(Spacer(1, 15))
        
        m_data = [
            [Paragraph(f"<b>Branch:</b> {branch}", meta_style), Paragraph(f"<b>Course:</b> {course_name} ({code})", meta_style)],
            [Paragraph(f"<b>Date:</b> {date}", meta_style), Paragraph(f"<b>Session:</b> {session}", meta_style)]
        ]
        m_table = Table(m_data, colWidths=[2.5*inch, 4.5*inch])
        m_table.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'LEFT'), ('BOTTOMPADDING', (0,0), (-1,-1), 6)]))
        elements.append(m_table)
        elements.append(Spacer(1, 15))
        
        present_usns = group[group['Status'] == 'PRESENT']['USN'].sort_values().tolist()
        absent_usns = group[group['Status'] == 'ABSENT']['USN'].sort_values().tolist()
        malp_usns = group[group['Status'] == 'MALPRACTICE']['USN'].sort_values().tolist()
        
        t_data = []
        t_styles = [('GRID', (0,0), (-1,-1), 0.5, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]
        current_row = 0
        
        def add_section(title, usn_list):
            nonlocal current_row
            t_data.append([Paragraph(f"<b>{title}</b>", th_style), Paragraph("<b>COUNT</b>", th_style)])
            t_styles.append(('BACKGROUND', (0, current_row), (-1, current_row), colors.lightgrey))
            current_row += 1
            if not usn_list:
                t_data.append([Paragraph("Nil", td_style_l), Paragraph("0", td_style_c)])
                current_row += 1
            else:
                chunk_size = 60 
                for i in range(0, len(usn_list), chunk_size):
                    chunk = usn_list[i:i+chunk_size]
                    t_data.append([Paragraph(", ".join(chunk), td_style_l), Paragraph(str(len(usn_list)) if i==0 else "", td_style_c)])
                    current_row += 1

        add_section("PRESENT CANDIDATES", present_usns)
        add_section("ABSENT CANDIDATES", absent_usns)
        add_section("MALPRACTICE CANDIDATES", malp_usns)
        
        t = Table(t_data, colWidths=[6.2*inch, 1.0*inch])
        t.setStyle(TableStyle(t_styles))
        elements.append(t)
        elements.append(PageBreak())
        
    doc.build(elements, onFirstPage=get_header_drawer(assets), onLaterPages=get_header_drawer(assets))
    return buf.getvalue()


# ==========================================
# 5. HYBRID BUNDLE GENERATORS (Excel + Barcodes)
# ==========================================

def create_locked_bundle(df, course_code, course_name, b_group, bundle_seq, total_bundles, cycle_name, assets):
    out = io.BytesIO()
    is_mba = 'MBA' in course_code.upper()
    num_q = 8 if is_mba else 10
    
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
        fmt_footer_val = wb.add_format({'bold': True, 'font_size': 11, 'valign': 'vcenter', 'align': 'left', 'font_color': '#0000FF'})
        
        end_col_idx = 2 + (num_q * 4) 
        col_tot = xl_col_to_name(end_col_idx)
        col_mod = xl_col_to_name(end_col_idx + 1)
        col_diff = xl_col_to_name(end_col_idx + 2)
        col_final = xl_col_to_name(end_col_idx + 3)
        last_q_col = xl_col_to_name(end_col_idx - 1)

        ws_marks.protect('admin123')
        ws_marks.merge_range(f'A1:{col_final}1', 'AMC Engineering College', fmt_title)
        ws_marks.merge_range(f'A2:{col_final}2', 'AMC Campus Bannerghatta Road, Bengaluru', fmt_sub)
        ws_marks.merge_range(f'A3:{col_final}3', 'Autonomous Institution under VTU, Belagavi | NAAC A+ Accredited', fmt_sub)
        ws_marks.merge_range(f'A5:{col_final}5', f'Semester End Examination - {cycle_name} | CBCS Scheme', fmt_sub)
        ws_marks.merge_range(f'A6:{col_final}6', f'Evaluation & Marks Allotment | Course: {course_code} - {course_name} | Bundle {bundle_seq}/{total_bundles}', fmt_sub)
        
        ws_marks.merge_range('A8:A9', 'Sl. No.', fmt_head)
        ws_marks.merge_range('B8:B9', 'Coding No.', fmt_head)
        
        col_idx = 2
        for q in range(1, num_q + 1):
            ws_marks.merge_range(7, col_idx, 7, col_idx+2, f'Q. {q}', fmt_head)
            ws_marks.write(8, col_idx, 'a', fmt_head)
            ws_marks.write(8, col_idx+1, 'b', fmt_head)
            ws_marks.write(8, col_idx+2, 'c', fmt_head)
            ws_marks.merge_range(7, col_idx+3, 8, col_idx+3, f'Q.{q} Total', fmt_head)
            col_idx += 4
            
        ws_marks.merge_range(7, end_col_idx, 8, end_col_idx, 'Total SEE Marks (100)', fmt_head)
        ws_marks.merge_range(7, end_col_idx+1, 8, end_col_idx+1, 'Total Moderation', fmt_head)
        ws_marks.merge_range(7, end_col_idx+2, 8, end_col_idx+2, 'Marks Difference', fmt_head)
        ws_marks.merge_range(7, end_col_idx+3, 8, end_col_idx+3, 'Final SEE Marks (100)', fmt_head)
        
        row_idx = 9
        for local_idx, (_, s) in enumerate(df.iterrows()):
            ws_marks.write(row_idx, 0, local_idx+1, fmt_locked)
            ws_marks.write(row_idx, 1, s['Dummy_ID'], fmt_locked) 
            
            if s['Status'] != "PRESENT":
                for c in range(2, end_col_idx+3): ws_marks.write(row_idx, c, "", fmt_locked_gray)
                ws_marks.write(row_idx, end_col_idx+3, s['Status'], fmt_abs)
            else:
                c = 2
                for q in range(1, num_q + 1):
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
                
                ws_marks.write_formula(row_idx, end_col_idx, formula_see, fmt_locked)
                ws_marks.write(row_idx, end_col_idx+1, "", fmt_edit) 
                
                ws_marks.write_formula(row_idx, end_col_idx+2, f'=IF({col_mod}{r}>0,{col_tot}{r}-{col_mod}{r},"")', fmt_locked)
                ws_marks.write_formula(row_idx, end_col_idx+3, f"=MAX({col_tot}{r},{col_mod}{r})", fmt_locked)

            row_idx += 1
            
        eval_row = row_idx + 2
        ws_marks.merge_range(eval_row, 0, eval_row, 1, "Evaluator Name:", fmt_head)
        ws_marks.merge_range(eval_row, 2, eval_row, 5, "", fmt_edit) 
        eval_input_cell = xl_rowcol_to_cell(eval_row, 2)
            
        ws_marks.set_column('A:A', 8)
        ws_marks.set_column('B:B', 12)
        ws_marks.set_column(f'C:{last_q_col}', 5)
        ws_marks.set_column(f'{col_tot}:{col_final}', 14)
        
        ws_print.protect('admin123')
        ws_print.set_row(0, 45) 
        
        ws_print.merge_range('A1:D1', 'AMC Engineering College', fmt_title)
        ws_print.merge_range('A2:D2', f'Semester End Examination - {cycle_name}', fmt_sub)
        ws_print.merge_range('A3:D3', f'Course Code: {course_code} | Course Title: {course_name}', fmt_sub)
        
        if "logo" in assets:
            ws_print.insert_image('A1', 'logo.png', {'image_data': resize_image_for_excel(assets["logo"]), 'x_offset': 10, 'y_offset': 5})
        if "naac" in assets:
            ws_print.insert_image('D1', 'naac.png', {'image_data': resize_image_for_excel(assets["naac"]), 'x_offset': 180, 'y_offset': 5})

        headers_print = ['Sl. No.', 'Answer Booklet Code', 'SEE Marks in Figures (100)', 'SEE Marks in Words']
        for c, h in enumerate(headers_print):
            ws_print.write(4, c, h, fmt_head)
            
        row_idx = 5
        for local_idx, (_, s) in enumerate(df.iterrows()):
            ws_print.write(row_idx, 0, local_idx+1, fmt_locked)
            ws_print.write(row_idx, 1, s['Dummy_ID'], fmt_locked)
            
            if s['Status'] != "PRESENT":
                ws_print.write(row_idx, 2, s['Status'], fmt_abs)
                ws_print.write(row_idx, 3, "-", fmt_locked_gray)
            else:
                final_marks_cell = xl_rowcol_to_cell(9 + local_idx, end_col_idx+3) 
                ws_print.write_formula(row_idx, 2, f"='Marks Entry'!{final_marks_cell}", fmt_locked)
                
                c_cell = xl_rowcol_to_cell(row_idx, 2) 
                ch = 'CHOOSE(MID({},{},1)+1, "Zero","One","Two","Three","Four","Five","Six","Seven","Eight","Nine")'
                p1 = f'IF(LEN({c_cell})>=1, {ch.format(c_cell, 1)}, "")'
                p2 = f'IF(LEN({c_cell})>=2, " " & {ch.format(c_cell, 2)}, "")'
                p3 = f'IF(LEN({c_cell})>=3, " " & {ch.format(c_cell, 3)}, "")'
                words_formula = f'=IF({c_cell}="","",TRIM({p1} & {p2} & {p3}))'
                
                ws_print.write_formula(row_idx, 3, words_formula, fmt_locked)
                
            row_idx += 1
            
        ws_print.set_column('A:A', 8)
        ws_print.set_column('B:B', 20)
        ws_print.set_column('C:C', 25)
        ws_print.set_column('D:D', 35)

        row_idx += 3
        ws_print.write(row_idx, 1, "Evaluator Name:", fmt_footer)
        ws_print.write_formula(row_idx, 2, f'=IF(\'Marks Entry\'!{eval_input_cell}="","",\'Marks Entry\'!{eval_input_cell})', fmt_footer_val)
        ws_print.write(row_idx, 3, "Signature with Date: _________________________", fmt_footer)

    return out.getvalue()

def gen_barcode_bundle_covers(bundles, cycle_name, assets):
    """Generates the physical printouts using High-Density QR Codes containing all bundle metadata"""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=50, bottomMargin=30)
    elements = []
    styles = getSampleStyleSheet()
    
    for b in bundles:
        elements.append(Paragraph(f"<b>EVALUATION BUNDLE COVER</b>", ParagraphStyle('T', alignment=TA_CENTER, fontSize=16)))
        elements.append(Spacer(1, 10))
        
        # 🟢 GENERATE HIGH-DENSITY QR CODE WITH EMBEDDED METADATA
        qr_payload = {
            "cycle": cycle_name,
            "bundle": b['bundle_id'],
            "course": b['course_code'],
            "map": {s['dummy_id']: s['usn'] for s in b['scripts'] if s['status'] == 'PRESENT'}
        }
        
        qr = qrcode.make(json.dumps(qr_payload))
        qr_io = io.BytesIO()
        qr.save(qr_io, format="PNG")
        qr_io.seek(0)
        
        # Add QR Image to PDF
        qr_img = RLImage(qr_io, width=2*inch, height=2*inch)
        qr_img.hAlign = 'CENTER'
        elements.append(qr_img)
        elements.append(Spacer(1, 5))
        
        elements.append(Paragraph(f"<b>{b['bundle_id']}</b>", ParagraphStyle('BC', alignment=TA_CENTER, fontSize=14, fontName='Helvetica-Bold')))
        elements.append(Spacer(1, 15))
        
        meta = [
            [f"Course Code:", f"{b['course_code']}"],
            [f"Course Name:", f"{b['course_name']}"],
            [f"Exam Date:", f"{b['exam_date']} ({b['session']})"],
            [f"Total Scripts Inside:", f"{len(b['scripts'])} Papers"]
        ]
        t_meta = Table(meta, colWidths=[2*inch, 4*inch])
        t_meta.setStyle(TableStyle([
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 12),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ]))
        elements.append(t_meta)
        elements.append(Spacer(1, 20))
        
        elements.append(Paragraph("<b>COE INSTRUCTIONS:</b> Mask the USNs and write the following familiar Dummy IDs on the physical booklets before sealing this envelope.", styles['Normal']))
        elements.append(Spacer(1, 10))
        
        grid_data = [["Sl. No.", "Dummy ID to Write on Booklet", "Status"]]
        for idx, s in enumerate(b['scripts']):
            status_str = s['status'] if s['status'] != 'PRESENT' else ""
            grid_data.append([str(idx+1), s['dummy_id'], status_str])
            
        t_grid = Table(grid_data, colWidths=[0.8*inch, 3*inch, 2*inch])
        t_grid.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 1, colors.black),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('PADDING', (0,0), (-1,-1), 6)
        ]))
        elements.append(t_grid)
        elements.append(Spacer(1, 30))
        
        elements.append(Paragraph("<b>EVALUATOR INSTRUCTIONS:</b> Open the Excel file matching the barcode ID above, OR scan the QR Code using the Faculty Portal to instantly ingest the dummy-to-USN mapping.", styles['Normal']))
        elements.append(PageBreak())
        
    doc.build(elements, onFirstPage=get_header_drawer(assets), onLaterPages=get_header_drawer(assets))
    return buf.getvalue()

def gen_hybrid_bundles(df_seating, date_post, sess_post, cycle_id, cycle_name, assets):
    """
    The Ultimate Hybrid Engine:
    1. Reverts to AA1, AB2 Dummy generation.
    2. Packages formulated Excel sheets for immediate faculty use.
    3. Generates QR Code PDF covers for the physical envelopes containing rich JSON data.
    4. Writes everything to Supabase for the upcoming Web Portal.
    """
    global USED_PREFIXES
    USED_PREFIXES.clear() 
    
    zip_buf = io.BytesIO()
    key_log = []
    bundles_payload = []
    scripts_payload = []
    cover_sheet_data = []

    def get_bundle_group(row):
        usn = str(row['USN']).strip().upper()
        branch = str(row['Branch']).strip().upper()
        if branch == 'CS' or 'CS' in usn:
            if usn.startswith('1AX'): return 'CS_1AX'
            else: return 'CS_1AM'
        return branch 

    df_bundles = df_seating.copy()
    df_bundles['BundleGroup'] = df_bundles.apply(get_bundle_group, axis=1)

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        
        for (cc, b_group), group in df_bundles.groupby(['Subject Code', 'BundleGroup']):
            course_name = group['Subject Name'].iloc[0]
            group = group.sort_values('USN').reset_index(drop=True)
            n_chunks = math.ceil(len(group) / 20)
            
            for i in range(n_chunks):
                chunk = group.iloc[i*20 : (i+1)*20].copy()
                
                # 🟢 RESTORED: Generate Familiar AA1, AA2 dummy IDs
                dummy_ids = generate_dummy_ids(len(chunk))
                chunk['Dummy_ID'] = dummy_ids
                
                # The Envelope Barcode (BNDL-XXXX)
                bndl_num = random.randint(10000, 99999)
                bundle_id = f"BNDL-{bndl_num}"
                
                bundles_payload.append({
                    "bundle_id": bundle_id,
                    "cycle_id": cycle_id,
                    "exam_date": date_post,
                    "course_code": cc,
                    "total_scripts": len(chunk),
                    "status": "CREATED"
                })
                
                bundle_scripts_info = []
                
                for _, s in chunk.iterrows():
                    scripts_payload.append({
                        "dummy_id": s['Dummy_ID'],
                        "bundle_id": bundle_id,
                        "usn": s['USN'],
                        "status": s['Status']
                    })
                    
                    bundle_scripts_info.append({"dummy_id": s['Dummy_ID'], "status": s['Status'], "usn": s['USN']})
                    
                    key_log.append({
                        'Bundle_Barcode': bundle_id, 
                        'Original_Room': s.get('RoomNo', 'N/A'), 
                        'USN': s['USN'], 
                        'Subject': cc, 
                        'Branch_Group': b_group,
                        'Dummy_ID': s['Dummy_ID'], 
                        'Status': s['Status']
                    })
                    
                cover_sheet_data.append({
                    "bundle_id": bundle_id,
                    "course_code": cc,
                    "course_name": course_name,
                    "exam_date": date_post,
                    "session": sess_post,
                    "scripts": bundle_scripts_info
                })
                
                # 🟢 GENERATE EXCEL FILE (For immediate use)
                excel_bytes = create_locked_bundle(chunk, cc, course_name, b_group, i+1, n_chunks, cycle_name, assets)
                zf.writestr(f"Excel_Bundles/{cc}/{bundle_id}_{b_group}.xlsx", excel_bytes)
                
        # 🟢 GENERATE PDF QR COVERS
        pdf_bytes = gen_barcode_bundle_covers(cover_sheet_data, cycle_name, assets)
        zf.writestr(f"QR_Envelope_Covers_{date_post}.pdf", pdf_bytes)
        
        # 🟢 GENERATE MASTER SECRET KEY
        kdf = pd.DataFrame(key_log)
        out_k = io.BytesIO()
        kdf.to_excel(out_k, index=False)
        zf.writestr("MASTER_SECRET_KEY.xlsx", out_k.getvalue())
        
    return zip_buf.getvalue(), bundles_payload, scripts_payload


# ==========================================
# 6. LIVE EXAM DAY UI FLOW (Decoupled)
# ==========================================

if not selected_cycle_id:
    st.warning("⚠️ Please select an Active Exam Cycle in the Sidebar to proceed.")
    st.stop()

pdf_assets = load_pdf_assets()

st.title("🚀 Exam Logistics & Bundling")

try:
    cycle_info = supabase.table("exam_cycles").select("exam_type").eq("cycle_id", selected_cycle_id).execute()
    active_exam_type = cycle_info.data[0]['exam_type'] if cycle_info.data else 'Regular'
except:
    active_exam_type = 'Regular'

sessions = fetch_exam_sessions(selected_cycle_id)
if not sessions:
    st.error("No timetable records found for this cycle.")
    st.stop()

tab1, tab2 = st.tabs(["📌 Phase 1: Pre-Exam (Seating)", "📦 Phase 2: Post-Exam (Attendance & Bundling)"])

# ==========================================
# TAB 1: PRE-EXAM LOGISTICS (Rooms & Seating)
# ==========================================
with tab1:
    st.subheader("Room Allocation & Form B")
    selected_slot_pre = st.selectbox("📅 Select Session for Seating:", sessions, key="slot_pre")
    date_pre, sess_pre = selected_slot_pre.split(" | ")
    
    # Check if seating is already saved
    existing_seating = fetch_seating_allocation(selected_cycle_id, date_pre, sess_pre)
    
    if not existing_seating.empty:
        st.success(f"✅ Seating layout already generated for this session! ({len(existing_seating)} students)")
        
        # 🟢 RESTORED: All 4 Download Buttons
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.download_button("📌 Download Room Posters", gen_posters(existing_seating, date_pre, sess_pre, pdf_assets), f"Posters_{date_pre}.pdf", type="primary", use_container_width=True)
        with c2: st.download_button("📝 Download Form B (Attendance)", gen_form_b(existing_seating, date_pre, sess_pre, pdf_assets), f"FormB_{date_pre}.pdf", type="primary", use_container_width=True)
        with c3: st.download_button("📋 Download QPDS (Indent)", gen_qpds(existing_seating, date_pre, sess_pre, pdf_assets), f"QPDS_{date_pre}.pdf", type="primary", use_container_width=True)
        with c4: st.download_button("📊 Download Appearing List", gen_smart_excel(existing_seating, date_pre, sess_pre), f"Appearing_{date_pre}.xlsx", type="primary", use_container_width=True)
        
        st.divider()
        if st.button("⚠️ Delete Seating & Re-Run Allocation", type="secondary"):
            supabase.table("exam_seating_allocations").delete().eq("cycle_id", selected_cycle_id).eq("exam_date", date_pre).eq("session", sess_pre).execute()
            st.rerun()
            
    else:
        df_stus = fetch_exam_data(selected_cycle_id, date_pre, sess_pre, exam_type=active_exam_type)
        df_rooms_master = fetch_rooms()

        if df_stus.empty:
            st.error("No registered students found for this session.")
        elif df_rooms_master.empty:
            st.error("No rooms defined in Infrastructure master.")
        else:
            total_students = len(df_stus)
            st.info(f"👨‍🎓 **Total Students to Allocate:** {total_students}")
            
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
                
                if st.form_submit_button("⚙️ Run Algorithm & Save Seating", type="primary"):
                    if selected_capacity < total_students:
                        st.error("⚠️ Not enough capacity! Please select more rooms.")
                    else:
                        with st.spinner("Assigning seats & writing to database..."):
                            df_alloc = run_allocation(df_stus, selected_rooms_df)
                            
                            # Prepare for DB Insert
                            payload = []
                            for _, row in df_alloc.iterrows():
                                payload.append({
                                    "cycle_id": selected_cycle_id,
                                    "exam_date": date_pre,
                                    "session": sess_pre,
                                    "usn": row['USN'],
                                    "student_name": row['Student Name'],
                                    "branch": row['Branch'],
                                    "course_code": row['Subject Code'],
                                    "course_name": row['Subject Name'],
                                    "room_no": row['RoomNo'],
                                    "seat_no": row['SeatNo'],
                                    "status": "PRESENT"
                                })
                                
                            try:
                                # Chunking insert for large arrays
                                for i in range(0, len(payload), 500):
                                    supabase.table("exam_seating_allocations").insert(payload[i:i+500]).execute()
                                st.success(f"✅ Seating successfully locked into database!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Database error: {e}")

# ==========================================
# TAB 2: POST-EXAM LOGISTICS (Attendance & Bundling)
# ==========================================
with tab2:
    st.subheader("Attendance & Secure Pocket Coding")
    selected_slot_post = st.selectbox("📅 Select Completed Session:", sessions, key="slot_post")
    date_post, sess_post = selected_slot_post.split(" | ")
    
    post_seating = fetch_seating_allocation(selected_cycle_id, date_post, sess_post)
    
    if post_seating.empty:
        st.warning("⚠️ Seating has not been generated for this session yet. Please go to Phase 1.")
    else:
        st.info("Mark any Absentees or Malpractice cases below before generating Form A or Evaluation Bundles.")
        
        with st.form("absentee_form"):
            col1, col2 = st.columns(2)
            with col1:
                # Pre-fill with existing absentees if already saved
                existing_abs = post_seating[post_seating['Status'] == 'ABSENT']['USN'].tolist()
                abs_text = st.text_area("Absentee USNs (comma separated)", value=",".join(existing_abs), height=80)
            with col2:
                existing_mal = post_seating[post_seating['Status'] == 'MALPRACTICE']['USN'].tolist()
                mal_text = st.text_area("Malpractice USNs (comma separated)", value=",".join(existing_mal), height=80)
                
            if st.form_submit_button("💾 Lock Attendance", type="primary"):
                absent_list = [x.strip().upper() for x in abs_text.replace('\n', ',').split(',') if x.strip()]
                mal_list = [x.strip().upper() for x in mal_text.replace('\n', ',').split(',') if x.strip()]
                
                with st.spinner("Updating database..."):
                    # Reset all to present first
                    supabase.table("exam_seating_allocations").update({"status": "PRESENT"}).eq("cycle_id", selected_cycle_id).eq("exam_date", date_post).eq("session", sess_post).execute()
                    
                    # Update Absentees
                    if absent_list:
                        supabase.table("exam_seating_allocations").update({"status": "ABSENT"}).eq("cycle_id", selected_cycle_id).eq("exam_date", date_post).eq("session", sess_post).in_("usn", absent_list).execute()
                    
                    # Update Malpractice
                    if mal_list:
                        supabase.table("exam_seating_allocations").update({"status": "MALPRACTICE"}).eq("cycle_id", selected_cycle_id).eq("exam_date", date_post).eq("session", sess_post).in_("usn", mal_list).execute()
                        
                st.success("✅ Attendance Locked!")
                st.rerun()

        st.download_button("📦 Download Form A (Based on Locked Attendance)", gen_form_a(post_seating, date_post, sess_post, pdf_assets, active_cycle_name), f"FormA_{date_post}.pdf", use_container_width=True)
        
        st.divider()
        st.subheader("Hybrid Database & Excel Bundling")
        st.write("Generates formulated Excel Files for your current process, printable QR Code covers, AND writes everything to the database for the upcoming Web App.")
        
        # Check if bundles exist
        existing_bundles = supabase.table("evaluation_bundles").select("bundle_id").eq("cycle_id", selected_cycle_id).eq("exam_date", date_post).execute()
        
        if existing_bundles.data:
            st.success(f"✅ Secure bundles have already been created for this session in the database!")
            st.warning("If you need to regenerate the Excel sheets, you must contact the DB Admin to clear the existing bundles for this session first.")
        else:
            if st.button("🚀 Generate Hybrid Bundles (ZIP)", type="primary"):
                with st.spinner("Building Excels, QR Codes, and locking to Database..."):
                    
                    df_to_bundle = post_seating.copy()
                    
                    # Run the Hybrid Engine
                    zip_bytes, b_payload, s_payload = gen_hybrid_bundles(df_to_bundle, date_post, sess_post, selected_cycle_id, active_cycle_name, pdf_assets)
                    
                    try:
                        # Write to database (Background process for future app)
                        for i in range(0, len(b_payload), 500):
                            supabase.table("evaluation_bundles").insert(b_payload[i:i+500]).execute()
                        for i in range(0, len(s_payload), 500):
                            supabase.table("evaluation_scripts").insert(s_payload[i:i+500]).execute()
                            
                        st.success("✅ Bundles successfully locked in database and ZIP generated!")
                        st.download_button(
                            label="📥 Download Master ZIP (Excels, QR Covers, Master Key)", 
                            data=zip_bytes, 
                            file_name=f"Hybrid_Evaluation_Bundles_{date_post}.zip", 
                            type="primary", 
                            use_container_width=True
                        )
                        
                    except Exception as e:
                        st.error(f"Error saving bundles to database: {e}")

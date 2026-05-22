import streamlit as st
import pandas as pd
import io
import datetime
import hashlib
import os
import re
import concurrent.futures
from PIL import Image as PILImage  
from utils import init_db
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, Paragraph, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader

# ==========================================
# 1. SETUP
# ==========================================
LOGO_FILENAME = "College_logo.png"       
NAAC_FILENAME = "NAAC_A_Logo.jpg"        
WATERMARK_FILENAME = "AMC_watermark.png" 
supabase = init_db()

st.title("🖨️ Pre-Exam Operations & Hall Tickets")

# --- GLOBAL CONTEXT ---
selected_cycle_id = st.session_state.get('active_cycle_id')
active_cycle_name = st.session_state.get('active_cycle_name', 'Unknown Cycle')

if not selected_cycle_id:
    st.warning("⚠️ Please select an Active Exam Cycle in the Sidebar to proceed.")
    st.stop()

def get_branch_code(usn):
    try:
        if len(usn) > 5:
            match = re.search(r'[A-Za-z]+', usn[5:])
            if match:
                return match.group(0).upper()
    except: pass
    return "GEN"

def generate_app_id(usn, cycle_id):
    h = hashlib.md5(f"{usn}{cycle_id}{datetime.date.today()}".encode()).hexdigest()[:6].upper()
    return f"AMC-26-{h}"

def get_sem_num(sem_val):
    """Safely extracts the numeric semester value to evaluate Regular vs Arrear"""
    try:
        return int(re.search(r'\d+', str(sem_val)).group())
    except:
        return 99

def fetch_all_records(table, columns="*", filter_col=None, filter_val=None):
    rows = []
    start = 0; step = 1000
    while True:
        query = supabase.table(table).select(columns)
        if filter_col and filter_val:
            query = query.eq(filter_col, filter_val)
            
        res = query.range(start, start+step-1).execute()
        if not res.data: break
        rows.extend(res.data)
        if len(res.data) < step: break
        start += step
    return rows

# ==========================================
# 2. BULLETPROOF PHOTO LOGIC
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
                if not fname or fname == '.emptyFolderPlaceholder': 
                    continue
                
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
# 3. DATA FETCHING UTILS
# ==========================================
def fetch_branches_map():
    branch_map = {}
    try:
        res = supabase.table("master_branches").select("branch_code, program_type, degree_type, branch_name").execute()
        for r in res.data:
            branch_map[r['branch_code']] = r
    except: pass
    return branch_map

def fetch_timetable_map(target_cycle_id):
    tt_map = {}
    try:
        if not target_cycle_id: return {}
        res = supabase.table("exam_timetable").select("course_code, exam_date, session").eq("cycle_id", target_cycle_id).execute()
        for row in res.data:
            c_code = row.get('course_code')
            raw_date = row.get('exam_date')
            raw_session = row.get('session')
            fmt_date = raw_date
            try:
                if raw_date: fmt_date = datetime.datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d-%m-%Y")
            except: pass
            fmt_session = raw_session
            if raw_session:
                if "Afternoon" in raw_session: fmt_session = "2:00 PM - 5:00 PM"
                elif "Morning" in raw_session: fmt_session = "9:30 AM - 12:30 PM"
            tt_map[c_code] = {"date": fmt_date if fmt_date else "TBD", "session": fmt_session if fmt_session else "TBD"}
    except: pass
    return tt_map

def fetch_course_eligibility_map():
    eligibility_map = {}
    try:
        res = supabase.table("master_courses").select("course_code, max_see").execute()
        for row in res.data:
            max_see = row.get('max_see')
            is_eligible = False
            if max_see is not None:
                try:
                    if float(max_see) > 0: is_eligible = True
                except: pass
            eligibility_map[row['course_code']] = is_eligible
    except: pass
    return eligibility_map

def sort_subjects_by_timetable(subs, timetable_map):
    def get_date(sub):
        date_str = timetable_map.get(sub['code'], {}).get('date', 'TBD')
        if date_str == 'TBD' or not date_str:
            return datetime.datetime(2099, 1, 1)
        try:
            return datetime.datetime.strptime(date_str, "%d-%m-%Y")
        except:
            return datetime.datetime(2099, 1, 1)
    return sorted(subs, key=get_date)

def draw_header(c, w, y_start, assets, is_hall_ticket=False):
    if assets.get("logo"):
        c.drawImage(ImageReader(assets["logo"]), 35, y_start - 35, width=60, height=60, mask='auto', preserveAspectRatio=True)
    if assets.get("naac"):
        if is_hall_ticket:
            c.drawImage(ImageReader(assets["naac"]), w - 85, y_start - 30, width=50, height=50, mask='auto', preserveAspectRatio=True)
        else:
            c.drawImage(ImageReader(assets["naac"]), w - 95, y_start - 35, width=60, height=60, mask='auto', preserveAspectRatio=True)

    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(w/2, y_start, "AMC ENGINEERING COLLEGE")
    c.setFont("Helvetica", 9)
    c.drawCentredString(w/2, y_start - 15, "AMC Campus, Bannerghatta Road, Bengaluru, Karnataka - 560083")
    c.drawCentredString(w/2, y_start - 27, "Autonomous Institution Affiliated to VTU, Belagavi")
    c.drawCentredString(w/2, y_start - 39, "Approved by AICTE, New Delhi | NAAC A+ Accredited")
    c.setLineWidth(1)
    c.line(30, y_start - 50, w - 30, y_start - 50)
    return y_start - 70

# ==========================================
# 4. PDF ENGINE (DYNAMIC LAYOUT)
# ==========================================
def draw_application_page(c, w, h, student, subjects, fees, assets, app_id, cycle_name, photo_bytes_io, prog_type, db_branch_code, branch_name_str):
    if assets.get("watermark"):
        c.saveState(); c.setFillAlpha(0.08)
        c.drawImage(ImageReader(assets["watermark"]), w/2 - 175, h/2 - 175, width=350, height=350, mask='auto', preserveAspectRatio=True)
        c.restoreState()

    y = draw_header(c, w, h - 30, assets, is_hall_ticket=False)
    c.setFont("Helvetica-Bold", 11)
    
    c.drawCentredString(w/2, y, f"Examination Application Form - {cycle_name}")
    y -= 25

    c.setFont("Helvetica-Bold", 10)
    c.drawString(30, y, "Student Details")
    y -= 5
    
    if photo_bytes_io:
        photo_bytes_io.seek(0)
        p_img = RLImage(photo_bytes_io, width=65, height=75)
        p_img.hAlign = 'CENTER'
        p_img.vAlign = 'MIDDLE'
    else:
        p_img = Paragraph("<para align=center>PHOTO</para>", getSampleStyleSheet()['Normal'])
    
    stu_sem_str = str(student.get('current_sem', '1'))
    stu_sem_num = get_sem_num(stu_sem_str)

    s_data = [
        ["USN", student['usn'], "Student Name", Paragraph(f"<b>{student['full_name']}</b>", getSampleStyleSheet()['Normal']), p_img],
        ["Semester", stu_sem_str, "Student Type", prog_type, ""],
        ["Branch Code", db_branch_code, "Programme", Paragraph(f"<b>{branch_name_str}</b>", getSampleStyleSheet()['Normal']), ""]
    ]
    
    t1 = Table(s_data, colWidths=[85, 85, 80, 205, 80], rowHeights=28)
    t1.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'), 
        ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'), 
        ('BACKGROUND', (0,0), (0,-1), colors.lightgrey), 
        ('BACKGROUND', (2,0), (2,-1), colors.lightgrey), 
        ('SPAN', (4,0), (4,2)), 
        ('VALIGN', (4,0), (4,2), 'MIDDLE'),
        ('ALIGN', (4,0), (4,2), 'CENTER'),
        ('ALIGN', (1,0), (1,2), 'LEFT'),
        ('ALIGN', (3,0), (3,2), 'LEFT'), 
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), 
    ]))
    t1.wrapOn(c, w, h)
    _, th1 = t1.wrap(w, h)
    t1.drawOn(c, 30, y - th1)
    y -= (th1 + 20)
    
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30, y, f"Application ID: {app_id}")
    c.drawRightString(w - 30, y, f"Application Date: {datetime.date.today().strftime('%d-%m-%Y')}")
    y -= 25

    c.setFont("Helvetica-Bold", 10); c.drawString(30, y, "Regular & Arrear Subjects"); y -= 10
    
    # 🟢 NEW LOGIC: Sort Application form by Regulars First, Arrears Second
    regular_subs = []
    arrear_subs = []
    
    for s in subjects:
        sub_sem_str = str(s.get('sem', '-'))
        sub_sem_num = get_sem_num(sub_sem_str)
        if sub_sem_num < stu_sem_num:
            arrear_subs.append(s)
        else:
            regular_subs.append(s)
            
    arrear_count = len(arrear_subs)
    regular_count = len(regular_subs)

    sub_rows = [["Sem", "Course Code", "Course Title", "Type"]]
    
    for s in regular_subs:
        sub_rows.append([str(s.get('sem', '-')), s['code'], Paragraph(s['title'], getSampleStyleSheet()['Normal']), "Regular"])
    for s in arrear_subs:
        sub_rows.append([str(s.get('sem', '-')), s['code'], Paragraph(s['title'], getSampleStyleSheet()['Normal']), "Arrear"])
    
    row_h = 16 if len(subjects) > 10 else None
    
    t2 = Table(sub_rows, colWidths=[40, 80, 335, 80], rowHeights=row_h)
    t2.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (3,0), colors.lightgrey),
        ('ALIGN', (0,0), (0,-1), 'CENTER'),
        ('ALIGN', (3,0), (3,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('FONTSIZE', (0,0), (-1,-1), 8 if len(subjects) > 10 else 9), 
    ]))
    t2.wrapOn(c, w, h)
    _, th2 = t2.wrap(w, h)
    t2.drawOn(c, 30, y - th2)
    y -= (th2 + 20) 

    c.setFont("Helvetica-Bold", 10); c.drawString(30, y, "Fee Details"); y -= 5
    
    base_exam_fee = float(fees.get('Exam', 2000))
    fee_exam = base_exam_fee if regular_count > 0 else 0.0  
    
    fee_arrear_per_sub = float(fees.get('Arrear', 0))
    fee_arrear_total = fee_arrear_per_sub * arrear_count
    
    fee_penalty = float(fees.get('Penalty', 0))
    fee_misc = float(fees.get('Misc', 400))
    
    total = fee_exam + fee_arrear_total + fee_penalty + fee_misc
    
    f_rows = [
        ["Description", "Amount (Rs)"],
        ["Regular Examination Fees", f"{fee_exam:.2f}"],
        [f"Arrear Examination Fees ({arrear_count} x {fee_arrear_per_sub:.2f})", f"{fee_arrear_total:.2f}"],
        ["Penalty Fees", f"{fee_penalty:.2f}"],
        ["Application & Marks Card Fees", f"{fee_misc:.2f}"],
        ["TOTAL AMOUNT", f"{total:.2f}"]
    ]
    
    t3 = Table(f_rows, colWidths=[435, 100], rowHeights=16 if len(subjects) > 10 else None)
    t3.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('FONTNAME', (-1,-1), (-1,-1), 'Helvetica-Bold'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('FONTSIZE', (0,0), (-1,-1), 8 if len(subjects) > 10 else 9)
    ]))
    t3.wrapOn(c, w, h)
    _, th3 = t3.wrap(w, h)
    t3.drawOn(c, 30, y - th3)
    y -= (th3 + 25) 

    c.rect(30, y - 25, w - 60, 25)
    c.setFont("Helvetica", 9)
    c.drawString(40, y - 17, "Receipt No: ______________________")
    c.drawString(350, y - 17, "Date: ______________________")
    y -= 40

    c.setFont("Helvetica-Bold", 10); c.drawString(30, y, "Declaration:"); y -= 15
    decl = "The subjects listed in this application are the only subjects I wish to apply for this Examination. I understand this application overrides any previous submission."
    p = Paragraph(decl, getSampleStyleSheet()['Normal']); p.wrapOn(c, w - 60, 50); p.drawOn(c, 30, y - 25)
    
    y -= 40
    c.setFont("Helvetica-Bold", 9); c.drawRightString(w - 30, y, "Signature of the Candidate")
    
    c.setFont("Helvetica", 8)
    c.drawRightString(w - 30, y - 12, "Contact No: ___________________________")
    c.drawRightString(w - 30, y - 24, "Email ID:   ___________________________")


def draw_hall_ticket_half(c, w, base_y, student, subjects, section, app_id, assets, cycle_name, photo_bytes_io, timetable_map, eligibility_map, header_branch, branch_name_str):
    HALF_HEIGHT = 420.94 # Exact half of A4 height (841.89)
    
    if assets.get("watermark"):
        c.saveState(); c.setFillAlpha(0.08)
        c.drawImage(ImageReader(assets["watermark"]), w/2 - 140, base_y + (HALF_HEIGHT/2) - 140, width=280, height=280, mask='auto', preserveAspectRatio=True)
        c.restoreState()

    y = draw_header(c, w, base_y + HALF_HEIGHT - 20, assets, is_hall_ticket=True)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(w/2, y + 5, f"Admission Ticket - {cycle_name}")
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(w - 40, y - 5, f"[{section}]")
    y -= 15 

    compact_style = getSampleStyleSheet()['Normal'].clone('Compact')
    compact_style.fontName = 'Helvetica-Bold'
    compact_style.fontSize = 7.5
    compact_style.leading = 8.5
    compact_style.alignment = 0 

    h_data = [
        ["USN:", student['usn'], "Name:", Paragraph(f"{student['full_name']}", compact_style)],
        ["App ID:", app_id, "Date:", datetime.date.today().strftime('%d-%m-%Y')],
        ["Semester:", str(student.get('current_sem', '1')), "Programme:", Paragraph(f"{branch_name_str}", compact_style)],
        ["Center:", "AMC ENGINEERING COLLEGE", "", ""]
    ]
    
    t_text = Table(h_data, colWidths=[50, 90, 55, 280], rowHeights=14)
    t_text.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('SPAN', (1,3), (3,3)), 
        ('ALIGN', (1,0), (1,-1), 'LEFT'),
        ('ALIGN', (3,0), (3,-1), 'LEFT'),
        ('TOPPADDING', (0,0), (-1,-1), 1),    
        ('BOTTOMPADDING', (0,0), (-1,-1), 1), 
    ]))
    
    if photo_bytes_io:
        photo_bytes_io.seek(0)
        p_img2 = RLImage(photo_bytes_io, width=48, height=54)
        p_img2.hAlign = 'CENTER'
        p_img2.vAlign = 'MIDDLE'
    else:
        p_img2 = Paragraph("<para align=center>PHOTO</para>", compact_style)

    master_data = [[t_text, p_img2]]
    t_master = Table(master_data, colWidths=[475, 60])
    t_master.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'CENTER'),
        ('GRID', (1,0), (1,0), 0.5, colors.black),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    
    t_master.wrapOn(c, w, 500)
    _, h_mast = t_master.wrap(w, 500)
    t_master.drawOn(c, 30, y - h_mast)
    
    y -= (h_mast + 15) 
    c.setFont("Helvetica-Bold", 9)
    c.drawString(30, y, "Exam Schedule:")
    y -= 8 
    
    valid_subs = [s for s in subjects if eligibility_map.get(s['code'], False)]
    
    # 🟢 CHANGED THRESHOLD: 10 or more subjects now trigger the side-by-side layout
    if len(valid_subs) >= 10:
        mid = (len(valid_subs) + 1) // 2
        left_subs = valid_subs[:mid]
        right_subs = valid_subs[mid:]
        
        left_data = [["Date", "Session", "Sem", "Course Code", "Sign"]]
        for s in left_subs:
            sch = timetable_map.get(s['code'], {"date": "", "session": ""})
            left_data.append([sch['date'], sch['session'], str(s.get('sem', '-')), s['code'], ""])
            
        right_data = [["Date", "Session", "Sem", "Course Code", "Sign"]]
        for s in right_subs:
            sch = timetable_map.get(s['code'], {"date": "", "session": ""})
            right_data.append([sch['date'], sch['session'], str(s.get('sem', '-')), s['code'], ""])
            
        while len(right_data) < len(left_data):
            right_data.append(["", "", "", "", ""])
            
        split_style = TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('FONTSIZE', (0,0), (-1,-1), 7),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('TOPPADDING', (0,0), (-1,-1), 1),
            ('BOTTOMPADDING', (0,0), (-1,-1), 1),
        ])
        
        t_left = Table(left_data, colWidths=[50, 80, 25, 55, 45], rowHeights=13)
        t_left.setStyle(split_style)
        
        t_right = Table(right_data, colWidths=[50, 80, 25, 55, 45], rowHeights=13)
        t_right.setStyle(split_style)
        
        tg = Table([[t_left, t_right]], colWidths=[260, 260])
        tg.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
        ]))
        
        tg.wrapOn(c, w, 500)
        _, gh = tg.wrap(w, 500)
        tg.drawOn(c, 30, y - gh)

    else:
        # SINGLE TABLE LOGIC (1 to 9 subjects)
        grid_data = [["Date", "Session", "Sem", "Course Code", "Invigilator Sign"]]
        
        for s in valid_subs:
            sch = timetable_map.get(s['code'], {"date": "", "session": ""})
            grid_data.append([sch['date'], sch['session'], str(s.get('sem', '-')), s['code'], ""])

        MIN_ROWS = 8
        if (len(grid_data) - 1) < MIN_ROWS:
            for _ in range(MIN_ROWS - (len(grid_data) - 1)):
                grid_data.append(["", "", "", "", ""])

        total_rows = len(grid_data)
        # Optimized stretching for max 9 subjects
        if total_rows <= 8:
            row_h = 18   
        else:
            row_h = 15   

        tg = Table(grid_data, colWidths=[75, 120, 35, 85, 220], rowHeights=row_h)
        tg.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('TOPPADDING', (0,0), (-1,-1), 2),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))
        tg.wrapOn(c, w, 500)
        _, gh = tg.wrap(w, 500)
        tg.drawOn(c, 30, y - gh)
    
    # 2. PIN THE SIGNATURES TO THE ABSOLUTE BOTTOM OF THE BOUNDING BOX
    footer_y = base_y + 20 
    
    c.setFont("Helvetica", 7)
    c.drawString(30, footer_y + 45, "Candidate must read the instructions provided in the answer booklet, before the commencement of examination.")
    
    c.setLineWidth(0.5)
    c.setFont("Helvetica-Bold", 9)
    sig_w = 80
    
    # Signatures lines and text
    c.line(40, footer_y + 25, 40 + sig_w, footer_y + 25)
    c.drawCentredString(40 + sig_w/2, footer_y + 15, "Candidate")
    
    c.line(w/2 - sig_w/2, footer_y + 25, w/2 + sig_w/2, footer_y + 25)
    c.drawCentredString(w/2, footer_y + 15, "CoE")
    
    c.line(w - 40 - sig_w, footer_y + 25, w - 40, footer_y + 25)
    c.drawCentredString(w - 40 - sig_w/2, footer_y + 15, "Principal")
    
    # Note at the very bottom
    c.setFont("Helvetica-Oblique", 7)
    c.drawCentredString(w/2, footer_y, "Note: Please verify the eligibility of candidate before issuing the admission ticket.")
    
    return y - 10
# ==========================================
# 5. APP MAIN LOGIC
# ==========================================
tabs = st.tabs(["💰 Fees", "🚀 Bulk Generator", "📄 Individual"])

with tabs[0]:
    st.info(f"Setting fees for cycle: **{active_cycle_name}**")
    with st.form("fees"):
        c1, c2 = st.columns(2)
        e = c1.number_input("Regular Fee", 2000.0)
        a = c2.number_input("Arrear Fee (Per Subject)", 0.0) 
        p = c1.number_input("Penalty", 0.0)
        m = c2.number_input("App & Marks Card Fee (Misc)", value=400.0)
        
        if st.form_submit_button("Save Fees"):
            supabase.table("master_fees").upsert([{"fee_type":k, "amount":v} for k,v in [("Exam",e),("Arrear",a),("Penalty",p),("Misc",m)]]).execute()
            st.success("Fees Saved.")

with tabs[1]:
    st.subheader(f"Bulk Generator: {active_cycle_name}")
    if st.button("🚀 Generate All Documents (Single PDF)"):
        with st.spinner("Step 1: Indexing Data..."):
            system_assets = {"logo": None, "naac": None, "watermark": None}
            sys_map = {"logo": LOGO_FILENAME, "naac": NAAC_FILENAME, "watermark": WATERMARK_FILENAME}
            for k, f in sys_map.items():
                try:
                    res = supabase.storage.from_("College_Logos").download(f)
                    if res: system_assets[k] = io.BytesIO(res) 
                except: pass
            
            photo_file_map = fetch_complete_bucket_map("StakeHolders_Photos")
            timetable_map = fetch_timetable_map(selected_cycle_id)
            eligibility_map = fetch_course_eligibility_map()
            branch_map = fetch_branches_map()
            
            fee_res = supabase.table("master_fees").select("*").execute()
            fees = {f['fee_type']: f['amount'] for f in fee_res.data}

            all_students = fetch_all_records("master_students")
            
            all_regs = fetch_all_records("course_registrations", "usn, course_code, semester, master_courses(title, semester_id)", "cycle_id", selected_cycle_id)
            
            course_map = {}
            for r in all_regs:
                usn = r['usn']
                if usn not in course_map: course_map[usn] = []
                
                mc = r.get('master_courses') or {}
                title = mc.get('title', "Unknown Title")
                
                sem = r.get('semester')
                if not sem:
                    sem = mc.get('semester_id', '-')
                    
                course_map[usn].append({"code": r['course_code'], "title": title, "sem": sem})
                
            usns = list(course_map.keys())

        if not usns:
            st.warning("No student registrations found for this cycle.")
        else:
            progress_bar = st.progress(0); status = st.empty()
            final_pdf_buffer = io.BytesIO(); c = canvas.Canvas(final_pdf_buffer, pagesize=A4)
            total = len(usns)
            
            BATCH_SIZE = 50 
            for i in range(0, total, BATCH_SIZE):
                batch_usns = usns[i : i + BATCH_SIZE]
                status.text(f"Processing Batch {i//BATCH_SIZE + 1} ({min(i+BATCH_SIZE, total)}/{total} students)...")
                
                batch_photos = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {executor.submit(download_photo_worker, (u, photo_file_map)): u for u in batch_usns}
                    for future in concurrent.futures.as_completed(futures):
                        u, p_stream = future.result()
                        if p_stream: batch_photos[u] = p_stream

                for u in batch_usns:
                    stu = next((s for s in all_students if s['usn'] == u), None)
                    if not stu: continue
                    raw_subs = course_map.get(u, [])
                    photo_stream = batch_photos.get(u)
                    
                    unique_subs = []
                    seen_codes = set()
                    for sub in raw_subs:
                        if sub['code'] not in seen_codes:
                            unique_subs.append(sub)
                            seen_codes.add(sub['code'])
                    
                    subs = sort_subjects_by_timetable(unique_subs, timetable_map)
                    
                    db_branch_code = stu.get('branch_code', get_branch_code(u))
                    
                    b_info = branch_map.get(db_branch_code, {"program_type": "UG", "branch_name": db_branch_code})
                    prog_type = b_info.get("program_type", "UG")
                    b_name_str = b_info.get("branch_name", db_branch_code)
                    
                    app_id = generate_app_id(u, selected_cycle_id)
                    draw_application_page(c, A4[0], A4[1], stu, subs, fees, system_assets, app_id, active_cycle_name, photo_stream, prog_type, db_branch_code, b_name_str)
                    c.showPage()
                    
                    # 🟢 Absolute Positioning for Bulk Tickets
                    HALF_A4 = 841.89 / 2
                    draw_hall_ticket_half(c, A4[0], HALF_A4, stu, subs, "STUDENT COPY", app_id, system_assets, active_cycle_name, photo_stream, timetable_map, eligibility_map, db_branch_code, b_name_str)
                    
                    c.setDash(4, 4)
                    c.line(20, HALF_A4, A4[0]-20, HALF_A4)
                    c.setDash([])
                    
                    draw_hall_ticket_half(c, A4[0], 0, stu, subs, "COLLEGE COPY", app_id, system_assets, active_cycle_name, photo_stream, timetable_map, eligibility_map, db_branch_code, b_name_str)
                    c.showPage()
                
                progress_bar.progress(min((i + BATCH_SIZE) / total, 1.0))
                for stream in batch_photos.values(): stream.close()
                batch_photos.clear() 

            c.save(); status.text("Bulk Generation Complete.")
            st.download_button("📥 Download PDF Bundle", final_pdf_buffer.getvalue(), f"Bulk_Docs_{active_cycle_name}.pdf", "application/pdf")

with tabs[2]:
    st.write("### Single Student Generator")
    
    col1, col2 = st.columns([3, 1])
    target_usn = col1.text_input("Enter USN to Generate:").strip().upper()
    
    if target_usn and st.button("Generate Document"):
        with st.spinner("Fetching Data..."):
            try:
                system_assets = {"logo": None, "naac": None, "watermark": None}
                sys_map = {"logo": LOGO_FILENAME, "naac": NAAC_FILENAME, "watermark": WATERMARK_FILENAME}
                for k, f in sys_map.items():
                    try:
                        res = supabase.storage.from_("College_Logos").download(f)
                        if res: system_assets[k] = io.BytesIO(res)
                    except: pass
                
                _, photo_stream = download_photo_worker((target_usn, fetch_complete_bucket_map("StakeHolders_Photos")))
                timetable_map = fetch_timetable_map(selected_cycle_id)
                eligibility_map = fetch_course_eligibility_map()
                branch_map = fetch_branches_map()

                stu_res = supabase.table("master_students").select("*").eq("usn", target_usn).execute()
                if not stu_res.data:
                    st.error(f"❌ Student {target_usn} not found.")
                    st.stop()
                stu = stu_res.data[0]

                sub_res = supabase.table("course_registrations")\
                    .select("course_code, semester, master_courses(title, semester_id)")\
                    .eq("usn", target_usn).eq("cycle_id", selected_cycle_id).execute()
                
                raw_subs = []
                for r in sub_res.data:
                    mc = r.get('master_courses') or {}
                    title = mc.get('title', "Unknown Title")
                    sem = r.get('semester')
                    if not sem:
                        sem = mc.get('semester_id', '-')
                    raw_subs.append({"code": r['course_code'], "title": title, "sem": sem})
                    
                unique_subs = []
                seen_codes = set()
                for sub in raw_subs:
                    if sub['code'] not in seen_codes:
                        unique_subs.append(sub)
                        seen_codes.add(sub['code'])
                        
                subs = sort_subjects_by_timetable(unique_subs, timetable_map)
                
                db_branch_code = stu.get('branch_code', get_branch_code(target_usn))
                
                b_info = branch_map.get(db_branch_code, {"program_type": "UG", "branch_name": db_branch_code})
                prog_type = b_info.get("program_type", "UG")
                b_name_str = b_info.get("branch_name", db_branch_code)
                    
                fee_res = supabase.table("master_fees").select("*").execute()
                fees = {f['fee_type']: f['amount'] for f in fee_res.data}
                
                if not subs:
                    st.error(f"No registrations found for {target_usn} in {active_cycle_name}.")
                else:
                    buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4)
                    app_id = generate_app_id(target_usn, selected_cycle_id)
                    
                    draw_application_page(c, A4[0], A4[1], stu, subs, fees, system_assets, app_id, active_cycle_name, photo_stream, prog_type, db_branch_code, b_name_str)
                    c.showPage()
                    
                    # 🟢 Absolute Positioning for Single Ticket
                    HALF_A4 = 841.89 / 2
                    
                    draw_hall_ticket_half(c, A4[0], HALF_A4, stu, subs, "STUDENT COPY", app_id, system_assets, active_cycle_name, photo_stream, timetable_map, eligibility_map, db_branch_code, b_name_str)
                    
                    c.setDash(4, 4)
                    c.line(20, HALF_A4, A4[0]-20, HALF_A4)
                    c.setDash([])
                    
                    draw_hall_ticket_half(c, A4[0], 0, stu, subs, "COLLEGE COPY", app_id, system_assets, active_cycle_name, photo_stream, timetable_map, eligibility_map, db_branch_code, b_name_str)
                    c.showPage(); c.save()
                    
                    st.download_button(f"📥 Download Docs for {target_usn}", buf.getvalue(), f"{target_usn}_ExamDocs.pdf")
            except Exception as e:
                st.error(f"Error: {e}")

import streamlit as st
import pandas as pd
import io
import datetime
import hashlib
import os
import concurrent.futures
from utils import init_db
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, Paragraph, Image
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
        if len(usn) > 7: return usn[5:7].upper()
    except: pass
    return "GEN"

def generate_app_id(usn, cycle_id):
    h = hashlib.md5(f"{usn}{cycle_id}{datetime.date.today()}".encode()).hexdigest()[:6].upper()
    return f"AMC-26-{h}"

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
# 2. HIGH-SPEED PHOTO LOGIC
# ==========================================

def fetch_complete_bucket_map(bucket_name):
    file_map = {}
    limit = 1000; offset = 0
    while True:
        try:
            files = supabase.storage.from_(bucket_name).list(path=None, options={"limit": limit, "offset": offset})
            if not files: break
            for f in files:
                key = os.path.splitext(f['name'])[0].upper().strip()
                file_map[key] = f['name']
            if len(files) < limit: break
            offset += limit
        except: break
    return file_map

def download_photo_worker(args):
    usn, file_map = args
    clean_usn = usn.strip().upper()
    filename = file_map.get(clean_usn)
    if not filename: filename = f"{clean_usn}.jpg"
    try:
        res = supabase.storage.from_("StakeHolders_Photos").download(filename)
        if res: return usn, io.BytesIO(res)
    except:
        try:
            res = supabase.storage.from_("StakeHolders_Photos").download(f"{clean_usn}.png")
            if res: return usn, io.BytesIO(res)
        except: pass
    return usn, None

# ==========================================
# 3. DATA FETCHING UTILS (CYCLE AWARE)
# ==========================================

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

# ==========================================
# 4. PDF ENGINE (EXACT ORIGINAL LAYOUT)
# ==========================================

def draw_header(c, w, y_start, assets):
    if assets.get("logo"):
        c.drawImage(ImageReader(assets["logo"]), 35, y_start - 35, width=60, height=60, mask='auto', preserveAspectRatio=True)
    if assets.get("naac"):
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

def draw_application_page(c, w, h, student, subjects, fees, assets, app_id, cycle_name, photo_bytes_io):
    if assets.get("watermark"):
        c.saveState(); c.setFillAlpha(0.08)
        c.drawImage(ImageReader(assets["watermark"]), w/2 - 175, h/2 - 175, width=350, height=350, mask='auto', preserveAspectRatio=True)
        c.restoreState()

    y = draw_header(c, w, h - 30, assets)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(w/2, y, f"Semester End Examination Application Form - {cycle_name}")
    y -= 25

    c.setFont("Helvetica-Bold", 10)
    c.drawString(30, y, "Student Details")
    y -= 5

    branch_code = get_branch_code(student['usn'])
    if photo_bytes_io:
        p_img = Image(photo_bytes_io, width=60, height=75)
    else:
        p_img = Paragraph("PHOTO", getSampleStyleSheet()['Normal'])

    name_para = Paragraph(f"<b>{student['full_name']}</b>", getSampleStyleSheet()['Normal'])

    s_data = [
        ["USN", student['usn'], "Student Name", name_para, p_img],
        ["Branch Code", branch_code, "Student Type", "UG", ""],
        ["Semester", "1", "", "", ""]
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
        ('ALIGN', (1,0), (1,2), 'LEFT'),
        ('ALIGN', (3,0), (3,2), 'LEFT'), 
        ('ALIGN', (4,0), (4,2), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), 
    ]))
    t1.wrapOn(c, w, h); t1.drawOn(c, 30, y - 90); y -= 110
    
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30, y, f"Application ID: {app_id}")
    c.drawRightString(w - 30, y, f"Application Date: {datetime.date.today().strftime('%d-%m-%Y')}")
    y -= 25

    c.setFont("Helvetica-Bold", 10); c.drawString(30, y, "Regular Subjects"); y -= 10
    sub_rows = [["Subject Code", "Subject Name", "Select"]]
    for s in subjects:
        sub_rows.append([s['code'], Paragraph(s['title'], getSampleStyleSheet()['Normal']), "Applied"])
    
    t2 = Table(sub_rows, colWidths=[90, 365, 80])
    t2.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (2,0), colors.lightgrey),
        ('ALIGN', (2,0), (2,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE')
    ]))
    t2.wrapOn(c, w, h); _, th = t2.wrap(w, h); t2.drawOn(c, 30, y - th); y -= (th + 30)

    c.setFont("Helvetica-Bold", 10); c.drawString(30, y, "Fee Details"); y -= 5
    total = sum([float(fees.get(k, 0)) for k in ['Exam', 'Arrear', 'Penalty', 'Misc']])
    if total == 0: total = 2400.00
    f_rows = [
        ["Description", "Amount (Rs)"],
        ["Regular Examination Fees", f"{float(fees.get('Exam', 2000)):.2f}"],
        ["Arrear Examination Fees", f"{float(fees.get('Arrear', 0)):.2f}"],
        ["Penalty Fees", f"{float(fees.get('Penalty', 0)):.2f}"],
        ["Application & Marks Card Fees", f"{float(fees.get('Misc', 400)):.2f}"],
        ["TOTAL AMOUNT", f"{total:.2f}"]
    ]
    t3 = Table(f_rows, colWidths=[435, 100])
    t3.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('FONTNAME', (-1,-1), (-1,-1), 'Helvetica-Bold'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT')
    ]))
    t3.wrapOn(c, w, h); t3.drawOn(c, 30, y - 110); y -= 135

    c.rect(30, y - 30, w - 60, 30)
    c.setFont("Helvetica", 10)
    c.drawString(40, y - 20, "Receipt No: ______________________")
    c.drawString(350, y - 20, "Date: ______________________")
    y -= 50

    c.setFont("Helvetica-Bold", 10); c.drawString(30, y, "Declaration:"); y -= 15
    decl = "The subjects listed in this application are the only subjects I wish to apply for this Examination. I understand this application overrides any previous submission."
    p = Paragraph(decl, getSampleStyleSheet()['Normal']); p.wrapOn(c, w - 60, 50); p.drawOn(c, 30, y - 25)
    c.setFont("Helvetica-Bold", 9); c.drawRightString(w - 30, y - 50, "Signature of the Candidate")

def draw_hall_ticket_half(c, w, y_start, student, subjects, section, app_id, assets, cycle_name, photo_bytes_io, timetable_map, eligibility_map):
    if assets.get("watermark"):
        c.saveState(); c.setFillAlpha(0.08)
        mid_y = y_start - 200
        c.drawImage(ImageReader(assets["watermark"]), w/2 - 150, mid_y - 150, width=300, height=300, mask='auto', preserveAspectRatio=True)
        c.restoreState()

    y = draw_header(c, w, y_start, assets)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(w/2, y - 10, f"Admission Ticket for B.E. Examination - {cycle_name}")
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(w - 40, y - 10, f"[{section}]")
    y -= 25 

    if photo_bytes_io:
        p_img = Image(photo_bytes_io, width=60, height=70)
    else:
        p_img = Paragraph("PHOTO", getSampleStyleSheet()['Normal'])

    name_para = Paragraph(f"<b>{student['full_name']}</b>", getSampleStyleSheet()['Normal'])
    h_data = [
        ["USN:", student['usn'], "Name:", name_para],
        ["App ID:", app_id, "Date:", datetime.date.today().strftime('%d-%m-%Y')],
        ["Center:", "AMC ENGINEERING COLLEGE", "", ""]
    ]
    
    t_text = Table(h_data, colWidths=[45, 95, 35, 290], rowHeights=None)
    t_text.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('SPAN', (1,2), (3,2)),
        ('ALIGN', (1,0), (1,-1), 'LEFT'),
        ('ALIGN', (3,0), (3,-1), 'LEFT'),
    ]))
    master_data = [[t_text, p_img]]
    t_master = Table(master_data, colWidths=[465, 70])
    t_master.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('GRID', (1,0), (1,0), 0.5, colors.black),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    t_master.wrapOn(c, w, 500); _, h_mast = t_master.wrap(w, 500); t_master.drawOn(c, 30, y - h_mast)
    y -= (h_mast + 5)

    c.setFont("Helvetica-Bold", 9); c.drawString(30, y, "Exam Schedule:"); y -= 8
    grid_data = [["Date", "Session", "Course Code", "Invigilator Sign"]]
    
    row_count = 0
    for s in subjects:
        code = s['code']
        if not eligibility_map.get(code, False): continue 
        sch = timetable_map.get(code, {"date": "", "session": ""})
        grid_data.append([sch['date'], sch['session'], code, ""])
        row_count += 1

    if row_count < 4:
        for _ in range(4 - row_count): grid_data.append(["", "", "", ""])

    tg = Table(grid_data, colWidths=[80, 130, 80, 245], rowHeights=16)
    tg.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
    ]))
    tg.wrapOn(c, w, 500); _, gh = tg.wrap(w, 500); tg.drawOn(c, 30, y - gh)
    y -= (gh + 10)

    c.setFont("Helvetica", 8)
    c.drawString(30, y, "Candidate must read the instructions provided in the answer booklet, before the commencement of examination.")
    y -= 25
    c.setLineWidth(0.5); c.line(30, y, w - 30, y); y -= 12 
    c.setFont("Helvetica-Bold", 9)
    sigs = ["Candidate", "HoD", "CoE", "Principal"]
    for j, sig in enumerate(sigs): c.drawString(30 + (j * 135), y, sig)
    y -= 12
    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(w/2, y, "Note: Please verify the eligibility of candidate before issuing the admission ticket.")

# ==========================================
# 5. APP MAIN LOGIC (PARALLEL BATCHES)
# ==========================================

tabs = st.tabs(["💰 Fees", "🚀 Bulk Generator", "📄 Individual"])

with tabs[0]:
    st.info(f"Setting fees for cycle: **{active_cycle_name}**")
    with st.form("fees"):
        c1, c2 = st.columns(2)
        e = c1.number_input("Regular Fee", 2000.0); a = c2.number_input("Arrear Fee", 0.0)
        p = c1.number_input("Penalty", 0.0); m = c2.number_input("Misc", 400.0)
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
            
            fee_res = supabase.table("master_fees").select("*").execute()
            fees = {f['fee_type']: f['amount'] for f in fee_res.data}

            # Fetch students
            all_students = fetch_all_records("master_students")
            
            # FIXED: Fetch ALL registrations for the specific cycle using the updated fetch_all_records
            all_regs = fetch_all_records("course_registrations", "usn, course_code, master_courses(title)", "cycle_id", selected_cycle_id)
            
            course_map = {}
            for r in all_regs:
                usn = r['usn']
                if usn not in course_map: course_map[usn] = []
                
                # Safely get title (handles if master_courses join is empty)
                title = r.get('master_courses', {}).get('title', "Unknown Title") if r.get('master_courses') else "Unknown Title"
                course_map[usn].append({"code": r['course_code'], "title": title})
                
            usns = list(course_map.keys())

        if not usns:
            st.warning("No student registrations found for this cycle.")
        else:
            progress_bar = st.progress(0); status = st.empty()
            final_pdf_buffer = io.BytesIO(); c = canvas.Canvas(final_pdf_buffer, pagesize=A4)
            total = len(usns)
            
            # --- PARALLEL BATCH PROCESSING ---
            BATCH_SIZE = 50 
            for i in range(0, total, BATCH_SIZE):
                batch_usns = usns[i : i + BATCH_SIZE]
                status.text(f"Processing Batch {i//BATCH_SIZE + 1} ({min(i+BATCH_SIZE, total)}/{total} students)...")
                
                batch_photos = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                    futures = {executor.submit(download_photo_worker, (u, photo_file_map)): u for u in batch_usns}
                    for future in concurrent.futures.as_completed(futures):
                        u, p_stream = future.result()
                        if p_stream: batch_photos[u] = p_stream

                for u in batch_usns:
                    stu = next((s for s in all_students if s['usn'] == u), None)
                    if not stu: continue
                    subs = course_map.get(u, [])
                    photo_stream = batch_photos.get(u)
                    
                    app_id = generate_app_id(u, selected_cycle_id)
                    draw_application_page(c, A4[0], A4[1], stu, subs, fees, system_assets, app_id, active_cycle_name, photo_stream)
                    c.showPage()
                    draw_hall_ticket_half(c, A4[0], A4[1] - 30, stu, subs, "STUDENT COPY", app_id, system_assets, active_cycle_name, photo_stream, timetable_map, eligibility_map)
                    c.setDash(4, 4); c.line(20, A4[1]/2, A4[0]-20, A4[1]/2); c.setDash([])
                    draw_hall_ticket_half(c, A4[0], (A4[1]/2) - 20, stu, subs, "COLLEGE COPY", app_id, system_assets, active_cycle_name, photo_stream, timetable_map, eligibility_map)
                    c.showPage()
                
                progress_bar.progress(min((i + BATCH_SIZE) / total, 1.0))
                for stream in batch_photos.values(): stream.close()
                batch_photos.clear() 

            c.save(); status.text("Bulk Generation Complete.")
            st.download_button("📥 Download PDF Bundle", final_pdf_buffer.getvalue(), f"Bulk_Docs_{active_cycle_name}.pdf", "application/pdf")

with tabs[2]:
    st.write("### Single Student Generator")
    target_usn = st.text_input("Enter USN to Generate:").strip().upper()
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
                
                _, photo_stream = download_photo_worker((target_usn, {}))
                timetable_map = fetch_timetable_map(selected_cycle_id)
                eligibility_map = fetch_course_eligibility_map()

                stu_res = supabase.table("master_students").select("*").eq("usn", target_usn).execute()
                if not stu_res.data:
                    st.error(f"❌ Student {target_usn} not found.")
                    st.stop()
                stu = stu_res.data[0]

                # --- IMPORTANT: Filter by USN and the SIDEBAR selected cycle_id ---
                sub_res = supabase.table("course_registrations")\
                    .select("course_code, master_courses(title)")\
                    .eq("usn", target_usn).eq("cycle_id", selected_cycle_id).execute()
                
                subs = []
                for r in sub_res.data:
                    title = r.get('master_courses', {}).get('title', "Unknown Title") if r.get('master_courses') else "Unknown Title"
                    subs.append({"code": r['course_code'], "title": title})
                    
                fee_res = supabase.table("master_fees").select("*").execute()
                fees = {f['fee_type']: f['amount'] for f in fee_res.data}
                
                if not subs:
                    st.error(f"No registrations found for {target_usn} in {active_cycle_name}.")
                else:
                    buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4)
                    app_id = generate_app_id(target_usn, selected_cycle_id)
                    
                    draw_application_page(c, A4[0], A4[1], stu, subs, fees, system_assets, app_id, active_cycle_name, photo_stream)
                    c.showPage()
                    draw_hall_ticket_half(c, A4[0], A4[1] - 30, stu, subs, "STUDENT COPY", app_id, system_assets, active_cycle_name, photo_stream, timetable_map, eligibility_map)
                    c.setDash(4, 4); c.line(20, A4[1]/2, A4[0]-20, A4[1]/2); c.setDash([])
                    draw_hall_ticket_half(c, A4[0], (A4[1]/2) - 20, stu, subs, "COLLEGE COPY", app_id, system_assets, active_cycle_name, photo_stream, timetable_map, eligibility_map)
                    c.showPage(); c.save()
                    
                    st.download_button(f"📥 Download Docs for {target_usn}", buf.getvalue(), f"{target_usn}_ExamDocs.pdf")
            except Exception as e:
                st.error(f"Error: {e}")
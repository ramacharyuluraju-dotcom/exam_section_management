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

# --- PDF LIBRARIES ---
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.utils import ImageReader

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
LOGO_FILENAME = "College_logo.png"
supabase = init_db()

# --- GLOBAL CONTEXT ---
# Pulls the active cycle directly from the session state managed by app.py
selected_cycle_id = st.session_state.get('active_cycle_id')

def generate_dummy_ids(count):
    """Generates a list of unique, easy-to-write IDs like 'VP01', 'AX89'"""
    ids = set()
    while len(ids) < count:
        letters = "".join(random.choices(string.ascii_uppercase, k=2))
        numbers = "".join(random.choices(string.digits, k=2))
        ids.add(f"{letters}{numbers}")
    return list(ids)

def clean_str(val):
    return str(val).strip().upper() if pd.notna(val) else ""

# ==========================================
# 2. DATA FETCHING (CYCLE AWARE)
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
        res = supabase.table("master_students").select("usn, full_name").in_("usn", usns).range(start, start + limit - 1).execute()
        if not res.data: break
        all_stus.extend(res.data)
        if len(res.data) < limit: break
        start += limit
        
    df_stus = pd.DataFrame(all_stus)
    df_stus['Branch'] = df_stus['usn'].apply(lambda x: x[5:7].upper() if len(x) > 7 else "GEN")
    
    df_merged = pd.merge(df_regs, df_stus, on='usn', how='left')
    df_merged.rename(columns={'usn': 'USN', 'full_name': 'Student Name', 'course_code': 'Subject Code'}, inplace=True)
    df_merged['Subject Name'] = df_merged['Subject Code']
    return df_merged

def fetch_rooms():
    res = supabase.table("master_rooms").select("*").order("priority_order").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

# ==========================================
# 3. ALLOCATION ENGINE (ANTI-CHEATING ZIP)
# ==========================================

def run_allocation(df_students, df_rooms):
    branches = df_students['Branch'].unique()
    branch_queues = {b: df_students[df_students['Branch'] == b].sort_values('USN').to_dict('records') for b in branches}
    
    def get_largest_branch(exclude_list=[]):
        cands = [b for b in branch_queues if len(branch_queues[b]) > 0 and b not in exclude_list]
        if not cands: return None
        return sorted(cands, key=lambda x: len(branch_queues[x]), reverse=True)[0]

    def get_best_partner(left_b, exclude_list=[]):
        cands = [b for b in branch_queues if len(branch_queues[b]) > 0 and b != left_b and b not in exclude_list]
        if not cands: return None
        if not left_b or len(branch_queues[left_b]) == 0:
            return sorted(cands, key=lambda x: len(branch_queues[x]), reverse=True)[0]
        
        left_code = branch_queues[left_b][0]['Subject Code']
        diff_code_cands = [b for b in cands if branch_queues[b][0]['Subject Code'] != left_code]
        if diff_code_cands: return sorted(diff_code_cands, key=lambda x: len(branch_queues[x]), reverse=True)[0]
        return sorted(cands, key=lambda x: len(branch_queues[x]), reverse=True)[0]

    curr_left = get_largest_branch()
    curr_right = get_best_partner(curr_left) if curr_left else None
    allotment_rows = []
    
    for _, room in df_rooms.iterrows():
        room_no = room['room_no']
        capacity = int(room['capacity'])
        half_cap = capacity // 2
        
        if all(len(q) == 0 for q in branch_queues.values()): break

        pile_1 = []
        while len(pile_1) < half_cap:
            if not curr_left or len(branch_queues[curr_left]) == 0:
                curr_left = get_largest_branch(exclude_list=[curr_right])
            if not curr_left: curr_left = get_largest_branch()
            if not curr_left: break
            needed = half_cap - len(pile_1)
            take = min(needed, len(branch_queues[curr_left]))
            pile_1.extend(branch_queues[curr_left][:take])
            del branch_queues[curr_left][:take]

        pile_2 = []
        while len(pile_2) < (capacity - len(pile_1)):
            if not curr_right or len(branch_queues[curr_right]) == 0:
                curr_right = get_best_partner(curr_left)
            target = curr_right if curr_right else curr_left
            if not target or len(branch_queues[target]) == 0: target = get_largest_branch()
            if not target: break
            needed = (capacity - len(pile_1)) - len(pile_2)
            take = min(needed, len(branch_queues[target]))
            pile_2.extend(branch_queues[target][:take])
            del branch_queues[target][:take]

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

def draw_header(c, doc):
    c.saveState()
    c.setFont('Helvetica-Bold', 14)
    c.drawCentredString(A4[0]/2, A4[1] - 40, "AMC ENGINEERING COLLEGE (AUTONOMOUS)")
    c.setFont('Helvetica', 9)
    c.drawCentredString(A4[0]/2, A4[1] - 55, "AMC Campus, Bannerghatta Road, Bengaluru - 560083")
    c.line(30, A4[1] - 62, A4[0] - 30, A4[1] - 62)
    c.restoreState()

def gen_posters(df, date, session):
    buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=75)
    elements = []; styles = getSampleStyleSheet()
    s_seat = ParagraphStyle('S', parent=styles['Normal'], fontSize=8, alignment=TA_CENTER, textColor=colors.gray)
    s_usn = ParagraphStyle('U', parent=styles['Normal'], fontSize=11, fontName='Helvetica-Bold', alignment=TA_CENTER)
    s_sub = ParagraphStyle('Sub', parent=styles['Normal'], fontSize=7, alignment=TA_CENTER)
    
    for room_no, data in df.groupby('RoomNo'):
        elements.append(Paragraph(f"ROOM: {room_no} | Date: {date} | Session: {session}", styles['Heading2']))
        elements.append(Spacer(1, 10))
        
        students = data.sort_values('SeatNo').to_dict('records')
        grid = []; row_buf = []
        for s in students:
            row_buf.append([Paragraph(f"Seat: {s['SeatNo']}", s_seat), Spacer(1,2), Paragraph(s['USN'], s_usn), Spacer(1,2), Paragraph(s['Subject Code'], s_sub)])
            if len(row_buf) == 4: grid.append(row_buf); row_buf = []
        if row_buf:
            while len(row_buf) < 4: row_buf.append("")
            grid.append(row_buf)
            
        t = Table(grid, colWidths=[1.8*inch]*4)
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (0,0), (-1,-1), 'CENTER')]))
        elements.append(t); elements.append(PageBreak())
        
    doc.build(elements, onFirstPage=draw_header, onLaterPages=draw_header)
    return buf.getvalue()

def gen_form_b(df, date, session):
    buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=75)
    elements = []; styles = getSampleStyleSheet()
    
    for (room, code), group in df.groupby(['RoomNo', 'Subject Code']):
        elements.append(Paragraph(f"<b>FORM B - ATTENDANCE SHEET ({room})</b>", styles['Heading2']))
        elements.append(Paragraph(f"Date: {date} | Session: {session} | Course: {code}", styles['Normal']))
        elements.append(Spacer(1, 10))
        
        data = [['Seat', 'USN', 'Booklet No.', 'Signature']]
        for _, r in group.sort_values('SeatNo').iterrows():
            data.append([str(r['SeatNo']), r['USN'], "", ""])
            
        t = Table(data, colWidths=[0.8*inch, 2*inch, 1.5*inch, 2.5*inch])
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
        elements.append(t); elements.append(PageBreak())
        
    doc.build(elements, onFirstPage=draw_header, onLaterPages=draw_header)
    return buf.getvalue()

def gen_form_a(df, date, session):
    """Generates the Absentee Summary & Bundle Dispatch Form (DEPARTMENT/BRANCH WISE)"""
    buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=75)
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
        
    doc.build(elements, onFirstPage=draw_header, onLaterPages=draw_header)
    return buf.getvalue()

def gen_qpds(df, date, session):
    buf = io.BytesIO(); doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=75)
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
        
    doc.build(elements, onFirstPage=draw_header, onLaterPages=draw_header)
    return buf.getvalue()

def gen_smart_excel(df, date, session):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
        df_sorted = df.sort_values(['Branch', 'USN'])
        df_sorted.to_excel(writer, sheet_name='Appearing_List', index=False, columns=['RoomNo', 'SeatNo', 'USN', 'Student Name', 'Branch', 'Subject Code'])
        summary = df.groupby(['RoomNo', 'Subject Code']).size().reset_index(name='Count')
        summary.to_excel(writer, sheet_name='Room_Summary', index=False)
    return buf.getvalue()

def create_locked_bundle(df, course_code, room_no, bundle_seq, total_bundles):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
        wb = writer.book
        fmt_locked = wb.add_format({'locked': True, 'align': 'center', 'border': 1})
        fmt_edit = wb.add_format({'locked': False, 'align': 'center', 'border': 1, 'bg_color': '#FFFFCC'})
        fmt_head = wb.add_format({'locked': True, 'bold': True, 'align': 'center', 'border': 1, 'bg_color': '#f0f0f0'})
        fmt_abs = wb.add_format({'locked': True, 'align': 'center', 'border': 1, 'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
        
        ws = wb.add_worksheet('Marks Entry')
        ws.protect('admin123')
        
        ws.write('A1', f"Course: {course_code} | Room: {room_no} | Bundle: {bundle_seq}/{total_bundles}", fmt_locked)
        headers = ["Sl.", "DUMMY NO."] + [f"Q{q}" for q in range(1, 11)] + ["Total SEE (100)"]
        for c, h in enumerate(headers): ws.write(2, c, h, fmt_head)
        
        row = 3
        for i, s in df.iterrows():
            ws.write(row, 0, i+1, fmt_locked)
            ws.write(row, 1, s['Dummy_ID'], fmt_locked)
            
            if s['Status'] != "PRESENT":
                for c in range(2, 12): ws.write(row, c, "", fmt_locked)
                ws.write(row, 12, s['Status'], fmt_abs)
            else:
                for c in range(2, 12): ws.write(row, c, "", fmt_edit)
                r_num = row + 1
                ws.write_formula(row, 12, f"=SUM(C{r_num}:L{r_num})", fmt_locked)
            row += 1
            
        ws.set_column('B:B', 15)
    return out.getvalue()

def gen_marks_bundles(df):
    zip_buf = io.BytesIO()
    key_log = []
    
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Evaluator Bundles generated Room & Subject-wise in chunks of 20
        for (room, cc), group in df.groupby(['RoomNo', 'Subject Code']):
            group = group.sort_values('SeatNo').reset_index(drop=True)
            n_chunks = math.ceil(len(group) / 20)
            
            for i in range(n_chunks):
                chunk = group.iloc[i*20 : (i+1)*20].copy()
                chunk['Dummy_ID'] = generate_dummy_ids(len(chunk))
                
                b_id = f"{room}_{cc}_{str(i+1).zfill(2)}"
                
                for _, s in chunk.iterrows():
                    key_log.append({
                        'Bundle_ID': b_id, 'Room': room, 'USN': s['USN'], 
                        'Subject': cc, 'Dummy_ID': s['Dummy_ID'], 'Status': s['Status']
                    })
                
                excel_bytes = create_locked_bundle(chunk, cc, room, i+1, n_chunks)
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
    with c1: st.download_button("📌 Room Posters (PDF)", gen_posters(df_a, date_str, sess_str), f"Posters_{date_str}.pdf")
    with c2: st.download_button("📝 Form B (PDF)", gen_form_b(df_a, date_str, sess_str), f"FormB_{date_str}.pdf")
    with c3: st.download_button("📦 Form A (PDF)", gen_form_a(df_a, date_str, sess_str), f"FormA_{date_str}.pdf")
    with c4: st.download_button("📋 QPDS (PDF)", gen_qpds(df_a, date_str, sess_str), f"QPDS_{date_str}.pdf")
    with c5: st.download_button("📊 Appearing (Excel)", gen_smart_excel(df_a, date_str, sess_str), f"Appearing_{date_str}.xlsx")
        
    st.markdown("---")
    st.subheader("🔐 3. Post-Exam Processing")
    st.info("Generates secure Excel bundles (Max 20 per bundle, Room & Subject-wise). Absentees are locked.")
    
    if st.button("📦 Generate Locked Marks Bundles (.zip)", type="primary"):
        with st.spinner("Encrypting bundles and generating Secret Key..."):
            zip_bytes = gen_marks_bundles(df_a)
            st.download_button("📥 Click to Download ZIP", zip_bytes, f"Evaluation_Bundles_{date_str}.zip", "application/zip")
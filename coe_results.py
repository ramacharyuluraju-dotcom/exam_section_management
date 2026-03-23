import streamlit as st
import pandas as pd
import io
import math
import zipfile
import string
import random
from utils import init_db

# --- REPORTLAB IMPORTS FOR PDF GENERATION ---
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
LOGO_FILENAME = "College_logo.png"
supabase = init_db()

selected_cycle_id = st.session_state.get('active_cycle_id')
active_cycle_name = st.session_state.get('active_cycle_name', 'Unknown Cycle')

def clean_str(val):
    return str(val).strip().upper() if pd.notna(val) else ""

def find_column(df, candidates):
    cols = [c.upper().strip() for c in df.columns]
    for candidate in candidates:
        if candidate.upper() in cols:
            return df.columns[cols.index(candidate.upper())]
    return None

def safe_float(val, default):
    """Safely converts a value to float, correctly preserving literal 0s."""
    if val is None:
        return float(default)
    try:
        if pd.isna(val):
            return float(default)
        if str(val).strip() == "":
            return float(default)
        return float(val)
    except:
        return float(default)

def fetch_all_records(table_name, select_query="*", filters=None):
    """Recursively fetches all records from a Supabase table bypassing the 1000 row limit."""
    all_data = []
    start = 0
    step = 1000
    while True:
        query = supabase.table(table_name).select(select_query).range(start, start + step - 1)
        if filters:
            for col, val in filters.items():
                query = query.eq(col, val)
        res = query.execute()
        if not res.data: break
        all_data.extend(res.data)
        if len(res.data) < step: break
        start += step
    return all_data

# ==========================================
# 2. UNIVERSAL GRADING ALGORITHM
# ==========================================
def apply_grading_rules(cie_raw, see_raw, status, credits, max_cie=50, max_see=50, exam_conducted_for=100, is_pg=False):
    is_internal_only = (max_see == 0)
    
    # Auto-Healer
    if not is_internal_only:
        if pd.notna(see_raw) and see_raw is not None and str(see_raw).strip() != "":
            if not status or status in ['PENDING', 'PND']: status = 'PRESENT'
    else:
        if pd.notna(cie_raw) and cie_raw is not None and str(cie_raw).strip() != "":
            if not status or status in ['PENDING', 'PND']: status = 'PRESENT'

    # Strict Pending Locks
    if not is_internal_only:
        if status in ['PENDING', 'PND'] or not status or pd.isna(see_raw) or see_raw is None: 
            return 0, cie_raw, 'PND', 0, False, status
    else:
        if status in ['PENDING', 'PND'] or not status or pd.isna(cie_raw) or cie_raw is None:
            return 0, cie_raw, 'PND', 0, False, status
            
    if status in ['ABSENT', 'AB']: return 0, 0, 'AB', 0, False, 'ABSENT'
    if status in ['MALPRACTICE', 'MP']: return 0, 0, 'MP', 0, False, 'MALPRACTICE'
    if status in ['WITHHELD', 'WH']: return 0, 0, 'WH', 0, False, 'WITHHELD'

    cie = math.ceil(float(cie_raw)) if pd.notna(cie_raw) else 0.0
    see_raw = float(see_raw) if pd.notna(see_raw) else 0.0
    
    if is_internal_only: see_scaled = 0
    else:
        scale_factor = max_see / exam_conducted_for if exam_conducted_for > 0 else 1
        see_scaled = math.ceil(see_raw * scale_factor)

    total = cie + see_scaled
    is_pass = True
    
    if is_pg:
        min_cie_req = math.ceil(0.50 * max_cie)
        min_see_raw_req = math.ceil(0.40 * exam_conducted_for)
        min_total_req = math.ceil(0.50 * (max_cie + max_see))
    else:
        min_cie_req = math.ceil(0.40 * max_cie)
        min_see_raw_req = math.ceil(0.35 * exam_conducted_for)
        min_total_req = math.ceil(0.40 * (max_cie + max_see))

    if is_internal_only:
        if cie < min_cie_req: is_pass = False
    else:
        if cie < min_cie_req or see_raw < min_see_raw_req or total < min_total_req:
            is_pass = False

    if credits == 0:
        if is_pass: return see_scaled, total, 'PP', 0, True, status  
        else: return see_scaled, total, 'NP', 0, False, status 

    if not is_pass: return see_scaled, total, 'F', 0, False, status
        
    total_max = max_cie + max_see
    pct = total / total_max
    
    if is_pg:
        if pct >= 0.90: return see_scaled, total, 'O', 10, True, status
        elif pct >= 0.80: return see_scaled, total, 'A+', 9, True, status
        elif pct >= 0.70: return see_scaled, total, 'A', 8, True, status
        elif pct >= 0.60: return see_scaled, total, 'B+', 7, True, status
        elif pct >= 0.55: return see_scaled, total, 'B', 6, True, status
        elif pct >= 0.50: return see_scaled, total, 'C', 5, True, status
        else: return see_scaled, total, 'F', 0, False, status
    else:
        if pct >= 0.90: return see_scaled, total, 'O', 10, True, status
        elif pct >= 0.80: return see_scaled, total, 'A+', 9, True, status
        elif pct >= 0.70: return see_scaled, total, 'A', 8, True, status
        elif pct >= 0.60: return see_scaled, total, 'B+', 7, True, status
        elif pct >= 0.50: return see_scaled, total, 'B', 6, True, status
        elif pct >= 0.45: return see_scaled, total, 'C', 5, True, status
        elif pct >= 0.40: return see_scaled, total, 'P', 4, True, status
        else: return see_scaled, total, 'F', 0, False, status

# ==========================================
# 3. PDF MARKS CARD GENERATOR
# ==========================================
def generate_marks_card_pdf(buffer, usn, name, results_list, sgpa, has_pending=False):
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    elements = []
    styles = getSampleStyleSheet()
    
    style_center = ParagraphStyle('Center', parent=styles['Heading1'], alignment=1, fontSize=16, spaceAfter=10)
    style_sub = ParagraphStyle('Sub', parent=styles['Heading3'], alignment=1, fontSize=12, spaceAfter=5)
    
    elements.append(Paragraph("AMC ENGINEERING COLLEGE", style_center))
    elements.append(Paragraph("Autonomous Institution Affiliated to VTU, Belagavi", style_sub))
    elements.append(Paragraph(f"Provisional Result Sheet - {active_cycle_name}", style_sub))
    elements.append(Spacer(1, 20))
    
    t_info = Table([[f"USN: {usn}", f"Name: {name}"]], colWidths=[250, 250])
    t_info.setStyle(TableStyle([('ALIGN', (1,0), (1,0), 'RIGHT'), ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold')]))
    elements.append(t_info); elements.append(Spacer(1, 15))
    
    data = [['Code', 'Subject', 'Cr', 'CIE', 'SEE', 'Total', 'Grade', 'GP']]
    for row in results_list:
        data.append([row['code'], row['title'][:30], str(row['cr']), str(row['cie']), str(row['see']), str(row['tot']), row['grade'], str(row['gp'])])
    
    t = Table(data, colWidths=[65, 175, 30, 40, 40, 50, 50, 40])
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]
    for i, row in enumerate(results_list):
        if row['grade'] in ['F', 'NP', 'AB', 'WH', 'MP']: col = colors.red
        elif row['grade'] in ['PND', 'PENDING']: col = colors.darkorange
        else: col = colors.green
        style_cmds.append(('TEXTCOLOR', (6, i+1), (6, i+1), col))
        
    t.setStyle(TableStyle(style_cmds))
    elements.append(t); elements.append(Spacer(1, 20))
    
    if has_pending: 
        pass_fail = "PENDING"
        sgpa_str = "---"
        pf_color = colors.darkorange
    else:
        pass_fail = "PASS" if all(r['pass'] for r in results_list) else "FAIL"
        sgpa_str = f"{sgpa:.2f}"
        pf_color = colors.red if pass_fail == "FAIL" else colors.green
        
    t_total = Table([[f"SGPA: {sgpa_str}", f"Result: {pass_fail}"]], colWidths=[250, 250])
    t_total.setStyle(TableStyle([
        ('ALIGN', (1,0), (1,0), 'RIGHT'), 
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'), 
        ('TEXTCOLOR', (1,0), (1,0), pf_color)
    ]))
    elements.append(t_total); elements.append(Spacer(1, 60))
    
    t_sig = Table([["Controller of Examinations", "Principal"]], colWidths=[250, 250])
    t_sig.setStyle(TableStyle([('ALIGN', (1,0), (1,0), 'RIGHT')]))
    elements.append(t_sig)
    
    doc.build(elements)

# ==========================================
# 4. MAIN UI FLOW 
# ==========================================

if not selected_cycle_id:
    st.error("⚠️ CRITICAL ERROR: No Exam Cycle Selected. Please select a cycle in the Sidebar.")
    st.stop()

st.title("🏆 Results & Grading Engine")
st.info(f"📍 **Active Context:** Processing data strictly for Cycle: **{active_cycle_name}**")

# 🟢 8 TABS TO SUPPORT NEW ARCHITECTURE 🟢
t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs([
    "1. CIE Consolidator", 
    "2. Bundle Decoder", 
    "3. SEE Consolidator", 
    "4. Grading Engine", 
    "5. Moderation (Audit Logged)", 
    "6. Publish Ledgers",
    "7. CoE Dashboard",
    "8. Arrear & Make-up Engine"
])

# ----------------------------------------------------
# TAB 1: CIE ENTRY 
# ----------------------------------------------------
with t1:
    st.subheader("Department Internals (CIE) Consolidation")
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        f_cie = st.file_uploader("Upload CSV (Required: usn, course_code, cie_marks)", type='csv', key="cie_up")
        if f_cie and st.button("🚀 Process Bulk CIE"):
            df_cie = pd.read_csv(f_cie)
            usn_col = find_column(df_cie, ['usn', 'student id'])
            cc_col = find_column(df_cie, ['course_code', 'course code', 'subject code'])
            m_col = find_column(df_cie, ['cie_marks', 'cie', 'ia marks', 'internals'])
            
            if not (usn_col and cc_col and m_col): st.error("Missing standard columns.")
            else:
                with st.spinner("Validating against registrations..."):
                    regs = fetch_all_records("course_registrations", "usn, course_code", {"cycle_id": selected_cycle_id})
                    valid_pairs = set((str(r['usn']).strip().upper(), str(r['course_code']).strip().upper()) for r in regs)
                    
                    records, ignored_count = [], 0
                    for _, r in df_cie.iterrows():
                        usn, cc = clean_str(r[usn_col]), clean_str(r[cc_col])
                        if (usn, cc) in valid_pairs:
                            records.append({"cycle_id": selected_cycle_id, "usn": usn, "course_code": cc, "cie_marks": safe_float(r[m_col], None)})
                        else: ignored_count += 1
                            
                    if not records: st.error("No matching registered students found.")
                    else:
                        for i in range(0, len(records), 500): supabase.table("student_results").upsert(records[i:i+500]).execute()
                        st.success(f"✅ Successfully uploaded {len(records)} CIE records.")
                        if ignored_count > 0: st.warning(f"⚠️ Blocked {ignored_count} records (Not registered).")

    with col_c2:
        with st.form("manual_cie"):
            m_usn = st.text_input("USN").strip().upper()
            m_cc = st.text_input("Course Code").strip().upper()
            m_marks = st.number_input("CIE Marks", min_value=0.0, max_value=100.0, value=0.0, step=0.5)
            if st.form_submit_button("Save CIE Mark"):
                regs = supabase.table("course_registrations").select("*").eq("cycle_id", selected_cycle_id).eq("usn", m_usn).eq("course_code", m_cc).execute().data
                if not regs: st.error(f"❌ Student {m_usn} is NOT registered for {m_cc}.")
                else:
                    supabase.table("student_results").upsert({"cycle_id": selected_cycle_id, "usn": m_usn, "course_code": m_cc, "cie_marks": m_marks}).execute()
                    st.success("✅ Saved.")

# ----------------------------------------------------
# TAB 2: BUNDLE DECODER UTILITY
# ----------------------------------------------------
with t2:
    st.subheader("🔐 Standalone Bundle Decoder")
    col_d1, col_d2 = st.columns(2)
    with col_d1: key_file = st.file_uploader("1. Upload MASTER_SECRET_KEY.xlsx", type=['xlsx'])
    with col_d2: bundle_files = st.file_uploader("2. Upload Evaluator Bundles (.xlsx)", type=['xlsx'], accept_multiple_files=True)

    if st.button("🔓 Generate Decoded CSV", type="primary"):
        if not key_file or not bundle_files: st.warning("⚠️ Please upload both the Master Key and at least one Evaluator Bundle.")
        else:
            with st.spinner("Decrypting Dummy IDs and extracting marks..."):
                try:
                    key_df = pd.read_excel(key_file)
                    key_df['Dummy_ID'] = key_df['Dummy_ID'].astype(str).str.strip().str.upper()
                    extracted_data = []
                    
                    for f in bundle_files:
                        try:
                            df_preview = pd.read_excel(f, sheet_name='Marks Entry', header=None, nrows=15)
                            header_idx = -1
                            for idx, row in df_preview.iterrows():
                                if any("CODING" in str(x).upper() or "DUMMY" in str(x).upper() for x in row.tolist()):
                                    header_idx = idx; break
                            if header_idx == -1: continue
                            
                            df_bun = pd.read_excel(f, sheet_name='Marks Entry', header=header_idx)
                            dummy_col = next((c for c in df_bun.columns if "DUMMY" in str(c).upper() or "CODING" in str(c).upper()), None)
                            marks_col = next((c for c in df_bun.columns if "FINAL SEE" in str(c).upper()), None)
                            if not marks_col: marks_col = next((c for c in df_bun.columns if "TOTAL SEE" in str(c).upper()), None)
                            
                            if dummy_col and marks_col:
                                for _, r in df_bun.iterrows():
                                    d_id = str(r[dummy_col]).strip().upper()
                                    m_val = r[marks_col]
                                    if len(d_id) > 2 and d_id != "NAN": extracted_data.append({'Dummy_ID': d_id, 'SEE_Raw_Val': m_val})
                        except: pass
                    
                    if extracted_data:
                        marks_df = pd.DataFrame(extracted_data)
                        final_df = pd.merge(key_df, marks_df, on='Dummy_ID', how='inner')
                        processed_records = []
                        for _, r in final_df.iterrows():
                            m_val = str(r.get('SEE_Raw_Val', '')).strip().upper()
                            stat, raw_see = "PRESENT", 0.0
                            
                            if m_val in ['AB', 'ABSENT']: stat = 'ABSENT'
                            elif m_val in ['MP', 'MAL', 'MALPRACTICE']: stat = 'MALPRACTICE'
                            elif m_val in ['WH', 'WITHHELD']: stat = 'WITHHELD'
                            elif m_val == 'NAN' or m_val == '': stat = 'PRESENT'
                            else:
                                try: raw_see = float(m_val)
                                except ValueError: raw_see = 0.0
                                    
                            processed_records.append({"usn": clean_str(r['USN']), "course_code": clean_str(r['Subject']), "see_marks": raw_see, "status": stat})
                            
                        out_df = pd.DataFrame(processed_records)
                        csv_buffer = io.StringIO()
                        out_df.to_csv(csv_buffer, index=False)
                        st.success(f"✅ Successfully decoded {len(out_df)} records!")
                        st.download_button(label="📥 Download Decoded SEE CSV", data=csv_buffer.getvalue(), file_name="Decoded_SEE_Marks.csv", mime="text/csv", type="primary")
                    else: st.error("No valid marks data extracted from bundles.")
                except Exception as e: st.error(f"Error: {e}")

# ----------------------------------------------------
# TAB 3: SEE CONSOLIDATION
# ----------------------------------------------------
with t3:
    st.subheader("SEE Marks Consolidation")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        f_see = st.file_uploader("Upload CSV (Required: usn, course_code, see_marks, status)", type='csv', key="see_up")
        if f_see and st.button("🚀 Process Bulk SEE"):
            df_see = pd.read_csv(f_see)
            usn_col = find_column(df_see, ['usn', 'student id'])
            cc_col = find_column(df_see, ['course_code', 'course code', 'subject code', 'subject'])
            m_col = find_column(df_see, ['see_marks', 'see', 'marks', 'see_raw'])
            stat_col = find_column(df_see, ['status', 'exam_status', 'attendance'])
            
            if not (usn_col and cc_col and m_col): st.error("Missing standard columns.")
            else:
                with st.spinner("Validating against registrations..."):
                    regs = fetch_all_records("course_registrations", "usn, course_code", {"cycle_id": selected_cycle_id})
                    valid_pairs = set((str(r['usn']).strip().upper(), str(r['course_code']).strip().upper()) for r in regs)
                    
                    records, ignored_count = [], 0
                    for _, r in df_see.iterrows():
                        usn, cc = clean_str(r[usn_col]), clean_str(r[cc_col])
                        if (usn, cc) in valid_pairs:
                            stat = clean_str(r[stat_col]) if stat_col else "PRESENT"
                            m_val = str(r[m_col]).strip().upper()
                            raw_see = None
                            
                            if m_val in ['AB', 'ABSENT']: stat = 'ABSENT'
                            elif m_val in ['MP', 'MAL']: stat = 'MALPRACTICE'
                            elif m_val in ['WH']: stat = 'WITHHELD'
                            elif pd.notna(r[m_col]) and m_val != 'NAN' and m_val != '':
                                try: raw_see = float(m_val)
                                except: raw_see = None

                            records.append({"cycle_id": selected_cycle_id, "usn": usn, "course_code": cc, "see_raw": raw_see, "exam_status": stat})
                        else: ignored_count += 1
                            
                    if not records: st.error("❌ Upload Failed. No valid records.")
                    else:
                        for i in range(0, len(records), 500): supabase.table("student_results").upsert(records[i:i+500]).execute()
                        st.success(f"✅ Successfully uploaded {len(records)} valid SEE records.")
                        if ignored_count > 0: st.warning(f"⚠️ Blocked {ignored_count} unregistered records.")

    with col_s2:
        with st.form("manual_see"):
            s_usn = st.text_input("USN").strip().upper()
            s_cc = st.text_input("Course Code").strip().upper()
            s_marks = st.number_input("SEE Marks (Raw Paper Score)", min_value=0.0, max_value=100.0, value=0.0)
            s_stat = st.selectbox("Status", ["PRESENT", "ABSENT", "MALPRACTICE", "WITHHELD"])
            if st.form_submit_button("Save SEE Mark"):
                regs = supabase.table("course_registrations").select("*").eq("cycle_id", selected_cycle_id).eq("usn", s_usn).eq("course_code", s_cc).execute().data
                if not regs: st.error(f"❌ Student {s_usn} is NOT registered for {s_cc}.")
                else:
                    supabase.table("student_results").upsert({"cycle_id": selected_cycle_id, "usn": s_usn, "course_code": s_cc, "see_raw": s_marks, "exam_status": s_stat}).execute()
                    st.success("✅ Saved to Database.")

# ----------------------------------------------------
# TAB 4: GRADING ENGINE
# ----------------------------------------------------
with t4:
    st.subheader("Result & Grading Processor")
    if st.button("⚙️ Execute Master Grading Algorithm", type="primary"):
        with st.spinner("Processing ALL records (bypassing 1000 row limit)..."):
            try:
                raw_res = fetch_all_records("student_results", filters={"cycle_id": selected_cycle_id})
                if not raw_res:
                    st.error("No marks found for this cycle.")
                    st.stop()
                    
                stu_res = fetch_all_records("master_students", "usn, branch_code")
                branch_map = {str(r['usn']).strip().upper(): r['branch_code'] for r in stu_res}
                
                branch_res = supabase.table("master_branches").select("branch_code, program_type").execute()
                pg_branches = [r['branch_code'] for r in branch_res.data if str(r['program_type']).upper() == 'PG']

                crs_res = fetch_all_records("master_courses", "course_code, credits, max_see, max_cie, total_marks")
                credit_map = {r['course_code']: safe_float(r.get('credits'), 4.0) for r in crs_res}
                max_see_map = {r['course_code']: safe_float(r.get('max_see'), 50.0) for r in crs_res}
                max_cie_map = {r['course_code']: safe_float(r.get('max_cie'), 50.0) for r in crs_res}
                paper_max_map = {r['course_code']: safe_float(r.get('total_marks'), 100.0) for r in crs_res}
                
                updates = []
                for row in raw_res:
                    usn, cc = str(row['usn']).strip().upper(), row['course_code']
                    cred = credit_map.get(cc, 4.0)
                    m_see, m_cie, conducted_for = max_see_map.get(cc, 50.0), max_cie_map.get(cc, 50.0), paper_max_map.get(cc, 100.0)
                    
                    is_pg = branch_map.get(usn, "") in pg_branches
                    status = row.get('exam_status')
                    
                    scaled_see, tot, grd, gp, is_pass, healed_status = apply_grading_rules(row['cie_marks'], row['see_raw'], status, cred, m_cie, m_see, conducted_for, is_pg)
                    
                    updates.append({
                        "cycle_id": selected_cycle_id, "usn": usn, "course_code": cc,
                        "see_scaled": scaled_see, "total_marks": tot, "grade": grd,
                        "grade_points": gp, "credits_earned": cred if is_pass else 0.0, "is_pass": is_pass,
                        "exam_status": healed_status
                    })
                    
                for i in range(0, len(updates), 500):
                    supabase.table("student_results").upsert(updates[i:i+500]).execute()
                    
                st.success(f"✅ Grading calculated for {len(updates)} records successfully!")
            except Exception as e: st.error(f"Error: {e}")

# ----------------------------------------------------
# TAB 5: MODERATION (GRACE MARKS & AUDIT)
# ----------------------------------------------------
with t5:
    st.subheader("⚖️ Moderation & Grace Marks (Audited)")
    st.info("All grace marks applied here are logged permanently to the `marks_audit_log` table for compliance.")
    mod_usn = st.text_input("Enter Student USN to review failing subjects:").strip().upper()
    if mod_usn:
        try:
            fail_res = supabase.table("student_results").select("*").eq("cycle_id", selected_cycle_id).eq("usn", mod_usn).eq("is_pass", False).execute()
            if not fail_res.data: st.success(f"🎉 Student {mod_usn} has no failing subjects!")
            else:
                actual_fails = [r for r in fail_res.data if r['grade'] not in ['PND', 'PENDING']]
                if not actual_fails: st.warning(f"Student {mod_usn} is PENDING in their subjects. Cannot apply grace marks yet.")
                else:
                    stu_res = supabase.table("master_students").select("branch_code").eq("usn", mod_usn).execute()
                    student_branch = stu_res.data[0]['branch_code'] if stu_res.data else ""
                    branch_res = supabase.table("master_branches").select("program_type").eq("branch_code", student_branch).execute()
                    is_pg = (str(branch_res.data[0]['program_type']).upper() == 'PG') if branch_res.data else False

                    failed_course_codes = [r['course_code'] for r in actual_fails]
                    crs_res = supabase.table("master_courses").select("course_code, title, credits, max_cie, max_see, total_marks").in_("course_code", failed_course_codes).execute()
                    crs_map = {c['course_code']: c for c in crs_res.data}
                    
                    st.warning(f"Found {len(actual_fails)} failing subject(s) for {mod_usn}.")
                    for r in actual_fails:
                        cc = r['course_code']
                        mc = crs_map.get(cc, {})
                        title = mc.get('title', cc)
                        c_cie, c_see, c_tot, c_grade = safe_float(r['cie_marks'], 0), safe_float(r['see_raw'], 0), safe_float(r['total_marks'], 0), str(r['grade'])
                        
                        with st.expander(f"⚠️ {cc} - {title} (Current Grade: {c_grade})"):
                            st.markdown(f"**Current Marks:** CIE: `{c_cie}` | SEE Raw: `{c_see}` | Scaled SEE: `{r['see_scaled']}` | Total: `{c_tot}`")
                            with st.form(f"grace_form_{cc}"):
                                col_m1, col_m2 = st.columns(2)
                                grace_target = col_m1.radio("Add Grace Marks To:", ["SEE Exam", "CIE (Internals)"])
                                grace_marks = col_m2.number_input("Grace Marks to Add", min_value=1.0, max_value=10.0, step=1.0, value=1.0)
                                grace_reason = st.text_input("Reason for Moderation (Required for Audit):")
                                
                                if st.form_submit_button("✨ Apply Grace Marks & Recalculate"):
                                    if not grace_reason:
                                        st.error("Audit reason is required.")
                                    else:
                                        new_cie = c_cie + grace_marks if grace_target == "CIE (Internals)" else c_cie
                                        new_see = c_see + grace_marks if grace_target == "SEE Exam" else c_see
                                        cred = safe_float(mc.get('credits'), 4.0)
                                        m_cie, m_see, conducted_for = safe_float(mc.get('max_cie'), 50.0), safe_float(mc.get('max_see'), 50.0), safe_float(mc.get('total_marks'), 100.0)
                                        
                                        scaled_see, tot, grd, gp, is_pass, healed_status = apply_grading_rules(new_cie, new_see, r['exam_status'], cred, m_cie, m_see, conducted_for, is_pg)
                                        
                                        # 🟢 WRITE TO AUDIT LOG 🟢
                                        audit_payload = {
                                            "cycle_id": selected_cycle_id, "usn": mod_usn, "course_code": cc,
                                            "change_type": "MODERATION - GRACE",
                                            "old_cie": c_cie, "old_see": c_see, "old_grade": c_grade,
                                            "new_cie": new_cie, "new_see": new_see, "new_grade": grd,
                                            "reason": f"{grace_reason} (+{grace_marks} to {grace_target})"
                                        }
                                        try: supabase.table("marks_audit_log").insert(audit_payload).execute()
                                        except Exception as e: st.warning("Audit Log Warning: Log table might not exist yet. Run the SQL script.")

                                        # 🟢 UPDATE RESULTS WITH TRACKING FLAGS 🟢
                                        update_data = {
                                            "cycle_id": selected_cycle_id, "usn": mod_usn, "course_code": cc,
                                            "cie_marks": new_cie, "see_raw": new_see, "see_scaled": scaled_see,
                                            "total_marks": tot, "grade": grd, "grade_points": gp,
                                            "credits_earned": cred if is_pass else 0.0, "is_pass": is_pass,
                                            "exam_status": healed_status,
                                            "is_graced": True, "grace_marks_added": float(grace_marks)
                                        }
                                        supabase.table("student_results").upsert(update_data).execute()
                                        if is_pass: st.success(f"✅ Grace marks applied and audited! Passed with Grade **{grd}**.")
                                        else: st.warning(f"⚠️ Audited, but student still failing. New Grade: **{grd}**.")
        except Exception as e: st.error(f"Error fetching data: {e}")

# ----------------------------------------------------
# TAB 6: PUBLISH LEDGERS & CARDS
# ----------------------------------------------------
with t6:
    st.subheader("Generate Ledgers & Marks Cards")
    if st.button("🖨️ Generate Master Ledger & PDFs"):
        with st.spinner("Compiling institutional ledgers..."):
            try:
                regs_data = fetch_all_records("course_registrations", "usn, course_code", {"cycle_id": selected_cycle_id})
                if not regs_data:
                    st.error("No course registrations found for this cycle.")
                    st.stop()
                
                stu_courses = {}
                for r in regs_data:
                    u, c = clean_str(r['usn']), clean_str(r['course_code'])
                    if u not in stu_courses: stu_courses[u] = []
                    stu_courses[u].append(c)

                res_data = fetch_all_records("student_results", filters={"cycle_id": selected_cycle_id})
                res_map = {(clean_str(r['usn']), clean_str(r['course_code'])): r for r in res_data}
                
                stu_res = fetch_all_records("master_students", "usn, full_name, branch_code")
                name_map = {clean_str(r['usn']): r.get('full_name', "Unknown") for r in stu_res}
                branch_map = {clean_str(r['usn']): r.get('branch_code', "UNKNOWN") for r in stu_res}
                
                crs_data = fetch_all_records("master_courses", "course_code, title, credits, max_see")
                crs_map = {clean_str(c['course_code']): c for c in crs_data}
                
                ledger_rows = []
                pdf_zip_buffer = io.BytesIO()
                
                with zipfile.ZipFile(pdf_zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for usn, courses in stu_courses.items():
                        name, branch = name_map.get(usn, "Unknown"), branch_map.get(usn, "UNKNOWN")
                        total_cr_attempted, total_gp_earned, results_list = 0.0, 0.0, []
                        ledger_dict = {'USN': usn, 'Name': name, 'Branch': branch}
                        pass_flag, has_pending = True, False
                        
                        for cc in courses:
                            mc = crs_map.get(cc, {})
                            cr = safe_float(mc.get('credits'), 0.0)
                            is_internal_only = (safe_float(mc.get('max_see'), 50.0) == 0.0)
                            r = res_map.get((usn, cc))
                            
                            if not is_internal_only: see_missing = not r or pd.isna(r.get('see_raw')) or r.get('see_raw') is None
                            else: see_missing = False
                            
                            if see_missing or not r or r.get('grade') in ['PND', 'PENDING'] or r.get('exam_status') in ['PND', 'PENDING']:
                                has_pending = True
                                cie_disp = str(r['cie_marks']) if (r and pd.notna(r.get('cie_marks'))) else "PND"
                                see_disp = "-" if is_internal_only else "PND"
                                results_list.append({'code': cc, 'title': mc.get('title', cc), 'cr': cr, 'cie': cie_disp, 'see': see_disp, 'tot': "-", 'grade': "PND", 'gp': "-", 'pass': False})
                                ledger_dict[f"{cc}_CIE"] = cie_disp; ledger_dict[f"{cc}_SEE"] = see_disp
                                ledger_dict[f"{cc}_Tot"] = "PND"; ledger_dict[f"{cc}_Grd"] = "PND"
                            else:
                                cie_val = r.get('cie_marks', 0)
                                see_val = r.get('see_scaled', 0)
                                tot_val = r.get('total_marks', 0)
                                grd_val = r.get('grade', 'F')
                                results_list.append({'code': cc, 'title': mc.get('title', cc), 'cr': cr, 'cie': str(cie_val), 'see': str(see_val) if not is_internal_only else "-", 'tot': str(tot_val), 'grade': str(grd_val), 'gp': str(r.get('grade_points', 0)), 'pass': r.get('is_pass', False)})
                                ledger_dict[f"{cc}_CIE"] = cie_val; ledger_dict[f"{cc}_SEE"] = "-" if is_internal_only else see_val
                                ledger_dict[f"{cc}_Tot"] = tot_val; ledger_dict[f"{cc}_Grd"] = grd_val
                                
                                total_cr_attempted += cr
                                total_gp_earned += (r.get('grade_points', 0) * cr)
                                if not r.get('is_pass', False): pass_flag = False
                            
                        sgpa = (total_gp_earned / total_cr_attempted) if total_cr_attempted > 0 else 0.0
                        ledger_dict['SGPA'] = round(sgpa, 2) if not has_pending else "---"
                        ledger_dict['Result'] = "PENDING" if has_pending else ("PASS" if pass_flag else "FAIL")
                        
                        ledger_rows.append(ledger_dict)
                        pdf_buf = io.BytesIO()
                        generate_marks_card_pdf(pdf_buf, usn, name, results_list, sgpa, has_pending)
                        zf.writestr(f"Marks_Cards/{usn}.pdf", pdf_buf.getvalue())
                        
                df_ledger = pd.DataFrame(ledger_rows)
                base_cols = ['USN', 'Name', 'Branch']; end_cols = ['SGPA', 'Result']
                def sort_key(col_name):
                    if col_name.endswith('_CIE'): return (col_name[:-4], 1)
                    if col_name.endswith('_SEE'): return (col_name[:-4], 2)
                    if col_name.endswith('_Tot'): return (col_name[:-4], 3)
                    if col_name.endswith('_Grd'): return (col_name[:-4], 4)
                    return (col_name, 5)
                course_cols = [c for c in df_ledger.columns if c not in base_cols + end_cols]
                course_cols.sort(key=sort_key)
                df_ledger = df_ledger[base_cols + course_cols + end_cols]
                
                ledger_zip = io.BytesIO()
                with zipfile.ZipFile(ledger_zip, "w") as branch_zf:
                    for b_name, b_df in df_ledger.groupby('Branch'):
                        branch_excel = io.BytesIO()
                        with pd.ExcelWriter(branch_excel, engine='xlsxwriter') as writer:
                            b_df.dropna(axis=1, how='all').to_excel(writer, index=False)
                        branch_zf.writestr(f"Ledger_{str(b_name)}.xlsx", branch_excel.getvalue())
                
                st.success(f"✅ Successfully compiled {len(ledger_rows)} records into ZIP!")
                c1, c2 = st.columns(2)
                with c1: st.download_button("📊 Branch Ledgers (ZIP)", ledger_zip.getvalue(), f"Branch_Ledgers_{active_cycle_name}.zip")
                with c2: st.download_button("📄 Marks Cards (ZIP)", pdf_zip_buffer.getvalue(), f"Marks_Cards_{active_cycle_name}.zip")
            except Exception as e: st.error(f"Generation Error: {e}")

# ----------------------------------------------------
# TAB 7: CoE DASHBOARD
# ----------------------------------------------------
with t7:
    st.subheader("📊 Institutional Analytics Dashboard")
    if st.button("🔄 Refresh Statistics", type="primary"):
        with st.spinner("Compiling institutional metrics..."):
            try:
                res_data = fetch_all_records("student_results", filters={"cycle_id": selected_cycle_id})
                if not res_data: st.warning("No data available.")
                else:
                    df = pd.DataFrame(res_data)
                    stu_data = fetch_all_records("master_students", "usn, branch_code")
                    branch_map = {str(r['usn']).strip().upper(): r.get('branch_code', 'UNKNOWN') for r in stu_data}
                    df['Branch'] = df['usn'].map(branch_map)

                    total_evals = len(df)
                    pending_evals = len(df[df['grade'].isin(['PND', 'PENDING'])])
                    failed_evals = len(df[df['grade'] == 'F'])
                    passed_evals = total_evals - pending_evals - failed_evals
                    completed_evals = total_evals - pending_evals
                    pass_pct = (passed_evals / completed_evals * 100) if completed_evals > 0 else 0
                    
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Total Evaluations", f"{total_evals:,}")
                    col2.metric("Pending SEE Marks", f"{pending_evals:,}", delta="-Requires Action" if pending_evals > 0 else "All Clear", delta_color="inverse")
                    col3.metric("Evaluated Pass Rate", f"{pass_pct:.1f}%")
                    col4.metric("Total Fails", f"{failed_evals:,}")
                    
                    st.markdown("---")
                    chart_col1, chart_col2 = st.columns(2)
                    with chart_col1:
                        st.markdown("##### 📈 Grade Distribution")
                        df_graded = df[~df['grade'].isin(['PND', 'PENDING'])]
                        if not df_graded.empty:
                            grade_counts = df_graded['grade'].value_counts().reset_index()
                            grade_counts.columns = ['Grade', 'Count']
                            grade_order = ['O', 'A+', 'A', 'B+', 'B', 'C', 'P', 'F', 'AB', 'MP']
                            grade_counts['Grade'] = pd.Categorical(grade_counts['Grade'], categories=grade_order, ordered=True)
                            st.bar_chart(grade_counts.sort_values('Grade').set_index('Grade')['Count'], color="#4CAF50")

                    with chart_col2:
                        st.markdown("##### 🏢 Branch-wise Pass Rates")
                        branch_stats = []
                        for branch, group in df_graded.groupby('Branch'):
                            b_total = len(group)
                            b_pass = len(group[group['is_pass'] == True])
                            branch_stats.append({'Branch': branch, 'Pass Rate %': (b_pass / b_total) * 100 if b_total > 0 else 0})
                        if branch_stats: st.bar_chart(pd.DataFrame(branch_stats).set_index('Branch')['Pass Rate %'], color="#2196F3")

                    st.markdown("---")
                    st.subheader("⚠️ Actionable Alerts")
                    pending_df = df[df['grade'].isin(['PND', 'PENDING'])]
                    if not pending_df.empty:
                        for course, count in pending_df['course_code'].value_counts().items():
                            st.error(f"Missing SEE Marks for **{count}** students in subject **{course}**.")
                    else: st.success("🎉 All clear! All evaluated subjects have full marks uploaded.")
            except Exception as e: st.error(f"Dashboard Error: {e}")

# ----------------------------------------------------
# TAB 8: ARREAR & MAKE-UP ENGINE
# ----------------------------------------------------
with t8:
    st.subheader("⚙️ Arrear & Make-up Exam Manager")
    
    # Check the database for the Smart Parent Link
    cycle_info = supabase.table("exam_cycles").select("exam_type, parent_cycle_id").eq("cycle_id", selected_cycle_id).execute().data
    parent_id = cycle_info[0].get("parent_cycle_id") if cycle_info else None
    
    if parent_id:
        st.success(f"🔗 **Smart Link Active:** This cycle is officially linked to **Parent Cycle ID: {parent_id}**.")
        st.info("The system can automatically cross-reference all Make-up registrations and pull their historical CIE marks in one click.")
        
        # --- BULK SYNC FEATURE (ENTERPRISE UPGRADE) ---
        if st.button("🔄 1-Click Auto-Sync All Make-up Registrations", type="primary"):
            with st.spinner("Fetching registrations and cross-referencing parent cycle..."):
                try:
                    # 1. Get all students registered for this current Make-up cycle
                    current_regs = fetch_all_records("course_registrations", "usn, course_code", {"cycle_id": selected_cycle_id})
                    
                    if not current_regs:
                        st.warning("No students are currently registered for this Make-up cycle.")
                    else:
                        # 2. Fetch all results from the Parent Cycle
                        parent_results = fetch_all_records("student_results", "usn, course_code, cie_marks", {"cycle_id": parent_id})
                        # Create a quick lookup dictionary: {(USN, Course): CIE}
                        parent_dict = {(str(r['usn']).strip().upper(), str(r['course_code']).strip().upper()): safe_float(r.get('cie_marks'), 0) for r in parent_results}
                        
                        updates = []
                        missing_history = 0
                        
                        # 3. Match registrations to historical marks
                        for reg in current_regs:
                            u = str(reg['usn']).strip().upper()
                            c = str(reg['course_code']).strip().upper()
                            
                            if (u, c) in parent_dict:
                                updates.append({
                                    "cycle_id": selected_cycle_id,
                                    "usn": u,
                                    "course_code": c,
                                    "cie_marks": parent_dict[(u, c)],
                                    "exam_status": "PENDING" # Reset SEE for the new exam
                                })
                            else:
                                missing_history += 1
                                
                        # 4. Bulk Upsert
                        if updates:
                            for i in range(0, len(updates), 500):
                                supabase.table("student_results").upsert(updates[i:i+500]).execute()
                            st.success(f"✅ Successfully synced historical CIE marks for {len(updates)} registered students! Their SEE status is now set to PENDING.")
                            if missing_history > 0:
                                st.warning(f"⚠️ {missing_history} registered students did not have historical CIE marks in the parent cycle.")
                        else:
                            st.error("Could not find any matching historical CIE marks for the registered students.")
                except Exception as e:
                    st.error(f"Sync failed: {e}")
                    
        st.divider()
    else:
        st.warning("⚠️ This active cycle is NOT linked to a Parent Cycle. You must manually enter the Parent Cycle ID for each student, or update the cycle settings.")

    # --- INDIVIDUAL PULL FEATURE (MANUAL OVERRIDE) ---
    st.markdown("#### 👤 Individual Student Pull (Manual Override)")
    with st.form("makeup_engine"):
        col_m1, col_m2, col_m3 = st.columns(3)
        mu_usn = col_m1.text_input("Student USN").strip().upper()
        mu_cc = col_m2.text_input("Course Code").strip().upper()
        
        # Disable parent input if smart link is active to prevent typos
        if parent_id:
            manual_parent = str(parent_id)
            col_m3.text_input("Parent Cycle ID", value=manual_parent, disabled=True)
        else:
            manual_parent = col_m3.text_input("Parent Cycle ID (Required)").strip()
            
        if st.form_submit_button("🔁 Pull Single CIE"):
            if not mu_usn or not mu_cc or not manual_parent:
                st.error("All fields are required.")
            else:
                regs = supabase.table("course_registrations").select("*").eq("cycle_id", selected_cycle_id).eq("usn", mu_usn).eq("course_code", mu_cc).execute().data
                if not regs:
                    st.error(f"❌ Student {mu_usn} is not officially registered for {mu_cc} in the current Make-up cycle.")
                else:
                    parent_record = supabase.table("student_results").select("cie_marks").eq("cycle_id", manual_parent).eq("usn", mu_usn).eq("course_code", mu_cc).execute().data
                    if not parent_record:
                        st.error(f"❌ Could not find a historical record for {mu_usn} in Parent Cycle {manual_parent}.")
                    else:
                        old_cie = safe_float(parent_record[0].get('cie_marks'), 0)
                        new_record = {
                            "cycle_id": selected_cycle_id,
                            "usn": mu_usn,
                            "course_code": mu_cc,
                            "cie_marks": old_cie,
                            "exam_status": "PENDING"
                        }
                        try:
                            supabase.table("student_results").upsert(new_record).execute()
                            st.success(f"✅ Success! Pulled historical CIE mark ({old_cie}) into Current Cycle. SEE is now PENDING.")
                        except Exception as e:
                            st.error(f"Database Error: {e}")

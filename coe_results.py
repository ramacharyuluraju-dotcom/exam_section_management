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

# ==========================================
# 2. UNIVERSAL GRADING ALGORITHM
# ==========================================
def apply_grading_rules(cie_raw, see_raw, status, credits, max_cie=50, max_see=50, exam_conducted_for=100, is_pg=False):
    if status in ['PENDING', 'PND'] or not status: 
        return 0, cie_raw, 'PND', 0, False
        
    if status in ['ABSENT', 'AB']: return 0, 0, 'AB', 0, False
    if status in ['MALPRACTICE', 'MP']: return 0, 0, 'MP', 0, False
    if status in ['WITHHELD', 'WH']: return 0, 0, 'WH', 0, False

    cie = math.ceil(float(cie_raw)) if pd.notna(cie_raw) else 0.0
    see_raw = float(see_raw) if pd.notna(see_raw) else 0.0
    
    is_internal_only = (max_see == 0)
    
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
        if is_pass: return see_scaled, total, 'PP', 0, True  
        else: return see_scaled, total, 'NP', 0, False 

    if not is_pass: return see_scaled, total, 'F', 0, False
        
    total_max = max_cie + max_see
    pct = total / total_max
    
    if is_pg:
        if pct >= 0.90: return see_scaled, total, 'O', 10, True
        elif pct >= 0.80: return see_scaled, total, 'A+', 9, True
        elif pct >= 0.70: return see_scaled, total, 'A', 8, True
        elif pct >= 0.60: return see_scaled, total, 'B+', 7, True
        elif pct >= 0.55: return see_scaled, total, 'B', 6, True
        elif pct >= 0.50: return see_scaled, total, 'C', 5, True
        else: return see_scaled, total, 'F', 0, False 
    else:
        if pct >= 0.90: return see_scaled, total, 'O', 10, True
        elif pct >= 0.80: return see_scaled, total, 'A+', 9, True
        elif pct >= 0.70: return see_scaled, total, 'A', 8, True
        elif pct >= 0.60: return see_scaled, total, 'B+', 7, True
        elif pct >= 0.50: return see_scaled, total, 'B', 6, True
        elif pct >= 0.45: return see_scaled, total, 'C', 5, True
        elif pct >= 0.40: return see_scaled, total, 'P', 4, True
        else: return see_scaled, total, 'F', 0, False

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

t1, t2, t3, t4, t5, t6 = st.tabs([
    "1. CIE Consolidator", 
    "2. Bundle Decoder", 
    "3. SEE Consolidator", 
    "4. Grading Engine", 
    "5. Moderation", 
    "6. Publish Ledgers"
])

# ----------------------------------------------------
# TAB 1: CIE ENTRY (Secured by Registration Firewall)
# ----------------------------------------------------
with t1:
    st.subheader("Department Internals (CIE) Consolidation")
    st.info("Marks are securely cross-checked against official Course Registrations for this cycle.")
    col_c1, col_c2 = st.columns(2)
    
    with col_c1:
        st.markdown("**Bulk CSV Upload**")
        f_cie = st.file_uploader("Upload CSV (Required: usn, course_code, cie_marks)", type='csv', key="cie_up")
        if f_cie and st.button("🚀 Process Bulk CIE"):
            df_cie = pd.read_csv(f_cie)
            usn_col = find_column(df_cie, ['usn', 'student id'])
            cc_col = find_column(df_cie, ['course_code', 'course code', 'subject code'])
            m_col = find_column(df_cie, ['cie_marks', 'cie', 'ia marks', 'internals'])
            
            if not (usn_col and cc_col and m_col):
                st.error("Missing standard columns. Ensure USN, Course Code, and CIE Marks exist.")
            else:
                with st.spinner("Validating against registrations..."):
                    # 🟢 THE REGISTRATION FIREWALL 🟢
                    regs = supabase.table("course_registrations").select("usn, course_code").eq("cycle_id", selected_cycle_id).execute().data
                    valid_pairs = set((str(r['usn']).strip().upper(), str(r['course_code']).strip().upper()) for r in regs)
                    
                    records = []
                    ignored_count = 0
                    
                    for _, r in df_cie.iterrows():
                        usn = clean_str(r[usn_col])
                        cc = clean_str(r[cc_col])
                        
                        if (usn, cc) in valid_pairs:
                            records.append({
                                "cycle_id": selected_cycle_id,
                                "usn": usn,
                                "course_code": cc,
                                "cie_marks": float(r[m_col]) if pd.notna(r[m_col]) else 0.0,
                                "exam_status": "PENDING"
                            })
                        else:
                            ignored_count += 1
                            
                    if not records:
                        st.error(f"❌ Upload Failed. None of the {len(df_cie)} records matched registered students for {active_cycle_name}.")
                    else:
                        try:
                            for i in range(0, len(records), 500):
                                supabase.table("student_results").upsert(records[i:i+500]).execute()
                            st.success(f"✅ Successfully uploaded {len(records)} valid CIE records. Marked as PENDING.")
                            if ignored_count > 0:
                                st.warning(f"⚠️ Blocked {ignored_count} records (Students were not registered for those courses in this cycle).")
                        except Exception as e:
                            st.error(f"Database Error: {e}")
                    
    with col_c2:
        st.markdown("**Manual Entry**")
        with st.form("manual_cie"):
            m_usn = st.text_input("USN").strip().upper()
            m_cc = st.text_input("Course Code").strip().upper()
            m_marks = st.number_input("CIE Marks", min_value=0.0, max_value=100.0, value=0.0, step=0.5)
            
            if st.form_submit_button("Save CIE Mark"):
                regs = supabase.table("course_registrations").select("*").eq("cycle_id", selected_cycle_id).eq("usn", m_usn).eq("course_code", m_cc).execute().data
                if not regs:
                    st.error(f"❌ Student {m_usn} is NOT registered for {m_cc} in this cycle.")
                else:
                    try:
                        supabase.table("student_results").upsert({
                            "cycle_id": selected_cycle_id, "usn": m_usn, "course_code": m_cc, 
                            "cie_marks": m_marks, "exam_status": "PENDING"
                        }).execute()
                        st.success("✅ Saved and marked as PENDING.")
                    except Exception as e:
                        st.error(f"Error: {e}")

# ----------------------------------------------------
# TAB 2: BUNDLE DECODER UTILITY (STANDALONE)
# ----------------------------------------------------
with t2:
    st.subheader("🔐 Standalone Bundle Decoder")
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        key_file = st.file_uploader("1. Upload MASTER_SECRET_KEY.xlsx", type=['xlsx'])
    with col_d2:
        bundle_files = st.file_uploader("2. Upload Evaluator Bundles (.xlsx)", type=['xlsx'], accept_multiple_files=True)

    if st.button("🔓 Generate Decoded CSV", type="primary"):
        if not key_file or not bundle_files:
            st.warning("⚠️ Please upload both the Master Key and at least one Evaluator Bundle.")
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
                                    header_idx = idx
                                    break
                            
                            if header_idx == -1: continue
                            df_bun = pd.read_excel(f, sheet_name='Marks Entry', header=header_idx)
                            dummy_col = next((c for c in df_bun.columns if "DUMMY" in str(c).upper() or "CODING" in str(c).upper()), None)
                            marks_col = next((c for c in df_bun.columns if "FINAL SEE" in str(c).upper()), None)
                            if not marks_col: marks_col = next((c for c in df_bun.columns if "TOTAL SEE" in str(c).upper()), None)
                            
                            if dummy_col and marks_col:
                                for _, r in df_bun.iterrows():
                                    d_id = str(r[dummy_col]).strip().upper()
                                    m_val = r[marks_col]
                                    if len(d_id) > 2 and d_id != "NAN":
                                        extracted_data.append({'Dummy_ID': d_id, 'SEE_Raw_Val': m_val})
                        except: pass
                    
                    if extracted_data:
                        marks_df = pd.DataFrame(extracted_data)
                        final_df = pd.merge(key_df, marks_df, on='Dummy_ID', how='inner')
                        processed_records = []
                        for _, r in final_df.iterrows():
                            raw_val = r.get('SEE_Raw_Val', '')
                            m_val = str(raw_val).strip().upper()
                            stat = "PRESENT"
                            raw_see = 0.0
                            
                            if m_val in ['AB', 'ABSENT']: stat = 'ABSENT'
                            elif m_val in ['MP', 'MAL', 'MALPRACTICE']: stat = 'MALPRACTICE'
                            elif m_val in ['WH', 'WITHHELD']: stat = 'WITHHELD'
                            elif m_val == 'NAN' or m_val == '': stat = 'PRESENT'
                            else:
                                try: 
                                    raw_see = float(m_val)
                                    if math.isnan(raw_see): raw_see = 0.0
                                except ValueError: raw_see = 0.0
                                    
                            processed_records.append({
                                "usn": clean_str(r['USN']), "course_code": clean_str(r['Subject']),
                                "see_marks": raw_see, "status": stat
                            })
                            
                        out_df = pd.DataFrame(processed_records)
                        csv_buffer = io.StringIO()
                        out_df.to_csv(csv_buffer, index=False)
                        st.success(f"✅ Successfully decoded {len(out_df)} records!")
                        st.download_button(label="📥 Download Decoded SEE CSV", data=csv_buffer.getvalue(), file_name="Decoded_SEE_Marks.csv", mime="text/csv", type="primary")
                    else: st.error("No valid marks data extracted from bundles.")
                except Exception as e: st.error(f"Error: {e}")

# ----------------------------------------------------
# TAB 3: SEE CONSOLIDATION (Secured by Registration Firewall)
# ----------------------------------------------------
with t3:
    st.subheader("SEE Marks Consolidation")
    st.info("Marks are securely cross-checked against official Course Registrations for this cycle.")
    col_s1, col_s2 = st.columns(2)
    
    with col_s1:
        st.markdown("**Bulk CSV Upload**")
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
                    # 🟢 THE REGISTRATION FIREWALL 🟢
                    regs = supabase.table("course_registrations").select("usn, course_code").eq("cycle_id", selected_cycle_id).execute().data
                    valid_pairs = set((str(r['usn']).strip().upper(), str(r['course_code']).strip().upper()) for r in regs)
                    
                    records = []
                    ignored_count = 0
                    
                    for _, r in df_see.iterrows():
                        usn = clean_str(r[usn_col])
                        cc = clean_str(r[cc_col])
                        
                        if (usn, cc) in valid_pairs:
                            stat = clean_str(r[stat_col]) if stat_col else "PRESENT"
                            m_val = str(r[m_col]).strip().upper()
                            raw_see = 0.0
                            
                            if m_val in ['AB', 'ABSENT']: stat = 'ABSENT'
                            elif m_val in ['MP', 'MAL']: stat = 'MALPRACTICE'
                            elif m_val in ['WH']: stat = 'WITHHELD'
                            else:
                                try: raw_see = float(m_val)
                                except: raw_see = 0.0

                            records.append({
                                "cycle_id": selected_cycle_id,
                                "usn": usn,
                                "course_code": cc,
                                "see_raw": raw_see,
                                "exam_status": stat 
                            })
                        else:
                            ignored_count += 1
                            
                    if not records:
                        st.error(f"❌ Upload Failed. None of the {len(df_see)} records matched registered students for {active_cycle_name}.")
                    else:
                        try:
                            for i in range(0, len(records), 500):
                                supabase.table("student_results").upsert(records[i:i+500]).execute()
                            st.success(f"✅ Successfully uploaded {len(records)} valid SEE records.")
                            if ignored_count > 0:
                                st.warning(f"⚠️ Blocked {ignored_count} records (Students were not registered for those courses in this cycle).")
                        except Exception as e: st.error(f"Database Error: {e}")

    with col_s2:
        st.markdown("**Manual Entry**")
        with st.form("manual_see"):
            s_usn = st.text_input("USN").strip().upper()
            s_cc = st.text_input("Course Code").strip().upper()
            s_marks = st.number_input("SEE Marks (Raw Paper Score)", min_value=0.0, max_value=100.0, value=0.0)
            s_stat = st.selectbox("Status", ["PRESENT", "ABSENT", "MALPRACTICE", "WITHHELD"])
            
            if st.form_submit_button("Save SEE Mark"):
                regs = supabase.table("course_registrations").select("*").eq("cycle_id", selected_cycle_id).eq("usn", s_usn).eq("course_code", s_cc).execute().data
                if not regs:
                    st.error(f"❌ Student {s_usn} is NOT registered for {s_cc} in this cycle.")
                else:
                    try:
                        supabase.table("student_results").upsert({
                            "cycle_id": selected_cycle_id, "usn": s_usn, "course_code": s_cc, 
                            "see_raw": s_marks, "exam_status": s_stat
                        }).execute()
                        st.success("✅ Saved to Database.")
                    except Exception as e: st.error(f"Error: {e}")

# ----------------------------------------------------
# TAB 4: GRADING ENGINE 
# ----------------------------------------------------
with t4:
    st.subheader("Result & Grading Processor")
    if st.button("⚙️ Execute Master Grading Algorithm", type="primary"):
        with st.spinner("Fetching rules and Calculating Totals..."):
            try:
                raw_res = supabase.table("student_results").select("*").eq("cycle_id", selected_cycle_id).execute()
                if not raw_res.data:
                    st.error("No marks found for this cycle. Complete CIE and SEE entry first.")
                    st.stop()
                    
                stu_res = supabase.table("master_students").select("usn, branch_code").execute()
                branch_map = {str(r['usn']).strip().upper(): r['branch_code'] for r in stu_res.data}
                
                branch_res = supabase.table("master_branches").select("branch_code, program_type").execute()
                pg_branches = [r['branch_code'] for r in branch_res.data if str(r['program_type']).upper() == 'PG']

                crs_res = supabase.table("master_courses").select("course_code, credits, max_see, max_cie, total_marks").execute()
                credit_map = {r['course_code']: float(r['credits'] or 0) for r in crs_res.data}
                max_see_map = {r['course_code']: float(r['max_see'] or 50) for r in crs_res.data}
                max_cie_map = {r['course_code']: float(r['max_cie'] or 50) for r in crs_res.data}
                paper_max_map = {r['course_code']: float(r['total_marks'] or 100) for r in crs_res.data}
                
                updates = []
                for row in raw_res.data:
                    usn = str(row['usn']).strip().upper()
                    cc = row['course_code']
                    
                    cred = credit_map.get(cc, 4.0) if cc in credit_map else 4.0
                    m_see = max_see_map.get(cc, 50.0) 
                    m_cie = max_cie_map.get(cc, 50.0)
                    conducted_for = paper_max_map.get(cc, 100.0)
                    
                    student_branch = branch_map.get(usn, "")
                    is_pg = student_branch in pg_branches
                    
                    status = row.get('exam_status')
                    if not status: status = 'PENDING'
                    
                    scaled_see, tot, grd, gp, is_pass = apply_grading_rules(
                        row['cie_marks'], row['see_raw'], status, 
                        cred, m_cie, m_see, conducted_for, is_pg
                    )
                    earned = cred if is_pass else 0.0
                    
                    updates.append({
                        "cycle_id": selected_cycle_id, "usn": usn, "course_code": cc,
                        "see_scaled": scaled_see, "total_marks": tot, "grade": grd,
                        "grade_points": gp, "credits_earned": earned, "is_pass": is_pass
                    })
                    
                for i in range(0, len(updates), 500):
                    supabase.table("student_results").upsert(updates[i:i+500]).execute()
                    
                st.success(f"✅ Grading calculated for {len(updates)} records successfully!")
            except Exception as e: st.error(f"Error during calculation: {e}")

# ----------------------------------------------------
# TAB 5: MODERATION (GRACE MARKS)
# ----------------------------------------------------
with t5:
    st.subheader("⚖️ Moderation & Grace Marks")
    mod_usn = st.text_input("Enter Student USN to review failing subjects:").strip().upper()
    if mod_usn:
        try:
            fail_res = supabase.table("student_results").select("*").eq("cycle_id", selected_cycle_id).eq("usn", mod_usn).eq("is_pass", False).execute()
            if not fail_res.data: st.success(f"🎉 Student {mod_usn} has no failing subjects in this cycle!")
            else:
                actual_fails = [r for r in fail_res.data if r['grade'] != 'PND']
                if not actual_fails: st.warning(f"Student {mod_usn} is PENDING in their subjects. Cannot apply grace marks until SEE marks are uploaded.")
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
                        c_cie, c_see, c_tot, c_grade = r['cie_marks'], r['see_raw'], r['total_marks'], r['grade']
                        
                        with st.expander(f"⚠️ {cc} - {title} (Current Grade: {c_grade})"):
                            st.markdown(f"**Current Marks:** CIE: `{c_cie}` | SEE Raw: `{c_see}` | Scaled SEE: `{r['see_scaled']}` | Total: `{c_tot}`")
                            with st.form(f"grace_form_{cc}"):
                                col_m1, col_m2 = st.columns(2)
                                grace_target = col_m1.radio("Add Grace Marks To:", ["SEE Exam", "CIE (Internals)"])
                                grace_marks = col_m2.number_input("Grace Marks to Add", min_value=1.0, max_value=10.0, step=1.0, value=1.0)
                                if st.form_submit_button("✨ Apply Grace Marks & Recalculate"):
                                    new_cie = c_cie + grace_marks if grace_target == "CIE (Internals)" else c_cie
                                    new_see = c_see + grace_marks if grace_target == "SEE Exam" else c_see
                                    cred = float(mc.get('credits', 4))
                                    m_cie, m_see, conducted_for = float(mc.get('max_cie', 50)), float(mc.get('max_see', 50)), float(mc.get('total_marks', 100))
                                    scaled_see, tot, grd, gp, is_pass = apply_grading_rules(new_cie, new_see, r['exam_status'], cred, m_cie, m_see, conducted_for, is_pg)
                                    update_data = {
                                        "cycle_id": selected_cycle_id, "usn": mod_usn, "course_code": cc,
                                        "cie_marks": new_cie, "see_raw": new_see, "see_scaled": scaled_see,
                                        "total_marks": tot, "grade": grd, "grade_points": gp,
                                        "credits_earned": cred if is_pass else 0.0, "is_pass": is_pass
                                    }
                                    supabase.table("student_results").upsert(update_data).execute()
                                    if is_pass: st.success(f"✅ Grace marks applied! Passed with Grade **{grd}**.")
                                    else: st.warning(f"⚠️ Grace marks applied, but student still failing. New Grade: **{grd}**.")
        except Exception as e: st.error(f"Error fetching data: {e}")

# ----------------------------------------------------
# TAB 6: PUBLISH LEDGERS & CARDS 
# ----------------------------------------------------
with t6:
    st.subheader("Generate Ledgers & Marks Cards")
    st.info("The system automatically checks the `course_registrations` table. Any student missing marks for a registered subject will explicitly show as **PENDING**.")
    
    if st.button("🖨️ Generate Master Ledger & PDFs"):
        with st.spinner("Compiling institutional ledgers against Registrations..."):
            try:
                regs_data = supabase.table("course_registrations").select("usn, course_code").eq("cycle_id", selected_cycle_id).execute().data
                if not regs_data:
                    st.error("No course registrations found for this cycle. Cannot compile ledgers.")
                    st.stop()
                
                stu_courses = {}
                for r in regs_data:
                    u = str(r['usn']).strip().upper()
                    c = str(r['course_code']).strip().upper()
                    if u not in stu_courses: stu_courses[u] = []
                    stu_courses[u].append(c)

                res_data = supabase.table("student_results").select("*").eq("cycle_id", selected_cycle_id).execute().data
                res_map = {(str(r['usn']).strip().upper(), str(r['course_code']).strip().upper()): r for r in res_data}
                
                stu_res = supabase.table("master_students").select("usn, full_name, branch_code").execute().data
                name_map = {str(r['usn']).strip().upper(): (r.get('full_name') or "Unknown Student") for r in stu_res}
                branch_map = {str(r['usn']).strip().upper(): (r.get('branch_code') or "UNKNOWN_BRANCH") for r in stu_res}
                
                crs_res = supabase.table("master_courses").select("course_code, title, credits").execute().data
                crs_map = {str(c['course_code']).strip().upper(): c for c in crs_res}
                
                ledger_rows = []
                pdf_zip_buffer = io.BytesIO()
                
                with zipfile.ZipFile(pdf_zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for usn, courses in stu_courses.items():
                        name = name_map.get(usn, "Unknown")
                        branch = branch_map.get(usn, "UNKNOWN_BRANCH")
                        
                        total_cr_attempted = 0.0
                        total_gp_earned = 0.0
                        results_list = []
                        
                        ledger_dict = {'USN': usn, 'Name': name, 'Branch': branch}
                        pass_flag = True
                        has_pending = False
                        
                        for cc in courses:
                            mc = crs_map.get(cc, {})
                            title = mc.get('title', cc)
                            cr = float(mc.get('credits', 0))
                            
                            r = res_map.get((usn, cc))
                            
                            if not r or r.get('exam_status') == 'PENDING' or r.get('grade') == 'PND':
                                has_pending = True
                                cie_disp = str(r['cie_marks']) if (r and r.get('cie_marks') > 0) else "PENDING"
                                results_list.append({
                                    'code': cc, 'title': title, 'cr': cr,
                                    'cie': cie_disp, 'see': "PENDING", 'tot': "PENDING",
                                    'grade': "PENDING", 'gp': "-", 'pass': False
                                })
                                ledger_dict[f"{cc}_Tot"] = "PENDING"
                                ledger_dict[f"{cc}_Grd"] = "PENDING"
                            else:
                                results_list.append({
                                    'code': cc, 'title': title, 'cr': cr,
                                    'cie': str(r['cie_marks']), 'see': str(r['see_scaled']), 'tot': str(r['total_marks']),
                                    'grade': str(r['grade']), 'gp': str(r['grade_points']), 'pass': r['is_pass']
                                })
                                ledger_dict[f"{cc}_Tot"] = r['total_marks']
                                ledger_dict[f"{cc}_Grd"] = r['grade']
                                
                                total_cr_attempted += cr
                                total_gp_earned += (r['grade_points'] * cr)
                                if not r['is_pass']: pass_flag = False
                            
                        sgpa = (total_gp_earned / total_cr_attempted) if total_cr_attempted > 0 else 0.0
                        ledger_dict['SGPA'] = round(sgpa, 2) if not has_pending else "---"
                        
                        if has_pending: ledger_dict['Result'] = "PENDING"
                        else: ledger_dict['Result'] = "PASS" if pass_flag else "FAIL"
                        
                        ledger_rows.append(ledger_dict)
                        
                        pdf_buf = io.BytesIO()
                        generate_marks_card_pdf(pdf_buf, usn, name, results_list, sgpa, has_pending)
                        zf.writestr(f"Marks_Cards/{usn}.pdf", pdf_buf.getvalue())
                        
                df_ledger = pd.DataFrame(ledger_rows)
                
                ledger_zip_buffer = io.BytesIO()
                with zipfile.ZipFile(ledger_zip_buffer, "w", zipfile.ZIP_DEFLATED) as branch_zf:
                    for branch_name, branch_df in df_ledger.groupby('Branch'):
                        safe_branch = str(branch_name).replace("/", "_").replace("\\", "_")
                        branch_df_clean = branch_df.dropna(axis=1, how='all')
                        
                        branch_excel_buf = io.BytesIO()
                        with pd.ExcelWriter(branch_excel_buf, engine='xlsxwriter') as writer:
                            branch_df_clean.to_excel(writer, sheet_name=safe_branch[:31], index=False)
                            
                        branch_zf.writestr(f"Ledger_{safe_branch}.xlsx", branch_excel_buf.getvalue())
                
                st.success("✅ Ledgers and PDFs Generated successfully!")
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.download_button("📊 Download Branch Ledgers (.zip)", ledger_zip_buffer.getvalue(), f"Branch_Ledgers_{active_cycle_name}.zip", "application/zip")
                with col_d2:
                    st.download_button("📄 Download Marks Cards (.zip)", pdf_zip_buffer.getvalue(), f"Marks_Cards_{active_cycle_name}.zip", "application/zip")
                    
            except Exception as e:
                st.error(f"Generation Error: {e}")

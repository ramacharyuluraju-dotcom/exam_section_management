import streamlit as st
import pandas as pd
import io
import math
import zipfile
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

# --- GLOBAL CONTEXT ---
# Pulls the active cycle directly from the session state managed by app.py
selected_cycle_id = st.session_state.get('active_cycle_id')

def clean_str(val):
    return str(val).strip().upper() if pd.notna(val) else ""

def find_column(df, candidates):
    cols = [c.upper().strip() for c in df.columns]
    for candidate in candidates:
        if candidate.upper() in cols:
            return df.columns[cols.index(candidate.upper())]
    return None

# ==========================================
# 2. BULLETPROOF GRADING ALGORITHM
# ==========================================
def apply_grading_rules(cie_raw, see_raw, status, credits, max_cie=50, max_see=50):
    """Bulletproof VTU/Autonomous Rules (Handles Projects, MNCs, & Decimals)"""
    
    # 1. Exception Cases
    if status in ['ABSENT', 'AB']: return 0, 0, 'AB', 0, False
    if status in ['MALPRACTICE', 'MP']: return 0, 0, 'MP', 0, False
    if status in ['WITHHELD', 'WH']: return 0, 0, 'WH', 0, False

    # 2. Decimal Rounding (VTU rule: round up fractions for internals)
    cie = math.ceil(float(cie_raw)) if pd.notna(cie_raw) else 0.0
    see_raw = float(see_raw) if pd.notna(see_raw) else 0.0
    
    is_internal_only = (max_see == 0)
    
    # 3. DYNAMIC SCALING (The Project/Internship Fix)
    if is_internal_only:
        see_scaled = 0
    elif max_see == 50 and see_raw > 50: 
        see_scaled = math.ceil(see_raw / 2) # Standard 100 -> 50 scaling
    else:
        see_scaled = math.ceil(see_raw) # E.g., Major Project is 100 SEE, no scaling needed

    total = cie + see_scaled

    # 4. Minimum Passing Rules (Dynamic based on course profile)
    is_pass = True
    if is_internal_only:
        # Pass requires 40% of the maximum CIE marks
        if cie < (0.40 * max_cie): 
            is_pass = False
    else:
        # Dynamic Triple Lock: 40% in CIE, 35% in SEE, 40% Overall
        min_cie_req = math.ceil(0.40 * max_cie)
        min_see_req = math.ceil(0.35 * max_see)
        min_total_req = math.ceil(0.40 * (max_cie + max_see))
        
        if cie < min_cie_req or see_scaled < min_see_req or total < min_total_req:
            is_pass = False

    # 5. Mandatory Non-Credit (MNC) Handling
    if credits == 0:
        if is_pass:
            return see_scaled, total, 'PP', 0, True  # Pass
        else:
            return see_scaled, total, 'NP', 0, False # Not Pass

    # 6. Standard 10-Point Grading Scale
    if not is_pass:
        return see_scaled, total, 'F', 0, False
        
    total_max = max_cie + max_see
    
    if total >= (0.90 * total_max): return see_scaled, total, 'O', 10, True
    elif total >= (0.80 * total_max): return see_scaled, total, 'A+', 9, True
    elif total >= (0.70 * total_max): return see_scaled, total, 'A', 8, True
    elif total >= (0.60 * total_max): return see_scaled, total, 'B+', 7, True
    elif total >= (0.50 * total_max): return see_scaled, total, 'B', 6, True
    elif total >= (0.45 * total_max): return see_scaled, total, 'C', 5, True
    else: return see_scaled, total, 'P', 4, True

# ==========================================
# 3. PDF MARKS CARD GENERATOR
# ==========================================
def generate_marks_card_pdf(buffer, usn, name, results_list, sgpa, logo_bytes=None):
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    elements = []
    styles = getSampleStyleSheet()
    
    style_center = ParagraphStyle('Center', parent=styles['Heading1'], alignment=1, fontSize=16, spaceAfter=10)
    style_sub = ParagraphStyle('Sub', parent=styles['Heading3'], alignment=1, fontSize=12, spaceAfter=5)
    
    elements.append(Paragraph("AMC ENGINEERING COLLEGE", style_center))
    elements.append(Paragraph("Autonomous Institution Affiliated to VTU, Belagavi", style_sub))
    elements.append(Paragraph(f"Provisional Result Sheet - {st.session_state.get('active_cycle_name', 'Examination')}", style_sub))
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
        color = colors.red if row['grade'] in ['F', 'NP', 'AB', 'WH', 'MP'] else colors.green
        style_cmds.append(('TEXTCOLOR', (6, i+1), (6, i+1), color))
        
    t.setStyle(TableStyle(style_cmds))
    elements.append(t); elements.append(Spacer(1, 20))
    
    pass_fail = "PASS" if all(r['pass'] for r in results_list) else "FAIL"
    t_total = Table([[f"SGPA: {sgpa:.2f}", f"Result: {pass_fail}"]], colWidths=[250, 250])
    t_total.setStyle(TableStyle([
        ('ALIGN', (1,0), (1,0), 'RIGHT'), 
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'), 
        ('TEXTCOLOR', (1,0), (1,0), colors.red if pass_fail == "FAIL" else colors.green)
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
    st.warning("⚠️ Please select an Active Exam Cycle in the Sidebar to proceed.")
    st.stop()

st.title("🏆 Results & Grading Engine")

t1, t2, t3, t4, t5 = st.tabs([
    "1. CIE Entry", 
    "2. SEE Consolidator", 
    "3. Grading Engine", 
    "4. Moderation", 
    "5. Publish Ledgers"
])

# ----------------------------------------------------
# TAB 1: CIE ENTRY
# ----------------------------------------------------
with t1:
    st.subheader("Department Internals (CIE)")
    st.write("Upload a CSV from the department or enter marks manually.")
    
    col_c1, col_c2 = st.columns(2)
    
    with col_c1:
        st.markdown("**Bulk CSV Upload**")
        f_cie = st.file_uploader("Upload CSV (Required: usn, course_code, cie_marks)", type='csv')
        if f_cie and st.button("🚀 Process Bulk CIE"):
            df_cie = pd.read_csv(f_cie)
            
            usn_col = find_column(df_cie, ['usn', 'student id'])
            cc_col = find_column(df_cie, ['course_code', 'course code', 'subject code'])
            m_col = find_column(df_cie, ['cie_marks', 'cie', 'ia marks', 'internals'])
            
            if not (usn_col and cc_col and m_col):
                st.error("Missing standard columns. Please ensure USN, Course Code, and CIE Marks exist.")
            else:
                records = []
                for _, r in df_cie.iterrows():
                    records.append({
                        "cycle_id": selected_cycle_id,
                        "usn": clean_str(r[usn_col]),
                        "course_code": clean_str(r[cc_col]),
                        "cie_marks": float(r[m_col]) if pd.notna(r[m_col]) else 0.0
                    })
                
                try:
                    supabase.table("student_results").upsert(records).execute()
                    st.success(f"✅ Successfully uploaded {len(records)} CIE records.")
                except Exception as e:
                    st.error(f"Database Error: {e}")
                    
    with col_c2:
        st.markdown("**Manual Entry**")
        with st.form("manual_cie"):
            m_usn = st.text_input("USN").strip().upper()
            m_cc = st.text_input("Course Code").strip().upper()
            m_marks = st.number_input("CIE Marks", min_value=0.0, max_value=100.0, value=0.0, step=0.5)
            
            if st.form_submit_button("Save CIE Mark"):
                try:
                    supabase.table("student_results").upsert({
                        "cycle_id": selected_cycle_id,
                        "usn": m_usn,
                        "course_code": m_cc,
                        "cie_marks": m_marks
                    }).execute()
                    st.success("✅ Saved.")
                except Exception as e:
                    st.error(f"Error: {e}")

# ----------------------------------------------------
# TAB 2: SEE CONSOLIDATOR (DECODER)
# ----------------------------------------------------
with t2:
    st.subheader("SEE Evaluator Decoder")
    st.info("Upload the Master Key and Evaluator Bundles. The system will decode the Dummy IDs and save SEE marks.")
    
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        key_file = st.file_uploader("Upload MASTER_SECRET_KEY.xlsx", type=['xlsx'])
    with col_s2:
        bundle_files = st.file_uploader("Upload Filled Evaluator Bundles", type=['xlsx'], accept_multiple_files=True)

    if st.button("🔓 Decode and Save SEE Marks", type="primary"):
        if not key_file or not bundle_files:
            st.warning("Please upload both the Master Key and at least one bundle.")
        else:
            with st.spinner("Decoding bundles..."):
                key_df = pd.read_excel(key_file)
                key_df['Dummy_ID'] = key_df['Dummy_ID'].astype(str).str.strip()
                
                extracted = []
                for f in bundle_files:
                    try:
                        df_preview = pd.read_excel(f, sheet_name='Marks Entry', header=None, nrows=10)
                        header_idx = -1
                        for idx, row in df_preview.iterrows():
                            if any("DUMMY NO" in str(x).upper() for x in row.tolist()):
                                header_idx = idx
                                break
                                
                        if header_idx == -1: continue
                            
                        df_bun = pd.read_excel(f, sheet_name='Marks Entry', header=header_idx)
                        dummy_col = next((c for c in df_bun.columns if "DUMMY" in str(c).upper()), None)
                        marks_col = next((c for c in df_bun.columns if "Total SEE" in str(c)), None)
                        
                        if dummy_col and marks_col:
                            for _, r in df_bun.iterrows():
                                d_id = str(r[dummy_col]).strip()
                                m = r[marks_col]
                                if len(d_id) > 2 and d_id.upper() != "NAN":
                                    extracted.append({'Dummy_ID': d_id, 'SEE_Raw': m})
                    except: pass
                
                if extracted:
                    marks_df = pd.DataFrame(extracted)
                    final_df = pd.merge(key_df, marks_df, on='Dummy_ID', how='inner')
                    
                    records = []
                    for _, r in final_df.iterrows():
                        stat = "PRESENT"
                        raw_see = 0.0
                        m_val = str(r.get('SEE_Raw', '')).strip().upper()
                        
                        if m_val in ['AB', 'ABSENT']: stat = 'ABSENT'
                        elif m_val in ['MP', 'MAL']: stat = 'MALPRACTICE'
                        elif m_val in ['WH']: stat = 'WITHHELD'
                        else:
                            try: raw_see = float(m_val)
                            except: raw_see = 0.0
                            
                        records.append({
                            "cycle_id": selected_cycle_id,
                            "usn": clean_str(r['USN']),
                            "course_code": clean_str(r['Subject']),
                            "see_raw": raw_see,
                            "exam_status": stat
                        })
                        
                    for i in range(0, len(records), 500):
                        supabase.table("student_results").upsert(records[i:i+500]).execute()
                        
                    st.success(f"✅ Decoded {len(records)} entries. SEE marks permanently saved to database.")
                else:
                    st.error("No valid data extracted from bundles.")

# ----------------------------------------------------
# TAB 3: GRADING ENGINE (BULLETPROOF)
# ----------------------------------------------------
with t3:
    st.subheader("Result & Grading Processor")
    st.write(f"Apply autonomous CBCS grading rules to all saved marks for **{st.session_state.get('active_cycle_name')}**.")
    
    if st.button("⚙️ Execute Master Grading Algorithm", type="primary"):
        with st.spinner("Calculating Totals and Grades..."):
            try:
                raw_res = supabase.table("student_results").select("*").eq("cycle_id", selected_cycle_id).execute()
                if not raw_res.data:
                    st.error("No marks found for this cycle. Complete CIE and SEE entry first.")
                    st.stop()
                    
                crs_res = supabase.table("master_courses").select("course_code, credits, max_see, max_cie").execute()
                
                credit_map = {r['course_code']: float(r['credits'] or 0) for r in crs_res.data}
                max_see_map = {r['course_code']: float(r['max_see'] or 50) for r in crs_res.data}
                max_cie_map = {r['course_code']: float(r['max_cie'] or 50) for r in crs_res.data}
                
                updates = []
                for row in raw_res.data:
                    cc = row['course_code']
                    cred = credit_map.get(cc, 0.0)
                    m_see = max_see_map.get(cc, 50.0) 
                    m_cie = max_cie_map.get(cc, 50.0)
                    
                    scaled_see, tot, grd, gp, is_pass = apply_grading_rules(
                        row['cie_marks'], row['see_raw'], row['exam_status'], cred, m_cie, m_see
                    )
                    
                    earned = cred if is_pass else 0.0
                    
                    updates.append({
                        "cycle_id": selected_cycle_id,
                        "usn": row['usn'],
                        "course_code": cc,
                        "see_scaled": scaled_see,
                        "total_marks": tot,
                        "grade": grd,
                        "grade_points": gp,
                        "credits_earned": earned,
                        "is_pass": is_pass
                    })
                    
                for i in range(0, len(updates), 500):
                    supabase.table("student_results").upsert(updates[i:i+500]).execute()
                    
                st.success(f"✅ Grading calculated for {len(updates)} records successfully!")
                
            except Exception as e:
                st.error(f"Error during calculation: {e}")

# ----------------------------------------------------
# TAB 4: MODERATION (GRACE MARKS)
# ----------------------------------------------------
with t4:
    st.subheader("⚖️ Moderation & Grace Marks")
    st.write("Lookup a student and award grace marks to push borderline failures to a Pass.")
    
    mod_usn = st.text_input("Enter Student USN to review failing subjects:").strip().upper()
    
    if mod_usn:
        try:
            # Fetch only failing results for this USN
            fail_res = supabase.table("student_results").select("*, master_courses(title, credits, max_cie, max_see)").eq("cycle_id", selected_cycle_id).eq("usn", mod_usn).eq("is_pass", False).execute()
            
            if not fail_res.data:
                st.success(f"🎉 Student {mod_usn} has no failing subjects in this cycle!")
            else:
                st.warning(f"Found {len(fail_res.data)} failing subject(s) for {mod_usn}.")
                
                for r in fail_res.data:
                    cc = r['course_code']
                    title = r.get('master_courses', {}).get('title', cc) if r.get('master_courses') else cc
                    c_cie = r['cie_marks']
                    c_see = r['see_raw']
                    c_tot = r['total_marks']
                    c_grade = r['grade']
                    
                    with st.expander(f"⚠️ {cc} - {title} (Current Grade: {c_grade})"):
                        st.markdown(f"**Current Marks:** CIE: `{c_cie}` | SEE Raw: `{c_see}` | Scaled SEE: `{r['see_scaled']}` | Total: `{c_tot}`")
                        
                        with st.form(f"grace_form_{cc}"):
                            col_m1, col_m2 = st.columns(2)
                            grace_target = col_m1.radio("Add Grace Marks To:", ["SEE Exam", "CIE (Internals)"])
                            grace_marks = col_m2.number_input("Grace Marks to Add", min_value=1.0, max_value=10.0, step=1.0, value=1.0)
                            
                            if st.form_submit_button("✨ Apply Grace Marks & Recalculate"):
                                new_cie = c_cie + grace_marks if grace_target == "CIE (Internals)" else c_cie
                                new_see = c_see + grace_marks if grace_target == "SEE Exam" else c_see
                                
                                cred = float(r.get('master_courses', {}).get('credits', 0) if r.get('master_courses') else 0)
                                m_cie = float(r.get('master_courses', {}).get('max_cie', 50) if r.get('master_courses') else 50)
                                m_see = float(r.get('master_courses', {}).get('max_see', 50) if r.get('master_courses') else 50)
                                
                                scaled_see, tot, grd, gp, is_pass = apply_grading_rules(
                                    new_cie, new_see, r['exam_status'], cred, m_cie, m_see
                                )
                                
                                update_data = {
                                    "cycle_id": selected_cycle_id,
                                    "usn": mod_usn,
                                    "course_code": cc,
                                    "cie_marks": new_cie,
                                    "see_raw": new_see,
                                    "see_scaled": scaled_see,
                                    "total_marks": tot,
                                    "grade": grd,
                                    "grade_points": gp,
                                    "credits_earned": cred if is_pass else 0.0,
                                    "is_pass": is_pass
                                }
                                
                                supabase.table("student_results").upsert(update_data).execute()
                                
                                if is_pass:
                                    st.success(f"✅ Grace marks applied! Student passed with a new Grade of **{grd}** (Total: {tot}).")
                                else:
                                    st.warning(f"⚠️ Grace marks applied, but the student is still failing. New Grade: **{grd}** (Total: {tot}).")
        except Exception as e:
            st.error(f"Error fetching data: {e}")

# ----------------------------------------------------
# TAB 5: PUBLISH LEDGERS & CARDS
# ----------------------------------------------------
with t5:
    st.subheader("Generate Ledgers & Marks Cards")
    
    if st.button("🖨️ Generate Master Ledger & PDFs"):
        with st.spinner("Compiling institutional ledgers..."):
            try:
                res_data = supabase.table("student_results").select(
                    "usn, course_code, cie_marks, see_scaled, total_marks, grade, grade_points, credits_earned, is_pass, master_courses(title, credits)"
                ).eq("cycle_id", selected_cycle_id).execute()
                
                if not res_data.data:
                    st.error("No graded results found. Run the Grading Engine first.")
                    st.stop()
                    
                stu_res = supabase.table("master_students").select("usn, full_name").execute()
                name_map = {r['usn']: r['full_name'] for r in stu_res.data}
                
                df_res = pd.DataFrame(res_data.data)
                
                ledger_rows = []
                pdf_zip_buffer = io.BytesIO()
                
                with zipfile.ZipFile(pdf_zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for usn, group in df_res.groupby('usn'):
                        name = name_map.get(usn, "Unknown")
                        
                        total_cr_attempted = 0.0
                        total_gp_earned = 0.0
                        results_list = []
                        
                        ledger_dict = {'USN': usn, 'Name': name}
                        pass_flag = True
                        
                        for _, r in group.iterrows():
                            cc = r['course_code']
                            title = r.get('master_courses', {}).get('title', cc) if r.get('master_courses') else cc
                            cr = float(r.get('master_courses', {}).get('credits', 0) if r.get('master_courses') else 0)
                            
                            results_list.append({
                                'code': cc, 'title': title, 'cr': cr,
                                'cie': r['cie_marks'], 'see': r['see_scaled'], 'tot': r['total_marks'],
                                'grade': r['grade'], 'gp': r['grade_points'], 'pass': r['is_pass']
                            })
                            
                            ledger_dict[f"{cc}_Tot"] = r['total_marks']
                            ledger_dict[f"{cc}_Grd"] = r['grade']
                            
                            total_cr_attempted += cr
                            total_gp_earned += (r['grade_points'] * cr)
                            if not r['is_pass']: pass_flag = False
                            
                        sgpa = (total_gp_earned / total_cr_attempted) if total_cr_attempted > 0 else 0.0
                        
                        ledger_dict['SGPA'] = round(sgpa, 2)
                        ledger_dict['Result'] = "PASS" if pass_flag else "FAIL"
                        ledger_rows.append(ledger_dict)
                        
                        pdf_buf = io.BytesIO()
                        generate_marks_card_pdf(pdf_buf, usn, name, results_list, sgpa)
                        zf.writestr(f"Marks_Cards/{usn}.pdf", pdf_buf.getvalue())
                        
                df_ledger = pd.DataFrame(ledger_rows)
                out_excel = io.BytesIO()
                df_ledger.to_excel(out_excel, index=False)
                
                st.success("✅ Ledgers and PDFs Generated!")
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.download_button("📊 Download College Ledger (Excel)", out_excel.getvalue(), f"College_Ledger_{st.session_state.get('active_cycle_name')}.xlsx")
                with col_d2:
                    st.download_button("📄 Download Marks Cards (.zip)", pdf_zip_buffer.getvalue(), f"Marks_Cards_{st.session_state.get('active_cycle_name')}.zip", "application/zip")
                    
            except Exception as e:
                st.error(f"Generation Error: {e}")
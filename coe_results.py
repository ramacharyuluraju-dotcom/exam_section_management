import streamlit as st
import pandas as pd
import io
import math
import zipfile
import xlsxwriter
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
    
    if not is_internal_only:
        if pd.notna(see_raw) and see_raw is not None and str(see_raw).strip() != "":
            if not status or status in ['PENDING', 'PND']: status = 'PRESENT'
    else:
        if pd.notna(cie_raw) and cie_raw is not None and str(cie_raw).strip() != "":
            if not status or status in ['PENDING', 'PND']: status = 'PRESENT'

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

# 🟢 MULTI-VALUATION ALGORITHMS 🟢
def calculate_nearest_two_max(v1, v2, v3):
    vals = [v for v in [v1, v2, v3] if v is not None and pd.notna(v) and str(v).strip() != '']
    vals = [float(v) for v in vals]
    
    if len(vals) == 0: return None
    if len(vals) == 1: return vals[0]
    if len(vals) == 2: return max(vals)
    
    if len(vals) >= 3:
        val1, val2, val3 = vals[:3]
        d12, d23, d13 = abs(val1 - val2), abs(val2 - val3), abs(val1 - val3)
        min_diff = min(d12, d23, d13)
        
        if min_diff == d12: return max(val1, val2)
        elif min_diff == d23: return max(val2, val3)
        else: return max(val1, val3)

def vtu_third_val_logic(m1, m2, m3):
    m1, m2, m3 = safe_float(m1, 0), safe_float(m2, 0), safe_float(m3, 0)
    diff_12 = abs(m1 - m2)
    diff_23 = abs(m2 - m3)
    diff_13 = abs(m1 - m3)

    min_diff = min(diff_12, diff_23, diff_13)

    candidates = []
    if min_diff == diff_12: candidates.append(max(m1, m2))
    if min_diff == diff_23: candidates.append(max(m2, m3))
    if min_diff == diff_13: candidates.append(max(m1, m3))

    return max(candidates) 

# ==========================================
# 3. PDF MARKS CARD & A3 LEDGER GENERATORS
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
    elements.append(t_info)
    elements.append(Spacer(1, 15))
    
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
    elements.append(t)
    elements.append(Spacer(1, 20))
    
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
    elements.append(t_total)
    elements.append(Spacer(1, 60))
    
    t_sig = Table([["Controller of Examinations", "Principal"]], colWidths=[250, 250])
    t_sig.setStyle(TableStyle([('ALIGN', (1,0), (1,0), 'RIGHT')]))
    elements.append(t_sig)
    
    doc.build(elements)

def generate_a3_excel_ledger(b_name, b_df, course_list, branch_name_map, active_cycle_name):
    """Generates an A3 print-ready Excel Ledger perfectly matching VTU formats."""
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet(f"{b_name}_Ledger")

    # A3 Landscape Print Setup
    worksheet.set_paper(8) # 8 = A3
    worksheet.set_landscape()
    worksheet.set_margins(left=0.2, right=0.2, top=0.4, bottom=0.4)
    worksheet.fit_to_pages(1, 0) # Fit columns to exactly 1 page wide

    # Formatting Styles
    title_format = workbook.add_format({'bold': True, 'align': 'left', 'font_size': 14})
    subtitle_format = workbook.add_format({'bold': True, 'align': 'left', 'font_size': 12})
    header_merged = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#D9D9D9', 'font_size': 10, 'text_wrap': True})
    header_normal = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#F2F2F2', 'font_size': 10})
    cell_center = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'font_size': 10})
    cell_left = workbook.add_format({'align': 'left', 'valign': 'vcenter', 'border': 1, 'font_size': 10})
    fail_format = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'font_color': 'red', 'bold': True, 'font_size': 10})

    full_branch_name = branch_name_map.get(b_name, b_name).upper()

    # University Header
    worksheet.write(0, 0, "AMC ENGINEERING COLLEGE", title_format)
    worksheet.write(1, 0, "Autonomous Institution affiliated to VTU, Belagavi", subtitle_format)
    worksheet.write(2, 0, f"DEPARTMENT OF {full_branch_name}", subtitle_format)
    worksheet.write(3, 0, f"Consolidated Result Sheet - {active_cycle_name}", subtitle_format)

    # Column Widths
    worksheet.set_column(0, 0, 5)   # Sl No
    worksheet.set_column(1, 1, 13)  # USN
    worksheet.set_column(2, 2, 22)  # Name

    # Write Table Headers
    row_idx = 5
    worksheet.merge_range(row_idx, 0, row_idx+1, 0, "Sl. No", header_merged)
    worksheet.merge_range(row_idx, 1, row_idx+1, 1, "USN", header_merged)
    worksheet.merge_range(row_idx, 2, row_idx+1, 2, "Name of the Student", header_merged)
    
    col_idx = 3
    for cc in course_list:
        worksheet.merge_range(row_idx, col_idx, row_idx, col_idx+3, cc, header_merged)
        worksheet.write(row_idx+1, col_idx, "CIE", header_normal)
        worksheet.write(row_idx+1, col_idx+1, "SEE", header_normal)
        worksheet.write(row_idx+1, col_idx+2, "TOT", header_normal)
        worksheet.write(row_idx+1, col_idx+3, "GRD", header_normal)
        worksheet.set_column(col_idx, col_idx+3, 4.5) # Compact marks columns
        col_idx += 4
        
    end_headers = ["GRAND TOT", "%", "RESULT", "SGPA", "GRADE", "CREDITS"]
    for eh in end_headers:
        worksheet.merge_range(row_idx, col_idx, row_idx+1, col_idx, eh, header_merged)
        worksheet.set_column(col_idx, col_idx, 7)
        col_idx += 1

    # Write Data
    row_idx = 7
    for i, (_, stu) in enumerate(b_df.iterrows()):
        worksheet.write(row_idx, 0, i+1, cell_center)
        worksheet.write(row_idx, 1, stu.get('USN', ''), cell_center)
        worksheet.write(row_idx, 2, stu.get('Name', ''), cell_left)
        
        c_col = 3
        for cc in course_list:
            cie = stu.get(f"{cc}_CIE", "")
            see = stu.get(f"{cc}_SEE", "")
            tot = stu.get(f"{cc}_Tot", "")
            grd = stu.get(f"{cc}_Grd", "")
            
            if pd.isna(cie) or cie == "": cie = "-"
            if pd.isna(see) or see == "": see = "-"
            if pd.isna(tot) or tot == "": tot = "-"
            if pd.isna(grd) or grd == "": grd = "-"
            
            fmt = fail_format if str(grd) in ['F', 'AB', 'NP', 'PND', 'PENDING'] else cell_center
            worksheet.write(row_idx, c_col, cie, cell_center)
            worksheet.write(row_idx, c_col+1, see, cell_center)
            worksheet.write(row_idx, c_col+2, tot, cell_center)
            worksheet.write(row_idx, c_col+3, grd, fmt)
            c_col += 4
            
        res = str(stu.get('Result', ''))
        res_fmt = fail_format if res != 'PASS' else cell_center
        worksheet.write(row_idx, c_col, stu.get('Grand_Tot', '-'), cell_center)
        worksheet.write(row_idx, c_col+1, stu.get('Percentage', '-'), cell_center)
        worksheet.write(row_idx, c_col+2, res, res_fmt)
        worksheet.write(row_idx, c_col+3, stu.get('SGPA', '-'), cell_center)
        worksheet.write(row_idx, c_col+4, stu.get('Overall_Grade', '-'), res_fmt)
        worksheet.write(row_idx, c_col+5, stu.get('Total_Credits', '-'), cell_center)
        
        row_idx += 1

    workbook.close()
    return output.getvalue()


# ==========================================
# 4. MAIN UI FLOW & CONTEXT AWARENESS
# ==========================================

if not selected_cycle_id:
    st.error("⚠️ CRITICAL ERROR: No Exam Cycle Selected. Please select a cycle in the Sidebar.")
    st.stop()

cycle_info = supabase.table("exam_cycles").select("exam_type, parent_cycle_id").eq("cycle_id", selected_cycle_id).execute().data
exam_type = cycle_info[0].get('exam_type', 'Regular') if cycle_info else 'Regular'
parent_id = cycle_info[0].get('parent_cycle_id') if cycle_info else None

st.title("🏆 Results & Grading Engine")
st.info(f"📍 **Active Context:** Processing {exam_type} data strictly for Cycle: **{active_cycle_name}**")

# 🟢 DYNAMIC TAB ROUTING SYSTEM 🟢
show_cie, show_decoder, show_see, show_grading, show_mod, show_ledgers, show_dashboard = False, False, False, False, False, False, False
show_makeup, show_reval = False, False

if exam_type == 'Regular':
    t1, t2, t3, t4, t5, t6, t7 = st.tabs(["1. CIE Consolidator", "2. Bundle Decoder", "3. SEE Consolidator", "4. Grading Engine", "5. Moderation", "6. Publish Ledgers", "7. CoE Dashboard"])
    show_cie, show_decoder, show_see, show_grading, show_mod, show_ledgers, show_dashboard = True, True, True, True, True, True, True

elif exam_type in ['Make-up', 'Supplementary', 'Summer']:
    t_mu, t3, t4, t6, t7 = st.tabs(["1. Auto-Sync Parent CIEs", "2. Upload Make-up SEEs", "3. Grading Engine", "4. Publish Ledgers", "5. CoE Dashboard"])
    show_makeup, show_see, show_grading, show_ledgers, show_dashboard = True, True, True, True, True

elif exam_type == 'Revaluation':
    t_rev, t6, t7 = st.tabs(["1. Revaluation Engine (V1/V2/V3)", "2. Publish Updated Ledgers", "3. CoE Dashboard"])
    show_reval, show_ledgers, show_dashboard = True, True, True

# ----------------------------------------------------
# TAB BLOCK: CIE ENTRY 
# ----------------------------------------------------
if show_cie:
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
# TAB BLOCK: BUNDLE DECODER
# ----------------------------------------------------
if show_decoder:
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
# TAB BLOCK: SEE CONSOLIDATION (Used in Reg & Make-up)
# ----------------------------------------------------
if show_see:
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
# TAB BLOCK: GRADING ENGINE (Used in Reg & Make-up)
# ----------------------------------------------------
if show_grading:
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
# TAB BLOCK: MODERATION & THIRD VALUATION
# ----------------------------------------------------
if show_mod:
    with t5:
        st.subheader("⚖️ Moderation & Third Valuation Engine")
        st.info("Apply bulk moderation. If the difference between the Original Evaluator and Moderator is > 15, the grade is frozen and flagged for Third Valuation.")
        
        mod_tabs = st.tabs(["📂 Bulk Moderation Upload", "📥 Export 3rd Valuation List", "👤 Manual Grace Marks", "⚖️ 3rd Valuation Upload"])

        # --- SUB-TAB 1: BULK MODERATION UPLOAD ---
        with mod_tabs[0]:
            st.markdown("#### Process Bulk Moderation Marks")
            
            with st.expander("View CSV Template Guide"):
                st.code("usn,course_code,moderated_marks\n1AM25CS001,1BCEDS103,45\n1AM25CS042,1BCEDS103,38")

            f_mod = st.file_uploader("Upload Moderation CSV", type='csv', key="mod_bulk_up")

            if f_mod and st.button("🚀 Execute Moderation Rules", type="primary"):
                df_mod = pd.read_csv(f_mod)
                usn_col = find_column(df_mod, ['usn', 'student id'])
                cc_col = find_column(df_mod, ['course_code', 'course code', 'subject code'])
                m_col = find_column(df_mod, ['moderated_marks', 'moderation', 'marks'])

                if not (usn_col and cc_col and m_col):
                    st.error("Missing standard columns. Please ensure USN, Course Code, and Moderated Marks are present in the CSV.")
                else:
                    with st.spinner("Analyzing True Original marks, checking > 15-mark differences, and processing grades..."):
                        try:
                            db_res = fetch_all_records("student_results", filters={"cycle_id": selected_cycle_id})
                            db_map = {(str(r['usn']).strip().upper(), str(r['course_code']).strip().upper()): r for r in db_res}

                            audit_res = fetch_all_records("marks_audit_log", "usn, course_code, old_see, created_at", filters={"cycle_id": selected_cycle_id})
                            audit_df = pd.DataFrame(audit_res)
                            true_original_map = {}
                            if not audit_df.empty:
                                audit_df = audit_df.sort_values('created_at') 
                                for _, row in audit_df.iterrows():
                                    key = (str(row['usn']).strip().upper(), str(row['course_code']).strip().upper())
                                    if key not in true_original_map:
                                        true_original_map[key] = safe_float(row['old_see'], 0) 

                            crs_res = fetch_all_records("master_courses", "course_code, credits, max_see, max_cie, total_marks")
                            crs_map = {r['course_code']: r for r in crs_res}
                            stu_res = fetch_all_records("master_students", "usn, branch_code")
                            branch_map = {str(r['usn']).strip().upper(): r.get('branch_code', '') for r in stu_res}
                            pg_branches = [r['branch_code'] for r in supabase.table("master_branches").select("branch_code, program_type").execute().data if str(r['program_type']).upper() == 'PG']

                            updates_list = []
                            audit_list = []
                            stats = {"upgraded": 0, "ignored": 0, "third_val": 0}

                            for _, r in df_mod.iterrows():
                                u = clean_str(r[usn_col])
                                c = clean_str(r[cc_col])
                                mod_mark = safe_float(r[m_col], None)

                                if (u, c) in db_map and mod_mark is not None:
                                    db_row = db_map[(u, c)]
                                    current_db_see = safe_float(db_row.get('see_raw'), 0)
                                    old_grade = db_row.get('grade')

                                    true_orig_see = true_original_map.get((u, c), current_db_see)
                                    mark_diff = abs(mod_mark - true_orig_see)

                                    if mark_diff > 15:
                                        stats["third_val"] += 1
                                        audit_list.append({
                                            "cycle_id": selected_cycle_id, "usn": u, "course_code": c,
                                            "change_type": "THIRD VALUATION PENDING",
                                            "old_see": true_orig_see, "old_grade": old_grade,
                                            "new_see": mod_mark, "new_grade": "FROZEN",
                                            "reason": f"Diff is {mark_diff} (Orig:{true_orig_see}, Mod:{mod_mark}). Escalate to 3rd Val."
                                        })
                                    else:
                                        if mod_mark > true_orig_see:
                                            stats["upgraded"] += 1
                                            
                                            mc = crs_map.get(c, {})
                                            cred, m_cie, m_see, conducted_for = safe_float(mc.get('credits'), 4.0), safe_float(mc.get('max_cie'), 50.0), safe_float(mc.get('max_see'), 50.0), safe_float(mc.get('total_marks'), 100.0)
                                            is_pg = branch_map.get(u) in pg_branches

                                            scaled_see, tot, grd, gp, is_pass, healed_status = apply_grading_rules(
                                                db_row['cie_marks'], mod_mark, db_row['exam_status'], cred, m_cie, m_see, conducted_for, is_pg
                                            )

                                            updates_list.append({
                                                "cycle_id": selected_cycle_id, "usn": u, "course_code": c,
                                                "see_raw": mod_mark, "see_scaled": scaled_see,
                                                "total_marks": tot, "grade": grd, "grade_points": gp,
                                                "credits_earned": cred if is_pass else 0.0, "is_pass": is_pass, "exam_status": healed_status
                                            })

                                            audit_list.append({
                                                "cycle_id": selected_cycle_id, "usn": u, "course_code": c,
                                                "change_type": "MODERATION - APPLIED",
                                                "old_see": true_orig_see, "old_grade": old_grade,
                                                "new_see": mod_mark, "new_grade": grd,
                                                "reason": f"Diff <= 15. Kept Higher Mod ({mod_mark})."
                                            })
                                        else:
                                            stats["ignored"] += 1
                                            audit_list.append({
                                                "cycle_id": selected_cycle_id, "usn": u, "course_code": c,
                                                "change_type": "MODERATION - IGNORED",
                                                "old_see": true_orig_see, "old_grade": old_grade,
                                                "new_see": true_orig_see, "new_grade": old_grade,
                                                "reason": f"Diff <= 15. Kept Higher Orig ({true_orig_see})."
                                            })

                            if audit_list:
                                if updates_list:
                                    for i in range(0, len(updates_list), 500):
                                        supabase.table("student_results").upsert(updates_list[i:i+500]).execute()
                                        
                                for i in range(0, len(audit_list), 500):
                                    try: supabase.table("marks_audit_log").insert(audit_list[i:i+500]).execute()
                                    except: pass

                            st.success("✅ Moderation Processed & Audited!")
                            c1, c2, c3 = st.columns(3)
                            c1.metric("⬆️ Upgraded (Mod > Orig)", stats["upgraded"])
                            c2.metric("➖ Ignored (Orig >= Mod)", stats["ignored"])
                            c3.metric("🚨 3rd Valuations Triggered", stats["third_val"], delta="Diff > 15", delta_color="inverse")
                        else:
                            st.warning("No valid matching students/courses found in the database.")

                        except Exception as e:
                            st.error(f"Processing Error: {e}")

        # --- SUB-TAB 2: THIRD VALUATION EXPORT ---
        with mod_tabs[1]:
            st.markdown("#### 🚨 Third Valuation Candidate List")
            st.write("These students had a moderation difference of more than 15. Their grades have been frozen until a Third Evaluator score is provided.")
            
            if st.button("🔍 Fetch Pending Third Valuations", type="primary"):
                with st.spinner("Scanning Audit Logs..."):
                    tv_logs = fetch_all_records("marks_audit_log", filters={"cycle_id": selected_cycle_id, "change_type": "THIRD VALUATION PENDING"})
                    
                    if not tv_logs:
                        st.success("🎉 No pending Third Valuations found for this cycle!")
                    else:
                        df_tv = pd.DataFrame(tv_logs)
                        display_cols = ['usn', 'course_code', 'old_see', 'new_see', 'reason', 'created_at']
                        df_tv_clean = df_tv[display_cols].rename(columns={
                            'usn': 'USN', 'course_code': 'Course Code', 
                            'old_see': 'Original Evaluator', 'new_see': 'Moderator Mark',
                            'reason': 'System Audit Note', 'created_at': 'Timestamp'
                        })
                        
                        st.dataframe(df_tv_clean, use_container_width=True, hide_index=True)
                        
                        csv_data = df_tv_clean.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="📥 Download List as CSV (For 3rd Evaluator)",
                            data=csv_data,
                            file_name=f"Third_Valuation_Candidates_{selected_cycle_id}.csv",
                            mime="text/csv",
                        )

        # --- SUB-TAB 3: MANUAL GRACE MARKS ---
        with mod_tabs[2]:
            st.markdown("#### Individual Student Grace Marks")
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
                                                
                                                audit_payload = {
                                                    "cycle_id": selected_cycle_id, "usn": mod_usn, "course_code": cc,
                                                    "change_type": "MODERATION - GRACE",
                                                    "old_cie": c_cie, "old_see": c_see, "old_grade": c_grade,
                                                    "new_cie": new_cie, "new_see": new_see, "new_grade": grd,
                                                    "reason": f"{grace_reason} (+{grace_marks} to {grace_target})"
                                                }
                                                try: supabase.table("marks_audit_log").insert(audit_payload).execute()
                                                except Exception as e: st.warning("Audit Log Warning: Log table might not exist yet.")

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

        # --- SUB-TAB 4: THIRD VALUATION UPLOAD ---
        with mod_tabs[3]: 
            st.markdown("#### Resolve Third Valuations")
            st.write("Upload the final 3rd Evaluator marks. The system applies the VTU **'Max of Nearest Two'** rule.")
            
            with st.expander("View CSV Template Guide"):
                st.code("usn,course_code,original_marks,moderation_marks,third_val_marks\n1AM25CS001,1BCEDS103,30,48,45")

            f_third = st.file_uploader("Upload 3rd Valuation CSV", type='csv', key="third_val_up")

            if f_third and st.button("⚖️ Apply VTU 3rd Valuation Rules", type="primary"):
                df_tv = pd.read_csv(f_third)
                req_cols = ['usn', 'course_code', 'original_marks', 'moderation_marks', 'third_val_marks']
                
                csv_cols = [c.strip().lower() for c in df_tv.columns]
                if not all(col in csv_cols for col in req_cols):
                    st.error(f"Missing required columns. Please ensure your CSV has exactly: {', '.join(req_cols)}")
                else:
                    with st.spinner("Applying VTU 'Max of Nearest Two' logic..."):
                        try:
                            db_res = fetch_all_records("student_results", filters={"cycle_id": selected_cycle_id})
                            db_map = {(str(r['usn']).strip().upper(), str(r['course_code']).strip().upper()): r for r in db_res}
                            
                            crs_res = fetch_all_records("master_courses", "course_code, credits, max_see, max_cie, total_marks")
                            crs_map = {r['course_code']: r for r in crs_res}
                            
                            stu_res = fetch_all_records("master_students", "usn, branch_code")
                            branch_map = {str(r['usn']).strip().upper(): r.get('branch_code', '') for r in stu_res}
                            pg_branches = [r['branch_code'] for r in supabase.table("master_branches").select("branch_code, program_type").execute().data if str(r['program_type']).upper() == 'PG']

                            updates_list = []
                            audit_list = []

                            for _, r in df_tv.iterrows():
                                u = clean_str(r['usn'])
                                c = clean_str(r['course_code'])
                                m1 = safe_float(r.get('original_marks'), 0)
                                m2 = safe_float(r.get('moderation_marks'), 0)
                                m3 = safe_float(r.get('third_val_marks'), 0)

                                if (u, c) in db_map:
                                    db_row = db_map[(u, c)]
                                    
                                    final_raw_see = vtu_third_val_logic(m1, m2, m3)
                                    
                                    mc = crs_map.get(c, {})
                                    cred, m_cie, m_see, conducted_for = safe_float(mc.get('credits'), 4.0), safe_float(mc.get('max_cie'), 50.0), safe_float(mc.get('max_see'), 50.0), safe_float(mc.get('total_marks'), 100.0)
                                    is_pg = branch_map.get(u) in pg_branches

                                    scaled_see, tot, grd, gp, is_pass, healed_status = apply_grading_rules(
                                        db_row['cie_marks'], final_raw_see, db_row['exam_status'], cred, m_cie, m_see, conducted_for, is_pg
                                    )

                                    updates_list.append({
                                        "cycle_id": selected_cycle_id, "usn": u, "course_code": c,
                                        "see_raw": final_raw_see, "see_scaled": scaled_see,
                                        "total_marks": tot, "grade": grd, "grade_points": gp,
                                        "credits_earned": cred if is_pass else 0.0, "is_pass": is_pass, "exam_status": healed_status
                                    })

                                    audit_list.append({
                                        "cycle_id": selected_cycle_id, "usn": u, "course_code": c,
                                        "change_type": "THIRD VALUATION - RESOLVED",
                                        "old_see": m1, "old_grade": db_row.get('grade'),
                                        "new_see": final_raw_see, "new_grade": grd,
                                        "reason": f"VTU Nearest Two [M1:{m1}, M2:{m2}, M3:{m3}] -> Final: {final_raw_see}"
                                    })

                            if updates_list:
                                for i in range(0, len(updates_list), 500):
                                    supabase.table("student_results").upsert(updates_list[i:i+500]).execute()
                                for i in range(0, len(audit_list), 500):
                                    supabase.table("marks_audit_log").insert(audit_list[i:i+500]).execute()
                                
                                st.success(f"✅ Third Valuation Complete! {len(updates_list)} grades updated based on VTU rules.")
                            else:
                                st.warning("No matching database records found for the uploaded USNs.")

                        except Exception as e:
                            st.error(f"Processing Error: {e}")

# ----------------------------------------------------
# TAB BLOCK: LEDGERS (Used in ALL Contexts)
# ----------------------------------------------------
if show_ledgers:
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
                    
                    branch_data = fetch_all_records("master_branches", "branch_code, branch_name")
                    branch_name_map = {r['branch_code']: r.get('branch_name', r['branch_code']) for r in branch_data}

                    crs_data = fetch_all_records("master_courses", "course_code, title, credits, max_see, total_marks")
                    crs_map = {clean_str(c['course_code']): c for c in crs_data}
                    
                    ledger_rows = []
                    pdf_zip_buffer = io.BytesIO()
                    branch_courses_map = {}
                    
                    with zipfile.ZipFile(pdf_zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                        for usn, courses in stu_courses.items():
                            name, branch = name_map.get(usn, "Unknown"), branch_map.get(usn, "UNKNOWN")
                            
                            if branch not in branch_courses_map:
                                branch_courses_map[branch] = set()
                            branch_courses_map[branch].update(courses)
                            
                            total_cr_attempted, total_gp_earned, results_list = 0.0, 0.0, []
                            ledger_dict = {'USN': usn, 'Name': name, 'Branch': branch}
                            pass_flag, has_pending, has_f = True, False, False
                            grand_tot, max_tot, total_cred = 0.0, 0.0, 0.0
                            
                            for cc in courses:
                                mc = crs_map.get(cc, {})
                                cr = safe_float(mc.get('credits'), 0.0)
                                c_max = safe_float(mc.get('total_marks'), 100.0)
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
                                    grand_tot += safe_float(tot_val, 0)
                                    max_tot += c_max
                                    
                                    if r.get('is_pass', False): 
                                        total_cred += cr
                                    else: 
                                        has_f = True
                                        pass_flag = False
                                
                            sgpa = (total_gp_earned / total_cr_attempted) if total_cr_attempted > 0 else 0.0
                            pct = (grand_tot / max_tot * 100) if max_tot > 0 else 0.0
                            
                            ledger_dict['SGPA'] = round(sgpa, 2) if not has_pending else "---"
                            ledger_dict['Result'] = "PENDING" if has_pending else ("PASS" if pass_flag else "FAIL")
                            ledger_dict['Grand_Tot'] = grand_tot if not has_pending else "---"
                            ledger_dict['Percentage'] = round(pct, 2) if not has_pending else "---"
                            ledger_dict['Total_Credits'] = total_cred if not has_pending else "---"
                            
                            if has_pending: ov_grd = "---"
                            elif pass_flag:
                                if sgpa >= 9.0: ov_grd = 'O'
                                elif sgpa >= 8.0: ov_grd = 'A+'
                                elif sgpa >= 7.0: ov_grd = 'A'
                                elif sgpa >= 6.0: ov_grd = 'B+'
                                elif sgpa >= 5.5: ov_grd = 'B'
                                elif sgpa >= 5.0: ov_grd = 'C'
                                elif sgpa >= 4.0: ov_grd = 'P'
                                else: ov_grd = 'F'
                            else: ov_grd = 'F'
                            
                            ledger_dict['Overall_Grade'] = ov_grd
                            
                            ledger_rows.append(ledger_dict)
                            pdf_buf = io.BytesIO()
                            generate_marks_card_pdf(pdf_buf, usn, name, results_list, sgpa, has_pending)
                            zf.writestr(f"Marks_Cards/{usn}.pdf", pdf_buf.getvalue())
                            
                    df_ledger = pd.DataFrame(ledger_rows)
                    
                    # 🟢 THE FIX: Sort by USN so the ledger appears in strict alphanumeric order
                    df_ledger = df_ledger.sort_values(by='USN', ascending=True).reset_index(drop=True)
                    
                    ledger_zip = io.BytesIO()
                    with zipfile.ZipFile(ledger_zip, "w") as branch_zf:
                        for b_name, b_df in df_ledger.groupby('Branch'):
                            b_course_list = sorted(list(branch_courses_map.get(b_name, [])))
                            excel_bytes = generate_a3_excel_ledger(b_name, b_df, b_course_list, branch_name_map, active_cycle_name)
                            branch_zf.writestr(f"Ledger_{str(b_name)}_{active_cycle_name}.xlsx", excel_bytes)
                    
                    st.success(f"✅ Successfully compiled {len(ledger_rows)} records into ZIP!")
                    c1, c2 = st.columns(2)
                    with c1: st.download_button("📊 Print-Ready Branch Ledgers (ZIP)", ledger_zip.getvalue(), f"A3_Ledgers_{active_cycle_name}.zip")
                    with c2: st.download_button("📄 Marks Cards (ZIP)", pdf_zip_buffer.getvalue(), f"Marks_Cards_{active_cycle_name}.zip")
                except Exception as e: st.error(f"Generation Error: {e}")

# ----------------------------------------------------
# TAB BLOCK: DASHBOARD (Used in ALL Contexts)
# ----------------------------------------------------
if show_dashboard:
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

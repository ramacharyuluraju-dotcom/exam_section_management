import streamlit as st
import pandas as pd
import io
import zipfile
import xlsxwriter
from utils import init_db

# --- CONFIGURATION ---
supabase = init_db()

st.title("🖨️ A3 Tabulation Ledger Hub")
st.info("🏛️ **Historical Read-Only Mode:** Generates official, wide-format tabulation registers designed specifically for A3 landscape printing. You can select ANY cycle (active or closed). Automatically separates Regular and Arrear students and fully resolves Make-up upgrades.")

# --- HELPER FUNCTIONS ---
@st.cache_data(ttl=60)
def fetch_all_records(table_name, select_query="*", filters=None):
    all_data = []
    start, step = 0, 1000
    while True:
        query = supabase.table(table_name).select(select_query)
        if filters:
            for col, val in filters.items(): 
                query = query.eq(col, val)
        res = query.range(start, start + step - 1).execute()
        if not res.data: break
        all_data.extend(res.data)
        if len(res.data) < step: break
        start += step
    return all_data

def get_vtu_grade_points(grade):
    gp_map = {'O': 10, 'A+': 9, 'A': 8, 'B+': 7, 'B': 6, 'C': 5, 'P': 4, 'F': 0, 'AB': 0, 'NP': 0}
    return gp_map.get(str(grade).strip().upper(), 0)

# ==========================================
# 1. HISTORICAL CYCLE SELECTOR
# ==========================================
st.markdown("### 🗓️ Select Academic Context")

all_cycles = fetch_all_records("exam_cycles", "cycle_id, cycle_name, academic_year, is_active")
if not all_cycles:
    st.error("No exam cycles found in the database.")
    st.stop()

# Group by Academic Year for a clean UI
ay_list = sorted(list(set([c.get('academic_year', 'Unknown') for c in all_cycles if c.get('academic_year')])), reverse=True)
col_ay, col_cyc = st.columns(2)
selected_ay = col_ay.selectbox("Filter by Academic Year", ay_list)

filtered_cycles = [c for c in all_cycles if c.get('academic_year') == selected_ay]
# Sort cycles so Active ones appear at the top, then by creation
filtered_cycles.sort(key=lambda x: (x.get('is_active', False)), reverse=True)

cycle_options = {f"{c['cycle_name']} ({'ACTIVE' if c['is_active'] else 'CLOSED'})": c['cycle_id'] for c in filtered_cycles}

selected_cycle_label = col_cyc.selectbox("Select Target Exam Cycle", list(cycle_options.keys()))
target_cycle_id = cycle_options[selected_cycle_label]
target_cycle_name = selected_cycle_label.split(' (')[0]

st.success(f"🔵 **Currently Generating Ledgers for:** {target_cycle_name}")
st.divider()

# ==========================================
# 2. GENERATION SETTINGS
# ==========================================
st.markdown("### ⚙️ Ledger Formatting")

l_col1, l_col2, l_col3 = st.columns(3)
l_prog = l_col1.selectbox("Program Type", ["UG", "PG"])
l_sem = l_col2.number_input("Target Semester", min_value=1, max_value=10, value=1)

# Fetch branches dynamically based on program
all_branches = fetch_all_records("master_branches", "branch_code, program_type")
valid_branches = sorted([b['branch_code'] for b in all_branches if b.get('program_type') == l_prog and b.get('branch_code') != 'COMMON'])

l_branch = l_col3.selectbox("Select Branch", ["ALL BRANCHES"] + valid_branches)

# ==========================================
# 3. EXCEL A3 GENERATOR ENGINE
# ==========================================
def generate_a3_ledger(df_results, df_students, dict_courses, branch, sem, ledger_type, prog_type, cycle_title):
    """Generates the wide-format A3 Excel matrix for Tabulation Registers."""
    
    # 1. Identify which courses these students actually wrote
    student_usns = df_students['usn'].unique().tolist()
    df_branch_res = df_results[df_results['usn'].isin(student_usns)].copy()
    
    if df_branch_res.empty:
        return None
        
    written_courses = df_branch_res['course_code'].unique().tolist()
    
    # Sort courses logically
    sorted_courses = sorted(written_courses)
    
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = workbook.add_worksheet(f"{branch}_{ledger_type}")
    
    # --- PAGE SETUP ---
    ws.set_paper(8) # 8 = A3 paper
    ws.set_landscape()
    ws.fit_to_pages(1, 0) # Fit to 1 page wide, unlimited pages tall
    ws.set_margins(left=0.2, right=0.2, top=0.4, bottom=0.4)
    ws.freeze_panes(5, 3) # Freeze headers and Student details
    
    # --- FORMATS ---
    fmt_title = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'font_size': 14})
    fmt_subtitle = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'font_size': 11})
    fmt_th_main = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#E8E8E8', 'text_wrap': True})
    fmt_th_sub = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#F5F5F5', 'font_size': 9})
    fmt_cell = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'font_size': 10})
    fmt_cell_fail = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'font_size': 10, 'font_color': '#D32F2F', 'bold': True})
    fmt_cell_text = workbook.add_format({'align': 'left', 'valign': 'vcenter', 'border': 1, 'font_size': 10, 'text_wrap': True})
    
    # --- COLUMN WIDTHS ---
    ws.set_column('A:A', 5)   # Sl
    ws.set_column('B:B', 14)  # USN
    ws.set_column('C:C', 30)  # Name
    
    # Dynamic course column widths (4 cols per subject)
    col_idx = 3
    for _ in sorted_courses:
        ws.set_column(col_idx, col_idx+3, 6) # CIE, SEE, TOT, GRD
        col_idx += 4
        
    ws.set_column(col_idx, col_idx+2, 8) # Total Credits, Points, SGPA

    # --- HEADER ROWS ---
    total_cols = 3 + (len(sorted_courses) * 4) + 3
    end_col_letter = xlsxwriter.utility.xl_col_to_name(total_cols - 1)
    
    clean_cycle_name = cycle_title.split(' (')[0]
    
    ws.merge_range(f"A1:{end_col_letter}1", "AMC ENGINEERING COLLEGE, BENGALURU", fmt_title)
    ws.merge_range(f"A2:{end_col_letter}2", f"TABULATION REGISTER - {clean_cycle_name.upper()}", fmt_subtitle)
    ws.merge_range(f"A3:{end_col_letter}3", f"Program: {prog_type}   |   Branch: {branch}   |   Semester: {sem}   |   Type: {ledger_type}", fmt_subtitle)

    # --- TABLE HEADERS ---
    ws.merge_range("A4:A5", "Sl.", fmt_th_main)
    ws.merge_range("B4:B5", "USN", fmt_th_main)
    ws.merge_range("C4:C5", "Student Name", fmt_th_main)
    
    c_idx = 3
    for cc in sorted_courses:
        c_title = dict_courses.get(cc, cc)
        ws.merge_range(3, c_idx, 3, c_idx+3, f"{cc}\n{c_title}", fmt_th_main)
        ws.write(4, c_idx, "CIE", fmt_th_sub)
        ws.write(4, c_idx+1, "SEE", fmt_th_sub)
        ws.write(4, c_idx+2, "TOT", fmt_th_sub)
        ws.write(4, c_idx+3, "GRD", fmt_th_sub)
        c_idx += 4
        
    ws.merge_range(3, c_idx, 4, c_idx, "Earned\nCredits", fmt_th_main)
    ws.merge_range(3, c_idx+1, 4, c_idx+1, "Total\nPoints", fmt_th_main)
    ws.merge_range(3, c_idx+2, 4, c_idx+2, "SGPA", fmt_th_main)

    # --- DATA ROWS ---
    row = 5
    # Sort students by USN
    df_students_sorted = df_students.sort_values(by='usn')
    
    for i, (_, stu) in enumerate(df_students_sorted.iterrows()):
        usn = stu['usn']
        ws.write(row, 0, i+1, fmt_cell)
        ws.write(row, 1, usn, fmt_cell)
        ws.write(row, 2, stu.get('full_name', ''), fmt_cell_text)
        
        stu_results = df_branch_res[df_branch_res['usn'] == usn]
        res_map = {r['course_code']: r for _, r in stu_results.iterrows()}
        
        c_idx = 3
        stu_credits_earned = 0.0
        stu_credits_attempted = 0.0
        stu_points = 0.0
        
        for cc in sorted_courses:
            if cc in res_map:
                r = res_map[cc]
                grade = str(r.get('grade', '')).strip().upper()
                is_pass = r.get('is_pass', False)
                cie = r.get('cie_marks', 0)
                see = r.get('see_raw', 0)
                tot = r.get('total_marks', 0)
                
                # Fetch course credits from dict
                course_cred = float(dict_courses.get(f"{cc}_credits", 0))
                
                format_to_use = fmt_cell if is_pass else fmt_cell_fail
                if grade in ['PND', 'PENDING', 'FROZEN', '']: 
                    grade = 'PND'
                    format_to_use = fmt_cell
                
                ws.write(row, c_idx, cie if pd.notna(cie) else "-", format_to_use)
                ws.write(row, c_idx+1, see if pd.notna(see) else "-", format_to_use)
                ws.write(row, c_idx+2, tot if pd.notna(tot) else "-", format_to_use)
                ws.write(row, c_idx+3, grade, format_to_use)
                
                # Math for SGPA
                if grade not in ['PND', 'W', 'X', 'I', 'AB']:
                    stu_credits_attempted += course_cred
                    if is_pass:
                        stu_credits_earned += course_cred
                        stu_points += (course_cred * get_vtu_grade_points(grade))
            else:
                # Student didn't take this course in this cycle
                ws.write(row, c_idx, "-", fmt_cell)
                ws.write(row, c_idx+1, "-", fmt_cell)
                ws.write(row, c_idx+2, "-", fmt_cell)
                ws.write(row, c_idx+3, "-", fmt_cell)
                
            c_idx += 4
            
        # SGPA Calculation
        sgpa = (stu_points / stu_credits_attempted) if stu_credits_attempted > 0 else 0.0
        
        ws.write(row, c_idx, stu_credits_earned, fmt_cell)
        ws.write(row, c_idx+1, stu_points, fmt_cell)
        ws.write(row, c_idx+2, round(sgpa, 2), fmt_cell)
        
        row += 1
        
    workbook.close()
    return output.getvalue()


# ==========================================
# 4. ACTION CONTROLLER
# ==========================================
if st.button("📥 Generate A3 Master Ledgers", type="primary"):
    with st.spinner(f"Compiling verified ledgers..."):
        
        # 1. Fetch Parent Results
        parent_results = fetch_all_records("student_results", filters={"cycle_id": target_cycle_id})
        
        if not parent_results:
            st.error(f"No results found for {target_cycle_name}.")
            st.stop()
            
        # 2. Safely Fetch Make-up Child Cycles & Results
        child_cycles = fetch_all_records("exam_cycles", "cycle_id", filters={"parent_cycle_id": target_cycle_id})
        
        # Create a dictionary to hold the resolved results (Parent is base)
        resolved_dict = {f"{r['usn']}_{r['course_code']}": r for r in parent_results}
        
        if child_cycles:
            child_ids = [c['cycle_id'] for c in child_cycles]
            child_results = []
            for cid in child_ids:
                c_res = fetch_all_records("student_results", filters={"cycle_id": cid})
                child_results.extend(c_res)
                
            # Overwrite Parent Results with Valid Make-up Results
            for cr in child_results:
                grade = str(cr.get('grade', '')).strip().upper()
                if grade not in ['PND', 'PENDING', 'FROZEN', '', 'NONE']:
                    key = f"{cr['usn']}_{cr['course_code']}"
                    if key in resolved_dict:
                        resolved_dict[key] = cr # Overwrite entirely
                        
        df_resolved = pd.DataFrame(list(resolved_dict.values()))
        
        # 3. Fetch Master Data
        raw_students = fetch_all_records("master_students", "usn, full_name, branch_code, current_sem")
        df_all_stu = pd.DataFrame(raw_students)
        
        raw_courses = fetch_all_records("master_courses", "course_code, title, credits")
        dict_courses = {}
        for c in raw_courses:
            dict_courses[c['course_code']] = c.get('title', 'Unknown')
            dict_courses[f"{c['course_code']}_credits"] = c.get('credits', 0)
            
        # 4. Prepare execution batch
        branches_to_process = valid_branches if l_branch == "ALL BRANCHES" else [l_branch]
        
        generated_files = [] # Tuples of (filename, bytes)
        
        for br in branches_to_process:
            # Filter students for this branch
            df_br_stu = df_all_stu[df_all_stu['branch_code'] == br].copy()
            if df_br_stu.empty: continue
            
            # --- SMART HEURISTIC: Regular vs Arrear ---
            # If the student's current recorded semester is <= target_sem + 1 (allowing for recent promotion buffer), 
            # they are Regular. Otherwise, they are writing a deep backlog and are Arrear.
            df_br_stu['current_sem'] = pd.to_numeric(df_br_stu['current_sem'], errors='coerce').fillna(1)
            
            mask_regular = df_br_stu['current_sem'] <= (l_sem + 1)
            df_regular = df_br_stu[mask_regular]
            df_arrear = df_br_stu[~mask_regular]
            
            # Generate Regular
            if not df_regular.empty:
                b_reg = generate_a3_ledger(df_resolved, df_regular, dict_courses, br, l_sem, "REGULAR", l_prog, target_cycle_name)
                if b_reg: generated_files.append((f"Ledger_{br}_Sem{l_sem}_REGULAR.xlsx", b_reg))
                
            # Generate Arrear
            if not df_arrear.empty:
                b_arr = generate_a3_ledger(df_resolved, df_arrear, dict_courses, br, l_sem, "ARREAR", l_prog, target_cycle_name)
                if b_arr: generated_files.append((f"Ledger_{br}_Sem{l_sem}_ARREAR.xlsx", b_arr))
                
        # 5. Serve Files
        if not generated_files:
            st.warning("No data found for the selected criteria.")
        elif len(generated_files) == 1:
            st.success("✅ A3 Ledger generated successfully!")
            fname, fbytes = generated_files[0]
            st.download_button(label=f"💾 Download {fname}", data=fbytes, file_name=fname, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", use_container_width=True)
        else:
            st.success(f"✅ Generated {len(generated_files)} A3 Ledgers successfully!")
            
            # Zip them up
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, fbytes in generated_files:
                    zf.writestr(fname, fbytes)
                    
            st.download_button(label=f"📥 Download ALL ({len(generated_files)} Files) as ZIP", data=zip_buffer.getvalue(), file_name=f"Master_Ledgers_Sem{l_sem}_{target_cycle_name.split(' ')[0]}.zip", mime="application/zip", type="primary", use_container_width=True)

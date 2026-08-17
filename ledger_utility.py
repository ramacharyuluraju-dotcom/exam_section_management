import streamlit as st
import pandas as pd
import io
import xlsxwriter
from utils import init_db

# --- CONFIGURATION ---
supabase = init_db()

st.title("🖨️ A3 Tabulation Ledger Hub")
st.info("🏛️ **Read-Only A3 Ledger Generator:** Generates official, wide-format tabulation registers designed specifically for A3 landscape printing. Automatically separates Regular and Arrear students and fully resolves Make-up upgrades.")

# --- HELPER FUNCTIONS ---
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

def safe_float(val, default=0.0):
    try: return float(val) if val and pd.notna(val) else default
    except: return default

def get_grade_point(grade):
    gp_map = {'O': 10, 'A+': 9, 'A': 8, 'B+': 7, 'B': 6, 'C': 5, 'P': 4, 'F': 0, 'AB': 0, 'NP': 0}
    return gp_map.get(str(grade).strip().upper(), 0)

# ==========================================
# 1. CYCLE SELECTOR (Global Override)
# ==========================================
st.markdown("### 1️⃣ Select Academic Context")

@st.cache_data(ttl=60)
def get_all_cycles():
    res = supabase.table("exam_cycles").select("cycle_id, cycle_name, academic_year, is_active").order("created_at", desc=True).execute()
    return res.data

all_cycles = get_all_cycles()
if not all_cycles:
    st.error("No exam cycles found in the database.")
    st.stop()

ay_list = sorted(list(set([c.get('academic_year', 'Unknown') for c in all_cycles])), reverse=True)

col1, col2 = st.columns(2)
selected_ay = col1.selectbox("Filter by Academic Year", ay_list)

filtered_cycles = [c for c in all_cycles if c.get('academic_year') == selected_ay]
cycle_options = {f"{c['cycle_name']} ({'ACTIVE' if c['is_active'] else 'CLOSED'})": c['cycle_id'] for c in filtered_cycles}

selected_cycle_name = col2.selectbox("Select Target Exam Cycle", list(cycle_options.keys()))
target_cycle_id = cycle_options[selected_cycle_name]
clean_cycle_name = selected_cycle_name.split(' (')[0]

st.divider()

# ==========================================
# 2. LEDGER CONFIGURATION
# ==========================================
st.markdown("### 2️⃣ Ledger Configuration")

l_col1, l_col2 = st.columns(2)
all_branches = fetch_all_records("master_branches", "branch_code")
valid_branches = [b['branch_code'] for b in all_branches if b.get('branch_code') != 'COMMON']

l_branch = l_col1.selectbox("Select Target Branch", valid_branches)
l_sem = l_col2.number_input("Select Target Semester", min_value=1, max_value=10, value=1)

def generate_a3_ledger(data_dict, sorted_courses, crs_info_dict, branch, sem, ledger_type):
    """Generates the wide-format A3 Matrix Excel Ledger"""
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = workbook.add_worksheet(f"Sem_{sem}_{ledger_type}")

    # --- A3 PRINT SETTINGS ---
    ws.set_paper(8) # 8 = A3 Paper Size
    ws.set_landscape()
    ws.set_margins(left=0.25, right=0.25, top=0.5, bottom=0.5)
    ws.fit_to_pages(1, 0) # Fit width to 1 page, let length flow naturally

    # --- FORMATS ---
    fmt_title = workbook.add_format({'bold': True, 'font_size': 16, 'align': 'center', 'valign': 'vcenter'})
    fmt_subtitle = workbook.add_format({'bold': True, 'font_size': 12, 'align': 'center', 'valign': 'vcenter'})
    fmt_head_main = workbook.add_format({'bold': True, 'border': 1, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#E0E0E0'})
    fmt_head_sub = workbook.add_format({'bold': True, 'border': 1, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#F5F5F5', 'font_size': 9})
    fmt_cell = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10})
    fmt_name = workbook.add_format({'border': 1, 'align': 'left', 'valign': 'vcenter', 'font_size': 10, 'text_wrap': True})
    fmt_fail = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 10, 'font_color': '#9C0006', 'bg_color': '#FFC7CE', 'bold': True})

    # --- HEADER ROWS ---
    total_cols = 3 + (len(sorted_courses) * 4) + 3 # Sl, USN, Name + (Courses * 4) + Total, Credits, SGPA
    end_col_letter = xlsxwriter.utility.xl_col_to_name(total_cols - 1)
    
    ws.merge_range(f"A1:{end_col_letter}1", "AMC ENGINEERING COLLEGE, BENGALURU", fmt_title)
    ws.merge_range(f"A2:{end_col_letter}2", f"TABULATION REGISTER - {clean_cycle_name.upper()}", fmt_subtitle)
    ws.merge_range(f"A3:{end_col_letter}3", f"Branch: {branch}   |   Semester: {sem}   |   Type: {ledger_type}", fmt_subtitle)

    # --- TABLE HEADERS ---
    ws.merge_range("A5:A6", "Sl.No", fmt_head_main)
    ws.merge_range("B5:B6", "USN", fmt_head_main)
    ws.merge_range("C5:C6", "Student Name", fmt_head_main)

    col_idx = 3
    for cc in sorted_courses:
        ws.merge_range(4, col_idx, 4, col_idx + 3, cc, fmt_head_main)
        ws.write(5, col_idx, "CIE", fmt_head_sub)
        ws.write(5, col_idx + 1, "SEE", fmt_head_sub)
        ws.write(5, col_idx + 2, "TOT", fmt_head_sub)
        ws.write(5, col_idx + 3, "GRD", fmt_head_sub)
        col_idx += 4

    ws.merge_range(4, col_idx, 5, col_idx, "Total\nMarks", fmt_head_main)
    ws.merge_range(4, col_idx + 1, 5, col_idx + 1, "Earned\nCredits", fmt_head_main)
    ws.merge_range(4, col_idx + 2, 5, col_idx + 2, "SGPA", fmt_head_main)

    # --- COLUMN WIDTHS ---
    ws.set_column("A:A", 5)
    ws.set_column("B:B", 14)
    ws.set_column("C:C", 25)
    
    for i in range(3, col_idx):
        ws.set_column(i, i, 5) # Compress marks columns tightly for A3 fitting
    
    ws.set_column(col_idx, col_idx + 2, 8)

    # --- DATA ROWS ---
    row_idx = 6
    sorted_usns = sorted(data_dict.keys())
    
    for i, usn in enumerate(sorted_usns):
        stu = data_dict[usn]
        ws.write(row_idx, 0, i + 1, fmt_cell)
        ws.write(row_idx, 1, usn, fmt_cell)
        ws.write(row_idx, 2, stu['name'], fmt_name)
        
        c_idx = 3
        stu_total_marks = 0
        stu_earned_credits = 0
        stu_total_points = 0
        stu_attempted_credits = 0
        
        for cc in sorted_courses:
            res = stu['results'].get(cc)
            
            if res:
                cie = res['cie']
                see = res['see']
                tot = res['tot']
                grd = res['grd']
                
                # Math calculations
                crs_credits = safe_float(crs_info_dict.get(cc, {}).get('credits', 0))
                stu_total_marks += tot
                
                # Exclude pending/frozen from SGPA math
                if grd not in ['PND', 'PENDING', 'FROZEN', 'W', 'X', 'I']:
                    stu_attempted_credits += crs_credits
                    gp = get_grade_point(grd)
                    stu_total_points += (gp * crs_credits)
                    
                    if res['is_pass']:
                        stu_earned_credits += crs_credits
                
                # Format Fails in Red
                cell_format = fmt_fail if not res['is_pass'] and grd not in ['PND', 'PENDING'] else fmt_cell
                
                ws.write(row_idx, c_idx, cie, cell_format)
                ws.write(row_idx, c_idx + 1, see if see is not None else "-", cell_format)
                ws.write(row_idx, c_idx + 2, tot, cell_format)
                ws.write(row_idx, c_idx + 3, grd, cell_format)
            else:
                # Student didn't register for this specific course
                ws.write(row_idx, c_idx, "-", fmt_cell)
                ws.write(row_idx, c_idx + 1, "-", fmt_cell)
                ws.write(row_idx, c_idx + 2, "-", fmt_cell)
                ws.write(row_idx, c_idx + 3, "-", fmt_cell)
                
            c_idx += 4
            
        sgpa = (stu_total_points / stu_attempted_credits) if stu_attempted_credits > 0 else 0
        
        ws.write(row_idx, c_idx, stu_total_marks, fmt_cell)
        ws.write(row_idx, c_idx + 1, stu_earned_credits, fmt_cell)
        ws.write(row_idx, c_idx + 2, f"{sgpa:.2f}", fmt_cell)
        
        row_idx += 1

    workbook.close()
    return output.getvalue()


if st.button("📥 Generate A3 Master Ledgers", type="primary"):
    with st.spinner(f"Compiling verified ledgers for {l_branch} Semester {l_sem}..."):
        
        # 1. Fetch Parent Results
        parent_results = fetch_all_records("student_results", filters={"cycle_id": target_cycle_id})
        
        if not parent_results:
            st.error(f"No results found for {clean_cycle_name}.")
            st.stop()
            
        # 2. Safely Fetch Make-up Child Cycles & Results
        child_cycles = fetch_all_records("exam_cycles", "cycle_id", filters={"parent_cycle_id": target_cycle_id})
        child_results = []
        for c in child_cycles:
            child_results.extend(fetch_all_records("student_results", filters={"cycle_id": c['cycle_id']}))
            
        # 3. Bulletproof Dictionary Merge (Child overwrites Parent)
        results_map = {}
        for r in parent_results:
            usn = str(r.get('usn', '')).strip().upper()
            cc = str(r.get('course_code', '')).strip().upper()
            results_map[f"{usn}_{cc}"] = r.copy()
            
        for cr in child_results:
            grade = str(cr.get('grade', '')).strip().upper()
            # Only overwrite if Make-up mark is officially finalized
            if grade not in ['PND', 'PENDING', 'FROZEN', '', 'NONE']:
                usn = str(cr.get('usn', '')).strip().upper()
                cc = str(cr.get('course_code', '')).strip().upper()
                key = f"{usn}_{cc}"
                
                if key in results_map:
                    results_map[key]['see_raw'] = cr.get('see_raw')
                    results_map[key]['see_scaled'] = cr.get('see_scaled')
                    results_map[key]['total_marks'] = cr.get('total_marks')
                    results_map[key]['grade'] = cr.get('grade')
                    results_map[key]['is_pass'] = cr.get('is_pass')
            
        final_resolved_results = list(results_map.values())
        
        # 4. Fetch Master Data References
        students = fetch_all_records("master_students", "usn, full_name, branch_code, current_sem, status")
        stu_dict = {str(s['usn']).strip().upper(): s for s in students}
        
        courses = fetch_all_records("master_courses", "course_code, title, semester_id, credits")
        crs_dict = {str(c['course_code']).strip().upper(): c for c in courses}
        
        # 5. Filter and Split into Regular vs Arrear
        regular_data = {}
        arrear_data = {}
        unique_courses_reg = set()
        unique_courses_arr = set()
        
        for r in final_resolved_results:
            usn = str(r.get('usn', '')).strip().upper()
            cc = str(r.get('course_code', '')).strip().upper()
            
            stu = stu_dict.get(usn)
            if not stu: continue
            
            # Ignore students who have officially left the college
            if str(stu.get('status', '')).upper() == 'DISCONTINUED': 
                continue
                
            branch = str(stu.get('branch_code', '')).strip().upper()
            if branch != l_branch: 
                continue
                
            crs = crs_dict.get(cc)
            if not crs: continue
            
            # We ONLY want subjects belonging to the user's targeted semester
            course_sem = safe_float(crs.get('semester_id', 0))
            if course_sem != l_sem: 
                continue
                
            student_current_sem = safe_float(stu.get('current_sem', 0))
            
            # 🟢 THE SEPARATION LOGIC
            # If the student's current semester matches the course semester, it's a Regular exam.
            # If the student's current semester is HIGHER than the course semester, it's an Arrear/Backlog exam.
            is_regular = (student_current_sem == l_sem)
            
            target_dict = regular_data if is_regular else arrear_data
            target_courses = unique_courses_reg if is_regular else unique_courses_arr
            
            if usn not in target_dict:
                target_dict[usn] = {'name': stu.get('full_name', 'Unknown'), 'results': {}}
                
            # The A3 Ledger needs the Scaled SEE marks (out of 50) usually, so we default to that if available
            see_mark = r.get('see_scaled') if r.get('see_scaled') is not None else r.get('see_raw')
                
            target_dict[usn]['results'][cc] = {
                'cie': r.get('cie_marks', 0),
                'see': see_mark,
                'tot': r.get('total_marks', 0),
                'grd': r.get('grade', 'PND'),
                'is_pass': r.get('is_pass', False)
            }
            target_courses.add(cc)

        # 6. Generate Excel Files if Data Exists
        sorted_courses_reg = sorted(list(unique_courses_reg))
        sorted_courses_arr = sorted(list(unique_courses_arr))
        
        if not regular_data and not arrear_data:
            st.warning(f"No results found for {l_branch} Semester {l_sem} in this cycle.")
        else:
            c1, c2 = st.columns(2)
            
            if regular_data:
                excel_reg = generate_a3_ledger(regular_data, sorted_courses_reg, crs_dict, l_branch, l_sem, "REGULAR")
                c1.success(f"✅ Regular Ledger Ready ({len(regular_data)} Students)")
                c1.download_button(
                    label="💾 Download REGULAR A3 Ledger",
                    data=excel_reg,
                    file_name=f"Ledger_{l_branch}_Sem{l_sem}_REGULAR.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            else:
                c1.info("No Regular students found.")
                
            if arrear_data:
                excel_arr = generate_a3_ledger(arrear_data, sorted_courses_arr, crs_dict, l_branch, l_sem, "ARREAR")
                c2.success(f"✅ Arrear Ledger Ready ({len(arrear_data)} Students)")
                c2.download_button(
                    label="💾 Download ARREAR A3 Ledger",
                    data=excel_arr,
                    file_name=f"Ledger_{l_branch}_Sem{l_sem}_ARREAR.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            else:
                c2.info("No Arrear students found.")

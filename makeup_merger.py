import streamlit as st
import pandas as pd
import math
from utils import init_db

# --- CONFIGURATION ---
supabase = init_db()

st.title("🚑 Child-to-Parent Merge Engine")
st.markdown("#### 🔄 Make-up & Supplementary Results Integrator")

# --- GLOBAL CONTEXT ---
active_cycle_id = st.session_state.get('active_cycle_id')
active_cycle_name = st.session_state.get('active_cycle_name', 'Unknown Cycle')

if not active_cycle_id:
    st.warning("⚠️ Please select an Active Exam Cycle in the Sidebar to proceed.")
    st.stop()

# --- 1. VERIFY CYCLE RELATIONSHIP ---
cycle_res = supabase.table("exam_cycles").select("*").eq("cycle_id", active_cycle_id).single().execute()
if not cycle_res.data:
    st.error("Could not fetch active cycle details.")
    st.stop()

current_cycle = cycle_res.data
parent_id = current_cycle.get('parent_cycle_id')

if not parent_id:
    st.error(f"❌ **Invalid Context:** The current cycle ({active_cycle_name}) does not have a linked Parent Cycle.")
    st.info("This tool can only be run from inside a Make-up or Supplementary cycle that is linked to a Regular semester.")
    st.stop()

# Fetch Parent Cycle Name for display
parent_res = supabase.table("exam_cycles").select("cycle_name").eq("cycle_id", parent_id).single().execute()
parent_cycle_name = parent_res.data.get('cycle_name', f'Cycle {parent_id}') if parent_res.data else f'Cycle {parent_id}'

st.info(f"🔵 **Current Source Cycle:** {active_cycle_name}")
st.success(f"🎯 **Target Parent Cycle:** {parent_cycle_name} (ID: {parent_id})")

# --- 🟢 FETCH PROGRAM TYPES TO SEPARATE UG/PG GRADING RULES ---
@st.cache_data(ttl=300)
def fetch_program_mappings():
    try:
        start = 0
        limit = 1000
        all_students = []
        while True:
            res = supabase.table("master_students").select("usn, branch_code").range(start, start + limit - 1).execute()
            if not res.data: break
            all_students.extend(res.data)
            if len(res.data) < limit: break
            start += limit
            
        branches = supabase.table("master_branches").select("branch_code, program_type").execute().data
        b_map = {b['branch_code']: b.get('program_type', 'UG') for b in branches}
        return {s['usn'].strip().upper(): b_map.get(s.get('branch_code'), 'UG') for s in all_students}
    except:
        return {}

usn_prog_map = fetch_program_mappings()

# --- HELPER: VTU GRADING ---
def get_vtu_grade(total_marks, cie_marks, see_scaled, program_type='UG', is_absent=False):
    """Calculates VTU standard grade, dynamically applying UG or PG minimums."""
    if is_absent: return 'AB', False
    
    # Passing minimums: PG (SEE >= 20, Total >= 50) | UG (SEE >= 18, Total >= 40)
    min_see = 20 if program_type == 'PG' else 18
    min_total = 50 if program_type == 'PG' else 40
    
    if see_scaled < min_see or total_marks < min_total:
        return 'F', False
        
    if total_marks >= 90: return 'O', True
    elif total_marks >= 80: return 'A+', True
    elif total_marks >= 70: return 'A', True
    elif total_marks >= 60: return 'B+', True
    elif total_marks >= 55: return 'B', True
    elif total_marks >= 50: return 'C', True
    elif total_marks >= 40 and program_type == 'UG': return 'P', True
    else: return 'F', False

# --- 2. THE MERGE ENGINE ---
st.markdown("### 1️⃣ Preview Mergeable Results")
st.write("This engine will scan the current Make-up cycle for finalized marks, look up the student's original 'I' or 'X' grade record in the Parent cycle, and prepare the grade upgrades.")

if st.button("🔍 Scan for Mergeable Results", type="primary"):
    with st.spinner("Analyzing results across both cycles..."):
        # 1. Get ALL results from Child Cycle
        child_results = supabase.table("student_results").select("*").eq("cycle_id", active_cycle_id).execute().data
        
        # Filter out pending ones
        valid_child = [r for r in child_results if r.get('grade') not in ['PND', 'PENDING', 'FROZEN', '', None]]
        
        if not valid_child:
            st.warning("No finalized results found in the current Make-up cycle.")
        else:
            # 2. Get Parent Results for these specific students and courses
            usns = list(set([r['usn'] for r in valid_child]))
            courses = list(set([r['course_code'] for r in valid_child]))
            
            # Fetch parent results safely
            parent_results = []
            for i in range(0, len(usns), 100):
                p_res = supabase.table("student_results").select("*").eq("cycle_id", parent_id).in_("usn", usns[i:i+100]).in_("course_code", courses).execute()
                if p_res.data:
                    parent_results.extend(p_res.data)
                    
            parent_map = {f"{r['usn']}_{r['course_code']}": r for r in parent_results}
            
            merge_preview = []
            
            for child_row in valid_child:
                usn = child_row['usn']
                cc = child_row['course_code']
                key = f"{usn}_{cc}"
                
                parent_row = parent_map.get(key)
                
                if parent_row:
                    # Get the child's newly evaluated SEE marks
                    new_see_raw = child_row.get('see_raw')
                    child_absent = (child_row.get('grade') == 'AB' or child_row.get('exam_status') == 'ABSENT')
                    
                    # Keep the ORIGINAL CIE marks from the Parent Semester
                    cie_marks = parent_row.get('cie_marks', 0)
                    prog_type = usn_prog_map.get(usn, 'UG') # Fetch UG/PG status
                    
                    if new_see_raw is not None and not child_absent:
                        new_see_scaled = math.ceil(new_see_raw / 2.0)
                        new_total = cie_marks + new_see_scaled
                        new_grade, is_pass = get_vtu_grade(new_total, cie_marks, new_see_scaled, program_type=prog_type, is_absent=False)
                    else:
                        new_see_raw = 0
                        new_see_scaled = 0
                        new_total = cie_marks
                        new_grade, is_pass = get_vtu_grade(new_total, cie_marks, new_see_scaled, program_type=prog_type, is_absent=True)
                    
                    merge_preview.append({
                        "usn": usn,
                        "course_code": cc,
                        "program_type": prog_type,
                        "parent_grade": parent_row.get('grade'),
                        "new_see_raw": new_see_raw,
                        "new_total": new_total,
                        "new_grade": new_grade,
                        "is_pass": is_pass,
                        "evaluator_id": child_row.get('evaluator_id')
                    })
            
            if merge_preview:
                st.session_state['merge_preview'] = merge_preview
                st.success(f"Found {len(merge_preview)} records ready to merge!")
            else:
                st.info("No matching records found to merge into the Parent Cycle.")

if 'merge_preview' in st.session_state:
    df_preview = pd.DataFrame(st.session_state['merge_preview'])
    st.dataframe(df_preview, use_container_width=True)
    
    st.markdown("### 2️⃣ Execute Final Merge")
    st.warning("⚠️ This action will permanently overwrite the marks in the Parent Cycle and create irreversible Audit Logs.")
    
    if st.button("🚀 Confirm & Merge to Parent Cycle", type="primary"):
        with st.spinner("Merging records..."):
            updates = st.session_state['merge_preview']
            success_count = 0
            error_count = 0
            
            progress_bar = st.progress(0)
            total = len(updates)
            
            for idx, row in enumerate(updates):
                try:
                    # 1. Update the Parent Cycle Record
                    update_payload = {
                        "see_raw": row['new_see_raw'],
                        "see_scaled": math.ceil(row['new_see_raw'] / 2.0) if row['new_see_raw'] else 0,
                        "total_marks": row['new_total'],
                        "grade": row['new_grade'],
                        "is_pass": row['is_pass']
                    }
                    
                    supabase.table("student_results").update(update_payload)\
                        .eq("cycle_id", parent_id)\
                        .eq("usn", row['usn'])\
                        .eq("course_code", row['course_code']).execute()
                        
                    # 2. Insert into marks_audit_log
                    audit_payload = {
                        "usn": row['usn'],
                        "course_code": row['course_code'],
                        "cycle_id": parent_id,
                        "change_type": "MAKE_UP_EXAM",
                        "old_marks": 0, # Since Make-up completely replaces I/X, old SEE is essentially 0 or N/A
                        "new_marks": row['new_see_raw'] or 0,
                        "evaluator_id": row.get('evaluator_id', 'MERGE_ENGINE')
                    }
                    supabase.table("marks_audit_log").insert(audit_payload).execute()
                    
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    print(f"Merge Error for {row['usn']}: {e}")
                    
                progress_bar.progress((idx + 1) / total)
                
            if success_count > 0:
                st.success(f"✅ Successfully merged {success_count} results into {parent_cycle_name}!")
                del st.session_state['merge_preview']
            if error_count > 0:
                st.error(f"⚠️ Encountered {error_count} errors during merge.")
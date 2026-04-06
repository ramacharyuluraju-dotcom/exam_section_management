import streamlit as st
import pandas as pd
from utils import init_db, clean_data_for_db

# --- CONFIGURATION ---
supabase = init_db()

st.title("⏳ Exam Lifecycle Management")
st.markdown("#### 🏢 Operational Phase: COE Office") 

active_cycle_id = st.session_state.get('active_cycle_id')

# --- HELPER FUNCTIONS ---
def fetch_all_records(table_name, select_query="*", filters=None):
    all_data = []
    start, step = 0, 1000
    while True:
        # 🟢 FIX: Initialize query first
        query = supabase.table(table_name).select(select_query)
        
        # 🟢 FIX: Apply filters BEFORE the range limits
        if filters:
            for col, val in filters.items(): 
                query = query.eq(col, val)
                
        # Apply pagination range last
        query = query.range(start, start + step - 1)
        res = query.execute()
        
        if not res.data: break
        all_data.extend(res.data)
        if len(res.data) < step: break
        start += step
    return all_data

def safe_float(val, default=0.0):
    try: return float(val) if val and pd.notna(val) else default
    except: return default

# --- STATUS DEFINITIONS ---
PHASES = {
    1: {"name": "Initiation", "desc": "Setup cycle and prepare for timetable."},
    2: {"name": "Timetable Ready", "desc": "Schedule is locked. Student registrations required."},
    3: {"name": "Applications Open", "desc": "Portal is open for students to verify subjects."},
    4: {"name": "Applications Closed", "desc": "Application window is over. Reviewing eligibility."},
    5: {"name": "Hall Ticket Phase", "desc": "Generating and releasing Admit Cards."},
    6: {"name": "Attendance (Form B)", "desc": "Generating subject-wise attendance sheets."},
    7: {"name": "Seating Allocation", "desc": "Mapping students to rooms and blocks."},
    8: {"name": "Logistics Ready", "desc": "Answer booklet allocation and QPDS indents."},
    9: {"name": "Live Examination", "desc": "Exam is currently in progress."},
    10: {"name": "Results Processing", "desc": "SEE marks entry and consolidation."}
}

tabs = st.tabs(["🚀 Active Lifecycle", "🆕 Create New Cycle", "📊 Cycle History", "🎓 Semester Promotion"])

# ==========================================
# 1. ACTIVE LIFECYCLE (CONTEXT-DRIVEN)
# ==========================================
with tabs[0]:
    if not active_cycle_id:
        st.warning("Please select a cycle from the sidebar or create a new one to begin.")
        st.info("The multi-cycle logic allows you to manage UG, PG, or Supplementary exams in parallel.")
    else:
        try:
            res = supabase.table("exam_cycles").select("*").eq("cycle_id", active_cycle_id).single().execute()
            current_cycle = res.data
            
            current_status = current_cycle.get('status_code', 1)
            phase_info = PHASES.get(current_status)

            st.subheader(f"Managing Session: {current_cycle['cycle_name']}")
            
            progress_val = current_status / 10
            st.progress(progress_val, text=f"Overall Progress: {int(progress_val*100)}%")
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Current Step", f"{current_status} / 10")
            m2.metric("Phase", phase_info['name'])
            m3.write(f"**Action Required:** {phase_info['desc']}")

            st.divider()

            if current_status == 1:
                st.markdown("### 📅 Step 1: Upload Exam Timetable")
                st.info("Upload the CSV containing the schedule for this specific cycle.")
                
                with st.expander("View CSV Template Guide"):
                    st.write("Columns: `course_code, exam_date, session` (Morning/Afternoon)")
                    st.code("course_code,exam_date,session\n1BMATC101,2026-02-20,Morning")
                
                f_tt = st.file_uploader("Upload Timetable CSV", type='csv', key=f"tt_uploader_{active_cycle_id}")
                
                if f_tt:
                    df_tt = pd.read_csv(f_tt)
                    st.dataframe(df_tt.head(), use_container_width=True)
                    
                    if st.button("🚀 Process & Advance to Step 2"):
                        expected = ['course_code', 'exam_date', 'session']
                        data = clean_data_for_db(df_tt, expected)
                        
                        for row in data:
                            row['cycle_id'] = active_cycle_id
                        
                        try:
                            supabase.table("exam_timetable").upsert(data).execute()
                            supabase.table("exam_cycles").update({"status_code": 2}).eq("cycle_id", active_cycle_id).execute()
                            st.success("Timetable Processed! Lifecycle advanced.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Upload failed: {e}")

            elif current_status < 10:
                st.markdown(f"### ✅ Current Phase: {phase_info['name']}")
                st.info(f"Context: {phase_info['desc']}")
                
                col_act, col_reset = st.columns([2, 1])
                
                with col_act:
                    st.write("Complete the required tasks in other modules (Registration, Hall Tickets, etc.)")
                    if st.button(f"➡️ Advance to Step {current_status + 1}: {PHASES[current_status+1]['name']}", type="primary"):
                        supabase.table("exam_cycles").update({"status_code": current_status + 1}).eq("cycle_id", active_cycle_id).execute()
                        st.rerun()
                
                with col_reset:
                    if st.button("⏪ Undo (Back to Previous Step)"):
                        if current_status > 1:
                            supabase.table("exam_cycles").update({"status_code": current_status - 1}).eq("cycle_id", active_cycle_id).execute()
                            st.rerun()

            else:
                st.balloons()
                st.markdown("### 🏁 Lifecycle Completed")
                st.success("All examinations and result processing for this cycle are concluded.")
                if st.button("📁 Close & Archive This Cycle"):
                    supabase.table("exam_cycles").update({"is_active": False}).eq("cycle_id", active_cycle_id).execute()
                    st.rerun()
        except Exception as e:
            st.error("Error retrieving cycle details. Please re-select from sidebar.")

# ==========================================
# 2. CREATE NEW CYCLE 
# ==========================================
with tabs[1]:
    st.markdown("### 🆕 Initiate New Exam Session")
    st.info("Parallel cycles allowed. Link Make-up/Arrear exams to their original Regular cycle.")
    
    c_name = st.text_input("Cycle Name", placeholder="e.g., UG ODD Semesters Jan-2026")
    
    col1, col2, col3 = st.columns(3)
    c_ay = col1.text_input("Academic Year", value="2025-26")
    c_type = col2.selectbox("Exam Type", ["Regular", "Supplementary", "Summer", "Revaluation", "Make-up"])
    c_sem_type = col3.selectbox("Semester Type", ["ODD", "EVEN", "BOTH"]) 
    
    # 🟢 NEW: Dynamic Semester Selection based on the Semester Type
    if c_sem_type == "ODD":
        sem_options = [1, 3, 5, 7, 9]
    elif c_sem_type == "EVEN":
        sem_options = [2, 4, 6, 8, 10]
    else:
        sem_options = list(range(1, 11))
        
    c_target_sems = st.multiselect(
        "Select Target Semesters for this Cycle", 
        options=sem_options, 
        default=sem_options, # Auto-selects all by default to save clicks
        help="Choose the specific semesters that will have exams in this cycle."
    )
    
    parent_cycle_id = None
    if c_type != "Regular":
        st.markdown("🔗 **Link to Parent Exam Cycle**")
        try:
            existing_cycles = supabase.table("exam_cycles").select("cycle_id, cycle_name").execute().data
            if existing_cycles:
                cycle_dict = {f"{c['cycle_name']} (ID: {c['cycle_id']})": int(c['cycle_id']) for c in existing_cycles}
                selected_parent = st.selectbox("Select Parent Cycle", options=["None"] + list(cycle_dict.keys()))
                
                if selected_parent != "None":
                    parent_cycle_id = cycle_dict[selected_parent]
        except Exception as e:
            st.error("Could not load existing cycles for linking.")

    if st.button("🚀 Start Exam Lifecycle", type="primary"):
        if not c_name:
            st.error("Please provide a name for the new cycle.")
        elif not c_target_sems:
            st.error("Please select at least one target semester.")
        else:
            new_cycle = {
                "cycle_name": c_name,
                "academic_year": c_ay,
                "exam_type": c_type,
                "semester_type": c_sem_type,
                "target_semesters": c_target_sems, # 🟢 ADDED: Passes the list [1, 3, 5] directly to Supabase
                "status_code": 1,
                "is_active": True,
                "parent_cycle_id": parent_cycle_id 
            }
            try:
                supabase.table("exam_cycles").insert(new_cycle).execute()
                st.success(f"Exam Cycle '{c_name}' initiated successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Could not create cycle: {e}")
                
# ==========================================
# 3. CYCLE HISTORY & RESTORE
# ==========================================
with tabs[2]:
    st.subheader("Archived Exam Cycles")
    try:
        history = supabase.table("exam_cycles").select("*").eq("is_active", False).order("created_at", desc=True).execute()
        
        if history.data:
            hist_df = pd.DataFrame(history.data)
            cols = ['cycle_name', 'academic_year', 'exam_type', 'created_at']
            st.dataframe(hist_df[cols], use_container_width=True)
            
            st.divider()
            
            st.markdown("### 🔄 Reopen an Archived Cycle")
            st.info("Accidentally closed a cycle? Reopen it here to continue processing marks and results.")
            
            cycle_options = {row['cycle_name']: row['cycle_id'] for row in history.data}
            
            col1, col2 = st.columns([3, 1])
            with col1:
                cycle_to_restore = st.selectbox("Select cycle to reopen:", options=list(cycle_options.keys()))
            
            with col2:
                st.write("") 
                st.write("")
                if st.button("🔓 Reopen Cycle", type="primary"):
                    restore_id = cycle_options[cycle_to_restore]
                    supabase.table("exam_cycles").update({"is_active": True}).eq("cycle_id", restore_id).execute()
                    
                    st.success(f"'{cycle_to_restore}' reopened! You can now select it in the sidebar.")
                    st.rerun()
                    
        else:
            st.info("No archived cycles found.")
    except Exception as e:
        st.error(f"History currently unavailable: {e}")

# ==========================================
# 4. SEMESTER PROMOTION ENGINE
# ==========================================
with tabs[3]:
    st.subheader("🎓 Master Semester Promotion")
    st.info("Promote students to their next semester based on VTU progression rules. Ensure you select the correct Program Type, as UG and PG calendars often differ.")

    # 🟢 NEW: Fetch branches to map Program Types (UG/PG) to Branch Codes
    try:
        all_branches = fetch_all_records("master_branches", "branch_code, program_type")
        ug_branches = [b['branch_code'] for b in all_branches if b.get('program_type') == 'UG']
        pg_branches = [b['branch_code'] for b in all_branches if b.get('program_type') == 'PG']
    except Exception:
        ug_branches, pg_branches = [], []

    promo_tabs = st.tabs(["⏩ Odd to Even Promotion", "🚧 Even to Odd (Vertical Progression)"])

    # --- ODD TO EVEN PROMOTION ---
    with promo_tabs[0]:
        st.write("Students moving from an Odd semester to an Even semester (e.g., 1st to 2nd) are promoted automatically without credit hurdles.")
        
        # 🟢 NEW: Added UI Filters for Program and Branch
        f_col1, f_col2, f_col3 = st.columns(3)
        odd_sems = [1, 3, 5, 7, 9]
        target_sem = f_col1.selectbox("Select current Odd Semester:", odd_sems)
        
        target_prog = f_col2.selectbox("Program Type", ["UG", "PG"], key="odd_prog")
        available_branches = ug_branches if target_prog == "UG" else pg_branches
        
        target_branches = f_col3.multiselect(
            "Select Branches", 
            options=available_branches, 
            default=available_branches,
            key="odd_branches"
        )
        
        if st.button(f"🚀 Promote {target_prog} Sem {target_sem} students to Sem {target_sem + 1}", type="primary"):
            if not target_branches:
                st.error("Please select at least one branch.")
            else:
                with st.spinner(f"Updating {target_prog} student records..."):
                    target_sem_str = str(target_sem)
                    # Fetch all students in that semester
                    all_sem_students = fetch_all_records("master_students", filters={"current_sem": target_sem_str})
                    
                    # 🟢 NEW: Filter down to ONLY the selected branches/program
                    students = [s for s in all_sem_students if s.get('branch_code') in target_branches]
                    
                    if not students:
                        st.warning(f"No active {target_prog} students found in Semester {target_sem} for the selected branches.")
                    else:
                        update_payload = [{"usn": s['usn'], "current_sem": str(target_sem + 1)} for s in students]
                        for i in range(0, len(update_payload), 1000):
                            supabase.table("master_students").upsert(update_payload[i:i+1000]).execute()
                        st.success(f"✅ {len(students)} {target_prog} students successfully promoted to Semester {target_sem + 1}!")

    # --- EVEN TO ODD PROMOTION (WITH HISTORICAL RESOLVER) ---
    with promo_tabs[1]:
        st.write("Vertical progression from Even to Odd requires students to meet VTU progression criteria.")
        
        # 🟢 NEW: Added UI Filters for Program and Branch
        f2_col1, f2_col2, f2_col3 = st.columns(3)
        even_sems = [2, 4, 6, 8]
        current_even_sem = f2_col1.selectbox("Select current Even Semester:", even_sems)
        
        target_prog_even = f2_col2.selectbox("Program Type", ["UG", "PG"], key="even_prog")
        available_branches_even = ug_branches if target_prog_even == "UG" else pg_branches
        
        target_branches_even = f2_col3.multiselect(
            "Select Branches", 
            options=available_branches_even, 
            default=available_branches_even,
            key="even_branches"
        )
        
        c_col1, c_col2 = st.columns(2)
        progression_rule = c_col1.selectbox("VTU Progression Criteria:", [
            "Max 4 Active Backlogs (Old Scheme)",
            "Minimum Credits Earned (NEP Scheme)",
            "No Active Backlogs from Previous Year"
        ])
        threshold = c_col2.number_input("Set Threshold (e.g., Max Backlogs or Min Credits):", value=4)

        if st.button("🔍 Analyze Eligibility & Promote", type="primary"):
            if not target_branches_even:
                st.error("Please select at least one branch.")
            else:
                with st.spinner(f"Analyzing {target_prog_even} academic histories..."):
                    current_even_sem_str = str(current_even_sem)
                    all_sem_students = fetch_all_records("master_students", filters={"current_sem": current_even_sem_str})
                    
                    # 🟢 NEW: Filter down to ONLY the selected branches/program
                    students = [s for s in all_sem_students if s.get('branch_code') in target_branches_even]
                    
                    if not students:
                        st.warning(f"No active {target_prog_even} students found in Semester {current_even_sem} for the selected branches.")
                    else:
                        all_results = fetch_all_records("student_results", "usn, course_code, is_pass, credits_earned, cycle_id")
                        all_results.sort(key=lambda x: int(x.get('cycle_id', 0)))
                        
                        latest_results = {}
                        for r in all_results:
                            u, c = r['usn'], r['course_code']
                            if u not in latest_results: latest_results[u] = {}
                            latest_results[u][c] = {
                                "is_pass": r.get('is_pass', False),
                                "credits": safe_float(r.get('credits_earned'), 0.0)
                            }

                        eligible_students = []
                        detained_students = []

                        for s in students:
                            usn = s['usn']
                            total_credits = 0.0
                            active_backlogs = 0
                            
                            student_courses = latest_results.get(usn, {})
                            for course_code, data in student_courses.items():
                                if data['is_pass']:
                                    total_credits += data['credits']
                                else:
                                    active_backlogs += 1
                                    
                            is_eligible = False
                            if "Backlogs" in progression_rule:
                                is_eligible = active_backlogs <= threshold
                            elif "Credits" in progression_rule:
                                is_eligible = total_credits >= threshold
                                
                            if is_eligible:
                                eligible_students.append({"usn": usn, "current_sem": str(current_even_sem + 1)})
                            else:
                                detained_students.append({"USN": usn, "Active Backlogs": active_backlogs, "Credits Earned": total_credits})

                        if eligible_students:
                            for i in range(0, len(eligible_students), 1000):
                                supabase.table("master_students").upsert(eligible_students[i:i+1000]).execute()
                            st.success(f"✅ {len(eligible_students)} {target_prog_even} students met the criteria and were promoted to Semester {current_even_sem + 1}!")
                        else:
                            st.warning("No students met the progression criteria.")
                            
                        if detained_students:
                            st.error(f"🚫 {len(detained_students)} {target_prog_even} students failed to meet the vertical progression criteria and have been detained.")
                            df_detained = pd.DataFrame(detained_students)
                            st.dataframe(df_detained, use_container_width=True)
                            
                            st.download_button(
                                label="📥 Download Detained Students CSV",
                                data=df_detained.to_csv(index=False).encode('utf-8'),
                                file_name=f"Detained_{target_prog_even}_Students_Sem_{current_even_sem}.csv",
                                mime="text/csv"
                            )

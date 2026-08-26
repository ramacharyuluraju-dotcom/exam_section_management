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
    start, step = 1000, 1000
    current_start = 0
    while True:
        query = supabase.table(table_name).select(select_query)
        if filters:
            for col, val in filters.items(): 
                query = query.eq(col, val)
                
        query = query.range(current_start, current_start + step - 1)
        res = query.execute()
        
        if not res.data: break
        all_data.extend(res.data)
        if len(res.data) < step: break
        current_start += step
    return all_data

def safe_float(val, default=0.0):
    try: return float(val) if val and pd.notna(val) else default
    except: return default

# --- STATUS DEFINITIONS (UPDATED TO 12 PHASES) ---
PHASES = {
    1: {"name": "Initiation", "desc": "Setup cycle and prepare for timetable."},
    2: {"name": "Timetable Ready", "desc": "Schedule is locked. Student registrations required."},
    3: {"name": "Applications Open", "desc": "Portal is open for students to apply for Regular & Arrear subjects."},
    4: {"name": "Applications Closed", "desc": "Application window is over. Reviewing eligibility & fee payments."},
    5: {"name": "Hall Ticket Phase", "desc": "Generating and releasing Admit Cards (Combining Regular + Arrear)."},
    6: {"name": "Attendance (Form B)", "desc": "Generating subject-wise attendance sheets."},
    7: {"name": "Seating Allocation", "desc": "Mapping students to rooms (Ensuring no clash for concurrent students)."},
    8: {"name": "Logistics Ready", "desc": "Answer booklet allocation and QPDS indents."},
    9: {"name": "Live Examination", "desc": "Exam is currently in progress."},
    10: {"name": "Results Processing", "desc": "SEE marks entry, valuation, and grading."},
    11: {"name": "Revaluation Window", "desc": "Accepting reval applications and entering 2nd/3rd valuation marks."},
    12: {"name": "Final Ledger Locked", "desc": "All revaluations complete. Ready for archiving."}
}

tabs = st.tabs(["🚀 Active Lifecycle", "🆕 Create New Cycle", "📊 Cycle History", "🎓 Semester Promotion"])

# ==========================================
# 1. ACTIVE LIFECYCLE (CONTEXT-DRIVEN)
# ==========================================
with tabs[0]:
    if not active_cycle_id:
        st.warning("Please select a cycle from the sidebar or create a new one to begin.")
    else:
        try:
            res = supabase.table("exam_cycles").select("*").eq("cycle_id", active_cycle_id).single().execute()
            current_cycle = res.data
            
            current_status = current_cycle.get('status_code', 1)
            phase_info = PHASES.get(current_status)

            st.subheader(f"Managing Session: {current_cycle['cycle_name']}")
            
            if current_cycle.get('exam_type') == "Regular + Arrear (Concurrent)":
                st.info("💡 **Concurrent Cycle Active:** This cycle is managing both regular semester students and their previous semester backlogs. Ensure timetables and hall tickets account for both.")

            # Calculate progress based on 12 steps now
            progress_val = current_status / 12
            st.progress(progress_val, text=f"Overall Progress: {int(progress_val*100)}%")
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Current Step", f"{current_status} / 12")
            m2.metric("Phase", phase_info['name'])
            m3.write(f"**Action Required:** {phase_info['desc']}")

            st.divider()

            if current_status == 1:
                st.markdown("### 📅 Step 1: Upload Exam Timetable")
                st.info("Upload the CSV containing the schedule. If this is a concurrent cycle (e.g. Sem 2 Regular + Sem 1 Arrears), include ALL course codes in this single file.")
                
                with st.expander("View CSV Template Guide"):
                    st.write("Columns: `course_code, exam_date, session` (Morning/Afternoon)")
                    st.code("course_code,exam_date,session\n1BMATC101,2026-02-20,Morning\n1BENG206,2026-02-21,Afternoon")
                
                f_tt = st.file_uploader("Upload Timetable CSV", type='csv', key=f"tt_uploader_{active_cycle_id}")
                
                if f_tt:
                    df_tt = pd.read_csv(f_tt)
                    
                    df_tt.columns = [str(c).strip().lower().replace(' ', '_') for c in df_tt.columns]
                    if 'date' in df_tt.columns and 'exam_date' not in df_tt.columns:
                        df_tt.rename(columns={'date': 'exam_date'}, inplace=True)
                        
                    if 'course_code' in df_tt.columns and 'exam_date' in df_tt.columns:
                        df_tt = df_tt.dropna(subset=['course_code', 'exam_date'])
                        df_tt = df_tt.drop_duplicates(subset=['course_code'], keep='first')
                    
                    if 'exam_date' in df_tt.columns:
                        df_tt['exam_date'] = pd.to_datetime(df_tt['exam_date'], errors='coerce')
                        failed_mask = df_tt['exam_date'].isna()
                        if failed_mask.any():
                            failed_courses = df_tt.loc[failed_mask, 'course_code'].astype(str).tolist()
                            st.error("❌ **Upload Failed: Unreadable Date Formats!**")
                            st.warning(f"Excel messed up the date format for these subjects: **{', '.join(failed_courses)}**")
                            st.info("Please open your CSV in Excel, highlight the Exam Date column, and change the format to standard **YYYY-MM-DD** (e.g., 2026-08-14). Save and re-upload!")
                            st.stop()
                            
                        df_tt['exam_date'] = df_tt['exam_date'].dt.strftime('%Y-%m-%d')
                        
                    st.dataframe(df_tt.head(), use_container_width=True)
                    
                    if st.button("🚀 Process & Advance to Step 2"):
                        if 'course_code' not in df_tt.columns or 'exam_date' not in df_tt.columns:
                            st.error("❌ Invalid CSV format. The file MUST contain 'course_code' and 'exam_date' columns.")
                        else:
                            expected = ['course_code', 'exam_date', 'session']
                            data = clean_data_for_db(df_tt, expected)
                            
                            uploaded_courses = {str(row['course_code']).strip().upper() for row in data}
                            valid_courses_db = fetch_all_records("master_courses", "course_code")
                            valid_courses = {str(c['course_code']).strip().upper() for c in valid_courses_db}
                            
                            invalid_courses = uploaded_courses - valid_courses
                            
                            if invalid_courses:
                                st.error("❌ **Upload Failed: Invalid Course Codes Detected!**")
                                st.warning(f"The following course codes from your CSV are missing from the Master Courses database:\n\n**{', '.join(invalid_courses)}**")
                                st.info("Please either correct typos in your CSV, or add these missing subjects in the Master Setup module before uploading the timetable.")
                            else:
                                for row in data:
                                    row['cycle_id'] = active_cycle_id
                                    row['course_code'] = str(row['course_code']).strip().upper()
                                
                                try:
                                    supabase.table("exam_timetable").delete().eq("cycle_id", active_cycle_id).execute()
                                    supabase.table("exam_timetable").insert(data).execute()
                                    supabase.table("exam_cycles").update({"status_code": 2}).eq("cycle_id", active_cycle_id).execute()
                                    st.success("Timetable Processed! Lifecycle advanced.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Upload failed: {e}")

            elif current_status < 12:
                st.markdown(f"### ✅ Current Phase: {phase_info['name']}")
                st.info(f"Context: {phase_info['desc']}")
                
                col_act, col_reset = st.columns([2, 1])
                
                with col_act:
                    st.write("Complete the required tasks in other modules (Registration, Hall Tickets, Results, etc.)")
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
                st.success("All examinations, result processing, and revaluations for this cycle are concluded.")
                
                if st.button("⏪ Undo (Re-open Phase 11 Revaluation)"):
                    supabase.table("exam_cycles").update({"status_code": 11}).eq("cycle_id", active_cycle_id).execute()
                    st.rerun()
                    
                if st.button("📁 Close & Archive This Cycle", type="primary"):
                    supabase.table("exam_cycles").update({"is_active": False}).eq("cycle_id", active_cycle_id).execute()
                    st.rerun()
        except Exception as e:
            st.error("Error retrieving cycle details. Please re-select from sidebar.")

# ==========================================
# 2. CREATE NEW CYCLE 
# ==========================================
with tabs[1]:
    st.markdown("### 🆕 Initiate New Exam Session")
    
    # 🟢 THE FIX: Catch the success message AFTER the page reloads
    if 'success_message' in st.session_state:
        st.success(st.session_state['success_message'])
        del st.session_state['success_message']
        
    cycle_category = st.radio(
        "Select Cycle Category", 
        ["Standard Academic Cycle", "Special Event Cycle (Summer / Make-up)"],
        horizontal=True
    )
    
    st.divider()
    
    # --- STANDARD ACADEMIC CYCLE ---
    if cycle_category == "Standard Academic Cycle":
        st.info("Use this for standard End-of-Semester examinations.")
        c_name = st.text_input("Cycle Name", placeholder="e.g., Even Sem + Odd Arrears July 2026")
        
        col_p1, col_p2, col_p3 = st.columns([1, 1, 2])
        c_ay = col_p1.text_input("Academic Year", value="2025-26")
        c_prog_type = col_p2.selectbox("Program", ["UG", "PG", "BOTH"])
        c_type = col_p3.selectbox("Exam Type", ["Regular", "Regular + Arrear (Concurrent)", "Supplementary (Arrear Only)"])
        
        c_sem_type = st.selectbox("Semester Type", ["ODD", "EVEN", "BOTH"], index=2 if c_type == "Regular + Arrear (Concurrent)" else 1) 
        
        if c_sem_type == "ODD": sem_options = [1, 3, 5, 7, 9]
        elif c_sem_type == "EVEN": sem_options = [2, 4, 6, 8, 10]
        else: sem_options = list(range(1, 11))
            
        if c_prog_type == "PG":
            sem_options = [s for s in sem_options if s <= 4]

        c_target_sems = st.multiselect("Select Target Semesters", options=sem_options, default=[1, 2] if c_type == "Regular + Arrear (Concurrent)" else sem_options)
        
        parent_cycle_id = None
        if c_type == "Supplementary (Arrear Only)":
            st.markdown("🔗 **Link to Parent Exam Cycle**")
            try:
                existing_cycles = supabase.table("exam_cycles").select("cycle_id, cycle_name").execute().data
                if existing_cycles:
                    cycle_dict = {f"{c['cycle_name']} (ID: {c['cycle_id']})": int(c['cycle_id']) for c in existing_cycles}
                    selected_parent = st.selectbox("Select Parent Cycle", options=["None"] + list(cycle_dict.keys()))
                    if selected_parent != "None": parent_cycle_id = cycle_dict[selected_parent]
            except Exception as e:
                st.error("Could not load existing cycles for linking.")

        if st.button("🚀 Start Standard Cycle", type="primary"):
            if not c_name or not c_target_sems:
                st.error("Please provide a name and select target semesters.")
            else:
                # 🟢 THE FIX: Check for duplicates before inserting
                dup_check = supabase.table("exam_cycles").select("cycle_id").eq("cycle_name", c_name.strip()).execute()
                if dup_check.data:
                    st.error(f"❌ A cycle named '{c_name}' already exists! Please use a unique name.")
                else:
                    new_cycle = {
                        "cycle_name": c_name.strip(), "academic_year": c_ay, "exam_type": c_type,
                        "semester_type": c_sem_type, "target_semesters": c_target_sems,
                        "program_type": c_prog_type,
                        "status_code": 1, "is_active": True, 
                        "is_brs_active": False,
                        "parent_cycle_id": parent_cycle_id
                    }
                    try:
                        supabase.table("exam_cycles").insert(new_cycle).execute()
                        # Save message to session state to survive the rerun
                        st.session_state['success_message'] = f"✅ Standard Cycle '{c_name}' ({c_prog_type}) initiated successfully!"
                        st.rerun()
                    except Exception as e: st.error(f"Database Error: {e}")

    # --- SPECIAL EVENT CYCLE (SUMMER / MAKE-UP) ---
    elif cycle_category == "Special Event Cycle (Summer / Make-up)":
        st.info("Use this for ad-hoc events. You can instantly push these to the BRS portal for Department Online Registrations.")
        
        e_name = st.text_input("Event Name", placeholder="e.g., Summer Semester 2026")
        
        col_e1, col_e2, col_e3, col_e4 = st.columns(4)
        e_ay = col_e1.text_input("Academic Year", value="2025-26", key="e_ay")
        e_prog_type = col_e2.selectbox("Program", ["UG", "PG", "BOTH"], key="e_prog")
        e_type = col_e3.selectbox("Event Type", ["Summer", "Make-up"])
        e_sem_type = col_e4.selectbox("Semester Type", ["SUMMER", "ODD", "EVEN", "BOTH"])
        
        e_sem_options = list(range(1, 11)) if e_prog_type != "PG" else list(range(1, 5))
        e_target_sems = st.multiselect("Select Target Semesters", options=e_sem_options, default=e_sem_options, key="e_sems")
        
        parent_cycle_id = None
        if e_type == "Make-up":
            st.markdown("🔗 **Link to Parent Exam Cycle**")
            try:
                existing_cycles = supabase.table("exam_cycles").select("cycle_id, cycle_name").execute().data
                if existing_cycles:
                    cycle_dict = {f"{c['cycle_name']} (ID: {c['cycle_id']})": int(c['cycle_id']) for c in existing_cycles}
                    selected_parent = st.selectbox("Select Parent Cycle", options=["None"] + list(cycle_dict.keys()), key="e_parent")
                    if selected_parent != "None": parent_cycle_id = cycle_dict[selected_parent]
            except Exception as e:
                st.error("Could not load existing cycles for linking.")

        st.markdown("### 🌐 Department Portal Integration")
        push_to_brs = st.toggle(f"Push {e_type} Event to BRS Portal?", value=True, help="If toggled ON, departments will immediately be able to register students for this event online.")
        
        if st.button(f"🚀 Start {e_type} Event", type="primary"):
            if not e_name or not e_target_sems:
                st.error("Please provide an event name and select target semesters.")
            else:
                # 🟢 THE FIX: Check for duplicates before inserting
                dup_check = supabase.table("exam_cycles").select("cycle_id").eq("cycle_name", e_name.strip()).execute()
                if dup_check.data:
                    st.error(f"❌ An event named '{e_name}' already exists! Please use a unique name.")
                else:
                    new_event = {
                        "cycle_name": e_name.strip(), "academic_year": e_ay, "exam_type": e_type,
                        "semester_type": e_sem_type, "target_semesters": e_target_sems,
                        "program_type": e_prog_type,
                        "status_code": 1, "is_active": True, 
                        "is_brs_active": push_to_brs,
                        "parent_cycle_id": parent_cycle_id
                    }
                    try:
                        supabase.table("exam_cycles").insert(new_event).execute()
                        # Save message to session state to survive the rerun
                        st.session_state['success_message'] = f"✅ {e_type} Event '{e_name}' ({e_prog_type}) initiated! (BRS Portal Active: {push_to_brs})"
                        st.rerun()
                    except Exception as e: st.error(f"Database Error: {e}")
                
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
    st.subheader("🎓 Master Semester Promotion & Graduation")
    st.info("Promote students, manage vertical progression rules, and finalize graduating classes.")

    try:
        all_branches = fetch_all_records("master_branches", "branch_code, program_type")
        
        # 🟢 FIX: Filter out non-departments from the promotion UI
        ignore_branches = ['BS', 'HM', 'COMMON', 'FIRST_YEAR', 'MATH', 'ENG', 'PHY', 'CHE', 'GEN']
        
        ug_branches = [b['branch_code'] for b in all_branches if b.get('program_type') == 'UG' and str(b['branch_code']).upper() not in ignore_branches]
        pg_branches = [b['branch_code'] for b in all_branches if b.get('program_type') == 'PG' and str(b['branch_code']).upper() not in ignore_branches]
    except Exception:
        ug_branches, pg_branches = [], []

    # 🟢 NEW: 3 Tabs (Added End of Program Tab)
    promo_tabs = st.tabs(["⏩ Odd to Even Promotion", "🚧 Even to Odd (Vertical Progression)", "🎓 Graduation & Course Completion"])

    # --- ODD TO EVEN PROMOTION ---
    with promo_tabs[0]:
        st.write("Students moving from an Odd semester to an Even semester (e.g., 1st to 2nd) are promoted automatically without credit hurdles.")
        
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
                    
                    raw_students = fetch_all_records("master_students", filters={"current_sem": target_sem_str})
                    all_sem_students = [s for s in raw_students if str(s.get('status', 'ACTIVE')).strip().upper() == 'ACTIVE']
                    
                    students = [s for s in all_sem_students if s.get('branch_code') in target_branches]
                    
                    if not students:
                        st.warning(f"No active {target_prog} students found in Semester {target_sem} for the selected branches.")
                    else:
                        update_payload = [{**s, "current_sem": target_sem + 1} for s in students]
                        
                        for i in range(0, len(update_payload), 1000):
                            supabase.table("master_students").upsert(update_payload[i:i+1000]).execute()
                        st.success(f"✅ {len(students)} {target_prog} students successfully promoted to Semester {target_sem + 1}!")

    # --- EVEN TO ODD PROMOTION (WITH HISTORICAL RESOLVER) ---
    with promo_tabs[1]:
        st.write("Vertical progression from Even to Odd requires students to meet VTU progression criteria.")
        
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

        if st.button("🔍 Analyze Eligibility (Preview Only)", type="primary"):
            if not target_branches_even:
                st.error("Please select at least one branch.")
            else:
                with st.spinner(f"Analyzing {target_prog_even} academic histories..."):
                    current_even_sem_str = str(current_even_sem)
                    
                    raw_students = fetch_all_records("master_students", filters={"current_sem": current_even_sem_str})
                    all_sem_students = [s for s in raw_students if str(s.get('status', 'ACTIVE')).strip().upper() == 'ACTIVE']
                    
                    students = [s for s in all_sem_students if s.get('branch_code') in target_branches_even]
                    
                    if not students:
                        st.warning(f"No active {target_prog_even} students found in Semester {current_even_sem} for the selected branches.")
                        if 'promo_preview' in st.session_state: del st.session_state['promo_preview']
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
                                eligible_students.append({**s, "current_sem": current_even_sem + 1})
                            else:
                                detained_students.append({
                                    "USN": usn, 
                                    "Name": s.get('full_name', 'Unknown'),
                                    "Branch": s.get('branch_code', ''),
                                    "Active Backlogs": active_backlogs, 
                                    "Credits Earned": total_credits
                                })

                        st.session_state['promo_preview'] = {
                            "eligible": eligible_students,
                            "detained": detained_students,
                            "target_sem": current_even_sem + 1,
                            "prog": target_prog_even
                        }

        if 'promo_preview' in st.session_state:
            preview_data = st.session_state['promo_preview']
            eligible = preview_data['eligible']
            detained = preview_data['detained']
            t_sem = preview_data['target_sem']
            prog_type = preview_data['prog']
            
            st.markdown("---")
            st.markdown("### 📊 Promotion Eligibility Report")
            
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Total Evaluated", len(eligible) + len(detained))
            mc2.metric("Eligible for Promotion", len(eligible), delta="Cleared", delta_color="normal")
            mc3.metric("Detained Students", len(detained), delta="Action Required", delta_color="inverse")
            
            if detained:
                st.error(f"🚫 {len(detained)} {prog_type} students failed to meet the vertical progression criteria.")
                df_detained = pd.DataFrame(detained)
                st.dataframe(df_detained, use_container_width=True)
                
                st.download_button(
                    label="📥 Download Detained Students CSV",
                    data=df_detained.to_csv(index=False).encode('utf-8'),
                    file_name=f"Detained_{prog_type}_Students_Moving_To_Sem_{t_sem}.csv",
                    mime="text/csv"
                )
            else:
                st.success("🎉 All students met the criteria! No one is detained.")
                
            if eligible:
                st.warning("⚠️ Warning: Confirming this action will update the Master Student Database.")
                if st.button("✅ Confirm & Promote Eligible Students", type="primary"):
                    with st.spinner("Updating student records..."):
                        for i in range(0, len(eligible), 1000):
                            supabase.table("master_students").upsert(eligible[i:i+1000]).execute()
                        st.success(f"✅ {len(eligible)} {prog_type} students successfully promoted to Semester {t_sem}!")
                        del st.session_state['promo_preview'] 
                        st.rerun()

    # --- 🟢 NEW: GRADUATION / COURSE COMPLETION ---
    with promo_tabs[2]:
        st.write("Process students who have completed their final semester. Students with no backlogs become **ALUMNI**, while those with pending arrears become **COURSE_COMPLETED**.")
        
        e_col1, e_col2, e_col3 = st.columns(3)
        e_prog = e_col1.selectbox("Program Type", ["UG", "PG"], key="end_prog")
        
        # Default Sem 8 for UG, Sem 4 for PG
        default_sem = 8 if e_prog == "UG" else 4
        e_sem = e_col2.number_input("Final Semester", value=default_sem, min_value=2, max_value=10)
        
        available_branches_end = ug_branches if e_prog == "UG" else pg_branches
        e_branches = e_col3.multiselect("Select Branches", options=available_branches_end, default=available_branches_end, key="end_branches")
        
        if st.button(f"🎓 Process End-of-Program for {e_prog} Sem {e_sem}", type="primary"):
            if not e_branches:
                st.error("Please select at least one branch.")
            else:
                with st.spinner("Analyzing academic histories for graduation..."):
                    
                    # Fetch ACTIVE students in final semester
                    raw_students = fetch_all_records("master_students", filters={"current_sem": str(e_sem)})
                    students = [s for s in raw_students if str(s.get('status', 'ACTIVE')).strip().upper() == 'ACTIVE' and s.get('branch_code') in e_branches]
                    
                    if not students:
                        st.warning(f"No ACTIVE {e_prog} students found in Semester {e_sem}.")
                    else:
                        # Fetch all results to determine ALUMNI vs COURSE_COMPLETED
                        all_results = fetch_all_records("student_results", "usn, course_code, is_pass, cycle_id")
                        all_results.sort(key=lambda x: int(x.get('cycle_id', 0)))
                        
                        latest_results = {}
                        for r in all_results:
                            u, c = r['usn'], r['course_code']
                            if u not in latest_results: latest_results[u] = {}
                            latest_results[u][c] = r.get('is_pass', False)
                        
                        alumni_payload = []
                        cc_payload = []
                        
                        for s in students:
                            usn = s['usn']
                            student_courses = latest_results.get(usn, {})
                            
                            # Count subjects that are NOT passed
                            active_backlogs = sum(1 for passed in student_courses.values() if not passed)
                            
                            if active_backlogs == 0 and len(student_courses) > 0:
                                # Passed everything!
                                alumni_payload.append({"usn": usn, "status": "ALUMNI"})
                            else:
                                # Has backlogs
                                cc_payload.append({"usn": usn, "status": "COURSE_COMPLETED"})
                        
                        # Execute DB updates
                        update_payload = alumni_payload + cc_payload
                        for i in range(0, len(update_payload), 1000):
                            # Updating just the status column for these USNs
                            # We must include the existing data to satisfy the upsert, 
                            # so we merge the new status into the student's existing record dict
                            batch = []
                            for row in update_payload[i:i+1000]:
                                target_usn = row['usn']
                                original_record = next(stu for stu in students if stu['usn'] == target_usn)
                                original_record['status'] = row['status']
                                batch.append(original_record)
                                
                            supabase.table("master_students").upsert(batch).execute()
                        
                        st.success(f"✅ Processed {len(students)} students!")
                        
                        if alumni_payload:
                            st.balloons()
                            st.success(f"🎓 {len(alumni_payload)} students successfully graduated and became ALUMNI!")
                        if cc_payload:
                            st.warning(f"🚧 {len(cc_payload)} students finished classes but have backlogs. Marked as COURSE_COMPLETED.")

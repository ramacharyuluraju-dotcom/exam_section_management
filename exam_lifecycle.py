import streamlit as st
import pandas as pd
from utils import init_db, clean_data_for_db

# --- CONFIGURATION ---
# Note: st.set_page_config removed because app.py handles it
supabase = init_db()

st.title("⏳ Exam Lifecycle Management")
st.sidebar.markdown("### Operational Phase: COE Office")

# --- GLOBAL CONTEXT ---
# Pulls the active cycle directly from the session state managed by app.py
active_cycle_id = st.session_state.get('active_cycle_id')

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

tabs = st.tabs(["🚀 Active Lifecycle", "🆕 Create New Cycle", "📊 Cycle History"])

# ==========================================
# 1. ACTIVE LIFECYCLE (CONTEXT-DRIVEN)
# ==========================================
with tabs[0]:
    if not active_cycle_id:
        st.warning("Please select a cycle from the sidebar or create a new one to begin.")
        st.info("The multi-cycle logic allows you to manage UG, PG, or Supplementary exams in parallel.")
    else:
        # Fetch the full details of the specific cycle selected in the sidebar
        try:
            res = supabase.table("exam_cycles").select("*").eq("cycle_id", active_cycle_id).single().execute()
            current_cycle = res.data
            
            current_status = current_cycle.get('status_code', 1)
            phase_info = PHASES.get(current_status)

            # Header Section
            st.subheader(f"Managing Session: {current_cycle['cycle_name']}")
            
            # Progress Bar based on status code
            progress_val = current_status / 10
            st.progress(progress_val, text=f"Overall Progress: {int(progress_val*100)}%")
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Current Step", f"{current_status} / 10")
            m2.metric("Phase", phase_info['name'])
            m3.write(f"**Action Required:** {phase_info['desc']}")

            st.divider()

            # --- PHASE-SPECIFIC LOGIC ---
            
            # STEP 1: TIMETABLE UPLOAD
            if current_status == 1:
                st.markdown("### 📅 Step 1: Upload Exam Timetable")
                st.info("Upload the CSV containing the schedule for this specific cycle.")
                
                with st.expander("View CSV Template Guide"):
                    st.write("Columns: `course_code, exam_date, session` (Morning/Afternoon)")
                    st.code("course_code,exam_date,session\n1BMATC101,2026-02-20,Morning")
                
                # Unique key prevents file mixups between different active cycles
                f_tt = st.file_uploader("Upload Timetable CSV", type='csv', key=f"tt_uploader_{active_cycle_id}")
                
                if f_tt:
                    df_tt = pd.read_csv(f_tt)
                    st.dataframe(df_tt.head(), use_container_width=True)
                    
                    if st.button("🚀 Process & Advance to Step 2"):
                        expected = ['course_code', 'exam_date', 'session']
                        data = clean_data_for_db(df_tt, expected)
                        
                        # Attach THIS specific cycle_id to the timetable rows
                        for row in data:
                            row['cycle_id'] = active_cycle_id
                        
                        try:
                            supabase.table("exam_timetable").upsert(data).execute()
                            # Advance the status for this specific cycle
                            supabase.table("exam_cycles").update({"status_code": 2}).eq("cycle_id", active_cycle_id).execute()
                            st.success("Timetable Processed! Lifecycle advanced.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Upload failed: {e}")

            # STEPS 2-9: GENERAL PROGRESSION
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

            # STEP 10: ARCHIVING
            else:
                st.balloons()
                st.markdown("### 🏁 Lifecycle Completed")
                st.success("All examinations and result processing for this cycle are concluded.")
                if st.button("📁 Close & Archive This Cycle"):
                    # This removes it from the sidebar selector but keeps the data in history
                    supabase.table("exam_cycles").update({"is_active": False}).eq("cycle_id", active_cycle_id).execute()
                    st.rerun()
        except Exception as e:
            st.error("Error retrieving cycle details. Please re-select from sidebar.")

# ==========================================
# 2. CREATE NEW CYCLE (MULTIPLE ALLOWED)
# ==========================================
with tabs[1]:
    st.markdown("### 🆕 Initiate New Exam Session")
    st.info("Parallel cycles allowed (e.g., manage UG Semester 1 and PG Semester 3 simultaneously).")
    
    with st.form("new_cycle_form", clear_on_submit=True):
        c_name = st.text_input("Cycle Name", placeholder="e.g., UG Sem-1 Regular Feb-2026")
        
        col1, col2 = st.columns(2)
        c_ay = col1.text_input("Academic Year", value="2025-26")
        c_type = col2.selectbox("Exam Type", ["Regular", "Supplementary", "Summer", "Revaluation", "Make-up"])
        
        if st.form_submit_button("🚀 Start Exam Lifecycle"):
            if c_name:
                new_cycle = {
                    "cycle_name": c_name,
                    "academic_year": c_ay,
                    "exam_type": c_type,
                    "status_code": 1,
                    "is_active": True
                }
                try:
                    supabase.table("exam_cycles").insert(new_cycle).execute()
                    st.success(f"Exam Cycle '{c_name}' initiated!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not create cycle: {e}")
            else:
                st.error("Please provide a name for the new cycle.")

# ==========================================
# 3. CYCLE HISTORY & RESTORE
# ==========================================
with tabs[2]:
    st.subheader("Archived Exam Cycles")
    try:
        # Fetch all closed cycles
        history = supabase.table("exam_cycles").select("*").eq("is_active", False).order("created_at", desc=True).execute()
        
        if history.data:
            hist_df = pd.DataFrame(history.data)
            # Display history table
            cols = ['cycle_name', 'academic_year', 'exam_type', 'created_at']
            st.dataframe(hist_df[cols], use_container_width=True)
            
            st.divider()
            
            # --- NEW: RESTORE FEATURE ---
            st.markdown("### 🔄 Reopen an Archived Cycle")
            st.info("Accidentally closed a cycle? Reopen it here to continue processing marks and results.")
            
            # Create a dictionary mapping cycle names to their IDs
            cycle_options = {row['cycle_name']: row['cycle_id'] for row in history.data}
            
            col1, col2 = st.columns([3, 1])
            with col1:
                cycle_to_restore = st.selectbox("Select cycle to reopen:", options=list(cycle_options.keys()))
            
            with col2:
                st.write("") # Spacing alignment
                st.write("")
                if st.button("🔓 Reopen Cycle", type="primary"):
                    restore_id = cycle_options[cycle_to_restore]
                    # Update database to make it active again
                    supabase.table("exam_cycles").update({"is_active": True}).eq("cycle_id", restore_id).execute()
                    
                    st.success(f"'{cycle_to_restore}' reopened! You can now select it in the sidebar.")
                    st.rerun()
                    
        else:
            st.info("No archived cycles found.")
    except Exception as e:
        st.error(f"History currently unavailable: {e}")
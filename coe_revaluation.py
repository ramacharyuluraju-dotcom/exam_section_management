import streamlit as st
import pandas as pd
import math
import datetime
from utils import init_db, clean_data_for_db

# --- CONFIGURATION ---
supabase = init_db()

st.title("⚖️ Revaluation & Make-up Engine")
st.markdown("#### 🏢 Favorable-Rule Processing & Auditing")

# --- GLOBAL CONTEXT ---
active_cycle_id = st.session_state.get('active_cycle_id')
active_cycle_name = st.session_state.get('active_cycle_name', 'Unknown Cycle')

if not active_cycle_id:
    st.warning("⚠️ Please select an Active Exam Cycle in the Sidebar to proceed.")
    st.stop()

st.info(f"🔵 Currently processing Revaluations for Cycle: **{active_cycle_name}**")

# --- HELPER FUNCTIONS ---
def get_vtu_grade(total_marks, cie_marks, see_scaled, is_absent=False):
    """Calculates VTU standard grade, ensuring minimum passing thresholds are met."""
    if is_absent: return 'AB', False
    
    # Passing minimums: SEE >= 18/50 (approx 35%), Total >= 40
    if see_scaled < 18 or total_marks < 40:
        return 'F', False
        
    if total_marks >= 90: return 'O', True
    elif total_marks >= 80: return 'A+', True
    elif total_marks >= 70: return 'A', True
    elif total_marks >= 60: return 'B+', True
    elif total_marks >= 55: return 'B', True
    elif total_marks >= 50: return 'C', True
    elif total_marks >= 40: return 'P', True
    else: return 'F', False

def process_revaluation(usn, course_code, new_raw_marks, evaluator_id, cycle_id):
    """Executes the Best-of-Two Favorable Rule and logs the result."""
    clean_usn = str(usn).strip().upper()
    clean_course = str(course_code).strip().upper()
    new_raw_marks = int(new_raw_marks)
    
    # 1. Fetch current result and course constraints
    res = supabase.table("student_results").select("cie_marks, see_raw, see_scaled").eq("cycle_id", cycle_id).eq("usn", clean_usn).eq("course_code", clean_course).execute()
    
    if not res.data:
        return False, f"No existing result found for {clean_usn} in {clean_course}."
        
    current_data = res.data[0]
    old_raw = current_data.get('see_raw')
    
    # If they were absent originally, old_raw might be None. Treat as 0 for math.
    old_raw_val = int(old_raw) if old_raw is not None else 0
    cie_marks = int(current_data.get('cie_marks', 0))
    
    # 2. Check Favorable Rule
    if new_raw_marks > old_raw_val:
        # --- 🟢 FAVORABLE (UPGRADE) ---
        
        # Calculate new scaled and total marks (Assuming 100 raw scales to 50)
        new_scaled = math.ceil(new_raw_marks / 2.0)
        new_total = cie_marks + new_scaled
        new_grade, is_pass = get_vtu_grade(new_total, cie_marks, new_scaled)
        
        # Update Main Table
        update_payload = {
            "see_raw": new_raw_marks,
            "see_scaled": new_scaled,
            "total_marks": new_total,
            "grade": new_grade,
            "is_pass": is_pass
        }
        supabase.table("student_results").update(update_payload).eq("cycle_id", cycle_id).eq("usn", clean_usn).eq("course_code", clean_course).execute()
        
        # Insert Audit Log
        audit_payload = {
            "usn": clean_usn, "course_code": clean_course, "cycle_id": cycle_id,
            "change_type": "REVAL_UPGRADE",
            "old_marks": old_raw_val, "new_marks": new_raw_marks,
            "evaluator_id": str(evaluator_id)
        }
        supabase.table("marks_audit_log").insert(audit_payload).execute()
        
        return True, f"✅ UPGRADED: {clean_usn} jumped from {old_raw_val} to {new_raw_marks}. New Grade: {new_grade}."
        
    else:
        # --- 🔴 UNFAVORABLE (NO CHANGE) ---
        
        # DO NOT update student_results!
        # Only log the attempt for legal auditing.
        audit_payload = {
            "usn": clean_usn, "course_code": clean_course, "cycle_id": cycle_id,
            "change_type": "REVAL_NO_CHANGE",
            "old_marks": old_raw_val, "new_marks": new_raw_marks,
            "evaluator_id": str(evaluator_id)
        }
        supabase.table("marks_audit_log").insert(audit_payload).execute()
        
        return False, f"ℹ️ NO CHANGE: {clean_usn} scored {new_raw_marks}, which is lower/equal to original {old_raw_val}. Original marks retained."


# --- UI TABS ---
t1, t2, t3 = st.tabs(["✍️ Single Entry", "📤 Bulk Upload", "📖 Audit Trail"])

# ==========================================
# 1. SINGLE ENTRY
# ==========================================
with t1:
    st.subheader("Manual Revaluation Entry")
    
    with st.form("single_reval_form"):
        col1, col2 = st.columns(2)
        r_usn = col1.text_input("Student USN")
        r_course = col2.text_input("Course Code")
        
        col3, col4 = st.columns(2)
        r_marks = col3.number_input("New Revaluation Marks (Raw/100)", min_value=0, max_value=100, value=0)
        r_eval = col4.text_input("Evaluator ID / Name", placeholder="e.g. FAC-4021")
        
        if st.form_submit_button("Process Revaluation", type="primary"):
            if not r_usn or not r_course:
                st.error("USN and Course Code are required.")
            else:
                with st.spinner("Applying Favorable Rule..."):
                    try:
                        success, message = process_revaluation(r_usn, r_course, r_marks, r_eval, active_cycle_id)
                        if success: st.success(message)
                        else: st.warning(message)
                    except Exception as e:
                        st.error(f"Database Error: {e}")

# ==========================================
# 2. BULK UPLOAD
# ==========================================
with t2:
    st.subheader("Bulk Process 2nd/3rd Valuations")
    st.info("Upload a CSV containing the revaluation marks. The system will automatically check every row, apply the Favorable Rule, and generate an audit log.")
    
    with st.expander("View CSV Template Guide"):
        st.code("usn,course_code,new_marks,evaluator\n1AM25CS042,1BMATC201,45,Dr. Smith\n1AM25AE014,1BAIA103,12,Dr. Jane")
        
    f_csv = st.file_uploader("Upload Revaluation CSV", type="csv")
    
    if f_csv and st.button("🚀 Execute Bulk Revaluation", type="primary"):
        df = pd.read_csv(f_csv)
        df.columns = [str(c).strip().lower() for c in df.columns]
        
        if not all(req in df.columns for req in ['usn', 'course_code', 'new_marks']):
            st.error("❌ CSV must contain: 'usn', 'course_code', 'new_marks'.")
        else:
            with st.spinner("Processing Revaluations..."):
                upgrades = 0
                no_changes = 0
                errors = []
                
                # Setup progress bar
                progress = st.progress(0)
                total_rows = len(df)
                
                for idx, row in df.iterrows():
                    eval_id = row.get('evaluator', 'BULK_UPLOAD')
                    try:
                        success, _ = process_revaluation(row['usn'], row['course_code'], row['new_marks'], eval_id, active_cycle_id)
                        if success: upgrades += 1
                        else: no_changes += 1
                    except Exception as e:
                        errors.append(f"Row {idx+1} ({row['usn']}): {e}")
                        
                    progress.progress((idx + 1) / total_rows)
                
                st.markdown("### 📊 Processing Summary")
                col_s1, col_s2 = st.columns(2)
                col_s1.metric("✅ Upgraded (Favorable)", upgrades)
                col_s2.metric("ℹ️ Retained Original (No Change)", no_changes)
                
                if errors:
                    st.error(f"Encountered {len(errors)} errors.")
                    with st.expander("View Errors"):
                        for e in errors: st.write(e)

# ==========================================
# 3. AUDIT TRAIL VIEWER
# ==========================================
with t3:
    st.subheader(f"Revaluation Audit Log - {active_cycle_name}")
    st.write("This table acts as your legal record of all marks altered after the primary evaluation phase.")
    
    if st.button("🔄 Refresh Audit Logs"):
        with st.spinner("Fetching logs..."):
            res = supabase.table("marks_audit_log").select("*").eq("cycle_id", active_cycle_id).execute()
            
            if not res.data:
                st.info("No revaluation audits found for this cycle.")
            else:
                df_audit = pd.DataFrame(res.data)
                
                # Clean up display columns
                df_audit = df_audit[['timestamp', 'usn', 'course_code', 'change_type', 'old_marks', 'new_marks', 'evaluator_id']]
                df_audit['timestamp'] = pd.to_datetime(df_audit['timestamp']).dt.strftime('%Y-%m-%d %H:%M')
                df_audit = df_audit.sort_values(by='timestamp', ascending=False)
                
                # Apply color formatting
                def highlight_changes(val):
                    if val == 'REVAL_UPGRADE': return 'color: #4CAF50; font-weight: bold'
                    elif val == 'REVAL_NO_CHANGE': return 'color: #FF9800'
                    return ''
                
                st.dataframe(df_audit.style.map(highlight_changes, subset=['change_type']), use_container_width=True, hide_index=True)
                
                # Download button
                csv = df_audit.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download Audit Trail (CSV)", data=csv, file_name=f"Audit_Trail_{active_cycle_id}.csv", mime="text/csv")
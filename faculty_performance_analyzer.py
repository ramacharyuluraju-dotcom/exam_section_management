import streamlit as st
import pandas as pd
from utils import init_db

# Initialize Supabase Connection securely via utils.py
supabase = init_db()

st.title("👨‍🏫 Faculty Performance Analyzer")
st.markdown("Upload your mapping CSV to instantly calculate faculty-wise pass percentages.")

# 1. Read the active cycle securely from the session state
cycle_id = st.session_state.get("active_cycle_id")

if cycle_id:
    # Display the currently active cycle to confirm context
    cycle_name = st.session_state.get("active_cycle_name", "Unknown Cycle")
    st.info(f"Currently analyzing context: **{cycle_name}**")
    
    # 2. Upload Mapping File
    uploaded_file = st.file_uploader("Upload Faculty Mapping CSV", type=["csv"], help="CSV must contain 'usn', 'course_code', and 'faculty_name'")
    
    if uploaded_file is not None:
        # Load CSV
        mapping_df = pd.read_csv(uploaded_file)
        
        # --- SANITIZE CSV DATA ---
        if not {'usn', 'course_code', 'faculty_name'}.issubset(mapping_df.columns):
            st.error("❌ CSV missing required columns! Please ensure it has: `usn`, `course_code`, and `faculty_name`.")
            st.stop()
            
        mapping_df['usn'] = mapping_df['usn'].astype(str).str.strip().str.upper()
        mapping_df['course_code'] = mapping_df['course_code'].astype(str).str.strip().str.upper()
        
        # Fetch data from student_results (Fetching both grade and is_pass)
        with st.spinner("Fetching exam results from database..."):
            try:
                response = supabase.table("student_results").select("usn, course_code, grade, is_pass").eq("cycle_id", cycle_id).execute()
                results_df = pd.DataFrame(response.data)
            except Exception as e:
                st.error(f"Failed to query student_results table: {e}")
                st.stop()
        
        if results_df.empty:
            st.error("❌ The database returned 0 rows from 'student_results' for this cycle. Make sure results have been uploaded via the COE interface.")
            st.stop()

        # --- SANITIZE DB DATA ---
        results_df['usn'] = results_df['usn'].astype(str).str.strip().str.upper()
        results_df['course_code'] = results_df['course_code'].astype(str).str.strip().str.upper()

        # --- DIAGNOSTIC EXPANDER ---
        with st.expander("🛠️ Debug Mismatches: View Raw Formatting (Click to expand)"):
            st.markdown("If you get a mismatch error, compare these two tables. Do the Course Codes look exactly the same?")
            st.markdown("**1. Raw Database Results (First 100 rows):**")
            st.dataframe(results_df.head(100), use_container_width=True)
            st.markdown(f"**Unique DB Course Codes:** `{results_df['course_code'].unique().tolist()}`")
            
            st.markdown("**2. Uploaded CSV Mapping (First 100 rows):**")
            st.dataframe(mapping_df.head(100), use_container_width=True)
            st.markdown(f"**Unique CSV Course Codes:** `{mapping_df['course_code'].unique().tolist()}`")

        # 3. Merge datasets
        merged_df = pd.merge(results_df, mapping_df, on=['usn', 'course_code'], how='inner')
        
        if merged_df.empty:
            st.error("❌ Mismatch Error: Could not find any database results that perfectly matched the USNs and Course Codes in your CSV.")
            st.warning("Please check the 'Debug' expander above to compare the formatting of your CSV versus the Database.")
            st.stop()
            
        st.success(f"✅ Successfully matched {len(merged_df)} student records!")

        # 4. Calculate Pass Percentages based on ATTENDED students
        # Mark Attended = 0 if AB or NE, else 1
        non_attended_grades = ['AB', 'NE']
        merged_df['Attended'] = merged_df['grade'].apply(lambda x: 0 if str(x).strip().upper() in non_attended_grades else 1)
        
        # Mark IsPass based purely on the database's is_pass column
        merged_df['IsPass'] = merged_df['is_pass'].apply(lambda x: 1 if x is True or str(x).strip().lower() == 'true' else 0)

        # Group by Faculty Name and Course Code
        summary = merged_df.groupby(['faculty_name', 'course_code']).agg(
            Total_Registered=('usn', 'count'),
            Total_Attended=('Attended', 'sum'),
            Total_Passed=('IsPass', 'sum')
        ).reset_index()

        # Calculate Pass Percentage against ATTENDED (avoiding division by zero)
        summary['Pass_Percentage'] = (summary['Total_Passed'] / summary['Total_Attended'] * 100).fillna(0).round(2)
        
        # Sort nicely
        summary = summary.sort_values(by=['course_code', 'Pass_Percentage'], ascending=[True, False])

        st.subheader("📊 Faculty Analytics")
        
        # Display elegant table with Streamlit Progress Column
        st.dataframe(
            summary,
            column_config={
                "faculty_name": "Faculty Name",
                "course_code": "Course Code",
                "Total_Registered": "Registered",
                "Total_Attended": "Attended",
                "Total_Passed": "Passed",
                "Pass_Percentage": st.column_config.ProgressColumn(
                    "Pass (%)",
                    help="Percentage of attended students who passed",
                    format="%.2f %%",
                    min_value=0,
                    max_value=100,
                ),
            },
            use_container_width=True,
            hide_index=True
        )
        
        # Download Button
        csv_export = summary.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Complete Report",
            data=csv_export,
            file_name="Faculty_Performance_Report.csv",
            mime="text/csv",
        )
else:
    st.info("👈 Please select a valid Exam Cycle from the sidebar to view analytics.")

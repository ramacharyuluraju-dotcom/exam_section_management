import streamlit as st
import pandas as pd
from supabase import create_client, Client

# Initialize Supabase Connection
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

st.title("🗂️ Database Inspector & Faculty Analyzer")

# 1. Fetch Exam Cycles
try:
    cycles_resp = supabase.table("exam_cycles").select("id, cycle_name, academic_year, is_active").execute()
    cycles_data = cycles_resp.data
except Exception as e:
    st.error(f"Error connecting to Supabase: {e}")
    st.stop()

if not cycles_data:
    st.warning("No exam cycles found in database.")
    st.stop()

# Group cycles by Academic Year
academic_years = sorted(list(set([c['academic_year'] for c in cycles_data])), reverse=True)
cycle_options = []
cycle_dict = {}

for yr in academic_years:
    cycle_options.append(f"--- {yr} ---")
    yr_cycles = [c for c in cycles_data if c['academic_year'] == yr]
    for c in yr_cycles:
        status = " (Active)" if c['is_active'] else " (Closed)"
        label = f"   {c['cycle_name']}{status}"
        cycle_options.append(label)
        cycle_dict[label] = c['id']

selected_cycle = st.sidebar.selectbox("Select Exam Cycle", cycle_options)

if selected_cycle and not selected_cycle.startswith("---"):
    cycle_id = cycle_dict[selected_cycle]
    
    st.info(f"Selected Cycle ID: `{cycle_id}`")
    
    # 2. Upload Mapping File
    uploaded_file = st.file_uploader("Upload Faculty Mapping CSV", type=["csv"])
    
    if uploaded_file is not None:
        mapping_df = pd.read_csv(uploaded_file)
        
        # Fetch data from student_results
        with st.spinner("Fetching raw records from database..."):
            try:
                response = supabase.table("student_results").select("usn, course_code, grade, result_status").eq("cycle_id", cycle_id).execute()
                results_df = pd.DataFrame(response.data)
            except Exception as e:
                st.error(f"Failed to query student_results table: {e}")
                st.stop()
        
        st.subheader("📋 Step 1: Raw Supabase Data Inspection")
        if results_df.empty:
            st.error(f"❌ The database returned 0 rows from 'student_results' for Cycle ID: {cycle_id}. Make sure results have been uploaded for this specific cycle.")
        else:
            st.success(f"✅ Successfully pulled {len(results_df)} rows from Supabase.")
            st.markdown("Here is exactly how the data looks inside your database table. Check if `usn` or `course_code` formats match your CSV:")
            st.dataframe(results_df.head(500), use_container_width=True)
            
            # Show unexpected variations
            st.markdown("### Unique Course Codes found in DB for this Cycle:")
            st.write(results_df['course_code'].unique().tolist())
            
        st.subheader("📋 Step 2: Uploaded CSV Data Inspection")
        st.dataframe(mapping_df.head(10), use_container_width=True)
        
        # Try a merge to see what matches after printing
        if not results_df.empty:
            st.subheader("📋 Step 3: Merge Test")
            
            # Clean copy test
            r_df = results_df.copy()
            m_df = mapping_df.copy()
            r_df['usn'] = r_df['usn'].astype(str).str.strip().str.upper()
            r_df['course_code'] = r_df['course_code'].astype(str).str.strip().str.upper()
            m_df['usn'] = m_df['usn'].astype(str).str.strip().str.upper()
            m_df['course_code'] = m_df['course_code'].astype(str).str.strip().str.upper()
            
            test_merge = pd.merge(r_df, m_df, on=['usn', 'course_code'], how='inner')
            st.write(f"Number of overlapping rows found during a clean merge: **{len(test_merge)}**")
            if len(test_merge) > 0:
                st.dataframe(test_merge.head(10))
else:
    st.info("Please select a valid Exam Cycle from the sidebar to view the database records.")

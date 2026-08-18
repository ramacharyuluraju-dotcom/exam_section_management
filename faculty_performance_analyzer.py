import streamlit as st
import pandas as pd
from utils import init_db

# --- CONFIGURATION ---
supabase = init_db()

st.set_page_config(page_title="Faculty Analytics", layout="wide", page_icon="👨‍🏫")
st.title("👨‍🏫 Faculty-wise Result Analysis")
st.info("Upload a mapping CSV to dynamically link students to their sections and faculty members. The system will cross-reference this with the actual database results to generate precise pass percentages.")

# ==========================================
# 1. EXAM CYCLE SELECTOR
# ==========================================
try:
    cycles_res = supabase.table("exam_cycles").select("cycle_id, cycle_name").order("created_at", desc=True).execute()
    cycle_dict = {c['cycle_name']: c['cycle_id'] for c in cycles_res.data if c.get('cycle_name')}
except Exception as e:
    st.error("Failed to fetch exam cycles.")
    st.stop()

if not cycle_dict:
    st.warning("No exam cycles found in the database.")
    st.stop()

selected_cycle = st.selectbox("Select Target Exam Cycle", options=list(cycle_dict.keys()))
cycle_id = cycle_dict[selected_cycle]

# ==========================================
# 2. CSV UPLOADER
# ==========================================
st.markdown("### 📥 Upload Faculty Mapping Data")
with st.expander("View CSV Template Guide"):
    st.markdown("Your Excel/CSV file must contain exactly these column headers:")
    st.code("usn, section, course_code, faculty_name\n1AM25CS001, A, 1BMATS201, Prof. Meghana R\n1AM25CS002, A, 1BMATS201, Prof. Meghana R")

f_csv = st.file_uploader("Upload Faculty Mapping CSV", type="csv")

# ==========================================
# 3. DATA PROCESSING ENGINE
# ==========================================
if f_csv and st.button("📊 Generate Faculty Analysis", type="primary"):
    # Read the mapping CSV
    df_map = pd.read_csv(f_csv)
    
    # Clean column headers
    df_map.columns = [str(c).strip().lower() for c in df_map.columns]
    req_cols = ['usn', 'section', 'course_code', 'faculty_name']
    
    if not all(col in df_map.columns for col in req_cols):
        st.error(f"Missing required columns! Ensure your CSV has: {', '.join(req_cols)}")
        st.stop()

    with st.spinner("Cross-referencing mapping with live database results..."):
        
        # 1. Fetch raw student results for the selected cycle
        start, step = 0, 1000
        all_results = []
        while True:
            res = supabase.table("student_results").select("usn, course_code, is_pass, grade").eq("cycle_id", cycle_id).range(start, start + step - 1).execute()
            if not res.data: break
            all_results.extend(res.data)
            if len(res.data) < step: break
            start += step
            
        if not all_results:
            st.error("No results found in the database for this exam cycle.")
            st.stop()
            
        df_res = pd.DataFrame(all_results)
        
        # Filter out pending results
        df_res = df_res[~df_res['grade'].isin(['PND', 'PENDING', 'FROZEN', '', None])]
        
        if df_res.empty:
            st.warning("All results in this cycle are currently pending. Cannot generate analysis.")
            st.stop()
            
        # 2. Standardize data for a bulletproof merge
        df_map['usn'] = df_map['usn'].astype(str).str.strip().str.upper()
        df_map['course_code'] = df_map['course_code'].astype(str).str.strip().str.upper()
        
        df_res['usn'] = df_res['usn'].astype(str).str.strip().str.upper()
        df_res['course_code'] = df_res['course_code'].astype(str).str.strip().str.upper()
        
        # 3. Inner Merge (Matches students who both wrote the exam AND are in your CSV mapping)
        df_merged = pd.merge(df_map, df_res, on=['usn', 'course_code'], how='inner')
        
        if df_merged.empty:
            st.error("❌ Mismatch Error: Could not find any database results that matched the USNs and Course Codes in your uploaded CSV.")
            st.stop()
            
        # 4. Fetch Course Master to get Subject Titles
        courses_res = supabase.table("master_courses").select("course_code, title").execute()
        course_names = {str(c['course_code']).strip().upper(): c.get('title', 'Unknown Subject') for c in courses_res.data}
        
        # 5. Aggregate by Faculty and Course
        grouped = df_merged.groupby(['faculty_name', 'course_code', 'section']).agg(
            total_students=('usn', 'count'),
            total_passed=('is_pass', 'sum')
        ).reset_index()
        
        # Calculate Pass Percentage
        grouped['pass_percentage'] = (grouped['total_passed'] / grouped['total_students']) * 100
        grouped['pass_percentage'] = grouped['pass_percentage'].round(2)
        
        # Map Course Titles
        grouped['course_name'] = grouped['course_code'].map(course_names)
        
        # Reorder columns for beautiful display
        final_df = grouped[['faculty_name', 'section', 'course_code', 'course_name', 'total_students', 'total_passed', 'pass_percentage']]
        final_df.rename(columns={
            'faculty_name': 'Faculty Name',
            'section': 'Section',
            'course_code': 'Course Code',
            'course_name': 'Subject Title',
            'total_students': 'Appeared',
            'total_passed': 'Passed',
            'pass_percentage': 'Pass (%)'
        }, inplace=True)
        
        # Sort by Faculty Name
        final_df = final_df.sort_values(by=['Faculty Name', 'Course Code'])
        
        # ==========================================
        # 4. DISPLAY & DOWNLOAD
        # ==========================================
        st.success(f"✅ Analysis Complete! Successfully matched {len(df_merged)} results.")
        
        st.dataframe(
            final_df, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "Pass (%)": st.column_config.ProgressColumn(
                    "Pass (%)",
                    help="Pass Percentage",
                    format="%.2f%%",
                    min_value=0,
                    max_value=100,
                )
            }
        )
        
        # CSV Download
        csv = final_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Full Report (CSV)",
            data=csv,
            file_name=f"Faculty_Performance_Cycle_{cycle_id}.csv",
            mime="text/csv",
            type="primary"
        )

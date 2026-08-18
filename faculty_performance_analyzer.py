import streamlit as st
import pandas as pd
import re
from utils import init_db

# --- CONFIGURATION ---
supabase = init_db()

st.set_page_config(page_title="Faculty Analytics", layout="wide", page_icon="👨‍🏫")
st.title("👨‍🏫 Faculty-wise Result Analysis (2nd Sem)")
st.info("Dynamically maps student USNs to their respective sections and allocates them to the assigned faculty to generate precise pass percentages.")

# ==========================================
# 1. HARDCODED ALLOCATION RULES (FROM YOUR MATRIX)
# ==========================================

def determine_section(usn):
    """Parses a USN to determine the student's section based on the 2nd Sem matrix."""
    usn = str(usn).strip().upper()
    
    # Try to extract the last numeric part of the USN
    match = re.search(r'(\d+)$', usn)
    if not match: return 'UNKNOWN'
    
    num = int(match.group(1))
    
    # CSE Branch
    if usn.startswith('1AM25CS'):
        if 1 <= num <= 65: return 'A'
        if 66 <= num <= 130: return 'B'
        if 131 <= num <= 196: return 'C'
    elif usn.startswith('1AX25CS'):
        if 1 <= num <= 60: return 'D'
        if 61 <= num <= 120: return 'E'
        if 121 <= num <= 178: return 'F'
        
    # CSE-AI & ML Branch
    elif usn.startswith('1AM25CI'):
        if 1 <= num <= 60: return 'I'
        if 61 <= num <= 120: return 'J'
        if 121 <= num <= 176: return 'K'
        
    # ECE Branch
    elif usn.startswith('1AM25EC'):
        if 1 <= num <= 55: return 'M'
        if 56 <= num <= 110: return 'N'
        if 111 <= num <= 165: return 'O'
        
    # Other Branches
    elif usn.startswith('1AM25EE'): return 'P'
    elif usn.startswith('1AM25CD'):
        if 1 <= num <= 52: return 'Q'
        if 53 <= num <= 104: return 'R'
    elif usn.startswith('1AM25AI'):
        if 1 <= num <= 55: return 'S'
        if 56 <= num <= 110: return 'T'
        if 111 <= num <= 165: return 'U'
    elif usn.startswith('1AM25AE'): return 'V'
    elif usn.startswith('1AM25ME'): return 'W'
    elif usn.startswith('1AM25CV'): return 'X'

    return 'UNKNOWN'

# Faculty Mapping Dictionary: (Section, Course Code) -> Faculty Name
FACULTY_MAP = {
    # Section A
    ('A', '1BMATS201'): 'Prof. Meghana R', ('A', '1BCHES202'): 'Dr. V. Veeranna',
    ('A', '1BAIA203'): 'Prof. Sheetal', ('A', '1BESC204B'): 'Dr. R. Ravi Kumar',
    ('A', '1BPLC205B'): 'Prof. Parthasarathy PV', ('A', '1BENG206'): 'Prof. Maria',
    ('A', '1BICO207'): 'Prof. Narendra Kumar', ('A', '1BPRJ258'): 'Dr. R. Nagaraja',
    # Section B
    ('B', '1BMATS201'): 'Prof. Chandana M C', ('B', '1BCHES202'): 'Dr. Nishath Tarannum',
    ('B', '1BAIA203'): 'Dr. Supriya Shrivatsav', ('B', '1BESC204B'): 'Dr. B. Gyatri devi G',
    ('B', '1BPLC205B'): 'Prof. Praveen Kumar B', ('B', '1BENG206'): 'Prof. Maria',
    ('B', '1BICO207'): 'Prof. Narendra Kumar', ('B', '1BPRJ258'): 'Dr. R. Nagaraja',
    # Section C
    ('C', '1BMATS201'): 'Prof. Mithuna H N', ('C', '1BCHES202'): 'Prof. Leelavathi',
    ('C', '1BAIA203'): 'Prof. Divya G S', ('C', '1BESC204B'): 'Dr. R. Ravi Kumar',
    ('C', '1BPLC205B'): 'Prof. Geena George', ('C', '1BENG206'): 'Prof. Maria',
    ('C', '1BICO207'): 'Prof. Narendra Kumar', ('C', '1BPRJ258'): 'Dr. Ramesh Shabadkar',
    # Section D
    ('D', '1BMATS201'): 'Prof. Ananda M R', ('D', '1BCHES202'): 'Dr. Upendranath K',
    ('D', '1BAIA203'): 'Prof. Bhavya Balakrishnan', ('D', '1BESC204B'): 'Dr. B. Gyatri devi G',
    ('D', '1BPLC205B'): 'Prof. Lithu (ISE)', ('D', '1BENG206'): 'Prof. Maria',
    ('D', '1BICO207'): 'Prof. Narendra Kumar', ('D', '1BPRJ258'): 'Prof. Muralithran G',
    # Section E
    ('E', '1BMATS201'): 'Prof. Farheen Fathima S', ('E', '1BCHES202'): 'Prof. Sowjanya',
    ('E', '1BAIA203'): 'Prof. Priyanka c', ('E', '1BESC204B'): 'Prof. Dilsha',
    ('E', '1BPLC205B'): 'Prof. Prem Kumar', ('E', '1BENG206'): 'Prof. Maria',
    ('E', '1BICO207'): 'Prof. Narendra Kumar', ('E', '1BPRJ258'): 'Prof. T.K Pradeep Kumar',
    # Section F
    ('F', '1BMATS201'): 'Prof. Chandana M C', ('F', '1BCHES202'): 'Prof. Shalini D S',
    ('F', '1BAIA203'): 'Prof. Prem Kumar', ('F', '1BESC204B'): 'Prof. Dilsha',
    ('F', '1BPLC205B'): 'Prof. Vishwanath Reddy', ('F', '1BENG206'): 'Prof. Maria',
    ('F', '1BICO207'): 'Prof. Narendra Kumar', ('F', '1BPRJ258'): 'Prof. Suchitra',
    # Section I
    ('I', '1BMATS201'): 'Prof. Nandini P', ('I', '1BCHES202'): 'Dr. Shyamala',
    ('I', '1BAIA203'): 'Prof. Swathi S A', ('I', '1BESC204B'): 'Dr. R. Ravi Kumar',
    ('I', '1BPLC205B'): 'Prof. Veena W', ('I', '1BENG206'): 'Prof. Maria',
    ('I', '1BICO207'): 'Prof. Narendra Kumar', ('I', '1BPRJ258'): 'Prof. Veena M',
    # Section J
    ('J', '1BMATS201'): 'Prof. Sharaanyashree M', ('J', '1BCHES202'): 'Dr. Upendranath',
    ('J', '1BAIA203'): 'Dr. Shrinivas S', ('J', '1BESC204B'): 'Dr. Bharati priya',
    ('J', '1BPLC205B'): 'Prof. Pamela B', ('J', '1BENG206'): 'Prof. Maria',
    ('J', '1BICO207'): 'Prof. Narendra Kumar', ('J', '1BPRJ258'): 'Prof. Swathi S A',
    # Section K
    ('K', '1BMATS201'): 'Prof. Jayarekha M C', ('K', '1BCHES202'): 'Prof. Akshay Prashanth & Dr. V. Venkata Lakshmi',
    ('K', '1BAIA203'): 'Prof. Nagavarshini B', ('K', '1BESC204B'): 'Dr. Bharati priya',
    ('K', '1BPLC205B'): 'Prof. Veena', ('K', '1BENG206'): 'Prof. Maria',
    ('K', '1BICO207'): 'Prof. Narendra Kumar', ('K', '1BPRJ258'): 'Prof. Nagavarshini B R',
}

# ==========================================
# 2. DATA PROCESSING ENGINE
# ==========================================

# Fetch Cycles for Dropdown
try:
    cycles_res = supabase.table("exam_cycles").select("cycle_id, cycle_name").execute()
    cycle_dict = {c['cycle_name']: c['cycle_id'] for c in cycles_res.data}
except Exception as e:
    st.error("Failed to fetch exam cycles.")
    st.stop()

selected_cycle = st.selectbox("Select Target Exam Cycle", options=list(cycle_dict.keys()))
cycle_id = cycle_dict[selected_cycle]

if st.button("📊 Generate Faculty Analysis", type="primary"):
    with st.spinner("Fetching results and allocating students to faculty..."):
        
        # 1. Fetch raw student results for the cycle
        start, step = 0, 1000
        all_results = []
        while True:
            res = supabase.table("student_results").select("usn, course_code, is_pass, grade").eq("cycle_id", cycle_id).range(start, start + step - 1).execute()
            if not res.data: break
            all_results.extend(res.data)
            if len(res.data) < step: break
            start += step
            
        if not all_results:
            st.error("No results found for this cycle.")
            st.stop()
            
        # 2. Fetch Course Master to get Subject Names
        courses_res = supabase.table("master_courses").select("course_code, title").execute()
        course_names = {c['course_code']: c.get('title', 'Unknown Subject') for c in courses_res.data}
            
        # 3. Process the data
        analysis_data = []
        
        for r in all_results:
            # Skip pending results
            if r.get('grade') in ['PND', 'PENDING', 'FROZEN', '', None]:
                continue
                
            usn = r['usn']
            course = r['course_code']
            is_pass = r.get('is_pass', False)
            
            section = determine_section(usn)
            
            # Find Faculty (If not explicitly mapped in Sections A-K, mark as "Unassigned/Other Sections")
            faculty_name = FACULTY_MAP.get((section, course), "Unassigned / Other Sections")
            
            analysis_data.append({
                "usn": usn,
                "section": section,
                "course_code": course,
                "is_pass": is_pass,
                "faculty_name": faculty_name
            })
            
        df = pd.DataFrame(analysis_data)
        
        # Filter out unassigned sections to keep the report clean (optional)
        df = df[df['faculty_name'] != "Unassigned / Other Sections"]
        
        if df.empty:
            st.warning("No matched data found for Sections A-F and I-K in this cycle.")
            st.stop()
            
        # 4. Aggregate by Faculty and Course
        grouped = df.groupby(['faculty_name', 'course_code', 'section']).agg(
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
        
        # Sort by Pass Percentage (High to Low)
        final_df = final_df.sort_values(by=['Faculty Name', 'Course Code'])
        
        # ==========================================
        # 3. DISPLAY & DOWNLOAD
        # ==========================================
        st.success("✅ Analysis Complete!")
        
        st.dataframe(final_df.style.background_gradient(cmap='RdYlGn', subset=['Pass (%)']), use_container_width=True, hide_index=True)
        
        # CSV Download
        csv = final_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Full Report (CSV)",
            data=csv,
            file_name=f"Faculty_Performance_Cycle_{cycle_id}.csv",
            mime="text/csv",
            type="primary"
        )
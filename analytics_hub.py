import streamlit as st
import pandas as pd
from utils import init_db

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
supabase = init_db()

st.title("🌐 Global Analytics & Student 360°")
st.markdown("#### 📈 Institutional Intelligence Hub")

def safe_float(val, default=0.0):
    if val is None: return float(default)
    try:
        if pd.isna(val) or str(val).strip() == "": return float(default)
        return float(val)
    except: return float(default)

@st.cache_data(ttl=300) 
def fetch_all_records(table_name, select_query="*", filters=None):
    all_data = []
    start, step = 0, 1000
    while True:
        query = supabase.table(table_name).select(select_query).range(start, start + step - 1)
        if filters:
            for col, val in filters.items(): query = query.eq(col, val)
        res = query.execute()
        if not res.data: break
        all_data.extend(res.data)
        if len(res.data) < step: break
        start += step
    return all_data

@st.cache_data(ttl=3600)
def fetch_student_photo(usn):
    """Securely fetches photo bytes using the native Supabase Python SDK."""
    clean_usn = str(usn).strip().upper()
    
    for ext in ['.jpg', '.jpeg', '.png', '.webp', '.JPG', '.PNG', '.JPEG', '.WEBP']:
        try:
            res = supabase.storage.from_("StakeHolders_Photos").download(f"{clean_usn}{ext}")
            if res:
                return res
        except Exception:
            continue
    return None

# ==========================================
# UI TABS
# ==========================================
t1, t2, t3 = st.tabs([
    "🏫 Institutional Overview", 
    "📂 Exam Cycle Analytics", 
    "👤 Student 360° Profile"
])

# ----------------------------------------------------
# TAB 1: INSTITUTIONAL OVERVIEW
# ----------------------------------------------------
with t1:
    st.subheader("University Demographics & Exam Status")
    
    with st.spinner("Compiling institutional data..."):
        students = fetch_all_records("master_students", "usn, branch_code")
        branches = fetch_all_records("master_branches", "branch_code, program_type, branch_name")
        cycles = fetch_all_records("exam_cycles", "cycle_id, cycle_name, is_active, status_code")
        
        if students and branches:
            df_st = pd.DataFrame(students)
            df_br = pd.DataFrame(branches)
            
            df_st = pd.merge(df_st, df_br, on='branch_code', how='left')
            
            total_students = len(df_st)
            ug_count = len(df_st[df_st['program_type'].str.upper() == 'UG'])
            pg_count = len(df_st[df_st['program_type'].str.upper() == 'PG'])
            
            active_cycles = len([c for c in cycles if c.get('is_active') == True])
            closed_cycles = len(cycles) - active_cycles
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Official Master Students", f"{total_students:,}")
            c2.metric("UG Students", f"{ug_count:,}")
            c3.metric("PG Students", f"{pg_count:,}")
            c4.metric("Active Exam Cycles", f"{active_cycles}")
            
            st.markdown("---")
            
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                st.markdown("##### 📊 Students by Branch")
                branch_counts = df_st['branch_code'].value_counts().reset_index()
                branch_counts.columns = ['Branch', 'Students']
                st.bar_chart(branch_counts.set_index('Branch'), color="#4CAF50")
                
            with col_chart2:
                st.markdown("##### ⏳ Exam Cycles Lifecycle Status")
                if cycles:
                    df_cyc = pd.DataFrame(cycles)
                    df_cyc['Status Name'] = df_cyc['status_code'].apply(lambda x: "Processing" if x >= 10 else "Ongoing")
                    df_cyc.loc[df_cyc['is_active'] == False, 'Status Name'] = "Closed/Archived"
                    
                    status_counts = df_cyc['Status Name'].value_counts().reset_index()
                    status_counts.columns = ['Status', 'Count']
                    st.bar_chart(status_counts.set_index('Status'), color="#2196F3")

# ----------------------------------------------------
# TAB 2: EXAM CYCLE ANALYTICS 
# ----------------------------------------------------
with t2:
    st.subheader("Historical Cycle Analytics")
    
    cycles_data = fetch_all_records("exam_cycles", "cycle_id, cycle_name, is_active")
    if not cycles_data:
        st.warning("No exam cycles found in the database.")
    else:
        cycles_data.sort(key=lambda x: x.get('is_active', False), reverse=True)
        cycle_dict = {f"{c['cycle_name']} {'(ACTIVE)' if c.get('is_active') else '(CLOSED)'}": c['cycle_id'] for c in cycles_data}
        
        selected_cycle_key = st.selectbox("📂 Select Exam Cycle:", options=list(cycle_dict.keys()))
        target_cycle_id = cycle_dict[selected_cycle_key]
        
        if st.button("📊 Load Cycle Analytics", type="primary"):
            with st.spinner(f"Loading data for {selected_cycle_key}..."):
                try:
                    res_data = fetch_all_records("student_results", filters={"cycle_id": target_cycle_id})
                    if not res_data: 
                        st.warning("No result data available for this cycle yet.")
                    else:
                        df = pd.DataFrame(res_data)
                        
                        stu_data = fetch_all_records("master_students", "usn, branch_code")
                        branch_map = {str(r['usn']).strip().upper(): r.get('branch_code') for r in stu_data}
                        df['Branch'] = df['usn'].map(lambda x: branch_map.get(x, '⚠️ GHOST STUDENT'))

                        total_evals = len(df)
                        ghost_count = len(df[df['Branch'] == '⚠️ GHOST STUDENT'])
                        pending_evals = len(df[df['grade'].isin(['PND', 'PENDING'])])
                        failed_evals = len(df[df['grade'] == 'F'])
                        passed_evals = total_evals - pending_evals - failed_evals
                        completed_evals = total_evals - pending_evals
                        pass_pct = (passed_evals / completed_evals * 100) if completed_evals > 0 else 0
                        
                        if ghost_count > 0:
                            st.error(f"🚨 WARNING: Found {ghost_count} 'Ghost Students' in this exam cycle. These USNs have exam marks but do not exist in the Master Students table.")

                        col1, col2, col3, col4 = st.columns(4)
                        col1.metric("Total Evaluations", f"{total_evals:,}")
                        col2.metric("Pending/Missing Marks", f"{pending_evals:,}")
                        col3.metric("Overall Pass Rate", f"{pass_pct:.1f}%")
                        col4.metric("Total Fails", f"{failed_evals:,}")
                        
                        st.markdown("---")
                        chart_col1, chart_col2 = st.columns(2)
                        with chart_col1:
                            st.markdown("##### 📈 Grade Distribution")
                            df_graded = df[~df['grade'].isin(['PND', 'PENDING'])]
                            if not df_graded.empty:
                                grade_counts = df_graded['grade'].value_counts().reset_index()
                                grade_counts.columns = ['Grade', 'Count']
                                grade_order = ['O', 'A+', 'A', 'B+', 'B', 'C', 'P', 'F', 'AB', 'MP']
                                grade_counts['Grade'] = pd.Categorical(grade_counts['Grade'], categories=grade_order, ordered=True)
                                st.bar_chart(grade_counts.sort_values('Grade').set_index('Grade')['Count'], color="#9C27B0")

                        with chart_col2:
                            st.markdown("##### 🏢 Branch-wise Pass Rates")
                            branch_stats = []
                            for branch, group in df_graded.groupby('Branch'):
                                b_total = len(group)
                                b_pass = len(group[group['is_pass'] == True])
                                branch_stats.append({'Branch': branch, 'Pass Rate %': (b_pass / b_total) * 100 if b_total > 0 else 0})
                            if branch_stats: 
                                st.bar_chart(pd.DataFrame(branch_stats).set_index('Branch')['Pass Rate %'], color="#FF9800")

                except Exception as e: 
                    st.error(f"Dashboard Error: {e}")

# ----------------------------------------------------
# TAB 3: STUDENT 360° PROFILE 
# ----------------------------------------------------
with t3:
    st.subheader("👤 Student 360° Profile")
    st.info("Search for a student to view their cumulative performance presented semester-wise.")
    
    search_usn = st.text_input("🔍 Enter Student USN:").strip().upper()
    
    if search_usn and st.button("Search Student"):
        with st.spinner("Verifying Master Profile and compiling semester-wise dossier..."):
            
            stu_profile = supabase.table("master_students").select("*").eq("usn", search_usn).execute().data
            
            if not stu_profile:
                st.error(f"❌ USN '{search_usn}' not found in Master Database.")
            else:
                profile = stu_profile[0]
                branch_code = profile.get('branch_code', 'N/A')
                
                branch_info = supabase.table("master_branches").select("program_type, branch_name").eq("branch_code", branch_code).execute().data
                prog_type = branch_info[0].get('program_type', 'N/A') if branch_info else 'N/A'
                branch_name = branch_info[0].get('branch_name', branch_code) if branch_info else branch_code
                
                results_history = supabase.table("student_results").select("*").eq("usn", search_usn).execute().data
                
                # Fetch Maps
                cycles_map = {c['cycle_id']: c for c in fetch_all_records("exam_cycles", "cycle_id, cycle_name, exam_type")}
                audit_history = fetch_all_records("marks_audit_log", "course_code, change_type", filters={"usn": search_usn})
                
                reval_courses = set([r['course_code'] for r in audit_history if 'REVALUATION' in str(r.get('change_type', '')).upper()])
                grace_courses = set([r['course_code'] for r in audit_history if 'GRACE' in str(r.get('change_type', '')).upper()])
                
                crs_data = fetch_all_records("master_courses", "*")
                course_sem_col = 'semester'
                if crs_data:
                    for k in ['semester', 'sem', 'course_sem', 'current_sem', 'semester_id']:
                        if k in crs_data[0].keys():
                            course_sem_col = k
                            break
                courses_map = {c['course_code']: c for c in crs_data}
                
                # 🟢 CALCULATE CGPA (Using Latest Attempts) 🟢
                sorted_history = sorted(results_history, key=lambda x: int(x.get('cycle_id', 0)))
                latest_attempts = {}
                for r in sorted_history:
                    if r.get('grade') not in ['PND', 'PENDING', None]:
                        latest_attempts[r.get('course_code')] = r
                
                total_credits_attempted = 0.0
                total_grade_points_earned = 0.0
                active_backlogs = 0
                
                for c_code, r in latest_attempts.items():
                    cred = safe_float(courses_map.get(c_code, {}).get('credits', 0))
                    gp = safe_float(r.get('grade_points', 0))
                    total_credits_attempted += cred
                    total_grade_points_earned += (gp * cred)
                    if not r.get('is_pass', False):
                        active_backlogs += 1

                cgpa = (total_grade_points_earned / total_credits_attempted) if total_credits_attempted > 0 else 0.0
                
                # --- RENDER PROFILE HEADER ---
                st.markdown("---")
                col_img, col_det, col_met = st.columns([1, 2, 1.5])
                
                with col_img:
                    photo_bytes = fetch_student_photo(search_usn)
                    if photo_bytes:
                        st.image(photo_bytes, use_container_width=True)
                    else:
                        st.image("https://cdn.pixabay.com/photo/2015/10/05/22/37/blank-profile-picture-973460_960_720.png", use_container_width=True)
                
                with col_det:
                    st.markdown(f"### 👤 {profile.get('full_name', 'Name Not Provided')}")
                    st.markdown(f"**USN:** `{search_usn}`")
                    st.markdown(f"**Program:** {prog_type.upper()} | **Branch:** {branch_name}")
                    
                    usn_str = profile.get('usn', search_usn)
                    if len(usn_str) >= 5 and usn_str[3:5].isdigit():
                        adm_year = f"20{usn_str[3:5]}" 
                    else:
                        adm_year = "N/A"
                        
                    curr_sem = profile.get('current_semester') or profile.get('semester') or profile.get('sem') or 'N/A'
                    st.markdown(f"**Admission Year:** {adm_year} | **Current Sem:** {curr_sem}")
                    
                    email = profile.get('email')
                    phone = profile.get('phone')
                    st.markdown(f"**Email:** {email if pd.notna(email) else 'N/A'} | **Phone:** {phone if pd.notna(phone) else 'N/A'}")
                
                with col_met:
                    st.metric("Cumulative GPA (CGPA)", f"{cgpa:.2f}")
                    st.metric("Total Credits Attempted", f"{total_credits_attempted}")
                    st.metric("Active Backlogs", f"{active_backlogs}", delta_color="inverse")

                # --- RENDER SEMESTER-WISE HISTORY ---
                st.markdown("### 📚 Semester-wise Academic Transcript")
                
                if not results_history:
                    st.info("No exam records found for this student.")
                else:
                    df_res = pd.DataFrame(results_history)
                    df_res['Cycle Name'] = df_res['cycle_id'].map(lambda x: cycles_map.get(x, {}).get('cycle_name', f"Cycle: {x}"))
                    df_res['Cycle Type'] = df_res['cycle_id'].map(lambda x: cycles_map.get(x, {}).get('exam_type', 'Regular'))
                    df_res['Subject Title'] = df_res['course_code'].map(lambda x: courses_map.get(x, {}).get('title', 'Unknown Title'))
                    df_res['Credits'] = df_res['course_code'].map(lambda x: safe_float(courses_map.get(x, {}).get('credits', 0)))
                    df_res['Course Sem'] = df_res['course_code'].map(lambda x: safe_float(courses_map.get(x, {}).get(course_sem_col, 1)))
                    
                    # Calculate Max Sem per Cycle to detect Arrears written during Regular cycles
                    cycle_max_sems = df_res.groupby('cycle_id')['Course Sem'].max().to_dict()
                    
                    def determine_attempt_type(row):
                        c_type = str(row['Cycle Type']).upper()
                        cc = row['course_code']
                        
                        if 'MAKE-UP' in c_type: base = 'Make-up'
                        elif 'SUPPLEMENTARY' in c_type or 'ARREAR' in c_type: base = 'Arrear'
                        elif row['Course Sem'] < cycle_max_sems.get(row['cycle_id'], 1): base = 'Arrear'
                        else: base = 'Regular'
                        
                        if cc in reval_courses: base += ' + Reval'
                        elif cc in grace_courses: base += ' + Graced'
                            
                        return base
                        
                    df_res['Attempt Type'] = df_res.apply(determine_attempt_type, axis=1)
                    
                    # Group strictly by Course Semester
                    for sem, group in sorted(df_res.groupby('Course Sem')):
                        with st.expander(f"🎓 Semester {int(sem)} History", expanded=True):
                            group = group.sort_values(by='cycle_id')
                            
                            # SGPA based on latest cleared attempts for this specific semester
                            latest_sem_attempts = group.drop_duplicates(subset=['course_code'], keep='last')
                            sem_cr = latest_sem_attempts['Credits'].sum()
                            sem_gp = (latest_sem_attempts['grade_points'] * latest_sem_attempts['Credits']).sum()
                            sem_sgpa = (sem_gp / sem_cr) if sem_cr > 0 else 0.0
                            
                            st.markdown(f"**Final Semester SGPA: {sem_sgpa:.2f}** *(Based on latest attempts)*")
                            
                            display_cols = ['Cycle Name', 'Attempt Type', 'course_code', 'Subject Title', 'Credits', 'cie_marks', 'see_scaled', 'total_marks', 'grade', 'exam_status']
                            clean_df = group[display_cols].rename(columns={
                                'Cycle Name': 'Exam Cycle', 'Attempt Type': 'Attempt', 'course_code': 'Course', 
                                'Subject Title': 'Title', 'cie_marks': 'CIE', 'see_scaled': 'SEE', 
                                'total_marks': 'Total', 'grade': 'Grade', 'exam_status': 'Status'
                            })
                            
                            st.dataframe(clean_df, use_container_width=True, hide_index=True)

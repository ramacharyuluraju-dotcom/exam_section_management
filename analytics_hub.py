import streamlit as st
import pandas as pd
import urllib.request
from utils import init_db

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
supabase = init_db()

st.title("🌐 Global Analytics & Student 360°")
st.markdown("#### 📈 Institutional Intelligence Hub")

# --- YOUR SUPABASE PROJECT DETAILS FOR PHOTOS ---
PROJECT_ID = "zlsxqsfssczyvkjyitdg"
PHOTO_BUCKET = "StakeHolders_Photos"

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

# ==========================================
# UI TABS
# ==========================================
t1, t2, t3 = st.tabs([
    "🏫 Institutional Overview", 
    "📂 Exam Cycle Analytics", 
    "👤 Student 360° Profile"
])

# ----------------------------------------------------
# TAB 1: INSTITUTIONAL OVERVIEW (Strict Master Check)
# ----------------------------------------------------
with t1:
    st.subheader("University Demographics & Exam Status")
    
    with st.spinner("Compiling institutional data..."):
        # Strictly rely on master_students for demographic truth
        students = fetch_all_records("master_students", "usn, branch_code")
        branches = fetch_all_records("master_branches", "branch_code, program_type, branch_name")
        cycles = fetch_all_records("exam_cycles", "cycle_id, cycle_name, is_active, status_code")
        
        if students and branches:
            df_st = pd.DataFrame(students)
            df_br = pd.DataFrame(branches)
            
            # Merge to get UG/PG status for each student
            df_st = pd.merge(df_st, df_br, on='branch_code', how='left')
            
            total_students = len(df_st)
            ug_count = len(df_st[df_st['program_type'].str.upper() == 'UG'])
            pg_count = len(df_st[df_st['program_type'].str.upper() == 'PG'])
            
            active_cycles = len([c for c in cycles if c.get('is_active') == True])
            closed_cycles = len(cycles) - active_cycles
            
            # Top Metrics
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
                        
                        # Fetch master students to flag ghosts
                        stu_data = fetch_all_records("master_students", "usn, branch_code")
                        branch_map = {str(r['usn']).strip().upper(): r.get('branch_code') for r in stu_data}
                        
                        # Map branches. If not in branch_map, it's a Ghost!
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
# TAB 3: STUDENT 360° PROFILE (Strict Master Validation)
# ----------------------------------------------------
with t3:
    st.subheader("👤 Student 360° Profile")
    st.info("Search for a student to view their cumulative performance. Student MUST be registered in the Master list.")
    
    search_usn = st.text_input("🔍 Enter Student USN:").strip().upper()
    
    if search_usn and st.button("Search Student"):
        with st.spinner("Verifying Master Profile and retrieving dossier..."):
            
            # 1. STRICT GATEKEEPER: Check master_students first!
            stu_profile = supabase.table("master_students").select("*").eq("usn", search_usn).execute().data
            
            if not stu_profile:
                st.error(f"❌ USN '{search_usn}' not found in Master Database.")
                st.warning("This is a 'Ghost Record'. Please register the student in the Master Setup before viewing analytics.")
            else:
                profile = stu_profile[0]
                branch_code = profile.get('branch_code', 'N/A')
                
                # Determine UG/PG
                branch_info = supabase.table("master_branches").select("program_type, branch_name").eq("branch_code", branch_code).execute().data
                prog_type = branch_info[0].get('program_type', 'N/A') if branch_info else 'N/A'
                branch_name = branch_info[0].get('branch_name', branch_code) if branch_info else branch_code
                
                # 2. Fetch Results History
                results_history = supabase.table("student_results").select("*").eq("usn", search_usn).execute().data
                
                # Fetch Mappings
                cycles_map = {c['cycle_id']: c['cycle_name'] for c in fetch_all_records("exam_cycles", "cycle_id, cycle_name")}
                courses_map = {c['course_code']: c for c in fetch_all_records("master_courses", "course_code, title, credits")}
                
                # Calculate CGPA
                total_credits_attempted = 0.0
                total_grade_points_earned = 0.0
                active_backlogs = 0
                
                for r in results_history:
                    if r.get('grade') not in ['PND', 'PENDING', None]:
                        c_code = r.get('course_code')
                        cred = safe_float(courses_map.get(c_code, {}).get('credits', 0))
                        gp = safe_float(r.get('grade_points', 0))
                        
                        total_credits_attempted += cred
                        total_grade_points_earned += (gp * cred)
                        
                        if not r.get('is_pass', False):
                            active_backlogs += 1

                cgpa = (total_grade_points_earned / total_credits_attempted) if total_credits_attempted > 0 else 0.0
                
                # --- RENDER PROFILE UI ---
                st.markdown("---")
                
                col_img, col_det, col_met = st.columns([1, 2, 1.5])
                
                with col_img:
                    # 🟢 BULLETPROOF PHOTO FETCHER 🟢
                    photo_url = "https://cdn.pixabay.com/photo/2015/10/05/22/37/blank-profile-picture-973460_960_720.png" 
                    base_url = f"https://supabase.com/dashboard/project/zlsxqsfssczyvkjyitdg/storage/files/buckets/StakeHolders_Photos/{search_usn}"
                    
                    # We manually check the live URL for all common extensions
                    for ext in ['.jpg', '.jpeg', '.png', '.JPG', '.PNG', '.JPEG', 'webp']:
                        test_url = base_url + ext
                        try:
                            # Send a rapid "HEAD" request just to see if the file exists (returns 200 OK)
                            req = urllib.request.Request(test_url, method='HEAD')
                            with urllib.request.urlopen(req, timeout=1.5) as response:
                                if response.status == 200:
                                    photo_url = test_url
                                    break # Found it! Stop searching.
                        except Exception:
                            continue # File doesn't exist with this extension, try the next one
                    
                    st.markdown(
                        f"""
                        <div style="width: 150px; height: 180px; border-radius: 10px; overflow: hidden; border: 2px solid #ddd; background-color: #f0f0f0; display: flex; align-items: center; justify-content: center;">
                            <img src="{photo_url}" onerror="this.src='https://cdn.pixabay.com/photo/2015/10/05/22/37/blank-profile-picture-973460_960_720.png'" style="width: 100%; height: 100%; object-fit: cover;"/>
                        </div>
                        """, 
                        unsafe_allow_html=True
                    )
                
                with col_det:
                    st.markdown(f"### {profile.get('full_name', 'Name Not Provided')}")
                    st.markdown(f"**USN:** `{search_usn}`")
                    st.markdown(f"**Program:** {prog_type.upper()} | **Branch:** {branch_name}")
                    
                    # Ensure defaults are handled cleanly if the columns are missing or null
                    adm_year = profile.get('admission_year')
                    curr_sem = profile.get('current_semester')
                    st.markdown(f"**Admission Year:** {adm_year if pd.notna(adm_year) else 'N/A'} | **Current Sem:** {curr_sem if pd.notna(curr_sem) else 'N/A'}")
                    
                    email = profile.get('email')
                    phone = profile.get('phone')
                    st.markdown(f"**Email:** {email if pd.notna(email) else 'N/A'} | **Phone:** {phone if pd.notna(phone) else 'N/A'}")
                
                with col_met:
                    st.metric("Cumulative GPA (CGPA)", f"{cgpa:.2f}")
                    st.metric("Total Credits Attempted", f"{total_credits_attempted}")
                    st.metric("Active Backlogs", f"{active_backlogs}", delta_color="inverse")

                # --- RENDER ACADEMIC HISTORY ---
                st.markdown("### 📚 Academic History (Cycle-wise)")
                
                if not results_history:
                    st.info("No exam records found for this student.")
                else:
                    df_res = pd.DataFrame(results_history)
                    df_res['Cycle Name'] = df_res['cycle_id'].map(lambda x: cycles_map.get(x, f"Cycle ID: {x}"))
                    df_res['Subject Title'] = df_res['course_code'].map(lambda x: courses_map.get(x, {}).get('title', 'Unknown Title'))
                    df_res['Credits'] = df_res['course_code'].map(lambda x: safe_float(courses_map.get(x, {}).get('credits', 0)))
                    
                    for cycle_name, group in df_res.groupby('Cycle Name'):
                        with st.expander(f"📖 {cycle_name} (Evaluated Subjects: {len(group)})"):
                            
                            # Calculate SGPA
                            cyc_cr = group['Credits'].sum()
                            cyc_gp = (group['grade_points'] * group['Credits']).sum()
                            sgpa = (cyc_gp / cyc_cr) if cyc_cr > 0 else 0.0
                            
                            st.markdown(f"**Cycle SGPA: {sgpa:.2f}**")
                            
                            # Display clean dataframe
                            display_cols = ['course_code', 'Subject Title', 'Credits', 'cie_marks', 'see_scaled', 'total_marks', 'grade', 'exam_status']
                            clean_df = group[display_cols].rename(columns={
                                'course_code': 'Course', 'cie_marks': 'CIE', 'see_scaled': 'SEE', 
                                'total_marks': 'Total', 'grade': 'Grade', 'exam_status': 'Status'
                            })
                            
                            st.dataframe(clean_df, use_container_width=True, hide_index=True)

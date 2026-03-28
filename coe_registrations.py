import streamlit as st
import pandas as pd
import os
from utils import init_db, clean_data_for_db

# --- CONFIGURATION ---
# Note: st.set_page_config removed because app.py handles it
supabase = init_db()

st.title("📝 Semester Course Registration")
st.sidebar.markdown("### Operational Phase")

# --- GLOBAL CONTEXT ---
selected_cycle_id = st.session_state.get('active_cycle_id')

if not selected_cycle_id:
    st.warning("⚠️ Please select an Active Exam Cycle in the Sidebar to proceed.")
    st.stop()

st.info(f"🔵 Currently Registering Students for Cycle: **{st.session_state.get('active_cycle_name')}**")

# ==========================================
# NAVIGATION TABS
# ==========================================
reg_tabs = st.tabs(["📤 Bulk Registration", "📝 Manual Mapping", "🔍 View Registrations", "📸 Photo Backup Utility"])

# ==========================================
# 1. BULK REGISTRATION (CSV)
# ==========================================
with reg_tabs[0]:
    st.header("Step 2.1: Bulk Course Mapping")
    f_reg = st.file_uploader("Upload Registration CSV", type='csv', key="reg_bulk")
    
    if f_reg and st.button("Execute Bulk Registration"):
        df = pd.read_csv(f_reg)
        expected = ['usn', 'course_code', 'academic_year', 'semester_type']
        data = clean_data_for_db(df, expected)
        
        for row in data: 
            row['cycle_id'] = selected_cycle_id
            
        try:
            supabase.table("course_registrations").upsert(data).execute()
            st.success(f"✅ Successfully registered {len(data)} student-course mappings for this cycle.")
        except Exception as e:
            st.error(f"Registration failed: {e}")

# ==========================================
# 2. MANUAL MAPPING
# ==========================================
with reg_tabs[1]:
    st.header("Step 2.2: Individual Student Mapping")
    with st.form("manual_reg_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        r_usn = col1.text_input("Student USN")
        r_course = col2.text_input("Course Code")
        r_ay = col1.text_input("Academic Year", value="2025-26")
        r_sem = col2.selectbox("Semester Type", ["ODD", "EVEN"])
        
        c1, c2 = st.columns(2)
        if c1.form_submit_button("💾 Register Course"):
            reg_data = {"cycle_id": selected_cycle_id, "usn": r_usn.strip().upper(), "course_code": r_course.strip().upper(), "academic_year": r_ay, "semester_type": r_sem}
            try: 
                supabase.table("course_registrations").upsert(reg_data).execute()
                st.success(f"✅ Registered {r_course} for {r_usn}")
            except Exception as e: 
                st.error(f"Error: {e}")
                
        if c2.form_submit_button("🗑️ Remove Registration"):
            try: 
                supabase.table("course_registrations").delete().match({"cycle_id": selected_cycle_id, "usn": r_usn.strip().upper(), "course_code": r_course.strip().upper()}).execute()
                st.warning(f"Removed registration.")
            except Exception as e: 
                st.error(f"Error: {e}")

# ==========================================
# 3. VIEW REGISTRATIONS
# ==========================================
with reg_tabs[2]:
    st.header(f"🔍 Current Course Mappings for {st.session_state.get('active_cycle_name')}")
    search_usn = st.text_input("Filter by USN (Optional)")
    
    if st.button("Fetch Registration Data"):
        query = supabase.table("course_registrations").select("*").eq("cycle_id", selected_cycle_id)
        if search_usn: 
            query = query.eq("usn", search_usn.strip().upper())
            
        res = query.execute()
        if res.data: 
            st.dataframe(pd.DataFrame(res.data), use_container_width=True)
            st.write(f"Total Records: {len(res.data)}")
        else: 
            st.write("No registration records found.")

# ==========================================
# 4. PHOTO BACKUP UTILITY (SERVER LOCAL)
# ==========================================
with reg_tabs[3]:
    st.header("📸 Student Photo Server Backup")
    st.info("This utility connects to your Supabase bucket and downloads all student photos to a local folder on your host machine/server.")
    
    BUCKET_NAME = "StakeHolders_Photos"
    DOWNLOAD_FOLDER = "Downloaded_Student_Photos"
    
    col_a, col_b = st.columns([3, 1])
    col_a.text_input("Target Directory", value=DOWNLOAD_FOLDER, disabled=True)
    
    if st.button("🚀 Start Bulk Photo Backup", type="primary"):
        status_text = st.empty()
        progress_bar = st.progress(0)
        log_container = st.container()
        
        # 1. Folder Setup
        if not os.path.exists(DOWNLOAD_FOLDER):
            os.makedirs(DOWNLOAD_FOLDER)
            log_container.write(f"📁 Created local folder: '{DOWNLOAD_FOLDER}'")
            
        status_text.info(f"📡 Scanning Supabase bucket '{BUCKET_NAME}' for files...")
        
        try:
            # 2. Fetch file list (using options for pagination/limit if needed by your dataset size)
            files = supabase.storage.from_(BUCKET_NAME).list()
            
            if not files:
                status_text.warning("⚠️ No files found in the bucket.")
            else:
                total_files = len(files)
                status_text.info(f"✅ Found {total_files} files. Starting bulk download...")
                
                success_count = 0
                error_count = 0
                skipped_count = 0
                
                # 3. Download Loop
                for index, file_info in enumerate(files, start=1):
                    file_name = file_info.get('name')
                    
                    # Skip hidden system files or empty folder placeholders
                    if not file_name or file_name.startswith('.') or file_name == ".emptyFolderPlaceholder":
                        continue
                        
                    local_file_path = os.path.join(DOWNLOAD_FOLDER, file_name)
                    
                    # Skip if the file already exists locally
                    if os.path.exists(local_file_path):
                        skipped_count += 1
                    else:
                        try:
                            # Download raw bytes from Supabase
                            file_bytes = supabase.storage.from_(BUCKET_NAME).download(file_name)
                            
                            # Write the bytes to the local hard drive
                            with open(local_file_path, "wb") as f:
                                f.write(file_bytes)
                                
                            success_count += 1
                        except Exception as e:
                            log_container.error(f"❌ Failed to download '{file_name}': {e}")
                            error_count += 1
                            
                    # Update visual progress
                    progress_pct = index / total_files
                    progress_bar.progress(progress_pct)
                    status_text.markdown(f"**Progress:** Processing file {index} of {total_files}...")
                
                progress_bar.progress(1.0)
                st.success("🎉 --- BACKUP COMPLETE --- 🎉")
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Newly Downloaded", success_count)
                col2.metric("Skipped (Already Existed)", skipped_count)
                col3.metric("Errors", error_count)
                
        except Exception as e:
            status_text.error(f"🚨 Critical Error accessing the storage bucket: {e}")

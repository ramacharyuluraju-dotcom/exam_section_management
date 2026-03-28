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
# 4. PHOTO BACKUP UTILITY (ZIP DOWNLOAD)
# ==========================================
with reg_tabs[3]:
    st.header("📸 Student Photo Server Backup")
    st.info("This utility grabs all student photos from your Supabase cloud and packages them into a single ZIP file for you to download to your computer.")
    
    BUCKET_NAME = "StakeHolders_Photos"
    
    if st.button("🚀 Prepare Photo Backup (ZIP)", type="primary"):
        status_text = st.empty()
        progress_bar = st.progress(0)
        
        status_text.info(f"📡 Scanning Supabase bucket '{BUCKET_NAME}'...")
        
        try:
            import requests
            import io
            import zipfile
            
            # 🟢 THE FIX: Extract the URL and Key directly from the already-connected 'supabase' object
            supabase_url = supabase.supabase_url
            supabase_key = supabase.supabase_key
            
            if not supabase_url or not supabase_key:
                raise Exception("Could not extract Supabase credentials from the active connection.")
                
            api_url = f"{supabase_url.rstrip('/')}/storage/v1/object/list/{BUCKET_NAME}"
            headers = {
                "Authorization": f"Bearer {supabase_key}",
                "apikey": supabase_key,
                "Content-Type": "application/json"
            }
            
            all_files = []
            current_offset = 0
            batch_limit = 1000  # Safely request up to 1000 files in a single network call
            
            while True:
                payload = {"prefix": "", "limit": batch_limit, "offset": current_offset}
                response = requests.post(api_url, headers=headers, json=payload)
                
                if response.status_code != 200:
                    raise Exception(f"API Error: {response.text}")
                    
                batch = response.json()
                if not batch: break
                
                all_files.extend(batch)
                if len(batch) < batch_limit: break
                current_offset += batch_limit
                
            if not all_files:
                status_text.warning("⚠️ No files found in the bucket.")
            else:
                # Filter out hidden folders/files
                valid_files = [f for f in all_files if f.get('name') and not f.get('name').startswith('.')]
                total_files = len(valid_files)
                
                status_text.info(f"✅ Found {total_files} photos. Zipping them up now (this may take a minute)...")
                
                zip_buffer = io.BytesIO()
                success_count = 0
                error_count = 0
                
                # Zip the actual files
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for index, file_info in enumerate(valid_files, start=1):
                        file_name = file_info.get('name')
                        
                        try:
                            # We still use the SDK to download the actual image bytes
                            file_bytes = supabase.storage.from_(BUCKET_NAME).download(file_name)
                            zf.writestr(file_name, file_bytes)
                            success_count += 1
                        except Exception as e:
                            error_count += 1
                            
                        # Update progress bar
                        progress_bar.progress(index / total_files)
                        status_text.markdown(f"**Progress:** Zipping photo {index} of {total_files}...")
                
                # Present the Download Button
                status_text.success("🎉 ZIP file created successfully! Click below to save to your local Downloads folder.")
                
                col1, col2 = st.columns(2)
                col1.metric("Photos Zipped", success_count)
                col2.metric("Errors", error_count)
                
                st.download_button(
                    label="📥 Download All Photos (ZIP)",
                    data=zip_buffer.getvalue(),
                    file_name="Student_Photos_Backup.zip",
                    mime="application/zip",
                    type="primary"
                )
                
        except Exception as e:
            status_text.error(f"🚨 Critical Error: {e}")

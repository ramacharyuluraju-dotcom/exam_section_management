import streamlit as st

# 1. INITIALIZE MASTER PAGE CONFIG (Must be the absolute first Streamlit command)
st.set_page_config(page_title="AMC COE ERP", layout="wide", page_icon="🏛️")

from utils import init_db, global_cycle_selector
from auth import login_form, logout

# 2. SECURE GATEKEEPER
# If the user is not logged in, show the form and STOP running the rest of the app.
if not login_form():
    st.stop()

# --- Everything below this line only runs IF the user is logged in ---

supabase = init_db()

# 3. GLOBAL SIDEBAR (User Info & Controls)
st.sidebar.markdown("## 🏛️ AMC COE Office")

# Display Logged-in User Info
st.sidebar.info(f"👤 **{st.session_state['user']['name']}**\n\n🛡️ Role: {st.session_state['role']}")

if st.sidebar.button("🚪 Logout", use_container_width=True):
    logout()

# Call the switchboard for Cycle Context
global_cycle_selector(supabase)
st.sidebar.divider()

# 4. DEFINE PAGES
home_page = st.Page("home.py", title="Home Dashboard", icon="🏠", default=True)
setup_page = st.Page("main.py", title="1. Master Setup", icon="⚙️")
lifecycle_page = st.Page("exam_lifecycle.py", title="2. Exam Lifecycle", icon="📅")
registration_page = st.Page("coe_registrations.py", title="3. Registrations", icon="📝")
pre_exam_page = st.Page("coe_control.py", title="4. Pre-Exam (Docs)", icon="🖨️")
exam_day_page = st.Page("sandbox_exam_day.py", title="5. Exam Day Logistics", icon="🚀")
results_page = st.Page("coe_results.py", title="6. Results & Grading", icon="🏆")
analytics_page = st.Page("analytics_hub.py", title="7. Global Analytics", icon="📊")
utilities_page = st.Page("doc_utilities.py", title="8. Doc Generator", icon="🖨️") 

# 5. BUILD NAVIGATION MENU
pages = {
    "🏠 Welcome": [home_page],
    "📅 Exam Management": [lifecycle_page, registration_page],
    "🚀 Operations": [pre_exam_page, exam_day_page, results_page, utilities_page], 
    "📈 Intelligence": [analytics_page]
}

# Only show Administration tab to Super Users or COE
if st.session_state['role'] in ["Admin", "COE", "Super User"]:
    pages = {"⚙️ Administration": [setup_page], **pages}

pg = st.navigation(pages)

# 6. RUN APP
pg.run()

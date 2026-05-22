import streamlit as st
from supabase import create_client, Client

# ==========================================
# 1. DATABASE INITIALIZATION
# ==========================================
@st.cache_resource
def init_db() -> Client:
    """Initialize and cache the Supabase connection."""
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

# ==========================================
# 2. GLOBAL CYCLE SELECTOR (BULLETPROOF)
# ==========================================
def global_cycle_selector(supabase):
    st.sidebar.markdown("### 🔄 Exam Context")
    
    try:
        # Fetch all cycles, ordered by newest first (created_at desc)
        cycles_res = supabase.table("exam_cycles").select("*").order("created_at", desc=True).execute()
        cycles = cycles_res.data
        
        if not cycles:
            st.sidebar.warning("No Exam Cycles found. Please create one in Setup.")
            return

        # 🟢 SMART EXTRACTOR: Safely adapts to whatever your database columns are actually named
        def get_cycle_name(c):
            if c.get('cycle_name'): return c['cycle_name']
            if c.get('name'): return c['name']
            
            # Fallback if you do happen to use month/year combinations
            m = c.get('month', '')
            y = c.get('year', '')
            if m or y: return f"{m} {y}".strip()
            
            # Ultimate fallback if everything fails
            return f"Exam Cycle {c['id']}"

        # Build options dictionary safely
        cycle_options = {f"{get_cycle_name(c)} (ID: {c['id']})": c for c in cycles}
        cycle_labels = list(cycle_options.keys())

        # 🟢 AUTO-INITIALIZE: Lock in the LATEST cycle if the user just logged in
        if 'active_cycle_id' not in st.session_state:
            latest_cycle = cycles[0] 
            st.session_state['active_cycle_id'] = latest_cycle['id']
            st.session_state['active_cycle_name'] = get_cycle_name(latest_cycle)
            st.session_state['active_academic_year'] = latest_cycle.get('academic_year', '2025-26')

        # Find the index of the currently active cycle so the dropdown visual matches the background state
        current_index = 0
        for i, label in enumerate(cycle_labels):
            if cycle_options[label]['id'] == st.session_state['active_cycle_id']:
                current_index = i
                break

        # 🟢 STRICT CALLBACK: Forces an instant state update when the dropdown is changed
        def update_cycle():
            selected_label = st.session_state['cycle_selector_widget']
            selected_cycle = cycle_options[selected_label]
            
            st.session_state['active_cycle_id'] = selected_cycle['id']
            st.session_state['active_cycle_name'] = get_cycle_name(selected_cycle)
            st.session_state['active_academic_year'] = selected_cycle.get('academic_year', '2025-26')

        # The Dropdown Widget
        st.sidebar.selectbox(
            "Active Exam Cycle", 
            options=cycle_labels, 
            index=current_index,
            key='cycle_selector_widget', # Ties the visual widget to the session state
            on_change=update_cycle       # Triggers the update function the millisecond it is clicked
        )
        
        st.sidebar.success(f"✅ Active: {st.session_state['active_cycle_name']}")

    except Exception as e:
        st.sidebar.error(f"Error loading cycles: {e}")

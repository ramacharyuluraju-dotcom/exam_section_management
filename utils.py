import streamlit as st
import pandas as pd
import numpy as np
from supabase import create_client

def init_db():
    """Initializes the Supabase client using secrets."""
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

def clean_data_for_db(df, expected_cols, numeric_cols=None):
    """
    1. Filters CSV to only the columns your Supabase tables expect.
    2. Converts 'PP', '-', or empty cells in numeric columns to 0.
    3. Replaces NaNs with None for JSON compliance.
    """
    valid_cols = [c for c in expected_cols if c in df.columns]
    df = df[valid_cols].copy()

    if numeric_cols:
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].astype(str).replace('-', np.nan).replace(' ', np.nan)
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
    
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.where(pd.notnull(df), None)
    
    records = df.to_dict('records')
    return records

# --- NEW: MULTI-CYCLE SWITCHBOARD LOGIC ---

def global_cycle_selector(supabase):
    st.sidebar.markdown("### 🔄 Exam Context")
    
    try:
        # Fetch all cycles, ordered by newest first (created_at desc)
        cycles_res = supabase.table("exam_cycles").select("*").order("created_at", desc=True).execute()
        cycles = cycles_res.data
        
        if not cycles:
            st.sidebar.warning("No Exam Cycles found. Please create one in Setup.")
            return

        # Map for the selectbox
        cycle_options = {f"{c['month']} {c['year']} (ID: {c['id']})": c for c in cycles}
        cycle_labels = list(cycle_options.keys())

        # 🟢 FIX 1: Auto-initialize the LATEST cycle if the user just logged in
        if 'active_cycle_id' not in st.session_state:
            latest_cycle = cycles[0] # The most recently created cycle
            st.session_state['active_cycle_id'] = latest_cycle['id']
            st.session_state['active_cycle_name'] = f"{latest_cycle['month']} {latest_cycle['year']}"
            st.session_state['active_academic_year'] = latest_cycle.get('academic_year', '2025-26')

        # Find the index of the currently active cycle so the selectbox shows the correct one visually
        current_index = 0
        for i, label in enumerate(cycle_labels):
            if cycle_options[label]['id'] == st.session_state['active_cycle_id']:
                current_index = i
                break

        # 🟢 FIX 2: Strict Callback Function to force an instant, reliable state update
        def update_cycle():
            selected_label = st.session_state['cycle_selector_widget']
            selected_cycle = cycle_options[selected_label]
            st.session_state['active_cycle_id'] = selected_cycle['id']
            st.session_state['active_cycle_name'] = f"{selected_cycle['month']} {selected_cycle['year']}"
            st.session_state['active_academic_year'] = selected_cycle.get('academic_year', '2025-26')

        # The Dropdown Widget
        st.sidebar.selectbox(
            "Active Exam Cycle", 
            options=cycle_labels, 
            index=current_index,
            key='cycle_selector_widget', # Ties the visual widget to the session state
            on_change=update_cycle       # Triggers the function the millisecond it is clicked
        )
        
        st.sidebar.success(f"✅ Active: {st.session_state['active_cycle_name']}")

    except Exception as e:
        st.sidebar.error(f"Error loading cycles: {e}")

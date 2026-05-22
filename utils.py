import streamlit as st
import pandas as pd
import numpy as np
from supabase import create_client

@st.cache_resource
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
    
    df = df.replace([np.inf, -np.inf], np.nan).astype(object).where(pd.notnull(df), None)
    
    records = df.to_dict('records')
    for r in records:
        for k, v in r.items():
            if pd.isna(v): r[k] = None
    return records

# --- MULTI-CYCLE SWITCHBOARD LOGIC ---

def global_cycle_selector(supabase):
    """
    Displays a dropdown in the sidebar to pick the active context.
    Uses strict callbacks to prevent Streamlit UI lag.
    """
    st.sidebar.markdown("---")
    st.sidebar.subheader("🎯 Context Selector")
    
    try:
        # Fetch only cycles marked as active
        res = supabase.table("exam_cycles").select("cycle_id, cycle_name").eq("is_active", True).execute()
        cycles = res.data
        
        if not cycles:
            st.sidebar.warning("No active cycles available. Create one in Lifecycle Management.")
            st.session_state.active_cycle_id = None
            st.session_state.active_cycle_name = None
            return None

        # Prepare dictionary for selector
        options = {r['cycle_name']: r['cycle_id'] for r in cycles}
        cycle_labels = list(options.keys())
        
        # Auto-Initialize if user just logged in
        if "active_cycle_id" not in st.session_state or not st.session_state.active_cycle_id:
            st.session_state.active_cycle_id = cycles[0]['cycle_id']
            st.session_state.active_cycle_name = cycles[0]['cycle_name']

        # Determine current index for the visual widget
        default_index = 0
        if st.session_state.active_cycle_name in cycle_labels:
            default_index = cycle_labels.index(st.session_state.active_cycle_name)

        # STRICT CALLBACK: Forces instant state update
        def update_cycle():
            selected_name = st.session_state['cycle_selector_widget']
            st.session_state.active_cycle_id = options[selected_name]
            st.session_state.active_cycle_name = selected_name

        # The Widget
        st.sidebar.selectbox(
            "Select Working Cycle:",
            options=cycle_labels,
            index=default_index,
            key='cycle_selector_widget',
            on_change=update_cycle,
            help="All data on this page will filter based on this selection."
        )

        st.sidebar.success(f"Current: **{st.session_state.active_cycle_name}**")
        return st.session_state.active_cycle_id

    except Exception as e:
        st.sidebar.error(f"Cycle Fetch Error: {e}")
        return None

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
    
    df = df.replace([np.inf, -np.inf], np.nan).astype(object).where(pd.notnull(df), None)
    
    records = df.to_dict('records')
    for r in records:
        for k, v in r.items():
            if pd.isna(v): r[k] = None
    return records

# --- NEW: MULTI-CYCLE SWITCHBOARD LOGIC ---

def global_cycle_selector(supabase):
    """
    Displays a dropdown in the sidebar to pick the active context.
    Usage: Call this in main.py or at the top of every module.
    """
    st.sidebar.markdown("---")
    st.sidebar.subheader("🎯 Context Selector")
    
    try:
        # Fetch all cycles that are marked as active
        res = supabase.table("exam_cycles").select("cycle_id, cycle_name").eq("is_active", True).execute()
        
        if not res.data:
            st.sidebar.warning("No active cycles available. Create one in Lifecycle Management.")
            st.session_state.active_cycle_id = None
            st.session_state.active_cycle_name = None
            return None

        # Prepare dictionary for selector
        options = {r['cycle_name']: r['cycle_id'] for r in res.data}
        
        # Determine index to keep selection consistent across page refreshes
        default_index = 0
        if "active_cycle_name" in st.session_state and st.session_state.active_cycle_name in options:
            default_index = list(options.keys()).index(st.session_state.active_cycle_name)

        selected_name = st.sidebar.selectbox(
            "Select Working Cycle:",
            options=list(options.keys()),
            index=default_index,
            help="All data on this page will filter based on this selection."
        )

        # Update Session State
        st.session_state.active_cycle_id = options[selected_name]
        st.session_state.active_cycle_name = selected_name

        st.sidebar.success(f"Current: **{selected_name}**")
        return st.session_state.active_cycle_id

    except Exception as e:
        st.sidebar.error(f"Cycle Fetch Error: {e}")
        return None
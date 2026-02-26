import streamlit as st
import time
from utils import init_db

supabase = init_db()

def login_form():
    """Renders the login form and handles authentication"""
    if 'user' in st.session_state:
        return True

    # Center the login box nicely
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.markdown("<h2 style='text-align: center;'>🔐 AMC Exam Portal</h2>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In", use_container_width=True)
            
            if submitted:
                try:
                    # 1. Authenticate with Supabase
                    response = supabase.auth.sign_in_with_password({
                        "email": email, 
                        "password": password
                    })
                    
                    if response.user:
                        # 2. Fetch Role using EMAIL (since we uploaded emails in the CSV)
                        data = supabase.table("master_stakeholders").select("*").eq("email", email).execute()
                        
                        if data.data:
                            user_info = data.data[0]
                            
                            # 3. Save to Session State
                            st.session_state['user'] = user_info
                            st.session_state['role'] = user_info['role']
                            
                            st.success(f"Welcome, {user_info['name']}!")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("Login successful, but your email is not registered in the Staff Master database. Contact Admin.")
                    
                except Exception as e:
                    st.error(f"Login Failed: Invalid Email or Password.")
        
    return False

def logout():
    """Logs out the user and clears session"""
    supabase.auth.sign_out()
    st.session_state.clear()
    st.rerun()
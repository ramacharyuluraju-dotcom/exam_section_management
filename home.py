import streamlit as st

def show_home():
    # Header Section
    st.title("🏛️ AMC Engineering College")
    st.markdown("### Controller of Examinations (COE) Portal")
    st.divider()

    col1, col2 = st.columns([1.2, 1])

    # Left Column: Vision & Mission
    with col1:
        st.subheader("🌟 Our Vision")
        st.info("To be a premier institution in engineering education and research, producing globally competent professionals with strong ethical values.")

        st.subheader("🎯 Our Mission")
        st.success("""
        * **Impart quality technical education** through continuous improvement in teaching and learning.
        * **Foster a culture of research**, innovation, and entrepreneurship among students and faculty.
        * **Build strong industry-institute interaction** for holistic development and real-world readiness.
        """)
        
        st.markdown("*Note: You can easily edit these statements in `home.py` to match the exact official wording of the college.*")

    # Right Column: Current Activities & Quick Links
    with col2:
        st.subheader("📌 Current Activities")
        
        # Fetch the active cycle from the session state you built earlier
        active_cycle = st.session_state.get('active_cycle_name', 'No Active Cycle Selected')
        
        st.metric(label="Currently Managing", value=active_cycle)
        
        st.markdown("""
        **System Status & Updates:**
        * 🟢 **Registrations Engine:** Online and syncing.
        * 🟢 **Grading Engine:** Ready for processing.
        * 🟢 **Analytics Hub:** Tracking real-time metrics.
        """)
        
        st.divider()
        st.markdown("**Quick Actions**")
        
        # A quick-jump button to get them right into the workflow
        if st.button("Go to Exam Lifecycle ➔", type="primary", use_container_width=True):
            st.switch_page("exam_lifecycle.py")

show_home()
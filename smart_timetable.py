import streamlit as st
import pandas as pd
import io
import datetime
import networkx as nx # Ensure you run: pip install networkx
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from utils import init_db # Your existing database connection

# --- SETUP ---
supabase = init_db()
st.set_page_config(page_title="Smart Timetable Generator", layout="wide")
st.title("📅 AI Smart Timetable Generator")
st.markdown("Generates a completely conflict-free timetable by mathematically analyzing student course registrations.")

# --- HELPER FUNCTIONS ---
def fetch_all_records(table, columns="*", filter_col=None, filter_val=None):
    rows = []
    start = 0; step = 1000
    while True:
        query = supabase.table(table).select(columns)
        if filter_col and filter_val: query = query.eq(filter_col, filter_val)
        res = query.range(start, start+step-1).execute()
        if not res.data: break
        rows.extend(res.data)
        if len(res.data) < step: break
        start += step
    return rows

# --- UI CONTROLS ---
col1, col2, col3 = st.columns(3)
active_cycle_id = st.text_input("Enter Exam Cycle ID to Analyze:")
start_date = col1.date_input("Exam Start Date", datetime.date.today())
exclude_sundays = col2.checkbox("Exclude Sundays", value=True)
default_session = col3.selectbox("Default Session Layout", ["Morning & Afternoon Split", "All Morning (9:30 AM)", "All Afternoon (2:00 PM)"])

if st.button("🚀 Generate Conflict-Free Timetable", type="primary") and active_cycle_id:
    with st.spinner("Analyzing thousands of student registrations to build the conflict matrix..."):
        try:
            # 1. Fetch Data
            registrations = fetch_all_records("course_registrations", "usn, course_code", "cycle_id", active_cycle_id)
            courses_data = fetch_all_records("master_courses", "course_code, title, semester_id")
            course_dict = {c['course_code']: c for c in courses_data}

            if not registrations:
                st.error("No registrations found for this Cycle ID.")
                st.stop()

            # 2. Build the Student-to-Course Mapping
            student_courses = {}
            for reg in registrations:
                usn = reg['usn']
                cc = reg['course_code']
                if usn not in student_courses: student_courses[usn] = set()
                student_courses[usn].add(cc)

            # 3. Build the Conflict Graph
            G = nx.Graph()
            for usn, courses in student_courses.items():
                course_list = list(courses)
                for i in range(len(course_list)):
                    for j in range(i + 1, len(course_list)):
                        # Draw a conflict line between these two courses
                        G.add_edge(course_list[i], course_list[j])
            
            # Add standalone courses that have no conflicts (so they aren't left behind)
            for reg in registrations: G.add_node(reg['course_code'])

            # 4. Graph Coloring Algorithm (Greedy)
            # Strategy: 'largest_first' sorts nodes by highest degree of conflict
            coloring = nx.coloring.greedy_color(G, strategy='largest_first')

            # Group courses by their assigned "Color" (Time Bucket)
            time_buckets = {}
            for course, color in coloring.items():
                if color not in time_buckets: time_buckets[color] = []
                time_buckets[color].append(course)

            # 5. Map Buckets to Calendar Dates
            timetable_data = []
            current_date = start_date
            
            # Sort buckets sequentially
            for bucket_id in sorted(time_buckets.keys()):
                # Skip Sundays if requested
                while exclude_sundays and current_date.weekday() == 6:
                    current_date += datetime.timedelta(days=1)
                
                bucket_courses = time_buckets[bucket_id]
                
                # Assign sessions (Split evenly if requested, otherwise apply default)
                for i, cc in enumerate(bucket_courses):
                    if default_session == "Morning & Afternoon Split":
                        session = "9:30 AM - 12:30 PM" if i % 2 == 0 else "2:00 PM - 5:00 PM"
                    elif "Morning" in default_session: session = "9:30 AM - 12:30 PM"
                    else: session = "2:00 PM - 5:00 PM"

                    c_info = course_dict.get(cc, {"title": "Unknown", "semester_id": "-"})
                    timetable_data.append({
                        "cycle_id": active_cycle_id,
                        "exam_date": current_date.strftime("%Y-%m-%d"),
                        "session": session,
                        "course_code": cc,
                        "course_title": c_info['title'],
                        "semester": c_info['semester_id']
                    })
                
                current_date += datetime.timedelta(days=1) # Move to next day for the next conflict bucket

            # --- GENERATE OUTPUTS ---
            df_tt = pd.DataFrame(timetable_data)
            
            st.success(f"✅ Timetable successfully optimized into {len(time_buckets)} Exam Days!")
            st.dataframe(df_tt, use_container_width=True)

            colA, colB = st.columns(2)

            # --- CSV GENERATION (FOR ERP UPLOAD) ---
            csv_buffer = io.BytesIO()
            df_upload = df_tt[['cycle_id', 'course_code', 'exam_date', 'session']] # Exact columns needed for your DB
            df_upload.to_csv(csv_buffer, index=False)
            colA.download_button("📥 Download ERP Upload File (CSV)", csv_buffer.getvalue(), "Timetable_Upload.csv", "text/csv", use_container_width=True)

            # --- PDF GENERATION (FOR PUBLISHING) ---
            pdf_buffer = io.BytesIO()
            doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
            elements = []
            styles = getSampleStyleSheet()
            
            elements.append(Paragraph("<b>AMC ENGINEERING COLLEGE</b>", styles['Title']))
            elements.append(Paragraph("Semester End Examinations - Official Timetable", styles['Heading2']))
            elements.append(Spacer(1, 20))

            pdf_data = [["Date", "Session", "Sem", "Course Code", "Course Title"]]
            for row in timetable_data:
                pdf_data.append([
                    datetime.datetime.strptime(row['exam_date'], "%Y-%m-%d").strftime("%d-%m-%Y"),
                    row['session'],
                    str(row['semester']),
                    row['course_code'],
                    Paragraph(row['course_title'], styles['Normal'])
                ])

            t = Table(pdf_data, colWidths=[70, 110, 30, 80, 240])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ]))
            elements.append(t)
            doc.build(elements)

            colB.download_button("🖨️ Download Publishable Timetable (PDF)", pdf_buffer.getvalue(), "Official_Timetable.pdf", "application/pdf", use_container_width=True)

        except Exception as e:
            st.error(f"Critical Error computing timetable: {e}")
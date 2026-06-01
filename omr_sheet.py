import streamlit as st
import pandas as pd
from utils import init_db

supabase = init_db()

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
import io

DROPOUT_GREY = colors.Color(0.6, 0.6, 0.6)

OMR_PAGE_W, OMR_PAGE_H = A4
OMR_MARGIN = 10 * mm
OMR_CONTENT_W = OMR_PAGE_W - (2 * OMR_MARGIN)

def draw_official_header(c, width, y_top, left_logo, right_logo, college_name, is_caed=False, compact=False):
    c.saveState()
    if compact:
        logo_size = 18 * mm; font_main = 14; font_sub = 8; spacing = 4 * mm
    else:
        logo_size = 22 * mm; font_main = 16; font_sub = 9; spacing = 5 * mm

    margin_x = 8 * mm if is_caed else 10 * mm
    
    if left_logo:
        try:
            img = ImageReader(left_logo)
            c.drawImage(img, margin_x, y_top - logo_size, width=logo_size, height=logo_size, preserveAspectRatio=True, mask='auto')
        except: pass
        
    if right_logo:
        try:
            img = ImageReader(right_logo)
            c.drawImage(img, width - margin_x - logo_size, y_top - logo_size, width=logo_size, height=logo_size, preserveAspectRatio=True, mask='auto')
        except: pass

    c.setFont("Helvetica-Bold", font_main)
    c.drawCentredString(width/2.0, y_top - spacing, college_name)
    c.setFont("Helvetica", font_sub)
    
    if compact:
        c.drawCentredString(width/2.0, y_top - (spacing + 4*mm), "AMC Campus, Bannerghatta Road, Bengaluru - 560 083")
        c.drawCentredString(width/2.0, y_top - (spacing + 8*mm), "Autonomous Institution under VTU, Belagavi | Approved by AICTE | NAAC A+ Accredited")
        y_bottom = y_top - logo_size - 2*mm
    else:
        c.drawCentredString(width/2.0, y_top - (spacing + 5*mm), "AMC Campus, Bannerghatta Road, Bengaluru - 560 083")
        c.drawCentredString(width/2.0, y_top - (spacing + 9*mm), "Autonomous Institution Affiliated to VTU, Belagavi")
        c.drawCentredString(width/2.0, y_top - (spacing + 13*mm), "Approved by AICTE, New Delhi | NAAC A+ Accredited")
        y_bottom = y_top - logo_size - 4*mm

    c.setLineWidth(1.5)
    c.line(margin_x, y_bottom, width - margin_x, y_bottom)
    c.restoreState()
    return y_bottom - (4*mm if is_caed else 5*mm)

def draw_omr_watermark(c, watermark):
    if not watermark: return
    c.saveState()
    try:
        c.setFillAlpha(0.08)
        img = ImageReader(watermark)
        w_size = 120 * mm
        x = (OMR_PAGE_W - w_size)/2
        y = (OMR_PAGE_H - w_size)/2
        c.drawImage(img, x, y, width=w_size, height=w_size, mask='auto', preserveAspectRatio=True)
    except: pass
    c.restoreState()

def draw_omr_titles_and_serial(c, y_start, exam_type="SEMESTER END EXAMINATION"):
    c.saveState()
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(OMR_PAGE_W / 2.0, y_start, exam_type)
    
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.red)
    c.drawRightString(OMR_PAGE_W - OMR_MARGIN, y_start, "Sl. No: ________________")
    c.setFillColor(colors.black)
    
    c.restoreState()
    return y_start - 8 * mm

def draw_omr_details_with_qr(c, y_start, name, usn, course_code):
    c.saveState()
    box_y = y_start - 25 * mm
    c.setLineWidth(1)
    c.rect(OMR_MARGIN, box_y, OMR_CONTENT_W, 25 * mm)
    
    c.setFont("Helvetica-Bold", 10)
    col_x = OMR_MARGIN + 5 * mm
    line_h = 7 * mm
    
    c.drawString(col_x, box_y + 18 * mm, f"Candidate Name : {name}")
    c.drawString(col_x, box_y + 11 * mm, f"USN : {usn}")
    c.drawString(col_x, box_y + 4 * mm,  f"Course Code : {course_code}")
    
    qr_data = f"{usn}|{course_code}"
    qr_code = qr.QrCodeWidget(qr_data)
    qr_code.barWidth = 20 * mm
    qr_code.barHeight = 20 * mm
    qr_drawing = Drawing(20*mm, 20*mm)
    qr_drawing.add(qr_code)
    
    renderPDF.draw(qr_drawing, c, OMR_PAGE_W - OMR_MARGIN - 25 * mm, box_y + 2.5 * mm)
    c.restoreState()
    return box_y - 6 * mm

def draw_omr_instructions_compact(c, y_start):
    c.saveState()
    c.setFont("Helvetica-Bold", 9)
    c.drawString(OMR_MARGIN, y_start, "INSTRUCTIONS TO CANDIDATES:")
    
    c.setFont("Helvetica", 8)
    inst = [
        "1. Use Black / Blue ball point pen only to darken the circles.",
        "2. Darken the circles completely. Do not put tick mark or cross mark.",
        "3. Do not make any stray marks on this OMR sheet.",
        "4. Folding, tearing or wrinkling of this sheet is strictly prohibited."
    ]
    
    y = y_start - 4 * mm
    for idx, txt in enumerate(inst):
        if idx % 2 == 0: x = OMR_MARGIN
        else: x = OMR_PAGE_W / 2.0; y += 4 * mm
        c.drawString(x, y, txt)
        y -= 4 * mm
        
    c.restoreState()
    return y - 2 * mm

def draw_isolated_version_block(c, y_start):
    c.saveState()
    block_w = 40 * mm
    block_h = 20 * mm
    x_start = OMR_PAGE_W - OMR_MARGIN - block_w
    
    c.setLineWidth(1)
    c.rect(x_start, y_start - block_h, block_w, block_h)
    
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(x_start + block_w/2, y_start - 4*mm, "VERSION CODE")
    
    options = ['A', 'B', 'C', 'D']
    radius = 2 * mm
    spacing = 7 * mm
    
    start_x = x_start + (block_w - (len(options)-1)*spacing)/2
    circ_y = y_start - 12*mm
    
    c.setFont("Helvetica", 8)
    c.setFillColor(DROPOUT_GREY)
    
    for i, opt in enumerate(options):
        cx = start_x + i * spacing
        c.setLineWidth(0.5)
        c.circle(cx, circ_y, radius)
        
        # Center the letter mathematically inside the circle
        c.drawCentredString(cx, circ_y - 1*mm, opt)
        
    c.restoreState()
    return y_start - block_h - 10 * mm

def draw_signatures_block(c, y_start):
    c.saveState()
    c.setLineWidth(1)
    
    box_w = OMR_CONTENT_W / 3.0
    c.rect(OMR_MARGIN, y_start - 15 * mm, box_w, 15 * mm)
    c.rect(OMR_MARGIN + box_w, y_start - 15 * mm, box_w, 15 * mm)
    c.rect(OMR_MARGIN + 2*box_w, y_start - 15 * mm, box_w, 15 * mm)
    
    c.setFont("Helvetica", 8)
    c.drawCentredString(OMR_MARGIN + box_w/2, y_start - 13*mm, "Signature of the Candidate")
    c.drawCentredString(OMR_MARGIN + 1.5*box_w, y_start - 13*mm, "Signature of the Invigilator")
    c.drawCentredString(OMR_MARGIN + 2.5*box_w, y_start - 13*mm, "Signature of Chief Superintendent")
    
    c.restoreState()
    return y_start - 25 * mm

def draw_4_corner_question_block(c, x_start, y_start, block_w, num_questions):
    c.saveState()
    
    col_w = block_w / 4.0
    radius = 2 * mm
    q_spacing_y = 5.2 * mm 
    opts_spacing_x = 5.5 * mm
    
    c.setLineWidth(1)
    c.rect(x_start, y_start - (25 * q_spacing_y + 10 * mm), block_w, 25 * q_spacing_y + 10 * mm)
    
    # Draw tracking anchors on the corners of the box for Computer Vision
    anchor_w = 4 * mm
    c.setFillColor(colors.black)
    c.rect(x_start, y_start - anchor_w, anchor_w, anchor_w, fill=1) # Top-Left
    c.rect(x_start + block_w - anchor_w, y_start - anchor_w, anchor_w, anchor_w, fill=1) # Top-Right
    c.rect(x_start, y_start - (25 * q_spacing_y + 10 * mm), anchor_w, anchor_w, fill=1) # Bottom-Left
    c.rect(x_start + block_w - anchor_w, y_start - (25 * q_spacing_y + 10 * mm), anchor_w, anchor_w, fill=1) # Bottom-Right
    
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(colors.black)
    
    c.drawCentredString(x_start + 1*col_w, y_start - 5*mm, "Q.No")
    c.drawCentredString(x_start + 2*col_w, y_start - 5*mm, "Q.No")
    c.drawCentredString(x_start + 3*col_w, y_start - 5*mm, "Q.No")
    
    c.setLineWidth(0.5)
    c.line(x_start, y_start - 7*mm, x_start + block_w, y_start - 7*mm)
    
    c.line(x_start + col_w, y_start, x_start + col_w, y_start - (25 * q_spacing_y + 10 * mm))
    c.line(x_start + 2*col_w, y_start, x_start + 2*col_w, y_start - (25 * q_spacing_y + 10 * mm))
    c.line(x_start + 3*col_w, y_start, x_start + 3*col_w, y_start - (25 * q_spacing_y + 10 * mm))

    c.setFont("Helvetica", 8)
    
    for q in range(1, num_questions + 1):
        col_idx = (q - 1) // 25
        row_idx = (q - 1) % 25
        
        cx = x_start + (col_idx * col_w)
        cy = y_start - 10*mm - (row_idx * q_spacing_y)
        
        c.setFillColor(colors.black)
        c.drawRightString(cx + 6*mm, cy - 1*mm, str(q).zfill(2))
        
        c.setFillColor(DROPOUT_GREY)
        opt_start_x = cx + 9 * mm
        for i, opt in enumerate(['A', 'B', 'C', 'D']):
            ox = opt_start_x + (i * opts_spacing_x)
            c.circle(ox, cy, radius)
            c.drawCentredString(ox, cy - 1*mm, opt)
            
    c.restoreState()


def draw_caed_grid(c, y_start):
    c.saveState()
    c.setLineWidth(0.5)
    c.setStrokeColor(colors.gray)
    
    grid_w = A4[0] - 16 * mm
    grid_h = y_start - 12 * mm
    start_x = 8 * mm
    start_y = 8 * mm
    
    step = 5 * mm
    for x in range(int(start_x), int(start_x + grid_w) + 1, int(step)):
        c.line(x, start_y, x, start_y + grid_h)
        
    for y in range(int(start_y), int(start_y + grid_h) + 1, int(step)):
        c.line(start_x, y, start_x + grid_w, y)
        
    c.setLineWidth(1)
    c.setStrokeColor(colors.black)
    c.rect(start_x, start_y, grid_w, grid_h)
    c.restoreState()

def draw_caed_details_box(c, y_start):
    c.saveState()
    margin_x = 8 * mm
    box_w = A4[0] - (2 * margin_x)
    box_h = 30 * mm
    box_y = y_start - box_h
    
    c.setLineWidth(1)
    c.rect(margin_x, box_y, box_w, box_h)
    
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(A4[0]/2.0, box_y + 24*mm, "SEMESTER END EXAMINATION - ANSWER SHEET (CAED)")
    
    c.setFont("Helvetica", 10)
    col1 = margin_x + 5 * mm
    col2 = A4[0] / 2.0
    
    c.drawString(col1, box_y + 15*mm, "USN: ___________________________")
    c.drawString(col2, box_y + 15*mm, "Name: _____________________________________")
    
    c.drawString(col1, box_y + 5*mm,  "Date: ___________________________")
    c.drawString(col2, box_y + 5*mm,  "Signature of Candidate: ____________________")
    
    c.restoreState()
    return box_y - 5 * mm


def generate_batch_omr_pdf(college, left_logo, right_logo, watermark, students_data, course_code, exam_type, num_qs):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"OMR_{course_code}")
    
    cols = [c.upper().strip() for c in students_data.columns]
    usn_col = students_data.columns[cols.index('USN')] if 'USN' in cols else students_data.columns[0]
    name_col = students_data.columns[cols.index('NAME')] if 'NAME' in cols else students_data.columns[1] if len(students_data.columns) > 1 else None

    for (_, student) in students_data.iterrows():
        usn = str(student[usn_col])
        name = str(student[name_col]) if name_col else ''
        
        draw_omr_watermark(c, watermark)
        
        y_start = OMR_PAGE_H - 12 * mm
        curr_y = draw_official_header(c, OMR_PAGE_W, y_start, left_logo, right_logo, college)
        
        curr_y = draw_omr_titles_and_serial(c, curr_y, exam_type)
        curr_y = draw_omr_details_with_qr(c, curr_y, name, usn, course_code)
        
        curr_y = draw_omr_instructions_compact(c, curr_y)
        
        curr_y = draw_signatures_block(c, curr_y)
        
        curr_y = draw_isolated_version_block(c, curr_y)
        
        if num_qs <= 50:
            block_w = 150 * mm
            x_start = (OMR_PAGE_W - block_w) / 2
            draw_4_corner_question_block(c, x_start, curr_y, block_w, 50)
        else:
            block_w = 190 * mm
            x_start = (OMR_PAGE_W - block_w) / 2
            draw_4_corner_question_block(c, x_start, curr_y, block_w, 100)
            
        c.showPage()

    c.save()
    return buf.getvalue()

def generate_caed_pdf(college, left_logo, right_logo):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("CAED_Answer_Sheet")
    
    y_start = OMR_PAGE_H - 10 * mm
    curr_y = draw_official_header(c, OMR_PAGE_W, y_start, left_logo, right_logo, college, is_caed=True, compact=True)
    curr_y = draw_caed_details_box(c, curr_y)
    draw_caed_grid(c, curr_y)
    
    c.showPage()
    c.save()
    return buf.getvalue()

def generate_diary_pdf(college, left_logo, right_logo):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    c.setTitle("Relieving_Diary")
    
    W, H = landscape(A4)
    margin = 12 * mm
    
    c.setLineWidth(2)
    c.rect(margin, margin, W - 2*margin, H - 2*margin)
    
    y_start = H - 20 * mm
    draw_official_header(c, W, y_start, left_logo, right_logo, college)
    
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(W/2.0, H - 45*mm, "RELIEVING ORDER / ATTENDANCE CERTIFICATE")
    
    c.setFont("Helvetica", 12)
    text_y = H - 65*mm
    line_h = 10*mm
    start_x = 20 * mm
    
    c.drawString(start_x, text_y, "This is to certify that Prof. / Dr. / Mr. / Ms. ____________________________________________________________________")
    c.drawString(start_x, text_y - line_h, "of ______________________________________________________________________________ College / Institution has")
    c.drawString(start_x, text_y - 2*line_h, "attended duty as __________________________________________ at AMC Engineering College, Bengaluru Centre")
    c.drawString(start_x, text_y - 3*line_h, "from ______________ to ______________. He / She is relieved of his / her duties on ______________ at _______.")
    
    c.setFont("Helvetica-Bold", 12)
    c.drawString(start_x, margin + 20*mm, "Date:")
    c.drawRightString(W - start_x, margin + 20*mm, "Chief Superintendent")
    
    c.showPage()
    c.save()
    return buf.getvalue()

# ================================
# STREAMLIT UI
# ================================
st.set_page_config(page_title="PDF Operations Generator", layout="wide")

st.title("🖨️ Form & Sheet Generator")
college_name = "AMC ENGINEERING COLLEGE"

col_left, col_right = st.columns([1, 2])

with col_left:
    st.subheader("Global Assets")
    left_logo = st.file_uploader("Left Logo", type=["png", "jpg"])
    right_logo = st.file_uploader("Right Logo", type=["png", "jpg"])
    
    sheet_type = st.radio("Select Document Type", ["Batch OMR Sheets", "CAED Printout Sheet", "Relieving Diary"])
    
    if "OMR" in sheet_type:
        watermark = st.file_uploader("Watermark", type=["png", "jpg"]) if "OMR" in sheet_type else None

with col_right:
    st.subheader("Configuration & Generation")
    
    if sheet_type == "Batch OMR Sheets":
        st.markdown("### Exam Details")
        col1, col2 = st.columns(2)
        with col1:
            course_code = st.text_input("Course Code (e.g., 1BMATC101)", "1BXX")
        with col2:
            exam_type = st.text_input("Exam Type", "SEMESTER END EXAMINATION")
            
        st.markdown("### Grid Setup")
        num_qs = st.selectbox("Number of Questions", [50, 100])
        
        st.markdown("### Target Audience")
        st.markdown("Upload a CSV containing only the **USN** column. The system will auto-fetch names from the database.")
        uploaded_file = st.file_uploader("Upload USN List (CSV)", type=["csv"])
        
        if uploaded_file is not None:
            try:
                # 1. Read the uploaded USNs
                df_uploaded = pd.read_csv(uploaded_file)
                cols = [c.upper().strip() for c in df_uploaded.columns]
                
                # Find the USN column (defaults to the first column if no header named 'USN' is found)
                usn_col = df_uploaded.columns[cols.index('USN')] if 'USN' in cols else df_uploaded.columns[0]
                
                # Clean the USN list (remove spaces, make uppercase)
                usn_list = df_uploaded[usn_col].astype(str).str.strip().str.upper().tolist()
                
                with st.spinner("Fetching student details from Master Database..."):
                    all_stus = []
                    chunk_size = 200 # Fetch in chunks of 200 to keep database queries lightweight
                    
                    for i in range(0, len(usn_list), chunk_size):
                        chunk = usn_list[i : i + chunk_size]
                        
                        # Query the master_students table for these specific USNs
                        res = supabase.table("master_students").select("usn, full_name").in_("usn", chunk).execute()
                        if res.data:
                            all_stus.extend(res.data)
                    
                    if not all_stus:
                        st.error("⚠️ No matching students found in the master database for the uploaded USNs.")
                    else:
                        # 2. Build the final DataFrame for the PDF generator
                        df = pd.DataFrame(all_stus)
                        
                        # Rename columns to match exactly what your generate_batch_omr_pdf function expects
                        df.rename(columns={'usn': 'USN', 'full_name': 'NAME'}, inplace=True)
                        
                        # Sort them alphabetically by USN just to be clean
                        df = df.sort_values('USN').reset_index(drop=True)
                        
                        st.success(f"✅ Successfully loaded and verified {len(df)} students.")
                        st.dataframe(df.head()) # Preview the matched data
                        
                        if st.button("Generate Batch OMR PDFs", type="primary"):
                            pdf_out = generate_batch_omr_pdf(college_name, left_logo, right_logo, watermark, df, course_code, exam_type, num_qs)
                            fname = f"AMC_OMR_{course_code}_{num_qs}Q_Batch.pdf"
                            st.download_button("Download Exam Batch", pdf_out, fname, "application/pdf")
            
            except Exception as e:
                st.error(f"Error processing file or database fetch: {e}")
        else:
            st.info("Waiting for CSV upload.")

    elif st.button("Generate PDF", type="primary"):
        if sheet_type == "CAED Printout Sheet":
            pdf_out = generate_caed_pdf(college_name, left_logo, right_logo)
            fname = "AMC_CAED.pdf"
        else:
            pdf_out = generate_diary_pdf(college_name, left_logo, right_logo)
            fname = "AMC_Relieving_Diary.pdf"
            
        st.success(f"{sheet_type} Generated!")
        st.download_button("Download PDF", pdf_out, fname, "application/pdf")

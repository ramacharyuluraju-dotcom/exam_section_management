import streamlit as st
import pandas as pd
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
import io

# ==========================================
#        TONER SAVER & CV OPTIMIZATIONS
# ==========================================
# This specific grey will be printed cheaply but will be 
# completely erased ("dropped out") by the OpenCV scanner.
DROPOUT_GREY = colors.Color(0.6, 0.6, 0.6)

# ==========================================
#        SHARED HEADER FUNCTIONS
# ==========================================

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
            c.drawImage(img, margin_x, y_top - logo_size + (spacing/2), width=logo_size, height=logo_size, mask='auto', preserveAspectRatio=True)
        except: pass

    if right_logo:
        try:
            img = ImageReader(right_logo)
            right_x = width - margin_x - logo_size
            c.drawImage(img, right_x, y_top - logo_size + (spacing/2), width=logo_size, height=logo_size, mask='auto', preserveAspectRatio=True)
        except: pass

    c.setFillColor(colors.black)
    center_x = width / 2
    c.setFont("Helvetica-Bold", font_main)
    c.drawCentredString(center_x, y_top, college_name)
    c.setFont("Helvetica", font_sub)
    c.drawCentredString(center_x, y_top - spacing, "AMC Campus, Bannerghatta Road, Bengaluru, Karnataka - 560083")
    c.drawCentredString(center_x, y_top - (2*spacing), "Autonomous Institution Affiliated to VTU, Belagavi")
    c.setFont("Helvetica-Bold", font_sub)
    c.drawCentredString(center_x, y_top - (3*spacing), "Approved by AICTE, New Delhi | NAAC A+ Accredited")
    c.restoreState()
    return y_top - (3*spacing) - 5*mm

# ==========================================
#        LOGIC FOR BATCH OMR SHEET
# ==========================================

OMR_PAGE_W, OMR_PAGE_H = A4
OMR_MARGIN = 10 * mm
OMR_CONTENT_W = OMR_PAGE_W - (2 * OMR_MARGIN)

def draw_omr_watermark(c, watermark_stream):
    if watermark_stream:
        try:
            c.saveState()
            c.setFillAlpha(0.08)
            img = ImageReader(watermark_stream)
            img_w, img_h = 130 * mm, 130 * mm
            c.drawImage(img, (OMR_PAGE_W - img_w)/2, (OMR_PAGE_H - img_h)/2, 
                        width=img_w, height=img_h, mask='auto', preserveAspectRatio=True)
            c.restoreState()
        except: pass

def draw_omr_titles_and_serial(c, y_start, exam_type):
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 11)
    
    c.drawCentredString(OMR_PAGE_W / 2, y_start - 5*mm, exam_type.upper())
    
    c.setFont("Helvetica-Bold", 14)
    omr_title_y = y_start - 11*mm
    c.drawCentredString(OMR_PAGE_W / 2, omr_title_y, "OMR ANSWER SHEET")
    
    # Border converted to Dropout Grey
    c.saveState(); c.setStrokeColor(DROPOUT_GREY)
    box_w = 35 * mm; box_h = 7 * mm
    box_x = OMR_PAGE_W - OMR_MARGIN - box_w; box_y = omr_title_y - 2*mm 
    c.rect(box_x, box_y, box_w, box_h)
    
    # Text stays black for human readability
    c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 9)
    c.drawString(box_x - 16*mm, box_y + 2*mm, "Serial No:"); c.restoreState()
    return y_start - 16*mm

def draw_omr_details_with_qr(c, y_start, student_name, usn, course_code):
    total_h = 30 * mm
    y_bottom = y_start - total_h
    
    # Outer Border and Divider converted to Dropout Grey
    c.saveState()
    c.setStrokeColor(DROPOUT_GREY)
    c.setLineWidth(1)
    c.rect(OMR_MARGIN, y_bottom, OMR_CONTENT_W, total_h)
    mid_x = OMR_PAGE_W - OMR_MARGIN - 45*mm 
    c.line(mid_x, y_bottom, mid_x, y_start)
    c.restoreState() 
    
    # Printed Details stay black for human readability
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 11)
    text_x = OMR_MARGIN + 5*mm
    c.drawString(text_x, y_start - 8*mm, f"Student Name:  {student_name}")
    c.drawString(text_x, y_start - 16*mm, f"USN:           {usn}")
    c.drawString(text_x, y_start - 24*mm, f"Course Code:   {course_code}")
    
    # QR Code MUST stay Black
    qr_data = f"{usn}|{course_code}"
    qr_code = qr.QrCodeWidget(qr_data)
    bounds = qr_code.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    
    # Toner Saver QR (17mm)
    qr_size = 17 * mm
    d = Drawing(qr_size, qr_size, transform=[qr_size/width, 0, 0, qr_size/height, 0, 0])
    d.add(qr_code)
    
    qr_x_pos = mid_x + 14 * mm
    qr_y_pos = y_bottom + 6.5 * mm
    renderPDF.draw(d, c, qr_x_pos, qr_y_pos)
    
    return y_bottom - 4*mm 

def draw_omr_instructions_compact(c, y_start):
    box_h = 28 * mm 
    y_bottom = y_start - box_h
    
    # Box converted to Dropout Grey
    c.saveState(); c.setStrokeColor(DROPOUT_GREY); c.rect(OMR_MARGIN, y_bottom, OMR_CONTENT_W, box_h); c.restoreState()
    
    # Text stays black for human readability
    c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 9)
    c.drawString(OMR_MARGIN + 3*mm, y_start - 5*mm, "INSTRUCTIONS TO STUDENTS")
    c.setFont("Helvetica", 8)
    lines = ["1. No extra marking on OMR sheet.", "2. Use Black Ball Point Pen ONLY.", 
             "3. Darken the circle completely.", "4. Do not make stray marks.", "5. Multiple markings are invalid."]
    curr_y = y_start - 9*mm
    for line in lines: c.drawString(OMR_MARGIN + 3*mm, curr_y, line); curr_y -= 3.5*mm
    
    # Instruction diagrams converted to Dropout Grey
    mid_right_x = OMR_PAGE_W/2 + 5*mm; labels_y = y_start - 5*mm
    c.setFont("Helvetica-Bold", 7); c.drawString(mid_right_x, labels_y, "CORRECT METHOD:")
    c.saveState(); c.setFillColor(DROPOUT_GREY); c.circle(mid_right_x + 35*mm, labels_y + 1.5*mm, 3*mm, fill=1, stroke=0); c.restoreState()
    c.drawString(mid_right_x, labels_y - 8*mm, "WRONG METHODS:")
    gap = 10*mm; start_ex = mid_right_x + 30*mm; ex_y = labels_y - 8*mm + 1.5*mm 
    
    c.saveState(); c.setStrokeColor(DROPOUT_GREY)
    c.circle(start_ex, ex_y, 3*mm); c.line(start_ex-2*mm, ex_y-2*mm, start_ex+2*mm, ex_y+2*mm); c.line(start_ex-2*mm, ex_y+2*mm, start_ex+2*mm, ex_y-2*mm)
    c.circle(start_ex+gap, ex_y, 3*mm); c.line(start_ex+gap-2*mm, ex_y, start_ex+gap-0.5*mm, ex_y-2*mm); c.line(start_ex+gap-0.5*mm, ex_y-2*mm, start_ex+gap+2*mm, ex_y+2*mm)
    c.circle(start_ex+2*gap, ex_y, 3*mm); p = c.beginPath(); p.moveTo(start_ex+2*gap, ex_y); p.arc(start_ex+2*gap-3*mm, ex_y-3*mm, start_ex+2*gap+3*mm, ex_y+3*mm, 90, 180); p.close(); c.setFillColor(DROPOUT_GREY); c.drawPath(p, fill=1, stroke=0)
    c.restoreState()
    return y_bottom - 4*mm

def draw_omr_signatures_and_version(c, y_start):
    sig_h = 15 * mm; sig_bottom = y_start - sig_h; col_w = OMR_CONTENT_W / 3
    
    # Signature box borders converted to Dropout Grey
    c.saveState(); c.setStrokeColor(DROPOUT_GREY); c.rect(OMR_MARGIN, sig_bottom, OMR_CONTENT_W, sig_h)
    c.line(OMR_MARGIN + col_w, sig_bottom, OMR_MARGIN + col_w, y_start); c.line(OMR_MARGIN + 2*col_w, sig_bottom, OMR_MARGIN + 2*col_w, y_start); c.restoreState()
    
    c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(OMR_MARGIN + col_w/2, y_start - 3*mm, "Student's Signature")
    c.drawCentredString(OMR_MARGIN + 1.5*col_w, y_start - 3*mm, "Date")
    c.drawCentredString(OMR_MARGIN + 2.5*col_w, y_start - 3*mm, "Invigilator's Signature")
    
    c.saveState(); c.setFillColor(colors.black, alpha=0.3); c.setFont("Helvetica", 10)
    c.drawCentredString(OMR_MARGIN + 1.5*col_w, sig_bottom + 4*mm, "DD / MM / YYYY")
    c.restoreState()
    
    version_y_start = sig_bottom - 3*mm; version_h = 10 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(OMR_PAGE_W/2, version_y_start - 2*mm, "Question Paper Version Code")
    
    c.saveState()
    bubble_y = version_y_start - 7*mm 
    spacing = 15 * mm 
    total_bubble_w = 3 * spacing 
    start_x = (OMR_PAGE_W - total_bubble_w) / 2
    
    # MUST BE BLACK: Version Anchor (Shrunk to 3.5mm)
    c.setFillColor(colors.black)
    c.rect(start_x - 12*mm, bubble_y - 1.75*mm, 3.5*mm, 3.5*mm, fill=1, stroke=0)
    
    # DROPOUT GREY: Version Bubbles and inner text
    c.setStrokeColor(DROPOUT_GREY)
    for i, opt in enumerate(['A', 'B', 'C', 'D']):
        bx = start_x + (i*spacing)
        c.circle(bx, bubble_y, 3.5*mm)
        c.setFillColor(DROPOUT_GREY); c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(bx, bubble_y - 1*mm, opt)
        
    c.restoreState()
    return version_y_start - version_h - 4*mm

def draw_omr_answer_box(c, y_start):
    c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 10); c.drawCentredString(OMR_PAGE_W / 2, y_start, "ANSWERS")
    y_box_top = y_start - 4*mm; row_h = 7.0 * mm; total_grid_h = 17 * row_h + 5*mm; y_box_bottom = y_box_top - total_grid_h
    
    # Answer box border converted to Dropout Grey
    c.saveState(); c.setStrokeColor(DROPOUT_GREY); c.rect(OMR_MARGIN, y_box_bottom, OMR_CONTENT_W, total_grid_h); c.restoreState()
    
    col_w = OMR_CONTENT_W / 3
    col1_x = OMR_MARGIN + 8*mm
    col2_x = OMR_MARGIN + col_w + 8*mm
    col3_x = OMR_MARGIN + 2*col_w + 8*mm
    start_y = y_box_top - 6*mm 
    
    for q in range(1, 51):
        if q <= 17: x_base = col1_x; row = q - 1
        elif q <= 34: x_base = col2_x; row = q - 18
        else: x_base = col3_x; row = q - 35
        
        y_pos = start_y - (row * row_h)
        
        # MUST BE BLACK: Question Anchors (Shrunk to 3.5mm)
        c.saveState()
        c.setFillColor(colors.black)
        c.rect(x_base - 6*mm, y_pos - 0.75*mm, 3.5*mm, 3.5*mm, fill=1, stroke=0)
        c.restoreState()
        
        # Stays Black: Question Numbers (for human readability)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(x_base + 4*mm, y_pos, f"{q}.")
        
        # DROPOUT GREY: The Bubbles and the Letters inside them
        spacing = 8.5*mm; b_start = x_base + 8*mm
        for i, opt in enumerate(['A', 'B', 'C', 'D']):
            bx = b_start + (i*spacing); by = y_pos + 1.5*mm
            c.saveState()
            c.setStrokeColor(DROPOUT_GREY)
            c.circle(bx, by, 3.2*mm)
            c.restoreState()
            
            c.setFillColor(DROPOUT_GREY)
            c.setFont("Helvetica", 6.5)
            c.drawCentredString(bx, by - 1*mm, opt)
            
    return y_box_bottom

def generate_batch_omr_pdf(college, left_logo, right_logo, watermark, students_data, course_code, exam_type):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    
    for _, student in students_data.iterrows():
        usn = str(student.get('USN', student.iloc[0]))
        name = str(student.get('Name', student.iloc[1]))
        
        draw_omr_watermark(c, watermark)
        y_start = OMR_PAGE_H - 12*mm 
        
        header_end = draw_official_header(c, OMR_PAGE_W, y_start, left_logo, right_logo, college)
        curr_y = draw_omr_titles_and_serial(c, header_end, exam_type) 
        curr_y = draw_omr_details_with_qr(c, curr_y, name, usn, course_code) 
        curr_y = draw_omr_instructions_compact(c, curr_y)
        curr_y = draw_omr_signatures_and_version(c, curr_y) 
        draw_omr_answer_box(c, curr_y)
        
        c.showPage()
        
    c.save()
    buffer.seek(0)
    return buffer

# ==========================================
#        LOGIC FOR CAED & DIARY (Untouched)
# ==========================================
def generate_caed_pdf(college, left_logo, right_logo):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    width, height = landscape(A4); margin = 5 * mm; content_w = width - 2*margin
    y_header_start = height - 10*mm
    header_bottom_y = draw_official_header(c, width, y_header_start, left_logo, right_logo, college, is_caed=True)
    title_line_y = header_bottom_y - 6*mm
    c.setFont("Helvetica-Bold", 12); c.drawCentredString(width/2, title_line_y, "PRINTOUT SHEET FOR ALL COMPUTER AIDED DRAWING SUBJECTS")
    serial_box_w = 35 * mm; serial_box_h = 7 * mm; serial_x = width - margin - serial_box_w; serial_y = title_line_y - 2.5*mm 
    c.rect(serial_x, serial_y, serial_box_w, serial_box_h); c.setFont("Helvetica-Bold", 10); c.drawString(serial_x - 18*mm, serial_y + 2*mm, "Serial No:")
    drawing_top = serial_y - 5*mm
    footer_height = 15 * mm; footer_bottom_y = margin; footer_top_y = footer_bottom_y + footer_height
    c.setLineWidth(1); c.rect(margin, footer_bottom_y, content_w, footer_height)
    col1 = content_w * 0.15; col2 = content_w * 0.25; col3 = content_w * 0.25; col4 = content_w * 0.35; x = margin
    c.line(x+col1, footer_bottom_y, x+col1, footer_top_y); c.setFont("Helvetica-Bold", 10); c.drawString(x+5*mm, footer_bottom_y + 5*mm, "Question No:")
    x += col1; c.line(x+col2, footer_bottom_y, x+col2, footer_top_y); c.drawString(x+5*mm, footer_bottom_y + 5*mm, "USN:")
    x += col2; c.line(x+col3, footer_bottom_y, x+col3, footer_top_y); c.drawString(x+5*mm, footer_bottom_y + 5*mm, "Student's Signature")
    x += col3; ex_w = col4 / 2; c.line(x+ex_w, footer_bottom_y, x+ex_w, footer_top_y); c.drawString(x+5*mm, footer_bottom_y + 5*mm, "Examiner 1"); c.drawString(x+ex_w+5*mm, footer_bottom_y + 5*mm, "Examiner 2")
    drawing_bottom = footer_top_y + 5*mm; drawing_height = drawing_top - drawing_bottom
    c.setLineWidth(1.5); c.rect(margin, drawing_bottom, content_w, drawing_height)
    c.showPage(); c.save(); buffer.seek(0)
    return buffer

def draw_diary_form(c, start_y, width, college, left_logo, right_logo):
    margin = 10 * mm; content_w = width - 2*margin
    y = draw_official_header(c, width, start_y, left_logo, right_logo, college, compact=True)
    c.setFont("Helvetica-Bold", 12); c.drawCentredString(width/2, y - 5*mm, "RELIEVING SUPERINTENDENT'S DIARY")
    c.setFont("Helvetica-Bold", 10); c.drawCentredString(width/2, y - 10*mm, "B.E./B.Arch/M.Tech/M.B.A/M.C.A/M.Arch Semester Examination ...........................")
    y -= 20 * mm; c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "Centre: ........................................................................"); c.drawString(width - margin - 60*mm, y, "Date: ........................")
    y -= 8 * mm; c.drawString(margin, y, "Name of Relieving Superintendent: ........................................................................"); c.drawString(width - margin - 60*mm, y, "Time: ........... to ...........")
    y -= 8 * mm; c.drawString(margin, y, "Centre Code: ........................")
    y -= 5 * mm; table_top = y; row_h = 7 * mm; header_h = 12 * mm; num_rows = 7; table_h = header_h + (num_rows * row_h)
    col1 = content_w * 0.08; col2 = content_w * 0.12; col3 = content_w * 0.30; col4 = content_w * 0.25; col5 = content_w * 0.25
    c.rect(margin, table_top - table_h, content_w, table_h); x = margin
    c.line(x+col1, table_top, x+col1, table_top - table_h); x += col1; c.line(x+col2, table_top, x+col2, table_top - table_h); x += col2; c.line(x+col3, table_top, x+col3, table_top - table_h); x += col3; c.line(x+col4, table_top, x+col4, table_top - table_h)
    c.line(margin, table_top - header_h, width - margin, table_top - header_h)
    time_x = margin + col1 + col2 + col3; sig_x = time_x + col4
    c.line(time_x, table_top - (header_h/2), width - margin, table_top - (header_h/2))
    c.line(time_x + col4/2, table_top - (header_h/2), time_x + col4/2, table_top - table_h); c.line(sig_x + col5/2, table_top - (header_h/2), sig_x + col5/2, table_top - table_h)
    c.setFont("Helvetica-Bold", 8); c.drawCentredString(margin + col1/2, table_top - 7*mm, "S.No."); c.drawCentredString(margin + col1 + col2/2, table_top - 7*mm, "Block No."); c.drawCentredString(margin + col1 + col2 + col3/2, table_top - 7*mm, "Name of Room Supdt.")
    c.drawCentredString(time_x + col4/2, table_top - 4*mm, "Time of Relief"); c.drawCentredString(time_x + col4/4, table_top - 10*mm, "From"); c.drawCentredString(time_x + 3*col4/4, table_top - 10*mm, "To")
    c.drawCentredString(sig_x + col5/2, table_top - 4*mm, "Signature"); c.drawCentredString(sig_x + col5/4, table_top - 10*mm, "Relieving"); c.drawCentredString(sig_x + 3*col5/4, table_top - 10*mm, "Room Supdt")
    y_row = table_top - header_h
    for i in range(num_rows):
        c.line(margin, y_row - row_h, width - margin, y_row - row_h); c.drawString(margin + 2*mm, y_row - 5*mm, str(i+1)); y_row -= row_h
    foot_y = table_top - table_h - 15*mm; c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, foot_y, "Signature of Relieving Superintendent"); c.drawRightString(width - margin, foot_y, "Signature of Chief Superintendent")

def generate_diary_pdf(college, left_logo, right_logo):
    buffer = io.BytesIO(); c = canvas.Canvas(buffer, pagesize=A4); width, height = A4
    draw_diary_form(c, height - 5*mm, width, college, left_logo, right_logo)
    c.setDash(3, 3); c.line(10*mm, height/2, width - 10*mm, height/2); c.setDash(1, 0)
    draw_diary_form(c, (height/2) - 5*mm, width, college, left_logo, right_logo)
    c.showPage(); c.save(); buffer.seek(0)
    return buffer

# ==========================================
#              STREAMLIT UI
# ==========================================
st.title("📄 AMC Exam Sheet Generator")
st.markdown("Generates: **OMR (Dropout Grey Optimized)**, **CAED**, and **Relieving Diary**.")

with st.sidebar:
    st.header("Select Format")
    sheet_type = st.radio("Format:", ["OMR Answer Sheet (Batch)", "CAED Printout Sheet", "Relieving Superintendent Diary"])
    st.divider()
    college_name = st.text_input("College", "AMC ENGINEERING COLLEGE")
    left_logo = st.file_uploader("Left Logo", type=["png", "jpg"])
    right_logo = st.file_uploader("Right Logo", type=["png", "jpg"])
    watermark = st.file_uploader("Watermark", type=["png", "jpg"]) if "OMR" in sheet_type else None

if "OMR" in sheet_type:
    st.subheader("Batch Generation Settings")
    
    exam_type = st.text_input("Exam Type", "SEMESTER END EXAMINATION")
    course_code = st.text_input("Course Code (e.g., 1BENG206)", "1BENG206")
    
    st.markdown("Upload a CSV containing the student list. Ensure it has columns named **USN** and **Name**.")
    uploaded_file = st.file_uploader("Upload Student List (CSV)", type=["csv"])
    
    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file)
            st.success(f"Loaded {len(df)} students.")
            st.dataframe(df.head())
            
            if st.button("Generate Batch OMR PDFs", type="primary"):
                pdf_out = generate_batch_omr_pdf(college_name, left_logo, right_logo, watermark, df, course_code, exam_type)
                fname = f"AMC_OMR_{course_code}_Batch_Anchored.pdf"
                st.download_button("Download Exam Batch", pdf_out, fname, "application/pdf")
        except Exception as e:
            st.error(f"Error reading CSV: {e}")
    else:
        st.info("Waiting for CSV upload. Format required: 'USN', 'Name'")

elif st.button("Generate PDF", type="primary"):
    if sheet_type == "CAED Printout Sheet":
        pdf_out = generate_caed_pdf(college_name, left_logo, right_logo)
        fname = "AMC_CAED.pdf"
    else:
        pdf_out = generate_diary_pdf(college_name, left_logo, right_logo)
        fname = "AMC_Relieving_Diary.pdf"
        
    st.success(f"{sheet_type} Generated!")
    st.download_button("Download PDF", pdf_out, fname, "application/pdf")

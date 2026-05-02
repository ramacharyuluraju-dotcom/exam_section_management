import streamlit as st
import cv2
import numpy as np
import pandas as pd
import fitz  # PyMuPDF
import io
import os

# Automatically create the dataset folder if it doesn't exist for ML Harvesting
DATASET_DIR = "omr_training_data/needs_review"
os.makedirs(DATASET_DIR, exist_ok=True)

st.title("🎯 AMC OMR Sheet Evaluator")
st.markdown("Powered by **Strict ROI Isolation & Automated Data Harvesting**.")

# ==========================================
#        COMPUTER VISION LOGIC
# ==========================================

def find_and_map_anchors(image):
    """Finds the ROI and anchors"""
    img_h, img_w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    
    thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    cnts, _ = cv2.findContours(thresh, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    
    roi_rect = None
    max_area = 0
    
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        if w > (img_w * 0.5) and h > (img_h * 0.3):
            if y > (img_h * 0.15):
                if area > max_area:
                    max_area = area
                    roi_rect = (x, y, w, h)
                    
    if roi_rect is None:
        roi_rect = (int(img_w*0.05), int(img_h*0.35), int(img_w*0.9), int(img_h*0.6))
        
    rx, ry, rw, rh = roi_rect
    
    candidates = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        area = cv2.contourArea(c)
        cx, cy = x + w//2, y + h//2
        
        if rx < cx < (rx + rw) and ry < cy < (ry + rh):
            if w > 0 and h > 0:
                aspect_ratio = w / float(h)
                extent = area / (w * h)
                if 30 < area < 8000 and 0.6 <= aspect_ratio <= 1.4 and extent > 0.82:
                    candidates.append({"pt": (cx, cy, np.sqrt(area)), "area": area})
                    
    if len(candidates) < 50:
        return None, roi_rect, thresh, gray, 0, None
        
    median_area = np.median([c["area"] for c in candidates])
    valid_candidates = [c for c in candidates if 0.5 * median_area < c["area"] < 1.5 * median_area]
    valid_candidates.sort(key=lambda c: abs(c["area"] - median_area))
    valid_candidates = valid_candidates[:50]
    
    fiducials = [c["pt"] for c in valid_candidates]
    
    if len(fiducials) != 50:
         return None, roi_rect, thresh, gray, 0, None
         
    fiducials.sort(key=lambda p: p[0]) 
    columns = []
    current_col = [fiducials[0]]
    
    for f in fiducials[1:]:
        if abs(f[0] - current_col[-1][0]) < (f[2] * 4):
            current_col.append(f)
        else:
            columns.append(current_col)
            current_col = [f]
    columns.append(current_col)
    
    if len(columns) != 3:
        return None, roi_rect, thresh, gray, 0, None
        
    question_map = {}
    q_num = 1
    avg_w_list = []
    
    for col in columns:
        col.sort(key=lambda p: p[1]) 
        for f in col:
            avg_w_list.append(f[2])
            if q_num <= 50:
                question_map[q_num] = f
                q_num += 1
                
    avg_w = np.mean(avg_w_list)

    version_anchor = None
    version_candidates = []
    
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        area = cv2.contourArea(c)
        cx, cy = x + w//2, y + h//2
        
        if cy < ry:
            if w > 0 and h > 0:
                aspect_ratio = w / float(h)
                extent = area / (w * h)
                
                if 0.5 * median_area < area < 1.5 * median_area:
                    if 0.6 <= aspect_ratio <= 1.4 and extent > 0.82:
                        version_candidates.append({"pt": (cx, cy, np.sqrt(area)), "dist_from_center": abs(cx - img_w/2)})
                        
    if version_candidates:
        version_candidates.sort(key=lambda c: c["dist_from_center"])
        version_anchor = version_candidates[0]["pt"]

    return question_map, roi_rect, thresh, gray, avg_w, version_anchor

def evaluate_image(image, multi_master_key, fill_percentage):
    """Evaluates the sheet and harvests data for Machine Learning."""
    res = find_and_map_anchors(image)
    if res[0] is None:
        roi_rect = res[1] if res is not None else None
        debug_img = image.copy()
        if roi_rect is not None:
            rx, ry, rw, rh = roi_rect
            cv2.rectangle(debug_img, (rx, ry), (rx+rw, ry+rh), (0, 255, 255), 4) # Yellow Box for ROI
        return {"USN": "Error", "Course": "Error", "Version": "N/A", "Score": 0, "Confidence": "0%", "Needs Moderation": "YES", "Status": "Failed to find 50 anchors."}, debug_img

    question_map, roi_rect, thresh, gray, anchor_width_px, version_anchor = res

    # ================== QR CODE DECODE ==================
    qr_detector = cv2.QRCodeDetector()
    qr_data, bbox, _ = qr_detector.detectAndDecode(gray)
    if not qr_data:
        h, w = gray.shape
        qr_data, bbox, _ = qr_detector.detectAndDecode(gray[:int(h*0.4), :])
        
    usn, course_code = "Unknown", "Unknown"
    if qr_data and '|' in qr_data:
        usn, course_code = qr_data.split('|')

    debug_img = image.copy()
    if roi_rect:
        rx, ry, rw, rh = roi_rect
        cv2.rectangle(debug_img, (rx, ry), (rx+rw, ry+rh), (0, 255, 255), 4) # Yellow Box for ROI
    
    # ================== HARVESTING GRADING FUNCTION ==================
    def grade_row(ax, ay, offset_mm, spacing_mm, radius_mm, options_list, is_version=False, local_ruler=1.0, q_id="Unknown"):
        offset_px = offset_mm * local_ruler
        spacing_px = spacing_mm * local_ruler
        radius_px = int(radius_mm * local_ruler)
        
        # Color coding: Purple (255,0,255) for Version Anchor, Green (0,255,0) for Question Anchors (BGR format)
        box_color = (255, 0, 255) if is_version else (0, 255, 0)
        cv2.rectangle(debug_img, (int(ax)-15, int(ay)-15), (int(ax)+15, int(ay)+15), box_color, 2)
        
        b_start_x = ax + offset_px
        bubble_area = 3.1415 * (radius_px ** 2)
        
        fills = []
        for i in range(len(options_list)):
            cx = int(b_start_x + (i * spacing_px))
            cy = int(ay)
            
            # Draw tracking rings in Blue (255,0,0) in BGR format
            cv2.circle(debug_img, (cx, cy), radius_px, (255, 0, 0), 2)
            
            mask = np.zeros(thresh.shape, dtype="uint8")
            cv2.circle(mask, (cx, cy), radius_px, 255, -1)
            pixel_count = cv2.countNonZero(cv2.bitwise_and(thresh, thresh, mask=mask))
            fill_ratio = pixel_count / bubble_area
            fills.append((fill_ratio, i))
            
        fills.sort(key=lambda x: x[0], reverse=True)
        max_fill, max_idx = fills[0]
        sec_fill, sec_idx = fills[1]
        
        is_confident = True
        ans = "Blank"
        
        if max_fill > fill_percentage:
            if sec_fill > fill_percentage:
                ans = "Multiple"
                is_confident = False 
            else:
                ans = options_list[max_idx]
                if (max_fill - sec_fill) < 0.12: is_confident = False
                if (max_fill - fill_percentage) < 0.08: is_confident = False
        else:
            ans = "Blank"
            if (fill_percentage - max_fill) < 0.08: is_confident = False
                
        # ==========================================
            # ML HARVESTING DOWNLOADER (CLOUD FIX)
            # ==========================================
            if os.path.exists(DATASET_DIR) and len(os.listdir(DATASET_DIR)) > 0:
                st.divider()
                st.markdown("### 📦 Harvested ML Training Data")
                file_count = len(os.listdir(DATASET_DIR))
                st.info(f"The system has collected **{file_count}** image crops from this batch for ML training.")
                
                # Zip the files in memory
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fname in os.listdir(DATASET_DIR):
                        fpath = os.path.join(DATASET_DIR, fname)
                        zf.write(fpath, arcname=fname)
                        
                st.download_button(
                    label="📥 Download Harvested Images (ZIP)",
                    data=zip_buffer.getvalue(),
                    file_name="harvested_omr_data.zip",
                    mime="application/zip",
                    type="primary"
                )

    # ================== EVALUATE VERSION ==================
    detected_version = "N/A"
    flags_count = 0
    needs_moderation = "NO"
    
    if version_anchor is not None:
        # Scale mapped for 3.5mm anchor and shifted 10.25 offset
        version_ruler = version_anchor[2] / 3.5
        detected_version, v_conf = grade_row(version_anchor[0], version_anchor[1], 10.25, 15.0, 3.5, ['A', 'B', 'C', 'D'], is_version=True, local_ruler=version_ruler, q_id="Version")
        if not v_conf or detected_version in ["Multiple", "Blank"]:
            flags_count += 1
            needs_moderation = "YES"

    # ================== MULTI-VERSION ROUTING ==================
    actual_score = 0
    final_status = "Evaluated Successfully"
    
    if detected_version in ['A', 'B', 'C', 'D']:
        active_key = multi_master_key.get(detected_version, {})
    else:
        active_key = multi_master_key.get('A', {})
        final_status = "Warning: Version Code Invalid."

    # ================== EVALUATE QUESTIONS ==================
    for q_num, (ax, ay, aw) in question_map.items():
        # Scale mapped for 3.5mm anchor and shifted 12.25 offset
        row_ruler = aw / 3.5
        ans, q_conf = grade_row(ax, ay, 12.25, 8.5, 3.2, ['A', 'B', 'C', 'D'], local_ruler=row_ruler, q_id=f"Q{q_num}")
        
        if not q_conf or ans in ["Multiple", "Blank"]:
            flags_count += 1
            needs_moderation = "YES"
            
        if active_key and ans == active_key.get(q_num):
            actual_score += 1

    confidence_score = max(0, 100 - (flags_count * 2))

    result_dict = {
        "USN": usn, 
        "Course": course_code, 
        "Version": detected_version,
        "Score": actual_score, 
        "Confidence": f"{confidence_score}%",
        "Needs Moderation": needs_moderation,
        "Status": final_status
    }
    return result_dict, debug_img

# ==========================================
#              STREAMLIT UI
# ==========================================

with st.sidebar:
    st.header("1. Master Key Upload")
    
    template_df = pd.DataFrame({
        "Question": range(1, 51),
        "Version_A": ["A"] * 50,
        "Version_B": ["B"] * 50,
        "Version_C": ["C"] * 50,
        "Version_D": ["D"] * 50
    })
    csv_template = template_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Download Multi-Version CSV Template",
        data=csv_template,
        file_name="AMC_Master_Key_Template.csv",
        mime="text/csv"
    )
    
    st.markdown("Upload your completed `.csv` key below.")
    uploaded_key = st.file_uploader("Upload Master Key", type=["csv"])
    
    multi_master_key_dict = {'A': {}, 'B': {}, 'C': {}, 'D': {}}
    
    if uploaded_key is not None:
        try:
            key_df = pd.read_csv(uploaded_key)
            for _, row in key_df.iterrows():
                q = int(row["Question"])
                multi_master_key_dict['A'][q] = str(row.get("Version_A", 'A')).strip().upper()
                multi_master_key_dict['B'][q] = str(row.get("Version_B", 'B')).strip().upper()
                multi_master_key_dict['C'][q] = str(row.get("Version_C", 'C')).strip().upper()
                multi_master_key_dict['D'][q] = str(row.get("Version_D", 'D')).strip().upper()
            st.success("✅ Multi-Version Key Loaded.")
        except Exception as e:
            st.error("Error reading CSV. Ensure columns are named 'Question', 'Version_A', etc.")
    else:
        st.info("ℹ️ Using default test pattern for all versions until uploaded.")
        for v in ['A', 'B', 'C', 'D']:
            multi_master_key_dict[v] = {i: ['A', 'B', 'C', 'D'][(i-1) % 4] for i in range(1, 51)}

    with st.expander("👀 View Active Keys"):
        st.json(multi_master_key_dict)

    st.divider()
    st.header("2. Ink Threshold")
    fill_percent = st.slider("Required Ink Fill (%)", min_value=10, max_value=80, value=30, step=5) / 100.0

# --- TAB LAYOUT ---
tab1, tab2 = st.tabs(["📐 Step 1: Verify Targeting Rings", "🚀 Step 2: Batch Process Scans"])

with tab1:
    st.subheader("Upload any scanned page to verify the anchor targeting.")
    calib_file = st.file_uploader("Upload Scan for Debugging", type=["jpg", "jpeg", "png", "pdf"], key="calib")
    
    if calib_file:
        if calib_file.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=calib_file.read(), filetype="pdf")
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=200)
            img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            if pix.n == 4: img_array = cv2.cvtColor(img_array, cv2.COLOR_RGBA2BGR)
            elif pix.n == 3: img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
            doc.close()
        else:
            img_array = cv2.imdecode(np.frombuffer(calib_file.read(), np.uint8), cv2.IMREAD_COLOR)

        result, debug_img = evaluate_image(img_array, multi_master_key_dict, fill_percent)
        
        if debug_img is not None:
            col1, col2 = st.columns([1, 2])
            with col1:
                st.success(f"Status: {result['Status']}")
                st.write(f"**Detected USN:** {result.get('USN', 'N/A')}")
                st.write(f"**Detected Version:** {result.get('Version', 'N/A')}")
                st.write(f"**Detected Score:** {result.get('Score', 0)}/50")
                
                conf_val = int(result['Confidence'].strip('%'))
                color = "green" if conf_val > 90 else "orange" if conf_val > 70 else "red"
                st.markdown(f"**Confidence Score:** <span style='color:{color}; font-weight:bold;'>{result['Confidence']}</span>", unsafe_allow_html=True)
                
                mod_color = "red" if result['Needs Moderation'] == "YES" else "green"
                st.markdown(f"**Needs Moderation:** <span style='color:{mod_color}; font-weight:bold;'>{result['Needs Moderation']}</span>", unsafe_allow_html=True)

                st.markdown("---")
                st.markdown("### How to read the map:")
                st.markdown("🟨 **Yellow Box:** The strictly isolated ROI for answers.")
                st.markdown("🟪 **Purple Box:** The decoupled Version Code anchor.")
                st.markdown("🟩 **Green Boxes:** The 50 main question anchors.")
                st.markdown("🟦 **Blue Rings:** The evaluator's eyes tracking the bubbles.")
            with col2:
                st.image(cv2.cvtColor(debug_img, cv2.COLOR_BGR2RGB), caption="Anchor Targeting Map", use_container_width=True)
                
            # Restored Download Button
            is_success, buffer = cv2.imencode(".png", debug_img)
            if is_success:
                st.download_button("📥 Download High-Res Map", buffer.tobytes(), "Anchor_Map_Debug.png", "image/png")

with tab2:
    st.subheader("Upload filled OMR scans.")
    batch_files = st.file_uploader("Upload Exam Scans", type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True, key="batch")

    if batch_files:
        if st.button("Evaluate Batch", type="primary"):
            results_list = []
            my_bar = st.progress(0, text="Evaluating anchored scans...")
            total_pages = 0; processed = 0
            
            for file in batch_files:
                if file.name.lower().endswith('.pdf'):
                    pdf_doc = fitz.open(stream=file.read(), filetype="pdf")
                    total_pages += len(pdf_doc)
                    pdf_doc.close(); file.seek(0)
                else: total_pages += 1
                    
            for file in batch_files:
                if file.name.lower().endswith('.pdf'):
                    pdf_document = fitz.open(stream=file.read(), filetype="pdf")
                    for page_num in range(len(pdf_document)):
                        page = pdf_document.load_page(page_num)
                        pix = page.get_pixmap(dpi=200)
                        scan_img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
                        if pix.n == 4: scan_img = cv2.cvtColor(scan_img, cv2.COLOR_RGBA2BGR)
                        elif pix.n == 3: scan_img = cv2.cvtColor(scan_img, cv2.COLOR_RGB2BGR)
                            
                        result, _ = evaluate_image(scan_img, multi_master_key_dict, fill_percent)
                        result["File Name"] = f"{file.name} (Page {page_num + 1})"
                        results_list.append(result)
                        
                        processed += 1
                        my_bar.progress(processed / total_pages, text=f"Processed page {page_num + 1}")
                    pdf_document.close()
                else:
                    scan_img = cv2.imdecode(np.frombuffer(file.read(), np.uint8), cv2.IMREAD_COLOR)
                    result, _ = evaluate_image(scan_img, multi_master_key_dict, fill_percent)
                    result["File Name"] = file.name
                    results_list.append(result)
                    
                    processed += 1
                    my_bar.progress(processed / total_pages, text=f"Processed {file.name}")
                
            my_bar.empty() 
            st.success(f"Successfully processed {processed} total sheets! Look in the 'omr_training_data/needs_review' folder on your PC to see harvested crops.")
            
            results_df = pd.DataFrame(results_list)[["USN", "Course", "Version", "Score", "Confidence", "Needs Moderation", "Status", "File Name"]]
            
            def highlight_moderation(val):
                color = 'red' if val == 'YES' else ''
                return f'color: {color}'
                
            st.dataframe(results_df.style.map(highlight_moderation, subset=['Needs Moderation']), use_container_width=True)
            
            csv = results_df.to_csv(index=False).encode('utf-8')
            st.download_button("Download Final Report (CSV)", csv, "AMC_Evaluation_Report.csv", "text/csv")

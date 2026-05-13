import streamlit as st
import cv2
import numpy as np
import pandas as pd
import fitz  # PyMuPDF
import io
import os
import itertools
import zipfile

# Automatically create the dataset folder if it doesn't exist for ML Harvesting
DATASET_DIR = "omr_training_data/needs_review"
os.makedirs(DATASET_DIR, exist_ok=True)

st.set_page_config(page_title="AMC OMR Evaluator (With ERP Export)", layout="wide")

st.title("🎯 AMC OMR Sheet Evaluator")
st.markdown("Powered by **Perfect-Rectangle Homography, PyZbar & Global Scaling**.")

# ==========================================
#   DYNAMIC GRID CONFIGURATIONS (10px = 1mm)
# ==========================================
CONFIG_50Q = {
    'warped_w': 1450,       
    'warped_h': 1380,       
    'cols': 3,
    'rows': 17,
    'col_w': 1500 / 3.0,    
    'start_x': 140,         
    'start_y': 33,          
    'b_spacing': 75,        
    'row_h': 75,            
    'group_gap': 25,        
    'b_radius': 30,         
    'total_q': 50
}

CONFIG_100Q = {
    'warped_w': 1850,       
    'warped_h': 1680,       
    'cols': 4,
    'rows': 25,
    'col_w': 1900 / 4.0,    
    'start_x': 140,         
    'start_y': 33,          
    'b_spacing': 68,        
    'row_h': 62,            
    'group_gap': 25,        
    'b_radius': 29,         
    'total_q': 100
}

# ==========================================
#        COMPUTER VISION LOGIC
# ==========================================

def find_anchors_and_warp(image, config):
    img_h, img_w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    
    # Robust contour checking across OpenCV versions
    cnts_res = cv2.findContours(thresh, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cnts = cnts_res[0] if len(cnts_res) == 2 else cnts_res[1]
    
    candidates = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        if w == 0 or h == 0: continue
        aspect_ratio = w / float(h)
        extent = cv2.contourArea(c) / area if area > 0 else 0
        
        if 50 < area < 5000 and 0.60 <= aspect_ratio <= 1.45 and extent > 0.85:
            candidates.append({"pt": (x + w//2, y + h//2), "area": area, "x": x + w//2, "y": y + h//2, "w": w})
            
    if len(candidates) < 5:
        return None, thresh, gray, None, None, None
        
    candidates.sort(key=lambda c: c["area"], reverse=True)
    top_candidates = candidates[:20] 
    
    min_error = float('inf')
    best_corners = None
    
    for combo in itertools.combinations(top_candidates, 4):
        cx = np.mean([c['x'] for c in combo])
        cy = np.mean([c['y'] for c in combo])
        
        try:
            tl = [c for c in combo if c['x'] < cx and c['y'] < cy][0]
            tr = [c for c in combo if c['x'] > cx and c['y'] < cy][0]
            bl = [c for c in combo if c['x'] < cx and c['y'] > cy][0]
            br = [c for c in combo if c['x'] > cx and c['y'] > cy][0]
        except IndexError:
            continue
            
        w = (tr['x'] - tl['x'] + br['x'] - bl['x']) / 2.0
        h = (bl['y'] - tl['y'] + br['y'] - tr['y']) / 2.0
        
        if w < 100 or h < 100:
            continue
            
        dx_left = abs(tl['x'] - bl['x'])
        dx_right = abs(tr['x'] - br['x'])
        dy_top = abs(tl['y'] - tr['y'])
        dy_bottom = abs(bl['y'] - br['y'])
        
        error = (dx_left + dx_right) / w + (dy_top + dy_bottom) / h
        
        if error < min_error:
            min_error = error
            best_corners = [tl, tr, br, bl] 
            
    if not best_corners:
        return None, thresh, gray, None, None, None
        
    grid_top_y = min(best_corners[0]['y'], best_corners[1]['y'])
    grid_center_x = (best_corners[0]['x'] + best_corners[1]['x']) / 2.0
    
    valid_versions = [c for c in top_candidates if c not in best_corners and c['y'] < grid_top_y and c['x'] < grid_center_x]
    version_anchor = max(valid_versions, key=lambda c: c['area']) if valid_versions else None

    src_pts = np.array([c['pt'] for c in best_corners], dtype="float32")
    dst_pts = np.array([
        [0, 0],
        [config['warped_w'], 0],
        [config['warped_w'], config['warped_h']],
        [0, config['warped_h']]
    ], dtype="float32")
    
    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped_thresh = cv2.warpPerspective(thresh, M, (config['warped_w'], config['warped_h']))
    warped_color = cv2.warpPerspective(image, M, (config['warped_w'], config['warped_h']))
    
    return best_corners, thresh, gray, version_anchor, warped_thresh, warped_color

def evaluate_image(image, multi_master_key, fill_percentage, config):
    flagged_log = []
    
    res = find_anchors_and_warp(image, config)
    if res[0] is None:
        return {"USN": "Error", "Course": "Error", "Version": "N/A", "Score": 0, "Confidence": "0%", "Needs Moderation": "YES", "Flagged Questions": "Failed to map 4 perfect corners", "Status": "Failed to map 4 perfect corners."}, image.copy(), None

    corners, thresh, gray, version_anchor, warped_thresh, warped_color = res

    # ================== QR CODE DECODE ==================
    qr_data = None
    h, w = gray.shape
    
    top_right_gray = gray[0:int(h*0.35), int(w*0.5):w]
    tr_large = cv2.resize(top_right_gray, (0,0), fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    tr_thresh = cv2.threshold(tr_large, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]

    try:
        from pyzbar.pyzbar import decode
        decoded = decode(tr_large)
        if decoded: qr_data = decoded[0].data.decode('utf-8')
        if not qr_data:
            decoded = decode(tr_thresh)
            if decoded: qr_data = decoded[0].data.decode('utf-8')
    except ImportError:
        pass 

    if not qr_data:
        qr_detector = cv2.QRCodeDetector()
        qr_data, _, _ = qr_detector.detectAndDecode(tr_large)
        if not qr_data: qr_data, _, _ = qr_detector.detectAndDecode(tr_thresh)
        if not qr_data: qr_data, _, _ = qr_detector.detectAndDecode(gray) 

    usn, course_code = "Unknown", "Unknown"
    if qr_data and '|' in qr_data:
        usn, course_code = qr_data.split('|')

    debug_original = image.copy()
    for c in corners:
        cv2.circle(debug_original, (int(c['x']), int(c['y'])), 20, (0, 255, 255), 4)
    if version_anchor:
        cv2.rectangle(debug_original, (int(version_anchor['x'])-15, int(version_anchor['y'])-15), 
                      (int(version_anchor['x'])+15, int(version_anchor['y'])+15), (255, 0, 255), 4)

    # ================== EVALUATE VERSION CODE ==================
    detected_version = "N/A"
    flags_count = 0
    needs_moderation = "NO"
    
    if version_anchor is not None:
        tl, tr = corners[0], corners[1]
        dist_px = np.sqrt((tr['x'] - tl['x'])**2 + (tr['y'] - tl['y'])**2)
        global_scale = dist_px / (config['warped_w'] / 10.0) 
        
        vx, vy = version_anchor['x'], version_anchor['y']
        b_start_x = vx + (68 * global_scale) 
        b_spacing = 11 * global_scale
        b_rad = int(3.2 * global_scale)      
        b_area = 3.1415 * (b_rad ** 2)
        
        v_fills = []
        for i, opt in enumerate(['A', 'B', 'C', 'D']):
            cx = int(b_start_x + (i * b_spacing))
            cy = int(vy) 
            cv2.circle(debug_original, (cx, cy), b_rad, (255, 0, 0), 2)
            
            mask = np.zeros(thresh.shape, dtype="uint8")
            cv2.circle(mask, (cx, cy), b_rad, 255, -1)
            px_count = cv2.countNonZero(cv2.bitwise_and(thresh, thresh, mask=mask))
            v_fills.append((px_count / b_area, i))
            
        v_fills.sort(key=lambda x: x[0], reverse=True)
        if v_fills[0][0] > fill_percentage:
            detected_version = ['A', 'B', 'C', 'D'][v_fills[0][1]]
        else:
            detected_version = "Blank"
            flags_count += 1
            needs_moderation = "YES"
            flagged_log.append("Version Code")

    # ================== MULTI-VERSION ROUTING ==================
    actual_score = 0
    final_status = "Evaluated Successfully"
    
    if detected_version in ['A', 'B', 'C', 'D']:
        active_key = multi_master_key.get(detected_version, {})
    else:
        active_key = multi_master_key.get('A', {})
        final_status = "Warning: Version Code Invalid."

    # ================== EVALUATE QUESTIONS ==================
    q_current = 1
    bubble_area = 3.1415 * (config['b_radius'] ** 2)
    
    for col in range(config['cols']):
        curr_y = config['start_y']
        for row in range(config['rows']):
            if q_current > config['total_q']:
                break
                
            if row > 0 and row % 5 == 0:
                curr_y += config['group_gap']
                
            b_start_x = config['start_x'] + (col * config['col_w'])
            
            fills = []
            for i in range(4):
                bx = int(b_start_x + (i * config['b_spacing']))
                by = int(curr_y)
                
                cv2.circle(warped_color, (bx, by), config['b_radius'], (255, 0, 0), 2)
                
                mask = np.zeros(warped_thresh.shape, dtype="uint8")
                cv2.circle(mask, (bx, by), config['b_radius'], 255, -1)
                pixel_count = cv2.countNonZero(cv2.bitwise_and(warped_thresh, warped_thresh, mask=mask))
                fill_ratio = pixel_count / bubble_area
                fills.append((fill_ratio, i))
                
            fills.sort(key=lambda x: x[0], reverse=True)
            max_fill = fills[0][0]
            sec_fill = fills[1][0]
            
            ans = "Blank"
            is_confident = True
            
            if max_fill > fill_percentage:
                if sec_fill > fill_percentage:
                    ans = "Multiple"
                    is_confident = False 
                else:
                    ans = ['A', 'B', 'C', 'D'][fills[0][1]]
            else:
                ans = "Blank"
                is_confident = False
                
            if not is_confident or ans in ["Multiple", "Blank"]:
                flags_count += 1
                needs_moderation = "YES"
                
                if ans == "Multiple": flagged_log.append(f"Q{q_current} (Multiple)")
                else: flagged_log.append(f"Q{q_current} (Blank/Light)")

                y1 = max(0, int(curr_y - config['b_radius'] * 2.5))
                y2 = min(warped_color.shape[0], int(curr_y + config['b_radius'] * 2.5))
                x1 = max(0, int(b_start_x - config['b_radius'] * 2))
                x2 = min(warped_color.shape[1], int(b_start_x + (4 * config['b_spacing']) + config['b_radius']))
                
                crop_img = warped_color[y1:y2, x1:x2] 
                if crop_img.size > 0:
                    filename = os.path.join(DATASET_DIR, f"{usn}_Q{q_current}_guess_{ans}.jpg")
                    cv2.imwrite(filename, crop_img)

            if active_key and ans == active_key.get(q_current):
                actual_score += 1
                
            curr_y += config['row_h']
            q_current += 1

    confidence_score = max(0, 100 - (flags_count * 2))

    result_dict = {
        "usn": usn, 
        "course_code": course_code,
        "see_marks": actual_score,  # Renamed for ERP matching
        "Version": detected_version,
        "Confidence": f"{confidence_score}%",
        "Needs Moderation": needs_moderation,
        "Flagged Questions": ", ".join(flagged_log) if flagged_log else "None",
        "Status": final_status
    }
    return result_dict, debug_original, warped_color

# ==========================================
#              STREAMLIT UI
# ==========================================

with st.sidebar:
    st.header("1. Sheet Configuration")
    sheet_format = st.selectbox("Exam Format:", ["50 Questions", "100 Questions"])
    active_config = CONFIG_50Q if sheet_format == "50 Questions" else CONFIG_100Q
    
    st.divider()
    st.header("2. ERP Sync Data")
    target_cycle_id = st.number_input("Target Exam Cycle ID (for Bulk Upload)", min_value=1, value=1, help="Appends this to the output CSV so it can be uploaded directly into the main ERP.")
    
    st.divider()
    st.header("3. Master Key Upload")
    template_df = pd.DataFrame({
        "Question": range(1, active_config['total_q'] + 1),
        "Version_A": ["A"] * active_config['total_q'],
        "Version_B": ["B"] * active_config['total_q'],
        "Version_C": ["C"] * active_config['total_q'],
        "Version_D": ["D"] * active_config['total_q']
    })
    st.download_button("📥 Multi-Version CSV Template", template_df.to_csv(index=False).encode('utf-8'), f"AMC_Master_Key_{active_config['total_q']}Q.csv", "text/csv")
    
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
            st.error("Error reading CSV.")
    else:
        st.info("ℹ️ Using default test pattern for all versions until uploaded.")
        for v in ['A', 'B', 'C', 'D']:
            multi_master_key_dict[v] = {i: ['A', 'B', 'C', 'D'][(i-1) % 4] for i in range(1, active_config['total_q'] + 1)}

    st.divider()
    st.header("4. Ink Threshold")
    fill_percent = st.slider("Required Ink Fill (%)", min_value=10, max_value=80, value=30, step=5) / 100.0

# --- TAB LAYOUT ---
tab1, tab2 = st.tabs(["📐 Step 1: Verify Homography Grid", "🚀 Step 2: Batch Process Scans"])

with tab1:
    st.subheader(f"Upload any {sheet_format} scan to verify perspective transformation.")
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

        result, debug_original, warped_color = evaluate_image(img_array, multi_master_key_dict, fill_percent, active_config)
        
        if debug_original is not None:
            st.success(f"Status: {result['Status']}")
            col_res, col_orig, col_warp = st.columns([1, 1.5, 1.5])
            
            with col_res:
                st.write(f"**USN:** {result.get('usn', 'N/A')}")
                st.write(f"**Version:** {result.get('Version', 'N/A')}")
                st.write(f"**Score:** {result.get('see_marks', 0)}/{active_config['total_q']}")
                
                conf_val = int(result['Confidence'].strip('%'))
                color = "green" if conf_val > 90 else "orange" if conf_val > 70 else "red"
                st.markdown(f"**Confidence:** <span style='color:{color}; font-weight:bold;'>{result['Confidence']}</span>", unsafe_allow_html=True)
                
                mod_color = "red" if result['Needs Moderation'] == "YES" else "green"
                st.markdown(f"**Needs Moderation:** <span style='color:{mod_color}; font-weight:bold;'>{result['Needs Moderation']}</span>", unsafe_allow_html=True)
                
                if result.get('Flagged Questions', "None") != "None":
                    st.markdown(f"**Flagged Items to Check:** <span style='color:red;'>{result['Flagged Questions']}</span>", unsafe_allow_html=True)
                
                st.divider()
                st.markdown("### Debug Exports")
                is_success, orig_buffer = cv2.imencode(".png", debug_original)
                if is_success: st.download_button("📥 Original Corners Map", orig_buffer.tobytes(), "Anchor_Map_Original.png", "image/png")
                    
            with col_orig:
                st.markdown("**1. Original Scan (Corner Lock)**")
                st.image(cv2.cvtColor(debug_original, cv2.COLOR_BGR2RGB), use_container_width=True)
                
            with col_warp:
                if warped_color is not None:
                    st.markdown("**2. Warped Image (Virtual Grid)**")
                    st.image(cv2.cvtColor(warped_color, cv2.COLOR_BGR2RGB), use_container_width=True)

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
                            
                        result, _, _ = evaluate_image(scan_img, multi_master_key_dict, fill_percent, active_config)
                        result["File Name"] = f"{file.name} (Page {page_num + 1})"
                        results_list.append(result)
                        
                        processed += 1
                        my_bar.progress(processed / total_pages, text=f"Processed page {page_num + 1}")
                    pdf_document.close()
                else:
                    scan_img = cv2.imdecode(np.frombuffer(file.read(), np.uint8), cv2.IMREAD_COLOR)
                    result, _, _ = evaluate_image(scan_img, multi_master_key_dict, fill_percent, active_config)
                    result["File Name"] = file.name
                    results_list.append(result)
                    
                    processed += 1
                    my_bar.progress(processed / total_pages, text=f"Processed {file.name}")
                
            my_bar.empty() 
            st.success(f"Successfully processed {processed} sheets!")
            
            # Map for ERP integration
            results_df = pd.DataFrame(results_list)
            results_df["cycle_id"] = target_cycle_id
            results_df["status"] = "PRESENT" 
            
            export_cols = ["cycle_id", "usn", "course_code", "see_marks", "status", "Version", "Confidence", "Needs Moderation", "Flagged Questions", "File Name"]
            results_df = results_df[export_cols]
            
            def highlight_moderation(val):
                return 'color: red' if val == 'YES' else ''
                
            st.dataframe(results_df.style.map(highlight_moderation, subset=['Needs Moderation']), use_container_width=True)
            
            col_csv, col_zip = st.columns(2)
            with col_csv:
                csv = results_df.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download Final Report (CSV for ERP Upload)", csv, "AMC_Evaluation_Report.csv", "text/csv", type="primary")
                
            # Allow downloading the harvested ML images
            with col_zip:
                if os.path.exists(DATASET_DIR) and len(os.listdir(DATASET_DIR)) > 0:
                    zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                        for fname in os.listdir(DATASET_DIR):
                            fpath = os.path.join(DATASET_DIR, fname)
                            zf.write(fpath, fname)
                    st.download_button("🗂️ Download Flagged Questions (ZIP for Manual Review)", zip_buf.getvalue(), "Flagged_OMR_Review.zip", "application/zip")

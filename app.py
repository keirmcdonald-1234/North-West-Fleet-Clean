import streamlit as st
import cv2
import numpy as np
import pytesseract
from PIL import Image
import re
from typing import List
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import io

# Configure page
st.set_page_config(
    page_title="License Plate Recognition",
    page_icon="🚗",
    layout="wide"
)

# Title and description
st.title("🚗 License Plate Recognition App")
st.markdown("Upload car images, group them with headers, and export all results to one Excel file!")

# Initialize session state for storing results
if 'all_groups' not in st.session_state:
    st.session_state.all_groups = []

def preprocess_image_for_plates(image: np.ndarray) -> np.ndarray:
    """Preprocess image to enhance license plate detection"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    filtered = cv2.bilateralFilter(gray, 11, 17, 17)
    edges = cv2.Canny(filtered, 30, 200)
    return edges, gray

def find_license_plate_contours(edges: np.ndarray) -> List:
    """Find potential license plate contours"""
    contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:30]
    
    license_plate_contours = []
    
    for contour in contours:
        epsilon = 0.018 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        
        if len(approx) == 4:
            x, y, w, h = cv2.boundingRect(approx)
            aspect_ratio = w / h
            area = cv2.contourArea(contour)
            
            if 2.0 <= aspect_ratio <= 5.0 and area > 1000:
                license_plate_contours.append(approx)
    
    return license_plate_contours

def extract_text_from_region(image: np.ndarray, contour) -> str:
    """Extract text from a specific region of the image"""
    x, y, w, h = cv2.boundingRect(contour)
    roi = image[y:y+h, x:x+w]
    roi = cv2.resize(roi, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, roi = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = np.ones((1, 1), np.uint8)
    roi = cv2.morphologyEx(roi, cv2.MORPH_CLOSE, kernel)
    roi = cv2.morphologyEx(roi, cv2.MORPH_OPEN, kernel)
    
    custom_config = r'--oem 3 --psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    text = pytesseract.image_to_string(roi, config=custom_config)
    
    return text.strip()

def clean_license_plate_text(text: str) -> str:
    """Clean and validate extracted license plate text"""
    cleaned = re.sub(r'\s+', '', text.upper())
    cleaned = re.sub(r'[^A-Z0-9]', '', cleaned)
    
    if 3 <= len(cleaned) <= 8:
        return cleaned
    
    return ""

def process_single_image(image: np.ndarray) -> List[str]:
    """Process a single image and return found license plates"""
    license_plates = []
    
    edges, gray = preprocess_image_for_plates(image)
    plate_contours = find_license_plate_contours(edges)
    
    for contour in plate_contours:
        text = extract_text_from_region(gray, contour)
        cleaned_text = clean_license_plate_text(text)
        
        if cleaned_text and cleaned_text not in license_plates:
            license_plates.append(cleaned_text)
    
    if not license_plates:
        custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        full_text = pytesseract.image_to_string(gray, config=custom_config)
        words = full_text.split()
        for word in words:
            cleaned_word = clean_license_plate_text(word)
            if cleaned_word and cleaned_word not in license_plates:
                license_plates.append(cleaned_word)
    
    return license_plates

def create_excel_file(all_groups: list, filename: str) -> bytes:
    """Create an Excel spreadsheet with all grouped results in side-by-side columns"""
    wb = Workbook()
    ws = wb.active
    ws.title = "License Plates"
    
    # Define styles
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)
    plate_font = Font(name="Courier New", bold=True, size=11)
    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Add title
    ws['A1'] = "License Plate Recognition Results"
    ws['A1'].font = Font(bold=True, size=14, color="1F4E78")
    
    # Find max number of plates to determine rows needed
    max_plates = max((len(group['plates']) for group in all_groups), default=0)
    
    # Add each group in columns A, C, E, G, etc. (with spacing columns B, D, F, H)
    for group_idx, group in enumerate(all_groups):
        # Calculate column position: A=1, C=3, E=5, G=7, etc.
        col = (group_idx * 2) + 1
        
        group_name = group['name']
        plates = group['plates']
        
        # Add group header
        header_cell = ws.cell(row=3, column=col)
        header_cell.value = group_name
        header_cell.font = header_font
        header_cell.fill = header_fill
        header_cell.border = border
        header_cell.alignment = Alignment(horizontal="left", vertical="center")
        
        # Add plates
        for plate_idx, plate in enumerate(plates):
            plate_row = 4 + plate_idx
            plate_cell = ws.cell(row=plate_row, column=col)
            plate_cell.value = plate
            plate_cell.font = plate_font
            plate_cell.border = border
            plate_cell.alignment = Alignment(horizontal="left", vertical="center")
    
    # Set column widths - data columns wider, spacing columns narrow
    for col_idx in range(1, len(all_groups) * 2 + 1):
        if col_idx % 2 == 1:  # Data columns (A, C, E, G...)
            ws.column_dimensions[chr(64 + col_idx)].width = 30
        else:  # Spacing columns (B, D, F, H...)
            ws.column_dimensions[chr(64 + col_idx)].width = 2
    
    # Save to bytes
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()

def main():
    # Section for adding new upload group
    st.header("Add Photo Group")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        group_header = st.text_input(
            "Group Header/Name:",
            placeholder="e.g., 'Parking Lot A', 'Monday Cars', 'Lot 1'",
            help="This will appear as the header for this group in the Excel file"
        )
    
    with col2:
        st.write("")  # Spacing
        st.write("")
    
    uploaded_files = st.file_uploader(
        "Upload car images for this group",
        type=['png', 'jpg', 'jpeg'],
        accept_multiple_files=True,
        help="Upload one or more images containing cars with visible license plates"
    )
    
    # Process and add group
    if uploaded_files and group_header:
        if st.button("✅ Process & Add to List", use_container_width=True):
            with st.spinner("Processing images..."):
                all_plates = []
                
                # Process each image
                for uploaded_file in uploaded_files:
                    image = Image.open(uploaded_file)
                    image_np = np.array(image)
                    
                    if len(image_np.shape) == 3:
                        image_cv = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)
                    else:
                        image_cv = image_np
                    
                    plates = process_single_image(image_cv)
                    all_plates.extend(plates)
                
                # Remove duplicates
                unique_plates = list(dict.fromkeys(all_plates))
                
                # Add to session state
                st.session_state.all_groups.append({
                    'name': group_header,
                    'plates': unique_plates,
                    'image_count': len(uploaded_files)
                })
                
                st.success(f"✅ Added '{group_header}' with {len(unique_plates)} license plate(s)")
    
    elif uploaded_files and not group_header:
        st.warning("⚠️ Please enter a group header/name before processing")
    
    # Display all accumulated groups
    if st.session_state.all_groups:
        st.divider()
        st.header("📋 All Groups")
        
        # Show each group
        for idx, group in enumerate(st.session_state.all_groups):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.subheader(f"📌 {group['name']}")
                st.write(f"**Plates found:** {len(group['plates'])} | **Images processed:** {group['image_count']}")
                
                # Display plates
                for plate in group['plates']:
                    st.code(plate, language=None)
            
            with col2:
                st.write("")  # Spacing
                if st.button("❌ Remove", key=f"remove_{idx}", use_container_width=True):
                    st.session_state.all_groups.pop(idx)
                    st.rerun()
        
        st.divider()
        
        # Export section
        st.header("📊 Export to Excel")
        
        filename = st.text_input(
            "Excel filename:",
            value="license_plates",
            help="The file will be saved as .xlsx"
        )
        
        # Calculate totals
        total_groups = len(st.session_state.all_groups)
        total_plates = sum(len(group['plates']) for group in st.session_state.all_groups)
        
        st.info(f"📊 Ready to export: **{total_groups}** groups with **{total_plates}** unique license plates total")
        
        # Create Excel file
        excel_data = create_excel_file(st.session_state.all_groups, filename)
        excel_filename = f"{filename}.xlsx" if filename else "license_plates.xlsx"
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.download_button(
                label="📥 Download Excel File",
                data=excel_data,
                file_name=excel_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        
        with col2:
            if st.button("🗑️ Clear All Groups", use_container_width=True):
                st.session_state.all_groups = []
                st.rerun()

# Sidebar with information
st.sidebar.title("ℹ️ How to Use")
st.sidebar.markdown("""
1. **Enter Group Name**: Give this batch of photos a header (e.g., "Parking Lot A")
2. **Upload Photos**: Select multiple car images
3. **Process**: Click "Process & Add to List"
4. **Repeat**: Add more groups as needed
5. **Export**: Download all groups in one Excel file

**Tips for Best Results:**
- Use clear, high-resolution images
- Ensure license plates are visible
- Avoid blurry or heavily angled photos
- Each group will have its own header in Excel

**Example Workflow:**
- Add "Monday - Lot A" photos → Process
- Add "Monday - Lot B" photos → Process  
- Add "Tuesday - Lot A" photos → Process
- Download one Excel file with all three groups!
""")

if __name__ == "__main__":
    try:
        pytesseract.get_tesseract_version()
    except:
        st.error("Tesseract OCR is not installed. Please install it to use this app.")
        st.stop()
    
    main()
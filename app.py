
import streamlit as st
import boto3
from PIL import Image
import re
from typing import List
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import io
from botocore.exceptions import NoCredentialsError, ClientError

st.set_page_config(page_title="License Plate Recognition", page_icon="🚗", layout="wide")

st.title("🚗 License Plate Recognition App")
st.markdown("Upload car images, group them with headers, and export all results to one Excel file!")

if 'all_groups' not in st.session_state:
    st.session_state.all_groups = []

@st.cache_resource
def get_rekognition_client():
    try:
        return boto3.client(
            'rekognition',
            region_name='us-east-1',
            aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"]
        )
    except KeyError:
        st.error("AWS credentials not configured. See sidebar for setup instructions.")
        st.stop()
    except NoCredentialsError:
        st.error("AWS credentials are invalid or missing.")
        st.stop()

def clean_license_plate_text(text: str) -> str:
    cleaned = re.sub(r'\s+', '', text.upper())
    cleaned = re.sub(r'[^A-Z0-9]', '', cleaned)
    
    if len(cleaned) == 7:
        # UK format: 2 letters + 2 digits + 3 letters
        # Correct common OCR mistakes
        first_two = cleaned[0:2]
        middle_two = cleaned[2:4]
        last_three = cleaned[4:7]
        
        # Fix 0/O and 5/S confusion in letter positions
        first_two = first_two.replace('0', 'O').replace('5', 'S')
        last_three = last_three.replace('0', 'O').replace('5', 'S')
        
        corrected = first_two + middle_two + last_three
        
        if corrected[0:2].isalpha() and corrected[2:4].isdigit() and corrected[4:7].isalpha():
            return corrected
    
    return ""

def detect_plates_in_image(image_bytes: bytes) -> List[str]:
    try:
        client = get_rekognition_client()
        response = client.detect_text(Image={'Bytes': image_bytes})
        
        license_plates = []
        
        for detection in response['TextDetections']:
            if detection['Type'] == 'LINE':
                text = detection['DetectedText']
                confidence = detection['Confidence']
                
                if confidence > 50:
                    cleaned_text = clean_license_plate_text(text)
                    if cleaned_text and cleaned_text not in license_plates:
                        license_plates.append(cleaned_text)
        
        return license_plates
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'AccessDeniedException':
            st.error("AWS credentials are invalid or lack Rekognition permissions.")
        else:
            st.error(f"AWS Error: {e}")
        return []

def create_excel_file(all_groups: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "License Plates"
    
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)
    plate_font = Font(name="Courier New", bold=True, size=11)
    border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
    
    ws['A1'] = "License Plate Recognition Results"
    ws['A1'].font = Font(bold=True, size=14, color="1F4E78")
    
    for group_idx, group in enumerate(all_groups):
        col = (group_idx * 2) + 1
        group_name = group['name']
        plates = group['plates']
        
        header_cell = ws.cell(row=3, column=col)
        header_cell.value = group_name
        header_cell.font = header_font
        header_cell.fill = header_fill
        header_cell.border = border
        header_cell.alignment = Alignment(horizontal="left", vertical="center")
        
        for plate_idx, plate in enumerate(plates):
            plate_row = 4 + plate_idx
            plate_cell = ws.cell(row=plate_row, column=col)
            plate_cell.value = plate
            plate_cell.font = plate_font
            plate_cell.border = border
            plate_cell.alignment = Alignment(horizontal="left", vertical="center")
    
    for col_idx in range(1, len(all_groups) * 2 + 1):
        if col_idx % 2 == 1:
            ws.column_dimensions[chr(64 + col_idx)].width = 30
        else:
            ws.column_dimensions[chr(64 + col_idx)].width = 2
    
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()

st.header("Add Photo Group")

col1, col2 = st.columns([2, 1])

with col1:
    group_header = st.text_input(
        "Group Header/Name:",
        placeholder="e.g., 'Parking Lot A', 'Monday Cars', 'Lot 1'",
        help="This will appear as the header for this group in the Excel file"
    )

uploaded_files = st.file_uploader(
    "Upload car images for this group",
    type=['png', 'jpg', 'jpeg'],
    accept_multiple_files=True,
    help="Upload one or more images containing cars with visible license plates"
)

if uploaded_files and group_header:
    if st.button("✅ Process & Add to List", use_container_width=True):
        with st.spinner("Processing images with AWS Rekognition..."):
            all_plates = []
            processed_count = 0
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for idx, uploaded_file in enumerate(uploaded_files):
                status_text.text(f"Processing image {idx + 1} of {len(uploaded_files)}...")
                
                try:
                    image_bytes = uploaded_file.read()
                    plates = detect_plates_in_image(image_bytes)
                    all_plates.extend(plates)
                    processed_count += 1
                    
                except Exception as e:
                    st.warning(f"Error processing {uploaded_file.name}: {str(e)}")
                
                progress = (idx + 1) / len(uploaded_files)
                progress_bar.progress(progress)
            
            unique_plates = list(dict.fromkeys(all_plates))
            
            progress_bar.empty()
            status_text.empty()
            
            st.session_state.all_groups.append({
                'name': group_header,
                'plates': unique_plates,
                'image_count': processed_count
            })
            
            st.success(f"Added '{group_header}' with {len(unique_plates)} license plate(s) from {processed_count} images")

elif uploaded_files and not group_header:
    st.warning("Please enter a group header/name before processing")

if st.session_state.all_groups:
    st.divider()
    st.header("📋 All Groups")
    
    for idx, group in enumerate(st.session_state.all_groups):
        col1, col2 = st.columns([3, 1])
        
        with col1:
            st.subheader(f"📌 {group['name']}")
            st.write(f"**Plates found:** {len(group['plates'])} | **Images processed:** {group['image_count']}")
            
            for plate in group['plates']:
                st.code(plate, language=None)
        
        with col2:
            st.write("")
            if st.button("❌ Remove", key=f"remove_{idx}", use_container_width=True):
                st.session_state.all_groups.pop(idx)
                st.rerun()
    
    st.divider()
    
    st.header("📊 Export to Excel")
    
    filename = st.text_input(
        "Excel filename:",
        value="license_plates",
        help="The file will be saved as .xlsx"
    )
    
    total_groups = len(st.session_state.all_groups)
    total_plates = sum(len(group['plates']) for group in st.session_state.all_groups)
    
    st.info(f"Ready to export: **{total_groups}** groups with **{total_plates}** unique license plates total")
    
    excel_data = create_excel_file(st.session_state.all_groups)
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

st.sidebar.title("ℹ️ Setup Instructions")
st.sidebar.markdown("""
## AWS Configuration Required

### Step 1: Get AWS Credentials
1. Go to [AWS Console](https://console.aws.amazon.com)
2. Click your name (top right) → **Security Credentials**
3. Create an **Access Key**
4. Copy both keys

### Step 2: Add to Streamlit Cloud
1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Click your app → **Settings**
3. Go to **Secrets**
4. Paste this:
```
AWS_ACCESS_KEY_ID = "your-access-key-id"
AWS_SECRET_ACCESS_KEY = "your-secret-access-key"
```

### Step 3: Restart App
Click "Rerun" - it should work!

## How to Use
1. Enter group name
2. Upload photos
3. Click "Process & Add to List"
4. Repeat for more groups
5. Download Excel file
""")

import streamlit as st
import boto3
from PIL import Image
import re
from typing import List
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import io
from botocore.exceptions import NoCredentialsError, ClientError

st.set_page_config(page_title="Number Plate Recognition", page_icon="🚗", layout="wide")

st.title("🚗 Number Plate Recognition App")
st.markdown("Upload car images, group them with site names, and export all results to one Excel file!")

if 'all_groups' not in st.session_state:
    st.session_state.all_groups = []

if 'clear_uploader' not in st.session_state:
    st.session_state.clear_uploader = False

if 'failed_images' not in st.session_state:
    st.session_state.failed_images = []

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
        st.error("AWS credentials not configured.")
        st.stop()
    except NoCredentialsError:
        st.error("AWS credentials are invalid or missing.")
        st.stop()

def compress_image(image_bytes: bytes) -> bytes:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = rgb_img
        
        img.thumbnail((1500, 1500), Image.LANCZOS)
        
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=80, optimize=True)
        output.seek(0)
        return output.getvalue()
    except Exception as e:
        return image_bytes

def clean_license_plate_text(text: str) -> str:
    cleaned = re.sub(r'\s+', '', text.upper())
    cleaned = re.sub(r'[^A-Z0-9]', '', cleaned)
    
    if len(cleaned) == 7:
        first_two = cleaned[0:2]
        middle_two = cleaned[2:4]
        last_three = cleaned[4:7]
        
        first_two = first_two.replace('0', 'O').replace('5', 'S').replace('1', 'I')
        last_three = last_three.replace('0', 'O').replace('5', 'S').replace('1', 'I')
        
        middle_two = middle_two.replace('O', '0').replace('I', '1').replace('S', '5')
        
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
                
                if confidence > 40:
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
    
    ws['A1'] = "Number Plate Recognition Results"
    ws['A1'].font = Font(bold=True, size=14, color="1F4E78")
    
    display_groups = []
    for group in all_groups:
        plates = group['plates']
        if len(plates) > 50:
            for chunk_idx in range(0, len(plates), 50):
                chunk = plates[chunk_idx:chunk_idx + 50]
                chunk_num = (chunk_idx // 50) + 1
                display_name = f"{group['name']} ({chunk_num})" if chunk_num > 1 else group['name']
                display_groups.append({
                    'name': display_name,
                    'plates': chunk
                })
        else:
            display_groups.append(group)
    
    for group_idx, group in enumerate(display_groups):
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
    
    for col_idx in range(1, len(display_groups) * 2 + 1):
        if col_idx % 2 == 1:
            ws.column_dimensions[chr(64 + col_idx)].width = 30
        else:
            ws.column_dimensions[chr(64 + col_idx)].width = 2
    
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()

st.header("Add Photo Group")

with st.form("upload_form"):
    group_header = st.text_input(
        "Site Name:",
        placeholder="e.g., 'Parking Lot A', 'Monday Cars', 'Lot 1'",
        help="This will appear as the header for this site in the Excel file"
    )
    
    uploaded_files = st.file_uploader(
        "Upload car images for this group",
        type=['png', 'jpg', 'jpeg'],
        accept_multiple_files=True,
        help="Upload one or more images containing cars with visible license plates",
        key=f"uploader_{st.session_state.clear_uploader}"
    )
    
    if uploaded_files:
        total_size_mb = sum(file.size for file in uploaded_files) / (1024 * 1024)
        if total_size_mb >= 990:
            st.error("Maximum upload size reached! Remove some photos to add more.")
    
    submitted = st.form_submit_button("✅ Process & Add to List", use_container_width=True)

if submitted and uploaded_files and group_header:
    with st.spinner("Processing images with AWS Rekognition..."):
        all_plates = []
        processed_count = 0
        no_plate_images = []
        error_images = []
        failed_images_data = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Processing image {idx + 1} of {len(uploaded_files)}...")
            
            try:
                image_bytes = uploaded_file.read()
                compressed_bytes = compress_image(image_bytes)
                plates = detect_plates_in_image(compressed_bytes)
                
                if plates:
                    all_plates.extend(plates)
                    processed_count += 1
                else:
                    no_plate_images.append(uploaded_file.name)
                    failed_images_data.append({
                        'name': uploaded_file.name,
                        'image': Image.open(io.BytesIO(image_bytes)),
                        'plate': ''
                    })
                
            except Exception as e:
                error_images.append(uploaded_file.name)
            
            progress = (idx + 1) / len(uploaded_files)
            progress_bar.progress(progress)
        
        unique_plates = list(dict.fromkeys(all_plates))
        
        progress_bar.empty()
        status_text.empty()
        
        existing_group = None
        for group in st.session_state.all_groups:
            if group['name'].lower() == group_header.lower():
                existing_group = group
                break
        
        if existing_group:
            combined_plates = existing_group['plates'] + unique_plates
            new_unique_plates = list(dict.fromkeys(combined_plates))
            duplicates_found = len(combined_plates) - len(new_unique_plates)
            existing_group['plates'] = new_unique_plates
            existing_group['total_uploaded'] += len(uploaded_files)
            existing_group['no_plate_count'] += len(no_plate_images)
            existing_group['duplicate_count'] += duplicates_found
            st.success(f"Appended {len(unique_plates)} plate(s) to '{group_header}'")
        else:
            duplicates_in_batch = len(all_plates) - len(unique_plates)
            st.session_state.all_groups.append({
                'name': group_header,
                'plates': unique_plates,
                'total_uploaded': len(uploaded_files),
                'no_plate_count': len(no_plate_images),
                'duplicate_count': duplicates_in_batch
            })
            st.success(f"Added '{group_header}' with {len(unique_plates)} unique number plate(s)")
        
        if no_plate_images:
            st.warning(f"⚠️ No number plates detected in {len(no_plate_images)} image(s)")
            st.session_state.failed_images = failed_images_data
        
        if error_images:
            st.error(f"❌ Error processing {len(error_images)} image(s):")
            for img in error_images:
                st.write(f"  • {img}")
        
        st.session_state.clear_uploader = not st.session_state.clear_uploader
        st.rerun()

elif submitted and not group_header:
    st.warning("Please enter a site name before processing")

if st.session_state.failed_images:
    st.divider()
    st.header("📸 Manual Number Plate Entry")
    st.markdown("Images with no detected plates - enter the number plate manually:")
    
    for idx, failed_img in enumerate(st.session_state.failed_images):
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.image(failed_img['image'], use_column_width=True)
        
        with col2:
            st.write(f"**{failed_img['name']}**")
            plate = st.text_input(
                "Enter number plate:",
                key=f"manual_plate_{idx}",
                placeholder="e.g., PO75XPR"
            )
            if plate:
                st.session_state.failed_images[idx]['plate'] = plate.upper()
    
    if st.button("✅ Confirm Manual Entries", use_container_width=True):
        manual_plates = [img['plate'] for img in st.session_state.failed_images if img['plate']]
        
        if manual_plates:
            if st.session_state.all_groups:
                latest_group = st.session_state.all_groups[-1]
                combined_plates = latest_group['plates'] + manual_plates
                latest_group['plates'] = list(dict.fromkeys(combined_plates))
                st.success(f"Added {len(manual_plates)} manual plate(s) to '{latest_group['name']}'")
        
        st.session_state.failed_images = []
        st.rerun()

if st.session_state.all_groups:
    st.divider()
    st.header("📋 All Sites")
    
    for idx, group in enumerate(st.session_state.all_groups):
        col1, col2 = st.columns([3, 1])
        
        with col1:
            st.subheader(f"📌 {group['name']}")
            st.write(f"**Total images uploaded:** {group.get('total_uploaded', 0)}")
            st.write(f"**Unique Number Plates Identified:** {len(group['plates'])}")
            st.write(f"**Duplicates:** {group.get('duplicate_count', 0)}")
            st.write(f"**No number plate detected:** {group.get('no_plate_count', 0)}")
        
        with col2:
            st.write("")
            if st.button("❌ Remove", key=f"remove_{idx}", use_container_width=True):
                st.session_state.all_groups.pop(idx)
                st.rerun()
    
    st.divider()
    
    st.header("📊 Export to Excel")
    
    filename = st.text_input(
        "Excel filename:",
        value="number_plates",
        help="The file will be saved as .xlsx"
    )
    
    total_groups = len(st.session_state.all_groups)
    total_plates = sum(len(group['plates']) for group in st.session_state.all_groups)
    total_images = sum(group.get('total_uploaded', 0) for group in st.session_state.all_groups)
    
    st.info(f"**Total images uploaded:** {total_images} | **Total unique number plates:** {total_plates}")
    
    excel_data = create_excel_file(st.session_state.all_groups)
    excel_filename = f"{filename}.xlsx" if filename else "number_plates.xlsx"
    
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
        if st.button("🗑️ Clear All Sites", use_container_width=True):
            st.session_state.all_groups = []
            st.rerun()
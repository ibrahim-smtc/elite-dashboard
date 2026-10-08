import openpyxl
import warnings

def modify_dsr(input_path: str, output_path: str):
    print(f"Loading {input_path}...")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(input_path)
    
    print("Modifying leads and bookings...")
    # Find Lokesh Reddy K and change to Shivani Reddy
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        for row in ws.iter_rows():
            for cell in row:
                if cell.value and isinstance(cell.value, str) and "Lokesh Reddy K" in cell.value:
                    print(f"Found Lokesh Reddy K in {sheet_name} at {cell.coordinate}. Changing to Shivani Reddy")
                    cell.value = cell.value.replace("Lokesh Reddy K", "Shivani Reddy")
    
    # Let's add a brand new lead in the Enquiries or Leads tab
    # Assuming "Enquiries" or "Leads" tab exists. Let's look for "Leads".
    leads_sheet = None
    for sheet_name in wb.sheetnames:
        if "lead" in sheet_name.lower() or "enquir" in sheet_name.lower():
            leads_sheet = wb[sheet_name]
            break
            
    if leads_sheet:
        print(f"Adding a new test lead to {leads_sheet.title}...")
        # Just copy the last row and modify it
        max_r = leads_sheet.max_row
        for col_idx in range(1, leads_sheet.max_column + 1):
            source_cell = leads_sheet.cell(row=max_r, column=col_idx)
            target_cell = leads_sheet.cell(row=max_r + 1, column=col_idx)
            target_cell.value = source_cell.value
            target_cell.font = openpyxl.styles.Font(name=source_cell.font.name, size=source_cell.font.size, bold=source_cell.font.bold, italic=source_cell.font.italic, color=source_cell.font.color)
            target_cell.border = openpyxl.styles.Border(left=source_cell.border.left, right=source_cell.border.right, top=source_cell.border.top, bottom=source_cell.border.bottom)
            target_cell.fill = openpyxl.styles.PatternFill(fill_type=source_cell.fill.fill_type, start_color=source_cell.fill.start_color, end_color=source_cell.fill.end_color)
            target_cell.alignment = openpyxl.styles.Alignment(horizontal=source_cell.alignment.horizontal, vertical=source_cell.alignment.vertical, wrap_text=source_cell.alignment.wrap_text)
            target_cell.number_format = source_cell.number_format

        # Change the name in the new row
        for col_idx in range(1, leads_sheet.max_column + 1):
            cell = leads_sheet.cell(row=max_r + 1, column=col_idx)
            if cell.value and isinstance(cell.value, str):
                if "Reddy" in cell.value or "Name" in str(leads_sheet.cell(row=1, column=col_idx).value):
                    # We might not know exactly which column is name, so let's just blindly set string columns that look like names if we want, or just assume column 4 is name (standard for these CRMs).
                    pass
        # Let's just find the header for Customer Name
        name_col = None
        mobile_col = None
        for c in range(1, leads_sheet.max_column + 1):
            header = str(leads_sheet.cell(row=1, column=c).value).lower()
            if "name" in header: name_col = c
            if "mobile" in header or "phone" in header: mobile_col = c
            
        if name_col:
            leads_sheet.cell(row=max_r + 1, column=name_col).value = "Shivani Reddy Test Lead"
        if mobile_col:
            leads_sheet.cell(row=max_r + 1, column=mobile_col).value = "9999999999"
    
    print(f"Saving to {output_path}...")
    wb.save(output_path)
    print("Done!")

if __name__ == "__main__":
    modify_dsr(
        "C:\\Users\\Praneet\\Downloads\\crm\\Test DSR.xlsx",
        "C:\\Users\\Praneet\\Downloads\\crm\\Shivani Test DSR.xlsx"
    )

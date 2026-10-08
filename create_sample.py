import openpyxl
import warnings

def modify():
    input_path = 'Sample DSR.xlsx'
    output_path = 'Test DSR.xlsx'
    print(f'Loading {input_path}...')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        wb = openpyxl.load_workbook(input_path)
    
    replaced = 0
    for sheetname in wb.sheetnames:
        ws = wb[sheetname]
        for row in ws.iter_rows():
            for cell in row:
                if cell.value and isinstance(cell.value, str) and 'lokesh' in cell.value.lower():
                    # Preserve case formatting if needed, but simple replace for now:
                    if 'Lokesh Reddy K' in cell.value:
                        cell.value = cell.value.replace('Lokesh Reddy K', 'Shivani Reddy K')
                        replaced += 1
                    elif 'LOKESH REDDY K' in cell.value:
                        cell.value = cell.value.replace('LOKESH REDDY K', 'SHIVANI REDDY K')
                        replaced += 1
                    elif 'Lokesh' in cell.value:
                        cell.value = cell.value.replace('Lokesh', 'Shivani')
                        replaced += 1
                        
    print(f'Replaced {replaced} total occurrences of Lokesh in the workbook.')
    
    # Add new leads in 'Leads'
    ws = wb['Leads']
    max_row = ws.max_row
    last_row_data = [cell.value for cell in ws[max_row]]
    
    new_names = ['Shivani Reddy K', 'Test Lead Beta', 'Test Lead Gamma']
    for name in new_names:
        new_row_data = list(last_row_data)
        for j, cell in enumerate(ws[1]):
            if cell.value and 'Name' in str(cell.value):
                new_row_data[j] = name
        ws.append(new_row_data)
        
    wb.save(output_path)
    print(f'Saved to {output_path}')

if __name__ == '__main__':
    modify()

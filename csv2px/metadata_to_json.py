#!/usr/bin/env python3
"""
Converts user-friendly metadata text files to PxBuild JSON format.

Input: txt file with simple key: value format
Output: json file in PxBuild JSON structure

Example input file format:
    Tabell-kode: SYS002
    antall desimaler: 2
    Måleénheter: personer, prosent
    ...
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Tuple


def parse_metadata_file(filepath: str) -> Dict[str, str]:
    """Parse the text metadata file and return key-value pairs.
    
    Handles format with section headings:
        -----------
        SECTION NAME
        -----------
        key: value
        another_key: another value
    """
    metadata = {}
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Skip empty lines, comments, and heading lines (lines with only dashes)
            if not line or line.startswith('#') or set(line) == {'-'}:
                continue
            # Skip lines that are only section names (no dashes, no colons)
            if ':' not in line and '-' not in line:
                continue
            
            # Split on first colon
            if ':' not in line:
                continue
            
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()
            
            metadata[key] = value
    
    return metadata


def extract_contact_info(contact_str: str) -> Dict[str, Any]:
    """
    Extract contact information from comma-separated string.
    Format: "Name, email@example.com, +47 12345678"
    """
    parts = [p.strip() for p in contact_str.split(',')]
    contact = {}
    
    if len(parts) > 0:
        contact['name'] = {'no': parts[0]}
    if len(parts) > 1:
        contact['email'] = parts[1]
    if len(parts) > 2:
        contact['phone'] = parts[2]
    
    return contact


def parse_dimension_lists(dimension_names: str, dimension_codes: str = "", elimination_codes: str = "") -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Parse dimension names and codes to separate coded and uncoded dimensions.
    
    Args:
        dimension_names: Comma-separated dimension names (e.g., "geografi_navn, alder, kjønn")
        dimension_codes: Comma-separated dimension codes or empty strings (e.g., "geografi_kode, , ")
        elimination_codes: Comma-separated elimination codes
    
    Returns:
        Tuple of (coded_dimensions, uncoded_dimensions) lists
    """
    coded_dims = []
    uncoded_dims = []
    
    dim_names = [d.strip() for d in dimension_names.split(',')]
    dim_codes = [d.strip() for d in dimension_codes.split(',')] if dimension_codes else []
    elim_codes = [e.strip() for e in elimination_codes.split(',')] if elimination_codes else []
    
    # Pad dimension_codes list to match dimension_names length
    while len(dim_codes) < len(dim_names):
        dim_codes.append('')
    
    # Pad elimination_codes list to match dimension_names length
    while len(elim_codes) < len(dim_names):
        elim_codes.append('')
    
    for i, dim_name in enumerate(dim_names):
        dim_code = dim_codes[i] if i < len(dim_codes) else ''
        elim_code = elim_codes[i] if i < len(elim_codes) else ''
        
        # Extract dimension ID from name (remove _navn if present)
        dim_id = dim_name.replace('_namn', '').replace('_navn', '').replace('_name', '')
        
        dimension = {
            'dimensionId': dim_id,
            'columnName': dim_code if dim_code else dim_name,
            'label': {'no': dim_id},
            'eliminationPossible': True if elim_code else False
        }
        
        if elim_code:
            dimension['eliminationCode'] = elim_code
        
        # Remove None values
        dimension = {k: v for k, v in dimension.items() if v is not None}
        
        # Add to coded or uncoded based on whether code is provided
        if dim_code:
            # Add required fields for coded dimensions
            dimension['codelistId'] = dim_id
            dimension['labelConstructionOption'] = 'text'
            dimension['labelColumnName'] = f'{dim_id}_navn'
            coded_dims.append(dimension)
        else:
            uncoded_dims.append(dimension)
    
    return coded_dims, uncoded_dims





def build_measurements(measurement_names: str, units_str: str = None, precision_str: str = None, aggregation_allowed: bool = True) -> List[Dict[str, Any]]:
    """Build measurements array from measurement names and optional units.
    
    Args:
        measurement_names: Comma-separated measurement names
        units_str: Optional comma-separated units (if provided, must match number of measurements)
        precision_str: Optional comma-separated precision values
        aggregation_allowed: Whether aggregation is allowed
    """
    measurements = []
    meas_list = [m.strip() for m in measurement_names.split(',')]
    
    # Parse units if provided
    units_list = []
    if units_str:
        units_list = [u.strip() for u in units_str.split(',')]
    
    # Parse precision values if provided
    precision_list = []
    if precision_str:
        try:
            precision_list = [int(p.strip()) for p in precision_str.split(',')]
        except ValueError:
            precision_list = []
    
    # Generate codes for measurements (simple pattern: ASxx, ASx1, etc.)
    codes = ['ASXX', 'ASX1', 'BTXX', 'DSXX', 'ESXX']
    
    for i, meas in enumerate(meas_list):
        unit = units_list[i] if i < len(units_list) else 'Enheter'
        
        # Convert measurement name to ID with underscores
        meas_id = meas.lower().replace(' ', '_')
        
        measurement = {
            'measurementId': meas_id,
            'code': codes[i] if i < len(codes) else f'CD{i:02d}',
            'label': {'no': meas_id},
            'columnName': meas_id,
            'aggregationAllowed': aggregation_allowed,
            'unitOfMeasure': {'no': unit}
        }
        
        # Add precision if provided and greater than 0 (requires 1-6)
        if i < len(precision_list) and precision_list[i] and precision_list[i] > 0:
            measurement['precision'] = precision_list[i]
        
        measurements.append(measurement)
    
    return measurements


def metadata_to_json(input_file: str, output_file: str = None) -> str:
    """
    Convert metadata text file to JSON.
    
    Args:
        input_file: Path to metadata text file
        output_file: Path to output JSON file (auto-generated if None)
    
    Returns:
        JSON string
    """
    # Parse input file
    metadata = parse_metadata_file(input_file)
    
    # Extract table code
    table_code = metadata.get('Tabell-kode', 'UNKNOWN')
    table_code_clean = table_code.replace('-', '').replace(' ', '')
    
    # Try new format first (Dimensjoner navn), fall back to old format (Dimensjoner)
    dim_names = metadata.get('Dimensjoner navn', metadata.get('Dimensjoner', ''))
    dim_codes = metadata.get('Dimensjoner kode', '')
    elim_codes = metadata.get('Eliminasjon', '')
    
    coded_dimensions, uncoded_dimensions = parse_dimension_lists(dim_names, dim_codes, elim_codes)
    
    # Extract subject area and use for subjectText/subjectarea if available
    subject_area = metadata.get('subject-area', table_code_clean)
    
    # Get time dimension info - use the raw name from metadata for dimensionId
    time_dim_name = metadata.get('Navn på tidsdimensjon', 'tid')
    
    # Get optional title/content fields, with fallbacks
    title_text = metadata.get('Tittel', f'{table_code}: {subject_area}') if metadata.get('Tittel') else f'{table_code}'
    base_title = metadata.get('Basetittel', subject_area)
    contents_text = metadata.get('Innhold', subject_area)
    
    # Build JSON structure
    dataset = {
        'dataset': {
            'matrix': f'OK-{table_code_clean}',
            'decimals': int(metadata.get('Antall desimaler', '0')),
            'showDecimals': 0,
            'subjectCode': table_code_clean,
            'subjectText': {
                'no': subject_area if subject_area else metadata.get('Tabell-kode', 'Unknown'),
            },
            'subjectarea': {
                'no': subject_area if subject_area else metadata.get('Tabell-kode', 'Unknown')
            },
            'title': {
                'no': title_text
            },
            'contents': {
                'no': contents_text
            },
            'units': {
                'no': metadata.get('Måleénheter', '')
            },
            'last-updated': metadata.get('Sist oppdatert', ''),
            'notes': [
                {
                    'text': {'no': metadata.get('Notater', '')},
                    'isMandatory': False
                }
            ] if metadata.get('Notater') else [],
            'tableId': table_code_clean,
            'baseTitle': {'no': base_title},
            'searchKeywords': {'no': []},
            'statisticsId': table_code_clean,
            'dataFile': table_code_clean,
            'contacts': [extract_contact_info(metadata['Kontakt'])] if 'Kontakt' in metadata else [],
            'timeDimension': {
                'dimensionId': time_dim_name,
                'columnName': time_dim_name,
                'label': {'no': time_dim_name}
            },
            'codedDimensions': coded_dimensions,
            'dimensions': uncoded_dimensions,
            'measurements': build_measurements(
                metadata.get('Statistikkvariabler', ''),
                metadata.get('Måleénheter', ''),
                metadata.get('Presisjon', ''),
                metadata.get('aggregationAllowed', 'false').lower() == 'true'
            ) if 'Statistikkvariabler' in metadata else []
        }
    }
    
    # Generate output filename if not provided
    if output_file is None:
        input_path = Path(input_file)
        output_file = input_path.parent / f'{table_code_clean}.json'
    
    # Write JSON file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)
    
    print(f'✓ Successfully converted {input_file}')
    print(f'✓ Output written to {output_file}')
    
    return json.dumps(dataset, indent=2, ensure_ascii=False)


def main():
    """Command-line interface."""
    if len(sys.argv) < 2:
        print('Usage: python metadata_to_json.py <input_file> [output_file]')
        print('Example: python metadata_to_json.py metadata_SYS002.txt')
        print('         python metadata_to_json.py metadata_SYS002.txt output_SYS002.json')
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        metadata_to_json(input_file, output_file)
    except FileNotFoundError:
        print(f'Error: File not found: {input_file}', file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

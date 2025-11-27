#!/usr/bin/env python3
"""
Analyze FC and FMASK date matching for tile 089078
Determine how many FC files have exact FMASK matches vs need proximity search
"""

import os
import re
from datetime import datetime, timedelta
from collections import defaultdict

def extract_date_from_filename(filename):
    """Extract date from filename in various formats"""
    # Standard format: YYYYMMDD
    match = re.search(r'(\d{8})', filename)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y%m%d')
        except ValueError:
            pass
    
    # Alternative format: YYYY-MM-DD
    match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y-%m-%d')
        except ValueError:
            pass
    
    return None

def find_closest_date(target_date, available_dates, max_days=7):
    """Find closest date within max_days window"""
    if not available_dates:
        return None, float('inf')
    
    closest_date = None
    min_diff = float('inf')
    
    for date in available_dates:
        diff = abs((target_date - date).days)
        if diff <= max_days and diff < min_diff:
            min_diff = diff
            closest_date = date
    
    return closest_date, min_diff

def main():
    tile_dir = r'D:\data\lsat\089_078'
    
    # Collect all FC files
    fc_files = []
    fc_dates = []
    
    print("Scanning for FC files...")
    for root, dirs, files in os.walk(tile_dir):
        for file in files:
            if file.endswith('_fc3ms.tif') and '_clr' not in file:
                filepath = os.path.join(root, file)
                file_date = extract_date_from_filename(file)
                if file_date:
                    fc_files.append((filepath, file, file_date))
                    fc_dates.append(file_date)
                else:
                    print(f"Could not extract date from FC file: {file}")
    
    # Collect all FMASK files
    fmask_files = []
    fmask_dates = []
    fmask_dates_set = set()
    
    print(f"\nScanning for FMASK files...")
    for root, dirs, files in os.walk(tile_dir):
        for file in files:
            if file.endswith('_fmask.tif'):
                filepath = os.path.join(root, file)
                file_date = extract_date_from_filename(file)
                if file_date:
                    fmask_files.append((filepath, file, file_date))
                    fmask_dates.append(file_date)
                    fmask_dates_set.add(file_date)
                else:
                    print(f"Could not extract date from FMASK file: {file}")
    
    print(f"\nFound {len(fc_files)} FC files")
    print(f"Found {len(fmask_files)} FMASK files")
    
    # Analyze matches
    exact_matches = 0
    proximity_matches = 0
    no_matches = 0
    
    exact_match_details = []
    proximity_match_details = []
    no_match_details = []
    
    print(f"\nAnalyzing date matches...")
    
    for fc_path, fc_file, fc_date in fc_files:
        # Check for exact match
        if fc_date in fmask_dates_set:
            exact_matches += 1
            exact_match_details.append((fc_file, fc_date.strftime('%Y-%m-%d')))
        else:
            # Check for proximity match within 7 days
            closest_date, diff_days = find_closest_date(fc_date, fmask_dates, max_days=7)
            if closest_date:
                proximity_matches += 1
                proximity_match_details.append((fc_file, fc_date.strftime('%Y-%m-%d'), 
                                              closest_date.strftime('%Y-%m-%d'), int(diff_days)))
            else:
                no_matches += 1
                no_match_details.append((fc_file, fc_date.strftime('%Y-%m-%d')))
    
    # Print summary
    print(f"\n" + "="*80)
    print(f"DATE MATCHING ANALYSIS FOR TILE 089078")
    print(f"="*80)
    print(f"Total FC files:           {len(fc_files)}")
    print(f"Total FMASK files:        {len(fmask_files)}")
    print(f"")
    print(f"Exact date matches:       {exact_matches:3d} ({exact_matches/len(fc_files)*100:.1f}%)")
    print(f"Proximity matches (≤7d):  {proximity_matches:3d} ({proximity_matches/len(fc_files)*100:.1f}%)")
    print(f"No matches found:         {no_matches:3d} ({no_matches/len(fc_files)*100:.1f}%)")
    print(f"")
    print(f"Total with FMASK data:    {exact_matches + proximity_matches:3d} ({(exact_matches + proximity_matches)/len(fc_files)*100:.1f}%)")
    
    # Show some examples
    if exact_match_details:
        print(f"\nEXACT MATCHES (first 5):")
        for i, (fc_file, fc_date) in enumerate(exact_match_details[:5]):
            print(f"  {fc_file} -> {fc_date}")
        if len(exact_match_details) > 5:
            print(f"  ... and {len(exact_match_details) - 5} more")
    
    if proximity_match_details:
        print(f"\nPROXIMITY MATCHES (first 5):")
        for i, (fc_file, fc_date, fmask_date, diff) in enumerate(proximity_match_details[:5]):
            print(f"  {fc_file} ({fc_date}) -> {fmask_date} (+{diff}d)")
        if len(proximity_match_details) > 5:
            print(f"  ... and {len(proximity_match_details) - 5} more")
    
    if no_match_details:
        print(f"\nNO MATCHES FOUND (first 10):")
        for i, (fc_file, fc_date) in enumerate(no_match_details[:10]):
            print(f"  {fc_file} ({fc_date}) -> NO FMASK WITHIN 7 DAYS")
        if len(no_match_details) > 10:
            print(f"  ... and {len(no_match_details) - 10} more")
    
    # Date range analysis
    if fc_dates:
        fc_start = min(fc_dates)
        fc_end = max(fc_dates)
        print(f"\nFC DATE RANGE: {fc_start.strftime('%Y-%m-%d')} to {fc_end.strftime('%Y-%m-%d')}")
    
    if fmask_dates:
        fmask_start = min(fmask_dates)
        fmask_end = max(fmask_dates)
        print(f"FMASK DATE RANGE: {fmask_start.strftime('%Y-%m-%d')} to {fmask_end.strftime('%Y-%m-%d')}")
    
    # Show distribution by year
    fc_by_year = defaultdict(int)
    fmask_by_year = defaultdict(int)
    matches_by_year = defaultdict(lambda: {'exact': 0, 'proximity': 0, 'none': 0})
    
    for _, _, fc_date in fc_files:
        year = fc_date.year
        fc_by_year[year] += 1
        
        # Determine match type for this FC file
        if fc_date in fmask_dates_set:
            matches_by_year[year]['exact'] += 1
        else:
            closest_date, diff_days = find_closest_date(fc_date, fmask_dates, max_days=7)
            if closest_date:
                matches_by_year[year]['proximity'] += 1
            else:
                matches_by_year[year]['none'] += 1
    
    for _, _, fmask_date in fmask_files:
        fmask_by_year[fmask_date.year] += 1
    
    print(f"\nDISTRIBUTION BY YEAR:")
    print(f"Year    FC  FMASK  Exact  Proximity  NoMatch")
    print(f"-" * 45)
    for year in sorted(set(fc_by_year.keys()) | set(fmask_by_year.keys())):
        fc_count = fc_by_year[year]
        fmask_count = fmask_by_year[year] 
        exact = matches_by_year[year]['exact']
        prox = matches_by_year[year]['proximity']
        none = matches_by_year[year]['none']
        print(f"{year}   {fc_count:3d}   {fmask_count:3d}     {exact:2d}       {prox:2d}       {none:2d}")

if __name__ == "__main__":
    main()
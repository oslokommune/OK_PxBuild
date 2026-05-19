import argparse
import pandas as pd
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Convert Excel file to CSV")
    parser.add_argument("id", help="The ID of the Excel file (without .xlsx extension)")
    args = parser.parse_args()

    input_dir = Path(r"input\excel_files")
    output_dir = Path(r"input\csv_files")

    excel_file = input_dir / f"{args.id}.xlsx"
    csv_file = output_dir / f"{args.id}.csv"

    if not excel_file.exists():
        print(f"Error: {excel_file} does not exist")
        return

    # Read Excel file
    df = pd.read_excel(excel_file)

    # Write to CSV
    df.to_csv(csv_file, index=False, sep=";")
    print(f"Converted {excel_file} to {csv_file}")


if __name__ == "__main__":
    main()

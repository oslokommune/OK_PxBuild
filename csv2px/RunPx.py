from pathlib import Path
import argparse
import pxbuild


def main():
    """Run the PxBuild process for a given table ID."""
    ap = argparse.ArgumentParser()  # Argument parser for command-line interface
    ap.add_argument("tableid", type=str, help="Table ID (e.g., VAL001)")  # Table ID argument
    args = ap.parse_args()  # Parse command-line arguments

    ID = args.tableid.upper()  # Convert table ID to uppercase
    Path(f"output/px/output_{ID}").mkdir(parents=True, exist_ok=True)  # Create output directory if it doesn't exist
    pxbuild.LoadFromPxmetadata(ID, "input/pxbuildconfig/my_config.json")  # Load PX metadata and build PX file


if __name__ == "__main__":
    main()

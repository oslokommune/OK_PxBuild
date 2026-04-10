from pathlib import Path
import argparse
import pxbuild


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tableid", type=str, help="Table ID (e.g., VAL001)")
    args = ap.parse_args()

    ID = args.tableid.upper()
    Path(f"output/px/output_{ID}").mkdir(parents=True, exist_ok=True)
    pxbuild.LoadFromPxmetadata(ID, "input/pxbuildconfig/my_config.json")


if __name__ == "__main__":
    main()

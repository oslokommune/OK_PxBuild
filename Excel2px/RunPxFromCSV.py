from pathlib import Path
import pxbuild

ID = input("Enter ID of the dataset: ")
Path(f"Excel2px/output/px/output_{ID}").mkdir(parents=True, exist_ok=True)
pxbuild.LoadFromPxmetadata(ID, "Excel2px/pxjson/pxbuildconfig/my_configCSV.json")

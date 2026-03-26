from pathlib import Path
import pxbuild

ID = input("Enter ID of the dataset: ")
Path(f"output/px/output_{ID}").mkdir(parents=True, exist_ok=True)
pxbuild.LoadFromPxmetadata(ID, "pxjson/pxbuildconfig/my_config.json")

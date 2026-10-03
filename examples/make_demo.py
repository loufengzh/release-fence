"""Generate a tiny ZIP from synthetic text; no project data is read."""
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

output = Path(__file__).with_name("demo.zip")
with ZipFile(output, "w") as archive:
    for name, content in [("LICENSE", "Synthetic demonstration license text.\n"),
                          ("README.md", "# Demonstration package\n"),
                          ("package/version.txt", "0.1.0\n")]:
        info = ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        archive.writestr(info, content)
print(output)

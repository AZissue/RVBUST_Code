import json, glob, os

base = "prototypes/cloudcompare_like"
files = []
for ext in ["*.py", "*.md"]:
    for path in glob.glob(f"{base}/**/{ext}", recursive=True):
        rel = path.replace(base + "/", "prototypes/cloudcompare_like/")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        files.append({"path": rel, "content": content})

print(f"Found {len(files)} files")
with open("_push_files.json", "w", encoding="utf-8") as f:
    json.dump(files, f, ensure_ascii=False)

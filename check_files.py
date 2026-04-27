import paramiko

# Remove BOM from local index.html
local_path = r"D:\RVC_SRC\CRM_New\project\index.html"
with open(local_path, 'rb') as f:
    content = f.read()

# Remove BOM if present
if content.startswith(b'\xef\xbb\xbf'):
    content = content[3:]
    print("[Fix] Removed BOM from index.html")
else:
    print("[Fix] No BOM found")

with open(local_path, 'wb') as f:
    f.write(content)
print("[Fix] Saved clean index.html")

# Now upload to server
HOST = "120.55.245.72"
USER = "root"
PASS = "010921Zj"

print("[Connect] Connecting to server...")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASS, timeout=30)

print("[Upload] Uploading fixed index.html...")
sftp = client.open_sftp()
sftp.put(local_path, "/opt/crm-new/project/index.html")
sftp.close()
print("[OK] Uploaded fixed index.html")

# Restart PM2
print("[Restart] Restarting crm-new...")
stdin, stdout, stderr = client.exec_command("pm2 restart crm-new")
stdout.read()
client.close()

print("[Done] Fixed and deployed!")
print("[URL] http://120.55.245.72:38000")

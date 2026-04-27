import paramiko

HOST = "120.55.245.72"
USER = "root"
PASS = "010921Zj"
LOCAL_TAR = r"D:\RVC_SRC\CRM_New\crm-new.tar.gz"
LOCAL_SCRIPT = r"D:\RVC_SRC\CRM_New\deploy.sh"

print("[Connect] Connecting to server...")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASS, timeout=30)

print("[Upload] Uploading crm-new.tar.gz...")
sftp = client.open_sftp()
sftp.put(LOCAL_TAR, "/opt/crm-new.tar.gz")
print("[OK] tar.gz uploaded")

print("[Upload] Uploading deploy.sh...")
sftp.put(LOCAL_SCRIPT, "/opt/deploy.sh")
sftp.close()
print("[OK] deploy.sh uploaded")

print("[Deploy] Running remote deploy...")
stdin, stdout, stderr = client.exec_command("cd /opt && bash deploy.sh")
output = stdout.read().decode('utf-8', errors='replace')
errors = stderr.read().decode('utf-8', errors='replace')
client.close()

with open(r'D:\RVC_SRC\CRM_New\deploy_output.txt', 'w', encoding='utf-8') as f:
    f.write('=== Deploy Output ===\n')
    f.write(output)
    if errors:
        f.write('\n=== Error Output ===\n')
        f.write(errors)

print('[Done] Deploy finished!')
print('[URL] http://{}:38000'.format(HOST))
print('[Log] See D:\\RVC_SRC\\CRM_New\\deploy_output.txt')

with open(r'D:\RVC_SRC\CRM_New\project\index.html', 'rb') as f:
    data = f.read()
if data.startswith(b'\xef\xbb\xbf'):
    data = data[3:]
    print('Removed BOM')
else:
    print('No BOM found')
with open(r'D:\RVC_SRC\CRM_New\project\index.html', 'wb') as f:
    f.write(data)
print('Done, file size:', len(data))

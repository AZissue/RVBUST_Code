import requests

# 测试登录
res = requests.post('http://localhost:3000/api/login', json={'username': 'admin', 'password': 'admin123'})
print(f"Status: {res.status_code}")
print(f"Body: {res.text[:200]}")

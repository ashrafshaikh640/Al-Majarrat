import urllib.request
import json
import socket
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

ENDPOINTS = [
    ("Ollama Default", "http://localhost:11434/v1/chat/completions", "127.0.0.1", 11434, "qwen2.5:3b"),
    ("LM Studio Default", "http://localhost:1234/v1/chat/completions", "127.0.0.1", 1234, "local-model"),
    ("vLLM / Local API", "http://localhost:8000/v1/chat/completions", "127.0.0.1", 8000, "default"),
    ("Text-Gen WebUI", "http://localhost:5000/v1/chat/completions", "127.0.0.1", 5000, "default")
]

def check_port(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.5)
    res = s.connect_ex((host, port))
    s.close()
    return res == 0

def test_endpoint(name, url, model):
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Hello! Confirm if you are operational."}
        ],
        "max_tokens": 50
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            choices = res_data.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "").strip()
                return True, content
            return True, "Connected successfully, but response format was empty."
    except Exception as e:
        return False, str(e)

def main():
    print("==========================================================")
    print("   PROJECT AL-MAJARRAT - OFFLINE LLM CONNECTION TESTER    ")
    print("==========================================================")
    
    found_any = False
    
    for name, url, host, port, model in ENDPOINTS:
        print(f"\nTesting {name} (Port {port})...")
        is_port_open = check_port(host, port)
        
        if not is_port_open:
            print(f"  ❌ Port {port} is CLOSED / Inactive.")
        else:
            print(f"  ✅ Port {port} is OPEN! Sending test prompt...")
            success, message = test_endpoint(name, url, model)
            if success:
                print(f"  🎉 SUCCESS! Connected to {name} at {url}")
                print(f"  Response: \"{message}\"")
                found_any = True
            else:
                print(f"  ⚠️ Port is open, but API request failed: {message}")

    print("\n" + "="*58)
    if found_any:
        print("🟢 SUCCESS: An active Offline LLM server was detected!")
        print("You can run `python src/al_majarrat.py` to start AI Q&A.")
    else:
        print("🔴 OFFLINE: No active Local LLM server detected on ports 11434 or 1234.")
        print("\nTo connect an offline LLM:")
        print("1. Install & start Ollama (https://ollama.com) -> run `ollama run llama3` in PowerShell")
        print("2. OR start LM Studio (https://lmstudio.ai) -> click 'Start Local Server'")
        print("3. Re-run `python test_offline_llm.py` to verify.")

if __name__ == "__main__":
    main()

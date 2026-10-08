import os
import sys
import subprocess
import webbrowser
import time
import socket

def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("",0))
    s.listen(1)
    port = s.getsockname()[1]
    s.close()
    return port

if __name__ == '__main__':
    # Determine absolute path to the streamlit app script
    if getattr(sys, 'frozen', False):
        application_path = sys._MEIPASS
    else:
        application_path = os.path.dirname(os.path.abspath(__file__))
        
    app_path = os.path.join(application_path, 'app.py')  # Replace 'app.py' with your exam script name
    
    port = get_free_port()
    
    # Start the Streamlit server in the background
    subprocess.Popen([
        sys.executable, "-m", "streamlit", "run", app_path, 
        "--server.port", str(port), 
        "--server.headless", "true"
    ])
    
    # Give the server a moment to boot, then open the browser
    time.sleep(3)
    webbrowser.open(f'http://localhost:{port}')
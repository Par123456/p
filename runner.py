import time
import paramiko
import random
import string
import json
import os
from datetime import datetime
from telethon import TelegramClient, events
from pathlib import Path

# ===================== BOT CONFIG =====================
API_ID = 123456
API_HASH = "API_HASH"
BOT_TOKEN = "BOT_TOKEN"

ADMIN_ID = 123456789  # فقط ادمین

# ===================== SSH CONFIG =====================
SSH_HOST = "1.2.3.4"
SSH_PORT = 22
SSH_USER = "root"
SSH_PASS = "password"

REMOTE_FILES = "/root/files"
REMOTE_LOGS = "/root/logs"

# ===================== SESSION MANAGEMENT =====================
SESSIONS_FILE = "sessions.json"
ACTIVE_SESSIONS = {}
PENDING_AUTH = {}

def load_sessions():
    global ACTIVE_SESSIONS
    if os.path.exists(SESSIONS_FILE):
        with open(SESSIONS_FILE, 'r') as f:
            ACTIVE_SESSIONS = json.load(f)

def save_sessions():
    with open(SESSIONS_FILE, 'w') as f:
        json.dump(ACTIVE_SESSIONS, f, indent=2)

def generate_session_id():
    prefix = ''.join(random.choices(string.ascii_lowercase, k=3))
    suffix = ''.join(random.choices(string.digits, k=3))
    return f"{prefix}{suffix}"

load_sessions()

# ===================== TELETHON =====================
client = TelegramClient("terminal_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ===================== SSH CORE =====================
def ssh_exec(cmd, timeout=20):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            hostname=SSH_HOST,
            port=SSH_PORT,
            username=SSH_USER,
            password=SSH_PASS,
            timeout=timeout
        )
        stdin, stdout, stderr = ssh.exec_command(cmd)
        out = stdout.read().decode()
        err = stderr.read().decode()
        ssh.close()
        return out if out else err if err else "OK"
    except Exception as e:
        return f"SSH ERROR: {e}"

def is_admin(event):
    return event.sender_id == ADMIN_ID

# ===================== RUN WITH 4 METHODS =====================
def run_remote(filename):
    path = f"{REMOTE_FILES}/{filename}"
    log = f"{REMOTE_LOGS}/{filename}.log"

    methods = [
        f"nohup python3 {path} > {log} 2>&1 &",
        f"screen -dmS {filename} python3 {path}",
        f"python3 {path}",
        f"bash {path}"
    ]

    for cmd in methods:
        ssh_exec(cmd)
        time.sleep(2)
        check = ssh_exec(f"ps aux | grep {filename} | grep -v grep")
        if filename in check:
            return f"RUN SUCCESS\n{cmd}"

    return "ALL METHODS FAILED"

# ===================== GIT & DIRECT UPLOAD =====================
def download_from_git(git_url, filename):
    """Download file directly from git repository"""
    try:
        cmd = f"cd {REMOTE_FILES} && wget -O {filename} '{git_url}' 2>&1"
        result = ssh_exec(cmd)
        if "saved" in result.lower() or "100%" in result:
            return f"✅ Downloaded: {filename}\n{result}"
        return f"❌ Download failed: {result}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

def download_from_url(url, filename):
    """Download file from direct URL"""
    try:
        cmd = f"cd {REMOTE_FILES} && curl -L -o {filename} '{url}' 2>&1"
        result = ssh_exec(cmd)
        return f"✅ Downloaded: {filename}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

# ===================== INTERACTIVE SESSION SYSTEM =====================
def create_session(filename, session_type="pyrun"):
    """Create an interactive session with unique ID"""
    session_id = generate_session_id()
    session_data = {
        "id": session_id,
        "filename": filename,
        "type": session_type,
        "created": datetime.now().isoformat(),
        "status": "pending",
        "auth_steps": [],
        "responses": {}
    }
    ACTIVE_SESSIONS[session_id] = session_data
    save_sessions()
    return session_id

def get_session(session_id):
    """Get session data"""
    return ACTIVE_SESSIONS.get(session_id)

def update_session(session_id, key, value):
    """Update session data"""
    if session_id in ACTIVE_SESSIONS:
        ACTIVE_SESSIONS[session_id][key] = value
        save_sessions()

def delete_session(session_id):
    """Delete session"""
    if session_id in ACTIVE_SESSIONS:
        del ACTIVE_SESSIONS[session_id]
        save_sessions()

def list_sessions():
    """List all active sessions"""
    sessions_info = []
    for sid, data in ACTIVE_SESSIONS.items():
        sessions_info.append(
            f"ID: {sid}\n"
            f"  File: {data.get('filename')}\n"
            f"  Type: {data.get('type')}\n"
            f"  Status: {data.get('status')}\n"
            f"  Created: {data.get('created')}"
        )
    return "\n\n".join(sessions_info) if sessions_info else "No active sessions"

# ===================== AUTHENTICATION FLOW =====================
def start_authentication(filename, auth_requirements=None):
    """Start multi-step authentication"""
    session_id = create_session(filename, "pyrun")
    
    if auth_requirements is None:
        auth_requirements = ["phone_number", "code"]
    
    session = get_session(session_id)
    session["auth_steps"] = auth_requirements
    session["current_step"] = 0
    session["status"] = "awaiting_input"
    update_session(session_id, "auth_steps", auth_requirements)
    update_session(session_id, "current_step", 0)
    update_session(session_id, "status", "awaiting_input")
    
    return session_id

def get_next_auth_step(session_id):
    """Get the next authentication step message"""
    session = get_session(session_id)
    if not session:
        return None
    
    current = session.get("current_step", 0)
    steps = session.get("auth_steps", [])
    
    if current < len(steps):
        step = steps[current]
        messages = {
            "phone_number": f"🔑 Session {session_id}\n\n📱 Phone Number Required:\nSend your phone number (e.g., +989123456789)",
            "code": f"🔑 Session {session_id}\n\n🔐 Verification Code Required:\nSend the code you received",
            "password": f"🔑 Session {session_id}\n\n🔒 Password Required:\nSend your password",
            "username": f"🔑 Session {session_id}\n\n👤 Username Required:\nSend your username",
            "email": f"🔑 Session {session_id}\n\n📧 Email Required:\nSend your email address",
        }
        return messages.get(step, f"Input required for: {step}")
    return None

def process_auth_response(session_id, response):
    """Process authentication response"""
    session = get_session(session_id)
    if not session:
        return None, "Session not found"
    
    current = session.get("current_step", 0)
    steps = session.get("auth_steps", [])
    
    if current >= len(steps):
        return None, "All steps completed"
    
    step_name = steps[current]
    session["responses"][step_name] = response
    
    next_step = current + 1
    update_session(session_id, "current_step", next_step)
    
    if next_step >= len(steps):
        update_session(session_id, "status", "auth_complete")
        return session_id, "✅ Authentication Complete!"
    
    return session_id, None

# ===================== PYRUN EXECUTION =====================
def execute_pyrun(session_id, filename):
    """Execute file with collected authentication data"""
    session = get_session(session_id)
    if not session:
        return "❌ Session not found"
    
    if session.get("status") != "auth_complete":
        return "❌ Authentication not completed"
    
    responses = session.get("responses", {})
    
    # Build command with responses
    cmd_args = " ".join([f'"{v}"' for v in responses.values()])
    path = f"{REMOTE_FILES}/{filename}"
    log = f"{REMOTE_LOGS}/{filename}_{session_id}.log"
    
    methods = [
        f"nohup python3 {path} {cmd_args} > {log} 2>&1 &",
        f"screen -dmS {session_id} python3 {path} {cmd_args}",
        f"python3 {path} {cmd_args}",
    ]
    
    for cmd in methods:
        ssh_exec(cmd)
        time.sleep(2)
        check = ssh_exec(f"ps aux | grep {session_id} | grep -v grep")
        if session_id in check:
            update_session(session_id, "status", "running")
            return f"✅ Execution Started\nSession: {session_id}\nFile: {filename}\nLog: {log}"
    
    return "❌ Execution failed"

def get_session_log(session_id):
    """Get log of a session"""
    session = get_session(session_id)
    if not session:
        return "❌ Session not found"
    
    filename = session.get("filename")
    log = f"{REMOTE_LOGS}/{filename}_{session_id}.log"
    out = ssh_exec(f"tail -n 100 {log} 2>/dev/null")
    return out if out else "No log found yet"

# ===================== COMMANDS =====================
@client.on(events.NewMessage)
async def handler(event):
    if not is_admin(event):
        return

    text = event.raw_text.strip()

    # filelist - List all files on server
    if text == "filelist":
        out = ssh_exec(f"ls -lah {REMOTE_FILES}")
        await event.reply(f"📁 Remote Files:\n\n{out[:4000]}")

    # runlist - List running processes
    elif text == "runlist":
        out = ssh_exec("ps aux | grep python3 | grep -v grep")
        await event.reply(f"🔄 Running Processes:\n\n{out[:4000]}")

    # lastlag - Get last log
    elif text == "lastlag":
        cmd = f"ls -t {REMOTE_LOGS} | head -1"
        last = ssh_exec(cmd).strip()
        if not last:
            await event.reply("❌ NO LOG")
            return
        log = ssh_exec(f"tail -n 50 {REMOTE_LOGS}/{last}")
        await event.reply(f"📋 Last Log:\n\n{log}")

    # addfile name.py - Create empty file
    elif text.startswith("addfile"):
        try:
            name = text.split(" ", 1)[1]
            ssh_exec(f"touch {REMOTE_FILES}/{name}")
            await event.reply(f"✅ File Created: {name}")
        except:
            await event.reply("❌ Usage: addfile filename.py")

    # adsor name.py - Add file from message or attachment
    elif text.startswith("adsor"):
        try:
            name = text.split(" ", 1)[1]
            reply = await event.get_reply_message()
            if not reply:
                await event.reply("❌ REPLY TO CODE OR FILE")
                return

            if reply.file:
                path = await reply.download_media()
                ssh = paramiko.Transport((SSH_HOST, SSH_PORT))
                ssh.connect(username=SSH_USER, password=SSH_PASS)
                sftp = paramiko.SFTPClient.from_transport(ssh)
                sftp.put(path, f"{REMOTE_FILES}/{name}")
                sftp.close()
                ssh.close()
            else:
                ssh_exec(f"echo '''{reply.text}''' > {REMOTE_FILES}/{name}")

            await event.reply(f"✅ File Saved: {name}")
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # delfile name.py - Delete file
    elif text.startswith("delfile"):
        try:
            name = text.split(" ", 1)[1]
            ssh_exec(f"rm -f {REMOTE_FILES}/{name}")
            await event.reply(f"✅ Deleted: {name}")
        except:
            await event.reply("❌ Usage: delfile filename.py")

    # check name.py - View file content
    elif text.startswith("check"):
        try:
            name = text.split(" ", 1)[1]
            out = ssh_exec(f"cat {REMOTE_FILES}/{name}")
            await event.reply(f"📄 Content of {name}:\n\n{out[:4000]}")
        except:
            await event.reply("❌ Usage: check filename.py")

    # run name.py - Run file (old method)
    elif text.startswith("run "):
        try:
            name = text.split(" ", 1)[1]
            out = run_remote(name)
            await event.reply(out)
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # pyrun name.py - Interactive execution (NEW)
    elif text.startswith("pyrun "):
        try:
            filename = text.split(" ", 1)[1].strip()
            session_id = start_authentication(filename, ["phone_number", "code"])
            next_msg = get_next_auth_step(session_id)
            PENDING_AUTH[session_id] = True
            await event.reply(next_msg)
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # gitdl URL filename - Download from git (NEW)
    elif text.startswith("gitdl "):
        try:
            parts = text.split(" ", 2)
            url = parts[1]
            filename = parts[2] if len(parts) > 2 else "downloaded_file.py"
            result = download_from_git(url, filename)
            await event.reply(result)
        except:
            await event.reply("❌ Usage: gitdl <git_url> <filename>")

    # urldl URL filename - Download from direct URL (NEW)
    elif text.startswith("urldl "):
        try:
            parts = text.split(" ", 2)
            url = parts[1]
            filename = parts[2] if len(parts) > 2 else "downloaded_file.py"
            result = download_from_url(url, filename)
            await event.reply(result)
        except:
            await event.reply("❌ Usage: urldl <url> <filename>")

    # sessions - List active sessions (NEW)
    elif text == "sessions":
        sessions_list = list_sessions()
        await event.reply(f"📊 Active Sessions:\n\n{sessions_list}")

    # session info <session_id> - Get session info (NEW)
    elif text.startswith("session info "):
        try:
            session_id = text.split(" ", 2)[2].strip()
            session = get_session(session_id)
            if session:
                info = f"""
🔍 Session Info:
ID: {session.get('id')}
File: {session.get('filename')}
Type: {session.get('type')}
Status: {session.get('status')}
Responses: {json.dumps(session.get('responses', {}), indent=2)}
                """
                await event.reply(info)
            else:
                await event.reply(f"❌ Session {session_id} not found")
        except:
            await event.reply("❌ Usage: session info <session_id>")

    # session delete <session_id> - Delete session (NEW)
    elif text.startswith("session delete "):
        try:
            session_id = text.split(" ", 2)[2].strip()
            delete_session(session_id)
            if session_id in PENDING_AUTH:
                del PENDING_AUTH[session_id]
            await event.reply(f"✅ Session {session_id} deleted")
        except:
            await event.reply("❌ Usage: session delete <session_id>")

    # session log <session_id> - Get session log (NEW)
    elif text.startswith("session log "):
        try:
            session_id = text.split(" ", 2)[2].strip()
            log = get_session_log(session_id)
            await event.reply(f"📋 Log for {session_id}:\n\n{log[:4000]}")
        except:
            await event.reply("❌ Usage: session log <session_id>")

    # kill all
    elif text == "kill all":
        ssh_exec("pkill -f python3")
        await event.reply("⚠️ ALL PROCESSES KILLED")

    # kill name.py
    elif text.startswith("kill"):
        try:
            name = text.split(" ", 1)[1]
            ssh_exec(f"pkill -f {name}")
            await event.reply(f"✅ Killed: {name}")
        except:
            await event.reply("❌ Usage: kill <process_name>")

    # trpy pip install ... - Terminal python
    elif text.startswith("trpy"):
        try:
            cmd = text.replace("trpy", "", 1).strip()
            out = ssh_exec(cmd)
            await event.reply(f"⚙️ Result:\n\n{out[:4000]}")
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # py code - Execute Python code
    elif text.startswith("py"):
        try:
            code = text.replace("py", "", 1).strip()
            exec_result = ssh_exec(f"python3 - << 'EOF'\n{code}\nEOF")
            await event.reply(f"🐍 Python Output:\n\n{exec_result[:4000]}")
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # pingserver - Server status
    elif text == "pingserver":
        out = ssh_exec("uptime && echo '---' && free -h && echo '---' && df -h /")
        await event.reply(f"🖥️ Server Status:\n\n{out}")

    # help - Show help
    elif text == "help" or text == "/help":
        help_text = """
📚 AVAILABLE COMMANDS:

📁 FILE MANAGEMENT:
  filelist          - List all remote files
  addfile <name>    - Create empty file
  adsor <name>      - Upload file (reply with file/code)
  delfile <name>    - Delete file
  check <name>      - View file content

🚀 EXECUTION:
  run <file>        - Run file (classic method)
  pyrun <file>      - Interactive execution with auth
  trpy <command>    - Execute terminal command
  py <code>         - Execute Python code

📥 DOWNLOADS:
  gitdl <url> <name> - Download from git URL
  urldl <url> <name> - Download from direct URL

🔐 SESSION MANAGEMENT:
  sessions            - List all active sessions
  session info <id>   - Get session details
  session log <id>    - Get session output
  session delete <id> - Delete session

📊 MONITORING:
  runlist            - List running processes
  lastlag            - View last log
  pingserver         - Server status
  kill <name>        - Kill process
  kill all           - Kill all python processes
        """
        await event.reply(help_text)

    # Handle authentication responses (NEW)
    else:
        # Check if user is responding to an auth prompt
        for session_id in list(PENDING_AUTH.keys()):
            session = get_session(session_id)
            if session and session.get("status") == "awaiting_input":
                result_sid, result_msg = process_auth_response(session_id, text)
                
                if result_msg == "✅ Authentication Complete!":
                    del PENDING_AUTH[session_id]
                    exec_result = execute_pyrun(session_id, session.get("filename"))
                    await event.reply(f"{result_msg}\n\n{exec_result}")
                    return
                
                next_msg = get_next_auth_step(session_id)
                if next_msg:
                    await event.reply(next_msg)
                    return
                else:
                    await event.reply("✅ All inputs received!")
                    return

print("🚀 Ultimate Terminal Bot Ready - Enhanced Edition")
print(f"⏰ Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
client.run_until_disconnected()

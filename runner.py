import time
import paramiko
import random
import string
import json
import os
import re
import threading
import hashlib
import subprocess
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from pathlib import Path
from collections import defaultdict

# ===================== CONFIGURATION =====================
API_ID = 29042268
API_HASH = "54a7b377dd4a04a58108639febe2f443"
BOT_TOKEN = "8573030745:AAG6Lzn0La7mywT80q9lJ7yMIBKv2PIdgsg"

ADMIN_ID = 6508600903
ALLOWED_USERS = [6508600903]

SSH_HOST = "141.8.192.232"
SSH_PORT = 22
SSH_USER = "a1207253"
SSH_PASS = "bafaihviip"

REMOTE_FILES = "/a1207253/files"
REMOTE_LOGS = "/a1207253/logs"

SESSIONS_FILE = "sessions.json"
EXECUTION_HISTORY_FILE = "execution_history.json"
CONFIG_FILE = "runner_config.json"

# ===================== SESSION STATE MANAGEMENT =====================
ACTIVE_SESSIONS = {}
PENDING_AUTH = {}
EXECUTION_HISTORY = []
CONNECTION_POOL = {}
RATE_LIMITER = defaultdict(list)

class SessionManager:
    def __init__(self):
        self.sessions = {}
        self.load()
    
    def load(self):
        global ACTIVE_SESSIONS
        if os.path.exists(SESSIONS_FILE):
            try:
                with open(SESSIONS_FILE, 'r') as f:
                    self.sessions = json.load(f)
                    ACTIVE_SESSIONS = self.sessions
            except json.JSONDecodeError:
                self.sessions = {}
    
    def save(self):
        with open(SESSIONS_FILE, 'w') as f:
            json.dump(self.sessions, f, indent=2)
    
    def generate_id(self):
        unique = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        timestamp = str(int(time.time()))[-6:]
        return f"{unique}_{timestamp}"
    
    def create(self, filename, session_type="execution", requirements=None):
        session_id = self.generate_id()
        session_data = {
            "id": session_id,
            "filename": filename,
            "type": session_type,
            "created": datetime.now().isoformat(),
            "status": "initialized",
            "requirements": requirements or [],
            "responses": {},
            "execution_count": 0,
            "last_execution": None,
            "error_count": 0,
            "process_id": None,
            "duration_seconds": 0,
            "output_size_bytes": 0
        }
        self.sessions[session_id] = session_data
        self.save()
        return session_id
    
    def get(self, session_id):
        return self.sessions.get(session_id)
    
    def update(self, session_id, updates):
        if session_id in self.sessions:
            self.sessions[session_id].update(updates)
            self.save()
    
    def delete(self, session_id):
        if session_id in self.sessions:
            del self.sessions[session_id]
            self.save()
    
    def list_all(self):
        return self.sessions
    
    def cleanup_old_sessions(self, days=7):
        cutoff = datetime.now() - timedelta(days=days)
        to_delete = []
        for sid, data in self.sessions.items():
            created = datetime.fromisoformat(data.get("created", ""))
            if created < cutoff:
                to_delete.append(sid)
        for sid in to_delete:
            self.delete(sid)
        return len(to_delete)

class ExecutionHistory:
    def __init__(self):
        self.history = []
        self.load()
    
    def load(self):
        global EXECUTION_HISTORY
        if os.path.exists(EXECUTION_HISTORY_FILE):
            try:
                with open(EXECUTION_HISTORY_FILE, 'r') as f:
                    self.history = json.load(f)
                    EXECUTION_HISTORY = self.history
            except json.JSONDecodeError:
                self.history = []
    
    def save(self):
        with open(EXECUTION_HISTORY_FILE, 'w') as f:
            json.dump(self.history, f, indent=2)
    
    def record(self, filename, session_id, status, output_size, duration, error_msg=None):
        record = {
            "timestamp": datetime.now().isoformat(),
            "filename": filename,
            "session_id": session_id,
            "status": status,
            "output_size_bytes": output_size,
            "duration_seconds": duration,
            "error": error_msg
        }
        self.history.append(record)
        if len(self.history) > 1000:
            self.history = self.history[-500:]
        self.save()
    
    def get_stats(self):
        if not self.history:
            return {}
        total = len(self.history)
        successful = sum(1 for h in self.history if h.get("status") == "success")
        failed = sum(1 for h in self.history if h.get("status") == "failed")
        avg_duration = sum(h.get("duration_seconds", 0) for h in self.history) / total if total > 0 else 0
        return {
            "total_executions": total,
            "successful": successful,
            "failed": failed,
            "success_rate": f"{(successful/total*100):.1f}%" if total > 0 else "0%",
            "average_duration_seconds": f"{avg_duration:.2f}"
        }

session_manager = SessionManager()
execution_history = ExecutionHistory()

client = TelegramClient("terminal_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ===================== SSH CONNECTION MANAGEMENT =====================
class SSHConnectionManager:
    def __init__(self):
        self.connections = {}
        self.max_attempts = 3
        self.timeout = 20
    
    def get_connection(self, host_key=None):
        key = host_key or "default"
        if key in self.connections:
            try:
                self.connections[key].get_banner()
                return self.connections[key]
            except:
                del self.connections[key]
        return None
    
    def create_connection(self):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                hostname=SSH_HOST,
                port=SSH_PORT,
                username=SSH_USER,
                password=SSH_PASS,
                timeout=self.timeout,
                look_for_keys=False,
                allow_agent=False
            )
            return ssh
        except Exception as e:
            return None
    
    def execute(self, cmd, timeout=None):
        timeout = timeout or self.timeout
        attempts = 0
        
        while attempts < self.max_attempts:
            try:
                ssh = self.get_connection() or self.create_connection()
                if not ssh:
                    attempts += 1
                    time.sleep(1)
                    continue
                
                stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
                out = stdout.read().decode(errors='ignore')
                err = stderr.read().decode(errors='ignore')
                
                return {
                    "status": "success",
                    "output": out if out else err,
                    "error": err if err and not out else None,
                    "exit_code": stdout.channel.recv_exit_status()
                }
            except paramiko.SSHException as e:
                attempts += 1
                time.sleep(1)
            except Exception as e:
                return {
                    "status": "error",
                    "output": None,
                    "error": str(e),
                    "exit_code": -1
                }
        
        return {
            "status": "failed_max_attempts",
            "output": None,
            "error": f"Failed after {self.max_attempts} attempts",
            "exit_code": -1
        }

ssh_manager = SSHConnectionManager()

def ssh_exec(cmd, timeout=20):
    result = ssh_manager.execute(cmd, timeout)
    return result.get("output", "") or result.get("error", "")

# ===================== SECURITY & VALIDATION =====================
class SecurityValidator:
    DANGEROUS_COMMANDS = [
        "rm -rf /",
        "mkfs",
        "dd if=/dev/zero",
        "fork()",
        ":(){ :|:& };:",
    ]
    
    ALLOWED_FILE_EXTENSIONS = [".py", ".sh", ".js", ".txt", ".json", ".yml", ".yaml"]
    
    @staticmethod
    def validate_filename(filename):
        if ".." in filename or "/" in filename or "\\" in filename:
            return False, "Invalid filename characters"
        if not any(filename.endswith(ext) for ext in SecurityValidator.ALLOWED_FILE_EXTENSIONS):
            return False, f"File extension not allowed. Allowed: {', '.join(SecurityValidator.ALLOWED_FILE_EXTENSIONS)}"
        return True, None
    
    @staticmethod
    def validate_command(cmd):
        if not cmd or not isinstance(cmd, str):
            return False, "Invalid command format"
        for dangerous in SecurityValidator.DANGEROUS_COMMANDS:
            if dangerous and dangerous.lower() in cmd.lower():
                return False, f"Command contains dangerous pattern: {dangerous}"
        return True, None
    
    @staticmethod
    def is_authorized(user_id):
        return user_id in ALLOWED_USERS

security = SecurityValidator()

# ===================== RATE LIMITING =====================
class RateLimiter:
    def __init__(self, max_requests=10, window_seconds=60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)
    
    def is_allowed(self, user_id):
        now = time.time()
        self.requests[user_id] = [t for t in self.requests[user_id] if now - t < self.window_seconds]
        
        if len(self.requests[user_id]) >= self.max_requests:
            return False
        
        self.requests[user_id].append(now)
        return True
    
    def get_remaining(self, user_id):
        now = time.time()
        self.requests[user_id] = [t for t in self.requests[user_id] if now - t < self.window_seconds]
        return max(0, self.max_requests - len(self.requests[user_id]))

rate_limiter = RateLimiter(max_requests=20, window_seconds=60)

# ===================== FILE OPERATIONS ENHANCED =====================
class FileManager:
    def __init__(self, remote_base, remote_logs):
        self.remote_base = remote_base
        self.remote_logs = remote_logs
    
    def list_files(self):
        if not self.remote_base:
            return None, "Remote base path not configured"
        result = ssh_exec(f"ls -lh {self.remote_base} 2>/dev/null | tail -n +2")
        if not result or "error" in result.lower() or "cannot" in result.lower():
            return None, "Failed to list files"
        return result, None
    
    def get_file_content(self, filename):
        is_valid, error = security.validate_filename(filename)
        if not is_valid:
            return None, error
        
        if not filename:
            return None, "Filename cannot be empty"
        
        path = f"{self.remote_base}/{filename}"
        result = ssh_exec(f"cat {path} 2>/dev/null | head -c 100000")
        if not result:
            return None, "File not found or empty"
        return result, None
    
    def create_file(self, filename, content=""):
        is_valid, error = security.validate_filename(filename)
        if not is_valid:
            return None, error
        
        path = f"{self.remote_base}/{filename}"
        if content:
            cmd = f"cat > {path} << 'EOFMARKER'\n{content}\nEOFMARKER"
        else:
            cmd = f"touch {path}"
        
        ssh_exec(cmd)
        time.sleep(0.5)
        check = ssh_exec(f"ls {path} 2>/dev/null")
        if check and path in check:
            return True, None
        return None, "Failed to create file"
    
    def delete_file(self, filename):
        is_valid, error = security.validate_filename(filename)
        if not is_valid:
            return None, error
        
        path = f"{self.remote_base}/{filename}"
        ssh_exec(f"rm -f {path}")
        check = ssh_exec(f"ls {path} 2>/dev/null")
        if not check:
            return True, None
        return None, "Failed to delete file"
    
    def upload_file(self, local_path, remote_filename):
        is_valid, error = security.validate_filename(remote_filename)
        if not is_valid:
            return None, error
        
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(SSH_HOST, SSH_PORT, SSH_USER, SSH_PASS, timeout=20)
            sftp = paramiko.SFTPClient.from_transport(ssh.get_transport())
            sftp.put(local_path, f"{self.remote_base}/{remote_filename}")
            sftp.close()
            ssh.close()
            return True, None
        except Exception as e:
            return None, str(e)
    
    def get_log_content(self, session_id):
        log_path = f"{self.remote_logs}/{session_id}.log"
        result = ssh_exec(f"tail -n 200 {log_path} 2>/dev/null")
        return result, None
    
    def cleanup_old_logs(self, days=7):
        cmd = f"find {self.remote_logs} -type f -mtime +{days} -delete"
        ssh_exec(cmd)
        return True, None

file_manager = FileManager(REMOTE_FILES, REMOTE_LOGS)

# ===================== EXECUTION ENGINE =====================
class ExecutionEngine:
    def __init__(self):
        self.running_processes = {}
    
    def run_file(self, filename, args=None, session_id=None):
        is_valid, error = security.validate_filename(filename)
        if not is_valid:
            return {"status": "error", "message": error}
        
        path = f"{REMOTE_FILES}/{filename}"
        log_file = f"{REMOTE_LOGS}/{session_id or filename}.log"
        
        args_str = f" {' '.join(args)}" if args else ""
        
        methods = [
            f"nohup python3 {path}{args_str} > {log_file} 2>&1 & echo $!",
            f"screen -dmS {session_id or filename} python3 {path}{args_str} && echo 'launched'",
            f"bash {path}{args_str} > {log_file} 2>&1 & echo $!",
        ]
        
        start_time = time.time()
        for attempt, cmd in enumerate(methods, 1):
            try:
                result = ssh_exec(cmd, timeout=10)
                time.sleep(1.5)
                
                process_check = ssh_exec(f"ps aux | grep {session_id or filename} | grep -v grep")
                if filename in process_check or "launched" in result:
                    duration = time.time() - start_time
                    execution_history.record(filename, session_id or "direct", "running", 0, duration)
                    
                    return {
                        "status": "success",
                        "message": f"Script executed successfully (Method {attempt})",
                        "session_id": session_id or filename,
                        "log_file": log_file,
                        "process_output": result.strip()
                    }
            except Exception as e:
                continue
        
        duration = time.time() - start_time
        execution_history.record(filename, session_id or "direct", "failed", 0, duration, "All methods exhausted")
        
        return {
            "status": "error",
            "message": "Failed to execute script after all methods",
            "attempts": len(methods)
        }
    
    def get_process_status(self, filename):
        check = ssh_exec(f"ps aux | grep {filename} | grep -v grep")
        lines = [l.strip() for l in check.split('\n') if l.strip()]
        
        if not lines:
            return {"status": "stopped", "count": 0}
        
        return {
            "status": "running",
            "count": len(lines),
            "processes": lines
        }
    
    def stop_process(self, identifier):
        if not identifier:
            return False
        cmd = f"pkill -f {identifier}"
        ssh_exec(cmd)
        time.sleep(0.5)
        check = ssh_exec(f"ps aux | grep {identifier} | grep -v grep")
        return check and "killed" not in check.lower()

execution_engine = ExecutionEngine()

# ===================== INTERACTIVE SESSION ENGINE =====================
class InteractiveSessionEngine:
    def __init__(self, manager):
        self.manager = manager
    
    def create_with_requirements(self, filename, requirements):
        is_valid, error = security.validate_filename(filename)
        if not is_valid:
            return None, error
        
        session_id = self.manager.create(filename, "interactive", requirements)
        self.manager.update(session_id, {"status": "awaiting_input"})
        return session_id, None
    
    def get_requirement_prompt(self, session_id):
        session = self.manager.get(session_id)
        if not session:
            return None
        
        requirements = session.get("requirements", [])
        responses = session.get("responses", {})
        current_index = len(responses)
        
        if current_index >= len(requirements):
            return None
        
        req = requirements[current_index]
        return self._format_prompt(session_id, req, current_index + 1, len(requirements))
    
    def _format_prompt(self, session_id, requirement, step, total):
        prompts = {
            "phone_number": f"Phone number required (Step {step}/{total})\nSession: {session_id}\nFormat: +XXXXXXXXXXXX",
            "verification_code": f"Verification code required (Step {step}/{total})\nSession: {session_id}\nEnter the code you received",
            "password": f"Password required (Step {step}/{total})\nSession: {session_id}\nEnter your password",
            "username": f"Username required (Step {step}/{total})\nSession: {session_id}\nEnter username",
            "email": f"Email required (Step {step}/{total})\nSession: {session_id}\nEnter email address",
            "api_key": f"API Key required (Step {step}/{total})\nSession: {session_id}\nEnter your API key",
            "token": f"Token required (Step {step}/{total})\nSession: {session_id}\nEnter the token",
            "custom": f"Input required: {requirement} (Step {step}/{total})\nSession: {session_id}"
        }
        return prompts.get(requirement, prompts["custom"])
    
    def submit_response(self, session_id, response):
        session = self.manager.get(session_id)
        if not session:
            return None, "Session not found"
        
        requirements = session.get("requirements", [])
        responses = session.get("responses", {})
        current_index = len(responses)
        
        if current_index >= len(requirements):
            return None, "All requirements already submitted"
        
        req = requirements[current_index]
        responses[req] = response
        
        updated = {
            "responses": responses,
            "status": "complete" if current_index + 1 >= len(requirements) else "awaiting_input"
        }
        self.manager.update(session_id, updated)
        
        if updated["status"] == "complete":
            return session_id, "All requirements received"
        else:
            return session_id, None
    
    def execute_with_session(self, session_id, filename):
        session = self.manager.get(session_id)
        if not session or session.get("status") != "complete":
            return None, "Session not ready for execution"
        
        responses = session.get("responses", {})
        args = [str(v) for v in responses.values()]
        
        result = execution_engine.run_file(filename, args, session_id)
        
        if result["status"] == "success":
            self.manager.update(session_id, {
                "status": "executed",
                "execution_count": session.get("execution_count", 0) + 1,
                "last_execution": datetime.now().isoformat()
            })
        
        return result, None

interactive_engine = InteractiveSessionEngine(session_manager)

# ===================== DOWNLOAD MANAGER =====================
class DownloadManager:
    def download_from_git(self, git_url, filename):
        is_valid, error = security.validate_filename(filename)
        if not is_valid:
            return None, error
        
        try:
            cmd = f"cd {REMOTE_FILES} && wget -O {filename} '{git_url}' 2>&1"
            result = ssh_exec(cmd, timeout=30)
            if "saved" in result.lower() or "100%" in result or "Saving to" in result:
                return filename, None
            return None, f"Download may have failed: {result}"
        except Exception as e:
            return None, str(e)
    
    def download_from_url(self, url, filename):
        is_valid, error = security.validate_filename(filename)
        if not is_valid:
            return None, error
        
        try:
            cmd = f"cd {REMOTE_FILES} && curl -L -o {filename} '{url}' 2>&1 && echo 'Downloaded'"
            result = ssh_exec(cmd, timeout=30)
            return filename, None
        except Exception as e:
            return None, str(e)

download_manager = DownloadManager()

# ===================== MESSAGE FORMATTER =====================
class MessageFormatter:
    @staticmethod
    def format_error(message, details=None):
        text = f"[ERROR] {message}"
        if details:
            text += f"\nDetails: {details}"
        return text
    
    @staticmethod
    def format_success(message, details=None):
        text = f"[SUCCESS] {message}"
        if details:
            text += f"\n{details}"
        return text
    
    @staticmethod
    def format_info(title, content, max_length=3000):
        text = f"[{title}]\n{content}"
        if len(text) > max_length:
            text = text[:max_length] + f"\n... (truncated, total {len(text)} chars)"
        return text
    
    @staticmethod
    def format_table(headers, rows):
        if not rows:
            return "No data"
        
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(cell)))
        
        header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
        separator = "-" * len(header_line)
        
        lines = [separator, header_line, separator]
        for row in rows:
            lines.append(" | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)))
        lines.append(separator)
        
        return "\n".join(lines)

formatter = MessageFormatter()

# ===================== COMMAND PARSER =====================
class CommandParser:
    def __init__(self):
        self.commands = {}
    
    def register(self, name, handler, description=""):
        self.commands[name] = {"handler": handler, "description": description}
    
    def parse(self, text):
        if not text:
            return None, ""
        parts = text.split(maxsplit=1)
        if not parts or not parts[0]:
            return None, ""
        cmd = parts[0].lstrip('/').lower() if parts[0] else None
        args = parts[1] if len(parts) > 1 else ""
        return cmd, args
    
    def get_command(self, name):
        return self.commands.get(name)
    
    def list_commands(self):
        return self.commands

command_parser = CommandParser()

# ===================== COMMAND HANDLERS =====================
class CommandHandlers:
    @staticmethod
    async def cmd_filelist(event, args):
        result, error = file_manager.list_files()
        if error:
            return formatter.format_error(error)
        return formatter.format_info("FILE LIST", result)
    
    @staticmethod
    async def cmd_addfile(event, args):
        if not args or not args.strip():
            return formatter.format_error("Usage: addfile <filename>")
        
        filename = args.strip()
        result, error = file_manager.create_file(filename)
        if error:
            return formatter.format_error(error)
        return formatter.format_success(f"File created: {filename}")
    
    @staticmethod
    async def cmd_adsor(event, args):
        if not args or not args.strip():
            return formatter.format_error("Usage: adsor <filename>. Reply to file or code.")
        
        filename = args.strip()
        reply = await event.get_reply_message()
        if not reply:
            return formatter.format_error("Please reply to a file or code message")
        
        content = ""
        try:
            if reply.file:
                path = await reply.download_media()
                if path:
                    with open(path, 'r', errors='ignore') as f:
                        content = f.read()
            else:
                content = reply.text or ""
        except Exception as e:
            return formatter.format_error(f"Failed to read reply: {str(e)}")
        
        result, error = file_manager.create_file(filename, content)
        if error:
            return formatter.format_error(error)
        return formatter.format_success(f"File saved: {filename}")
    
    @staticmethod
    async def cmd_delfile(event, args):
        if not args or not args.strip():
            return formatter.format_error("Usage: delfile <filename>")
        
        filename = args.strip()
        result, error = file_manager.delete_file(filename)
        if error:
            return formatter.format_error(error)
        return formatter.format_success(f"File deleted: {filename}")
    
    @staticmethod
    async def cmd_check(event, args):
        if not args or not args.strip():
            return formatter.format_error("Usage: check <filename>")
        
        filename = args.strip()
        content, error = file_manager.get_file_content(filename)
        if error:
            return formatter.format_error(error)
        return formatter.format_info(f"Content: {filename}", content)
    
    @staticmethod
    async def cmd_run(event, args):
        if not args or not args.strip():
            return formatter.format_error("Usage: run <filename>")
        
        filename = args.strip()
        result = execution_engine.run_file(filename)
        
        if result["status"] == "error":
            return formatter.format_error(result["message"])
        
        return formatter.format_success(result["message"], 
            f"Session: {result.get('session_id')}\nLog: {result.get('log_file')}")
    
    @staticmethod
    async def cmd_interactive(event, args):
        if not args or not args.strip():
            return formatter.format_error("Usage: interactive <filename> <req1> <req2>...")
        
        parts = args.split()
        if not parts:
            return formatter.format_error("Please provide a filename")
        
        filename = parts[0]
        requirements = parts[1:] if len(parts) > 1 else ["parameter1", "parameter2"]
        
        session_id, error = interactive_engine.create_with_requirements(filename, requirements)
        if error:
            return formatter.format_error(error)
        
        PENDING_AUTH[session_id] = True
        prompt = interactive_engine.get_requirement_prompt(session_id)
        return formatter.format_info("Interactive Session Started", 
            f"Session ID: {session_id}\n\n{prompt}")
    
    @staticmethod
    async def cmd_gitdl(event, args):
        if not args or not args.strip():
            return formatter.format_error("Usage: gitdl <url> <filename>")
        
        parts = args.split(maxsplit=1)
        if not parts or not parts[0]:
            return formatter.format_error("URL is required")
        
        url = parts[0]
        filename = parts[1] if len(parts) > 1 else "downloaded_file.py"
        
        result, error = download_manager.download_from_git(url, filename)
        if error:
            return formatter.format_error(f"Download failed: {error}")
        return formatter.format_success(f"Downloaded: {result}")
    
    @staticmethod
    async def cmd_urldl(event, args):
        if not args or not args.strip():
            return formatter.format_error("Usage: urldl <url> <filename>")
        
        parts = args.split(maxsplit=1)
        if not parts or not parts[0]:
            return formatter.format_error("URL is required")
        
        url = parts[0]
        filename = parts[1] if len(parts) > 1 else "downloaded_file.py"
        
        result, error = download_manager.download_from_url(url, filename)
        if error:
            return formatter.format_error(f"Download failed: {error}")
        return formatter.format_success(f"Downloaded: {result}")
    
    @staticmethod
    async def cmd_sessions(event, args):
        sessions = session_manager.list_all()
        if not sessions:
            return formatter.format_info("Active Sessions", "No active sessions")
        
        rows = []
        for sid, data in sessions.items():
            rows.append([
                sid[:8],
                data.get("filename", "?"),
                data.get("status", "?"),
                data.get("type", "?")
            ])
        
        table = formatter.format_table(["ID", "File", "Status", "Type"], rows)
        return formatter.format_info("Active Sessions", table)
    
    @staticmethod
    async def cmd_session_info(event, args):
        if not args or not args.strip():
            return formatter.format_error("Usage: session info <session_id>")
        
        session_id = args.strip()
        if not session_id:
            return formatter.format_error("Session ID is required")
        
        session = session_manager.get(session_id)
        
        if not session:
            return formatter.format_error(f"Session not found: {session_id}")
        
        info = f"""
ID: {session.get('id')}
File: {session.get('filename')}
Type: {session.get('type')}
Status: {session.get('status')}
Created: {session.get('created')}
Executions: {session.get('execution_count', 0)}
Errors: {session.get('error_count', 0)}
Duration: {session.get('duration_seconds', 0):.1f}s
Requirements: {', '.join(session.get('requirements', []))}
Responses Received: {len(session.get('responses', {}))}
        """
        return formatter.format_info("Session Info", info.strip())
    
    @staticmethod
    async def cmd_session_log(event, args):
        if not args or not args.strip():
            return formatter.format_error("Usage: session log <session_id>")
        
        session_id = args.strip()
        if not session_id:
            return formatter.format_error("Session ID is required")
        
        log, error = file_manager.get_log_content(session_id)
        
        if error or not log:
            return formatter.format_error("No log found for session")
        
        return formatter.format_info(f"Log: {session_id}", log)
    
    @staticmethod
    async def cmd_session_delete(event, args):
        if not args or not args.strip():
            return formatter.format_error("Usage: session delete <session_id>")
        
        session_id = args.strip()
        if not session_id:
            return formatter.format_error("Session ID is required")
        
        session_manager.delete(session_id)
        if session_id in PENDING_AUTH:
            del PENDING_AUTH[session_id]
        
        return formatter.format_success(f"Session deleted: {session_id}")
    
    @staticmethod
    async def cmd_runlist(event, args):
        check = ssh_exec("ps aux | grep -E 'python|node|bash' | grep -v grep")
        if not check:
            return formatter.format_info("Running Processes", "No processes running")
        
        lines = [l.strip() for l in check.split('\n') if l.strip()]
        return formatter.format_info("Running Processes", f"Total: {len(lines)}\n\n{check}")
    
    @staticmethod
    async def cmd_kill(event, args):
        if not args or not args.strip():
            return formatter.format_error("Usage: kill <identifier>")
        
        identifier = args.strip()
        if not identifier:
            return formatter.format_error("Identifier is required")
        
        if identifier.lower() == "all":
            ssh_exec("pkill -f -9 'python3|node|bash'")
            return formatter.format_success("All processes terminated")
        
        ssh_exec(f"pkill -f {identifier}")
        time.sleep(0.5)
        return formatter.format_success(f"Kill signal sent to: {identifier}")
    
    @staticmethod
    async def cmd_server_status(event, args):
        uptime = ssh_exec("uptime")
        memory = ssh_exec("free -h | grep Mem")
        disk = ssh_exec("df -h / | tail -1")
        
        info = f"""
UPTIME:
{uptime}

MEMORY:
{memory}

DISK:
{disk}
        """
        return formatter.format_info("Server Status", info.strip())
    
    @staticmethod
    async def cmd_stats(event, args):
        stats = execution_history.get_stats()
        if not stats:
            return formatter.format_info("Statistics", "No execution history")
        
        info = f"""
Total Executions: {stats.get('total_executions', 0)}
Successful: {stats.get('successful', 0)}
Failed: {stats.get('failed', 0)}
Success Rate: {stats.get('success_rate', '0%')}
Average Duration: {stats.get('average_duration_seconds', '0')}s
Active Sessions: {len(session_manager.list_all())}
        """
        return formatter.format_info("Execution Statistics", info.strip())
    
    @staticmethod
    async def cmd_start(event, args):
        welcome = """
✅ TERMINAL RUNNER BOT - STARTED

This bot allows you to manage files and execute scripts on a remote server.

📋 Quick Start:
/help - View all available commands
/filelist - List all remote files
/run <filename> - Execute a script
/sessions - View active sessions

🔐 Status: Connected and Ready
        """
        return welcome.strip()
    
    @staticmethod
    async def cmd_help(event, args):
        help_text = """
COMMAND REFERENCE:

FILE MANAGEMENT:
  filelist              List all files
  addfile <name>        Create empty file
  adsor <name>          Upload file (reply to message)
  delfile <name>        Delete file
  check <name>          View file content

EXECUTION:
  run <file>            Execute file directly
  interactive <file>    Interactive execution with parameters
  
DOWNLOADS:
  gitdl <url> <name>    Download from git
  urldl <url> <name>    Download from URL

SESSION MANAGEMENT:
  sessions              List active sessions
  session info <id>     Get session details
  session log <id>      View session log
  session delete <id>   Delete session

MONITORING:
  runlist               List running processes
  server_status         Show server info
  stats                 Show execution statistics
  kill <name>           Kill process
  kill all              Kill all processes

UTILITIES:
  help                  Show this help
        """
        return formatter.format_info("Help", help_text)

register = command_parser.register
register("start", CommandHandlers.cmd_start)
register("filelist", CommandHandlers.cmd_filelist)
register("addfile", CommandHandlers.cmd_addfile)
register("adsor", CommandHandlers.cmd_adsor)
register("delfile", CommandHandlers.cmd_delfile)
register("check", CommandHandlers.cmd_check)
register("run", CommandHandlers.cmd_run)
register("interactive", CommandHandlers.cmd_interactive)
register("gitdl", CommandHandlers.cmd_gitdl)
register("urldl", CommandHandlers.cmd_urldl)
register("sessions", CommandHandlers.cmd_sessions)
register("session", CommandHandlers.cmd_session_info)
register("runlist", CommandHandlers.cmd_runlist)
register("kill", CommandHandlers.cmd_kill)
register("server_status", CommandHandlers.cmd_server_status)
register("stats", CommandHandlers.cmd_stats)
register("help", CommandHandlers.cmd_help)

# ===================== EVENT HANDLER =====================
@client.on(events.NewMessage)
async def message_handler(event):
    if not security.is_authorized(event.sender_id):
        return
    
    if not rate_limiter.is_allowed(event.sender_id):
        await event.reply("[RATE_LIMITED] Too many requests. Try again later.")
        return
    
    text = event.raw_text.strip()
    
    if not text:
        return
    
    try:
        cmd, args = command_parser.parse(text)
        
        if not cmd:
            return
        
        # Handle interactive session responses
        if cmd not in command_parser.commands:
            for session_id in list(PENDING_AUTH.keys()):
                session = session_manager.get(session_id)
                if session and session.get("status") == "awaiting_input":
                    result_sid, result_msg = interactive_engine.submit_response(session_id, text)
                    
                    if result_msg == "All requirements received":
                        exec_result, _ = interactive_engine.execute_with_session(session_id, session.get("filename"))
                        if exec_result:
                            await event.reply(formatter.format_success(
                                "Execution Complete",
                                f"Session: {session_id}\nMessage: {exec_result.get('message', '')}"
                            ))
                        if session_id in PENDING_AUTH:
                            del PENDING_AUTH[session_id]
                        return
                    
                    next_prompt = interactive_engine.get_requirement_prompt(session_id)
                    if next_prompt:
                        await event.reply(next_prompt)
                        return
            return
        
        # Execute command
        handler = command_parser.get_command(cmd)
        if handler:
            try:
                response = await handler["handler"](event, args)
                if response:
                    await event.reply(response)
            except Exception as e:
                error_detail = str(e) if str(e) else "Unknown error"
                await event.reply(formatter.format_error("Command execution failed", error_detail))
    except Exception as e:
        await event.reply(formatter.format_error("Message processing failed", str(e)))

# ===================== STARTUP =====================
print("[SYSTEM] Terminal Runner Bot Initialization")
print(f"[TIME] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("[STATUS] Loading sessions and configuration")
print(f"[SESSIONS] {len(session_manager.list_all())} active sessions")
print(f"[HISTORY] {len(execution_history.history)} execution records")
print("[READY] Bot is running and waiting for commands")
print("-" * 50)

client.run_until_disconnected()

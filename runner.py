import time
import paramiko
from telethon import TelegramClient, events

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

# ===================== COMMANDS =====================
@client.on(events.NewMessage)
async def handler(event):
    if not is_admin(event):
        return

    text = event.raw_text.strip()

    # filelist
    if text == "filelist":
        out = ssh_exec(f"ls {REMOTE_FILES}")
        await event.reply(out)

    # runlist
    elif text == "runlist":
        out = ssh_exec("ps aux | grep python3 | grep -v grep")
        await event.reply(out[:4000])

    # lastlag
    elif text == "lastlag":
        cmd = f"ls -t {REMOTE_LOGS} | head -1"
        last = ssh_exec(cmd).strip()
        if not last:
            await event.reply("NO LOG")
            return
        log = ssh_exec(f"tail -n 50 {REMOTE_LOGS}/{last}")
        await event.reply(log)

    # addfile name.py
    elif text.startswith("addfile"):
        name = text.split(" ", 1)[1]
        ssh_exec(f"touch {REMOTE_FILES}/{name}")
        await event.reply("FILE CREATED")

    # adsor name.py
    elif text.startswith("adsor"):
        name = text.split(" ", 1)[1]
        reply = await event.get_reply_message()
        if not reply:
            await event.reply("REPLY TO CODE OR FILE")
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

        await event.reply("SAVED")

    # delfile name.py
    elif text.startswith("delfile"):
        name = text.split(" ", 1)[1]
        ssh_exec(f"rm -f {REMOTE_FILES}/{name}")
        await event.reply("DELETED")

    # check name.py
    elif text.startswith("check"):
        name = text.split(" ", 1)[1]
        out = ssh_exec(f"cat {REMOTE_FILES}/{name}")
        await event.reply(out[:4000])

    # run name.py
    elif text.startswith("run "):
        name = text.split(" ", 1)[1]
        out = run_remote(name)
        await event.reply(out)

    # kill all
    elif text == "kill all":
        ssh_exec("pkill -f python3")
        await event.reply("ALL KILLED")

    # kill name.py
    elif text.startswith("kill"):
        name = text.split(" ", 1)[1]
        ssh_exec(f"pkill -f {name}")
        await event.reply("KILLED")

    # trpy pip install ...
    elif text.startswith("trpy"):
        cmd = text.replace("trpy", "", 1).strip()
        out = ssh_exec(cmd)
        await event.reply(out[:4000])

    # py code
    elif text.startswith("py"):
        code = text.replace("py", "", 1)
        try:
            exec_result = ssh_exec(f"python3 - << 'EOF'\n{code}\nEOF")
            await event.reply(exec_result[:4000])
        except Exception as e:
            await event.reply(str(e))

    # pingserver
    elif text == "pingserver":
        out = ssh_exec("uptime && free -h && df -h /")
        await event.reply(out)

print("Ultimate Terminal Bot Ready")
client.run_until_disconnected()
          

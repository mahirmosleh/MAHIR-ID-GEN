# -*- coding: utf-8 -*-
# ======================================================================
#   MAHIR ID GENERATOR — Async + Login + Role-based Access
# ======================================================================

import asyncio
import aiohttp
import json
import hmac
import hashlib
import time
import random
import ipaddress
import os
import sys
import uuid
import ssl
import string
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from datetime import datetime
from colorama import init, Fore, Style
from aiohttp import web

init(autoreset=True)


# ======================================================================
# CONSTANTS
# ======================================================================
AES_KEY = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
AES_IV  = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])

GAME_VERSION    = "2.132.8"
RELEASE_VERSION = "OB55"

WEB_HOST = "0.0.0.0"
WEB_PORT = 8080

# ---- Login credentials (change here) ----
USER_CREDENTIALS  = {"username": "MAHIR-ID-GEN",  "password": "MAHIR.XO.JE"}
OWNER_CREDENTIALS = {"username": "OWNER-MAHIR-BRO", "password": "MAHIR-JOD"}

# ---- Defaults ----
DEFAULT_NICKNAME = "MAHIR"
DEFAULT_BIO = "[C][B]WEB : MAHIR.XO.JE [FFD700]TG : MAHIR0208"

GGRE_BLOB = bytes.fromhex(
    "47475245010101006d020000b260ee08e1f86b4c57f9c70f86bba26ed5d1436bcf52e142db3249d905eded757764991ca31a8373cdd26eab91b80f3f1f6f262f4f10b895d7b6937ddba30a27197453890e9da49373f736c679b8254e2f8e1623e91084a5fdd5374fe478ff99e010834553fddeb0bec4018d142e49df9bb236675b67e852f92a43586f7a7d4d0d7a197a1d4da32714dab4d069ad53214e2c33b3877420a12459738c4c619cbd815fa878bbd104776bb3e1ac7818d5397b04a666ac57f682763ff2df31bc2f846ddc7904f3dce1bda0c4b01f9698e9166f98c84f92640abe3f6317834a42e5c12573b46842c1a6ea8fe6ca9c006dca48a2087e1f983dfb5692771e4a0b15b337ad669b1d08b40862b176bace5331b49a767375b1a8469012aa70a67b55fe71b72478201d0b3ac7269c064c960361e92ee7ba8a42cc6b582bf9b965fb388fa9172ad44c4b073ac23c02080a6bcd106b691ffdf4c7cf71e42f2063fcf196e9bddc5e85be1fe5048eb1b31b460efbb46d76195eef9904c4cba326f2e17ff51fec17dd965aa06dadd4ab07d6966e4a7c38e8afd66dfde56c872bb87516a8f7313c797e4d80e5ad4a5f7afad95c1e0449254adae052e71a3fb98399f93ab30848e0d23252dd45e6fd41bc5fa7303dfb846a8fd713a0032a0b0ae96dfba1bbe41d20abd8099e2cb7fccc329d25bd153029139ef05d090a5093ea557693c0a8d491395b8a23ca844b3887dd5dfc29ac06f4b9be87883a793211b973465e2644c4f5de02b8ab01571401203fc2740423826858cc6da0194c195d27aac4ec4b9d23d506c1501d06440aca3fc180926d75d4a004d3dff21eb4ea1e8c86e6c9627248eff953e1d192d5c8efc006a7e512388ef2ebdb72ee3ad42d719f28e8f994e12ebf4c79f2ffe3abd7408ccd2236a7b89b2606247a732c10c4"
)


# ======================================================================
# GLOBAL STATE
# ======================================================================
HTTP_SEM       = None
HTTP_SESSION   = None
HTTP_CONCURRENCY = 30
CONNECTOR_LIMIT          = 30
CONNECTOR_LIMIT_PER_HOST = 30

DYNAMIC_SERVER_URL = "https://loginbp.ppmainecoonghj.com/"
CURRENT_OB = RELEASE_VERSION

Hr = {
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded",
    "ReleaseVersion": CURRENT_OB,
    "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
    "X-GA": "v1 1",
    "X-GA-SV": str(int(time.time())),
    "X-Unity-Version": "2018.4.12f1",
}

# ---- Session state ----
sessions = {}                       # token -> {"username", "role"}
SESSION_COOKIE = "mahir_sid"

# ---- Generation state ----
accounts_list   = []
success_count   = 0
fail_count      = 0
accounts_lock   = asyncio.Lock()
success_lock    = asyncio.Lock()
fail_lock       = asyncio.Lock()

GENERATION_RUNNING = False
STOP_EVENT         = None
WORKER_TASKS       = []

# ---- Per-session values (set on /api/start) ----
SESSION_NICKNAME = DEFAULT_NICKNAME
SESSION_BIO      = DEFAULT_BIO
SESSION_FILE     = ""               # MAHIR_ID_GEN_XXXXXX.json

# ---- Logs ----
log_buffer = []
LOG_MAX = 200


def log_msg(msg, level="info"):
    entry = {"t": time.strftime("%H:%M:%S"), "msg": msg, "level": level}
    log_buffer.append(entry)
    if len(log_buffer) > LOG_MAX:
        log_buffer.pop(0)
    color = {"success": Fore.GREEN, "error": Fore.RED,
             "warning": Fore.YELLOW, "info": Fore.CYAN}.get(level, Fore.WHITE)
    print(f"{color}[{entry['t']}] {msg}{Style.RESET_ALL}")


# ======================================================================
# LOGIN / SESSION HELPERS
# ======================================================================
def check_credentials(username, password, role):
    """Return True if username/password matches the credentials for that role."""
    if role == "user":
        return (username == USER_CREDENTIALS["username"]
                and password == USER_CREDENTIALS["password"])
    if role == "owner":
        return (username == OWNER_CREDENTIALS["username"]
                and password == OWNER_CREDENTIALS["password"])
    return False


def get_current_session(request):
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    return sessions.get(sid)


def make_session(username, role):
    sid = uuid.uuid4().hex
    sessions[sid] = {"username": username, "role": role, "created": time.time()}
    return sid


def new_session_filename():
    rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"MAHIR_ID_GEN_{rand}.json"


# ======================================================================
# IP ROTATOR
# ======================================================================
class IPRotator:
    REGION_IP_CIDRS = {
        "BD": ["27.147.128.0/17", "37.111.192.0/19", "49.0.32.0/20",
               "59.152.96.0/20", "114.130.0.0/17", "115.127.0.0/17",
               "119.30.32.0/20", "123.49.0.0/18", "103.220.220.0/22",
               "103.108.140.0/22", "103.242.20.0/22"],
    }
    _cache = {}

    @classmethod
    def get_random_ip(cls, region="BD"):
        region = region.upper()
        if region not in cls._cache:
            cidrs = cls.REGION_IP_CIDRS.get(region, ["27.0.0.0/8"])
            hosts = []
            for cidr in cidrs:
                try:
                    net = ipaddress.ip_network(cidr, strict=False)
                    for _ in range(3):
                        ip_int = int(net.network_address) + random.randint(
                            1, 2 ** (32 - net.prefixlen) - 2
                        )
                        hosts.append(str(ipaddress.IPv4Address(ip_int)))
                except Exception:
                    continue
            cls._cache[region] = hosts if hosts else [
                f"{random.randint(1,255)}.{random.randint(0,255)}."
                f"{random.randint(0,255)}.{random.randint(0,255)}"
            ]
        return random.choice(cls._cache[region])

    @classmethod
    def get_ip_headers(cls, region="BD"):
        ip = cls.get_random_ip(region)
        return {"X-Forwarded-For": ip, "X-Real-IP": ip, "Client-IP": ip}


# ======================================================================
# NAME / BIO
# ======================================================================
def make_account_name():
    """Uses SESSION_NICKNAME prefix + superscript suffix."""
    SUPERSCRIPTS = ['⁰','¹','²','³','⁴','⁵','⁶','⁷','⁸','⁹',
                    '₀','₁','₂','₃','₄','₅','₆','₇','₈','₉']
    prefix = SESSION_NICKNAME or DEFAULT_NICKNAME
    suffix = ''.join(random.choice(SUPERSCRIPTS) for _ in range(4))
    return f"{prefix}{suffix}"


# ======================================================================
# PROTOBUF HELPERS
# ======================================================================
def encode_varint(value):
    result = []
    if value < 0:
        value &= (1 << 64) - 1
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        result.append(byte)
        if not value:
            break
    return bytes(result)


def create_proto(fields):
    packet = bytearray()
    for field, value in fields.items():
        if isinstance(value, dict):
            nested = create_proto(value)
            packet.extend(encode_varint((field << 3) | 2))
            packet.extend(encode_varint(len(nested)))
            packet.extend(nested)
        elif isinstance(value, bool):
            packet.extend(encode_varint((field << 3) | 0))
            packet.extend(encode_varint(1 if value else 0))
        elif isinstance(value, int):
            packet.extend(encode_varint((field << 3) | 0))
            packet.extend(encode_varint(value))
        elif isinstance(value, str):
            encoded = value.encode('utf-8')
            packet.extend(encode_varint((field << 3) | 2))
            packet.extend(encode_varint(len(encoded)))
            packet.extend(encoded)
        elif isinstance(value, bytes):
            packet.extend(encode_varint((field << 3) | 2))
            packet.extend(encode_varint(len(value)))
            packet.extend(value)
    return bytes(packet)


def encrypt_aes(hex_data: str) -> str:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return cipher.encrypt(pad(bytes.fromhex(hex_data), AES.block_size)).hex()


def decode_varint(data, offset):
    result, shift = 0, 0
    while offset < len(data):
        b = data[offset]
        result |= (b & 0x7F) << shift
        offset += 1
        if not (b & 0x80):
            return result, offset
        shift += 7
    return None, offset


def decode_protobuf(data):
    result, offset = {}, 0
    while offset < len(data):
        header, offset = decode_varint(data, offset)
        if header is None:
            break
        fno, wt = header >> 3, header & 0x7
        if wt == 0:
            v, offset = decode_varint(data, offset)
            if v is not None:
                result[fno] = v
        elif wt == 2:
            ln, offset = decode_varint(data, offset)
            if ln is None:
                break
            val = data[offset:offset + ln]
            offset += ln
            try:    result[fno] = val.decode('utf-8')
            except: result[fno] = val.hex()
        elif wt == 1: offset += 8
        elif wt == 3: offset += 4
        else: break
    return result


# ======================================================================
# HTTP WRAPPER
# ======================================================================
async def http_post(url, headers, data, timeout=20):
    global HTTP_SEM, HTTP_SESSION
    async with HTTP_SEM:
        for attempt in range(3):
            try:
                async with HTTP_SESSION.post(
                    url, headers=headers, data=data,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    ssl=False
                ) as resp:
                    body = await resp.read()
                    return resp.status, body
            except (aiohttp.ClientConnectorError,
                    aiohttp.ClientOSError,
                    aiohttp.ServerDisconnectedError,
                    asyncio.TimeoutError):
                if attempt == 2: raise
                await asyncio.sleep(0.3 * (2 ** attempt))
            except Exception:
                if attempt == 2: raise
                await asyncio.sleep(0.3 * (2 ** attempt))
        return 0, b""


# ======================================================================
# PIPELINE
# ======================================================================
async def register_account(password, region="BD"):
    url = "https://ffmconnect.ppmainecoonghj.com/api/v2/oauth/guest:register"
    ip_headers = IPRotator.get_ip_headers(region)
    api_key_str = "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3"
    payload_json = {"app_id": 100067, "client_type": 2, "password": password, "source": 2}
    payload = json.dumps(payload_json, separators=(',', ':'))
    signature = hmac.new(api_key_str.encode(), payload.encode(), hashlib.sha256).hexdigest()

    headers = {
        "User-Agent": "GarenaMSDK/4.0.42(SM-E135F ;Android 14;en;GB;app 2.130.1 2019118332;)",
        "Authorization": f"Signature {signature}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "Host": "ffmconnect.ppmainecoonghj.com",
        **ip_headers
    }
    try:
        status, body = await http_post(url, headers, payload, timeout=20)
        if status == 200:
            jd = json.loads(body.decode('utf-8', errors='ignore'))
            if jd.get("code") == 0 and "data" in jd:
                return jd["data"]["uid"], password
        return None, None
    except Exception:
        return None, None


async def get_access_token(uid, password, region="BD"):
    url = "https://100067.connect.garena.com/oauth/guest/token/grant"
    ip_headers = IPRotator.get_ip_headers(region)
    headers = {
        "Host": "100067.connect.garena.com",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; SM-G960F Build/PIE)",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "gzip, deflate",
        **ip_headers
    }
    data = {
        "uid": uid, "password": password,
        "response_type": "token", "client_type": "2",
        "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_id": "100067"
    }
    try:
        status, body = await http_post(url, headers, data, timeout=20)
        if status == 200:
            jd = json.loads(body.decode('utf-8', errors='ignore'))
            at = jd.get("access_token"); oi = jd.get("open_id"); pf = jd.get("platform")
            return at, oi, (int(pf) if pf else 4)
        return None, None, None
    except Exception:
        return None, None, None


async def major_register(access_token, open_id, name, LANG='en', region="BD"):
    url = "https://loginbp.ggpolarbear.com/MajorRegister"
    ip_headers = IPRotator.get_ip_headers(region)
    keystream = [
        0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,
        0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30,0x31,
        0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30
    ]
    encoded_open_id = ""
    for i, ch in enumerate(open_id):
        encoded_open_id += chr(ord(ch) ^ keystream[i % len(keystream)])
    field14 = encoded_open_id.encode('latin1')

    payload_fields = {
        1: name, 2: access_token, 3: open_id,
        5: 102000007, 6: 4, 7: 1, 13: 1,
        14: field14, 15: LANG,
        16: 2, 20: GAME_VERSION, 21: 1, 22: GGRE_BLOB,
    }
    proto_hex = create_proto(payload_fields).hex()
    payload = bytes.fromhex(encrypt_aes(proto_hex))

    headers = {
        "Accept": "*/*", "Authorization": "Bearer ",
        "Content-Type": "application/x-www-form-urlencoded",
        "ReleaseVersion": RELEASE_VERSION,
        "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        "X-GA": "v1 1", "X-GA-SV": str(int(time.time())),
        "X-Unity-Version": "2018.4.12f1",
        **ip_headers
    }
    try:
        status, content = await http_post(url, headers, payload, timeout=20)
        if len(content) > 64:
            decoded = decode_protobuf(content[64:])
            if not decoded or 3 not in decoded:
                decoded = decode_protobuf(content)
        else:
            decoded = decode_protobuf(content)
        return decoded
    except Exception:
        return {}


async def build_majorlogin_payload(open_id, access_token, version):
    fields = {
        3: str(datetime.now())[:-7], 4: "free fire", 5: 1, 7: str(version),
        8: "Android OS 11 / API-30 (RP1A.200720.011/230921V810)",
        9: "Handheld", 10: "Grameenphone", 11: "WIFI",
        12: 1708, 13: 750, 14: "480",
        15: "ARM64 FP ASIMD AES | 2000 | 8",
        16: 5767, 17: "Mali-G52 MC2",
        18: "OpenGL ES 3.2 v1.r26p0-01eac0.f143e3f9482527bbad36b3ec27f93e59",
        19: "Google|3f10d414-be33-4ac3-b9fc-fcbf47c183b5",
        20: "103.200.36.134", 21: "en", 22: str(open_id), 23: "4", 24: "Handheld",
        25: "INFINIX MOBILITY LIMITED Infinix X6812", 26: "BD",
        29: str(access_token), 30: 1, 41: "Grameenphone", 42: "WIFI",
        57: "7428b253defc164018c604a1ebbfebdf",
        60: 110962, 61: 80611, 62: 1051, 64: 80829,
        65: 110962, 66: 80829, 67: 110962, 73: 2,
        74: "/data/app/~~MxBbX9YA6AkFscre_RExgw==/com.dts.freefireth-hLOkTeh1Q46L_oLV4UXQTg==/lib/arm64",
        76: 1,
        77: "b8e0cd5e295eee42f5860d3c86e483dd|/data/app/~~MxBbX9YA6AkFscre_RExgw==/com.dts.freefireth-hLOkTeh1Q46L_oLV4UXQTg==/base.apk",
        78: 3, 79: 2, 81: "64", 83: "2019121229", 85: 3,
        86: "OpenGLES2", 87: 4095, 88: 4,
        91: {9: 65}, 92: 10508, 93: "android",
        94: "KqsHT76RdsVKvnpkirzc2FQs3eu0OZChfZxMTZn+Rjv06Ri2qeOQkyPcdk5JceWKmXhOFFUPuNy9S8esTr37yCT5piY32iUcehVw0bL4F4lzAmyD",
        95: 111207,
        96: '{"cur_rate":[60,90],"support_etc2":false}',
        97: 1, 98: 1, 99: "4", 100: "4",
        102: "B\\FFP[[\tf", 103: 1, 104: 28754, 105: 1,
        106: "https://dl.ak.freefiremobile.com/live/ABHotUpdates/|https://core-ak.freefiremobile.com/live/ABHotUpdates/|a4332cb1c1a84e51dd77441e4856ed5a",
        107: "1.477aa00e98bf924c"
    }
    return bytes.fromhex(encrypt_aes(create_proto(fields).hex()))


async def send_majorlogin(payload):
    global DYNAMIC_SERVER_URL
    base = DYNAMIC_SERVER_URL.rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    url = f"{base}/MajorLogin"
    Hr["X-GA-SV"] = str(int(time.time()))
    Hr["ReleaseVersion"] = CURRENT_OB
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=payload, headers=Hr, ssl=ssl_context) as resp:
                if resp.status != 200: return None
                raw = await resp.read()
                return raw[64:] if len(raw) > 64 else raw
    except Exception:
        return None


async def get_login_data(server_url, jwt_token, payload, region="BD"):
    url = f"{server_url.rstrip('/')}/GetLoginData"
    ip_headers = IPRotator.get_ip_headers(region)
    headers = {
        "Accept": "*/*", "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "ReleaseVersion": RELEASE_VERSION,
        "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        "X-GA": "v1 1", "X-GA-SV": str(int(time.time())),
        "X-Unity-Version": "2018.4.12f1",
        **ip_headers
    }
    try:
        status, content = await http_post(url, headers, payload, timeout=20)
        return decode_protobuf(content)
    except Exception:
        return {}


def create_bio_payload(bio_text):
    if not bio_text: bio_text = "hello"
    if len(bio_text) > 300: bio_text = bio_text[:300]
    fields = {5: "", 6: "", 8: bio_text, 9: 1, 11: "", 12: "", 16: ""}
    return bytes.fromhex(encrypt_aes(create_proto(fields).hex()))


async def change_bio(jwt_token, bio_text, region="BD"):
    url = "https://clientbp.ggpolarbear.com/UpdateSocialBasicInfo"
    headers = {
        "Accept": "*/*", "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "ReleaseVersion": RELEASE_VERSION,
        "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        "X-GA": "v1 1", "X-GA-SV": str(int(time.time())),
        "X-Unity-Version": "2018.4.12f1",
    }
    try:
        payload = create_bio_payload(bio_text)
        status, _ = await http_post(url, headers, payload, timeout=10)
        return status == 200
    except Exception:
        return False


# ======================================================================
# SAVE / LOAD
# ======================================================================
async def save_session_json():
    global SESSION_FILE
    if not SESSION_FILE:
        SESSION_FILE = new_session_filename()
    async with accounts_lock:
        try:
            tmp = SESSION_FILE + ".tmp"
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(accounts_list, f, indent=2, ensure_ascii=False)
            os.replace(tmp, SESSION_FILE)
        except Exception as e:
            log_msg(f"Save error: {e}", "error")


def account_exists(uid):
    for acc in accounts_list:
        if str(acc.get('uid')) == str(uid) or str(acc.get('account_id')) == str(uid):
            return True
    return False


async def get_next_count():
    global success_count
    async with success_lock:
        success_count += 1
        return success_count


async def bump_fail():
    global fail_count
    async with fail_lock:
        fail_count += 1


# ======================================================================
# ACCOUNT CREATION
# ======================================================================
async def create_full_account(thread_id, region="BD", max_retries=3):
    for attempt in range(max_retries):
        if STOP_EVENT.is_set():
            return None
        try:
            password = f"MAHIR_{random.randint(1, 9999)}"
            name = make_account_name()

            register_uid, password = await register_account(password, region)
            if not register_uid:
                await asyncio.sleep(random.uniform(0.3, 1.0))
                continue

            access_token, open_id, platform_type = await get_access_token(register_uid, password, region)
            if not access_token:
                await asyncio.sleep(0.4)
                continue

            reg_response = await major_register(access_token, open_id, name, region=region)
            if 3 not in reg_response:
                continue

            account_id = reg_response[3]
            payload = await build_majorlogin_payload(open_id, access_token, GAME_VERSION)
            login_raw = await send_majorlogin(payload)
            if not login_raw:
                continue

            login_response = decode_protobuf(login_raw)
            jwt_token = login_response.get(8)
            if not jwt_token:
                continue

            server_url = login_response.get(10) or DYNAMIC_SERVER_URL
            await get_login_data(server_url, jwt_token, payload, region)

            if account_exists(register_uid) or account_exists(account_id):
                return None

            bio_success = await change_bio(jwt_token, SESSION_BIO)
            count = await get_next_count()

            account = {
                'uid': register_uid,
                'password': password,
                'name': name,
                'account_id': account_id,
                'region': region,
                'jwt_token': jwt_token,
                'bio': SESSION_BIO,
                'bio_updated': bio_success,
                'created_at': datetime.now().isoformat()
            }
            async with accounts_lock:
                accounts_list.append(account)

            await save_session_json()

            log_msg(f"✅ [T{thread_id}] #{count} UID: {register_uid} | ID: {account_id} | {name}", "success")
            return account

        except (aiohttp.ClientOSError, aiohttp.ClientConnectorError, OSError) as e:
            err = str(e)
            if "Cannot assign requested address" in err or "Errno 99" in err:
                await asyncio.sleep(min(2.0 * (attempt + 1), 8.0))
            else:
                await asyncio.sleep(0.5)
            continue
        except Exception as e:
            log_msg(f"❌ [T{thread_id}] {e}", "error")
            await asyncio.sleep(0.3)
            continue

    await bump_fail()
    return None


async def worker(thread_id, region="BD"):
    while not STOP_EVENT.is_set():
        try:
            await create_full_account(thread_id, region)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log_msg(f"⚠️ [T{thread_id}] {e}", "warning")
            await asyncio.sleep(0.5)


# ======================================================================
# AUTH DECORATOR
# ======================================================================
def require_login(role=None):
    def deco(func):
        async def wrapper(request):
            sess = get_current_session(request)
            if not sess:
                return web.json_response({"ok": False, "error": "Not logged in"}, status=401)
            if role and sess["role"] != role and sess["role"] != "owner":
                return web.json_response({"ok": False, "error": "Forbidden"}, status=403)
            return await func(request)
        return wrapper
    return deco


# ======================================================================
# WEB HANDLERS
# ======================================================================
async def handle_index(request):
    # already logged in → dashboard
    if get_current_session(request):
        raise web.HTTPFound("/dashboard")
    path = os.path.join(os.path.dirname(__file__), "templates", "login.html")
    with open(path, "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html")


async def handle_dashboard(request):
    if not get_current_session(request):
        raise web.HTTPFound("/")
    path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    with open(path, "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html")


async def handle_login(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"})

    username = str(body.get("username", "")).strip()
    password = str(body.get("password", "")).strip()
    role     = str(body.get("role", "user")).strip().lower()

    if role not in ("user", "owner"):
        return web.json_response({"ok": False, "error": "Invalid role"})

    if not check_credentials(username, password, role):
        log_msg(f"❌ Failed login attempt ({role}: {username})", "warning")
        return web.json_response({"ok": False, "error": "Invalid credentials"})

    sid = make_session(username, role)
    log_msg(f"✅ Login: {username} ({role})", "success")

    resp = web.json_response({"ok": True, "role": role})
    resp.set_cookie(SESSION_COOKIE, sid, httponly=True, max_age=86400)
    return resp


async def handle_logout(request):
    sid = request.cookies.get(SESSION_COOKIE)
    if sid and sid in sessions:
        del sessions[sid]
    resp = web.json_response({"ok": True})
    resp.del_cookie(SESSION_COOKIE)
    return resp


async def handle_me(request):
    sess = get_current_session(request)
    if not sess:
        return web.json_response({"ok": False}, status=401)
    return web.json_response({
        "ok": True,
        "username": sess["username"],
        "role": sess["role"],
    })


async def handle_start(request):
    global GENERATION_RUNNING, STOP_EVENT, WORKER_TASKS
    global SESSION_NICKNAME, SESSION_BIO, SESSION_FILE
    global accounts_list, success_count, fail_count

    sess = get_current_session(request)
    if not sess:
        return web.json_response({"ok": False, "error": "Not logged in"}, status=401)

    if GENERATION_RUNNING:
        return web.json_response({"ok": False, "error": "Already running"})

    try:
        body = await request.json()
    except Exception:
        body = {}

    # ---- ROLE-BASED FIELDS ----
    if sess["role"] == "owner":
        nickname = str(body.get("nickname", "")).strip()[:20] or DEFAULT_NICKNAME
        bio      = str(body.get("bio", "")).strip() or DEFAULT_BIO
    else:
        # user: forced defaults
        nickname = DEFAULT_NICKNAME
        bio      = DEFAULT_BIO

    SESSION_NICKNAME = nickname
    SESSION_BIO      = bio
    SESSION_FILE     = new_session_filename()

    # reset per-session counters
    accounts_list = []
    success_count = 0
    fail_count    = 0
    log_buffer.clear()

    workers = int(body.get("workers", 20))
    workers = max(1, min(workers, 100))

    STOP_EVENT = asyncio.Event()
    GENERATION_RUNNING = True
    WORKER_TASKS = []
    for i in range(workers):
        WORKER_TASKS.append(asyncio.create_task(worker(i, "BD")))

    log_msg(
        f"▶ Started {workers} workers | role={sess['role']} | "
        f"name={nickname} | file={SESSION_FILE}",
        "success"
    )
    return web.json_response({
        "ok": True, "workers": workers,
        "session_file": SESSION_FILE,
    })


async def handle_stop(request):
    global GENERATION_RUNNING
    sess = get_current_session(request)
    if not sess:
        return web.json_response({"ok": False, "error": "Not logged in"}, status=401)
    if not GENERATION_RUNNING:
        return web.json_response({"ok": False, "error": "Not running"})

    STOP_EVENT.set()
    for t in WORKER_TASKS:
        t.cancel()
    await asyncio.gather(*WORKER_TASKS, return_exceptions=True)
    WORKER_TASKS.clear()
    GENERATION_RUNNING = False
    await save_session_json()
    log_msg("■ Stopped — JSON saved", "warning")
    return web.json_response({"ok": True, "session_file": SESSION_FILE})


async def handle_stats(request):
    sess = get_current_session(request)
    if not sess:
        return web.json_response({"ok": False}, status=401)
    return web.json_response({
        "running": GENERATION_RUNNING,
        "success": success_count,
        "fail": fail_count,
        "total": len(accounts_list),
        "logs": log_buffer[-80:],
        "session_file": SESSION_FILE,
    })


async def handle_download(request):
    sess = get_current_session(request)
    if not sess:
        return web.Response(status=401, text="Not logged in")

    fname = request.query.get("file", "") or SESSION_FILE
    # Security: only allow files starting with MAHIR_ID_GEN_
    if not fname.startswith("MAHIR_ID_GEN_") or not fname.endswith(".json"):
        return web.Response(status=400, text="Invalid filename")
    if not os.path.exists(fname):
        return web.Response(status=404, text="File not found")

    return web.FileResponse(
        fname,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


# ======================================================================
# MAIN
# ======================================================================
async def async_main():
    global HTTP_SEM, HTTP_SESSION

    HTTP_SEM = asyncio.Semaphore(HTTP_CONCURRENCY)
    connector = aiohttp.TCPConnector(
        limit=CONNECTOR_LIMIT,
        limit_per_host=CONNECTOR_LIMIT_PER_HOST,
        ttl_dns_cache=300,
        enable_cleanup_closed=True,
        ssl=False,
    )
    HTTP_SESSION = aiohttp.ClientSession(connector=connector)

    app = web.Application()
    app.router.add_get("/",             handle_index)
    app.router.add_get("/dashboard",    handle_dashboard)
    app.router.add_post("/api/login",   handle_login)
    app.router.add_post("/api/logout",  handle_logout)
    app.router.add_get("/api/me",       handle_me)
    app.router.add_post("/api/start",   handle_start)
    app.router.add_post("/api/stop",    handle_stop)
    app.router.add_get("/api/stats",    handle_stats)
    app.router.add_get("/api/download", handle_download)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEB_HOST, WEB_PORT)
    await site.start()

    print(f"\n{Fore.GREEN}{Style.BRIGHT}🌐 Dashboard: http://localhost:{WEB_PORT}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}👤 User  : {USER_CREDENTIALS['username']} / {USER_CREDENTIALS['password']}{Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}👑 Owner : {OWNER_CREDENTIALS['username']} / {OWNER_CREDENTIALS['password']}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}Press CTRL+C to stop{Style.RESET_ALL}\n")

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        log_msg("Shutting down…", "warning")
        if GENERATION_RUNNING and STOP_EVENT:
            STOP_EVENT.set()
            for t in WORKER_TASKS:
                t.cancel()
            await asyncio.gather(*WORKER_TASKS, return_exceptions=True)
        await save_session_json()
        await HTTP_SESSION.close()
        await runner.cleanup()


def run():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}👋 Bye{Style.RESET_ALL}")
        sys.exit(0)


if __name__ == '__main__':
    run()
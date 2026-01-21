import os
import datetime
import json
import glob
import threading
import time
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import tkinter.scrolledtext as st

# --- KIỂM TRA & IMPORT THƯ VIỆN GIAO DIỆN ---
try:
    import ttkbootstrap as ttk
    from ttkbootstrap.constants import *
    from ttkbootstrap.widgets.scrolled import ScrolledFrame
except ImportError:
    import os
    print("Installing ttkbootstrap...")
    os.system("pip install ttkbootstrap")
    import ttkbootstrap as ttk
    from ttkbootstrap.constants import *
    from ttkbootstrap.widgets.scrolled import ScrolledFrame

# --- KIỂM TRA & IMPORT GOOGLE API ---
try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
except ImportError:
    messagebox.showerror("Environment Error", "Missing Google API libraries!\nPlease run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
    exit()

# --- LICENSE SYSTEM IMPORT ---
try:
    import firebase_admin
    from firebase_admin import credentials, db
except ImportError:
    print("Installing firebase-admin...")
    os.system("pip install firebase-admin")
    import firebase_admin
    from firebase_admin import credentials, db

# =============================================================================
# SYSTEM CONFIGURATION
# =============================================================================

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/youtube"
]

TOKEN_DIR = "user_tokens"
SECRET_DIR = "client_secrets"
SETTINGS_FILE = "settings.json"
GRID_STATE_FILE = "grid_state.json"
LICENSE_FILE = "license.key"

FIREBASE_KEY = "firebase_key.json" 
FIREBASE_DB_URL = "https://npsang-e678c-default-rtdb.asia-southeast1.firebasedatabase.app/" 

for d in [TOKEN_DIR, SECRET_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

file_lock = threading.Lock()

firebase_app = None
if os.path.exists(FIREBASE_KEY):
    try:
        cred = credentials.Certificate(FIREBASE_KEY)
        firebase_app = firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_DB_URL})
    except Exception as e:
        print(f"Firebase Init Error: {e}")
else:
    print("Warning: firebase_key.json not found! License check will fail.")

# =============================================================================
# DATA
# =============================================================================

YT_CATEGORIES = {
    "Default (From Settings)": "default",
    "Film & Animation": "1",
    "Autos & Vehicles": "2",
    "Music": "10",
    "Pets & Animals": "15",
    "Sports": "17",
    "Travel & Events": "19",
    "Gaming": "20",
    "People & Blogs": "22",
    "Comedy": "23",
    "Entertainment": "24",
    "News & Politics": "25",
    "Howto & Style": "26",
    "Education": "27",
    "Science & Technology": "28",
    "Nonprofits & Activism": "29"
}

YT_LANGUAGES = {
    "English (Global)": "en",
    "English (United States)": "en-US",
    "Vietnamese (Vietnam)": "vi",
    "Japanese (Japan)": "ja",
    "Korean (South Korea)": "ko",
    "Chinese (Simplified)": "zh-CN",
    "Chinese (Traditional)": "zh-TW",
    "Spanish (Spain)": "es",
    "French (France)": "fr",
    "German (Germany)": "de",
    "Russian (Russia)": "ru",
    "Portuguese (Brazil)": "pt-BR",
    "Indonesian (Indonesia)": "id",
    "Thai (Thailand)": "th"
}

YT_LOCATIONS = {
    "No Location": {"desc": "", "lat": 0.0, "long": 0.0},
    "United States": {"desc": "United States", "lat": 37.0902, "long": -95.7129},
    "Vietnam": {"desc": "Vietnam", "lat": 14.0583, "long": 108.2772},
    "Japan": {"desc": "Japan", "lat": 36.2048, "long": 138.2529},
    "South Korea": {"desc": "South Korea", "lat": 35.9078, "long": 127.7669},
    "United Kingdom": {"desc": "United Kingdom", "lat": 55.3781, "long": -3.4360},
    "Germany": {"desc": "Germany", "lat": 51.1657, "long": 10.4515},
    "France": {"desc": "France", "lat": 46.2276, "long": 2.2137},
    "Brazil": {"desc": "Brazil", "lat": -14.2350, "long": -51.9253},
    "India": {"desc": "India", "lat": 20.5937, "long": 78.9629}
}

DEFAULT_SETTINGS = {
    "categoryId": "22",          
    "languageCode": "en-US",     
    "locationKey": "United States"
}

# =============================================================================
# UTILS
# =============================================================================

def load_json(filepath, default_val):
    if not os.path.exists(filepath): return default_val
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default_val

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        return True
    except:
        return False

def save_grid_state(rows):
    state = {}
    for i, row in enumerate(rows):
        pl_name = row['playlist'].get()
        pl_id = row['playlist_map'].get(pl_name, "") if hasattr(row, 'playlist_map') and row['playlist_map'] else ""
        
        state[str(i+1)] = {
            "secret": row['secret'].get(),
            "folder": row['folder'].get(),
            "acc": row['acc'].get(),
            "time": row['time'].get(),
            "cat": row['cat'].get(),
            "gap": row['gap'].get(),
            "chk": row['chk'].get(),
            "playlist_name": pl_name,
            "playlist_id": pl_id
        }
    try:
        with open(GRID_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=4)
    except:
        pass

CURRENT_SETTINGS = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)

# =============================================================================
# BACKEND LOGIC
# =============================================================================

def get_client_id_from_file(secret_filename):
    path = os.path.join(SECRET_DIR, secret_filename)
    if not os.path.exists(path): return None
    try:
        with open(path, 'r') as f:
            d = json.load(f)
            return d.get('installed', {}).get('client_id') or d.get('web', {}).get('client_id')
    except: return None

def get_authenticated_service(token_filename, secret_filename):
    token_path = os.path.join(TOKEN_DIR, token_filename)
    secret_path = os.path.join(SECRET_DIR, secret_filename)
    if not os.path.exists(token_path) or not os.path.exists(secret_path): return None

    try:
        with open(token_path, 'r') as f: store = json.load(f)
        if "google_creds" not in store or "client_id" not in store: return None
        target_cid = get_client_id_from_file(secret_filename)
        if target_cid != store["client_id"]: return None

        creds = Credentials.from_authorized_user_info(store["google_creds"], SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
                creds.refresh(Request())
                store["google_creds"] = json.loads(creds.to_json())
                with file_lock:
                    with open(token_path, "w") as f: json.dump(store, f, indent=4)
            else: return None
        return build("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception as e: return None

def create_new_login(secret_filename):
    secret_path = os.path.join(SECRET_DIR, secret_filename)
    cid = get_client_id_from_file(secret_filename)
    if not cid: return None, "Invalid Secret File!"

    try:
        flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
        creds = flow.run_local_server(port=0, authorization_prompt_message="", timeout_seconds=60)
        with build("oauth2", "v2", credentials=creds) as oauth_service:
            email = oauth_service.userinfo().get().execute().get('email')
        if not email: return None, "Cannot retrieve Email!"

        fname = f"{email}.json"
        data = {"google_creds": json.loads(creds.to_json()), "client_id": cid, "email": email, "created_at": str(datetime.datetime.now())}
        with open(os.path.join(TOKEN_DIR, fname), "w") as f: json.dump(data, f, indent=4)
        return fname, None
    except Exception as e: return None, f"Error/Timeout: {str(e)}"

def get_user_playlists(youtube):
    try:
        playlists = {}
        request = youtube.playlists().list(
            part="snippet",
            mine=True,
            maxResults=50
        )
        response = request.execute()
        for item in response.get("items", []):
            pid = item["id"]
            title = item["snippet"]["title"]
            playlists[title] = pid
        return playlists
    except Exception as e:
        print(f"Error fetching playlists: {e}")
        return {}

def add_video_to_playlist(youtube, video_id, playlist_id):
    if not playlist_id: return False, "No Playlist ID"
    try:
        body_request = {
            "snippet": {
                "playlistId": str(playlist_id),
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": str(video_id)
                }
            }
        }
        request = youtube.playlistItems().insert(
            part="snippet",
            body=body_request
        )
        response = request.execute()
        return True, json.dumps(response.get('snippet', {})) 
    except Exception as e:
        return False, str(e)

# --- CẬP NHẬT: QUÉT FILE TXT BẤT KỲ VÀ PARSE CẤU TRÚC MỚI ---
def scan_folder_for_video(folder_path):
    if not os.path.exists(folder_path): return None
    
    # 1. Tìm Video
    vids = glob.glob(os.path.join(folder_path, "*.mp4")) + glob.glob(os.path.join(folder_path, "*.mp3"))
    if not vids: return None
    
    # 2. Tìm Ảnh
    imgs = glob.glob(os.path.join(folder_path, "*.jpg")) + glob.glob(os.path.join(folder_path, "*.png"))
    
    # 3. Tìm File Text (Bất kỳ file .txt nào, lấy file đầu tiên)
    txt_files = glob.glob(os.path.join(folder_path, "*.txt"))
    # Loại bỏ file tạm của hệ thống hoặc file rác nếu cần, ở đây lấy file đầu tiên tìm thấy
    info_path = txt_files[0] if txt_files else None
    
    title = os.path.splitext(os.path.basename(vids[0]))[0]
    tags = []; desc = ""
    
    if info_path and os.path.exists(info_path):
        try:
            with open(info_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            current_mode = None
            raw_title, raw_desc, raw_tags = [], [], []
            
            for line in lines:
                clean = line.strip()
                
                # --- PHÁT HIỆN TỪ KHÓA (Hỗ trợ cả Tiếng Anh và Tiếng Việt cũ) ---
                if "Title:" in line or "Tiêu đề:" in line:
                    current_mode = "title"
                    # Lấy nội dung sau dấu :
                    parts = line.split(":", 1)
                    if len(parts) > 1 and parts[1].strip():
                        raw_title.append(parts[1].strip())
                    continue

                if "Video Description:" in line or "Giới thiệu:" in line:
                    current_mode = "desc"
                    parts = line.split(":", 1)
                    if len(parts) > 1 and parts[1].strip():
                        raw_desc.append(parts[1].strip())
                    continue

                if "Tags:" in line or "Thẻ tag video:" in line:
                    current_mode = "tags"
                    parts = line.split(":", 1)
                    if len(parts) > 1 and parts[1].strip():
                        raw_tags.append(parts[1].strip())
                    continue
                
                # --- NẠP DỮ LIỆU ---
                if current_mode == "title":
                    if clean: raw_title.append(clean)
                elif current_mode == "desc":
                    raw_desc.append(line.rstrip())
                elif current_mode == "tags":
                    if clean: raw_tags.append(clean)
            
            # --- XỬ LÝ KẾT QUẢ ---
            if raw_title: title = " ".join(raw_title).strip()
            if raw_desc: desc = "\n".join(raw_desc).strip()
            if raw_tags: 
                # Nối tất cả dòng tag lại, thay xuống dòng bằng dấu phẩy
                combined = ",".join(raw_tags)
                # Tách bằng dấu phẩy và xóa khoảng trắng
                tags = [t.strip() for t in combined.split(",") if t.strip()]

        except Exception as e:
            print(f"Error parsing text file {info_path}: {e}")
            
    return {"folder": folder_path, "video": vids[0], "thumb": imgs[0] if imgs else None, "title": title, "tags": tags, "desc": desc}

def calculate_schedule_time(last_time, slots_string, day_gap):
    now = datetime.datetime.now().astimezone()
    slots = []
    for s in slots_string.split(","):
        try: slots.append(datetime.datetime.strptime(s.strip(), "%H:%M").time())
        except: pass
    if not slots: slots = [datetime.time(8, 0)]
    slots.sort()

    gap = int(day_gap)

    if not last_time:
        base_date = now.date()
        for s in slots:
            dt = datetime.datetime.combine(base_date, s).replace(tzinfo=now.tzinfo)
            if dt > now: return dt
        next_dt = datetime.datetime.combine(base_date + datetime.timedelta(days=1), slots[0]).replace(tzinfo=now.tzinfo)
        return next_dt

    base_date = last_time.date()
    for s in slots:
        dt_candidate = datetime.datetime.combine(base_date, s).replace(tzinfo=last_time.tzinfo)
        if dt_candidate > last_time:
            return dt_candidate 

    days_to_add = 1 + gap
    next_date = base_date + datetime.timedelta(days=days_to_add)
    next_dt = datetime.datetime.combine(next_date, slots[0]).replace(tzinfo=last_time.tzinfo)
    return next_dt

def execute_upload(youtube, video_data, publish_time, specific_category, progress_callback, pause_event, log_func):
    cfg = CURRENT_SETTINGS
    final_cat = specific_category if (specific_category and specific_category != "default") else cfg.get("categoryId", "22")
    publish_at = publish_time.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    lang_code = cfg.get("languageCode", "en-US")
    loc_key = cfg.get("locationKey", "United States")
    loc_data = YT_LOCATIONS.get(loc_key, YT_LOCATIONS["No Location"])
    if loc_key not in YT_LOCATIONS:
        for k, v in YT_LOCATIONS.items():
            if k in loc_key or loc_key in k: loc_data = v; break

    log_func(f"   -> Lang: {lang_code} | Loc: {loc_data['desc']}")
    
    body = {
        "snippet": {
            "title": video_data['title'],
            "description": video_data['desc'],
            "tags": video_data['tags'],
            "categoryId": final_cat,
            "defaultLanguage": lang_code,       
            "defaultAudioLanguage": lang_code   
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
            "embeddable": True,
            "license": "youtube"
        },
        "recordingDetails": {
            "locationDescription": loc_data["desc"],
            "location": {"latitude": loc_data["lat"], "longitude": loc_data["long"]}
        }
    }
    
    media = MediaFileUpload(video_data['video'], chunksize=1024*1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status,recordingDetails", body=body, media_body=media)
    
    resp = None
    retry_count = 0
    MAX_RETRIES = 5

    while resp is None:
        if not pause_event.is_set():
            progress_callback("Paused...")
            pause_event.wait()
            progress_callback("Resuming...")
        
        try:
            stat, resp = request.next_chunk()
            if stat:
                pct = int(stat.progress() * 100)
                progress_callback(f"Upload {pct}%")
        except HttpError as e:
            if e.resp.status in [500, 502, 503, 504]:
                retry_count += 1
                if retry_count > MAX_RETRIES:
                    raise Exception(f"Upload Failed: Too many retries ({e.resp.status})")
                progress_callback(f"Retry {retry_count}...")
                time.sleep(5)
                continue
            else:
                raise e 
        except Exception as e:
            retry_count += 1
            if retry_count > MAX_RETRIES:
                raise Exception(f"Upload Failed: Network Error ({str(e)})")
            progress_callback(f"Net Retry {retry_count}...")
            time.sleep(5)
    
    vid = resp.get("id")
    if video_data['thumb']:
        try: youtube.thumbnails().set(videoId=vid, media_body=MediaFileUpload(video_data['thumb'])).execute()
        except: pass
    return vid

def run_job_thread(row_widgets, config, log_func, pause_event):
    COLOR_MAP = {"primary": "#007bff", "secondary": "#6c757d", "success": "#28a745", "info": "#17a2b8", "warning": "#ffc107", "danger": "#dc3545", "black": "black", "gray": "gray"}
    def ui_update(text, color_key="black"): 
        hex_color = COLOR_MAP.get(color_key, "black")
        row_widgets['stat'].config(text=text, foreground=hex_color)
    
    acc_display = config['acc'].replace(".json", "")
    btn_pause = row_widgets['btn_pause']
    
    try:
        btn_pause.config(state="normal", text="⏸", bootstyle="primary")
        log_func(f"[{acc_display}] Init...")
        ui_update("Connecting...", "primary")
        
        yt = get_authenticated_service(config['acc'], config['secret'])
        if not yt: ui_update("Login Error", "danger"); log_func(f"[{acc_display}] Token Mismatch"); return

        ui_update("Scanning...", "info")
        direct = glob.glob(os.path.join(config['folder'], "*.mp4")) + glob.glob(os.path.join(config['folder'], "*.mp3"))
        if direct: folders = [config['folder']]
        else: folders = sorted([f.path for f in os.scandir(config['folder']) if f.is_dir()])

        if not folders: ui_update("EMPTY", "danger"); log_func(f"[{acc_display}] Folder empty!"); return
        pending = [f for f in folders if not os.path.exists(os.path.join(f, "done.json"))]
        
        if not pending:
            ui_update("COMPLETED", "success"); log_func(f"[{acc_display}] All done. Check done.json."); return
        
        count_ok = 0; last_time_cursor = None
        for idx, folder in enumerate(pending):
            if not pause_event.is_set():
                ui_update("Paused", "warning")
                btn_pause.config(text="▶", bootstyle="primary-outline")
                pause_event.wait()
                btn_pause.config(text="⏸", bootstyle="primary")

            ui_update(f"Up {idx+1}/{len(pending)}", "warning")
            data = scan_folder_for_video(folder)
            if not data: continue
            
            pub_time = calculate_schedule_time(last_time_cursor, config['time'], config['gap'])
            last_time_cursor = pub_time
            log_func(f"[{acc_display}] Up: {data['title']} ({pub_time.strftime('%H:%M %d/%m')})")
            
            try:
                def on_progress(msg): 
                    if "Uploading" in msg: ui_update(msg, "warning")
                cat_id = YT_CATEGORIES.get(config['cat_name'], "default")
                
                vid_id = execute_upload(yt, data, pub_time, cat_id, on_progress, pause_event, log_func)
                
                if config.get('playlist_id'):
                    ui_update("Syncing...", "warning")
                    log_func(f"   -> Debug: Waiting 5s to add Vid {vid_id} to PL {config['playlist_id']}")
                    time.sleep(5) 
                    
                    ui_update("Add Playlist...", "info")
                    res_pl, msg_pl = add_video_to_playlist(yt, vid_id, config['playlist_id'])
                    
                    if res_pl: log_func(f"   -> Playlist Added: OK")
                    else: log_func(f"   -> Playlist FAILED: {msg_pl}")

                log_data = {"video_id": vid_id, "status": "Scheduled", "publish_time": str(pub_time), "account": config['acc']}
                with open(os.path.join(folder, "done.json"), "w") as f: json.dump(log_data, f, indent=4)
                
                log_func(f"[{acc_display}] -> OK ID: {vid_id}")
                count_ok += 1
            except HttpError as e:
                if "quotaExceeded" in str(e): ui_update("QUOTA LIMIT", "danger"); log_func(f"[{acc_display}] Quota Exceeded"); return
                else: ui_update("API Error", "danger"); log_func(f"[{acc_display}] Err: {e}"); time.sleep(3)
            except Exception as e: ui_update("Error", "danger"); log_func(f"[{acc_display}] Err: {e}"); time.sleep(3)
        ui_update(f"COMPLETED ({count_ok})", "success"); log_func(f"[{acc_display}] FINISHED")
    except Exception as e: ui_update("Crash", "danger"); log_func(f"[{acc_display}] CRASH: {e}")
    finally:
        row_widgets['running'] = False 
        btn_pause.config(state="disabled")

# =============================================================================
# GUI APP
# =============================================================================

class AutoYoutubeApp(ttk.Window):
    def __init__(self):
        super().__init__(themename="cosmo")
        self.title("YouTube Automation Tool - Protected")
        self.geometry("1900x850") 
        
        self.is_licensed = False
        self.is_admin = False
        self.row_frames = [] 

        self.win_settings = None
        self.win_secrets = None
        self.win_accounts = None
        self.win_admin_manager = None

        self.create_header()
        self.create_grid_header()
        self.create_scrollable_body()
        self.create_log_area()
        self.load_dynamic_state()
        self.after(500, self.check_local_license)

    def create_header(self):
        header = ttk.Frame(self, padding=10, bootstyle="secondary"); header.pack(fill=X)
        self.lbl_title = ttk.Label(header, text="YOUTUBE AUTO UPLOADER (LOCKED)", font=("Helvetica", 14, "bold"), bootstyle="inverse-secondary")
        self.lbl_title.pack(side=LEFT)
        bf = ttk.Frame(header, bootstyle="secondary"); bf.pack(side=RIGHT)
        self.btn_admin_manager = ttk.Button(bf, text="🛡 Manager", bootstyle="primary", command=self.open_admin_panel)
        ttk.Button(bf, text="▶ START", bootstyle="success", command=self.on_start).pack(side=RIGHT, padx=5)
        ttk.Separator(bf, orient=VERTICAL).pack(side=RIGHT, padx=10, fill=Y)
        ttk.Button(bf, text="⚙ Settings", bootstyle="primary", command=self.open_settings).pack(side=RIGHT, padx=5)
        ttk.Button(bf, text="🔑 Secrets", bootstyle="primary", command=self.open_secret_manager).pack(side=RIGHT, padx=5)
        ttk.Button(bf, text="🗑 Accounts", bootstyle="primary", command=self.open_acc_manager).pack(side=RIGHT, padx=5)
        ttk.Separator(bf, orient=VERTICAL).pack(side=RIGHT, padx=10, fill=Y)
        ttk.Button(bf, text="+ 1 Row", bootstyle="primary", command=lambda: self.add_row()).pack(side=RIGHT, padx=5)
        ttk.Button(bf, text="➕ Batch Add", bootstyle="primary", command=self.open_batch_add).pack(side=RIGHT, padx=5)
        ttk.Button(bf, text="🔑 License", bootstyle="primary", command=self.open_license_dialog).pack(side=RIGHT, padx=5)

    def create_grid_header(self):
        cols_fr = ttk.Frame(self, padding=(10, 5)); cols_fr.pack(fill=X)
        self.master_chk = tk.BooleanVar(value=True)
        ttk.Checkbutton(cols_fr, variable=self.master_chk, command=self.toggle_all_rows).pack(side=LEFT, padx=(5, 10))
        headers = [("#", 3), ("Client Secret", 30), ("Video Folder", 40), ("YouTube Account", 30), ("Playlist", 25), ("Schedule Time", 35), ("Gap", 5), ("Category", 20), ("Status", 20), ("Pause", 8), ("", 5)]
        for text, w in headers: ttk.Label(cols_fr, text=text, width=w, font=("Segoe UI", 9, "bold"), anchor="center").pack(side=LEFT, padx=2)

    def create_scrollable_body(self):
        self.scroll_frame = ScrolledFrame(self, autohide=True); self.scroll_frame.pack(fill=BOTH, expand=True, padx=10)

    def create_log_area(self):
        lf = ttk.Labelframe(self, text="Activity Log", padding=5); lf.pack(fill=BOTH, expand=True, padx=10, pady=10)
        self.log_text = st.ScrolledText(lf, height=8, state='disabled', font=("Consolas", 10)); self.log_text.pack(fill=BOTH, expand=True)
        self.log_text.tag_config("ts", foreground="gray"); self.log_text.tag_config("msg", foreground="black")

    def check_local_license(self):
        if os.path.exists(LICENSE_FILE):
            try:
                with open(LICENSE_FILE, "r") as f:
                    self.verify_license_online(f.read().strip(), silent_fail=True)
            except: pass
            
    def open_license_dialog(self):
        current_key = ""
        if os.path.exists(LICENSE_FILE):
            try:
                with open(LICENSE_FILE, "r") as f: current_key = f.read().strip()
            except: pass
        res = simpledialog.askstring("License Check", "Enter License Key (or Admin Code):", parent=self, initialvalue=current_key)
        if res: self.verify_license_online(res.strip())

    def verify_license_online(self, key, silent_fail=False):
        if not firebase_app:
            if not silent_fail: messagebox.showerror("Error", "Firebase not initialized. Check firebase_key.json")
            return
        try:
            admin_ref = db.reference('admin_code')
            remote_admin_code = admin_ref.get()
            if remote_admin_code and str(key) == str(remote_admin_code):
                self.activate_admin_mode(save_to_file=True)
                with open(LICENSE_FILE, "w") as f: f.write(key)
                if not silent_fail: messagebox.showinfo("Admin", "Admin Access Granted.")
                return
            ref = db.reference(f'licenses/{key}')
            val = ref.get()
            if val is True:
                self.is_licensed = True; self.is_admin = False; self.btn_admin_manager.pack_forget()
                self.lbl_title.config(text=f"YOUTUBE UPLOADER (ACTIVATED: {key})")
                with open(LICENSE_FILE, "w") as f: f.write(key)
                if not silent_fail: messagebox.showinfo("Success", "License Valid! Tool Activated.")
                self.log(f"License activated: {key}")
            else:
                self.is_licensed = False; self.lbl_title.config(text="YOUTUBE UPLOADER (LOCKED)")
                if not silent_fail: messagebox.showerror("Failed", "Invalid License or Admin Code!")
        except Exception as e:
            if not silent_fail: messagebox.showerror("Connection Error", str(e))

    def activate_admin_mode(self, save_to_file=True):
        self.is_licensed = True; self.is_admin = True
        self.lbl_title.config(text="YOUTUBE UPLOADER (ADMIN MODE)")
        self.btn_admin_manager.pack(side=RIGHT, padx=5)
        self.log("Auto-login: Admin Mode")

    def open_admin_panel(self):
        if not firebase_app: return
        if self.focus_or_create(self.win_admin_manager): return
        self.win_admin_manager = ttk.Toplevel(self); w = self.win_admin_manager; w.title("Admin License Manager"); w.geometry("400x500")
        list_frame = ScrolledFrame(w, height=300); list_frame.pack(fill=BOTH, expand=True, padx=10)
        def refresh_list():
            for c in list_frame.winfo_children(): c.destroy()
            try:
                data = db.reference('licenses').get() or {}
                for key, active in data.items():
                    r = ttk.Frame(list_frame); r.pack(fill=X, pady=2)
                    ttk.Label(r, text=key, width=30).pack(side=LEFT)
                    ttk.Button(r, text="X", bootstyle="primary-outline", width=3, command=lambda k=key: delete_key(k)).pack(side=RIGHT)
            except Exception as e: messagebox.showerror("Err", str(e))
        def add_key():
            k = simpledialog.askstring("New License", "Enter new key to add:")
            if k: db.reference(f'licenses/{k}').set(True); refresh_list()
        def delete_key(k):
            if messagebox.askyesno("Confirm", f"Delete key '{k}'?"): db.reference(f'licenses/{k}').delete(); refresh_list()
        ttk.Button(w, text="Refresh List", bootstyle="primary", command=refresh_list).pack(pady=5)
        ttk.Button(w, text="+ Add New License", bootstyle="primary", command=add_key).pack(pady=5, fill=X, padx=20)
        refresh_list()
    
    def check_access(self):
        if not self.is_licensed: messagebox.showwarning("Locked", "Please enter a valid License first!\nClick '🔑 License' on header."); return False
        return True

    def refresh_global_ui(self):
        all_secrets = [os.path.basename(f) for f in glob.glob(os.path.join(SECRET_DIR, "*.json"))]
        for r in self.row_frames:
            current_sec = r['secret'].get()
            r['secret']['values'] = all_secrets
            if current_sec and current_sec not in all_secrets: r['secret'].set(''); current_sec = ''
            valid_accs = []
            if current_sec:
                cid = get_client_id_from_file(current_sec)
                if cid:
                    for f in glob.glob(os.path.join(TOKEN_DIR, "*.json")):
                        try:
                            if json.load(open(f)).get("client_id") == cid: valid_accs.append(os.path.basename(f))
                        except: pass
            used = []
            this_row_idx = int(r['lbl_idx'].cget("text"))
            for i, other_row in enumerate(self.row_frames):
                 if (i+1) != this_row_idx:
                    v = other_row['acc'].get(); 
                    if v: used.append(v)
            final_accs = [a for a in valid_accs if a not in used]
            current_acc = r['acc'].get()
            if current_acc and current_acc in valid_accs: 
                if current_acc not in final_accs: final_accs.append(current_acc)
            r['acc']['values'] = final_accs
            if current_acc and current_acc not in valid_accs:
                 r['acc'].set(''); r['playlist'].set(''); r['playlist']['values'] = []
                 if 'playlist_map' in r: r['playlist_map'] = {}
            self.update_master_state()

    def update_master_state(self):
        if not self.row_frames: self.master_chk.set(False); return
        all_checked = True
        for r in self.row_frames:
            if not r['chk'].get(): all_checked = False; break
        self.master_chk.set(all_checked)

    def add_row(self, initial_data=None):
        idx = len(self.row_frames) + 1
        data = initial_data if initial_data else {}
        row_widgets = {}
        fr = ttk.Frame(self.scroll_frame, padding=(0, 2)); fr.pack(fill=X)
        chk_var = tk.BooleanVar(value=data.get('chk', True))
        ttk.Checkbutton(fr, variable=chk_var, command=self.update_master_state).pack(side=LEFT, padx=(5, 10))
        lbl_idx = ttk.Label(fr, text=str(idx), width=3, anchor="center"); lbl_idx.pack(side=LEFT)
        
        sec_cb = ttk.Combobox(fr, state="readonly", width=28); sec_cb.pack(side=LEFT, padx=2)
        secrets = [os.path.basename(f) for f in glob.glob(os.path.join(SECRET_DIR, "*.json"))]
        sec_cb['values'] = secrets
        if data.get('secret') in secrets: sec_cb.set(data.get('secret'))
        
        fol_ent = ttk.Entry(fr, width=38); fol_ent.pack(side=LEFT, padx=2)
        fol_ent.insert(0, data.get('folder', ''))
        ttk.Button(fr, text="📂", width=3, bootstyle="primary-outline", command=lambda: self.browse_folder(fol_ent, idx)).pack(side=LEFT, padx=(0,5))
        
        acc_cb = ttk.Combobox(fr, state="readonly", width=28); acc_cb.pack(side=LEFT, padx=2)
        
        playlist_map = {} 
        playlist_cb = ttk.Combobox(fr, state="readonly", width=23); playlist_cb.pack(side=LEFT, padx=2)
        playlist_cb.set(data.get('playlist_name', ''))
        old_playlist_id = data.get('playlist_id', '')

        def load_playlists_for_acc(acc_file, secret_file):
            if not acc_file or not secret_file: return
            def task():
                playlist_cb.set("Loading...")
                yt = get_authenticated_service(acc_file, secret_file)
                if yt:
                    pls = get_user_playlists(yt)
                    def update_ui():
                        playlist_cb['values'] = ["No Playlist"] + list(pls.keys())
                        row_widgets['playlist_map'] = pls 
                        found = False
                        if old_playlist_id:
                            for name, pid in pls.items():
                                if pid == old_playlist_id: playlist_cb.set(name); found = True; break
                        if not found:
                             if data.get('playlist_name') in pls: playlist_cb.set(data.get('playlist_name'))
                             else: playlist_cb.set("No Playlist")
                    self.after(0, update_ui)
                else: self.after(0, lambda: playlist_cb.set("Error Login"))
            threading.Thread(target=task, daemon=True).start()

        def update_acc_list(event=None, load_only=False):
            sec = sec_cb.get()
            if not sec: 
                if not load_only: acc_cb['values'] = []
                return
            cid = get_client_id_from_file(sec)
            if cid:
                valid = []
                for f in glob.glob(os.path.join(TOKEN_DIR, "*.json")):
                    try:
                        if json.load(open(f)).get("client_id") == cid: valid.append(os.path.basename(f))
                    except: pass
                used = []
                for i, r in enumerate(self.row_frames):
                    if (i+1) != int(lbl_idx.cget("text")):
                        v = r['acc'].get()
                        if v: used.append(v)
                final = [a for a in valid if a not in used]
                acc_cb['values'] = final
                cur = acc_cb.get()
                if not load_only:
                    if not cur and final: acc_cb.set(final[0])
                    elif cur and cur not in final: acc_cb.set('')
                    if acc_cb.get(): load_playlists_for_acc(acc_cb.get(), sec_cb.get())

        sec_cb.bind("<<ComboboxSelected>>", lambda e: [acc_cb.set(''), update_acc_list()])
        acc_cb.bind("<Button-1>", update_acc_list)
        acc_cb.bind("<<ComboboxSelected>>", lambda e: load_playlists_for_acc(acc_cb.get(), sec_cb.get()))

        if sec_cb.get(): 
            update_acc_list(load_only=True)
            acc_cb.set(data.get('acc', ''))
            if data.get('acc'): load_playlists_for_acc(data.get('acc'), sec_cb.get())

        def quick_add_acc():
            if not self.check_access(): return
            s = sec_cb.get()
            if not s: messagebox.showwarning("Missing", "Select Secret first!"); return
            def t():
                self.log("Opening browser for login...")
                new, err = create_new_login(s)
                if new: self.after(0, lambda: [update_acc_list(), acc_cb.set(new), self.log(f"Added {new}"), load_playlists_for_acc(new, s)])
                else: self.after(0, lambda: messagebox.showerror("Error", err))
            threading.Thread(target=t, daemon=True).start()

        ttk.Button(fr, text="+", width=3, bootstyle="primary-outline", command=quick_add_acc).pack(side=LEFT, padx=(0,5))
        tm = ttk.Entry(fr, width=33, justify="center"); tm.pack(side=LEFT, padx=2)
        tm.insert(0, data.get('time', "08:00, 19:00"))
        gap = ttk.Spinbox(fr, from_=0, to=30, width=5, justify="center"); gap.pack(side=LEFT, padx=2)
        gap.set(data.get('gap', 0))
        cat = ttk.Combobox(fr, state="readonly", values=list(YT_CATEGORIES.keys()), width=15); cat.pack(side=LEFT, padx=2)
        cat.set(data.get('cat', "Default (From Settings)"))
        stat = ttk.Label(fr, text="Ready", foreground="gray", width=18, anchor="center"); stat.pack(side=LEFT, padx=5)
        pause_event = threading.Event(); pause_event.set()
        
        def toggle_pause():
            if pause_event.is_set(): pause_event.clear(); btn_pause.config(text="▶", bootstyle="primary-outline")
            else: pause_event.set(); btn_pause.config(text="⏸", bootstyle="primary")
        
        btn_pause = ttk.Button(fr, text="⏸", width=4, bootstyle="primary", state="disabled", command=toggle_pause)
        btn_pause.pack(side=LEFT, padx=2)
        def delete_this_row():
            fr.destroy(); self.row_frames.remove(row_widgets)
            for i, r in enumerate(self.row_frames): r['lbl_idx'].config(text=str(i+1))
            self.update_master_state()
        ttk.Button(fr, text="X", width=4, bootstyle="primary-outline", command=delete_this_row).pack(side=LEFT, padx=5)

        row_widgets = {
            'frame': fr, 'lbl_idx': lbl_idx, 'chk': chk_var, 
            'secret': sec_cb, 'folder': fol_ent, 'acc': acc_cb, 
            'playlist': playlist_cb, 'playlist_map': playlist_map, 
            'time': tm, 'gap': gap, 'cat': cat, 'stat': stat, 
            'pause_event': pause_event, 'btn_pause': btn_pause,
            'running': False 
        }
        self.row_frames.append(row_widgets)

    def load_dynamic_state(self):
        try:
            with open(GRID_STATE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, list): 
                    for d in saved: self.add_row(d)
                elif isinstance(saved, dict):
                     for k in sorted(saved.keys(), key=lambda x: int(x)): self.add_row(saved[k])
                else: self.add_row()
        except: self.add_row()
        self.update_master_state()

    def save_current_state(self):
        save_grid_state(self.row_frames)

    def open_batch_add(self):
        if not self.check_access(): return
        w = ttk.Toplevel(self); w.title("Batch Add Channels"); w.geometry("500x500")
        ttk.Label(w, text="1. Select Secret:", font=("Bold", 10)).pack(anchor=W, padx=10, pady=5)
        secrets = [os.path.basename(f) for f in glob.glob(os.path.join(SECRET_DIR, "*.json"))]
        sec_cb = ttk.Combobox(w, values=secrets, state="readonly"); sec_cb.pack(fill=X, padx=10)
        ttk.Label(w, text="2. Select Accounts:", font=("Bold", 10)).pack(anchor=W, padx=10, pady=5)
        list_frame = ScrolledFrame(w, height=250); list_frame.pack(fill=BOTH, expand=True, padx=10)
        self.batch_vars = [] 
        def load_accounts(event=None):
            for widget in list_frame.winfo_children(): widget.destroy()
            self.batch_vars = []
            sec = sec_cb.get()
            if not sec: return
            cid = get_client_id_from_file(sec)
            for f in glob.glob(os.path.join(TOKEN_DIR, "*.json")):
                try:
                    if json.load(open(f)).get("client_id") == cid:
                        name = os.path.basename(f)
                        var = tk.BooleanVar(value=True)
                        ttk.Checkbutton(list_frame, text=name, variable=var).pack(anchor=W)
                        self.batch_vars.append((name, var))
                except: pass
        sec_cb.bind("<<ComboboxSelected>>", load_accounts)
        def quick_login():
            s = sec_cb.get(); 
            if not s: return
            def t():
                new, err = create_new_login(s)
                if new: self.after(0, load_accounts)
            threading.Thread(target=t, daemon=True).start()
        ttk.Button(w, text="+ Add New Account", command=quick_login, bootstyle="primary-outline").pack(fill=X, padx=10, pady=5)
        def confirm():
            sec = sec_cb.get()
            if not sec: messagebox.showwarning("Missing Data", "Please select a Client Secret!"); return
            accs = [n for n, v in self.batch_vars if v.get()]
            if not accs: messagebox.showwarning("Missing Data", "Please select at least one Account to add!"); return
            existing_pairs = set()
            for r in self.row_frames:
                if r['secret'].get() and r['acc'].get(): existing_pairs.add((r['secret'].get(), r['acc'].get()))
            count_added = 0
            for acc in accs:
                if (sec, acc) in existing_pairs: continue
                self.add_row({"secret": sec, "acc": acc, "folder": "", "time": "08:00, 19:00", "gap": 0, "cat": "Default (From Settings)", "chk": True})
                count_added += 1
                existing_pairs.add((sec, acc))
            w.destroy()
            messagebox.showinfo("Result", f"Added {count_added} rows.")
            self.update_master_state()
        ttk.Button(w, text="ADD TO GRID", bootstyle="primary", command=confirm).pack(fill=X, padx=10, pady=10)

    def log(self, text):
        ts = datetime.datetime.now().strftime("[%H:%M:%S] ")
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, ts, "ts"); self.log_text.insert(tk.END, text + "\n", "msg")
        self.log_text.see(tk.END); self.log_text.config(state='disabled')

    def browse_folder(self, entry, current_idx):
        d = filedialog.askdirectory()
        if d:
            new_path = os.path.normpath(d).lower()
            for i, r in enumerate(self.row_frames):
                if (i + 1) == current_idx: continue
                exist = r['folder'].get()
                if exist and os.path.normpath(exist).lower() == new_path:
                    messagebox.showwarning("Duplicate", f"This folder is selected in Row {i+1}!"); return
            entry.delete(0, tk.END); entry.insert(0, d)

    def toggle_all_rows(self):
        val = self.master_chk.get()
        for r in self.row_frames: r['chk'].set(val)

    def on_start(self):
        if not self.check_access(): return
        self.save_current_state()
        active = 0; self.log("--- START PROCESS ---")
        for r in self.row_frames:
            if not r['chk'].get(): continue
            if r['running']: continue

            sec = r['secret'].get(); fol = r['folder'].get(); acc = r['acc'].get(); tim = r['time'].get()
            if not all([sec, fol, acc, tim]): continue
            
            pl_name = r['playlist'].get()
            pl_id = r['playlist_map'].get(pl_name, "") if hasattr(r, 'playlist_map') and r['playlist_map'] else ""

            r['running'] = True
            r['stat'].config(text="Starting...", foreground="#007bff") # Fixed Color
            
            cfg = {'secret': sec, 'folder': fol, 'acc': acc, 'time': tim, 'cat_name': r['cat'].get(), 'gap': int(r['gap'].get() or 0), 'playlist_id': pl_id}
            
            t = threading.Thread(target=run_job_thread, args=(r, cfg, self.log, r['pause_event']))
            t.daemon = True; t.start(); active += 1
            
        if active == 0: self.log("No new rows started.")
        else: self.log(f"Started {active} new threads.")

    def destroy(self):
        self.save_current_state(); super().destroy()
    def focus_or_create(self, win_ref):
        if win_ref and win_ref.winfo_exists(): win_ref.lift(); win_ref.focus_force(); return True
        return False
        
    def open_secret_manager(self):
        if not self.check_access(): return
        if self.focus_or_create(self.win_secrets): return
        self.win_secrets = ttk.Toplevel(self); self.win_secrets.title("Secret Manager"); self.win_secrets.geometry("400x350")
        lb = tk.Listbox(self.win_secrets); lb.pack(fill=BOTH, expand=True)
        [lb.insert(tk.END, os.path.basename(f)) for f in glob.glob(os.path.join(SECRET_DIR, "*.json"))]
        def refresh_ui():
             self.refresh_global_ui(); lb.delete(0, tk.END)
             [lb.insert(tk.END, os.path.basename(x)) for x in glob.glob(os.path.join(SECRET_DIR, "*.json"))]
        def add(): 
            f=filedialog.askopenfilename(filetypes=[("JSON","*.json")]); 
            if f: shutil.copy(f, SECRET_DIR); refresh_ui()
        def delete_secret():
            sel = lb.curselection()
            if not sel: return
            fname = lb.get(sel[0])
            if messagebox.askyesno("Delete", f"Delete {fname}?\nWARNING: All accounts linked to this secret will also be deleted!"):
                cid = get_client_id_from_file(fname)
                try: os.remove(os.path.join(SECRET_DIR, fname))
                except: pass
                if cid:
                    for acc_file in glob.glob(os.path.join(TOKEN_DIR, "*.json")):
                        try:
                            if json.load(open(acc_file)).get("client_id") == cid: os.remove(acc_file)
                        except: pass
                refresh_ui()
        ttk.Button(self.win_secrets, text="+ Import", bootstyle="primary", command=add).pack(pady=2)
        ttk.Button(self.win_secrets, text="- Delete Secret", bootstyle="danger", command=delete_secret).pack(pady=2)

    def open_acc_manager(self):
        if not self.check_access(): return
        if self.focus_or_create(self.win_accounts): return
        self.win_accounts = ttk.Toplevel(self); self.win_accounts.title("Account Manager"); self.win_accounts.geometry("400x300")
        lb = tk.Listbox(self.win_accounts); lb.pack(fill=BOTH, expand=True)
        [lb.insert(tk.END, os.path.basename(f)) for f in glob.glob(os.path.join(TOKEN_DIR, "*.json"))]
        def dele():
            s = lb.curselection()
            if s: 
                fname = lb.get(s[0])
                if messagebox.askyesno("Delete", f"Delete {fname}?"):
                    try: os.remove(os.path.join(TOKEN_DIR, fname))
                    except: pass
                    lb.delete(s[0]); self.refresh_global_ui() 
        ttk.Button(self.win_accounts, text="Delete Account", bootstyle="danger", command=dele).pack()

    def open_settings(self):
        if not self.check_access(): return
        if self.focus_or_create(self.win_settings): return
        self.win_settings = ttk.Toplevel(self); self.win_settings.title("Global Settings"); self.win_settings.geometry("400x480") 
        data = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
        fr = ttk.Frame(self.win_settings, padding=20); fr.pack(fill=BOTH, expand=True)
        ttk.Label(fr, text="Video Language:").pack(anchor=W)
        cb_l = ttk.Combobox(fr, values=list(YT_LANGUAGES.keys()), state="readonly"); cb_l.pack(fill=X, pady=(0, 10))
        for k,v in YT_LANGUAGES.items():
            if v == data.get("languageCode"): cb_l.set(k)
        ttk.Label(fr, text="Video Location:").pack(anchor=W)
        cb_loc = ttk.Combobox(fr, values=list(YT_LOCATIONS.keys()), state="readonly"); cb_loc.pack(fill=X, pady=(0, 10))
        cb_loc.set(data.get("locationKey", "United States"))
        ttk.Label(fr, text="Default Category:").pack(anchor=W)
        cb_cat = ttk.Combobox(fr, values=list(YT_CATEGORIES.keys()), state="readonly"); cb_cat.pack(fill=X, pady=(0, 10))
        cur = data.get("categoryId", "22")
        for k,v in YT_CATEGORIES.items():
            if v == cur: cb_cat.set(k)
        ttk.Separator(fr, orient=HORIZONTAL).pack(fill=X, pady=15)
        ttk.Label(fr, text="File Template (Cấu trúc info.txt):", font=("Bold", 10)).pack(anchor=W, pady=(0, 5))
        def download_sample_info():
            content = """Title:\nTitle Here\n\nVideo Description:\nDescription Here\n\nTags:\ntag1\n,tag2"""
            f = filedialog.asksaveasfilename(parent=self.win_settings, defaultextension=".txt", initialfile="info_mau.txt", filetypes=[("Text Files", "*.txt")])
            if f: 
                try: 
                    with open(f, "w", encoding="utf-8") as file: file.write(content)
                    messagebox.showinfo("Thành công", f"Đã tạo file mẫu tại:\n{f}")
                except Exception as e: messagebox.showerror("Lỗi", str(e))
        ttk.Button(fr, text="⬇ Tải file info.txt mẫu", bootstyle="info-outline", command=download_sample_info).pack(fill=X)
        ttk.Separator(fr, orient=HORIZONTAL).pack(fill=X, pady=15)
        def save():
            nd = {"categoryId": YT_CATEGORIES.get(cb_cat.get(), "22"), "languageCode": YT_LANGUAGES.get(cb_l.get(), "en-US"), "locationKey": cb_loc.get()}
            save_json(SETTINGS_FILE, nd); global CURRENT_SETTINGS; CURRENT_SETTINGS = nd
            messagebox.showinfo("Success", "Settings Saved!"); self.win_settings.destroy()
        ttk.Button(fr, text="SAVE CONFIG", bootstyle="primary", command=save).pack(fill=X, pady=10)

if __name__ == "__main__":
    app = AutoYoutubeApp()
    try: app.mainloop()
    except KeyboardInterrupt:
        print("\nStopped by User."); app.destroy()
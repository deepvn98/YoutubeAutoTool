import os
import datetime
import json
import glob
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# --- KIỂM TRA THƯ VIỆN ---
try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
except ImportError:
    messagebox.showerror("Lỗi", "Thiếu thư viện!\nChạy: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
    exit()

# --- CẤU HÌNH HỆ THỐNG ---
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/userinfo.email"
]
TOKEN_DIR = "user_tokens"
if not os.path.exists(TOKEN_DIR): os.makedirs(TOKEN_DIR)

lock = threading.Lock()

# =============================================================================
# PHẦN 1: CORE LOGIC (ĐÃ XÓA BIẾN GLOBAL THỪA)
# =============================================================================

def get_client_id_from_secret(secret_path):
    """Đọc Client ID để khớp Token"""
    try:
        with open(secret_path, 'r') as f:
            data = json.load(f)
            if 'installed' in data: return data['installed'].get('client_id')
            if 'web' in data: return data['web'].get('client_id')
    except: return None
    return None

def get_service(token_path, secret_path):
    """Lấy service YouTube từ Token + Secret cụ thể"""
    if not os.path.exists(token_path): return None
    
    try:
        with open(token_path, 'r') as f:
            store_data = json.load(f)
        
        # --- BẢN VÁ LỖI TOKEN CŨ ---
        if not isinstance(store_data, dict) or "google_creds" not in store_data:
            return None 

        creds_data = store_data.get("google_creds")
        creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
        
        # Kiểm tra khớp Client ID
        target_cid = get_client_id_from_secret(secret_path)
        stored_cid = store_data.get("client_id")
        
        if target_cid and stored_cid and target_cid != stored_cid:
            return None # Token không thuộc về Secret này
        
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                if not os.path.exists(secret_path): return None
                flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
                creds.refresh(Request())
                
                store_data["google_creds"] = json.loads(creds.to_json())
                with lock:
                    with open(token_path, "w") as tf: json.dump(store_data, tf)
            else: return None
            
        return build("youtube", "v3", credentials=creds, cache_discovery=False)
    except: return None

def new_login(secret_path):
    """Đăng nhập mới dựa trên file Secret được truyền vào"""
    if not secret_path or not os.path.exists(secret_path):
        return None, "Chưa chọn file Client Secret!"

    target_cid = get_client_id_from_secret(secret_path)
    if not target_cid: return None, "File Secret lỗi (Không có client_id)"

    try:
        flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
        creds = flow.run_local_server(port=0)
        
        with build("oauth2", "v2", credentials=creds) as oauth_service:
            email = oauth_service.userinfo().get().execute().get('email')
        
        if not email: return None, "Không lấy được Email!"
        
        file_name = f"{email}.json"
        save_path = os.path.join(TOKEN_DIR, file_name)
        
        final_data = {
            "google_creds": json.loads(creds.to_json()),
            "client_id": target_cid,
            "email": email,
            "created_at": str(datetime.datetime.now())
        }
        
        with open(save_path, "w") as t: json.dump(final_data, t, indent=4)
        return file_name, None
    except Exception as e: return None, str(e)

# --- CÁC HÀM XỬ LÝ FOLDER & UPLOAD (GIỮ NGUYÊN) ---
def get_folder_info(path):
    vids = glob.glob(os.path.join(path, "*.mp4")) + glob.glob(os.path.join(path, "*.mp3"))
    if not vids: return None
    imgs = glob.glob(os.path.join(path, "*.jpg")) + glob.glob(os.path.join(path, "*.png"))
    info = os.path.join(path, "info.txt")
    title = os.path.splitext(os.path.basename(vids[0]))[0]
    tags, desc = [], ""
    if os.path.exists(info):
        try:
            with open(info, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if len(lines) >= 1 and lines[0].strip(): title = lines[0].strip()
                if len(lines) >= 2: tags = [t.strip() for t in lines[1].split(",")]
                if len(lines) >= 3: desc = "".join(lines[2:])
        except: pass
    return {"folder": path, "video": vids[0], "thumb": imgs[0] if imgs else None, "title": title, "tags": tags, "desc": desc}

def get_publish_time(last, slots_str):
    now = datetime.datetime.now().astimezone()
    base = last if last else now
    slots = []
    for s in slots_str.split(","):
        try: slots.append(datetime.datetime.strptime(s.strip(), "%H:%M").time())
        except: pass
    if not slots: slots = [datetime.time(8, 0)]
    slots.sort()
    candidate = None
    for s in slots:
        dt = base.replace(hour=s.hour, minute=s.minute, second=0, microsecond=0)
        if dt > base: candidate = dt; break
    if not candidate:
        tomorrow = base + datetime.timedelta(days=1)
        candidate = tomorrow.replace(hour=slots[0].hour, minute=slots[0].minute, second=0, microsecond=0)
    return candidate

def upload_logic(yt, data, time_pub, callback):
    time_str = time_pub.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    callback(f"Đang up: {data['title'][:10]}...", "orange")
    body = {
        "snippet": {"title": data['title'], "description": data['desc'], "tags": data['tags'], "categoryId": "22", "defaultLanguage": "en-US"},
        "status": {"privacyStatus": "private", "publishAt": time_str, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
        "recordingDetails": {"locationDescription": "United States", "location": {"latitude": 37.0902, "longitude": -95.7129}}
    }
    media = MediaFileUpload(data['video'], chunksize=1024*1024, resumable=True)
    req = yt.videos().insert(part="snippet,status,recordingDetails", body=body, media_body=media)
    resp = None
    while resp is None:
        stat, resp = req.next_chunk()
        if stat:
            pct = int(stat.progress() * 100)
            if pct % 20 == 0: callback(f"Up {pct}%", "orange")
    vid_id = resp.get("id")
    if data['thumb']:
        try: yt.thumbnails().set(videoId=vid_id, media_body=MediaFileUpload(data['thumb'])).execute()
        except: pass
    return vid_id

def worker_thread(label, cfg):
    def ui(msg, color="black"): label.config(text=msg, fg=color)
    try:
        ui("Kết nối...", "blue")
        yt = get_service(os.path.join(TOKEN_DIR, cfg['acc']), cfg['secret'])
        if not yt:
            ui("Lỗi Token/Secret", "red")
            return

        ui("Quét file...", "blue")
        direct = glob.glob(os.path.join(cfg['folder'], "*.mp4")) + glob.glob(os.path.join(cfg['folder'], "*.mp3"))
        folders = [cfg['folder']] if direct else sorted([f.path for f in os.scandir(cfg['folder']) if f.is_dir()])
        pending = [f for f in folders if not os.path.exists(os.path.join(f, "done.json"))]
        
        if not pending:
            ui("XONG HẾT", "green")
            return
            
        count, last_time = 0, None
        for idx, fol in enumerate(pending):
            ui(f"Up {idx+1}/{len(pending)}", "orange")
            data = get_folder_info(fol)
            if not data: continue
            
            pub_time = get_publish_time(last_time, cfg['time'])
            last_time = pub_time
            
            try:
                vid_id = upload_logic(yt, data, pub_time, ui)
                log = {"id": vid_id, "status": "Scheduled", "time": str(pub_time), "acc": cfg['acc']}
                with open(os.path.join(fol, "done.json"), "w") as f: json.dump(log, f, indent=4)
                count += 1
            except HttpError as e:
                if "quotaExceeded" in str(e):
                    ui("HẾT QUOTA", "red")
                    return
                time.sleep(2)
            except Exception:
                ui("Lỗi Up", "red")
                time.sleep(2)
        ui(f"XONG ({count})", "green")
    except: ui("Lỗi Crash", "red")

# =============================================================================
# PHẦN 3: GIAO DIỆN HIỆN ĐẠI
# =============================================================================

class ModernApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YT Auto Pro - Multi Thread & Auto Match")
        self.geometry("1150x700")
        
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Header.TLabel", font=("Segoe UI", 10, "bold"), background="#e1e1e1", padding=5)
        
        # Header Toolbar
        top_bar = tk.Frame(self, bg="#f0f0f0", pady=10)
        top_bar.pack(fill="x")
        tk.Button(top_bar, text="▶ CHẠY DÒNG ĐÃ CHỌN", bg="#28a745", fg="white", font=("Segoe UI", 11, "bold"), command=self.start_selected).pack(side="left", padx=20)
        tk.Button(top_bar, text="⬇ Copy Giờ Dòng 1", bg="#17a2b8", fg="white", command=self.copy_time).pack(side="left")
        tk.Button(top_bar, text="🗑 Quản lý Acc", bg="#dc3545", fg="white", command=self.open_acc_manager).pack(side="left", padx=5)

        # Scroll Container
        container = tk.Frame(self)
        container.pack(fill="both", expand=True, padx=10, pady=5)
        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.scroll_frame = tk.Frame(canvas)
        self.scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # Headers
        self.master_chk = tk.BooleanVar(value=True)
        tk.Checkbutton(self.scroll_frame, variable=self.master_chk, command=self.toggle_all).grid(row=0, column=0)
        headers = ["#", "File Client Secret (Project)", "Thư mục Video", "Tài khoản (Auto Filter)", "Giờ đăng", "Trạng thái"]
        widths = [4, 25, 25, 25, 12, 15]
        for i, h in enumerate(headers): ttk.Label(self.scroll_frame, text=h, style="Header.TLabel", width=widths[i], anchor="center").grid(row=0, column=i+1, sticky="ew", padx=1)

        # Create Rows
        self.rows = []
        for i in range(1, 11): self.create_row(i)

    def create_row(self, idx):
        row = {}
        r = idx
        pad_y = 6
        
        var_chk = tk.BooleanVar(value=True)
        tk.Checkbutton(self.scroll_frame, variable=var_chk).grid(row=r, column=0, pady=pad_y)
        row['chk'] = var_chk
        
        tk.Label(self.scroll_frame, text=str(idx), font=("Segoe UI", 10, "bold"), fg="#555").grid(row=r, column=1)
        
        # Secret
        fr_sec = tk.Frame(self.scroll_frame)
        fr_sec.grid(row=r, column=2, padx=5, sticky="ew")
        ent_sec = ttk.Entry(fr_sec)
        ent_sec.pack(side="left", fill="x", expand=True)
        
        # AUTOFILL TIỆN ÍCH: Nếu có file client_secret.json trong thư mục gốc thì tự điền vào dòng 1
        if idx == 1 and os.path.exists("client_secret.json"):
            ent_sec.insert(0, os.path.abspath("client_secret.json"))

        tk.Button(fr_sec, text="📂", width=3, command=lambda: self.browse_secret(idx)).pack(side="right")
        row['secret'] = ent_sec

        # Folder
        fr_fol = tk.Frame(self.scroll_frame)
        fr_fol.grid(row=r, column=3, padx=5, sticky="ew")
        ent_fol = ttk.Entry(fr_fol)
        ent_fol.pack(side="left", fill="x", expand=True)
        tk.Button(fr_fol, text="📂", width=3, command=lambda: self.browse_dir(ent_fol)).pack(side="right")
        row['folder'] = ent_fol

        # Account
        fr_acc = tk.Frame(self.scroll_frame)
        fr_acc.grid(row=r, column=4, padx=5, sticky="ew")
        cb_acc = ttk.Combobox(fr_acc, state="readonly")
        cb_acc.pack(side="left", fill="x", expand=True)
        cb_acc.bind("<Button-1>", lambda e: self.filter_accounts(idx))
        tk.Button(fr_acc, text="+", width=3, bg="#d4edda", command=lambda i=idx: self.add_acc(i)).pack(side="right")
        row['acc'] = cb_acc

        # Time
        ent_time = ttk.Entry(self.scroll_frame, justify="center")
        ent_time.insert(0, "08:00, 19:00")
        ent_time.grid(row=r, column=5, padx=5, sticky="ew")
        row['time'] = ent_time

        # Status
        lbl_stat = tk.Label(self.scroll_frame, text="Sẵn sàng", fg="gray", font=("Segoe UI", 9))
        lbl_stat.grid(row=r, column=6, padx=5)
        row['stat'] = lbl_stat

        self.rows.append(row)

    # --- HELPER FUNCTIONS ---
    def filter_accounts(self, idx):
        row = self.rows[idx-1]
        secret = row['secret'].get()
        combo = row['acc']
        
        target_id = get_client_id_from_secret(secret)
        if not target_id:
            combo['values'] = []
            return

        valid = []
        for f in glob.glob(os.path.join(TOKEN_DIR, "*.json")):
            try:
                with open(f, 'r') as fp:
                    data = json.load(fp)
                    if data.get("client_id") == target_id: valid.append(os.path.basename(f))
            except: pass
        combo['values'] = valid

    def browse_secret(self, idx):
        f = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if f: 
            self.rows[idx-1]['secret'].delete(0, tk.END)
            self.rows[idx-1]['secret'].insert(0, f)
            self.rows[idx-1]['acc'].set('')
            self.filter_accounts(idx)
            if self.rows[idx-1]['acc']['values']: self.rows[idx-1]['acc'].current(0)

    def browse_dir(self, entry):
        d = filedialog.askdirectory()
        if d: entry.delete(0, tk.END); entry.insert(0, d)

    def add_acc(self, idx):
        sec = self.rows[idx-1]['secret'].get()
        if not sec: return messagebox.showwarning("Thiếu Secret", f"Chọn file Secret dòng {idx} trước!")
        messagebox.showinfo("Login", "Đang mở trình duyệt...")
        new_acc, err = new_login(sec)
        if new_acc:
            self.filter_accounts(idx)
            self.rows[idx-1]['acc'].set(new_acc)
        else: messagebox.showerror("Lỗi", err)

    def open_acc_manager(self):
        top = tk.Toplevel(self)
        top.title("Quản lý"); top.geometry("300x300")
        lb = tk.Listbox(top); lb.pack(fill="both", expand=True)
        for f in glob.glob(os.path.join(TOKEN_DIR, "*.json")): lb.insert(tk.END, os.path.basename(f))
        def dele():
            s = lb.curselection()
            if s and messagebox.askyesno("Xóa", "Xóa acc này?"):
                os.remove(os.path.join(TOKEN_DIR, lb.get(s[0])))
                lb.delete(s[0])
                for r in self.rows: r['acc'].set('')
        tk.Button(top, text="Xóa", bg="red", fg="white", command=dele).pack()

    def copy_time(self):
        t = self.rows[0]['time'].get()
        for r in self.rows[1:]: r['time'].delete(0, tk.END); r['time'].insert(0, t)

    def toggle_all(self):
        v = self.master_chk.get()
        for r in self.rows: r['chk'].set(v)

    def start_selected(self):
        c = 0
        for r in self.rows:
            if r['chk'].get() and r['secret'].get() and r['folder'].get() and r['acc'].get():
                if "Sẵn sàng" in r['stat'].cget("text") or "HOÀN TẤT" in r['stat'].cget("text") or "Lỗi" in r['stat'].cget("text"):
                    cfg = {'secret': r['secret'].get(), 'folder': r['folder'].get(), 'acc': r['acc'].get(), 'time': r['time'].get()}
                    t = threading.Thread(target=worker_thread, args=(r['stat'], cfg))
                    t.daemon = True; t.start()
                    c += 1
        if c > 0: messagebox.showinfo("OK", f"Chạy {c} luồng!")
        else: messagebox.showwarning("Lỗi", "Chưa chọn dòng nào!")

if __name__ == "__main__":
    app = ModernApp()
    app.mainloop()
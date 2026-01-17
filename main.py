import os
import datetime
import json
import glob
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.scrolledtext as st # Thư viện cho cửa sổ log

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

# --- CẤU HÌNH ---
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/userinfo.email"
]
TOKEN_DIR = "user_tokens"
if not os.path.exists(TOKEN_DIR): os.makedirs(TOKEN_DIR)

lock = threading.Lock()

# =============================================================================
# PHẦN 1: LOGIC CORE
# =============================================================================

def get_client_id(secret_path):
    try:
        with open(secret_path, 'r') as f:
            d = json.load(f)
            return d.get('installed', {}).get('client_id') or d.get('web', {}).get('client_id')
    except: return None

def get_service(token_path, secret_path):
    if not os.path.exists(token_path): return None
    try:
        with open(token_path, 'r') as f: store = json.load(f)
        
        # Check token cũ/mới
        if "google_creds" not in store: return None
        
        # Check khớp Client ID
        tid = get_client_id(secret_path)
        if tid and store.get("client_id") != tid: return None

        creds = Credentials.from_authorized_user_info(store["google_creds"], SCOPES)
        
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                if not os.path.exists(secret_path): return None
                flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
                creds.refresh(Request())
                store["google_creds"] = json.loads(creds.to_json())
                with lock:
                    with open(token_path, "w") as tf: json.dump(store, tf)
            else: return None
        return build("youtube", "v3", credentials=creds, cache_discovery=False)
    except: return None

def new_login(secret_path):
    if not secret_path or not os.path.exists(secret_path): return None, "Thiếu file Secret!"
    cid = get_client_id(secret_path)
    if not cid: return None, "File Secret lỗi!"

    try:
        # Hộp thoại hướng dẫn trước khi mở web
        messagebox.showinfo("Lưu ý", "Trình duyệt sẽ tự mở.\n1. Đăng nhập Google.\n2. Nếu báo 'Unverified', chọn Advanced -> Go to (unsafe).\n3. Bấm Allow.")
        
        flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
        creds = flow.run_local_server(port=0, authorization_prompt_message="")
        
        with build("oauth2", "v2", credentials=creds) as s:
            email = s.userinfo().get().execute().get('email')
        
        fname = f"{email}.json"
        data = {
            "google_creds": json.loads(creds.to_json()),
            "client_id": cid,
            "email": email,
            "created_at": str(datetime.datetime.now())
        }
        with open(os.path.join(TOKEN_DIR, fname), "w") as f: json.dump(data, f, indent=4)
        return fname, None
    except Exception as e: return None, str(e)

# --- XỬ LÝ FOLDER & UPLOAD ---
def get_folder_info(path):
    v = glob.glob(os.path.join(path, "*.mp4")) + glob.glob(os.path.join(path, "*.mp3"))
    if not v: return None
    img = glob.glob(os.path.join(path, "*.jpg")) + glob.glob(os.path.join(path, "*.png"))
    info = os.path.join(path, "info.txt")
    
    t = os.path.splitext(os.path.basename(v[0]))[0]
    tags, desc = [], ""
    if os.path.exists(info):
        try:
            with open(info, "r", encoding="utf-8") as f:
                ls = f.readlines()
                if len(ls)>=1 and ls[0].strip(): t = ls[0].strip()
                if len(ls)>=2: tags = [x.strip() for x in ls[1].split(",")]
                if len(ls)>=3: desc = "".join(ls[2:])
        except: pass
    return {"folder": path, "video": v[0], "thumb": img[0] if img else None, "title": t, "tags": tags, "desc": desc}

def get_pub_time(last, slots_str):
    now = datetime.datetime.now().astimezone()
    base = last if last else now
    slots = []
    for s in slots_str.split(","):
        try: slots.append(datetime.datetime.strptime(s.strip(), "%H:%M").time())
        except: pass
    if not slots: slots = [datetime.time(8,0)]
    slots.sort()
    
    cand = None
    for s in slots:
        dt = base.replace(hour=s.hour, minute=s.minute, second=0, microsecond=0)
        if dt > base: cand = dt; break
    if not cand:
        t = base + datetime.timedelta(days=1)
        cand = t.replace(hour=slots[0].hour, minute=slots[0].minute, second=0, microsecond=0)
    return cand

def upload_logic(yt, data, time_pub, callback):
    ts = time_pub.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    body = {
        "snippet": {"title": data['title'], "description": data['desc'], "tags": data['tags'], "categoryId": "22", "defaultLanguage": "en-US"},
        "status": {"privacyStatus": "private", "publishAt": ts, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
        "recordingDetails": {"locationDescription": "United States", "location": {"latitude": 37.0902, "longitude": -95.7129}}
    }
    media = MediaFileUpload(data['video'], chunksize=1024*1024, resumable=True)
    req = yt.videos().insert(part="snippet,status,recordingDetails", body=body, media_body=media)
    
    resp = None
    while resp is None:
        stat, resp = req.next_chunk()
        if stat:
            pct = int(stat.progress() * 100)
            if pct % 20 == 0: callback(f"Uploading {pct}%...")
    
    vid = resp.get("id")
    if data['thumb']:
        try: yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(data['thumb'])).execute()
        except: pass
    return vid

# =============================================================================
# PHẦN 2: WORKER (GHI LOG RA CỬA SỔ CHÍNH)
# =============================================================================

def worker_thread(label, cfg, log_func):
    """
    log_func: Hàm để ghi log ra cửa sổ chính
    label: Hàm cập nhật trạng thái dòng ngắn gọn
    """
    def ui(msg, color="black"): label.config(text=msg, fg=color)
    acc_name = cfg['acc'].replace(".json", "")
    
    try:
        log_func(f"[{acc_name}] Bắt đầu tiến trình...")
        ui("Kết nối...", "blue")
        
        yt = get_service(os.path.join(TOKEN_DIR, cfg['acc']), cfg['secret'])
        if not yt:
            ui("Lỗi Auth", "red")
            log_func(f"[{acc_name}] LỖI: Không thể xác thực hoặc token không khớp secret!")
            return

        ui("Quét file...", "blue")
        direct = glob.glob(os.path.join(cfg['folder'], "*.mp4")) + glob.glob(os.path.join(cfg['folder'], "*.mp3"))
        folders = [cfg['folder']] if direct else sorted([f.path for f in os.scandir(cfg['folder']) if f.is_dir()])
        pending = [f for f in folders if not os.path.exists(os.path.join(f, "done.json"))]
        
        log_func(f"[{acc_name}] Tìm thấy {len(pending)} video cần đăng.")

        if not pending:
            ui("XONG HẾT", "green")
            return
            
        count, last_time = 0, None
        for idx, fol in enumerate(pending):
            ui(f"Up {idx+1}/{len(pending)}", "orange")
            data = get_folder_info(fol)
            if not data: continue
            
            pub_time = get_pub_time(last_time, cfg['time'])
            last_time = pub_time
            
            # Log chi tiết
            log_func(f"[{acc_name}] Đang up video: {data['title']}")
            log_func(f"[{acc_name}] --> Lịch đăng: {pub_time.strftime('%H:%M %d/%m/%Y')}")

            try:
                # Hàm callback nội bộ để cập nhật %
                def progress_cb(msg):
                    # Chỉ hiện % ở label nhỏ, đỡ spam log lớn
                    if "Uploading" in msg: ui(msg, "orange")
                
                vid_id = upload_logic(yt, data, pub_time, progress_cb)
                
                log = {"id": vid_id, "status": "Scheduled", "time": str(pub_time), "acc": cfg['acc']}
                with open(os.path.join(fol, "done.json"), "w") as f: json.dump(log, f, indent=4)
                
                log_func(f"[{acc_name}] --> Thành công! ID: {vid_id}")
                count += 1
                
            except HttpError as e:
                if "quotaExceeded" in str(e):
                    ui("HẾT QUOTA", "red")
                    log_func(f"[{acc_name}] LỖI: Hết Quota trong ngày!")
                    return
                time.sleep(2)
            except Exception as e:
                ui("Lỗi Up", "red")
                log_func(f"[{acc_name}] Lỗi: {str(e)}")
                time.sleep(2)
        
        ui(f"XONG ({count})", "green")
        log_func(f"[{acc_name}] === HOÀN TẤT TOÀN BỘ ({count} VIDEO) ===")
        
    except Exception as e:
        ui("Crash", "red")
        log_func(f"[{acc_name}] CRASH: {str(e)}")

# =============================================================================
# PHẦN 3: GIAO DIỆN CHÍNH
# =============================================================================

class ModernApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YT Auto Pro - Kèm Cửa Sổ Log")
        self.geometry("1150x750") # Tăng chiều cao
        
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Header.TLabel", font=("Segoe UI", 10, "bold"), background="#e1e1e1", padding=5)
        
        # --- TOP TOOLBAR ---
        bar = tk.Frame(self, bg="#f0f0f0", pady=8)
        bar.pack(fill="x")
        tk.Button(bar, text="▶ CHẠY DÒNG ĐÃ CHỌN", bg="#28a745", fg="white", font=("Segoe UI", 10, "bold"), command=self.start_selected).pack(side="left", padx=15)
        tk.Button(bar, text="⬇ Copy Giờ Dòng 1", bg="#17a2b8", fg="white", command=self.copy_time).pack(side="left")
        tk.Button(bar, text="🗑 Quản lý Acc", bg="#dc3545", fg="white", command=self.open_manager).pack(side="left", padx=5)

        # --- MIDDLE: GRID (DANH SÁCH 10 DÒNG) ---
        # Dùng PanedWindow để chia tỉ lệ màn hình giữa Grid và Log
        paned = tk.PanedWindow(self, orient=tk.VERTICAL)
        paned.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Frame chứa Grid
        grid_frame = tk.Frame(paned)
        paned.add(grid_frame, height=400) # Grid chiếm phần trên

        canvas = tk.Canvas(grid_frame, highlightthickness=0)
        sb = ttk.Scrollbar(grid_frame, orient="vertical", command=canvas.yview)
        self.scroll_fr = tk.Frame(canvas)
        self.scroll_fr.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=self.scroll_fr, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # Headers
        self.master_chk = tk.BooleanVar(value=True)
        tk.Checkbutton(self.scroll_fr, variable=self.master_chk, command=self.toggle_all).grid(row=0, column=0)
        headers = ["#", "File Client Secret", "Thư mục Video", "Tài khoản (Auto)", "Giờ đăng", "Trạng thái"]
        ws = [4, 25, 25, 25, 12, 15]
        for i,h in enumerate(headers): ttk.Label(self.scroll_fr, text=h, style="Header.TLabel", width=ws[i], anchor="center").grid(row=0, column=i+1, sticky="ew", padx=1)

        self.rows = []
        for i in range(1,11): self.create_row(i)

        # --- BOTTOM: LOG WINDOW ---
        log_frame = tk.LabelFrame(paned, text="Nhật ký hoạt động (Log)", font=("Segoe UI", 10, "bold"))
        paned.add(log_frame, height=250) # Log chiếm phần dưới
        
        self.txt_log = st.ScrolledText(log_frame, state='disabled', font=("Consolas", 9))
        self.txt_log.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Khởi tạo màu cho log
        self.txt_log.tag_config("time", foreground="gray")
        self.txt_log.tag_config("info", foreground="black")

    def create_row(self, idx):
        row = {}
        r = idx; py = 6
        
        v = tk.BooleanVar(value=True)
        tk.Checkbutton(self.scroll_fr, variable=v).grid(row=r, column=0, pady=py)
        row['chk'] = v
        
        tk.Label(self.scroll_fr, text=str(idx), font=("Segoe UI",10,"bold"), fg="#555").grid(row=r, column=1)
        
        fr_s = tk.Frame(self.scroll_fr)
        fr_s.grid(row=r, column=2, padx=5, sticky="ew")
        es = ttk.Entry(fr_s)
        es.pack(side="left", fill="x", expand=True)
        if idx==1 and os.path.exists("client_secret.json"): es.insert(0, os.path.abspath("client_secret.json"))
        tk.Button(fr_s, text="📂", width=3, command=lambda: self.browse_f(es)).pack(side="right")
        row['secret'] = es
        
        fr_f = tk.Frame(self.scroll_fr)
        fr_f.grid(row=r, column=3, padx=5, sticky="ew")
        ef = ttk.Entry(fr_f)
        ef.pack(side="left", fill="x", expand=True)
        tk.Button(fr_f, text="📂", width=3, command=lambda: self.browse_d(ef)).pack(side="right")
        row['folder'] = ef
        
        fr_a = tk.Frame(self.scroll_fr)
        fr_a.grid(row=r, column=4, padx=5, sticky="ew")
        ca = ttk.Combobox(fr_a, state="readonly")
        ca.pack(side="left", fill="x", expand=True)
        ca.bind("<Button-1>", lambda e: self.filter_acc(idx))
        tk.Button(fr_a, text="+", width=3, bg="#d4edda", command=lambda: self.add_acc(idx)).pack(side="right")
        row['acc'] = ca
        
        et = ttk.Entry(self.scroll_fr, justify="center")
        et.insert(0, "08:00, 19:00")
        et.grid(row=r, column=5, padx=5, sticky="ew")
        row['time'] = et
        
        ls = tk.Label(self.scroll_fr, text="Sẵn sàng", fg="gray")
        ls.grid(row=r, column=6, padx=5)
        row['stat'] = ls
        
        self.rows.append(row)

    # --- LOGGING FUNCTION ---
    def log_msg(self, msg):
        """Hàm ghi log an toàn từ thread"""
        ts = datetime.datetime.now().strftime("[%H:%M:%S] ")
        
        # Tkinter không thread-safe hoàn toàn, nhưng ScrolledText insert thường ổn.
        # Để an toàn nhất ta có thể dùng after, nhưng ở đây insert trực tiếp cho nhanh
        self.txt_log.configure(state='normal')
        self.txt_log.insert(tk.END, ts, "time")
        self.txt_log.insert(tk.END, msg + "\n", "info")
        self.txt_log.see(tk.END) # Tự động cuộn xuống dưới
        self.txt_log.configure(state='disabled')

    # --- ACTIONS ---
    def browse_f(self, e):
        f = filedialog.askopenfilename(filetypes=[("JSON","*.json")])
        if f: 
            e.delete(0,tk.END); e.insert(0,f)
            # Reset acc dòng tương ứng (tìm dòng nào chứa entry này)
            for r in self.rows:
                if r['secret'] == e:
                    r['acc'].set('')
                    break

    def browse_d(self, e):
        d = filedialog.askdirectory()
        if d: e.delete(0,tk.END); e.insert(0,d)

    def filter_acc(self, idx):
        row = self.rows[idx-1]
        sec = row['secret'].get()
        combo = row['acc']
        tid = get_client_id(sec)
        if not tid: 
            combo['values']=[]; return
        valid = []
        for f in glob.glob(os.path.join(TOKEN_DIR, "*.json")):
            try:
                with open(f,'r') as fp:
                    if json.load(fp).get("client_id") == tid: valid.append(os.path.basename(f))
            except: pass
        combo['values'] = valid

    def add_acc(self, idx):
        sec = self.rows[idx-1]['secret'].get()
        if not sec: return messagebox.showwarning("Thiếu","Chọn Secret trước!")
        new, err = new_login(sec)
        if new:
            self.filter_acc(idx)
            self.rows[idx-1]['acc'].set(new)
            self.log_msg(f"Đã thêm tài khoản mới: {new}")
        else: messagebox.showerror("Lỗi", err)

    def open_manager(self):
        t = tk.Toplevel(self); t.geometry("300x300")
        l = tk.Listbox(t); l.pack(fill="both", expand=True)
        for f in glob.glob(os.path.join(TOKEN_DIR, "*.json")): l.insert(tk.END, os.path.basename(f))
        def d():
            s = l.curselection()
            if s and messagebox.askyesno("Xóa","Xóa?"):
                f = l.get(s[0])
                os.remove(os.path.join(TOKEN_DIR, f))
                l.delete(s[0])
                for r in self.rows: r['acc'].set('')
                self.log_msg(f"Đã xóa tài khoản: {f}")
        tk.Button(t, text="Xóa", bg="red", fg="white", command=d).pack()

    def copy_time(self):
        t = self.rows[0]['time'].get()
        for r in self.rows[1:]: r['time'].delete(0,tk.END); r['time'].insert(0,t)
    
    def toggle_all(self):
        v = self.master_chk.get()
        for r in self.rows: r['chk'].set(v)

    def start_selected(self):
        self.log_msg("--- BẮT ĐẦU CHẠY ---")
        c=0
        for r in self.rows:
            if r['chk'].get() and r['secret'].get() and r['folder'].get() and r['acc'].get():
                st = r['stat'].cget("text")
                if "Sẵn sàng" in st or "HOÀN TẤT" in st or "Lỗi" in st:
                    cfg = {'secret': r['secret'].get(), 'folder': r['folder'].get(), 'acc': r['acc'].get(), 'time': r['time'].get()}
                    # Truyền hàm log_msg vào worker
                    th = threading.Thread(target=worker_thread, args=(r['stat'], cfg, self.log_msg))
                    th.daemon = True; th.start()
                    c+=1
        if c==0: self.log_msg("Chưa chọn dòng nào hoặc thiếu thông tin!")
        else: self.log_msg(f"Đã kích hoạt {c} luồng.")

if __name__ == "__main__":
    app = ModernApp()
    app.mainloop()
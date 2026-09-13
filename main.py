"""
============================================================
       🐾 AI小新 —— 桌面互动AI宠物  主程序
       作者：Vibe Coding 课程项目
       运行方式：python main.py
============================================================
"""

# ====================================
# 第一部分：导入需要的库
# ====================================
import tkinter as tk
from tkinter import scrolledtext, messagebox, font as tkfont
import random
import subprocess
import ollama
import os
import sys
import urllib.request
import threading
from PIL import Image, ImageTk

# ====================================
# Ollama模型配置
# ====================================
MODEL_NAME = "xiaoxin"

# 强制使用 IPv4（127.0.0.1），避免 Windows 上 localhost 解析为 ::1 导致连接失败
OLLAMA_HOST = "http://127.0.0.1:11434"
ollama_client = ollama.Client(host=OLLAMA_HOST)

# ====================================
# 精灵图路径配置
# ====================================
SPRITE_PATH = os.path.join(
    getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))),
    "assets", "shinchan", "sprite.webp"
)

# 每一行对应的宠物状态名称
STATE_ROWS = [
    "idle", "walk_r", "walk_l", "wave", "jump",
    "sad", "happy", "run", "review"
]

# 精灵图行名 → 中文标签
STATE_LABELS = {
    "idle":    "😌 待机",
    "walk_r":  "🚶 右走",
    "walk_l":  "🚶 左走",
    "wave":    "👋 挥手",
    "jump":    "🦘 跳跃",
    "sad":     "😢 难过",
    "happy":   "😄 开心",
    "run":     "🏃 奔跑",
    "review":  "🤔 思考",
}

# 自定义状态 → 精灵图行索引
STATE_TO_ROW = {
    "idle":    0,   # 待机：第1行（idle）
    "talking": 3,   # 说话：挥手（wave）
    "happy":   6,   # 开心：大笑
    "sad":     5,   # 难过：哭泣
}

# 宠物窗口大小
PET_WIDTH = 200
PET_HEIGHT = 230

INIT_X = 50
INIT_Y = 100

# ====================================
# 台词配置
# ====================================
CLICK_LINES = [
    "戳我干嘛啦！", "哎呀！", "你很闲嘛？", "别碰我～",
    "嘿嘿。", "干嘛戳我！", "痛痛痛！", "你这个人哦……",
]
DRAG_LINES = [
    "喂！你要带我去哪？", "慢一点啦！", "好啦好啦，我知道你要去哪～",
]
TALK_LINES = [
    "今天也要开心哦！", "我一直在这里呢！", "要不要陪我玩一会？",
    "哎呀，好无聊啊。", "你有没有想我呀？", "嘿嘿，我在呢！",
    "你的电脑有点热呢～", "今天也要好好加油哦！",
]
CURRENT_LINE = ""

# ====================================
# 聊天数据
# ====================================
chat_messages = []
QUICK_QUESTIONS = ["你是谁？", "你会干什么？", "讲个笑话", "你今天开心吗？"]

# ====================================
# 精灵图加载
# ====================================
_state_frames = {}      # {"idle": [photo0, photo1...]}
_current_state = "idle"
_current_frame_idx = 0
_anim_timer_id = None


def _detect_frame_bounds(arr_2d, threshold=10):
    """动态检测一行图片中每一帧的左右边界"""
    col_has_content = (arr_2d[:, :, 3] > threshold).any(axis=0)
    frames = []
    in_frame = False
    frame_start = 0
    for x in range(len(col_has_content)):
        if col_has_content[x] and not in_frame:
            frame_start = x
            in_frame = True
        elif not col_has_content[x] and in_frame:
            frames.append((frame_start, x))
            in_frame = False
    if in_frame:
        frames.append((frame_start, len(col_has_content)))
    return [(s, e) for s, e in frames if e - s >= 50]


def load_spritesheet():
    """从 spritesheet 中提取所有帧，每行独立解析帧边界"""
    global _state_frames
    _state_frames = {}
    try:
        img = Image.open(SPRITE_PATH)
        w, h = img.size
        num_rows = len(STATE_ROWS)
        frame_h = h // num_rows
        print(f"📷 精灵图 {w}x{h}，共 {num_rows} 行，每行高 {frame_h}px")
        import numpy as np
        for row_idx, row_name in enumerate(STATE_ROWS):
            y_start = row_idx * frame_h
            row_img = img.crop((0, y_start, w, y_start + frame_h))
            row_arr = np.array(row_img)
            bounds = _detect_frame_bounds(row_arr)
            frames_for_row = []
            for (x_start, x_end) in bounds:
                frame = row_img.crop((x_start, 0, x_end, frame_h))
                photo = ImageTk.PhotoImage(frame)
                frames_for_row.append(photo)
            _state_frames[row_name] = frames_for_row
            print(f"  行{row_idx} [{row_name}]: {len(frames_for_row)}帧")
        print(f"✅ 加载成功，共 {len(_state_frames)} 个状态")
    except FileNotFoundError:
        print("⚠️ 未找到精灵图，使用默认表情 🧒")
    except Exception as e:
        print(f"⚠️ 加载出错：{e}，使用默认表情 🧒")


def get_frame_photo(state="idle", frame_index=0):
    """获取指定状态的指定帧图片"""
    frames = _state_frames.get(state)
    if not frames:
        return None
    if frame_index >= len(frames):
        frame_index = len(frames) - 1
    return frames[frame_index]


def stop_animation():
    """停止动画循环"""
    global _anim_timer_id
    if _anim_timer_id is not None:
        root.after_cancel(_anim_timer_id)
        _anim_timer_id = None


# ====================================
# Ollama检测
# ====================================
def check_ollama_running():
    """检查Ollama服务是否在运行（通过HTTP端口探测）"""
    try:
        # 直接用Python标准库HTTP请求检测（不依赖curl命令）
        req = urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2)
        return req.status == 200
    except Exception:
        pass
    # 备选：通过ollama命令检测
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            timeout=3
        )
        return result.returncode == 0
    except Exception:
        return False


def check_model_exists(model_name):
    """检查指定模型是否已创建"""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=3
        )
        return model_name in result.stdout
    except Exception:
        return False


def show_start_warnings():
    """启动时检查Ollama和模型，有问题则弹出提示"""
    if not check_ollama_running():
        messagebox.showwarning(
            "🐾 警告",
            "小新的AI大脑好像没启动。\n\n"
            "请先启动Ollama服务，再运行本程序。\n\n"
            "提示：在终端输入 'ollama serve' 启动服务。"
        )
        return False
    if not check_model_exists(MODEL_NAME):
        messagebox.showwarning(
            "🐾 提示",
            f"还没有找到 '{MODEL_NAME}' 模型。\n\n"
            f"请先执行：\n  ollama create {MODEL_NAME} -f Modelfile\n\n"
            "创建完成后重新启动本程序。"
        )
        return False
    return True


# ====================================
# 创建桌面宠物窗口
# ====================================
root = tk.Tk()
root.overrideredirect(True)           # 无边框
root.attributes("-toolwindow", True)
root.attributes("-topmost", True)      # 始终置顶
root.geometry(f"{PET_WIDTH}x{PET_HEIGHT}+{INIT_X}+{INIT_Y}")
root.configure(bg="#FFFFFF")
root.attributes("-transparentcolor", "#FFFFFF")   # 白色像素透明

pet_label = tk.Label(
    root,
    cursor="hand2",
    bg="#FFFFFF",
    padx=0,
    pady=0
)
pet_label.pack()

# root 创建后再加载精灵图（PhotoImage 需要 Tk 实例）
load_spritesheet()


def start_state_animation(state):
    """启动指定状态的动画循环（所有状态均可循环）"""
    global _anim_timer_id
    _anim_timer_id = 0  # 安全初始值

    def animate():
        global _current_frame_idx, _anim_timer_id
        frames = _state_frames.get(_current_state, [])
        if frames:
            _current_frame_idx = (_current_frame_idx + 1) % len(frames)
            pet_label.image = frames[_current_frame_idx]
            pet_label.config(image=frames[_current_frame_idx])
        # 先用旧 timer ID 取消，再调度新回调，彻底杜绝叠加
        old_id = _anim_timer_id
        _anim_timer_id = root.after(400, animate)
        try:
            root.after_cancel(old_id)
        except Exception:
            pass
    _current_frame_idx = 0
    animate()


if _state_frames.get("idle"):
    first_img = get_frame_photo("idle", 0)
    if first_img is not None:
        pet_label.image = first_img
        pet_label.config(image=first_img)
    start_state_animation("idle")
else:
    pet_label.config(text="🧒", font=("Segoe UI Emoji", 48))


# ====================================
# 切换宠物状态
# ====================================
def set_pet_state(state):
    """切换宠物状态，显示对应帧，非idle时启动对应动画"""
    global _current_state
    _current_state = state
    stop_animation()
    img = get_frame_photo(state, 0)
    if img is not None:
        pet_label.image = img
        pet_label.config(image=img)
    start_state_animation(state)


# ====================================
# 鼠标拖动 & 单击/双击 统一处理
# 原理：drag_offset = 按下时窗口左上角屏幕坐标 - 按下时鼠标屏幕坐标
#       移动时：新窗口坐标 = 当前鼠标屏幕坐标 + drag_offset（纯差值法，无累积误差）
# ====================================
drag_offset_x = 0
drag_offset_y = 0
is_dragging = False       # 是否已经发生了位移（区别于单击）
last_drag_lineShown = False

def on_pet_label_press(event):
    """鼠标按下：记录窗口左上角与鼠标的屏幕坐标差值"""
    global drag_offset_x, drag_offset_y, is_dragging
    drag_offset_x = root.winfo_rootx() - root.winfo_pointerx()
    drag_offset_y = root.winfo_rooty() - root.winfo_pointery()
    is_dragging = False   # 先假定是单击

def on_pet_label_motion(event):
    """鼠标移动中：拖动窗口；只要鼠标移动了就标记为拖拽"""
    global is_dragging, last_drag_lineShown
    # 使用绝对坐标重算，避免累积误差
    new_x = root.winfo_pointerx() + drag_offset_x
    new_y = root.winfo_pointery() + drag_offset_y
    # 用 wm_geometry 替代 geometry，在 Windows 上更稳定
    root.wm_geometry(f"+{new_x}+{new_y}")
    is_dragging = True  # 发生位移即为拖拽
    # 拖拽时偶尔显示台词
    if is_dragging and random.randint(1, 5) == 1 and not last_drag_lineShown:
        show_pet_line(random.choice(DRAG_LINES))
        last_drag_lineShown = True
    else:
        last_drag_lineShown = False

def on_pet_label_release(event):
    """鼠标松开：没有发生拖拽位移则触发单击"""
    global is_dragging
    if not is_dragging:
        on_pet_click(event)
    is_dragging = False

pet_label.bind("<Button-1>", on_pet_label_press)
pet_label.bind("<B1-Motion>", on_pet_label_motion)
pet_label.bind("<ButtonRelease-1>", on_pet_label_release)
root.bind("<Double-1>", lambda e: open_chat_window())


# ====================================
# 台词气泡（优化：圆角+箭头+渐变配色）
# ====================================
bubble_window = None
bubble_canvas = None

def show_pet_line(text):
    """在宠物右侧弹出气泡，3秒后自动消失"""
    global bubble_window
    if bubble_window is not None:
        try:
            bubble_window.destroy()
        except Exception:
            pass
        bubble_window = None

    px = root.winfo_x()
    py = root.winfo_y()

    bubble_window = tk.Toplevel(root)
    bubble_window.overrideredirect(True)
    bubble_window.attributes("-topmost", True)
    bubble_window.configure(bg="#FFFFFF")

    # 文字标签
    lbl = tk.Label(bubble_window, text=text, font=("Microsoft YaHei UI", 12),
                   bg="#FFFFFF", fg="#222222", padx=12, pady=7)
    lbl.pack()

    bubble_window.update_idletasks()
    bh = lbl.winfo_reqheight() + 16  # 估算总高度

    # 小三角箭头（Canvas绘制）
    arw = tk.Canvas(bubble_window, width=8, height=8, bg="#FFFFFF",
                    highlightthickness=0, bd=0)
    arw.create_polygon(2, 0, 6, 0, 4, 6, fill="#FFFFFF", outline="")
    arw.place(x=10, y=bh - 8)

    bubble_window.geometry(f"+{px + PET_WIDTH + 8}+{py + PET_HEIGHT//2 - bh//2}")
    bubble_window.after(3000, hide_pet_line)


def hide_pet_line():
    """隐藏台词气泡"""
    global bubble_window
    if bubble_window is not None:
        try:
            bubble_window.destroy()
        except Exception:
            pass
        bubble_window = None


# ====================================
# 单击宠物 —— 随机台词
# ====================================
def on_pet_click(event):
    global CURRENT_LINE
    CURRENT_LINE = random.choice(CLICK_LINES)
    show_pet_line(CURRENT_LINE)
    set_pet_state("talking")
    root.after(1500, lambda: set_pet_state("idle"))


# ====================================
# 双击宠物 —— 打开AI聊天窗口（苹果风）
# ====================================
chat_window_ref = None

def open_chat_window():
    global chat_window_ref
    if chat_window_ref is not None:
        try:
            chat_window_ref.lift()
            chat_window_ref.attributes("-topmost", True)
            chat_window_ref.attributes("-topmost", False)
            chat_window_ref.focus_force()
            return
        except Exception:
            pass

    # ===== 创建聊天窗口 =====
    chat_win = tk.Toplevel(root)
    chat_win.title("AI小新")
    chat_win.geometry("440x660")
    chat_win.minsize(380, 520)
    chat_win.configure(bg="#ffffff")
    chat_win.overrideredirect(False)
    chat_win.attributes("-toolwindow", True)
    chat_win.attributes("-topmost", True)   # 必须置顶，否则被主宠物窗口盖住
    chat_win.lift()
    chat_win.focus_force()                  # 强制获取焦点，弹出到最前

    # ===== 颜色常量（高对比度设计） =====
    C_NAV_BG    = "#007aff"     # 顶部导航栏：蓝色
    C_CHAT_BG   = "#f0f0f5"     # 聊天记录区：浅灰
    C_BUBBLE_AI = "#ffffff"     # AI气泡：纯白
    C_BUBBLE_US = "#007aff"     # 用户气泡：蓝色
    C_INPUT_BG  = "#ffffff"     # 输入区：纯白
    C_SEND_BG   = "#007aff"     # 发送按钮：蓝色
    C_TEXT_DARK = "#1d1d1f"     # 深色文字
    C_TEXT_LIGHT= "#ffffff"     # 浅色文字
    C_PLACEHOLDER = "#999999"   # 占位符文字
    C_DIVIDER   = "#e0e0e5"     # 分隔线颜色

    # ===== 顶部导航栏 =====
    nav_bar = tk.Frame(chat_win, bg=C_NAV_BG, height=56)
    nav_bar.pack(fill=tk.X)
    nav_bar.pack_propagate(False)

    tk.Label(nav_bar, text="🐾  AI小新", font=("Segoe UI", 15, "bold"),
             bg=C_NAV_BG, fg=C_TEXT_LIGHT).pack(side=tk.LEFT, padx=16, pady=16)

    status_label = tk.Label(nav_bar, text="● 在线", font=("Segoe UI", 10),
                            bg=C_NAV_BG, fg="#9ffaf5")
    status_label.pack(side=tk.RIGHT, padx=16, pady=16)

    # ===== 聊天记录区（Canvas + Scrollbar）=====
    chat_area = tk.Frame(chat_win, bg=C_CHAT_BG)
    chat_area.place(x=0, y=56, width=440, height=532)

    MAX_BUBBLE_W = 380
    BUBBLE_PAD_X = 14
    BUBBLE_PAD_Y = 10
    ROW_PAD = 10
    VISIBLE_H = 532

    chat_canvas = tk.Canvas(chat_area, bg=C_CHAT_BG,
                            highlightthickness=0, bd=0)
    chat_canvas.place(x=0, y=0, width=424, height=532)

    _font = tkfont.Font(family="Segoe UI", size=12)

    chat_scroll = tk.Scrollbar(chat_area, orient=tk.VERTICAL,
                                command=chat_canvas.yview, width=16)
    chat_scroll.place(x=424, y=0, width=16, height=532)
    chat_canvas.configure(yscrollcommand=chat_scroll.set)

    chat_msg_list = []
    _clearing = False
    _last_y = 0  # 记录最后一行底部 y 坐标，用于增量渲染

    def _split_lines(content, max_width):
        """用 Canvas font 实际测量，按像素宽度折行"""
        if not content:
            return [""]
        lines = []
        for orig in content.splitlines():
            if not orig:
                lines.append("")
                continue
            s = 0
            while s < len(orig):
                e = min(s + 1, len(orig))
                while e < len(orig) and _font.measure(orig[s:e]) <= max_width:
                    e += 1
                lines.append(orig[s:e])
                s = e
        return lines

    def _draw_bubble(y, msg):
        """在 y 位置绘制一条气泡，返回气泡高度"""
        role, content = msg["role"], msg["content"]
        is_right = (role == "user")
        bg = C_BUBBLE_US if is_right else C_BUBBLE_AI
        fg = C_TEXT_LIGHT if is_right else C_TEXT_DARK
        if role == "err":
            fg, bg = "#ff453a", "#ffe5e5"

        lh = _font.metrics("ascent") + 1  # 字体实际高度，+1 补偿基线间隙

        # 思考气泡：固定 80px 宽，固定一行高
        if role == "thinking":
            bh = lh + BUBBLE_PAD_Y * 2
            bw = 80
            x = 8
            dots = content.replace("思考", "")
            chat_canvas.create_rectangle(x, y, x + bw, y + bh, fill=bg, outline="")
            chat_canvas.create_text(x + bw // 2, y + bh // 2,
                                    text=f"思考{dots}", font=_font,
                                    fill=fg, anchor=tk.CENTER, tag="thinking")
            return bh + ROW_PAD

        # 用 Canvas font 测量每行实际宽度
        lines = content.splitlines() if content else [""]
        line_widths = [_font.measure(l) for l in lines]
        bw = min(max(80, max(line_widths) + BUBBLE_PAD_X * 2), MAX_BUBBLE_W)
        x = 424 - 8 - bw if is_right else 8

        # 对过长的行按像素宽度再折行
        max_cw = bw - BUBBLE_PAD_X * 2
        final_lines = _split_lines(content, max_cw)

        bh = max(lh * len(final_lines), lh) + BUBBLE_PAD_Y * 2

        chat_canvas.create_rectangle(x, y, x + bw, y + bh, fill=bg, outline="")
        for li, line in enumerate(final_lines):
            chat_canvas.create_text(x + bw // 2, y + BUBBLE_PAD_Y + lh // 2 + li * lh,
                                    text=line, font=_font, fill=fg,
                                    anchor=tk.CENTER, tag=f"msg_{len(chat_msg_list)}")
        return bh + ROW_PAD

    def render_chat():
        chat_win.after_idle(_do_render)

    def _do_render():
        chat_canvas.delete("all")
        y = 8
        for i, msg in enumerate(chat_msg_list):
            h = _draw_bubble(y, msg)
            y += h
        total_h = max(y, VISIBLE_H)
        chat_canvas.configure(scrollregion=(0, 0, 424, total_h))
        chat_canvas.yview_moveto(1.0)
        _last_y = total_h
        print(f"[render_chat] msgs={len(chat_msg_list)} total_h={total_h}")

    # ===== 底部输入区域（固定 72px，靠底部）=====
    input_frame = tk.Frame(chat_win, bg=C_INPUT_BG, height=72)
    input_frame.place(x=0, y=588, width=440, height=72)
    input_frame.pack_propagate(False)

    msg_entry = tk.Entry(input_frame,
        font=("Segoe UI", 13),
        bg="#e8e8ed", fg=C_TEXT_DARK,
        relief="flat", borderwidth=0,
        insertbackground=C_TEXT_DARK,
        highlightthickness=0
    )
    msg_entry.place(x=16, y=14, width=326, height=44)
    msg_entry.insert(0, "说点什么…")
    msg_entry.bind("<FocusOut>", lambda e: (msg_entry.delete(0, tk.END), msg_entry.insert(0, "说点什么…")) if msg_entry.get() == "" and not _clearing else None)
    msg_entry.bind("<FocusIn>",  lambda e: msg_entry.delete(0, tk.END) if msg_entry.get() == "说点什么…" else None)

    # 输入框底部边框线
    tk.Frame(input_frame, bg=C_DIVIDER, height=1).place(x=16, y=57, width=326, height=1)

    send_btn = tk.Button(input_frame, text="发送", font=("Segoe UI", 12, "bold"),
                         bg=C_SEND_BG, fg=C_TEXT_LIGHT,
                         relief="flat", borderwidth=0,
                         cursor="hand2", activebackground="#005ec4",
                         command=lambda: send_message(msg_entry.get()))
    send_btn.place(x=352, y=14, width=72, height=44)

    msg_entry.bind("<Return>", lambda e: send_message(msg_entry.get()))

    # ===== 发送消息函数 =====
    _thinking_idx = {"idx": None}

    def send_message(user_text):
        nonlocal _thinking_idx, _clearing
        text = user_text.strip()
        if not text or text == "说点什么…":
            return

        send_btn.config(state=tk.DISABLED)
        status_label.config(text="● 思考中…", fg="#ffd60a")

        # 用户消息
        chat_messages.append({"role": "user", "content": text})
        chat_msg_list.append({"role": "user", "content": text})
        _clearing = True
        msg_entry.delete(0, tk.END)
        _clearing = False
        render_chat()

        # 插入思考中临时标记
        _thinking_idx["idx"] = len(chat_msg_list)
        chat_msg_list.append({"role": "thinking", "content": "思考"})

        # 思考点跳动动画（在 UI 线程中运行）
        _dot_count = [0]
        def _animate_dots():
            _dot_count[0] = (_dot_count[0] % 3) + 1
            dots = "." * _dot_count[0]
            if _thinking_idx["idx"] is not None:
                chat_msg_list[_thinking_idx["idx"]] = {"role": "thinking", "content": f"思考{dots}"}
                render_chat()
            if send_btn.cget("state") == tk.DISABLED:
                chat_win.after(400, _animate_dots)
        _animate_dots()

        # 用线程调用 Ollama，避免阻塞主循环
        def _fetch_response():
            try:
                print("[_fetch_response] calling ollama...")
                response = ollama_client.chat(
                    model=MODEL_NAME,
                    messages=chat_messages,
                    options={"timeout": 60}
                )
                ai_reply = response.message.content
                print(f"[_fetch_response] got reply: {ai_reply[:50]}")
                chat_messages.append({"role": "assistant", "content": ai_reply})

                def _on_done():
                    if _thinking_idx["idx"] is not None:
                        chat_msg_list.pop(_thinking_idx["idx"])
                        _thinking_idx["idx"] = None
                    chat_msg_list.append({"role": "assistant", "content": ai_reply})
                    print(f"[_on_done] messages={len(chat_msg_list)}")
                    render_chat()
                    send_btn.config(state=tk.NORMAL)
                    status_label.config(text="● 在线", fg="#9ffaf5")

                chat_win.after(0, _on_done)

            except Exception as e:
                print(f"[_fetch_response] ERROR: {e}")
                import traceback
                traceback.print_exc()
                def _on_error():
                    if _thinking_idx["idx"] is not None:
                        chat_msg_list.pop(_thinking_idx["idx"])
                        _thinking_idx["idx"] = None
                    chat_msg_list.append({"role": "err", "content": f"出错了：{e}"})
                    render_chat()
                    send_btn.config(state=tk.NORMAL)
                    status_label.config(text="● 离线", fg="#ff453a")
                chat_win.after(0, _on_error)

        threading.Thread(target=_fetch_response, daemon=True).start()

    # 关闭时清空历史
    def close_chat_window():
        nonlocal chat_msg_list
        global chat_window_ref
        chat_messages.clear()
        chat_msg_list.clear()
        chat_window_ref = None
        chat_win.destroy()
    chat_win.protocol("WM_DELETE_WINDOW", close_chat_window)

    chat_window_ref = chat_win

    # 小新开场白
    chat_win.after(600, lambda: (
        chat_messages.append({"role": "assistant", "content": "哟，你终于来找我玩啦！"}),
        chat_msg_list.append({"role": "assistant", "content": "哟，你终于来找我玩啦！"}),
        render_chat()
    ))


# ====================================
# 单击/双击区分（已通过上面的 on_pet_label_press/release 统一处理）
# ====================================


# ====================================
# 右键菜单
# ====================================
context_menu = tk.Menu(root, tearoff=0, font=("Microsoft YaHei UI", 11))
context_menu.add_command(label="🐾 和我聊天", command=open_chat_window)
context_menu.add_separator()

def on_say_something():
    global CURRENT_LINE
    CURRENT_LINE = random.choice(TALK_LINES)
    show_pet_line(CURRENT_LINE)

def on_change_line():
    global CURRENT_LINE
    new_line = random.choice(TALK_LINES)
    while new_line == CURRENT_LINE and len(TALK_LINES) > 1:
        new_line = random.choice(TALK_LINES)
    CURRENT_LINE = new_line
    show_pet_line(CURRENT_LINE)

context_menu.add_command(label="💬 说句话", command=on_say_something)
context_menu.add_command(label="🔄 换一句", command=on_change_line)
context_menu.add_separator()
for _st in STATE_ROWS:
    context_menu.add_command(label=f"💫 {_st}", command=lambda s=_st: set_pet_state(s))
context_menu.add_separator()
context_menu.add_command(
    label="ℹ 关于",
    command=lambda: messagebox.showinfo(
        "🐾 关于 AI小新",
        "AI小新 v1.2\n\n一个住在桌面上的AI宠物。\n双击聊天，右键互动。\n\nPython + Tkinter + Ollama"
    )
)

def on_exit():
    root.quit()
    root.destroy()

context_menu.add_command(label="❌ 退出", command=on_exit)

def show_context_menu(event):
    context_menu.post(event.x_root, event.y_root)

pet_label.bind("<Button-3>", show_context_menu)


# ====================================
# 启动
# ====================================
if __name__ == "__main__":
    show_start_warnings()
    root.mainloop()
# 启动
# ====================================
if __name__ == "__main__":
    show_start_warnings()
    root.mainloop()

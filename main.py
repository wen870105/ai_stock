import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
# from plyer import notification # Removed dependency
from stock_utils import StockDataFetcher
import datetime
from hotkey_manager import HotkeyManager

import json
import os

WATCHLIST_FILE = "watchlist.json"

class AutocompleteEntry(ttk.Entry):
    """
    带有自动补全功能的输入框组件。
    当用户输入时，会弹出下拉列表显示匹配的建议。
    """
    def __init__(self, master, fetcher, **kwargs):
        super().__init__(master, **kwargs)
        self.fetcher = fetcher
        self.var = kwargs.get('textvariable')
        if not self.var:
            self.var = tk.StringVar()
            self.config(textvariable=self.var)
        
        self.var.trace('w', self.on_change)
        self.bind("<Return>", self.on_return)
        self.bind("<Down>", self.on_down)
        self.bind("<Up>", self.on_up)
        self.bind("<FocusOut>", self.on_focus_out)
        
        self.suggestion_window = None
        self.listbox = None

    def on_change(self, *args):
        """当输入内容变化时触发"""
        query = self.var.get().strip()
        if not query:
            self.hide_suggestions()
            return
        
        # 获取建议
        suggestions = self.fetcher.get_suggestions(query)
        if suggestions:
            self.show_suggestions(suggestions)
        else:
            self.hide_suggestions()

    def show_suggestions(self, suggestions):
        """显示建议列表窗口"""
        if not self.suggestion_window:
            self.suggestion_window = tk.Toplevel(self)
            self.suggestion_window.wm_overrideredirect(True) # 无边框窗口
            self.suggestion_window.wm_attributes("-topmost", True)
            
            self.listbox = tk.Listbox(self.suggestion_window, height=5)
            self.listbox.pack(fill="both", expand=True)
            self.listbox.bind("<<ListboxSelect>>", self.on_select)
        
        # 更新位置（每次都需要更新，因为主窗口可能移动）
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        self.suggestion_window.geometry(f"{self.winfo_width()}x100+{x}+{y}")
        
        self.listbox.delete(0, tk.END)
        for code, name in suggestions:
            self.listbox.insert(tk.END, f"{code} | {name}")
        
        self.suggestion_window.deiconify()

    def hide_suggestions(self):
        """隐藏建议列表窗口"""
        if self.suggestion_window:
            self.suggestion_window.withdraw()

    def on_select(self, event):
        """当用户点击列表项时触发"""
        if self.listbox:
            selection = self.listbox.curselection()
            if selection:
                item = self.listbox.get(selection[0])
                code = item.split(" | ")[0]
                self.var.set(code)
                self.hide_suggestions()
                # 触发确认事件（模拟回车）
                self.event_generate("<<AutocompleteSelected>>")

    def on_return(self, event):
        """回车键处理"""
        if self.suggestion_window and self.suggestion_window.state() == "normal":
            # 如果建议窗口显示中，回车选择当前高亮项
            if self.listbox and self.listbox.curselection():
                self.on_select(None)
                return "break" # 阻止默认的回车行为
        
        self.hide_suggestions()
        # 如果没有选中建议，或者建议窗口没显示，也触发确认事件
        # 这样外部可以通过绑定 <<AutocompleteSelected>> 来处理所有回车提交
        self.event_generate("<<AutocompleteSelected>>")

    def on_down(self, event):
        """向下箭头键选择建议"""
        if self.suggestion_window and self.suggestion_window.state() == "normal" and self.listbox:
            current_selection = self.listbox.curselection()
            if current_selection:
                index = current_selection[0]
                if index < self.listbox.size() - 1:
                    self.listbox.selection_clear(0, tk.END)
                    self.listbox.selection_set(index + 1)
                    self.listbox.activate(index + 1)
                    self.listbox.see(index + 1)
            else:
                if self.listbox.size() > 0:
                    self.listbox.selection_set(0)
                    self.listbox.activate(0)
                    self.listbox.see(0)
            return "break"

    def on_up(self, event):
        """向上箭头键"""
        if self.suggestion_window and self.suggestion_window.state() == "normal" and self.listbox:
            current_selection = self.listbox.curselection()
            if current_selection:
                index = current_selection[0]
                if index > 0:
                    self.listbox.selection_clear(0, tk.END)
                    self.listbox.selection_set(index - 1)
                    self.listbox.activate(index - 1)
                    self.listbox.see(index - 1)
            else:
                # 如果之前没有选中，且按下上键，选中最后一项
                size = self.listbox.size()
                if size > 0:
                    self.listbox.selection_set(size - 1)
                    self.listbox.activate(size - 1)
                    self.listbox.see(size - 1)
            return "break"

    def on_focus_out(self, event):
        """失去焦点时延迟关闭建议窗口"""
        # 延迟关闭，以便处理点击列表项的事件
        self.after(200, self.hide_suggestions)

class StockApp:
    """
    股价监控主应用程序类
    """
    def __init__(self, root):
        self.root = root
        self.root.title("实时监控与提醒")
        self.root.geometry("800x600")

        # 数据获取器实例
        self.fetcher = StockDataFetcher()
        # 监控列表：code -> {data, alert_settings, last_alert_time}
        self.watchlist = {} 
        self.is_monitoring = False
        self.monitor_thread = None

        # 全局热键管理器
        self.hotkey_manager = HotkeyManager(self.on_global_hotkey)
        self.hotkey_manager.start()
        
        # 绑定应用内快捷键 Ctrl+A
        # 注意：这里需要绑定到 root，但 AutocompleteEntry 可能会抢占事件
        # 如果 AutocompleteEntry 有焦点，且它是 Entry 的子类，默认 Ctrl+A 是全选
        # 我们可以通过 bind_all 来覆盖，或者让 AutocompleteEntry 处理
        self.root.bind_all("<Control-a>", self.on_ctrl_a)

        self._init_ui()
        
        # 加载上次保存的监控列表
        self.load_watchlist()

    def load_watchlist(self):
        """加载保存的监控列表"""
        if not os.path.exists(WATCHLIST_FILE):
            return

        try:
            with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)
            
            if not saved_data:
                return
            
            # 批量获取当前价格以更新 base_price
            codes = list(saved_data.keys())
            current_data_map = self.fetcher.get_real_time_data(codes)
            
            for code, settings in saved_data.items():
                # 恢复设置
                # 确保必要的字段存在
                settings.setdefault('alert_high', 0.0)
                settings.setdefault('alert_low', 0.0)
                settings.setdefault('alert_percent', 0.0)
                settings['last_alert_time'] = 0 # 重置上次提醒时间
                
                if code in current_data_map:
                    data = current_data_map[code]
                    settings['base_price'] = data['price']
                    settings['name'] = data['name'] # 更新名称以防万一
                    
                    self.watchlist[code] = settings
                    self.update_tree_item(code, data)
                else:
                    # 获取失败，可能是停牌或代码错误，暂时保留旧数据
                    settings.setdefault('base_price', 0.0)
                    self.watchlist[code] = settings
                    # 显示在列表中，但价格显示为 "-"
                    fmt = self._get_price_format(code)
                    self.tree.insert("", "end", iid=code, values=(
                        code, settings.get('name', '未知'), "-", "-", 
                        fmt.format(settings['alert_high']) if settings['alert_high'] > 0 else "-",
                        fmt.format(settings['alert_low']) if settings['alert_low'] > 0 else "-",
                        f"{settings['alert_percent']:.2f}%" if settings['alert_percent'] > 0 else "-"
                    ))
            
            self.status_var.set(f"已加载 {len(self.watchlist)} 个监控项")
            
        except Exception as e:
            print(f"加载监控列表失败: {e}")
            messagebox.showerror("错误", f"加载监控列表失败: {e}")

    def save_watchlist(self):
        """保存监控列表到文件"""
        try:
            # 获取 Treeview 中的顺序，保证保存顺序与 UI 一致
            ordered_codes = self.tree.get_children()
            
            # 构建有序字典
            ordered_watchlist = {}
            for code in ordered_codes:
                if code in self.watchlist:
                    ordered_watchlist[code] = self.watchlist[code]
            
            # 将剩余的（可能未显示在 treeview 中但存在于 watchlist 的，理论上不应该有）也加上
            for code, data in self.watchlist.items():
                if code not in ordered_watchlist:
                    ordered_watchlist[code] = data
            
            # 更新 self.watchlist 为有序版本 (Python 3.7+ dict is ordered)
            self.watchlist = ordered_watchlist

            with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
                # 序列化 self.watchlist
                json.dump(self.watchlist, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存监控列表失败: {e}")

    def on_ctrl_a(self, event):
        """处理应用内 Ctrl+A 事件"""
        # 隐藏窗口
        self.root.withdraw()
        
        # 注册全局热键，以便恢复
        # 使用 after 确保不会阻塞 GUI
        self.root.after(100, self.hotkey_manager.register_hotkey)
        
        return "break" # 阻止默认行为（如全选）

    def on_global_hotkey(self):
        """处理全局热键回调（在热键线程触发，需切回主线程）"""
        self.root.after(0, self.restore_window)

    def restore_window(self):
        """恢复显示窗口"""
        self.root.deiconify()
        # 恢复窗口并设为前台
        self.root.lift()
        self.root.focus_force()
        
        # 注销全局热键，避免影响系统其他程序
        self.hotkey_manager.unregister_hotkey()

    def _init_ui(self):
        """初始化用户界面"""
        # 输入区域
        input_frame = ttk.LabelFrame(self.root, text="添加代码/名称")
        input_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(input_frame, text="代码/名称:").pack(side="left", padx=5)
        
        self.input_var = tk.StringVar()
        # 使用自定义的自动补全输入框
        self.input_entry = AutocompleteEntry(input_frame, self.fetcher, textvariable=self.input_var, width=30)
        self.input_entry.pack(side="left", padx=5)
        # 绑定自定义选择事件（包括回车提交）
        self.input_entry.bind('<<AutocompleteSelected>>', lambda e: self.add_stock())
        # 注意：不要再绑定 <Return>，因为 AutocompleteEntry 内部已经处理了，并通过 <<AutocompleteSelected>> 通知外部

        ttk.Button(input_frame, text="添加", command=self.add_stock).pack(side="left", padx=5)
        ttk.Button(input_frame, text="删除选中", command=self.delete_stock).pack(side="left", padx=5)
        
        # 控制区域
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill="x", padx=10, pady=5)
        
        self.start_btn = ttk.Button(control_frame, text="开始监控", command=self.start_monitoring)
        self.start_btn.pack(side="left", padx=5)
        
        self.stop_btn = ttk.Button(control_frame, text="停止监控", command=self.stop_monitoring, state="disabled")
        self.stop_btn.pack(side="left", padx=5)

        # 排序按钮
        ttk.Button(control_frame, text="↑ 上移", command=self.move_up).pack(side="left", padx=5)
        ttk.Button(control_frame, text="↓ 下移", command=self.move_down).pack(side="left", padx=5)

        # 股票列表显示区域 (Treeview)
        columns = ("code", "name", "price", "percent", "alert_high", "alert_low", "alert_percent")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings")
        
        self.tree.heading("code", text="代码")
        self.tree.heading("name", text="名称")
        self.tree.heading("price", text="当前价")
        self.tree.heading("percent", text="涨跌幅(%)")
        self.tree.heading("alert_high", text="价格上限")
        self.tree.heading("alert_low", text="价格下限")
        self.tree.heading("alert_percent", text="涨跌幅阈值(%)")
        
        self.tree.column("code", width=80, anchor="center")
        self.tree.column("name", width=100, anchor="center")
        self.tree.column("price", width=80, anchor="e")
        self.tree.column("percent", width=80, anchor="e")
        self.tree.column("alert_high", width=80, anchor="center")
        self.tree.column("alert_low", width=80, anchor="center")
        self.tree.column("alert_percent", width=100, anchor="center")

        self.tree.pack(fill="both", expand=True, padx=10, pady=5)
        self.tree.bind("<Double-1>", self.on_double_click)
        
        # 拖拽排序支持
        self.tree.bind("<Button-1>", self.on_drag_start)
        self.tree.bind("<B1-Motion>", self.on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self.on_drag_release)
        self.drag_data = {"item": None, "index": None}

        # 状态栏
        self.status_var = tk.StringVar()
        self.status_var.set("就绪")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.pack(fill="x", side="bottom")

    def add_stock(self):
        """添加股票到监控列表"""
        query = self.input_var.get().strip()
        if not query:
            return

        # 先尝试搜索
        code, name, prefix = self.fetcher.search_stock(query)
        if not code:
            messagebox.showerror("错误", f"未找到股票/债券: {query}")
            return

        if code in self.watchlist:
            messagebox.showinfo("提示", "该股票已在列表中")
            self.input_var.set("") # 清空输入框
            return

        # 初始获取数据以验证并显示
        data_map = self.fetcher.get_real_time_data(code)
        if not data_map or code not in data_map:
            messagebox.showerror("错误", "无法获取实时数据，请检查网络或代码是否正确")
            return
        
        data = data_map[code]

        self.watchlist[code] = {
            "name": data['name'],
            "alert_high": 0.0,
            "alert_low": 0.0,
            "alert_percent": 0.0, 
            "last_alert_time": 0,
            "base_price": data['price'] 
        }

        self.update_tree_item(code, data)
        self.save_watchlist()
        self.input_var.set("")
        self.status_var.set(f"已添加: {data['name']}")
        
        # 隐藏建议窗口（以防万一）
        self.input_entry.hide_suggestions()

    def delete_stock(self):
        """删除选中的股票"""
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先在列表中选中要删除的股票")
            return
        
        # 确认删除
        if not messagebox.askyesno("确认", "确定要删除选中的股票吗？"):
            return

        for item_id in selection:
            if item_id in self.watchlist:
                del self.watchlist[item_id]
            self.tree.delete(item_id)
        
        self.save_watchlist()
        self.status_var.set("已删除选中股票")

    def _get_price_format(self, code):
        """根据股票代码判断价格显示格式"""
        # ETF (沪市 51/56/58, 深市 159)
        if code.startswith(('51', '56', '58', '159')):
            return "{:.3f}"
        # 可转债 (沪市 11, 深市 12)
        if code.startswith(('11', '12')):
            return "{:.3f}"
        # B股 (沪市 900, 深市 200) - 通常保留3位
        if code.startswith(('900', '200')):
            return "{:.3f}"
            
        return "{:.2f}"

    def update_tree_item(self, code, data=None):
        """更新列表中的单行数据"""
        if not data:
            # 如果没有新数据，保留原有显示或显示占位符
            # 这里简单处理，实际上应该不会发生
            return

        settings = self.watchlist[code]
        
        # 格式化颜色：涨红跌绿
        price_val = data['price']
        percent_val = data['percent']
        
        # 获取价格格式
        fmt = self._get_price_format(code)
        
        # 注意：这里我们只更新数值，Treeview 的颜色设置比较繁琐（需要 tag），暂时只显示数值
        
        values = (
            code,
            data['name'],
            fmt.format(price_val),
            f"{percent_val:.2f}%",
            fmt.format(settings['alert_high']) if settings['alert_high'] > 0 else "-",
            fmt.format(settings['alert_low']) if settings['alert_low'] > 0 else "-",
            f"{settings['alert_percent']:.2f}%" if settings['alert_percent'] > 0 else "-"
        )

        if self.tree.exists(code):
            self.tree.item(code, values=values)
        else:
            self.tree.insert("", "end", iid=code, values=values)

    def on_double_click(self, event):
        """双击列表项打开设置窗口"""
        selection = self.tree.selection()
        if not selection:
            return
        item_id = selection[0]
        self.open_settings_dialog(item_id)
        # 阻止事件传播，避免与拖拽冲突（虽然双击通常在 release 之后，但为了保险）
        return "break"

    def on_drag_start(self, event):
        """鼠标按下，开始准备拖拽"""
        item = self.tree.identify_row(event.y)
        if item:
            self.drag_data["item"] = item
            self.drag_data["index"] = self.tree.index(item)
            
    def on_drag_motion(self, event):
        """鼠标移动，执行拖拽"""
        if not self.drag_data["item"]:
            return
            
        target_item = self.tree.identify_row(event.y)
        if target_item and target_item != self.drag_data["item"]:
            try:
                # 获取目标位置的 index
                index = self.tree.index(target_item)
                # 执行移动
                self.tree.move(self.drag_data["item"], "", index)
            except Exception:
                pass

    def on_drag_release(self, event):
        """鼠标释放，结束拖拽并保存"""
        if self.drag_data["item"]:
            # 无论是否真正移动，都尝试保存一下，确保顺序正确
            # 为了性能，可以判断 index 是否变了
            current_index = self.tree.index(self.drag_data["item"])
            if current_index != self.drag_data["index"]:
                self.save_watchlist()
            
            self.drag_data = {"item": None, "index": None}

    def move_up(self):
        """将选中项上移"""
        selection = self.tree.selection()
        if not selection:
            return
        
        for item in selection:
            index = self.tree.index(item)
            if index > 0:
                self.tree.move(item, "", index - 1)
        
        self.save_watchlist()

    def move_down(self):
        """将选中项下移"""
        selection = self.tree.selection()
        if not selection:
            return
        
        # 倒序遍历，避免移动后索引混乱
        for item in reversed(selection):
            index = self.tree.index(item)
            if index < len(self.tree.get_children()) - 1:
                self.tree.move(item, "", index + 1)
                
        self.save_watchlist()

    def open_settings_dialog(self, code):
        """打开提醒设置对话框"""
        settings = self.watchlist[code]
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"设置提醒 - {settings['name']}")
        dialog.geometry("300x250")
        
        # 居中显示
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 150
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 125
        dialog.geometry(f"+{x}+{y}")

        ttk.Label(dialog, text="价格上限 (>):").pack(pady=5)
        high_var = tk.DoubleVar(value=settings['alert_high'])
        ttk.Entry(dialog, textvariable=high_var).pack()

        ttk.Label(dialog, text="价格下限 (<):").pack(pady=5)
        low_var = tk.DoubleVar(value=settings['alert_low'])
        ttk.Entry(dialog, textvariable=low_var).pack()

        ttk.Label(dialog, text="涨跌幅阈值 (%, 绝对值):").pack(pady=5)
        pct_var = tk.DoubleVar(value=settings['alert_percent'])
        ttk.Entry(dialog, textvariable=pct_var).pack()

        def save():
            try:
                self.watchlist[code]['alert_high'] = high_var.get()
                self.watchlist[code]['alert_low'] = low_var.get()
                self.watchlist[code]['alert_percent'] = pct_var.get()
                
                self.save_watchlist()

                # 立即更新界面显示
                current_values = list(self.tree.item(code, 'values'))
                fmt = self._get_price_format(code)
                
                alert_high = self.watchlist[code]['alert_high']
                alert_low = self.watchlist[code]['alert_low']
                alert_percent = self.watchlist[code]['alert_percent']
                
                # 更新提醒相关的列 (索引 4, 5, 6)
                if len(current_values) >= 7:
                    current_values[4] = fmt.format(alert_high) if alert_high > 0 else "-"
                    current_values[5] = fmt.format(alert_low) if alert_low > 0 else "-"
                    current_values[6] = f"{alert_percent:.2f}%" if alert_percent > 0 else "-"
                    
                    self.tree.item(code, values=current_values)
                
                self.status_var.set(f"已更新 {settings['name']} 的设置")
                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "请输入有效的数字")

        ttk.Button(dialog, text="保存", command=save).pack(pady=10)

    def start_monitoring(self):
        """开始后台监控"""
        if not self.watchlist:
            messagebox.showwarning("警告", "请先添加股票")
            return
        
        self.is_monitoring = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("正在监控...")
        
        self.monitor_loop()

    def stop_monitoring(self):
        """停止后台监控"""
        self.is_monitoring = False
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("监控已停止")

    def monitor_loop(self):
        """监控主循环，定期刷新数据"""
        if not self.is_monitoring:
            return

        codes = list(self.watchlist.keys())
        if codes:
            # 批量获取数据
            data_map = self.fetcher.get_real_time_data(codes)
            if data_map:
                for code, data in data_map.items():
                    if code in self.watchlist:
                        self.update_tree_item(code, data)
                        self.check_alert(code, data)
        
        # 每 3 秒刷新一次
        self.root.after(3000, self.monitor_loop)

    def check_alert(self, code, data):
        """检查是否触发提醒条件"""
        settings = self.watchlist[code]
        price = data['price']
        percent = data['percent']
        name = data['name']
        
        triggered = False
        msg = ""

        # 检查价格上限
        if settings['alert_high'] > 0 and price >= settings['alert_high']:
            triggered = True
            msg = f"{name} ({code}) 价格达到 {price}, 高于设定上限 {settings['alert_high']}"

        # 检查价格下限
        elif settings['alert_low'] > 0 and price <= settings['alert_low']:
            triggered = True
            msg = f"{name} ({code}) 价格达到 {price}, 低于设定下限 {settings['alert_low']}"

        # 检查涨跌幅阈值 (绝对值)
        elif settings['alert_percent'] > 0 and abs(percent) >= settings['alert_percent']:
            triggered = True
            msg = f"{name} ({code}) 涨跌幅 {percent:.2f}%, 超过设定阈值 {settings['alert_percent']}%"

        if triggered:
            now = time.time()
            # 冷却时间: 5分钟 (300秒)
            if now - settings['last_alert_time'] > 300:
                self.send_notification(msg)
                self.watchlist[code]['last_alert_time'] = now

    def send_notification(self, message):
        """发送桌面弹窗提醒"""
        try:
            # 创建一个非阻塞的顶级窗口作为弹窗
            popup = tk.Toplevel(self.root)
            popup.title("提醒")
            # 去除窗口边框
            popup.overrideredirect(True)
            popup.attributes("-topmost", True)
            
            width = 300
            height = 100
            
            # 获取屏幕尺寸
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            
            # 计算右下角位置 (留出任务栏高度，大约40-50px，这里给60px余量)
            x = screen_width - width - 20
            y = screen_height - height - 60
            
            popup.geometry(f"{width}x{height}+{x}+{y}")
            
            # 添加边框效果
            frame = ttk.Frame(popup, relief="raised", borderwidth=2)
            frame.pack(fill="both", expand=True)
            
            # 标题栏模拟
            title_frame = ttk.Frame(frame)
            title_frame.pack(fill="x", padx=5, pady=2)
            ttk.Label(title_frame, text="提醒", font=("", 9, "bold")).pack(side="left")
            # 关闭按钮 (X)
            close_btn = ttk.Label(title_frame, text="✕", cursor="hand2")
            close_btn.pack(side="right")
            close_btn.bind("<Button-1>", lambda e: popup.destroy())
            
            # 内容
            content_frame = ttk.Frame(frame)
            content_frame.pack(fill="both", expand=True, padx=10, pady=5)
            
            lbl = ttk.Label(content_frame, text=message, wraplength=280, justify="left")
            lbl.pack(expand=True, anchor="w")
            
            # 10秒后自动关闭
            popup.after(10000, popup.destroy)
            
            # 尝试将窗口置顶并获取焦点 (但不抢占输入焦点以免打断用户工作)
            popup.lift()
            # popup.focus_force() # 注释掉，避免打断用户输入
            
        except Exception as e:
            print(f"Notification error: {e}")
            self.status_var.set(f"提醒: {message}")

if __name__ == "__main__":
    root = tk.Tk()
    app = StockApp(root)
    root.mainloop()

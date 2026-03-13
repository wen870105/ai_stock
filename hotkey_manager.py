
import ctypes
import ctypes.wintypes
import threading
import time

# Windows API Constants
WM_HOTKEY = 0x0312
WM_USER = 0x0400
CMD_REGISTER = WM_USER + 1
CMD_UNREGISTER = WM_USER + 2
MOD_CONTROL = 0x0002
VK_A = 0x41

class HotkeyManager:
    def __init__(self, on_hotkey_callback):
        self.on_hotkey_callback = on_hotkey_callback
        self.user32 = ctypes.windll.user32
        self.thread_id = None
        self.running = False
        self.thread = None
        
    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        
        # 等待线程启动并获取 native_id
        while self.thread_id is None:
            time.sleep(0.01)

    def _loop(self):
        self.thread_id = threading.get_native_id()
        self.user32 = ctypes.windll.user32
        
        # 强制创建消息队列
        msg = ctypes.wintypes.MSG()
        self.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        
        while self.running:
            # GetMessage 是阻塞的，直到收到消息
            # hWnd = None (NULL) 表示接收当前线程的所有消息
            # GetMessageW 第二个参数为 None 时，会接收当前线程的所有窗口消息和线程消息
            ret = self.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            
            if ret == -1: # Error
                print(f"GetMessage failed: {ctypes.get_last_error()}")
                break
            if ret == 0: # WM_QUIT
                break
            
            # 处理自定义消息
            if msg.message == CMD_REGISTER:
                # 注册热键 Ctrl+A
                # id=1, fsModifiers=MOD_CONTROL, vk=VK_A
                res = self.user32.RegisterHotKey(None, 1, MOD_CONTROL, VK_A)
                if not res:
                    print(f"RegisterHotKey failed: {ctypes.get_last_error()}")
                continue # 消耗消息，不 Dispatch
                    
            elif msg.message == CMD_UNREGISTER:
                # 注销热键
                res = self.user32.UnregisterHotKey(None, 1)
                if not res:
                     # ERROR_HOTKEY_NOT_REGISTERED (1419) is fine
                     err = ctypes.get_last_error()
                     if err != 1419:
                         print(f"UnregisterHotKey failed: {err}")
                continue # 消耗消息
            
            elif msg.message == WM_HOTKEY:
                # 收到热键，触发回调
                if self.on_hotkey_callback:
                    self.on_hotkey_callback()
                continue # 消耗消息

            self.user32.TranslateMessage(ctypes.byref(msg))
            self.user32.DispatchMessageW(ctypes.byref(msg))

    def register_hotkey(self):
        if self.thread_id:
            res = self.user32.PostThreadMessageW(self.thread_id, CMD_REGISTER, 0, 0)
            if not res:
                print(f"PostThreadMessageW failed: {ctypes.get_last_error()}")

    def unregister_hotkey(self):
        if self.thread_id:
            res = self.user32.PostThreadMessageW(self.thread_id, CMD_UNREGISTER, 0, 0)
            if not res:
                print(f"PostThreadMessageW failed: {ctypes.get_last_error()}")

    def stop(self):
        self.running = False
        if self.thread_id:
            self.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0) # WM_QUIT

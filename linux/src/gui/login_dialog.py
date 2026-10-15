"""
登录对话框
==========
支持二维码登录、Cookie 登录多种方式。
"""
import logging
import time
from io import BytesIO
from urllib.parse import urlparse, parse_qs

from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QWidget, QMessageBox
)
from qfluentwidgets import (
    TabWidget, LineEdit, PasswordLineEdit, PushButton,
    PrimaryPushButton, BodyLabel, CaptionLabel,
    isDarkTheme,
)

import qrcode

from ..config import get_config
from ..network import api_get, api_post

logger = logging.getLogger(__name__)


class LoginDialog(QDialog):
    """登录对话框"""

    login_success = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("B站登录")
        self.setMinimumSize(420, 480)
        self.resize(420, 480)
        # 适配深色模式
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setStyleSheet("QDialog { background: transparent; }")

        self._qr_code_url = ""
        self._qr_code_key = ""
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_qr_code)

        self._setup_ui()

    def _setup_ui(self):
        is_dark = isDarkTheme()
        
        if is_dark:
            bg_color = "#1E1E1E"  # 深色背景
        else:
            bg_color = "#FFFFFF"  # 浅色背景（纯白）
        
        # 去掉透明背景设置，直接使用明确的颜色
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setStyleSheet(f"QDialog {{ background: {bg_color}; border-radius: 10px; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        self.tab_widget = TabWidget()

        self.qr_tab = QWidget()
        self._setup_qr_tab()
        self.tab_widget.addTab(self.qr_tab, "二维码登录")

        self.cookie_tab = QWidget()
        self._setup_cookie_tab()
        self.tab_widget.addTab(self.cookie_tab, "Cookie登录")

        layout.addWidget(self.tab_widget)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    """def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        self.tab_widget = TabWidget()

        self.qr_tab = QWidget()
        self._setup_qr_tab()
        self.tab_widget.addTab(self.qr_tab, "二维码登录")

        self.cookie_tab = QWidget()
        self._setup_cookie_tab()
        self.tab_widget.addTab(self.cookie_tab, "Cookie登录")

        layout.addWidget(self.tab_widget)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)"""

    def _setup_qr_tab(self):
        layout = QVBoxLayout(self.qr_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)

        tip = BodyLabel("请使用B站APP扫描二维码登录")
        tip.setAlignment(Qt.AlignCenter)
        layout.addWidget(tip)

        self.qr_label = QLabel("正在获取二维码...")
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setFixedSize(220, 220)
        qr_border = "#666" if isDarkTheme() else "#ccc"
        qr_bg = "#2C2C2C" if isDarkTheme() else "#f5f5f5"
        self.qr_label.setStyleSheet(
            f"border: 2px dashed {qr_border}; border-radius: 10px; background: {qr_bg};"
        )
        layout.addWidget(self.qr_label, alignment=Qt.AlignCenter)

        refresh_btn = PushButton("刷新二维码")
        refresh_btn.clicked.connect(self._load_qr_code)
        layout.addWidget(refresh_btn, alignment=Qt.AlignCenter)

        self.qr_status = CaptionLabel("")
        self.qr_status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.qr_status)

        QTimer.singleShot(200, self._load_qr_code)

    def _load_qr_code(self):
        """获取二维码并显示"""
        try:
            self.qr_status.setText("正在获取二维码...")
            self._poll_timer.stop()

            response = api_get("https://passport.bilibili.com/x/passport-login/web/qrcode/generate")
            if response.get("code") != 0:
                self.qr_status.setText(f"获取失败: {response.get('message', '未知错误')}")
                return

            data = response["data"]
            self._qr_code_url = data.get("url", "")
            self._qr_code_key = data.get("qrcode_key", "")

            if not self._qr_code_url:
                self.qr_status.setText("获取失败: 返回数据为空")
                return

            # 用 qrcode 库生成二维码图片并显示
            qr = qrcode.QRCode(version=1, box_size=6, border=2,
                               error_correction=qrcode.constants.ERROR_CORRECT_M)
            qr.add_data(self._qr_code_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            buf = BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)

            pixmap = QPixmap()
            pixmap.loadFromData(buf.read())
            self.qr_label.setPixmap(pixmap.scaled(
                200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

            self.qr_status.setText("请使用B站APP扫描二维码")
            self._poll_timer.start(2000)

        except Exception as e:
            self.qr_status.setText(f"加载失败: {e}")

    def _poll_qr_code(self):
        """轮询二维码扫描状态"""
        if not self._qr_code_key:
            return

        try:
            response = api_get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
                params={"qrcode_key": self._qr_code_key}
            )

            if response.get("code") != 0:
                return

            data = response.get("data", {})
            code = data.get("code", -1)

            if code == 0:
                # 登录成功，从返回的 url 中解析 Cookie
                self._poll_timer.stop()
                self.qr_status.setText("登录成功！")

                redirect_url = data.get("url", "")
                cookies = self._extract_cookies_from_url(redirect_url)

                # 也尝试从 response headers 获取 cookie（httpx 会自动处理）
                if not cookies.get("SESSDATA"):
                    # 尝试从客户端 cookies 获取
                    from ..network import get_client
                    client = get_client()
                    sessdata = client.cookies.get("SESSDATA", "")
                    bili_jct = client.cookies.get("bili_jct", "")
                    if sessdata:
                        cookies["SESSDATA"] = sessdata
                    if bili_jct:
                        cookies["bili_jct"] = bili_jct

                if cookies.get("SESSDATA"):
                    self._apply_login_cookies(cookies)
                    self.accept()
                else:
                    self.qr_status.setText("登录成功但未能获取Cookie，请尝试Cookie登录")

            elif code == 86038:
                self._poll_timer.stop()
                self.qr_status.setText("二维码已失效，请刷新")
            elif code == 86090:
                self.qr_status.setText("已扫描，请在手机上确认")
            elif code == 86039:
                self.qr_status.setText("等待扫描中...")

        except Exception as e:
            logger.debug(f"轮询异常: {e}")

    @staticmethod
    def _extract_cookies_from_url(url: str) -> dict:
        """从B站登录回调URL中解析Cookie参数"""
        cookies = {}
        if not url:
            return cookies
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            for key in ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5"]:
                if key in params and params[key]:
                    cookies[key] = params[key][0]
        except Exception:
            pass
        return cookies

    def _setup_cookie_tab(self):
        layout = QVBoxLayout(self.cookie_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)

        tip = BodyLabel("粘贴浏览器中的 Cookie 进行登录")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        layout.addWidget(BodyLabel("SESSDATA:"))
        self.sessdata_edit = LineEdit()
        self.sessdata_edit.setPlaceholderText("从浏览器复制 SESSDATA 值")
        layout.addWidget(self.sessdata_edit)

        layout.addWidget(BodyLabel("bili_jct:"))
        self.bili_jct_edit = LineEdit()
        self.bili_jct_edit.setPlaceholderText("从浏览器复制 bili_jct 值")
        layout.addWidget(self.bili_jct_edit)

        login_btn = PrimaryPushButton("使用 Cookie 登录")
        login_btn.clicked.connect(self._cookie_login)
        layout.addWidget(login_btn)

        help_text = CaptionLabel(
            "获取 Cookie 方法：\n"
            "1. 在浏览器中登录 bilibili.com\n"
            "2. 按 F12 → Application → Cookies\n"
            "3. 复制 SESSDATA 和 bili_jct 的值"
        )
        help_text.setWordWrap(True)
        help_color = "#AAA" if isDarkTheme() else "#333"      # 深色用亮灰，浅色用深灰
        help_bg = "#2C2C2C" if isDarkTheme() else "#F5F5F5"   # 深色用深灰，浅色用浅灰
        help_text.setStyleSheet(f"color: {help_color}; padding: 10px; background: {help_bg}; border-radius: 5px;")
        layout.addWidget(help_text)
        layout.addStretch()

    def _cookie_login(self):
        sessdata = self.sessdata_edit.text().strip()
        bili_jct = self.bili_jct_edit.text().strip()

        if not sessdata or not bili_jct:
            QMessageBox.warning(self, "错误", "SESSDATA 和 bili_jct 不能为空")
            return

        cookies = {"SESSDATA": sessdata, "bili_jct": bili_jct}
        self._apply_login_cookies(cookies)
        self.accept()

    def _apply_login_cookies(self, cookies: dict):
        """应用登录 Cookie"""
        main_win = getattr(self, '_main_window', None) or self.parent()
        if main_win and hasattr(main_win, 'cookie_manager'):
            main_win.cookie_manager.set_login_cookies(
                cookies.get("SESSDATA", ""),
                cookies.get("bili_jct", "")
            )

        c = get_config()
        if "DedeUserID" in cookies:
            c.set(c.user_mid, cookies["DedeUserID"])
        c.set(c.is_login, True)
        c.set(c.is_expired, False)  # 清除过期标记

        if main_win and hasattr(main_win, 'login_status_changed'):
            main_win.login_status_changed.emit(True)

    def closeEvent(self, event):
        self._poll_timer.stop()
        super().closeEvent(event)


class CookieInputDialog(QDialog):
    """Cookie 输入对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("手动输入 Cookie")
        self.resize(500, 300)
        # 适配深色模式：设置透明背景，让 qfluentwidgets 组件自动着色
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setStyleSheet("QDialog { background: transparent; }")
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # 标题
        from qfluentwidgets import SubtitleLabel
        title = SubtitleLabel("🍪 手动输入 Cookie")
        layout.addWidget(title)

        hint = CaptionLabel("从浏览器开发者工具中复制 SESSDATA 和 bili_jct 的值")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(BodyLabel("SESSDATA:"))
        self.sessdata_edit = LineEdit()
        self.sessdata_edit.setPlaceholderText("从浏览器复制 SESSDATA 值")
        layout.addWidget(self.sessdata_edit)

        layout.addWidget(BodyLabel("bili_jct:"))
        self.bili_jct_edit = LineEdit()
        self.bili_jct_edit.setPlaceholderText("从浏览器复制 bili_jct 值")
        layout.addWidget(self.bili_jct_edit)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        ok_btn = PrimaryPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

    def get_cookies(self) -> dict:
        return {
            "SESSDATA": self.sessdata_edit.text().strip(),
            "bili_jct": self.bili_jct_edit.text().strip(),
        }

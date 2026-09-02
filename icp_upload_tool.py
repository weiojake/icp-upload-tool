import asyncio
import threading
import tkinter as tk
from tkinter import messagebox, filedialog, ttk
import logging
from pathlib import Path
import csv
import subprocess
import time
import socket
import re
import os
import shutil
import sys
import psutil
import customtkinter as ctk
from playwright.async_api import async_playwright

# ---------- 检测操作系统 ----------
IS_WINDOWS = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'

# ---------- 主题 ----------
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

# ---------- 超时配置 ----------
TIMEOUT_PAGE_LOAD = 6
TIMEOUT_BUTTON_ADD = 2
TIMEOUT_DIALOG_APPEAR = 2
TIMEOUT_CONFIRM_BUTTON = 1.5
TIMEOUT_RESPONSE = 4
TIMEOUT_DIALOG_CLOSE = 1.5
LOGIN_TIMEOUT = 300
BROWSER_START_TIMEOUT = 20  # 浏览器启动超时（秒）

# ---------- 通用配置 ----------
BASE_DIR = Path(__file__).parent.absolute()
DEBUG_PORT = 9222

# ---------- 浏览器路径自动查找（跨平台） ----------
def get_browser_path(browser_name):
    if browser_name == "Microsoft Edge":
        if IS_WINDOWS:
            path = shutil.which("msedge.exe")
            if not path:
                for p in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                          r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]:
                    if Path(p).exists():
                        path = p
                        break
            return path or r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        elif IS_MAC:
            # Mac 上 Edge 的路径
            path = shutil.which("Microsoft Edge")
            if not path:
                p = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
                if Path(p).exists():
                    path = p
            return path or "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
        else:
            return shutil.which("msedge") or shutil.which("microsoft-edge") or ""
    elif browser_name == "Google Chrome":
        if IS_WINDOWS:
            path = shutil.which("chrome.exe")
            if not path:
                for p in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]:
                    if Path(p).exists():
                        path = p
                        break
            return path or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        elif IS_MAC:
            path = shutil.which("google-chrome")
            if not path:
                p = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                if Path(p).exists():
                    path = p
            return path or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        else:
            return shutil.which("google-chrome") or shutil.which("chrome") or ""
    return ""

def get_user_data_dir(browser_name):
    """获取用户数据目录（跨平台）"""
    if browser_name == "Microsoft Edge":
        dir_name = "edge_script_profile"
    else:
        dir_name = "chrome_script_profile"
    
    # Mac 上放在 ~/Library/Application Support/ 下，Windows 放在当前目录
    if IS_MAC:
        # 使用用户主目录下的 Application Support
        home = Path.home()
        app_support = home / "Library" / "Application Support" / "ICP备案批量上传工具"
        return str(app_support / dir_name)
    else:
        return str(BASE_DIR / dir_name)

# ---------- 辅助函数 ----------
def is_port_open(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    return result == 0

def kill_browser_on_port(port):
    killed = False
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            name = proc.info['name'] or ''
            name_lower = name.lower()
            if 'msedge' in name_lower or 'chrome' in name_lower or 'Microsoft Edge' in name:
                cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
                if f'--remote-debugging-port={port}' in cmdline:
                    proc.kill()
                    killed = True
        except:
            pass
    return killed

def start_browser_debug(browser_name):
    """
    启动带调试端口的浏览器，返回 (是否成功, 错误信息)
    """
    browser_path = get_browser_path(browser_name)
    if not browser_path or not Path(browser_path).exists():
        return False, f"未找到 {browser_name} 浏览器，请确认已安装。"

    user_data_dir = get_user_data_dir(browser_name)

    # 确保用户数据目录存在
    try:
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, f"无法创建用户数据目录: {e}"

    # 清理可能占用的端口
    if is_port_open(DEBUG_PORT):
        kill_browser_on_port(DEBUG_PORT)
        time.sleep(1)

    # 启动浏览器
    try:
        # Windows 使用 CREATE_NO_WINDOW，Mac 不需要
        if IS_WINDOWS:
            subprocess.Popen([
                browser_path,
                f"--remote-debugging-port={DEBUG_PORT}",
                f"--user-data-dir={user_data_dir}",
                "--start-maximized",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-notifications",
                "--no-first-run"
            ], creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            # Mac/Linux 直接启动
            # Mac 上需要允许浏览器在后台运行
            subprocess.Popen([
                browser_path,
                f"--remote-debugging-port={DEBUG_PORT}",
                f"--user-data-dir={user_data_dir}",
                "--start-maximized",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-notifications",
                "--no-first-run"
            ])
    except Exception as e:
        return False, f"启动失败: {e}"

    # 等待端口开放
    for i in range(BROWSER_START_TIMEOUT):
        if is_port_open(DEBUG_PORT):
            return True, "端口已开启"
        time.sleep(1)

    return False, f"启动超时（{BROWSER_START_TIMEOUT}秒），请检查浏览器是否弹出对话框或被安全软件拦截。"

# ---------- 日志处理器 ----------
class TextHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        self.text_widget.insert(tk.END, self.format(record) + "\n")
        self.text_widget.see(tk.END)

# ---------- 自定义异常 ----------
class FatalLoginError(Exception):
    pass

# ---------- 后台执行器 ----------
class UploadWorker:
    def __init__(self, tasks, log_callback, progress_callback, status_callback, done_callback, browser_name, pause_event):
        self.tasks = tasks
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.done_callback = done_callback
        self.browser_name = browser_name
        self.pause_event = pause_event
        self.task_items = {}

    async def wait_for_condition(self, page, condition_func, timeout, interval=0.1):
        elapsed = 0
        while elapsed < timeout:
            try:
                if await condition_func():
                    return True
            except:
                pass
            await asyncio.sleep(interval)
            elapsed += interval
        return False

    async def is_page_alive(self, page):
        try:
            await page.evaluate("1")
            return True
        except Exception:
            return False

    async def safe_goto(self, page, url, timeout=30000):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            return True
        except Exception as e:
            self.log_callback(f"⚠️ 导航失败: {e}")
            return False

    async def ensure_logged_in(self, initial_page, acc_id, target_url):
        """
        确保当前页面为目标资质页。
        处理登录过程中的各种跳转，包括「选择账户」页面的「进入新客户工作台」按钮（新标签页）。
        返回目标页的 page 对象。
        """
        target_base = f"https://ad.qq.com/atlas/{acc_id}/account/proof_info"
        current_page = initial_page

        await asyncio.sleep(1.0)
        try:
            current_url = await current_page.evaluate("window.location.href")
        except Exception as e:
            self.log_callback(f"❌ 获取初始 URL 失败: {e}")
            raise FatalLoginError("页面已关闭，请检查浏览器窗口")

        self.log_callback(f"📍 [初始检测] 当前URL: {current_url}")

        if current_url.startswith(target_base):
            self.log_callback("✅ 已在目标页")
            return current_page

        if "cm/home" in current_url:
            self.log_callback(f"✅ 初始检测到 cm/home，正在跳转到资质页...")
            if await self.safe_goto(current_page, target_url):
                await asyncio.sleep(1.5)
                if current_page.url.startswith(target_base):
                    self.log_callback("✅ 已进入资质页")
                    return current_page
            raise FatalLoginError("cm/home 跳转失败")

        if "login" in current_url or "sso.e.qq.com" in current_url or current_url == "https://ad.qq.com/":
            self.log_callback(f"⚠️ 检测到需要登录，当前页面: {current_url}")
            self.log_callback(f"⏳ 请扫码登录（超时 {LOGIN_TIMEOUT} 秒）...")

            elapsed = 0
            interval = 0.5
            last_url = current_url
            loop_count = 0

            while elapsed < LOGIN_TIMEOUT:
                loop_count += 1
                await asyncio.sleep(interval)
                elapsed += interval

                try:
                    await current_page.wait_for_load_state("domcontentloaded", timeout=300)
                except:
                    pass

                try:
                    current_url = await current_page.evaluate("window.location.href")
                except:
                    try:
                        current_url = current_page.url
                    except:
                        current_url = ""

                if loop_count % 5 == 0:
                    self.log_callback(f"📍 [检测] URL: {current_url}")

                # ---- 检测到 cm/home ----
                if "cm/home" in current_url:
                    self.log_callback(f"✅✅✅ [第{loop_count}次] 检测到登录成功！URL: {current_url}")
                    self.log_callback("🔄 正在跳转到资质页...")
                    try:
                        await current_page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                        await asyncio.sleep(1.0)
                        if current_page.url.startswith(target_base):
                            self.log_callback("✅✅✅ 成功进入资质页！")
                            return current_page
                        else:
                            self.log_callback("⚠️ 第一次跳转未到目标页，重试...")
                            await current_page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                            await asyncio.sleep(1.0)
                            if current_page.url.startswith(target_base):
                                self.log_callback("✅✅✅ 第二次跳转成功！")
                                return current_page
                            else:
                                self.log_callback(f"❌ 跳转失败，当前URL: {current_page.url}")
                                raise FatalLoginError("跳转失败")
                    except Exception as e:
                        self.log_callback(f"❌ 跳转异常: {e}")
                        raise FatalLoginError("跳转失败")

                # ---- 检测到选择账户页面（portalc） ----
                if "frontend/portalc" in current_url:
                    self.log_callback("📍 检测到选择账户页面，正在点击「进入新客户工作台」...")
                    try:
                        btn_selectors = [
                            "button:has-text('进入新客户工作台')",
                            "div.ac-bottom button:has-text('进入新客户工作台')",
                            "button.odc-button:has-text('进入新客户工作台')",
                            "div:nth-child(2) button"
                        ]
                        btn = None
                        for selector in btn_selectors:
                            locator = current_page.locator(selector)
                            if await locator.count() > 0:
                                btn = locator.first
                                break
                        if btn is None:
                            try:
                                btn = current_page.locator("text=进入新客户工作台").first
                                if await btn.count() == 0:
                                    self.log_callback("⚠️ 未找到进入新客户工作台按钮")
                                    continue
                            except:
                                continue

                        async with current_page.context.expect_page() as new_page_info:
                            await btn.click()
                        new_page = await new_page_info.value
                        self.log_callback("✅ 已点击，新标签页已打开，切换到新页...")

                        current_page = new_page
                        await current_page.wait_for_load_state("domcontentloaded")
                        new_url = current_page.url
                        self.log_callback(f"📍 新标签页URL: {new_url}")

                        if "cm/home" in new_url:
                            self.log_callback("✅ 新页面已跳转到 cm/home，登录成功")
                            await current_page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                            await asyncio.sleep(1.0)
                            if current_page.url.startswith(target_base):
                                self.log_callback("✅✅✅ 成功进入资质页！")
                                return current_page
                            else:
                                self.log_callback(f"⚠️ 跳转后仍不是目标页: {current_page.url}")
                        else:
                            last_url = new_url
                            continue

                    except Exception as e:
                        self.log_callback(f"⚠️ 点击进入新工作台出错: {e}")
                        continue

                # ---- 检查是否回到目标页 ----
                if current_url.startswith(target_base):
                    self.log_callback(f"✅ [第{loop_count}次] 已回到目标页")
                    return current_page

                # ---- 检查暂停 ----
                if self.pause_event.is_set():
                    self.log_callback("⏸ 暂停中，等待继续...")
                    while self.pause_event.is_set():
                        await asyncio.sleep(0.5)
                    self.log_callback("▶ 已继续")

                # ---- 检查页面存活 ----
                if not await self.is_page_alive(current_page):
                    self.log_callback("❌ 页面已关闭")
                    raise FatalLoginError("页面已关闭")

                # ---- 记录 URL 变化 ----
                if current_url != last_url:
                    self.log_callback(f"📍 [第{loop_count}次] URL 变化: {current_url}")
                    last_url = current_url

                # ---- 登录提示 ----
                if "login" in current_url or "sso.e.qq.com" in current_url:
                    if loop_count % 10 == 0:
                        self.log_callback(f"⏳ 请扫码登录（剩余 {LOGIN_TIMEOUT - elapsed:.0f} 秒）...")
                elif current_url == "https://ad.qq.com/":
                    if loop_count % 10 == 0:
                        self.log_callback(f"⏳ 请等待页面跳转或扫码登录（剩余 {LOGIN_TIMEOUT - elapsed:.0f} 秒）...")

            raise FatalLoginError(f"登录等待超时（{LOGIN_TIMEOUT}秒），任务已终止")

        self.log_callback(f"⚠️ 未知页面状态: {current_url}，尝试强制跳转...")
        if await self.safe_goto(current_page, target_url):
            await asyncio.sleep(1.5)
            if current_page.url.startswith(target_base):
                self.log_callback("✅ 已进入资质页")
                return current_page
        raise FatalLoginError(f"无法进入目标页，当前URL: {current_url}")

    def run(self):
        asyncio.run(self._run_async())

    async def _run_async(self):
        try:
            # 启动/连接浏览器（带超时和错误提示）
            if not is_port_open(DEBUG_PORT):
                self.log_callback(f"🔧 正在启动 {self.browser_name}...")
                success, msg = start_browser_debug(self.browser_name)
                if not success:
                    self.log_callback(f"❌ 启动失败: {msg}")
                    self.log_callback("💡 提示：您可以手动启动浏览器后重试。")
                    self.done_callback()
                    return
                self.log_callback(f"✅ {self.browser_name} 已启动")
            else:
                self.log_callback("✅ 端口已开启，直接连接")

            self.log_callback("正在连接浏览器...")
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
                self.log_callback("✅ 连接成功")
                context = browser.contexts[0]
                page = await context.new_page()
                self.log_callback("✅ 已创建专用标签页")

                total = len(self.tasks)
                completed = 0
                self.progress_callback(completed, total)

                for idx, task in enumerate(self.tasks):
                    # 检查暂停标志
                    if self.pause_event.is_set():
                        self.log_callback("⏸ 任务已暂停，等待继续...")
                        while self.pause_event.is_set():
                            await asyncio.sleep(0.5)
                        self.log_callback("▶ 任务已继续")

                    acc_id = task["account_id"].strip()
                    link = task["promote_link"].strip()
                    img_path = task["icp_image_path"].strip()
                    log_prefix = f"[{idx+1}/{total} {acc_id}]"

                    self.status_callback(acc_id, "⏳ 处理中")

                    try:
                        if not Path(img_path).exists():
                            self.log_callback(f"{log_prefix} ❌ 图片不存在")
                            self.status_callback(acc_id, "❌ 图片不存在")
                            completed += 1
                            self.progress_callback(completed, total)
                            continue

                        target_url = f"https://ad.qq.com/atlas/{acc_id}/account/proof_info"
                        self.log_callback(f"{log_prefix} 跳转至: {target_url}")

                        if not await self.safe_goto(page, target_url):
                            self.log_callback(f"{log_prefix} ⚠️ 导航失败，尝试继续...")
                            if not await self.is_page_alive(page):
                                raise FatalLoginError("页面已关闭")

                        # 登录检测（会返回最终可用的 page 对象）
                        page = await self.ensure_logged_in(page, acc_id, target_url)
                        self.log_callback(f"{log_prefix} ✅ 页面已加载，当前URL: {page.url}")

                        # ---------- 点击“添加上传链接” ----------
                        self.log_callback(f"{log_prefix} 等待【添加上传链接】按钮...")
                        page = await self.ensure_logged_in(page, acc_id, target_url)

                        button_found = False
                        try:
                            await page.locator("button:has-text('添加上传链接')").click(timeout=TIMEOUT_BUTTON_ADD * 1000)
                            self.log_callback(f"{log_prefix} ✅ 点击按钮成功（文本定位）")
                            button_found = True
                        except:
                            try:
                                await page.click("//button[contains(text(),'添加上传链接')]", timeout=TIMEOUT_BUTTON_ADD * 1000)
                                self.log_callback(f"{log_prefix} ✅ 点击按钮成功（XPath）")
                                button_found = True
                            except:
                                try:
                                    await page.locator(".spaui-button").first.click(timeout=2000)
                                    self.log_callback(f"{log_prefix} ✅ 点击按钮成功（.spaui-button）")
                                    button_found = True
                                except:
                                    self.log_callback(f"{log_prefix} ❌ 所有定位方式均失败")
                                    self.status_callback(acc_id, "❌ 未找到按钮")
                                    completed += 1
                                    self.progress_callback(completed, total)
                                    continue

                        # 等待弹窗
                        async def dialog_present():
                            return await page.locator(".spaui-dialog").count() > 0

                        if not await self.wait_for_condition(page, dialog_present, TIMEOUT_DIALOG_APPEAR):
                            self.log_callback(f"{log_prefix} ⚠️ 弹窗未出现，尝试重新点击...")
                            await page.locator(".spaui-button").first.click()
                            if not await self.wait_for_condition(page, dialog_present, TIMEOUT_DIALOG_APPEAR):
                                self.log_callback(f"{log_prefix} ❌ 弹窗仍未出现")
                                self.status_callback(acc_id, "❌ 弹窗未出现")
                                completed += 1
                                self.progress_callback(completed, total)
                                continue
                        self.log_callback(f"{log_prefix} ✅ 弹窗已出现")

                        # 填写链接
                        try:
                            await page.fill("input[placeholder='请输入推广链接']", link)
                            self.log_callback(f"{log_prefix} 已填写链接")
                        except:
                            await page.evaluate(f"document.querySelector('input[placeholder=\"请输入推广链接\"]').value='{link}';")
                            self.log_callback(f"{log_prefix} 已通过JS填写链接")

                        # 上传图片
                        self.status_callback(acc_id, "📤 上传中")
                        self.log_callback(f"{log_prefix} 正在上传图片...")
                        uploaded = False
                        file_inputs = await page.query_selector_all("input[type='file']")
                        if file_inputs:
                            for inp in file_inputs:
                                try:
                                    await inp.set_input_files(img_path)
                                    self.log_callback(f"{log_prefix} ✅ 直接注入成功")
                                    uploaded = True
                                    break
                                except:
                                    pass

                        if not uploaded:
                            try:
                                upload_trigger = page.locator("text=点击或拖拽上传").first
                                async with page.expect_file_chooser() as fc_info:
                                    await upload_trigger.click(timeout=2000)
                                file_chooser = await fc_info.value
                                await file_chooser.set_files(img_path)
                                self.log_callback(f"{log_prefix} ✅ 通过 FileChooser 上传成功")
                                uploaded = True
                            except Exception as e:
                                self.log_callback(f"{log_prefix} ❌ FileChooser 失败: {e}")

                        if not uploaded:
                            self.log_callback(f"{log_prefix} ❌ 自动上传失败，请手动上传")
                            await asyncio.sleep(3)

                        # 提交确定
                        self.status_callback(acc_id, "📨 提交中")
                        self.log_callback(f"{log_prefix} 等待【确定】按钮...")

                        async def confirm_button_present():
                            return await page.locator(".spaui-dialog-footer .spaui-button-primary").count() > 0

                        submit_success = False
                        if await self.wait_for_condition(page, confirm_button_present, TIMEOUT_CONFIRM_BUTTON):
                            try:
                                async with page.expect_response(
                                    lambda r: "create?" in r.url and "advertiser_id" in r.url,
                                    timeout=TIMEOUT_RESPONSE * 1000
                                ) as resp_info:
                                    await page.click(".spaui-dialog-footer .spaui-button-primary")
                                resp = await resp_info.value
                                result = await resp.json()
                                if result.get("code") == 0:
                                    self.log_callback(f"{log_prefix} ✅ 提交成功！")
                                    submit_success = True
                                else:
                                    self.log_callback(f"{log_prefix} ⚠️ 接口返回异常: {result}")
                                    submit_success = True
                            except Exception as e:
                                self.log_callback(f"{log_prefix} ⚠️ 响应监听超时，尝试文本点击确认...")
                                try:
                                    await page.click("button:has-text('确定')", timeout=2000)
                                    self.log_callback(f"{log_prefix} ✅ 文本点击成功")
                                    submit_success = True
                                except:
                                    await page.evaluate("document.querySelector('.spaui-dialog-footer .spaui-button-primary')?.click();")
                                    self.log_callback(f"{log_prefix} ⚠️ 已使用 JS 强制点击")
                                    submit_success = True
                        else:
                            self.log_callback(f"{log_prefix} ❌ 未找到确定按钮")
                            self.status_callback(acc_id, "❌ 未找到确定")
                            completed += 1
                            self.progress_callback(completed, total)
                            continue

                        # 等待弹窗关闭
                        async def dialog_closed():
                            return await page.locator(".spaui-dialog").count() == 0

                        if await self.wait_for_condition(page, dialog_closed, TIMEOUT_DIALOG_CLOSE):
                            self.log_callback(f"{log_prefix} ✅ 弹窗已关闭")
                        else:
                            self.log_callback(f"{log_prefix} ⚠️ 弹窗未关闭")

                        if submit_success:
                            self.status_callback(acc_id, "✅ 成功")
                        else:
                            self.status_callback(acc_id, "⚠️ 未知状态")
                        completed += 1
                        self.progress_callback(completed, total)
                        await asyncio.sleep(0.3)

                    except FatalLoginError as fatal_e:
                        self.log_callback(f"{log_prefix} ❌ 致命错误: {str(fatal_e)}")
                        self.log_callback("🛑 任务已终止，不再继续处理后续账户。")
                        self.status_callback(acc_id, "❌ 登录失败")
                        break

                    except Exception as e:
                        self.log_callback(f"{log_prefix} ❌ 出错: {str(e)}")
                        self.status_callback(acc_id, f"❌ 出错")
                        try:
                            await page.screenshot(path=f"error_{acc_id}.png")
                            self.log_callback(f"{log_prefix} 截图已保存")
                        except:
                            pass
                        completed += 1
                        self.progress_callback(completed, total)

                if completed < total:
                    self.log_callback(f"⚠️ 因登录问题，仅完成 {completed}/{total} 个任务")
                else:
                    self.log_callback("🎉 所有任务完成！")

        except Exception as e:
            self.log_callback(f"❌ 全局异常: {e}")
        finally:
            self.done_callback()

# ---------- GUI ----------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ICP备案批量上传工具")
        self.geometry("1100x720")
        self.minsize(900, 600)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ---------- 标题栏 ----------
        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.grid(row=0, column=0, padx=20, pady=(15, 5), sticky="ew")
        title_frame.grid_columnconfigure(0, weight=0)
        title_frame.grid_columnconfigure(1, weight=1)
        title_frame.grid_columnconfigure(2, weight=0)

        ctk.CTkLabel(title_frame, text="📤 ICP备案批量上传工具", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_frame, text="v6.4 跨平台版", font=ctk.CTkFont(size=12), text_color="gray").grid(row=0, column=1, padx=10, sticky="w")

        progress_frame = ctk.CTkFrame(title_frame, fg_color="transparent")
        progress_frame.grid(row=0, column=2, sticky="e")
        self.progress_label = ctk.CTkLabel(progress_frame, text="已完成: 0 / 0", font=ctk.CTkFont(size=12, weight="bold"))
        self.progress_label.pack(side="left", padx=5)
        self.progress_bar = ctk.CTkProgressBar(progress_frame, width=150, height=12)
        self.progress_bar.pack(side="left", padx=5)
        self.progress_bar.set(0)

        # ---------- 表格 ----------
        table_card = ctk.CTkFrame(self, corner_radius=10)
        table_card.grid(row=1, column=0, padx=20, pady=(5, 5), sticky="nsew")
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(0, weight=1)

        self.tree_frame = ctk.CTkFrame(table_card, fg_color="transparent")
        self.tree_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.tree_frame.grid_columnconfigure(0, weight=1)
        self.tree_frame.grid_rowconfigure(0, weight=1)

        columns = ("account_id", "promote_link", "icp_image_path", "status")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", height=8)
        self.tree.heading("account_id", text="账户ID", anchor=tk.CENTER)
        self.tree.heading("promote_link", text="推广链接", anchor=tk.CENTER)
        self.tree.heading("icp_image_path", text="ICP图片路径", anchor=tk.CENTER)
        self.tree.heading("status", text="状态", anchor=tk.CENTER)
        self.tree.column("account_id", width=100, anchor=tk.CENTER)
        self.tree.column("promote_link", width=350, anchor=tk.W)
        self.tree.column("icp_image_path", width=350, anchor=tk.W)
        self.tree.column("status", width=80, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(self.tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.item_id_map = {}

        # ---------- 控制栏 ----------
        control_frame = ctk.CTkFrame(self, fg_color="transparent")
        control_frame.grid(row=2, column=0, padx=20, pady=(15, 15), sticky="ew")
        control_frame.grid_columnconfigure(0, weight=1)
        control_frame.grid_columnconfigure(1, weight=0)

        left_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        left_frame.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(left_frame, text="➕ 添加任务", command=self.add_task, width=100).pack(side="left", padx=4)
        ctk.CTkButton(left_frame, text="✖ 删除选中", command=self.delete_selected, width=100).pack(side="left", padx=4)
        ctk.CTkButton(left_frame, text="🗑 清空全部", command=self.clear_all, width=100).pack(side="left", padx=4)
        ctk.CTkButton(left_frame, text="📂 从CSV导入", command=self.import_csv, width=100).pack(side="left", padx=4)

        browser_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        browser_frame.pack(side="left", padx=(15, 0))
        ctk.CTkLabel(browser_frame, text="🌐 浏览器:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 3))
        self.browser_var = tk.StringVar(value="Microsoft Edge")
        self.browser_combo = ctk.CTkComboBox(
            browser_frame,
            values=["Microsoft Edge", "Google Chrome"],
            variable=self.browser_var,
            state="readonly",
            width=150
        )
        self.browser_combo.pack(side="left", padx=3)

        self.status_label = ctk.CTkLabel(
            left_frame,
            text="🟢 Edge",
            font=ctk.CTkFont(size=11),
            fg_color=("#E0F7FA", "#E0F7FA"),
            corner_radius=10,
            padx=8,
            pady=3,
            border_width=1,
            border_color="#80DEEA"
        )
        self.status_label.pack(side="left", padx=(12, 0))

        def update_status(*args):
            browser = self.browser_var.get()
            short = "Edge" if browser == "Microsoft Edge" else "Chrome"
            self.status_label.configure(text=f"🟢 {short}")
        self.browser_var.trace('w', update_status)

        right_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        right_frame.grid(row=0, column=1, sticky="e")

        self.btn_start = ctk.CTkButton(right_frame, text="▶ 开始上传", command=self.start_upload,
                                       fg_color="#2ecc71", hover_color="#27ae60", text_color="white", width=120)
        self.btn_start.pack(side="left", padx=5)

        self.btn_pause = ctk.CTkButton(right_frame, text="⏸ 暂停", command=self.toggle_pause,
                                       fg_color="#f39c12", hover_color="#e67e22", text_color="white", width=80, state="disabled")
        self.btn_pause.pack(side="left", padx=5)

        ctk.CTkButton(right_frame, text="✕ 退出", command=self.quit, width=80).pack(side="left", padx=5)

        # ---------- 日志 ----------
        log_card = ctk.CTkFrame(self, corner_radius=10)
        log_card.grid(row=3, column=0, padx=20, pady=(0, 20), sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(log_card, text="📋 执行日志", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, padx=10, pady=(8, 0), sticky="w")
        self.log_text = tk.Text(log_card, height=10, font=('Consolas', 9), bg='#f8f9fa', fg='#2c3e50', relief=tk.FLAT, borderwidth=0)
        self.log_text.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="nsew")
        log_scrollbar = ttk.Scrollbar(log_card, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scrollbar.grid(row=1, column=1, sticky="ns", pady=(5, 10))
        self.log_text.configure(yscrollcommand=log_scrollbar.set)

        self.log_handler = TextHandler(self.log_text)
        self.log_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
        logging.getLogger().addHandler(self.log_handler)
        logging.getLogger().setLevel(logging.INFO)

        self.running = False
        self.pause_event = threading.Event()

    def toggle_pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.btn_pause.configure(text="⏸ 暂停")
            logging.info("▶ 任务已继续")
        else:
            self.pause_event.set()
            self.btn_pause.configure(text="▶ 继续")
            logging.info("⏸ 任务已暂停")

    def add_task(self):
        win = ctk.CTkToplevel(self)
        win.title("添加任务（支持批量）")
        win.geometry("600x400")
        win.grab_set()
        win.transient(self)

        main = ctk.CTkFrame(win, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(main, text="账户ID（多个用空格、换行或逗号分隔）:", font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="w", pady=(0, 5))
        entry_ids = ctk.CTkTextbox(main, height=80, font=ctk.CTkFont(size=12))
        entry_ids.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        ctk.CTkLabel(main, text="💡 例如：123456 789012 345678", font=ctk.CTkFont(size=11), text_color="gray").grid(row=2, column=0, sticky="w", pady=(0, 10))

        ctk.CTkLabel(main, text="推广链接:", font=ctk.CTkFont(size=12)).grid(row=3, column=0, sticky="w", pady=(0, 5))
        entry_link = ctk.CTkEntry(main, width=500, font=ctk.CTkFont(size=12))
        entry_link.grid(row=4, column=0, sticky="ew", pady=(0, 10))

        ctk.CTkLabel(main, text="ICP图片路径:", font=ctk.CTkFont(size=12)).grid(row=5, column=0, sticky="w", pady=(0, 5))
        img_frame = ctk.CTkFrame(main, fg_color="transparent")
        img_frame.grid(row=6, column=0, sticky="ew", pady=(0, 15))
        entry_img = ctk.CTkEntry(img_frame, width=400, font=ctk.CTkFont(size=12))
        entry_img.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(img_frame, text="浏览", width=80, command=lambda: self._browse_file(entry_img)).pack(side="right", padx=(5,0))

        btn_frame = ctk.CTkFrame(main, fg_color="transparent")
        btn_frame.grid(row=7, column=0, pady=10)
        ctk.CTkButton(btn_frame, text="确定", command=lambda: self._confirm_add(entry_ids, entry_link, entry_img, win),
                      fg_color="#3498db", hover_color="#2980b9", width=100).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="取消", command=win.destroy, width=100).pack(side="left", padx=5)

    def _browse_file(self, entry):
        path = filedialog.askopenfilename(filetypes=[("图片文件", "*.jpg *.jpeg *.png")])
        if path:
            entry.delete(0, tk.END)
            entry.insert(0, path)

    def _confirm_add(self, entry_ids, entry_link, entry_img, win):
        ids_text = entry_ids.get("1.0", tk.END).strip()
        link = entry_link.get().strip()
        img = entry_img.get().strip()
        if not ids_text or not link or not img:
            messagebox.showwarning("提示", "请填写完整信息")
            return
        if not Path(img).exists():
            messagebox.showwarning("提示", "图片文件不存在，请检查路径")
            return
        id_list = re.split(r'[\s,，、\n]+', ids_text)
        id_list = [x.strip() for x in id_list if x.strip()]
        if not id_list:
            messagebox.showwarning("提示", "未检测到有效的账户ID")
            return
        for acc_id in id_list:
            item_id = self.tree.insert("", tk.END, values=(acc_id, link, img, "待执行"))
            self.item_id_map[acc_id] = item_id
        win.destroy()
        logging.info(f"✅ 成功添加 {len(id_list)} 个任务")

    def delete_selected(self):
        for item in self.tree.selection():
            values = self.tree.item(item, "values")
            if values and values[0] in self.item_id_map:
                del self.item_id_map[values[0]]
            self.tree.delete(item)

    def clear_all(self):
        if messagebox.askyesno("确认", "清空所有任务？"):
            self.item_id_map.clear()
            for item in self.tree.get_children():
                self.tree.delete(item)

    def import_csv(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV文件", "*.csv")])
        if not file_path:
            return
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    acc = row.get('account_id', '').strip()
                    link = row.get('promote_link', '').strip()
                    img = row.get('icp_image_path', '').strip()
                    if acc and link and img and Path(img).exists():
                        item_id = self.tree.insert("", tk.END, values=(acc, link, img, "待执行"))
                        self.item_id_map[acc] = item_id
                    else:
                        logging.warning(f"跳过无效行: {row}")
            logging.info(f"✅ 成功从 {file_path} 导入任务")
        except Exception as e:
            messagebox.showerror("错误", f"导入失败: {e}")

    def update_status(self, acc_id, status):
        if acc_id in self.item_id_map:
            item_id = self.item_id_map[acc_id]
            values = list(self.tree.item(item_id, "values"))
            if len(values) >= 4:
                values[3] = status
                self.tree.item(item_id, values=tuple(values))
        self.update_idletasks()

    def update_progress(self, completed, total):
        self.progress_label.configure(text=f"已完成: {completed} / {total}")
        if total > 0:
            self.progress_bar.set(completed / total)
        self.update_idletasks()

    def start_upload(self):
        if self.running:
            messagebox.showinfo("提示", "正在执行上传，请稍候...")
            return
        items = self.tree.get_children()
        if not items:
            messagebox.showwarning("提示", "没有任务可上传")
            return

        browser_name = self.browser_var.get()
        if not browser_name:
            messagebox.showwarning("提示", "请选择浏览器")
            return

        self.pause_event.clear()
        self.btn_pause.configure(text="⏸ 暂停", state="normal")

        for item in items:
            values = list(self.tree.item(item, "values"))
            if len(values) >= 4:
                values[3] = "待执行"
                self.tree.item(item, values=tuple(values))
                if values[0] in self.item_id_map:
                    self.item_id_map[values[0]] = item

        task_list = []
        for item in items:
            v = self.tree.item(item, "values")
            task_list.append({"account_id": v[0], "promote_link": v[1], "icp_image_path": v[2]})

        self.running = True
        self.btn_start.configure(state="disabled", text="⏳ 执行中...")
        for child in self.winfo_children():
            if isinstance(child, ctk.CTkFrame) and child != self:
                for sub in child.winfo_children():
                    if isinstance(sub, ctk.CTkButton) and sub not in (self.btn_start, self.btn_pause) and sub.cget("text") != "✕ 退出":
                        sub.configure(state="disabled")

        self.log_text.delete(1.0, tk.END)
        logging.info(f"📂 开始批量上传（使用 {browser_name}）...")

        def log_callback(msg):
            logging.info(msg)

        def progress_callback(completed, total):
            self.update_progress(completed, total)

        def status_callback(acc_id, status):
            self.update_status(acc_id, status)

        def done_callback():
            self.running = False
            self.btn_start.configure(state="normal", text="▶ 开始上传")
            self.btn_pause.configure(state="disabled", text="⏸ 暂停")
            for child in self.winfo_children():
                if isinstance(child, ctk.CTkFrame):
                    for sub in child.winfo_children():
                        if isinstance(sub, ctk.CTkButton):
                            sub.configure(state="normal")

        worker = UploadWorker(task_list, log_callback, progress_callback, status_callback, done_callback, browser_name, self.pause_event)
        threading.Thread(target=worker.run, daemon=True).start()

if __name__ == "__main__":
    app = App()
    app.mainloop()

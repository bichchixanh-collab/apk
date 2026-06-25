# -*- coding: utf-8 -*-
"""
Viet Hoa Tool - Ban Android (Kivy)
====================================
UI Kivy thay the hoan toan cho ban Tkinter desktop. TOAN BO logic xu
ly file (.class, mission-table, sms-table, pascal-string-list,
binary-pascal, text-quoted/line/token/raw, goi Gemini API) nam trong
core.py va duoc giu nguyen 100% khong sua doi - file nay CHI lo phan
giao dien va dieu phoi luong chay tren Android.

Luong su dung (giong ban desktop):
  1. Mo file .jar (qua filechooser cua Android)
  2. Quet chuoi Trung trong toan bo jar
  3. Dich tat ca cac trang qua Gemini API
  4. Xem/sua tung fragment (phan trang 50/trang), rollback neu can
  5. Ap dung & xuat .jar moi (luu vao thu muc Download cua may)
"""
import json
import os
import shutil
import tempfile
import threading
import time
import zipfile

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import (
    BooleanProperty, ListProperty, NumericProperty, ObjectProperty,
    StringProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.utils import platform

import core

ANDROID = platform == "android"

if ANDROID:
    from android.permissions import Permission, request_permissions  # noqa
    from android.storage import primary_external_storage_path  # noqa


# ----------------------------------------------------------------------------
# KV layout - dinh nghia giao dien bang ngon ngu Kivy (tuong tu XML)
# ----------------------------------------------------------------------------
KV = """
#:import dp kivy.metrics.dp

<RowItem@BoxLayout>:
    orientation: "vertical"
    size_hint_y: None
    height: self.minimum_height
    padding: dp(8)
    spacing: dp(4)
    canvas.before:
        Color:
            rgba: 0.13, 0.13, 0.15, 1
        Rectangle:
            pos: self.pos
            size: self.size

<MainScreen>:
    name: "main"
    BoxLayout:
        orientation: "vertical"
        padding: dp(8)
        spacing: dp(6)

        Label:
            text: "Viet Hoa Tool - Game .jar (Android)"
            size_hint_y: None
            height: dp(36)
            bold: True
            font_size: "18sp"

        BoxLayout:
            size_hint_y: None
            height: dp(46)
            spacing: dp(6)
            Button:
                text: "1. Mo .jar"
                on_release: app.open_jar()
            Button:
                text: "2. Quet"
                on_release: app.start_scan()
            Button:
                text: "3. Dich tat ca"
                on_release: app.start_translate_all()

        BoxLayout:
            size_hint_y: None
            height: dp(46)
            spacing: dp(6)
            Button:
                text: "4. Ap dung & Xuat .jar"
                on_release: app.apply_and_export()
            Button:
                text: "Xem / Sua chuoi"
                on_release: app.go_to_list()

        BoxLayout:
            size_hint_y: None
            height: dp(40)
            spacing: dp(6)
            CheckBox:
                id: no_accent_cb
                size_hint_x: None
                width: dp(40)
                on_active: app.set_no_accent(self.active)
            Label:
                text: "Dich khong dau (tiet kiem byte, tranh loi do dai)"
                text_size: self.size
                valign: "middle"
                font_size: "13sp"

        Label:
            text: "Gemini API key:"
            size_hint_y: None
            height: dp(22)
            halign: "left"
            text_size: self.size
            font_size: "13sp"
        TextInput:
            id: api_key_input
            size_hint_y: None
            height: dp(44)
            multiline: False
            password: True
            text: app.api_key
            on_text: app.api_key = self.text

        Label:
            id: status_label
            text: app.status_text
            size_hint_y: None
            height: dp(50)
            text_size: self.size
            halign: "left"
            valign: "middle"
            font_size: "13sp"
            color: 0.4, 0.9, 0.5, 1

        ProgressBar:
            id: progress_bar
            size_hint_y: None
            height: dp(16)
            max: app.progress_max
            value: app.progress_value

        Label:
            text: "Log:"
            size_hint_y: None
            height: dp(20)
            halign: "left"
            text_size: self.size
            font_size: "13sp"

        ScrollView:
            id: log_scroll
            Label:
                id: log_label
                text: app.log_text
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
                halign: "left"
                valign: "top"
                font_size: "12sp"
                padding: dp(4), dp(4)


<ListScreen>:
    name: "list"
    BoxLayout:
        orientation: "vertical"
        padding: dp(8)
        spacing: dp(6)

        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(6)
            Button:
                text: "< Quay lai"
                size_hint_x: 0.3
                on_release: app.go_to_main()
            TextInput:
                id: search_input
                hint_text: "Tim kiem chuoi goc / ban dich..."
                multiline: False
                on_text: app.on_search(self.text)

        BoxLayout:
            size_hint_y: None
            height: dp(40)
            spacing: dp(6)
            Button:
                text: "< Trang truoc"
                on_release: app.prev_page()
            Label:
                id: page_label
                text: app.page_label_text
                font_size: "13sp"
            Button:
                text: "Trang sau >"
                on_release: app.next_page()

        ScrollView:
            BoxLayout:
                id: rows_container
                orientation: "vertical"
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(4)
"""


# ----------------------------------------------------------------------------
# Widget hien thi 1 fragment (chuoi goc + o sua ban dich + nut rollback)
# ----------------------------------------------------------------------------
class FragmentRow(BoxLayout):
    def __init__(self, app, fragment, **kwargs):
        super().__init__(orientation="vertical", size_hint_y=None,
                          padding=(dp(8), dp(6)), spacing=dp(4), **kwargs)
        self.app = app
        self.fragment = fragment
        self.bind(minimum_height=self._set_height)

        from kivy.graphics import Color, Rectangle
        with self.canvas.before:
            Color(0.15, 0.15, 0.17, 1)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_bg, size=self._update_bg)

        orig_label = Label(
            text=f"[b]Goc:[/b] {self._escape(fragment)}",
            markup=True, size_hint_y=None, halign="left", valign="top",
            font_size="13sp", color=(0.85, 0.85, 0.6, 1),
        )
        orig_label.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        orig_label.bind(texture_size=lambda w, v: setattr(w, "height", v[1]))
        self.add_widget(orig_label)

        files = app.fragment_files.get(fragment, [])
        if files:
            file_info = Label(
                text="Trong file: " + ", ".join(files[:3]) +
                     (f" (+{len(files)-3} file khac)" if len(files) > 3 else ""),
                size_hint_y=None, halign="left", valign="top",
                font_size="11sp", color=(0.55, 0.55, 0.55, 1),
            )
            file_info.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
            file_info.bind(texture_size=lambda w, v: setattr(w, "height", v[1]))
            self.add_widget(file_info)

        row2 = BoxLayout(orientation="horizontal", size_hint_y=None,
                          height=dp(44), spacing=dp(6))
        self.trans_input = TextInput(
            text=app.translations.get(fragment, fragment),
            multiline=False, size_hint_x=0.78, font_size="13sp",
        )
        self.trans_input.bind(
            on_text_validate=lambda w: self._commit(),
        )
        self.trans_input.bind(focus=self._on_focus_change)
        row2.add_widget(self.trans_input)

        rollback_btn = Button(text="Lui", size_hint_x=0.22)
        rollback_btn.bind(on_release=lambda w: self._rollback())
        row2.add_widget(rollback_btn)
        self.add_widget(row2)

    @staticmethod
    def _escape(s):
        # Trong markup Kivy, [ va ] can duoc escape de khong bi hieu
        # nham la the markup.
        return s.replace("[", "&bl;").replace("]", "&br;")

    def _set_height(self, instance, value):
        self.height = value

    def _update_bg(self, instance, value):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _on_focus_change(self, instance, focused):
        if not focused:
            self._commit()

    def _commit(self):
        new_val = self.trans_input.text
        self.app.set_translation(self.fragment, new_val)

    def _rollback(self):
        self.app.rollback_fragment(self.fragment)
        self.trans_input.text = self.app.translations.get(
            self.fragment, self.fragment)


class MainScreen(Screen):
    pass


class ListScreen(Screen):
    pass


class ViethoaApp(App):
    api_key = StringProperty("")
    status_text = StringProperty("Chua mo file .jar nao.")
    log_text = StringProperty("")
    progress_max = NumericProperty(1)
    progress_value = NumericProperty(0)
    page_label_text = StringProperty("Trang 0/0")

    def build(self):
        self.title = "Viet Hoa Tool"
        Window.clearcolor = (0.09, 0.09, 0.1, 1)

        # --- Trang thai (tuong duong cac thuoc tinh self.* trong ban
        # Tkinter goc - giu cung ten/cau truc de de doi chieu logic) ---
        self.work_dir = None
        self.jar_path = None
        self.scan_results = []      # list[core.ScanResult]

        self.unique_fragments = []  # list[str]
        self.fragment_files = {}    # {fragment: [rel_path,...]}
        self.translations = {}      # {fragment: ban dich}
        self.translation_history = {}  # {fragment: [gia tri cu,...]}

        self.no_accent = False
        self.stop_flag = threading.Event()

        self.page_size = 50
        self.current_page = 0
        self.pages = []
        self.search_query = ""

        self.cfg = core.load_config()
        self.api_key = self.cfg.get("api_key", "")

        if ANDROID:
            try:
                request_permissions([
                    Permission.READ_EXTERNAL_STORAGE,
                    Permission.WRITE_EXTERNAL_STORAGE,
                ])
            except Exception:
                pass

        self.sm = ScreenManager(transition=SlideTransition())
        self.sm.add_widget(MainScreen())
        self.sm.add_widget(ListScreen())
        return self.sm

    # ------------------------------------------------------------------
    # Tien ich UI
    # ------------------------------------------------------------------
    def log_msg(self, msg):
        self.log_text += msg + "\n"

        def _scroll(dt):
            scroll = self.sm.get_screen("main").ids.log_scroll
            scroll.scroll_y = 0
        Clock.schedule_once(_scroll, 0.05)

    def set_no_accent(self, active):
        self.no_accent = active

    def go_to_list(self):
        if not self.unique_fragments:
            self._popup_info("Chua co du lieu", "Hay quet file truoc.")
            return
        self._rebuild_pages()
        self.sm.current = "list"

    def go_to_main(self):
        self.sm.current = "main"

    def _popup_info(self, title, msg):
        Popup(
            title=title,
            content=Label(text=msg, text_size=(dp(280), None)),
            size_hint=(0.85, 0.4),
        ).open()

    def on_stop(self):
        # Luu API key khi dong app, giong save_config trong ban goc
        self.cfg["api_key"] = self.api_key
        try:
            core.save_config(self.cfg)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Buoc 1: Mo file .jar
    # ------------------------------------------------------------------
    def open_jar(self):
        if ANDROID:
            try:
                from plyer import filechooser
                filechooser.open_file(
                    on_selection=self._on_jar_selected,
                    filters=["*.jar"],
                )
            except Exception as e:
                self.status_text = f"Khong mo duoc trinh chon file: {e}"
        else:
            # Fallback khi test tren desktop (khong co plyer filechooser
            # native) - dung tkinter filedialog NEU co san, chi de dev/test.
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                path = filedialog.askopenfilename(filetypes=[("Java jar", "*.jar")])
                root.destroy()
                if path:
                    self._on_jar_selected([path])
            except Exception as e:
                self.status_text = f"Khong the mo file (chi test duoc tren Android): {e}"

    def _on_jar_selected(self, selection):
        if not selection:
            return
        jar_path = selection[0]
        self.jar_path = jar_path
        self.status_text = f"Da chon: {os.path.basename(jar_path)}. Dang giai nen..."
        threading.Thread(target=self._extract_jar_worker, args=(jar_path,), daemon=True).start()

    def _extract_jar_worker(self, jar_path):
        try:
            if self.work_dir and os.path.isdir(self.work_dir):
                shutil.rmtree(self.work_dir, ignore_errors=True)
            tmp_root = self._get_tmp_root()
            work_dir = tempfile.mkdtemp(prefix="viethoa_", dir=tmp_root)
            with zipfile.ZipFile(jar_path, "r") as zf:
                zf.extractall(work_dir)
            self.work_dir = work_dir
            self._set_status(f"Da giai nen: {os.path.basename(jar_path)}. "
                              f"San sang Quet (buoc 2).")
        except Exception as e:
            self._set_status(f"Loi giai nen jar: {e}")

    def _get_tmp_root(self):
        if ANDROID:
            try:
                return self.user_data_dir
            except Exception:
                pass
        return tempfile.gettempdir()

    @mainthread
    def _set_status(self, text):
        self.status_text = text

    # ------------------------------------------------------------------
    # Buoc 2: Quet chuoi Trung (dung scan_directory trong core.py)
    # ------------------------------------------------------------------
    def start_scan(self):
        if not self.work_dir:
            self._popup_info("Thieu du lieu", "Hay mo file .jar truoc.")
            return
        self.status_text = "Dang quet..."
        self.progress_value = 0
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        def progress_cb(idx, total, fpath):
            self._update_progress(idx, total)

        results = core.scan_directory(self.work_dir, progress_cb=progress_cb)
        self.scan_results = results

        # --- Boc tach FRAGMENT (giong logic trong ban Tkinter goc o
        # ham start_scan/_scan_worker - tai tao lai vi logic nay nam
        # trong class GUI cua ban goc, khong nam trong core.py) ---
        unique_fragments = []
        seen = set()
        fragment_files = {}

        for r in results:
            if r.kind == "binary-table-SKIPPED":
                continue  # khong dich, chi de canh bao (giong ban goc)
            if r.kind == "mission-table":
                extract_fn = core.extract_fragments_from_markup
            else:
                extract_fn = core.extract_fragments_from_raw

            for raw in r.strings:
                frags = extract_fn(raw)
                for frag in frags:
                    if frag not in seen:
                        seen.add(frag)
                        unique_fragments.append(frag)
                    fragment_files.setdefault(frag, [])
                    if r.rel_path not in fragment_files[frag]:
                        fragment_files[frag].append(r.rel_path)

        self.unique_fragments = unique_fragments
        self.fragment_files = fragment_files

        self._set_status(
            f"Quet xong: {len(results)} file co chu Han, "
            f"{len(unique_fragments)} fragment can dich."
        )
        self._log_async(
            f"=== Quet xong {len(results)} ket qua file, "
            f"{len(unique_fragments)} fragment duy nhat ==="
        )

    @mainthread
    def _update_progress(self, idx, total):
        self.progress_max = max(total, 1)
        self.progress_value = idx
        self.status_text = f"Dang quet {idx}/{total} file..."

    @mainthread
    def _log_async(self, msg):
        self.log_msg(msg)

    # ------------------------------------------------------------------
    # Buoc 3: Dich tat ca (dung translate_all + GeminiTranslator trong core.py)
    # ------------------------------------------------------------------
    def start_translate_all(self):
        if not self.unique_fragments:
            self._popup_info("Chua co du lieu", "Hay quet file truoc.")
            return
        api_key = self.api_key.strip()
        if not api_key:
            self._popup_info("Thieu API key", "Hay nhap Gemini API key.")
            return
        self.cfg["api_key"] = api_key
        try:
            core.save_config(self.cfg)
        except Exception:
            pass
        self.stop_flag.clear()
        self.progress_value = 0
        threading.Thread(target=self._translate_all_worker, args=(api_key,), daemon=True).start()

    def _translate_all_worker(self, api_key):
        translator = core.GeminiTranslator(api_key, no_accent=self.no_accent)
        nb_fragments = len(self.unique_fragments)
        self._log_async(f"=== Bat dau dich {nb_fragments} fragment ===")

        def progress_cb(bi, total_b):
            self._update_progress(bi, total_b)
            self._log_async(f"--- Trang {bi}/{total_b} ---")

        def log_cb(msg):
            self._log_async(msg)

        new_translations = core.translate_all(
            translator, self.unique_fragments, batch_size=self.page_size,
            progress_cb=progress_cb, log_cb=log_cb, stop_flag=self.stop_flag,
        )
        for frag, new_val in new_translations.items():
            self.set_translation(frag, new_val, record_history=True)

        self._set_status(
            f"Dich xong {len(self.translations)} fragment. "
            f"Vao 'Xem / Sua chuoi' de kiem tra truoc khi ap dung."
        )
        self._log_async("=== " + self.status_text + " ===")

    # ------------------------------------------------------------------
    # Quan ly translations + rollback (tuong duong _set_translation /
    # _rollback_fragment trong ban Tkinter goc)
    # ------------------------------------------------------------------
    def set_translation(self, fragment, new_value, record_history=True):
        old_value = self.translations.get(fragment)
        if old_value == new_value:
            return
        if record_history and old_value is not None:
            self.translation_history.setdefault(fragment, []).append(old_value)
        if new_value is None or new_value == fragment:
            self.translations.pop(fragment, None)
        else:
            self.translations[fragment] = new_value

    def rollback_fragment(self, fragment):
        hist = self.translation_history.get(fragment)
        if hist:
            prev = hist.pop()
            if prev == fragment:
                self.translations.pop(fragment, None)
            else:
                self.translations[fragment] = prev
            self.log_msg(f"Rollback: \"{fragment[:30]}...\" -> khoi phuc gia tri truoc.")
        else:
            self.translations.pop(fragment, None)
            self.log_msg(f"Rollback: \"{fragment[:30]}...\" -> ve trang thai chua dich.")

    # ------------------------------------------------------------------
    # Man hinh danh sach: phan trang + tim kiem
    # ------------------------------------------------------------------
    def _rebuild_pages(self):
        frags = self.unique_fragments
        if self.search_query:
            q = self.search_query.lower()
            frags = [
                f for f in frags
                if q in f.lower() or q in self.translations.get(f, "").lower()
            ]
        self.pages = [frags[i:i + self.page_size] for i in range(0, len(frags), self.page_size)] or [[]]
        self.current_page = min(self.current_page, len(self.pages) - 1)
        self._render_rows()

    def on_search(self, text):
        self.search_query = text
        self.current_page = 0
        self._rebuild_pages()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._render_rows()

    def next_page(self):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            self._render_rows()

    def _render_rows(self):
        screen = self.sm.get_screen("list")
        container = screen.ids.rows_container
        container.clear_widgets()
        page = self.pages[self.current_page] if self.pages else []
        for frag in page:
            container.add_widget(FragmentRow(self, frag))
        total_pages = len(self.pages)
        self.page_label_text = f"Trang {self.current_page + 1}/{total_pages} " \
                                f"({len(page)} fragment)"

    # ------------------------------------------------------------------
    # Buoc 4: Ap dung & xuat .jar moi (dung cac ham patch_* trong core.py)
    # ------------------------------------------------------------------
    def apply_and_export(self):
        if not self.work_dir:
            self._popup_info("Thieu du lieu", "Hay mo va quet file truoc.")
            return
        if not self.translations:
            self._confirm_popup(
                "Chua dich",
                "Chua co ban dich nao. Ban co muon tiep tuc ap dung "
                "(se khong thay doi gi) khong?",
                on_yes=self._do_export,
            )
        else:
            self._do_export()

    def _confirm_popup(self, title, msg, on_yes):
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        box.add_widget(Label(text=msg, text_size=(dp(280), None)))
        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        popup = Popup(title=title, content=box, size_hint=(0.9, 0.5))

        def _yes(*a):
            popup.dismiss()
            on_yes()

        btns.add_widget(Button(text="Huy", on_release=lambda w: popup.dismiss()))
        btns.add_widget(Button(text="Tiep tuc", on_release=_yes))
        box.add_widget(btns)
        popup.open()

    def _do_export(self):
        out_dir = self._get_output_dir()
        base_name = "game_viethoa.jar"
        out_path = os.path.join(out_dir, base_name)
        n = 1
        while os.path.exists(out_path):
            out_path = os.path.join(out_dir, f"game_viethoa_{n}.jar")
            n += 1
        self.status_text = "Dang ap dung ban dich vao file..."
        threading.Thread(target=self._apply_worker, args=(out_path,), daemon=True).start()

    def _get_output_dir(self):
        if ANDROID:
            try:
                d = primary_external_storage_path()
                download_dir = os.path.join(d, "Download")
                if os.path.isdir(download_dir):
                    return download_dir
                return d
            except Exception:
                pass
        return os.path.expanduser("~")

    def _apply_worker(self, out_path):
        """Sao chep CHINH XAC logic trong _apply_worker cua ban Tkinter
        goc - chi khac phan cap nhat UI (dung self._log_async /
        self._set_status thay vi self.log_msg / self.status_var.set
        truc tiep, vi phai chay tren main thread cua Kivy)."""
        total_patched_strings = 0
        total_patched_files = 0

        by_file = {}
        for r in self.scan_results:
            by_file.setdefault(r.rel_path, []).append(r)

        for rel_path, _r_list in by_file.items():
            full_path = os.path.join(self.work_dir, rel_path)
            try:
                with open(full_path, "rb") as f:
                    data = f.read()
            except Exception as e:
                self._log_async(f"Loi doc {rel_path}: {e}")
                continue

            if data[0:4] == b"\xca\xfe\xba\xbe":
                new_data, n = core.ClassFileStrings.patch(data, self.translations)
                if n:
                    with open(full_path, "wb") as f:
                        f.write(new_data)
                    total_patched_files += 1
                    total_patched_strings += n
                    self._log_async(f"Va {rel_path}: {n} chuoi (class)")
                continue

            r_kinds_check = {r.kind for r in by_file[rel_path]}
            if "mission-table" in r_kinds_check:
                new_data, n = core.patch_mission_table(data, self.translations)
                if n:
                    with open(full_path, "wb") as f:
                        f.write(new_data)
                    total_patched_files += 1
                    total_patched_strings += n
                    self._log_async(f"Va {rel_path}: {n} chuoi (mission-table)")
                continue

            if "sms-table" in r_kinds_check:
                new_data, n = core.patch_sms_table(data, self.translations)
                if n:
                    with open(full_path, "wb") as f:
                        f.write(new_data)
                    total_patched_files += 1
                    total_patched_strings += n
                    self._log_async(f"Va {rel_path}: {n} chuoi (sms-table)")
                continue

            if "pascal-string-list" in r_kinds_check:
                import warnings as _w
                with _w.catch_warnings(record=True) as _caught:
                    _w.simplefilter("always")
                    new_data, n = core.patch_pascal_string_list(data, self.translations)
                for _wm in _caught:
                    self._log_async(f"  !! {_wm.message}")
                if n:
                    with open(full_path, "wb") as f:
                        f.write(new_data)
                    total_patched_files += 1
                    total_patched_strings += n
                    self._log_async(f"Va {rel_path}: {n} chuoi (pascal-string-list)")
                elif _caught:
                    self._log_async(
                        f"  >> {rel_path}: mot so chuoi bi giu nguyen vi ban dich "
                        f"qua dai (> 127 byte). Vui long rut gon ban dich cho cac "
                        f"chuoi bi canh bao o tren."
                    )
                continue

            if "binary-pascal" in r_kinds_check:
                import warnings as _w
                with _w.catch_warnings(record=True) as _caught:
                    _w.simplefilter("always")
                    new_data, n = core.patch_binary_pascal_strings(data, self.translations)
                for _wm in _caught:
                    self._log_async(f"  !! {_wm.message}")
                if n:
                    with open(full_path, "wb") as f:
                        f.write(new_data)
                    total_patched_files += 1
                    total_patched_strings += n
                    self._log_async(f"Va {rel_path}: {n} chuoi (binary-pascal)")
                r_kinds_all = {r.kind for r in by_file[rel_path]}
                text_kinds = r_kinds_all & {"text-quoted", "text-line", "text-token", "text-raw"}
                if not text_kinds:
                    continue

            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue

            r_kinds = {r.kind for r in by_file[rel_path]}
            new_text = text
            n1 = n2 = n3 = n4 = 0
            if "text-quoted" in r_kinds:
                new_text, n1 = core.patch_text_quoted(new_text, self.translations)
            if "text-line" in r_kinds:
                new_text, n2 = core.patch_text_line(new_text, self.translations)
            if "text-token" in r_kinds:
                new_text, n3 = core.patch_text_token(new_text, self.translations)
            if "text-raw" in r_kinds:
                new_text, n4 = core.patch_text_raw(new_text, self.translations)
            n = n1 + n2 + n3 + n4
            if n:
                with open(full_path, "wb") as f:
                    f.write(new_text.encode("utf-8"))
                total_patched_files += 1
                total_patched_strings += n
                self._log_async(f"Va {rel_path}: {n} chuoi (text)")

        if os.path.exists(out_path):
            os.remove(out_path)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for dirpath, _dirs, files in os.walk(self.work_dir):
                for fn in files:
                    full = os.path.join(dirpath, fn)
                    arcname = os.path.relpath(full, self.work_dir)
                    zf.write(full, arcname)

        msg = (f"Hoan tat! Da va {total_patched_strings} chuoi trong "
               f"{total_patched_files} file. Xuat ra: {out_path}")
        self._set_status(msg)
        self._log_async(msg)
        self._show_done_popup(msg)

    @mainthread
    def _show_done_popup(self, msg):
        self._popup_info("Xong", msg)


if __name__ == "__main__":
    Builder.load_string(KV)
    ViethoaApp().run()

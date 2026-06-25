# -*- coding: utf-8 -*-
"""
Viet Hoa Tool - Cong cu Viet hoa file .jar (game Java/J2ME)
============================================================
Chuc nang:
  1. Mo file .jar, giai nen vao thu muc tam
  2. Quet TOAN BO file trong jar (khong phan biet duoi file) de tim
     chuoi text co chua ky tu Han (CJK), bao gom:
       - File .class (doc dung cau truc constant pool cua JVM)
       - Moi file khac (thu decode UTF-8, tim chuoi trong dau nhay
         hoac toan bo dong neu la file text)
  3. Goi Gemini API de dich tu dong, gop 50 chuoi / 1 lan goi
  4. Hien thi bang ket qua cho sua tay truoc khi ap dung
  5. Vá lại dung vi tri trong file goc va dong goi lai thanh .jar moi

Yeu cau: Python 3.8+, thu vien chuan (tkinter di kem san tren
Windows/macOS; tren Linux co the can: sudo apt install python3-tk)
Khong can cai them thu vien ngoai nao (dung urllib co san de goi API).

Cach dung:
    python viethoa_tool.py
"""

import json
import os
import re
import shutil
import struct
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
import zipfile
from pathlib import Path


# ----------------------------------------------------------------------------
# Cau hinh / Config file luu API key
# ----------------------------------------------------------------------------
def _get_app_storage_dir() -> Path:
    """Tren Android, python-for-android cung cap bien moi truong
    ANDROID_PRIVATE de chi thu muc luu tru rieng cua app (khong can
    quyen storage). Tren desktop (test/dev), dung Path.home() nhu
    ban goc."""
    android_private = os.environ.get("ANDROID_PRIVATE")
    if android_private:
        return Path(android_private) / ".viethoa_tool"
    return Path.home() / ".viethoa_tool"


CONFIG_DIR = _get_app_storage_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"
GEMINI_MODEL = "gemini-3.1-flash-lite"  # doi tai day neu Google doi ten model
GEMINI_URL_TMPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

CJK_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
QUOTED_STR_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
# Tach theo cac dau phan dinh thuong gap trong file du lieu dang bang
# cua engine game (vd: "id@name@desc@coolTime@..."), giu lai token de
# co the noi lai dung vi tri khi vá. (Dau '|' KHONG con nam trong day
# vi engine dung '|' theo cu phap chi thi rieng - xem ben duoi.)
TOKEN_SPLIT_RE = re.compile(r'([@\t\r\n]|(?<!\\),)')

# --- Cu phap markup thuc te cua engine game (xac nhan tu du lieu thuc te) ---
# Mot chuoi co the la day cac "chi thi" noi nhau bang dau '|', vd:
#   "按|c:0xff0000|ds:2/4/6/8|ds:移动"
# Tach theo '|' se ra: ["按", "c:0xff0000", "ds:2/4/6/8", "ds:移动"]
#   - doan dau tien (khong tien to)        -> TEXT THUONG, dich neu co chu Han
#   - doan dang "c:XXXXXX"                  -> MA MAU, KHONG BAO GIO dich
#   - doan dang "ds:noi_dung"                -> noi_dung la TEXT HIEN THI, dich duoc
#   - doan dang "ds:br noi_dung" (co tien
#     to phu 'br' ngay sau ds: = lenh xuong
#     dong)                                  -> chi dich phan SAU 'br'
# Ngoai ra, ben trong phan "noi_dung" co the con co them placeholder
# kieu ${bien}, {0}, %s/%d... can duoc bao ve khong dich rieng.
PIPE_DIRECTIVE_RE = re.compile(r'^([a-zA-Z]+):(.*)$', re.DOTALL)
BR_SUBPREFIX_RE = re.compile(r'^br(?![a-zA-Z])')
CONTROL_TAG_RE = re.compile(
    r'\$\{[^}]*\}'              # ${var}
    r'|\{\d+\}'                 # {0}, {1}
    r'|%[sdif]'                 # %s %d %i %f
)



# ----------------------------------------------------------------------------
# Tien ich: Bo dau tieng Viet (dung unicodedata, khong can thu vien ngoai)
# ----------------------------------------------------------------------------
import unicodedata as _ucd

_VIET_ACCENTED = (
    "àáâãäåæèéêëìíîïòóôõöùúûüýÿ"
    "ÀÁÂÃÄÅÆÈÉÊËÌÍÎÏÒÓÔÕÖÙÚÛÜÝŸ"
    "ăắặằẳẵĂẮẶẰẲẴ"
    "âấậầẩẫÂẤẬẦẨẪ"
    "đĐ"
    "êếệềểễÊẾỆỀỂỄ"
    "ôốộồổỗÔỐỘỒỔỖ"
    "ơớợờởỡƠỚỢỜỞỠ"
    "ưứựừửữƯỨỰỪỬỮ"
    "ùúûüůűũụủũỤỦÙÚÛÜŮŰŨ"
    "ìíîïịỉĩỊỈĨ"
)

def remove_vietnamese_accents(text: str) -> str:
    """Chuyen chu tieng Viet co dau sang khong dau.
    Dung unicodedata.normalize('NFD') de tach base char + dau,
    sau do giu lai chi base char (category != Mn = Non-spacing mark).
    Rieng 'd/D co gach ngang' (U+0111/U+0110) -> d/D biet xu ly."""
    text = text.replace("\u0111", "d").replace("\u0110", "D")
    nfd = _ucd.normalize("NFD", text)
    return "".join(c for c in nfd if _ucd.category(c) != "Mn")

def classify_pipe_piece(piece: str):
    """Phan loai 1 doan (giua 2 dau '|', hoac ca chuoi neu khong co
    '|' nao) thanh (prefix_giu_nguyen, body_co_the_dich, co_the_dich).
    Ghep lai prefix+body (sau khi dich body neu can) se ra dung doan
    goc (neu khong dich) hoac doan da dich (neu co)."""
    m = PIPE_DIRECTIVE_RE.match(piece)
    if not m:
        # Doan thuong (vd doan dau tien truoc dau '|' dau tien) - dich
        # truc tiep neu co chu Han.
        return '', piece, True
    name, body = m.group(1), m.group(2)
    if name == 'c':
        # Ma mau dang c:0xff0000 - KHONG BAO GIO dich, giu nguyen ca doan.
        return piece, '', False
    if name == 'ds':
        m2 = BR_SUBPREFIX_RE.match(body)
        if m2:
            sub = m2.group()  # "br"
            return 'ds:' + sub, body[len(sub):], True
        return 'ds:', body, True
    # Chi thi la (vd ten directive khac chua biet) - de an toan: chi
    # dich phan sau dau ':' NEU phan do co chu Han, con khong thi giu
    # nguyen ca doan (tranh dich nham ten bien/ma dieu khien la).
    if CJK_RE.search(body):
        return name + ':', body, True
    return piece, '', False


def split_inline_placeholders(text: str):
    """Tach tiep cac placeholder ${..}/{n}/%s nam BEN TRONG phan body
    (sau khi da tach xong tien to c:/ds:). Tra ve list (doan, la_placeholder)."""
    segs = []
    last = 0
    for m in CONTROL_TAG_RE.finditer(text):
        if m.start() > last:
            segs.append((text[last:m.start()], False))
        segs.append((m.group(), True))
        last = m.end()
    if last < len(text):
        segs.append((text[last:], False))
    if not segs:
        segs = [(text, False)]
    return segs


def extract_fragments_from_raw(raw: str):
    """Tu 1 chuoi 'raw' (co the chua nhieu doan noi boi '|'), tra ve
    danh sach cac FRAGMENT thuan text thuc su can dich - da loai het
    mã mau (c:...), tien to chi thi (ds:/ds:br), va placeholder
    (${..}/{0}/%s). Day la don vi duy nhat duoc gui cho Gemini."""
    frags = []
    for piece in raw.split('|'):
        prefix, body, translatable = classify_pipe_piece(piece)
        if not translatable or not body:
            continue
        for chunk, is_ph in split_inline_placeholders(body):
            if not is_ph and CJK_RE.search(chunk):
                frags.append(chunk)
    return frags


def reconstruct_with_translations(raw: str, fragment_translations: dict):
    """Ghep lai chuoi hoan chinh: GIU NGUYEN 100% mã mau/tien to chi
    thi/placeholder, chi thay phan fragment THUC SU co trong
    fragment_translations. Tra ve (new_raw, so_fragment_da_thay)."""
    new_pieces = []
    changed = 0
    for piece in raw.split('|'):
        prefix, body, translatable = classify_pipe_piece(piece)
        if not translatable:
            new_pieces.append(prefix + body)
            continue
        new_chunks = []
        for chunk, is_ph in split_inline_placeholders(body):
            if is_ph:
                new_chunks.append(chunk)
            elif chunk in fragment_translations and fragment_translations[chunk] != chunk:
                new_chunks.append(fragment_translations[chunk])
                changed += 1
            else:
                new_chunks.append(chunk)
        new_pieces.append(prefix + "".join(new_chunks))
    return "|".join(new_pieces), changed


def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------------
# Phan 1: Doc / vá file .class (cau truc constant pool JVM)
# ----------------------------------------------------------------------------
class ClassFileStrings:
    """Doc cac UTF8 constant trong file .class, tra ve danh sach
    (len_pos, total_len, original_string) de co the vá lai sau."""

    @staticmethod
    def extract(data: bytes):
        if data[0:4] != b'\xca\xfe\xba\xbe':
            return None
        cp_count = struct.unpack('>H', data[8:10])[0]
        pos = 10
        i = 1
        entries = []
        while i < cp_count:
            tag = data[pos]
            pos += 1
            if tag == 1:  # UTF8
                length = struct.unpack('>H', data[pos:pos + 2])[0]
                len_pos = pos
                str_pos = pos + 2
                raw = bytes(data[str_pos:str_pos + length])
                try:
                    s = raw.decode('utf-8')
                except Exception:
                    s = None
                entries.append({
                    'len_pos': len_pos,
                    'total_len': 2 + length,
                    'str': s,
                })
                pos = str_pos + length
            elif tag in (3, 4):
                pos += 4
            elif tag in (5, 6):
                pos += 8
                i += 1
            elif tag in (7, 8, 16, 19, 20):
                pos += 2
            elif tag in (9, 10, 11, 12, 17, 18):
                pos += 4
            elif tag == 15:
                pos += 3
            else:
                # Khong nhan dien duoc tag -> ngung phan tich file nay an toan
                return None
            i += 1
        return entries

    @staticmethod
    def patch(data: bytes, fragment_translations: dict):
        """fragment_translations: { fragment_text: translated_fragment }
        Moi UTF8 constant duoc tach qua reconstruct_with_translations
        truoc khi vá, de cac mã dieu khien |c:..|/|ds:..| trong chinh
        constant do (vd "|ds:br攻击力+") khong bao gio bi dich nham."""
        entries = ClassFileStrings.extract(data)
        if not entries:
            return data, 0
        to_apply = []
        for e in entries:
            s = e['str']
            if s is None:
                continue
            new_s, changed = reconstruct_with_translations(s, fragment_translations)
            if changed:
                to_apply.append((e['len_pos'], e['total_len'], new_s))
        if not to_apply:
            return data, 0
        new_data = bytearray(data)
        # Vá tu cuoi file len dau de offset cac phan truoc khong bi lech
        for len_pos, total_len, new_str in sorted(to_apply, key=lambda x: -x[0]):
            new_bytes = new_str.encode('utf-8')
            if len(new_bytes) > 65535:
                continue  # bo qua neu qua dai, khong the vá UTF8 constant
            new_entry = struct.pack('>H', len(new_bytes)) + new_bytes
            new_data[len_pos:len_pos + total_len] = new_entry
        return bytes(new_data), len(to_apply)


# ----------------------------------------------------------------------------
# Phan 2: Quet toan bo file (khong phan biet duoi) tim chuoi co chu Han
# ----------------------------------------------------------------------------
class ScanResult:
    def __init__(self, rel_path, kind, strings):
        self.rel_path = rel_path   # duong dan tuong doi trong jar
        self.kind = kind           # "class" hoac "text"
        self.strings = strings     # list[str] cac chuoi goc co chu Han


def looks_like_code_line(line: str) -> bool:
    """Nhan dien dong RO RANG la code/script (khong phai text thuan),
    de KHONG dua ca dong vao danh sach 'can dich' - tranh truong hop
    Gemini dich nham nguyen mot dong lenh (vd setVariable(...), func
    onInit() ...) lam hong cu phap khi vá lai. Dau hieu code: co dau
    ngoac (), {, }, dau =, dau ; hoac la tu khoa ham thuong gap."""
    code_markers = ('(', ')', '{', '}', '=', ';')
    if any(m in line for m in code_markers):
        return True
    code_keywords = ('func ', 'setVariable', 'getVariable', 'monsterDistribute',
                     'setAttribute', 'playsound', 'showDlg', 'showMessage',
                     'endif', 'if ', 'goto')
    if any(kw in line for kw in code_keywords):
        return True
    return False


def detect_binary_table_header(data: bytes):
    """Phat hien file dang 'bang du lieu nhi phan' rieng cua engine
    nay (vd res/fb.png, res/skill.png): bat dau bang 1 byte SO LUONG
    FIELD, sau do la N chuoi Pascal-string (1 byte do dai + ten field
    ASCII), ket thuc bang byte 0x00, roi tiep theo la MOT BANG CHI SO
    NHI PHAN (offset/do dai) truoc khi den phan du lieu '@'-delimited
    thuc su.

    File dang nay RAT NGUY HIEM de tu dong vá: khi text duoc dich co
    do dai byte khac voi nguyen ban, bang chi so nhi phan (luu san
    offset/do dai cua tung truong) se bi lech, khien engine doc sai
    vi tri/do dai khi load lai, gay loi nhu
    'NegativeArraySizeException' hoac OutOfMemoryError. Vi day la
    dinh dang nhi phan rieng (khong co tai lieu chinh thuc) nen tool
    se KHONG tu dong vá cac file nay, chi canh bao de nguoi dung tu
    xu ly rieng.

    Tra ve (la_binary_table: bool, field_names: list, header_len: int)."""
    if len(data) < 3:
        return False, [], 0
    n_fields = data[0]
    if n_fields == 0 or n_fields > 64:
        return False, [], 0
    pos = 1
    names = []
    try:
        for _ in range(n_fields):
            ln = data[pos]
            if ln == 0 or ln > 64:
                return False, [], 0
            name_bytes = data[pos + 1:pos + 1 + ln]
            name = name_bytes.decode('ascii')
            if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', name):
                return False, [], 0
            names.append(name)
            pos += 1 + ln
    except (IndexError, UnicodeDecodeError):
        return False, [], 0
    if pos >= len(data) or data[pos] != 0:
        return False, [], 0
    pos += 1
    # Them dieu kien: phai co it nhat 2 field hop le (tranh nhan dien
    # nham 1 file text thuong co byte dau ngau nhien giong do dai)
    if len(names) < 2:
        return False, [], 0
    return True, names, pos


def detect_pascal_string_list(data: bytes):
    """Phat hien dinh dang 'danh sach Pascal-string co header dem so'
    (vd go/wp.dat trong game Kinh Hoa Ky Duyen): 2 byte dau (u16 LE)
    la SO LUONG record, sau do la dung so luong do cac Pascal-string
    LIEN TIEP (1 byte do dai + text UTF-8 dung do dai). Sau khi doc
    het N record, phan CON LAI cua file la BLOCK NHI PHAN (so lieu
    thuoc tinh...) - KHONG dung Pascal-string, va KHONG can dong
    den khi vá vi day la cac truong fixed-width rieng.

    Day la dinh dang AN TOAN de vá (khac voi detect_binary_table_header):
    2 byte dem o dau la SO LUONG RECORD (khong phai tong do dai byte),
    nen khong bi anh huong boi viec text dich ra dai/ngan hon nguyen
    ban - chi can ghi dung lai 1 byte do dai MOI cho moi record sau
    khi dich.

    Tra ve (hop_le: bool, list_cac_chuoi: list[str], offset_bat_dau: int,
    offset_ket_thuc_khoi_text: int) hoac (False, [], 0, 0) neu khong khop."""
    if len(data) < 4:
        return False, [], 0, 0
    n = struct.unpack('<H', data[0:2])[0]
    if n == 0 or n > 5000:
        return False, [], 0, 0
    pos = 2
    texts = []
    for _ in range(n):
        if pos >= len(data):
            return False, [], 0, 0
        ln = data[pos]
        if pos + 1 + ln > len(data):
            return False, [], 0, 0
        chunk = data[pos + 1:pos + 1 + ln]
        try:
            text = chunk.decode('utf-8')
        except UnicodeDecodeError:
            return False, [], 0, 0
        texts.append(text)
        pos += 1 + ln
    # Doi hoi it nhat 1 chuoi co chu Han de chac day la file can dich
    # (tranh nhan nham file toan so/ky tu ASCII ngau nhien khop dinh dang)
    if not any(CJK_RE.search(t) for t in texts):
        return False, [], 0, 0
    return True, texts, 2, pos


def patch_pascal_string_list(data: bytes, fragment_translations: dict):
    """Vá dinh dang pascal-string-list: doc lai N record (N tu 2 byte
    dau, GIU NGUYEN khong doi), dich tung record qua
    reconstruct_with_translations, ghi lai DUNG byte do dai MOI cho
    moi record. Phan BLOCK NHI PHAN sau khoi text duoc copy y nguyen,
    khong dong vao."""
    ok, texts, start, text_end = detect_pascal_string_list(data)
    if not ok:
        return data, 0
    n = struct.unpack('<H', data[0:2])[0]
    new_chunks = []
    changed = 0
    for t in texts:
        new_t, c = reconstruct_with_translations(t, fragment_translations)
        new_bytes = new_t.encode('utf-8')
        # Gioi han 127 byte (KHONG phai 255): Java doc Pascal-string
        # length byte nhu SIGNED byte (-128..127), neu do dai >= 128
        # thi Java thay so AM -> NegativeArraySizeException. Toi da
        # 127 byte la gioi han an toan tuyet doi.
        MAX_PASCAL_BYTES = 127
        if len(new_bytes) > MAX_PASCAL_BYTES:
            # Khong the vá vi vuot qua gioi han signed byte cua Java
            # (Java doc length byte la SIGNED: max 127). Neu dich ra
            # dai hon, giu nguyen chuoi goc de tranh NegativeArraySize.
            # Log len de nguoi dung biet can rut gon ban dich tay.
            trunc_warning = (
                f"[CANH BAO] Chuoi dich qua dai ({len(new_bytes)} byte > "
                f"{MAX_PASCAL_BYTES}), giu nguyen ban goc: '{t[:30]}...'"
            )
            # Gui ve caller qua exception nhe de log (khong lam dung chuong trinh)
            import warnings
            warnings.warn(trunc_warning)
            new_bytes = t.encode('utf-8')
            new_t = t
        else:
            changed += (1 if c else 0)
        new_chunks.append(bytes([len(new_bytes)]) + new_bytes)
    new_text_block = b"".join(new_chunks)
    new_data = data[0:2] + new_text_block + data[text_end:]
    return new_data, changed



def find_pascal_strings_binary(data: bytes):
    """Quet CUC BO (khong can ca file decode UTF-8 thanh cong) de tim
    moi chuoi Pascal-string co chua chu Han trong file nhi phan tuy y.
    Hoc tu viethoa_gui.py: thu tung vi tri la 1-byte-prefix hoac
    2-byte-big-endian-prefix, neu decode duoc UTF-8 va co chu Han thi
    ghi nhan. Day la cach duy nhat bat duoc text trong cac file tron
    lan du lieu nhi phan (bang item/skill/npc/ban do...).

    Tra ve list (offset, prefix_size(1|2), old_len, text)."""
    results = []
    n = len(data)
    i = 0
    while i < n:
        matched = False
        # Thu 1-byte prefix
        if i + 1 <= n:
            L1 = data[i]
            if 1 <= L1 <= 250 and i + 1 + L1 <= n:
                chunk = data[i + 1:i + 1 + L1]
                try:
                    txt = chunk.decode('utf-8')
                    if txt and CJK_RE.search(txt) and all(
                            (ch.isprintable() or ch in '\n\r\t') for ch in txt):
                        results.append((i, 1, L1, txt))
                        i += 1 + L1
                        matched = True
                except UnicodeDecodeError:
                    pass
        # Thu 2-byte big-endian prefix
        if not matched and i + 2 <= n:
            L2 = struct.unpack('>H', data[i:i + 2])[0]
            if 1 <= L2 <= 4000 and i + 2 + L2 <= n:
                chunk = data[i + 2:i + 2 + L2]
                try:
                    txt = chunk.decode('utf-8')
                    if txt and CJK_RE.search(txt) and all(
                            (ch.isprintable() or ch in '\n\r\t') for ch in txt):
                        results.append((i, 2, L2, txt))
                        i += 2 + L2
                        matched = True
                except UnicodeDecodeError:
                    pass
        if not matched:
            i += 1
    return results


def patch_binary_pascal_strings(data: bytes, fragment_translations: dict):
    """Va cac Pascal-string tim duoc boi find_pascal_strings_binary.
    Quy trinh:
      1. Quet het de lay danh sach (offset, prefix_size, old_len, text)
      2. Dich text qua reconstruct_with_translations
      3. Ghi lai tu CUOI LEN DAU (de offset cac entry truoc khong bi
         lech boi su thay doi do dai o phia sau)
    GIOI HAN AN TOAN: neu ban dich (UTF-8) > 127 byte thi giu nguyen
    ban goc (tranh NegativeArraySizeException khi Java doc signed byte)."""
    hits = find_pascal_strings_binary(data)
    if not hits:
        return data, 0
    MAX_SAFE = 127
    to_patch = []
    changed = 0
    for offset, prefix_size, old_len, txt in hits:
        new_txt, c = reconstruct_with_translations(txt, fragment_translations)
        new_bytes = new_txt.encode('utf-8')
        if len(new_bytes) > MAX_SAFE:
            import warnings
            warnings.warn(
                f"[CANH BAO binary-pascal] Chuoi dich qua dai "
                f"({len(new_bytes)} byte > {MAX_SAFE}), giu nguyen: '{txt[:30]}'"
            )
            continue  # giu nguyen entry nay
        if not c:
            continue  # khong co gi thay doi
        to_patch.append((offset, prefix_size, old_len, new_bytes))
        changed += 1

    if not to_patch:
        return data, 0

    buf = bytearray(data)
    # Patch tu CUOI len DAU de offset khong bi lech
    for offset, prefix_size, old_len, new_bytes in sorted(to_patch, key=lambda x: -x[0]):
        new_len = len(new_bytes)
        if prefix_size == 1:
            new_entry = bytes([new_len]) + new_bytes
        else:
            new_entry = struct.pack('>H', new_len) + new_bytes
        old_entry_len = prefix_size + old_len
        buf[offset:offset + old_entry_len] = new_entry

    return bytes(buf), changed

# ----------------------------------------------------------------------------
# Phan 1b: Dinh dang 'mission-table' (vd mission.dat) - header dem so +
# bang offset u32 LE, moi record gom ten ngan (Pascal-string THAT) +
# task_id (Pascal-string THAT) + mo ta dai dung markup '#c5/#n/#r/#t/#c0'
# (KHONG phai Pascal-string - khong co prefix do dai) + footer nhi phan
# DO DAI THAY DOI tuy record (khong the doan truoc, chi xac dinh duoc
# qua bang offset cua record SAU).
# ----------------------------------------------------------------------------

# Tag dieu khien dang '#c5', '#n', '#r', '#t', '#c0'... Giu nguyen 100%,
# KHONG BAO GIO dich, chi dich phan VAN BAN nam GIUA cac tag.
MISSION_TAG_RE = re.compile(r'#[a-zA-Z][0-9A-Za-z]*')


def extract_fragments_from_markup(raw: str):
    """Tach 1 chuoi dung markup '#xx' thanh cac FRAGMENT thuan text
    (phan nam GIUA cac tag) thuc su can dich - giong extract_fragments_from_raw
    nhung cho cu phap '#tag' thay vi '|prefix:'."""
    frags = []
    last = 0
    for m in MISSION_TAG_RE.finditer(raw):
        chunk = raw[last:m.start()]
        if chunk and CJK_RE.search(chunk):
            frags.append(chunk)
        last = m.end()
    tail = raw[last:]
    if tail and CJK_RE.search(tail):
        frags.append(tail)
    return frags


def reconstruct_markup_with_translations(raw: str, fragment_translations: dict):
    """Ghep lai chuoi markup '#xx': GIU NGUYEN 100% cac tag, chi thay
    phan van ban giua tag neu co trong fragment_translations.
    Tra ve (new_raw, so_fragment_da_thay)."""
    pieces = []
    last = 0
    changed = 0
    for m in MISSION_TAG_RE.finditer(raw):
        chunk = raw[last:m.start()]
        if chunk in fragment_translations and fragment_translations[chunk] != chunk:
            pieces.append(fragment_translations[chunk])
            changed += 1
        else:
            pieces.append(chunk)
        pieces.append(m.group())
        last = m.end()
    tail = raw[last:]
    if tail in fragment_translations and fragment_translations[tail] != tail:
        pieces.append(fragment_translations[tail])
        changed += 1
    else:
        pieces.append(tail)
    return ''.join(pieces), changed


def detect_mission_table(data: bytes):
    """Phat hien dinh dang 'mission-table': 2 byte dau (u16 LE) = SO
    LUONG RECORD, theo sau la N offset (u32 LE) - offset[i] la vi tri
    TUYET DOI trong file noi record i bat dau (offset[0] phai dung
    bang vi tri ngay sau bang offset). Moi record:
        [1-byte len][ten ngan UTF-8]      (Pascal-string THAT)
        [6 byte binary, khong dong]
        [1-byte len][task_id ASCII]       (Pascal-string THAT)
        [2 byte binary, khong dong]
        [mo ta dai UTF-8 markup '#xx', KET THUC o lan xuat hien '#n'
         CUOI CUNG trong record]
        [footer nhi phan, do dai THAY DOI - moi thu sau '#n' cuoi,
         KHONG decode, KHONG dong, chi copy y nguyen]
    Diem mau chot de AN TOAN: tim ranh gioi mo ta/footer bang
    bytes.rfind(b'#n') tren DU LIEU BYTE THO (khong decode UTF-8 truoc),
    nen khong bao gio nham voi continuation byte cua chu Han.
    Tra ve list[dict] (mot phan tu / record) hoac None neu khong khop."""
    if len(data) < 4:
        return None
    n = struct.unpack('<H', data[0:2])[0]
    if n == 0 or n > 5000:
        return None
    header_end = 2 + 4 * n
    if header_end > len(data):
        return None
    offsets = list(struct.unpack('<%dI' % n, data[2:header_end]))
    if offsets[0] != header_end:
        return None
    for i in range(n - 1):
        if not (offsets[i] < offsets[i + 1] <= len(data)):
            return None
    if not (header_end <= offsets[-1] < len(data)):
        return None
    bounds = offsets + [len(data)]

    records = []
    for i in range(n):
        start, end = bounds[i], bounds[i + 1]
        rec = data[start:end]
        pos = 0
        if pos >= len(rec):
            return None
        name_len = rec[pos]
        pos += 1
        if pos + name_len > len(rec):
            return None
        name_bytes = rec[pos:pos + name_len]
        pos += name_len
        try:
            name = name_bytes.decode('utf-8')
        except UnicodeDecodeError:
            return None
        if pos + 6 > len(rec):
            return None
        bin6 = rec[pos:pos + 6]
        pos += 6
        if pos >= len(rec):
            return None
        tid_len = rec[pos]
        pos += 1
        if pos + tid_len > len(rec):
            return None
        tid_bytes = rec[pos:pos + tid_len]
        pos += tid_len
        try:
            tid = tid_bytes.decode('ascii')
        except UnicodeDecodeError:
            return None
        if pos + 2 > len(rec):
            return None
        bin2 = rec[pos:pos + 2]
        pos += 2
        body = rec[pos:]
        idx = body.rfind(b'#n')
        if idx == -1:
            return None
        desc_bytes = body[:idx + 2]
        footer_bytes = body[idx + 2:]
        try:
            desc = desc_bytes.decode('utf-8')
        except UnicodeDecodeError:
            return None
        records.append({
            'name': name, 'bin6': bin6, 'tid': tid, 'bin2': bin2,
            'desc': desc, 'footer': footer_bytes,
        })

    # Doi hoi it nhat 1 record co chu Han (ten hoac mo ta) de chac day
    # la file can dich, tranh nhan nham file toan so/ASCII ngau nhien.
    if not any(CJK_RE.search(r['name']) or CJK_RE.search(r['desc']) for r in records):
        return None
    return records


def patch_mission_table(data: bytes, fragment_translations: dict):
    """Va dinh dang mission-table. Khac voi pascal-string-list/binary-pascal:
    phan mo ta dai KHONG bi gioi han do dai (vi duoc dinh vi boi bang
    offset, khong phai Pascal-string 1-byte), nen co the dich dai/ngan
    tuy y - chi can GHI LAI TOAN BO bang offset cho dung voi do dai
    moi cua tung record. Rieng ten ngan VAN la Pascal-string 1-byte
    nen van gioi han 127 byte (giong quy uoc an toan o cac ham khac
    trong file nay, de tranh Java doc length byte la SIGNED)."""
    records = detect_mission_table(data)
    if records is None:
        return data, 0

    MAX_NAME_BYTES = 127
    changed = 0
    new_records_bytes = []
    for r in records:
        new_name = fragment_translations.get(r['name'], r['name'])
        new_name_bytes = new_name.encode('utf-8')
        if len(new_name_bytes) > MAX_NAME_BYTES:
            import warnings
            warnings.warn(
                f"[CANH BAO mission-table] Ten nhiem vu dich qua dai "
                f"({len(new_name_bytes)} byte > {MAX_NAME_BYTES}), giu nguyen: "
                f"'{r['name'][:30]}'"
            )
            new_name_bytes = r['name'].encode('utf-8')
        elif new_name != r['name']:
            changed += 1

        new_desc, c = reconstruct_markup_with_translations(r['desc'], fragment_translations)
        changed += c
        new_desc_bytes = new_desc.encode('utf-8')
        new_tid_bytes = r['tid'].encode('ascii')

        rec_bytes = (
            bytes([len(new_name_bytes)]) + new_name_bytes +
            r['bin6'] +
            bytes([len(new_tid_bytes)]) + new_tid_bytes +
            r['bin2'] +
            new_desc_bytes + r['footer']
        )
        new_records_bytes.append(rec_bytes)

    n = len(new_records_bytes)
    header_len = 2 + 4 * n
    offsets = []
    pos = header_len
    for rb in new_records_bytes:
        offsets.append(pos)
        pos += len(rb)
    header = struct.pack('<H', n) + struct.pack('<%dI' % n, *offsets)
    new_data = header + b''.join(new_records_bytes)
    return new_data, changed


def detect_sms_table(data: bytes):
    """Phat hien dinh dang 'sms-table' (vd jhy.smc2 - bang tin nhan SMS
    nap the/qua tang trong game): 1 BYTE dau la SO LUONG record (N).
    Sau do la N record LIEN TIEP, moi record:
        [u16 LE do dai byte cua text][text UTF-8]
        [2 byte binary trailer, KHONG dong - co the la ma dich vu/gia
         cuoc SMS rieng cho tung tin]

    Day la dinh dang KHAC voi 'pascal-string-list': o do so luong la
    u16 LE va do dai tung chuoi la 1 byte; o day so luong la 1 BYTE
    va do dai tung chuoi la u16 LE, them 2 byte trailer SAU MOI text.

    AN TOAN QUAN TRONG: phai nhan dien rieng dinh dang nay va loai no
    KHOI find_pascal_strings_binary - scanner do gia dinh do dai la
    1-byte hoac 2-byte BIG-ENDIAN va khong biet ve 2-byte trailer giua
    cac record, nen no se khop NHAM vao giua mot cau dai (vi du chu so
    ASCII trong "5000" bi doc nham la "do dai Pascal-string"), patch
    sai vi tri -> lech cau truc -> game bao
    ArrayIndexOutOfBoundsException: -1 khi mo man hinh SMS.

    Tra ve list[dict(text, trailer)] hoac None neu khong khop (phai
    doc HET DUNG den byte cuoi file, khong du khong thieu)."""
    if len(data) < 1:
        return None
    n = data[0]
    if n == 0 or n > 2000:
        return None
    pos = 1
    records = []
    for _ in range(n):
        if pos + 2 > len(data):
            return None
        ln = struct.unpack('<H', data[pos:pos + 2])[0]
        pos += 2
        if pos + ln > len(data):
            return None
        chunk = data[pos:pos + ln]
        try:
            text = chunk.decode('utf-8')
        except UnicodeDecodeError:
            return None
        pos += ln
        if pos + 2 > len(data):
            return None
        trailer = data[pos:pos + 2]
        pos += 2
        records.append({'text': text, 'trailer': trailer})
    # Phai khop CHINH XAC den het file - tranh nhan nham cau truc khac
    if pos != len(data):
        return None
    if not any(CJK_RE.search(r['text']) for r in records):
        return None
    return records


def patch_sms_table(data: bytes, fragment_translations: dict):
    """Va dinh dang sms-table. Do dai text dung u16 LE (toi da 65535,
    KHONG bi gioi han 127 byte nhu Pascal-string 1-byte), nen co the
    dich dai hon ban goc ma khong lo NegativeArraySizeException - chi
    can ghi dung lai do dai u16 LE MOI cho tung record. Truong nhi
    phan (2-byte trailer) duoc GIU NGUYEN 100%, khong dong vao."""
    records = detect_sms_table(data)
    if records is None:
        return data, 0

    MAX_SAFE_BYTES = 30000  # an toan xa duoi gioi han u16 thuc te (65535)
    changed = 0
    out = bytearray()
    out.append(len(records))
    for r in records:
        new_text, c = reconstruct_with_translations(r['text'], fragment_translations)
        new_bytes = new_text.encode('utf-8')
        if len(new_bytes) > MAX_SAFE_BYTES:
            import warnings
            warnings.warn(
                f"[CANH BAO sms-table] Chuoi dich qua dai "
                f"({len(new_bytes)} byte > {MAX_SAFE_BYTES}), giu nguyen: "
                f"'{r['text'][:30]}'"
            )
            new_bytes = r['text'].encode('utf-8')
        elif c:
            changed += 1
        out += struct.pack('<H', len(new_bytes))
        out += new_bytes
        out += r['trailer']
    return bytes(out), changed


def scan_directory(root_dir: str, progress_cb=None):
    """Quet TOAN BO file trong root_dir, bat ke duoi file la gi.
    Tra ve list[ScanResult]. Moi ScanResult.strings la danh sach cac
    chuoi 'raw' (nguyen ban, co the con mang theo mã dieu khien) -
    viec boc tach fragment thuan text de dich duoc lam o tang tren
    (xem extract_fragments_from_raw o dau file), KHONG lam o day, de
    van giu duoc chuoi raw goc phuc vu cho buoc vá lai file sau nay."""
    results = []
    all_files = []
    for dirpath, _dirs, files in os.walk(root_dir):
        for fn in files:
            all_files.append(os.path.join(dirpath, fn))

    total = len(all_files)
    for idx, fpath in enumerate(all_files):
        if progress_cb:
            progress_cb(idx + 1, total, fpath)
        rel = os.path.relpath(fpath, root_dir)

        # AN TOAN TRUOC: file MANIFEST.MF co dinh dang RAT NGHIEM NGAT
        # (bat buoc dung CRLF, bat buoc co dong trong ket thuc file) -
        # mot sai sot nho ve line-ending khi vá tu dong co the khien
        # launcher khong doc duoc MIDlet, gay loi ngay luc khoi dong
        # (truoc ca khi vao constructor). Vi MANIFEST.MF thuong chi co
        # 1-2 dong can dich (ten game/mo ta), nguoi dung nen tu chinh
        # tay file nay rieng de dam bao dung chuan, nen tool se KHONG
        # tu dong dua file nay vao danh sach can vá.
        if rel.replace('\\', '/').upper() == 'META-INF/MANIFEST.MF':
            continue

        try:
            with open(fpath, 'rb') as f:
                data = f.read()
        except Exception:
            continue

        # Thu nhan dien la file .class hop le (theo magic number,
        # KHONG chi dua vao duoi file, vi co the bi doi ten)
        if data[0:4] == b'\xca\xfe\xba\xbe':
            entries = ClassFileStrings.extract(data)
            if entries:
                cjk_strings = [e['str'] for e in entries
                               if e['str'] and CJK_RE.search(e['str'])]
                if cjk_strings:
                    results.append(ScanResult(rel, "class", cjk_strings))
            continue

        # AN TOAN TRUOC TIEN: thu nhan dien dinh dang 'mission-table'
        # (vd mission.dat) - PHAI kiem tra TRUOC pascal-string-list va
        # binary-pascal, vi cau truc nay co header dem so + bang offset
        # u32 LE rieng, va phan mo ta dai (markup '#xx') KHONG co
        # Pascal-string prefix. Neu khong loai tru truoc, buoc quet
        # binary-pascal o duoi se doc nham hang tram continuation byte
        # cua chu Han trong phan mo ta nhu la "do dai Pascal-string",
        # patch sai vi tri, lam lech toan bo offset table phia sau
        # (gay ArrayIndexOutOfBoundsException khi engine doc lai file).
        mission_records = detect_mission_table(data)
        if mission_records is not None:
            raw_strings = []
            for r in mission_records:
                if CJK_RE.search(r['name']):
                    raw_strings.append(r['name'])
                if CJK_RE.search(r['desc']):
                    raw_strings.append(r['desc'])
            if raw_strings:
                results.append(ScanResult(rel, "mission-table", raw_strings))
            continue

        # Thu nhan dien dinh dang 'sms-table' (vd jhy.smc2 - bang tin
        # nhan SMS nap the) - cung PHAI kiem tra TRUOC binary-pascal vi
        # ly do tuong tu mission-table: header dem so 1-byte + do dai
        # u16 LE + 2-byte trailer rieng, neu khong loai tru truoc thi
        # scanner binary-pascal se khop nham giua cau (xem chu thich
        # chi tiet trong detect_sms_table).
        sms_records = detect_sms_table(data)
        if sms_records is not None:
            raw_strings = [r['text'] for r in sms_records if CJK_RE.search(r['text'])]
            if raw_strings:
                results.append(ScanResult(rel, "sms-table", raw_strings))
            continue

        # Thu nhan dien dinh dang 'pascal-string-list' (vd go/wp.dat):
        # 2 byte dau = so luong record, sau do N Pascal-string lien
        # tiep, roi mot BLOCK NHI PHAN o cuoi (so lieu thuoc tinh...).
        # Phai kiem tra dinh dang nay TRUOC khi thu decode ca file
        # bang UTF-8, vi phan block nhi phan o cuoi se khien decode
        # toan file luon THAT BAI (file co text hop le o dau nhung
        # van bi bo qua oan uong neu chi thu decode() ca file).
        is_pasc, pasc_texts, _pasc_start, _pasc_end = detect_pascal_string_list(data)
        if is_pasc:
            cjk_texts = [t for t in pasc_texts if CJK_RE.search(t)]
            if cjk_texts:
                results.append(ScanResult(rel, "pascal-string-list", cjk_texts))
            continue

        # Khong phai .class va khong phai pascal-string-list co header dem so
        # -> TRUOC TIEN quet cu phap binary Pascal (1-byte hoac 2-byte big-endian
        # prefix) trong toan bo file - kieu nay bat duoc text trong cac file nhi
        # phan tron lan (bang item/skill/npc/ten ban do...) MA KHONG yeu cau ca
        # file phai decode duoc thanh UTF-8 (khac voi buoc phan tich text ben duoi).
        # Neu quet binary ra ket qua, ghi nhan loai "binary-pascal" va TIEP TUC
        # xuong buoc UTF-8 de khong bo sot truong hop file vua co binary-pascal vua
        # co phan text thuan (truong hop hiem nhung co the xay ra).
        binary_pascal_hits = find_pascal_strings_binary(data)
        if binary_pascal_hits:
            bp_texts = [txt for _off, _psz, _olen, txt in binary_pascal_hits]
            results.append(ScanResult(rel, "binary-pascal", bp_texts))
            # Khong 'continue' o day - tiep tuc thu decode UTF-8 de bat them
            # text dang quoted/line/token neu file cung co phan text thuan

        # Thu decode text (du la duoi gi: .png, .bin,
        # .dat, .txt, khong duoi...) de bat ca file gia dang resource anh
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            continue  # day la binary thuc su (anh/am thanh thuc), bo qua

        if not CJK_RE.search(text):
            continue

        # AN TOAN TRUOC: kiem tra file co phai dang 'bang nhi phan +
        # bang chi so offset/do dai' rieng cua engine nay khong (vd
        # res/fb.png, res/skill.png). Neu co, KHONG dua vao danh sach
        # can vá - vi thay doi do dai text se lam lech bang chi so nhi
        # phan, gay loi nghiem trong khi game doc lai file
        # (NegativeArraySizeException / OutOfMemoryError). Chi canh
        # bao de nguoi dung biet va tu xu ly rieng cho cac file nay.
        is_bin_table, field_names, _hdr_len = detect_binary_table_header(data)
        if is_bin_table:
            results.append(ScanResult(
                rel, "binary-table-SKIPPED",
                [f"(Bo qua de an toan - co {len(field_names)} field: "
                 f"{', '.join(field_names)})"]
            ))
            continue

        # Quet song song NHIEU kieu cu phap, KHONG loai tru nhau, vi
        # cac file co the tron lan nhieu kieu (vd: mot phan dung dau
        # nhay, mot phan dung dau '@' de ngan truong du lieu nhu cac
        # file dinh nghia item/skill: "id@name@desc@coolTime@...").
        found_kinds = set()

        quoted = [m.group(1) for m in QUOTED_STR_RE.finditer(text)
                  if CJK_RE.search(m.group(1))]
        if quoted:
            results.append(ScanResult(rel, "text-quoted", quoted))
            found_kinds.add("text-quoted")

        # CHI lay dong nao KHONG giong code (vd file config dang
        # "Key:gia tri tieng Trung" nhu dcn.bin, hoac dong comment
        # "#...."). Dong nao co dau hieu code (dau ngoac, dau =, tu
        # khoa ham...) se KHONG dua vao day de tranh Gemini dich nham
        # nguyen mot dong lenh, pha hong cu phap script.
        lines = [ln for ln in text.splitlines()
                 if CJK_RE.search(ln) and not looks_like_code_line(ln)]
        if lines:
            results.append(ScanResult(rel, "text-line", lines))
            found_kinds.add("text-line")

        # Tach theo cac dau phan dinh thuong gap trong file du lieu
        # dang bang (item/skill/dialogue duoc engine luu dang
        # "field1@field2@field3..."). Chi lay token nao THUC SU co
        # chu Han, bo qua token la so/ma (vd "dianlongzuan_", "30").
        tokens = TOKEN_SPLIT_RE.split(text)
        cjk_tokens = [t for t in tokens if CJK_RE.search(t)]
        if cjk_tokens:
            results.append(ScanResult(rel, "text-token", cjk_tokens))
            found_kinds.add("text-token")

        if not found_kinds:
            # An toan: van con chu Han nhung khong khop kieu nao o tren
            # (truong hop hiem) -> bao cao nguyen ca file de khong sot
            results.append(ScanResult(rel, "text-raw", [text]))

    return results




def patch_text_quoted(text: str, fragment_translations: dict):
    count = 0

    def repl(m):
        nonlocal count
        s = m.group(1)
        new_s, changed = reconstruct_with_translations(s, fragment_translations)
        if changed:
            count += changed
            return '"' + new_s.replace('"', '\\"') + '"'
        return m.group(0)

    new_text = QUOTED_STR_RE.sub(repl, text)
    return new_text, count


def patch_text_line(text: str, fragment_translations: dict):
    """Vá theo dong, nhung BAO TOAN TUYET DOI ky tu xuong dong goc cua
    tung dong (dung keepends=True) - khong doan/chuan hoa 1 kieu
    \\r\\n hay \\n chung cho ca file. Cach lam cu (tach bo het dau
    xuong dong roi doan lai 1 kieu de noi) co rui ro lam MAT dong
    trong cuoi file hoac doi nham CRLF -> LF, gay loi nghiem trong
    cho cac file co dinh dang nghiem ngat nhu MANIFEST.MF."""
    count = 0
    # splitlines(keepends=True) giu lai chinh xac \r\n / \n / \r o
    # cuoi moi dong (hoac khong co gi neu la dong cuoi khong xuong
    # dong) - noi lai bang "".join() se cho ra DUNG 100% text goc neu
    # khong co thay doi gi.
    raw_lines = text.splitlines(keepends=True)
    new_parts = []
    for raw_ln in raw_lines:
        # Tach rieng noi dung va phan xuong dong (neu co) o cuoi dong
        stripped = raw_ln.splitlines()[0] if raw_ln.splitlines() else raw_ln
        line_ending = raw_ln[len(stripped):]  # phan con lai la \r\n/\n/\r hoac rong
        new_ln, changed = reconstruct_with_translations(stripped, fragment_translations)
        new_parts.append(new_ln + line_ending)
        count += changed
    return "".join(new_parts), count


def patch_text_token(text: str, fragment_translations: dict):
    """Vá cac token tach boi dau @ / , / tab / xuong dong. Dung
    split() voi nhom capture de giu lai delimiter trong ket qua, nho
    vay noi lai bang join() se cho ra dung nguyen ban text goc, tru
    cac fragment da duoc thay the (mã dieu khien |c:..|/|ds:..| trong
    tung token van duoc giu nguyen qua reconstruct_with_translations)."""
    count = 0
    parts = TOKEN_SPLIT_RE.split(text)
    new_parts = []
    for p in parts:
        new_p, changed = reconstruct_with_translations(p, fragment_translations)
        new_parts.append(new_p)
        count += changed
    return "".join(new_parts), count


def patch_text_raw(text: str, fragment_translations: dict):
    """Truong hop hiem: ca file duoc coi la 1 chuoi duy nhat (khong
    khop dau nhay, dong, hay token nao ca)."""
    new_text, changed = reconstruct_with_translations(text, fragment_translations)
    return new_text, changed


# ----------------------------------------------------------------------------
# Phan 3: Goi Gemini API de dich, gop batch
# ----------------------------------------------------------------------------
class GeminiTranslator:
    def __init__(self, api_key: str, model: str = GEMINI_MODEL, no_accent: bool = False):
        self.api_key = api_key
        self.model = model
        self.no_accent = no_accent

    def translate_batch(self, strings: list, log_cb=None) -> dict:
        """Gui toi da 50 chuoi / lan goi. Tra ve dict {goc: dich}.
        Dung dinh dang JSON co so thu tu de tranh lech dong khi
        chuoi co chua ky tu xuong dong. log_cb(msg) duoc goi de bao
        tien do/loi realtime ra GUI (neu co)."""
        if not strings:
            return {}

        if log_cb:
            log_cb(f"  -> Gui {len(strings)} chuoi toi Gemini ({self.model})...")

        numbered = {str(i): s for i, s in enumerate(strings)}
        no_accent_note = (
            " Dich KHONG DAU (khong su dung dau sac/huyen/hoi/nga/nang, "
            "khong dung chu co dau nhu a/e/o/u/i co dau, khong dung d gach ngang). "
            "Chi dung ky tu ASCII thuong gap (a-z, A-Z, 0-9, khoang trang, dau cham, phay)."
            if self.no_accent else ""
        )
        prompt = (
            "Ban la bien dich vien game tieng Trung -> tieng Viet. "
            "Hay dich cac chuoi sau sang tieng Viet tu nhien, sat nghia, "
            "giu van phong phu hop game kiem hiep/tien hiep."
            + no_accent_note + " "
            "Neu chuoi co chua ma dieu khien dang |c:...| hoac |ds:...| "
            "hoac cac the ky thuat khac, GIU NGUYEN cac the do, chi dich "
            "phan noi dung tieng Trung. Tra loi DUY NHAT bang 1 doi tuong "
            "JSON dang {\"0\": \"ban dich 0\", \"1\": \"ban dich 1\", ...} "
            "voi cung so luong key nhu du lieu dau vao, khong them giai "
            "thich gi khac.\n\n"
            "Du lieu can dich (dang JSON, key la so thu tu, value la "
            "chuoi goc tieng Trung):\n"
            + json.dumps(numbered, ensure_ascii=False)
        )

        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3},
        }

        url = GEMINI_URL_TMPL.format(model=self.model)
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            hint = ""
            if e.code == 429:
                hint = " (CO THE DA VUOT RATE LIMIT - hay doi vai giay roi thu lai trang nay)"
            elif e.code in (401, 403):
                hint = " (kiem tra lai API key)"
            msg = f"Gemini API loi HTTP {e.code}{hint}: {err_body[:300]}"
            if log_cb:
                log_cb(f"  !! LOI: {msg}")
            raise RuntimeError(msg)
        except Exception as e:
            msg = f"Goi Gemini API that bai: {e}"
            if log_cb:
                log_cb(f"  !! LOI: {msg}")
            raise RuntimeError(msg)

        data = json.loads(raw)
        try:
            text_out = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            msg = f"Phan hoi Gemini khong dung dinh dang: {raw[:500]}"
            if log_cb:
                log_cb(f"  !! LOI: {msg}")
            raise RuntimeError(msg)

        # Don dep neu model tra ve kem ```json ... ```
        text_out = text_out.strip()
        if text_out.startswith("```"):
            text_out = re.sub(r'^```[a-zA-Z]*\n?', '', text_out)
            text_out = re.sub(r'\n?```$', '', text_out)

        try:
            parsed = json.loads(text_out)
        except json.JSONDecodeError as e:
            msg = f"Khong parse duoc JSON tu Gemini: {e}\nNoi dung: {text_out[:500]}"
            if log_cb:
                log_cb(f"  !! LOI: {msg}")
            raise RuntimeError(msg)

        result = {}
        for k, v in parsed.items():
            idx = int(k)
            if 0 <= idx < len(strings):
                # Neu no_accent: bo dau toan bo ban dich de dam bao
                # (Gemini doi khi van de lai dau du da dua vao prompt)
                final_v = remove_vietnamese_accents(v) if self.no_accent else v
                result[strings[idx]] = final_v

        if log_cb:
            log_cb(f"  <- Nhan duoc {len(result)} ban dich.")
        return result


def translate_all(translator: GeminiTranslator, unique_strings: list,
                   batch_size=50, progress_cb=None, log_cb=None, stop_flag=None):
    """Dich toan bo danh sach chuoi duy nhat, tra ve dict {goc: dich}."""
    result = {}
    batches = [unique_strings[i:i + batch_size]
               for i in range(0, len(unique_strings), batch_size)]
    for bi, batch in enumerate(batches):
        if stop_flag and stop_flag.is_set():
            if log_cb:
                log_cb("Da dung theo yeu cau.")
            break
        if progress_cb:
            progress_cb(bi + 1, len(batches))
        try:
            translated = translator.translate_batch(batch, log_cb=log_cb)
            result.update(translated)
        except Exception as e:
            # Ghi nhan loi nhung tiep tuc cac batch khac
            if log_cb:
                log_cb(f"  !! Batch {bi + 1}/{len(batches)} loi, bo qua: {e}")
            for s in batch:
                result.setdefault(s, f"[LOI DICH: {e}]")
        time.sleep(0.5)  # tranh goi qua nhanh
    return result


# ----------------------------------------------------------------------------

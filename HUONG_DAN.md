# Viet Hoa Tool — Ban Android (build APK qua GitHub Actions)

Tool nay duoc viet lai giao dien bang Kivy (thay cho Tkinter, vi
Tkinter khong chay duoc tren Android). Toan bo logic Viet hoa file
.jar (doc constant pool .class, mission-table, sms-table,
pascal-string-list, goi Gemini API...) nam trong `core.py` va duoc
giu nguyen 100% tu ban goc, khong sua doi gi ve logic.

Vi may chu (sandbox) cua minh khong the tai Android SDK/NDK de tu
build APK, ban se dung **GitHub Actions** — dich vu build mien phi
cua GitHub — de bien bo code nay thanh file `.apk`. Ban khong can
cai dat gi tren may, chi can 1 tai khoan GitHub (mien phi).

## Cac file trong bo nay

- `main.py` — Giao dien Kivy (man hinh chinh + man hinh xem/sua chuoi)
- `core.py` — Toan bo logic xu ly (giu nguyen 100% tu ban goc)
- `buildozer.spec` — Cau hinh build Android
- `icon.png` — Icon cua app
- `.github/workflows/build.yml` — Kich ban tu dong build APK
- `.gitignore` — Bo qua file rac khi upload

## Cach lay file APK — lam theo dung 6 buoc sau

### Buoc 1: Tao tai khoan GitHub (bo qua neu da co)
Vao https://github.com/signup va lam theo huong dan (chi can email).

### Buoc 2: Tao repository (kho chua code) moi
1. Dang nhap GitHub, bam dau **+** o goc tren ben phai > **New repository**.
2. Dat ten bat ky, vi du `viethoa-tool-apk`.
3. De **Public** hoac **Private** deu duoc (Private van build mien phi).
4. KHONG tick "Add a README file" (de trong).
5. Bam **Create repository**.

### Buoc 3: Tai len toan bo file trong bo nay
1. Trong trang repository vua tao, bam **uploading an existing file**
   (hoac vao tab **Add file > Upload files**).
2. Keo-tha (hoac chon) **TAT CA** cac file va thu muc sau vao:
   - `main.py`
   - `core.py`
   - `buildozer.spec`
   - `icon.png`
   - `.gitignore`
   - Ca thu muc `.github` (chua file `.github/workflows/build.yml`)

   **Luu y quan trong:** giao dien web cua GitHub cho phep keo-tha
   ca thu muc `.github` neu ban keo-tha tu may tinh (Windows/Mac) -
   trinh duyet se tu giu nguyen cau truc thu muc con. Neu dung nut
   "choose your files" thi co thien doi luc chon dung ca file an
   trong `.github/workflows/`.
3. Cuoi trang, bam **Commit changes**.

### Buoc 4: Cho GitHub tu dong build
1. Sau khi commit xong, vao tab **Actions** o thanh menu tren cung
   cua repository.
2. Ban se thay 1 workflow ten "Build APK" dang chay (bieu tuong vang
   xoay tron = dang chay; xanh = xong; do = loi).
3. Lan build dau tien thuong mat **15–30 phut** (vi phai tai Android
   SDK/NDK). Cac lan sau (neu sua code va day lai) se nhanh hon nho
   co cache.

### Buoc 5: Tai file APK ve
1. Khi thay dau **xanh** (thanh cong), bam vao lan chay do.
2. Keo xuong phan **Artifacts** o cuoi trang, ban se thay file ten
   `viethoa-tool-apk` — bam vao de tai ve (dang file .zip, ben trong
   co file .apk).
3. Giai nen file zip do tren dien thoai hoac may tinh de lay file
   `.apk`.

### Buoc 6: Cai len dien thoai Android
1. Chuyen file `.apk` vao dien thoai (qua USB, Zalo, Google Drive...).
2. Mo file .apk tren dien thoai. Neu Android canh bao "khong xac
   dinh nguon goc" / "Unknown sources", vao **Cai dat > bam cho phep**
   roi cai lai (day la canh bao binh thuong vi app khong tai tu
   Google Play, khong phai loi virus).
3. Mo app "Viet Hoa Tool" va su dung nhu ban desktop: Mo .jar > Quet
   > Dich tat ca > Xem/Sua chuoi > Ap dung & Xuat .jar.

## Neu Buoc 4 bi bao loi (dau do)

Bam vao lan chay bi loi > bam vao job "build" > doc dong chu loi
mau do gan cuoi log. Cac loi thuong gap:

- **Thieu file/sai ten file** khi upload (vd quen upload `.github`
  hoac `icon.png`) — kiem tra lai da upload du file chua.
- **Het luot build mien phi trong thang** — GitHub Actions cho tai
  khoan ca nhan (Public repo) la **khong gioi han**; Private repo co
  2000 phut/thang mien phi, du dung nhieu.

Neu van bi loi ma khong ro nguyen nhan, gui lai noi dung dong loi
mau do de duoc ho tro tiep.

## File .jar sau khi Viet hoa duoc luu o dau tren dien thoai?

App se luu file `game_viethoa.jar` (hoac `game_viethoa_1.jar`,
`_2.jar`... neu trung ten) vao thu muc **Download** cua dien thoai.

## Ghi chu ve API key Gemini

Ban can co API key cua Google Gemini de dung chuc nang dich tu dong
(giong ban desktop). Lay tai: https://aistudio.google.com/apikey —
mien phi voi han muc su dung co ban.

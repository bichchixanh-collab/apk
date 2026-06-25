[app]

title = Viet Hoa Tool
package.name = viethoatool
package.domain = org.viethoa

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

version = 1.4.2

requirements = python3,kivy==2.3.1,plyer,pyjnius

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icon.png

android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

# API toi thieu / target - gia tri an toan, tuong thich phan lon may Android
android.minapi = 24
android.api = 34
android.ndk = 25b

# Chi build 1 kien truc (arm64-v8a) de giam thoi gian build va dung
# luong tai xuong - phu hop hau het dien thoai Android tu 2018 tro
# lai. Neu can ho tro may rat cu (32-bit), them lai armeabi-v7a sau.
android.archs = arm64-v8a

# Cho phep ghi vao thu muc Download cua may (luu file .jar da Viet hoa)
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1

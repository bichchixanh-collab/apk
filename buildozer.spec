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
android.archs = arm64-v8a,armeabi-v7a

# Cho phep ghi vao thu muc Download cua may (luu file .jar da Viet hoa)
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1

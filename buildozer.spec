[app]
title           = Stock Dashboard
package.name    = stockdashboard
package.domain  = org.stockdashboard
source.dir      = .
source.include_exts = py
version         = 1.0.0

requirements = python3,kivy==2.3.0,requests,certifi,urllib3,idna

orientation     = portrait
fullscreen      = 0
android.api     = 34
android.minapi  = 21
android.archs   = arm64-v8a, armeabi-v7a

android.permissions = INTERNET

[buildozer]
log_level  = 2
warn_on_root = 1

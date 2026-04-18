[app]
title           = Stock Dashboard
package.name    = stockdashboard
package.domain  = org.stockdashboard
source.dir      = .
source.include_exts = py
version         = 1.0.0

# Android 필수 패키지
# yfinance/pandas는 빌드 시간이 오래 걸릴 수 있음
# 최소 빌드: requirements = python3,kivy==2.3.0,requests,certifi,charset-normalizer,urllib3,idna
# 전체 빌드 (S&P500 폴백 포함):
requirements = python3,kivy==2.3.0,requests,certifi,charset-normalizer,urllib3,idna

orientation     = portrait
fullscreen      = 0
android.api     = 34
android.minapi  = 21
android.archs   = arm64-v8a, armeabi-v7a

android.permissions = INTERNET

[buildozer]
log_level  = 2
warn_on_root = 1

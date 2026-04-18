#!/usr/bin/env python3
"""
미국 주식 대시보드 — Android APK (Kivy)

[PC 테스트]  pip install kivy requests yfinance pandas
             python main.py

[APK 빌드]  WSL2/Linux 에서:
             pip install buildozer cython
             buildozer android debug
"""

import os
os.environ.setdefault("KIVY_NO_ENV_CONFIG", "1")
from kivy.config import Config as _KC
_KC.set("input", "mouse", "mouse,disable_multitouch")

import json, time, threading
from datetime import datetime, timedelta, date as _date

import requests as _req

try:
    import yfinance as _yf
    import pandas as _pd
    _HAS_YF = True
except ImportError:
    _HAS_YF = False

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.clipboard import Clipboard
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle
from kivy.properties import StringProperty, ListProperty, NumericProperty

# ═══════════════════════════════════════════════════════════════════
# 색상 (RGBA 0~1)
# ═══════════════════════════════════════════════════════════════════
C_BG    = [0.051, 0.067, 0.090, 1]
C_PANEL = [0.086, 0.106, 0.133, 1]
C_P2    = [0.110, 0.129, 0.157, 1]
C_BORD  = [0.188, 0.212, 0.239, 1]
C_TEXT  = [0.788, 0.820, 0.851, 1]
C_SUB   = [0.545, 0.580, 0.620, 1]
C_ACC   = [0.345, 0.651, 1.000, 1]
C_GREEN = [0.247, 0.729, 0.314, 1]
C_RED   = [0.973, 0.318, 0.286, 1]
C_GOLD  = [0.824, 0.600, 0.133, 1]

# ═══════════════════════════════════════════════════════════════════
# 포매터
# ═══════════════════════════════════════════════════════════════════
def _fmt_price(v):
    return f"${v:,.2f}" if v else "—"

def _fmt_pct(v):
    if v is None: return "—"
    return f"{'+'if v>=0 else ''}{v:.2f}%"

def _fmt_vol(v):
    if not v: return "—"
    if v >= 1e9: return f"{v/1e9:.2f}B"
    if v >= 1e6: return f"{v/1e6:.1f}M"
    if v >= 1e3: return f"{v/1e3:.0f}K"
    return str(v)

def _fmt_tv(v):
    if not v: return "—"
    if v >= 1e9:  return f"${v/1e9:.2f}B"
    if v >= 1e6:  return f"${v/1e6:.1f}M"
    if v >= 1e3:  return f"${v/1e3:.0f}K"
    return f"${v:,.0f}"

# ═══════════════════════════════════════════════════════════════════
# 데이터 Fetching — Yahoo Finance (실시간)
# ═══════════════════════════════════════════════════════════════════
_sess = _req.Session()
_sess.headers.update({
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://finance.yahoo.com/",
})
_crumb = None

def _init_yahoo():
    global _crumb
    try:
        _sess.get("https://finance.yahoo.com/", timeout=10)
        r = _sess.get(
            "https://query1.finance.yahoo.com/v1/test/getcrumb",
            headers={"Referer": "https://finance.yahoo.com/"},
            timeout=10,
        )
        if r.ok and r.text.strip():
            _crumb = r.text.strip()
    except Exception:
        pass

_SCREENER = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"

def _yval(f, d=0):
    if f is None: return d
    return f.get("raw", d) if isinstance(f, dict) else f

def _fetch_screener(scr_id, count=50):
    global _crumb
    params = {"scrIds": scr_id, "count": count, "formatted": "true",
              "lang": "en-US", "region": "US", "corsDomain": "finance.yahoo.com"}
    if _crumb:
        params["crumb"] = _crumb
    r = _sess.get(_SCREENER, params=params, timeout=15)
    if r.status_code == 401:
        _init_yahoo()
        if _crumb: params["crumb"] = _crumb
        r = _sess.get(_SCREENER, params=params, timeout=15)
    r.raise_for_status()
    return r.json()["finance"]["result"][0]["quotes"]

def _norm(rank, q):
    price  = _yval(q.get("regularMarketPrice"))
    volume = int(_yval(q.get("regularMarketVolume"), 0) or 0)
    return {
        "rank":         rank,
        "ticker":       q.get("symbol", ""),
        "name":         q.get("shortName") or q.get("longName") or q.get("symbol", ""),
        "price":        price,
        "change":       _yval(q.get("regularMarketChange")),
        "changePct":    _yval(q.get("regularMarketChangePercent")),
        "volume":       volume,
        "tradingValue": round(price * volume),
        "mktCap":       int(_yval(q.get("marketCap"), 0) or 0),
    }

_rt_cache: dict = {}
_RT_TTL = 60

def _get_realtime(scr_id):
    now = time.time()
    if scr_id in _rt_cache and now - _rt_cache[scr_id]["ts"] < _RT_TTL:
        return _rt_cache[scr_id]["data"]
    data = [_norm(i+1, q) for i, q in enumerate(_fetch_screener(scr_id, 50))]
    _rt_cache[scr_id] = {"data": data, "ts": now}
    return data

# ═══════════════════════════════════════════════════════════════════
# 데이터 Fetching — Polygon.io (과거 전체)
# ═══════════════════════════════════════════════════════════════════
_POLYGON  = "https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks"
_poly_ses = _req.Session()
_poly_ses.headers.update({"User-Agent": "stock-dashboard/2.0"})

def _prev_biz(d):
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d

def _poly_grouped(date_str, api_key):
    r = _poly_ses.get(
        f"{_POLYGON}/{date_str}",
        params={"adjusted": "true", "include_otc": "false", "apiKey": api_key},
        timeout=20,
    )
    if r.status_code in (401, 403):
        raise PermissionError("Polygon.io API 키 오류 (⚙ 설정 확인)")
    r.raise_for_status()
    data = r.json()
    if data.get("status") in ("ERROR", "NOT_AUTHORIZED"):
        raise PermissionError(data.get("error") or "Polygon 오류")
    return data.get("results") or []

def _find_trade_day(start, api_key, back=7):
    d = start
    for _ in range(back):
        s = d.strftime("%Y-%m-%d")
        res = _poly_grouped(s, api_key)
        if res: return s, res
        d -= timedelta(days=1)
    raise ValueError(f"{start} 주변 거래일 없음")

def _fetch_polygon(date_str, api_key):
    target = datetime.strptime(date_str, "%Y-%m-%d").date()
    if target >= _date.today():
        raise ValueError("과거 날짜만 조회 가능합니다")

    act_str, curr = _find_trade_day(target, api_key)
    act_date      = datetime.strptime(act_str, "%Y-%m-%d").date()
    _, prev       = _find_trade_day(_prev_biz(act_date), api_key)
    prev_c        = {r["T"]: r["c"] for r in prev if r.get("c")}

    all_rows = []
    for r in curr:
        tkr = r.get("T", "")
        cc  = r.get("c", 0)
        pc  = prev_c.get(tkr, 0)
        vol = int(r.get("v", 0) or 0)
        vw  = r.get("vw") or cc or 0
        tv  = round(vw * vol)
        if not tkr or not cc: continue
        pct = (cc - pc) / pc * 100 if pc > 0 else 0
        all_rows.append({
            "ticker": tkr, "price": cc,
            "change": cc - pc if pc else 0,
            "changePct": pct, "volume": vol, "tradingValue": tv,
        })

    def _mk(rank, d):
        return {
            "rank": rank, "ticker": d["ticker"], "name": d["ticker"],
            "price":        round(d["price"], 2),
            "change":       round(d["change"], 2),
            "changePct":    round(d["changePct"], 2),
            "volume":       d["volume"],
            "tradingValue": d["tradingValue"],
            "mktCap":       0,
        }

    valid   = [r for r in all_rows if -80 < r["changePct"] < 500]
    gainers = sorted(valid,    key=lambda x: x["changePct"],    reverse=True)[:50]
    actives = sorted(all_rows, key=lambda x: x["volume"],       reverse=True)[:50]
    values  = sorted(all_rows, key=lambda x: x["tradingValue"], reverse=True)[:50]

    return {
        "gainers":    [_mk(i+1, r) for i, r in enumerate(gainers)],
        "actives":    [_mk(i+1, r) for i, r in enumerate(actives)],
        "values":     [_mk(i+1, r) for i, r in enumerate(values)],
        "actualDate": act_str,
        "source":     f"Polygon.io ({len(curr):,}종목)",
    }

# ═══════════════════════════════════════════════════════════════════
# 데이터 Fetching — yfinance S&P500 (Polygon 키 없을 때)
# ═══════════════════════════════════════════════════════════════════
_SP500 = [
    'AAPL','MSFT','NVDA','GOOGL','AMZN','META','TSLA','BRK-B','JPM','V',
    'XOM','UNH','AVGO','MA','JNJ','HD','PG','LLY','MRK','ABBV',
    'CVX','CRM','BAC','COST','AMD','NFLX','TMO','ACN','ORCL','ADBE',
    'WMT','PEP','MCD','DIS','CSCO','ABT','INTC','IBM','GE','CAT',
    'GS','BA','HON','AMGN','QCOM','LOW','T','VZ','SPGI','NOW',
]
_univ = {"t": None, "ts": 0}

def _get_univ():
    if _univ["t"] and time.time() - _univ["ts"] < 86400:
        return _univ["t"]
    try:
        if _HAS_YF:
            df = _pd.read_html(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            )[0]
            tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        else:
            tickers = _SP500
    except Exception:
        tickers = _SP500
    _univ["t"] = tickers
    _univ["ts"] = time.time()
    return tickers

def _fetch_yf(date_str):
    if not _HAS_YF:
        raise ImportError("yfinance 미설치 — Polygon.io API 키를 사용하세요")
    target  = datetime.strptime(date_str, "%Y-%m-%d").date()
    tickers = _get_univ()
    start   = (target - timedelta(days=10)).strftime("%Y-%m-%d")
    end     = (target + timedelta(days=2)).strftime("%Y-%m-%d")

    raw   = _yf.download(tickers, start=start, end=end,
                         progress=False, auto_adjust=True, threads=True)
    close = raw["Close"].dropna(how="all", axis=1).ffill()
    vol   = raw["Volume"].dropna(how="all", axis=1).ffill()

    dates = [d.date() for d in close.index]
    avail = [d for d in dates if d <= target]
    if not avail: raise ValueError(f"{date_str} 데이터 없음")
    actual = max(avail)
    idx    = dates.index(actual)
    if idx == 0: raise ValueError("이전 거래일 데이터 없음")

    cc  = close.iloc[idx]
    pc  = close.iloc[idx - 1]
    vv  = vol.iloc[idx]
    chg = ((cc - pc) / pc * 100).dropna()
    chg = chg[(chg > -80) & (chg < 500)]

    tvs = (cc * vv).dropna()
    gt  = [str(t) for t in chg.nlargest(50).index]
    at  = [str(t) for t in vv.dropna().nlargest(50).index]
    vt  = [str(t) for t in tvs.nlargest(50).index]

    def _row(rank, tkr):
        try:    p = float(cc[tkr])
        except: p = 0.0
        try:    q = float(pc[tkr])
        except: q = 0.0
        try:    v = int(vv[tkr])
        except: v = 0
        return {
            "rank": rank, "ticker": tkr, "name": tkr,
            "price":        round(p, 2),
            "change":       round(p - q, 2),
            "changePct":    round((p - q) / q * 100 if q else 0, 2),
            "volume":       v,
            "tradingValue": round(p * v),
            "mktCap":       0,
        }

    return {
        "gainers":    [_row(i+1, t) for i, t in enumerate(gt)],
        "actives":    [_row(i+1, t) for i, t in enumerate(at)],
        "values":     [_row(i+1, t) for i, t in enumerate(vt)],
        "actualDate": actual.strftime("%Y-%m-%d"),
        "source":     f"S&P 500 ({len(tickers)}종목)",
    }

_h_lock  = threading.Lock()
_h_cache: dict = {}

def _get_hist(date_str, api_key):
    key = f"{date_str}|{'p' if api_key else 'y'}"
    with _h_lock:
        if key in _h_cache: return _h_cache[key]
        data = _fetch_polygon(date_str, api_key) if api_key else _fetch_yf(date_str)
        _h_cache[key] = data
        return data

# ═══════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════
_cfg      = {}
_cfg_path = None

def cfg_init(user_data_dir):
    global _cfg_path, _cfg
    from pathlib import Path
    _cfg_path = Path(user_data_dir) / "config.json"
    try:
        if _cfg_path.exists():
            _cfg = json.loads(_cfg_path.read_text(encoding="utf-8"))
    except Exception:
        pass

def cfg_get(k, d=""):
    return _cfg.get(k, d)

def cfg_set(k, v):
    _cfg[k] = v
    if _cfg_path:
        try:
            _cfg_path.write_text(json.dumps(_cfg), encoding="utf-8")
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════
# KV 레이아웃
# ═══════════════════════════════════════════════════════════════════
KV = r"""
#:import dp kivy.metrics.dp

<StockRow>:
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(54)
    padding: [dp(8), 0, dp(8), 0]
    spacing: dp(4)
    canvas.before:
        Color:
            rgba: root.bg_color
        Rectangle:
            pos: self.pos
            size: self.size
        Color:
            rgba: [0.188, 0.212, 0.239, 0.6]
        Rectangle:
            pos: [self.x, self.y]
            size: [self.width, dp(1)]

    Label:
        text: root.rank_text
        size_hint: None, 1
        width: dp(36)
        color: root.rank_color
        font_size: dp(12)
        bold: True
        halign: 'center'
        valign: 'middle'
        text_size: self.width, self.height

    BoxLayout:
        orientation: 'vertical'
        size_hint_x: 1
        padding: [0, dp(6), dp(4), dp(6)]
        Label:
            text: root.ticker_text
            color: [0.345, 0.651, 1.0, 1]
            font_size: dp(13)
            bold: True
            halign: 'left'
            valign: 'bottom'
            text_size: self.width, self.height
            size_hint_y: 1
        Label:
            text: root.price_text
            color: [0.545, 0.580, 0.620, 1]
            font_size: dp(10)
            halign: 'left'
            valign: 'top'
            text_size: self.width, self.height
            size_hint_y: 1

    Label:
        text: root.pct_text
        size_hint: None, 1
        width: dp(68)
        color: root.pct_color
        font_size: dp(12)
        bold: True
        halign: 'right'
        valign: 'middle'
        text_size: self.width, self.height

    Label:
        text: root.vol_text
        size_hint: None, 1
        width: dp(64)
        color: [0.788, 0.820, 0.851, 1]
        font_size: dp(11)
        halign: 'right'
        valign: 'middle'
        text_size: self.width, self.height

    Label:
        text: root.tv_text
        size_hint: None, 1
        width: dp(74)
        color: [0.788, 0.820, 0.851, 1]
        font_size: dp(11)
        halign: 'right'
        valign: 'middle'
        text_size: self.width, self.height

<StockList>:
    viewclass: 'StockRow'
    RecycleBoxLayout:
        default_size: None, dp(54)
        default_size_hint: 1, None
        size_hint_y: None
        height: self.minimum_height
        orientation: 'vertical'
"""

Builder.load_string(KV)

# ═══════════════════════════════════════════════════════════════════
# 위젯: StockRow / StockList
# ═══════════════════════════════════════════════════════════════════
class StockRow(RecycleDataViewBehavior, BoxLayout):
    rank_text   = StringProperty('')
    ticker_text = StringProperty('')
    price_text  = StringProperty('')
    pct_text    = StringProperty('')
    vol_text    = StringProperty('')
    tv_text     = StringProperty('')
    rank_color  = ListProperty(list(C_SUB))
    pct_color   = ListProperty(list(C_TEXT))
    bg_color    = ListProperty(list(C_BG))
    index       = NumericProperty(0)

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        return super().refresh_view_attrs(rv, index, data)


class StockList(RecycleView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.data = []

    def load(self, rows: list, top_n: int):
        data = []
        for d in rows[:top_n]:
            rank = d.get("rank", 0)
            rc   = C_GOLD if rank == 1 else (C_TEXT if rank <= 3 else C_SUB)
            pct  = d.get("changePct") or 0
            pc   = C_GREEN if pct >= 0 else C_RED
            bg   = C_P2 if (rank - 1) % 2 == 0 else C_PANEL
            data.append({
                "rank_text":   str(rank),
                "ticker_text": d.get("ticker", ""),
                "price_text":  _fmt_price(d.get("price", 0)),
                "pct_text":    _fmt_pct(pct),
                "vol_text":    _fmt_vol(d.get("volume", 0)),
                "tv_text":     _fmt_tv(d.get("tradingValue", 0)),
                "rank_color":  list(rc),
                "pct_color":   list(pc),
                "bg_color":    list(bg),
            })
        self.data = data

# ═══════════════════════════════════════════════════════════════════
# 헬퍼: 버튼 / 레이블 / 배경
# ═══════════════════════════════════════════════════════════════════
def _btn(text, cb=None, bg=None, fg=None, bold=False, w=None, h=38):
    b = Button(
        text=text, font_size=dp(13), bold=bold,
        background_normal='', background_color=bg or C_P2,
        color=fg or C_SUB,
        size_hint_y=None, height=dp(h),
    )
    if w:
        b.size_hint_x = None
        b.width = dp(w)
    if cb:
        b.bind(on_press=cb)
    return b

def _lbl(text, color=None, size=12, bold=False, halign='left'):
    l = Label(
        text=text, font_size=dp(size), bold=bold,
        color=color or C_SUB, halign=halign, valign='middle',
    )
    l.bind(size=l.setter('text_size'))
    return l

def _bg(widget, color):
    with widget.canvas.before:
        c = Color(*color)
        r = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(pos=lambda *a: setattr(r, 'pos', widget.pos),
                size=lambda *a: setattr(r, 'size', widget.size))

# ═══════════════════════════════════════════════════════════════════
# 설정 팝업
# ═══════════════════════════════════════════════════════════════════
class SettingsPopup(ModalView):
    def __init__(self, on_saved=None, **kwargs):
        super().__init__(size_hint=(0.92, None), height=dp(300),
                         background_color=[0, 0, 0, 0.85], **kwargs)
        self._on_saved = on_saved

        root = BoxLayout(orientation='vertical',
                         padding=dp(18), spacing=dp(10))
        _bg(root, C_PANEL)

        root.add_widget(_lbl('⚙  설정', C_TEXT, 16, bold=True))
        root.add_widget(_lbl('Polygon.io API 키 (과거 전체 미국주식)', C_SUB, 12))

        self._inp = TextInput(
            text=cfg_get('polygon_key', ''),
            hint_text='API 키 입력 (없으면 빈칸 → S&P500 폴백)',
            password=True, multiline=False,
            font_size=dp(12),
            background_color=C_P2,
            foreground_color=C_TEXT,
            cursor_color=C_ACC,
            size_hint_y=None, height=dp(42),
        )
        root.add_widget(self._inp)

        has = bool(cfg_get('polygon_key'))
        self._st = _lbl(
            '✓ API 키 설정됨' if has else '키 없음 (오늘 실시간 데이터만 사용 가능)',
            C_GREEN if has else C_SUB, 11,
        )
        root.add_widget(self._st)
        root.add_widget(Widget(size_hint_y=1))

        row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        row.add_widget(_btn('닫기', lambda *a: self.dismiss()))
        row.add_widget(_btn('저장', self._save, C_ACC, C_BG, bold=True))
        root.add_widget(row)

        self.add_widget(root)

    def _save(self, *a):
        cfg_set('polygon_key', self._inp.text.strip())
        if self._on_saved:
            self._on_saved()
        self.dismiss()

# ═══════════════════════════════════════════════════════════════════
# 메인 화면
# ═══════════════════════════════════════════════════════════════════
class MainScreen(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', **kwargs)
        _bg(self, C_BG)

        self._gainers: list = []
        self._actives: list = []
        self._values:  list = []
        self._tab     = 'gainers'
        self._top_n   = 20
        self._is_today = True
        self._worker: threading.Thread | None = None

        self._build_ui()
        Clock.schedule_once(lambda dt: self._do_refresh(), 0.6)

    # ── UI 구성 ────────────────────────────────────────────────────
    def _build_ui(self):
        self.add_widget(self._make_header())
        self.add_widget(self._make_controls())
        self.add_widget(self._make_tabs())
        self.add_widget(self._make_col_hdr())
        self._list = StockList(size_hint=(1, 1))
        self.add_widget(self._list)
        self.add_widget(self._make_bottom())

    def _make_header(self):
        hdr = BoxLayout(size_hint_y=None, height=dp(52),
                        padding=[dp(12), 0, dp(12), 0], spacing=dp(8))
        _bg(hdr, C_PANEL)

        title = Label(
            text='미국 주식 대시보드',
            font_size=dp(15), bold=True, color=C_ACC,
            size_hint_x=1, halign='left', valign='middle',
        )
        title.bind(size=title.setter('text_size'))
        hdr.add_widget(title)

        self._upd_lbl = Label(
            text='', font_size=dp(10), color=C_SUB,
            size_hint=(None, 1), width=dp(85),
            halign='right', valign='middle',
        )
        self._upd_lbl.bind(size=self._upd_lbl.setter('text_size'))
        hdr.add_widget(self._upd_lbl)

        self._ref_btn = _btn('↻ 새로고침', self._on_refresh,
                             C_ACC, C_BG, bold=True, w=95)
        self._ref_btn.size_hint_y = 1
        self._ref_btn.height = dp(38)
        hdr.add_widget(self._ref_btn)

        hdr.add_widget(_btn('⚙', self._open_settings, w=38))
        return hdr

    def _make_controls(self):
        ctrl = BoxLayout(size_hint_y=None, height=dp(48),
                         padding=[dp(10), dp(5), dp(10), dp(5)], spacing=dp(6))
        _bg(ctrl, C_PANEL)

        self._date_in = TextInput(
            text=(_date.today() - timedelta(days=1)).strftime("%Y-%m-%d"),
            hint_text='YYYY-MM-DD',
            multiline=False, font_size=dp(12),
            background_color=C_P2, foreground_color=C_TEXT,
            cursor_color=C_ACC,
        )
        ctrl.add_widget(self._date_in)

        today_btn = _btn('오늘', self._on_today, w=54)
        today_btn.size_hint_y = 1
        ctrl.add_widget(today_btn)

        ctrl.add_widget(Label(text='Top', color=C_SUB, font_size=dp(12),
                              size_hint=(None, 1), width=dp(28)))

        self._top_sp = Spinner(
            text='20',
            values=[str(n) for n in [5, 10, 15, 20, 25, 30, 40, 50]],
            size_hint=(None, 1), width=dp(62),
            background_normal='', background_color=C_P2,
            color=C_TEXT, font_size=dp(12),
        )
        self._top_sp.bind(text=self._on_top_change)
        ctrl.add_widget(self._top_sp)
        return ctrl

    def _make_tabs(self):
        tabs = BoxLayout(size_hint_y=None, height=dp(42))
        _bg(tabs, C_P2)

        TABS = [('📈 상승률', 'gainers'), ('📊 거래량', 'actives'), ('💰 거래대금', 'values')]
        self._tab_btns = {}
        for label, key in TABS:
            btn = ToggleButton(
                text=label, group='tabs',
                state='down' if key == 'gainers' else 'normal',
                font_size=dp(12), bold=True,
                background_normal='', background_down='',
                background_color=(0, 0, 0, 0),
                color=C_ACC if key == 'gainers' else C_SUB,
            )
            btn._key = key
            btn.bind(state=self._on_tab)
            self._tab_btns[key] = btn
            tabs.add_widget(btn)
        return tabs

    def _make_col_hdr(self):
        hdr = BoxLayout(size_hint_y=None, height=dp(30),
                        padding=[dp(8), 0, dp(8), 0], spacing=dp(4))
        _bg(hdr, C_P2)

        def ch(text, w=None):
            l = Label(text=text, color=C_SUB, font_size=dp(10),
                      bold=True, halign='right', valign='middle')
            if w:
                l.size_hint_x = None
                l.width = dp(w)
            l.bind(size=l.setter('text_size'))
            return l

        hdr.add_widget(ch('#', 36))
        hdr.add_widget(ch('종목'))       # flex
        hdr.add_widget(ch('등락%',   68))
        hdr.add_widget(ch('거래량',  64))
        hdr.add_widget(ch('거래대금', 74))
        return hdr

    def _make_bottom(self):
        bot = BoxLayout(size_hint_y=None, height=dp(48),
                        padding=[dp(10), dp(5), dp(10), dp(5)], spacing=dp(8))
        _bg(bot, C_PANEL)

        self._st_lbl = Label(
            text='준비', color=C_SUB, font_size=dp(11),
            size_hint_x=1, halign='left', valign='middle',
        )
        self._st_lbl.bind(size=self._st_lbl.setter('text_size'))
        bot.add_widget(self._st_lbl)

        copy_btn = _btn('📋 JSON 복사', self._copy_json, C_ACC, C_BG, bold=True, w=110)
        copy_btn.size_hint_y = 1
        bot.add_widget(copy_btn)
        return bot

    # ── 이벤트 ──────────────────────────────────────────────────────
    def _on_tab(self, btn, state):
        if state == 'down':
            self._tab = btn._key
            for k, b in self._tab_btns.items():
                b.color = C_ACC if k == self._tab else C_SUB
            self._refresh_table()

    def _on_top_change(self, sp, text):
        try:
            self._top_n = int(text)
            self._refresh_table()
        except ValueError:
            pass

    def _on_today(self, *a):
        self._is_today = True
        self._do_refresh()

    def _on_refresh(self, *a):
        txt = self._date_in.text.strip()
        try:
            self._is_today = datetime.strptime(txt, "%Y-%m-%d").date() >= _date.today()
        except ValueError:
            self._is_today = True
        self._do_refresh()

    def _open_settings(self, *a):
        SettingsPopup(on_saved=self._do_refresh).open()

    # ── 데이터 로드 ─────────────────────────────────────────────────
    def _do_refresh(self, *a):
        if self._worker and self._worker.is_alive():
            return
        self._ref_btn.disabled = True
        self._ref_btn.text = '로딩 중…'
        self._set_st('데이터 로딩 중…')
        self._list.data = []
        self._worker = threading.Thread(target=self._fetch, daemon=True)
        self._worker.start()

    def _fetch(self):
        date_str  = self._date_in.text.strip()
        today_str = _date.today().strftime("%Y-%m-%d")
        try:
            if self._is_today:
                gainers = _get_realtime("day_gainers")
                actives = _get_realtime("most_actives")
                values  = sorted(actives,
                                 key=lambda x: x.get("tradingValue", 0),
                                 reverse=True)
                values  = [{**r, "rank": i+1} for i, r in enumerate(values)]
                data = {
                    "gainers": gainers, "actives": actives, "values": values,
                    "actualDate": today_str,
                    "source": "Yahoo Finance (실시간)",
                    "isToday": True,
                }
            else:
                api_key = cfg_get("polygon_key")
                data    = _get_hist(date_str, api_key)
                data["isToday"] = False
            self._on_data(data)
        except Exception as e:
            self._on_err(str(e))

    @mainthread
    def _on_data(self, data):
        self._gainers = data.get("gainers", [])
        self._actives = data.get("actives", [])
        self._values  = data.get("values",  [])
        self._refresh_table()
        now = datetime.now().strftime("%H:%M")
        self._upd_lbl.text = f"업데이트 {now}"
        src = data.get("source", "")
        actual = data.get("actualDate", "")
        self._set_st(f"{actual}  ·  {src}")
        self._ref_btn.disabled = False
        self._ref_btn.text = '↻ 새로고침'

    @mainthread
    def _on_err(self, msg):
        self._set_st(f"오류: {msg}")
        self._ref_btn.disabled = False
        self._ref_btn.text = '↻ 새로고침'

    def _refresh_table(self):
        rows = {'gainers': self._gainers,
                'actives': self._actives,
                'values':  self._values}.get(self._tab, [])
        self._list.load(rows, self._top_n)

    @mainthread
    def _set_st(self, msg):
        self._st_lbl.text = msg

    # ── JSON 복사 ────────────────────────────────────────────────────
    def _copy_json(self, *a):
        rows = {'gainers': self._gainers,
                'actives': self._actives,
                'values':  self._values}.get(self._tab, [])
        tab_name = {'gainers': '상승률', 'actives': '거래량',
                    'values': '거래대금'}.get(self._tab, self._tab)
        date_str = (_date.today().strftime("%Y-%m-%d") if self._is_today
                    else self._date_in.text.strip())
        out = {
            "tab":  tab_name,
            "topN": self._top_n,
            "date": date_str,
            "data": rows[:self._top_n],
        }
        Clipboard.copy(json.dumps(out, ensure_ascii=False, indent=2))
        self._set_st(f"✓ JSON 복사 완료 (Top {self._top_n})")

# ═══════════════════════════════════════════════════════════════════
# App 진입점
# ═══════════════════════════════════════════════════════════════════
class StockDashboardApp(App):
    def build(self):
        cfg_init(self.user_data_dir)
        threading.Thread(target=_init_yahoo, daemon=True).start()
        self.title = '미국 주식 대시보드'
        return MainScreen()


if __name__ == '__main__':
    StockDashboardApp().run()

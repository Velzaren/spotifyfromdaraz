# main.py
# main.py
import sys
import os
import json
import typing
import time
import traceback
import pygame
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC
from PyQt5 import QtCore, QtGui, QtWidgets

# --------------------
# Resource helper
# --------------------
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev & for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --------------------
# App constants
# --------------------
APP_TITLE = "Velzaren Music"
# songs folder (bundled or local)
SONGS_DIR = resource_path("songs")
DATA_DIR  = resource_path("data")
# logo placed in assets folder as you said
LOGO_PATH = resource_path(os.path.join("assets", "logo.ico"))
# placeholder art (simple built-in color if no file)
PLACEHOLDER_ART = resource_path(os.path.join("assets", "placeholder_art.png"))

IMPORTED_JSON = os.path.join(DATA_DIR, "imported_songs.json")
CUSTOM_JSON   = os.path.join(DATA_DIR, "custom_playlist.json")
RECENT_JSON   = os.path.join(DATA_DIR, "recent_songs.json")
SEARCHES_JSON = os.path.join(DATA_DIR, "recent_searches.json")

MAX_RECENTS = 5
MAX_RECENT_SEARCHES = 8

# --------------------
# Utilities
# --------------------
def ensure_dirs():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    if not os.path.exists(SONGS_DIR):
        os.makedirs(SONGS_DIR)
    # make sure assets folder exists for packaging (optional)
    assets_dir = resource_path("assets")
    if not os.path.exists(assets_dir):
        try:
            os.makedirs(assets_dir)
        except Exception:
            pass

def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("Save error:", e)

def nice_title(path):
    base = os.path.basename(path)
    name = os.path.splitext(base)[0]
    return name.replace("_", " ").replace("-", " ")

def is_file(path):
    return os.path.isfile(path)

def get_duration(path):
    try:
        audio = MP3(path)
        return float(audio.info.length)
    except Exception:
        return 0.0

def extract_album_art_pixmap(path) -> typing.Optional[QtGui.QPixmap]:
    """
    Try to extract embedded album art from an MP3 ID3 APIC frame.
    Returns QPixmap or None.
    """
    try:
        tags = ID3(path)
        for frame in tags.values():
            if isinstance(frame, APIC):
                data = frame.data
                pix = QtGui.QPixmap()
                if pix.loadFromData(data):
                    return pix
    except Exception:
        pass
    # no art
    return None

# --------------------
# Music backend
# --------------------
class MusicPlayer(QtCore.QObject):
    state_changed = QtCore.pyqtSignal()
    track_changed = QtCore.pyqtSignal(str)
    position_updated = QtCore.pyqtSignal(float, float)  # current_sec, total_sec

    def __init__(self):
        super().__init__()
        # init pygame mixer
        try:
            pygame.mixer.init()
        except Exception as e:
            print("pygame mixer init error:", e)
        self.playlist: typing.List[str] = []
        self.current_index: int = -1
        self.playing: bool = False
        self.volume = 0.85
        try:
            pygame.mixer.music.set_volume(self.volume)
        except Exception:
            pass

        # tracking for position
        self._track_start_time = None
        self._track_offset_seconds = 0.0

        self._timer = QtCore.QTimer()
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        cur = 0.0
        total = 0.0
        path = None
        if self.current_index != -1 and 0 <= self.current_index < len(self.playlist):
            path = self.playlist[self.current_index]
            total = get_duration(path)
        if self.playing and self._track_start_time is not None:
            try:
                ms = pygame.mixer.music.get_pos()
                if ms >= 0:
                    cur = self._track_offset_seconds + (ms / 1000.0)
                else:
                    cur = self._track_offset_seconds + (time.time() - self._track_start_time)
            except Exception:
                cur = self._track_offset_seconds + (time.time() - self._track_start_time)
        else:
            cur = self._track_offset_seconds

        if cur is None: cur = 0.0
        if total is None: total = 0.0

        # emit
        try:
            self.position_updated.emit(float(cur), float(total))
        except Exception:
            pass

        # auto next on end
        if self.playing and not pygame.mixer.music.get_busy():
            if total > 1 and cur >= total - 0.7:
                self.playing = False
                self.state_changed.emit()
                self.next()
            elif total <= 1:
                self.playing = False
                self.state_changed.emit()
                self.next()

    def load_playlist(self, paths: typing.List[str]):
        self.playlist = [p for p in paths if is_file(p)]
        self.current_index = 0 if self.playlist else -1

    def current_track(self):
        if self.current_index == -1:
            return None
        if 0 <= self.current_index < len(self.playlist):
            return self.playlist[self.current_index]
        return None

    def _play_internal(self, path, start_time=0.0):
        try:
            pygame.mixer.music.load(path)
            try:
                pygame.mixer.music.play(loops=0, start=start_time)
            except TypeError:
                pygame.mixer.music.play()
                try:
                    pygame.mixer.music.set_pos(start_time)
                except Exception:
                    pass
            self._track_offset_seconds = start_time
            self._track_start_time = time.time()
            self.playing = True
            self.track_changed.emit(path)
            self.state_changed.emit()
        except Exception as e:
            print("Playback error:", e)
            traceback.print_exc()

    def play_index(self, idx: int):
        if not self.playlist: return
        if idx < 0 or idx >= len(self.playlist): return
        path = self.playlist[idx]
        if not is_file(path): return
        self.current_index = idx
        self._play_internal(path, start_time=0.0)

    def play_path(self, path: str):
        if not is_file(path): return
        if path in self.playlist:
            self.play_index(self.playlist.index(path))
        else:
            self.current_index = -1
            self._play_internal(path, start_time=0.0)

    def toggle(self):
        if self.playing:
            try:
                pygame.mixer.music.pause()
            except Exception:
                pass
            try:
                ms = pygame.mixer.music.get_pos()
                if ms >= 0:
                    self._track_offset_seconds += (ms / 1000.0)
                else:
                    self._track_offset_seconds += (time.time() - self._track_start_time)
            except Exception:
                self._track_offset_seconds += (time.time() - (self._track_start_time or time.time()))
            self.playing = False
            self.state_changed.emit()
        else:
            try:
                pygame.mixer.music.unpause()
                self.playing = True
                self._track_start_time = time.time()
                self.state_changed.emit()
            except Exception:
                if self.playlist:
                    if self.current_index == -1:
                        self.play_index(0)
                    else:
                        self._play_internal(self.playlist[self.current_index], start_time=self._track_offset_seconds)

    def stop(self):
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        self.playing = False
        self._track_start_time = None
        self._track_offset_seconds = 0.0
        self.state_changed.emit()

    def next(self):
        if not self.playlist: return
        self.current_index = 0 if self.current_index == -1 else (self.current_index + 1) % len(self.playlist)
        self.play_index(self.current_index)

    def prev(self):
        if not self.playlist: return
        self.current_index = 0 if self.current_index == -1 else (self.current_index - 1 + len(self.playlist)) % len(self.playlist)
        self.play_index(self.current_index)

    def set_volume(self, vol: float):
        self.volume = max(0.0, min(1.0, vol))
        try:
            pygame.mixer.music.set_volume(self.volume)
        except Exception:
            pass
        self.state_changed.emit()

    def seek(self, seconds: float):
        if self.current_index == -1 or not (0 <= self.current_index < len(self.playlist)):
            return
        path = self.playlist[self.current_index]
        if not is_file(path): return
        total = get_duration(path)
        seconds = max(0.0, min(seconds, total if total > 0 else seconds))
        try:
            pygame.mixer.music.load(path)
            try:
                pygame.mixer.music.play(loops=0, start=seconds)
            except TypeError:
                pygame.mixer.music.play()
                try:
                    pygame.mixer.music.set_pos(seconds)
                except Exception:
                    pass
            self._track_offset_seconds = seconds
            self._track_start_time = time.time()
            self.playing = True
            self.track_changed.emit(path)
            self.state_changed.emit()
        except Exception as e:
            print("Seek error:", e)

# --------------------
# MainWindow UI
# --------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        ensure_dirs()
        self.setWindowTitle(APP_TITLE)
        if os.path.exists(LOGO_PATH):
            try:
                self.setWindowIcon(QtGui.QIcon(LOGO_PATH))
            except Exception:
                pass
        self.resize(1024, 640)

        # Styling
        self.setStyleSheet(self._qss())

        # Data
        self.imported = load_json(IMPORTED_JSON, [])
        self.custom   = load_json(CUSTOM_JSON, [])
        self.recents  = load_json(RECENT_JSON, [])
        self.searches = load_json(SEARCHES_JSON, [])

        self.master_songs: typing.List[dict] = []
        self._refresh_master()

        # Player
        self.player = MusicPlayer()
        self.player.load_playlist([s['path'] for s in self.master_songs])
        self.player.track_changed.connect(self._on_track_changed)
        self.player.position_updated.connect(self._on_position_update)
        self.player.state_changed.connect(self._on_state_changed)

        # UI layout
        self.stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self.stack)

        self.page_home = self._build_home()
        self.page_plist = self._build_playlist_page()
        self.page_search = self._build_search_page()
        self.page_add = QtWidgets.QWidget()

        self.stack.addWidget(self.page_home)
        self.stack.addWidget(self.page_plist)
        self.stack.addWidget(self.page_search)
        self.stack.addWidget(self.page_add)

        self._build_bottom()

        # initial UI refresh
        self._refresh_home_lists()

    # --------------------
    # Build pages
    # --------------------
    def _build_home(self):
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)

        # header with logo and title
        header = QtWidgets.QHBoxLayout()
        if os.path.exists(LOGO_PATH):
            logo_lbl = QtWidgets.QLabel()
            pix = QtGui.QPixmap(LOGO_PATH)
            logo_lbl.setPixmap(pix.scaled(56, 56, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            logo_lbl.setFixedSize(64, 64)
            header.addWidget(logo_lbl)
        title = QtWidgets.QLabel(APP_TITLE)
        title.setObjectName("Title")
        title.setStyleSheet("font-weight:800; font-size:20px; margin-left:8px; color:#2a014b;")
        header.addWidget(title)
        header.addStretch()
        v.addLayout(header)

        # top recents
        v.addWidget(self._section_label("Top 5 Recent"))
        self.recent_list = QtWidgets.QListWidget()
        self.recent_list.setFixedHeight(120)
        self.recent_list.setFlow(QtWidgets.QListView.LeftToRight)
        self.recent_list.itemClicked.connect(self._recent_clicked)
        v.addWidget(self.recent_list)

        # playlists cards
        v.addWidget(self._section_label("Playlists"))
        cards = QtWidgets.QHBoxLayout()
        cards.addWidget(self._playlist_card("My Device Songs", "Imported from device", self._open_device))
        cards.addWidget(self._playlist_card("Custom Playlist", "Your curated picks", self._open_custom))
        cards.addStretch()
        v.addLayout(cards)

        # all songs
        v.addWidget(self._section_label("All Songs"))
        self.home_list = QtWidgets.QListWidget()
        self.home_list.itemDoubleClicked.connect(self._play_from_home)
        self.home_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.home_list.customContextMenuRequested.connect(self._home_menu)
        v.addWidget(self.home_list)

        row = QtWidgets.QHBoxLayout()
        btn_add_to_custom = QtWidgets.QPushButton("Add Selected to Custom")
        btn_add_to_custom.clicked.connect(self._home_add_to_custom)
        row.addWidget(btn_add_to_custom)
        row.addStretch()
        v.addLayout(row)

        return page

    def _build_playlist_page(self):
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(12,12,12,12)
        top = QtWidgets.QHBoxLayout()
        self.pl_title = QtWidgets.QLabel("Playlist")
        top.addWidget(self.pl_title)
        top.addStretch()
        v.addLayout(top)
        self.pl_list = QtWidgets.QListWidget()
        self.pl_list.itemDoubleClicked.connect(self._play_from_plist)
        v.addWidget(self.pl_list)
        return page

    def _build_search_page(self):
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        self.search_inp = QtWidgets.QLineEdit()
        self.search_inp.setPlaceholderText("Search songs…")
        self.search_inp.textChanged.connect(self._on_search_change)
        v.addWidget(self.search_inp)
        v.addWidget(QtWidgets.QLabel("Recent searches"))
        self.search_recent = QtWidgets.QListWidget()
        self.search_recent.setFixedHeight(110)
        self.search_recent.itemClicked.connect(self._search_recent_clicked)
        v.addWidget(self.search_recent)
        v.addWidget(QtWidgets.QLabel("Results"))
        self.search_results = QtWidgets.QListWidget()
        self.search_results.itemDoubleClicked.connect(self._play_from_search)
        self.search_results.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.search_results.customContextMenuRequested.connect(self._search_menu)
        v.addWidget(self.search_results)
        return page

    def _section_label(self, text):
        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet("color:#5b2b88; font-weight:700; margin-top:6px;")
        return lbl

    def _playlist_card(self, title, subtitle, cb):
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        lay = QtWidgets.QVBoxLayout(card)
        t = QtWidgets.QLabel(f"<b>{title}</b>")
        s = QtWidgets.QLabel(subtitle)
        s.setStyleSheet("color:#666;")
        btn = QtWidgets.QPushButton("Open")
        btn.clicked.connect(cb)
        lay.addWidget(t); lay.addWidget(s); lay.addStretch(); lay.addWidget(btn)
        card.setFixedSize(240, 120)
        card.setStyleSheet("QFrame#Card { background: #fff; border-radius:10px; padding:10px; border:1px solid #eee; }")
        return card

    # --------------------
    # Bottom (mini player + nav)
    # --------------------
    def _build_bottom(self):
        container = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(container)
        v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        # player area
        player_area = QtWidgets.QWidget()
        player_area.setObjectName("Mini")
        player_layout = QtWidgets.QHBoxLayout(player_area)
        player_layout.setContentsMargins(12,8,12,8)

        # album art small
        self.art_thumb = QtWidgets.QLabel()
        self.art_thumb.setFixedSize(56,56)
        self.art_thumb.setStyleSheet("border-radius:6px; background:#eee;")
        self.art_thumb.setAlignment(QtCore.Qt.AlignCenter)
        player_layout.addWidget(self.art_thumb)

        # song title and timeline
        col = QtWidgets.QVBoxLayout()
        self.mini_label = QtWidgets.QLabel("Nothing playing")
        self.mini_label.setStyleSheet("font-weight:700; color:#2a014b;")
        self.mini_label.mousePressEvent = self._open_full_player
        col.addWidget(self.mini_label)

        # timeline slider and times
        self.timeline_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.timeline_slider.setRange(0, 1000)
        self.timeline_slider.sliderPressed.connect(self._timeline_pressed)
        self.timeline_slider.sliderReleased.connect(self._timeline_released)
        self.timeline_slider.sliderMoved.connect(self._timeline_moved)
        col.addWidget(self.timeline_slider)
        times_row = QtWidgets.QHBoxLayout()
        self.label_elapsed = QtWidgets.QLabel("0:00")
        self.label_total = QtWidgets.QLabel("0:00")
        times_row.addWidget(self.label_elapsed)
        times_row.addStretch()
        times_row.addWidget(self.label_total)
        col.addLayout(times_row)
        player_layout.addLayout(col, stretch=1)

        # controls
        btns = QtWidgets.QHBoxLayout()
        self.btn_prev = QtWidgets.QPushButton("⏮")
        self.btn_play = QtWidgets.QPushButton("▶️")
        self.btn_next = QtWidgets.QPushButton("⏭")
        for b in (self.btn_prev, self.btn_play, self.btn_next):
            b.setFixedHeight(36); b.setMinimumWidth(48)
        self.btn_prev.clicked.connect(self.player.prev)
        self.btn_play.clicked.connect(self.player.toggle)
        self.btn_next.clicked.connect(self.player.next)
        btns.addWidget(self.btn_prev); btns.addWidget(self.btn_play); btns.addWidget(self.btn_next)
        player_layout.addLayout(btns)

        # volume
        vol_box = QtWidgets.QHBoxLayout()
        self.vol_icon = QtWidgets.QPushButton("🔊")
        self.vol_icon.setFixedSize(36,36)
        self.vol_icon.clicked.connect(self._mute_unmute)
        self.vol_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.vol_slider.setRange(0,100)
        self.vol_slider.setValue(int(self.player.volume*100))
        self.vol_slider.setFixedWidth(120)
        self.vol_slider.valueChanged.connect(self._vol_changed)
        vol_box.addWidget(self.vol_icon)
        vol_box.addWidget(self.vol_slider)
        player_layout.addLayout(vol_box)

        v.addWidget(player_area)

        # nav
        nav = QtWidgets.QWidget()
        nav.setObjectName("Nav")
        nh = QtWidgets.QHBoxLayout(nav)
        nh.setContentsMargins(12,6,12,8)
        self.nav_home = QtWidgets.QPushButton("Home"); self.nav_home.setProperty("class","flat")
        self.nav_search = QtWidgets.QPushButton("Search"); self.nav_search.setProperty("class","flat")
        self.nav_add = QtWidgets.QPushButton("+"); self.nav_add.setProperty("class","flat")
        self.nav_home.clicked.connect(lambda: self._goto(0))
        self.nav_search.clicked.connect(lambda: self._goto(2))
        self.nav_add.clicked.connect(self._popup_add_songs)
        nh.addStretch(); nh.addWidget(self.nav_home); nh.addWidget(self.nav_search); nh.addWidget(self.nav_add); nh.addStretch()
        v.addWidget(nav)

        dock = QtWidgets.QDockWidget()
        dock.setTitleBarWidget(QtWidgets.QWidget())
        dock.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
        dock.setWidget(container)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)

        # timeline state
        self._seeking = False
        self._seek_target = 0.0

    # --------------------
    # Navigation / refresh
    # --------------------
    def _goto(self, idx):
        if idx == 0:
            self._refresh_master()
            self._refresh_home_lists()
        self.stack.setCurrentIndex(idx)

    def _refresh_master(self):
        songs = []
        if os.path.exists(SONGS_DIR):
            for f in sorted(os.listdir(SONGS_DIR)):
                if f.lower().endswith(".mp3"):
                    p = os.path.join(SONGS_DIR, f)
                    songs.append({"title": nice_title(p), "path": p, "source": "bundled"})
        cleaned = [p for p in self.imported if is_file(p)]
        if len(cleaned) != len(self.imported):
            self.imported = cleaned
            save_json(IMPORTED_JSON, self.imported)
        for p in self.imported:
            songs.append({"title": nice_title(p), "path": p, "source": "imported"})
        seen = set(); uniq = []
        for s in songs:
            if s["path"] not in seen:
                uniq.append(s); seen.add(s["path"])
        self.master_songs = uniq
        if hasattr(self, "player"):
            self.player.load_playlist([s['path'] for s in self.master_songs])

    def _refresh_home_lists(self):
        self.home_list.clear()
        self.home_list.addItems([s["title"] for s in self.master_songs])
        self.recent_list.clear()
        for p in reversed(self.recents[-MAX_RECENTS:]):
            if is_file(p):
                it = QtWidgets.QListWidgetItem(nice_title(p))
                it.setData(QtCore.Qt.UserRole, p)
                self.recent_list.addItem(it)

    def _refresh_recent_searches(self):
        self.search_recent.clear()
        for q in reversed(self.searches[-MAX_RECENT_SEARCHES:]):
            self.search_recent.addItem(q)

    # --------------------
    # Home actions & lists
    # --------------------
    def _home_menu(self, pos):
        item = self.home_list.itemAt(pos)
        if not item: return
        menu = QtWidgets.QMenu(self)
        add = menu.addAction("Add to Custom Playlist")
        action = menu.exec_(self.home_list.mapToGlobal(pos))
        if action == add:
            idx = self.home_list.row(item)
            path = self.master_songs[idx]["path"]
            self._add_to_custom(path)

    def _home_add_to_custom(self):
        item = self.home_list.currentItem()
        if not item: return
        idx = self.home_list.currentRow()
        path = self.master_songs[idx]["path"]
        self._add_to_custom(path)

    def _recent_clicked(self, item):
        path = item.data(QtCore.Qt.UserRole)
        self._play_path(path)

    def _play_from_home(self, item):
        idx = self.home_list.row(item)
        path = self.master_songs[idx]["path"]
        self._play_path(path)

    # --------------------
    # Playlists
    # --------------------
    def _open_device(self):
        self.pl_title.setText("My Device Songs")
        self.pl_list.clear()
        for p in self.imported:
            if is_file(p):
                self.pl_list.addItem(nice_title(p))
        self.stack.setCurrentIndex(1)

    def _open_custom(self):
        self.pl_title.setText("Custom Playlist")
        self.pl_list.clear()
        for p in self.custom:
            if is_file(p):
                self.pl_list.addItem(nice_title(p))
        self.stack.setCurrentIndex(1)

    # --------------------
    # Search
    # --------------------
    def _on_search_change(self, text):
        q = text.strip().lower()
        self.search_results.clear()
        if not q:
            return
        matches = [s for s in self.master_songs if q in s["title"].lower()]
        if not matches:
            self.search_results.addItem("No songs found.")
            return
        for s in matches:
            it = QtWidgets.QListWidgetItem(s["title"])
            it.setData(QtCore.Qt.UserRole, s["path"])
            self.search_results.addItem(it)
        if q:
            if q in self.searches: self.searches.remove(q)
            self.searches.append(q)
            self.searches = self.searches[-MAX_RECENT_SEARCHES:]
            save_json(SEARCHES_JSON, self.searches)
            self._refresh_recent_searches()

    def _search_recent_clicked(self, item):
        self.search_inp.setText(item.text())

    def _search_menu(self, pos):
        item = self.search_results.itemAt(pos)
        if not item: return
        path = item.data(QtCore.Qt.UserRole)
        if not path: return
        menu = QtWidgets.QMenu(self)
        add = menu.addAction("Add to Custom Playlist")
        action = menu.exec_(self.search_results.mapToGlobal(pos))
        if action == add:
            self._add_to_custom(path)

    def _play_from_search(self, item):
        path = item.data(QtCore.Qt.UserRole)
        if path:
            self._play_path(path)

    def _play_from_plist(self,item):
        idx=self.pl_list.row(item)
        #figure out playlist
        if self.pl_title.text()=="My Device Songs":
            songs=[p for p in self.imported if is_file(p)]
        elif self.pl_title.text()=="Custom Playlist":
            songs=[p for p in self.custom if is_file(p)]
        else:
            songs=[]

        if 0<=idx <len(songs):
            self.current_playlist=songs
            self.current_index=idx

            path= songs[idx]
            self._play_path(path)

    # --------------------
    # Add / Import (popup)
    # --------------------
    def _popup_add_songs(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Select MP3 files to import", QtCore.QDir.homePath(), "Audio Files (*.mp3)")
        if not files: return
        added = 0
        for f in files:
            if f not in self.imported:
                self.imported.append(f)
                added += 1
        if added:
            save_json(IMPORTED_JSON, self.imported)
            self._refresh_master()
            self._refresh_home_lists()
            QtWidgets.QMessageBox.information(self, "Imported", f"Added {added} song(s).")
        else:
            QtWidgets.QMessageBox.information(self, "No new songs", "No new songs were added.")

    # --------------------
    # Playback helpers
    # --------------------
    def _play_path(self, path: str):
        if not is_file(path):
            QtWidgets.QMessageBox.warning(self, "Missing file", "This song file was not found.")
            if path in self.imported:
                self.imported.remove(path); save_json(IMPORTED_JSON, self.imported)
            if path in self.custom:
                self.custom.remove(path); save_json(CUSTOM_JSON, self.custom)
            self._refresh_master(); self._refresh_home_lists()
            return

        if path in self.recents: self.recents.remove(path)
        self.recents.append(path)
        self.recents = self.recents[-MAX_RECENTS:]
        save_json(RECENT_JSON, self.recents)
        self._refresh_home_lists()

        if path not in self.player.playlist:
            newlist = [path] + [s["path"] for s in self.master_songs if s["path"] != path]
            self.player.load_playlist(newlist)
            self.player.play_index(0)
        else:
            self.player.play_path(path)
        self._update_mini_label(path)

    def _add_to_custom(self, path: str):
        if not is_file(path):
            QtWidgets.QMessageBox.warning(self, "Missing file", "This song file was not found.")
            return
        if path in self.custom:
            QtWidgets.QMessageBox.information(self, "Info", "Already in Custom Playlist.")
            return
        self.custom.append(path)
        save_json(CUSTOM_JSON, self.custom)
        QtWidgets.QMessageBox.information(self, "Added", f"Added “{nice_title(path)}” to Custom Playlist.")

    # --------------------
    # Player callbacks
    # --------------------
    def _on_track_changed(self, path):
        if is_file(path):
            self.mini_label.setText(nice_title(path))
            total = get_duration(path)
            self.label_total.setText(self._format_time(total))
            self.timeline_slider.setValue(0)
            # album art
            pix = extract_album_art_pixmap(path)
            if pix:
                self.art_thumb.setPixmap(pix.scaled(56,56, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            else:
                # placeholder color if no image exists
                if os.path.exists(PLACEHOLDER_ART):
                    p = QtGui.QPixmap(PLACEHOLDER_ART)
                    self.art_thumb.setPixmap(p.scaled(56,56, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
                else:
                    self.art_thumb.setStyleSheet("background:#e8e0f8; border-radius:6px;")

    def _on_state_changed(self):
        self.btn_play.setText("⏸" if self.player.playing else "▶️")

    def _on_position_update(self, cur, total):
        if not self._seeking:
            if total > 0:
                pos = int((cur / total) * 1000)
                self.timeline_slider.setValue(pos)
            else:
                self.timeline_slider.setValue(0)
            self.label_elapsed.setText(self._format_time(cur))
            if total > 0:
                self.label_total.setText(self._format_time(total))

    # --------------------
    # Timeline interaction
    # --------------------
    def _timeline_pressed(self):
        self._seeking = True

    def _timeline_moved(self, value):
        try:
            path = self.player.current_track()
            total = get_duration(path) if path else 0.0
            sec = (value / 1000.0) * total if total > 0 else 0.0
            self.label_elapsed.setText(self._format_time(sec))
            self._seek_target = sec
        except Exception:
            pass

    def _timeline_released(self):
        self._seeking = False
        try:
            path = self.player.current_track()
            if path and is_file(path):
                total = get_duration(path)
                seconds = self._seek_target if self._seek_target > 0 else 0.0
                seconds = max(0.0, min(seconds, total))
                self.player.seek(seconds)
        except Exception:
            pass

    # --------------------
    # Volume
    # --------------------
    def _vol_changed(self, val):
        vol = val / 100.0
        self.player.set_volume(vol)

    def _mute_unmute(self):
        if self.player.volume > 0:
            self._last_vol = self.player.volume
            self.vol_slider.setValue(0)
            self.player.set_volume(0.0)
        else:
            vol = getattr(self, "_last_vol", 0.85)
            self.vol_slider.setValue(int(vol*100))
            self.player.set_volume(vol)

    # --------------------
    # Misc
    # --------------------
    def _update_mini_label(self, path):
        self.mini_label.setText(nice_title(path))

    def _open_full_player(self, event):
        cur = self.player.current_track()
        path = cur if cur and is_file(cur) else (self.recents[-1] if self.recents else None)
        if not path or not is_file(path):
            QtWidgets.QMessageBox.information(self, "No track", "Nothing to show.")
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Now Playing")
        dlg.resize(520, 520)
        v = QtWidgets.QVBoxLayout(dlg)
        pix = extract_album_art_pixmap(path)
        art = QtWidgets.QLabel()
        art.setFixedSize(320,320)
        if pix:
            art.setPixmap(pix.scaled(320,320, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        else:
            if os.path.exists(PLACEHOLDER_ART):
                p = QtGui.QPixmap(PLACEHOLDER_ART)
                art.setPixmap(p.scaled(320,320, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            else:
                art.setStyleSheet("background:#e8e0f8;")
                art.setText("Album Art")
                art.setAlignment(QtCore.Qt.AlignCenter)
        v.addWidget(art, alignment=QtCore.Qt.AlignHCenter)
        t = QtWidgets.QLabel(f"<b>{nice_title(path)}</b>")
        t.setAlignment(QtCore.Qt.AlignCenter)
        v.addWidget(t)
        row = QtWidgets.QHBoxLayout()
        bprev = QtWidgets.QPushButton("⏮"); bplay = QtWidgets.QPushButton("⏯"); bnext = QtWidgets.QPushButton("⏭")
        bprev.clicked.connect(self.player.prev); bplay.clicked.connect(self.player.toggle); bnext.clicked.connect(self.player.next)
        for b in (bprev,bplay,bnext): b.setMinimumWidth(54)
        row.addStretch(); row.addWidget(bprev); row.addWidget(bplay); row.addWidget(bnext); row.addStretch()
        v.addLayout(row)
        dlg.exec_()

    def _format_time(self, seconds: float):
        try:
            s = int(seconds)
            m = s // 60
            s = s % 60
            return f"{m}:{s:02d}"
        except Exception:
            return "0:00"

    # --------------------
    # QSS style
    # --------------------
    def _qss(self):
        return """
        QWidget { font-family: 'Segoe UI', Roboto, Arial; color: #2b2b2b; background: #ffffff; }
        QMainWindow { background: #ffffff; }
        QLabel#Title { font-size: 20px; font-weight:800; color:#2a014b; }
        QPushButton { background:#5b2b88; color:#fff; border-radius:8px; padding:6px 10px; font-weight:700; }
        QPushButton:hover { background:#6f3aa3; }
        QPushButton.flat { background:transparent; color:#2a014b; border:none; padding:6px 8px; }
        QListWidget { background:#fff; border-radius:8px; padding:6px; color:#222; border:1px solid #eee; }
        QLineEdit { background:#fafafa; border-radius:10px; padding:8px; color:#222; border:1px solid #eee; }
        QWidget#Mini { background:#faf7ff; border-top:1px solid #efe8ff; }
        QWidget#Nav { background:#fff; border-top:1px solid #f0edf8; }
        QSlider::groove:horizontal { height:6px; border-radius:4px; background:#f0ecf6; }
        QSlider::handle:horizontal { width:12px; background:#5b2b88; border-radius:6px; margin:-4px 0; }
        """

# --------------------
# App entry (safe splash)
# --------------------
def main():
    # attributes BEFORE creating QApplication
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

    app = QtWidgets.QApplication(sys.argv)
    ensure_dirs()

    # splash pixmap (use logo if available, else fallback)
    if os.path.exists(LOGO_PATH):
        pix = QtGui.QPixmap(LOGO_PATH).scaled(300, 300, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        splash_pix = QtGui.QPixmap(480, 320)
        splash_pix.fill(QtGui.QColor("#ffffff"))
        painter = QtGui.QPainter(splash_pix)
        # draw background accent
        grad = QtGui.QLinearGradient(0, 0, splash_pix.width(), splash_pix.height())
        grad.setColorAt(0.0, QtGui.QColor("#ffffff"))
        grad.setColorAt(1.0, QtGui.QColor("#f6f0ff"))
        painter.fillRect(splash_pix.rect(), grad)
        # draw logo centered
        x = (splash_pix.width() - pix.width()) // 2
        painter.drawPixmap(x, 30, pix)
        # draw title
        pen = QtGui.QPen(QtGui.QColor("#2a014b"))
        painter.setPen(pen)
        font = QtGui.QFont("Segoe UI", 18, QtGui.QFont.Bold)
        painter.setFont(font)
        painter.drawText(splash_pix.rect().adjusted(0, 200, 0, -20), QtCore.Qt.AlignHCenter, APP_TITLE)
        painter.end()
    else:
        splash_pix = QtGui.QPixmap(480, 320)
        splash_pix.fill(QtGui.QColor("#ffffff"))

    splash = QtWidgets.QSplashScreen(splash_pix)
    splash.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()

    # create main window
    window = MainWindow()

    # delay slightly to ensure splash painted, then show main and finish splash
    def finish_and_show():
        window.show()
        splash.finish(window)

    QtCore.QTimer.singleShot(700, finish_and_show)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

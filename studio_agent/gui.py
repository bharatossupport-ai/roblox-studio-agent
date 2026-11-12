"""Studio Agent desktop app (PySide6)."""
from __future__ import annotations

import datetime
import html
import os
import sys
import traceback

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QDesktopServices, QFont, QTextCursor
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QTextBrowser, QVBoxLayout, QWidget, QFileDialog,
)

from . import config
from .agent import QUICK_ACTIONS, Agent
from .llm import ChatClient, FreePoolClient
from .mcp_client import StudioMCP
from .providers import PROVIDERS, get_provider

APP_NAME = "Studio Agent"
VERSION = "1.0.0"

STYLE = """
QWidget { background:#0f1117; color:#e6e8ef; font-family:'Segoe UI'; font-size:10.5pt; }
QFrame#side { background:#151824; border-right:1px solid #232838; }
QFrame#side QLabel { background:transparent; }
QPushButton { background:#232838; border:1px solid #2e3448; border-radius:8px; padding:8px 12px; }
QPushButton:hover { background:#2c3246; }
QPushButton:checked { background:#3b5bfd; border-color:#3b5bfd; color:white; }
QPushButton#primary { background:#3b5bfd; border:none; color:white; font-weight:600; }
QPushButton#primary:hover { background:#5470ff; }
QPushButton#danger { background:#3a1f26; border-color:#5b2a35; }
QPushButton:disabled { color:#666; }
QPlainTextEdit, QLineEdit, QComboBox, QSpinBox { background:#151824; border:1px solid #2e3448; border-radius:8px; padding:6px; }
QTextBrowser { background:#0f1117; border:none; }
QLabel#title { font-size:15pt; font-weight:700; }
QLabel#muted { color:#8a90a6; }
"""

TEMPLATES = {
    "game": [
        ("Obby", "A 30-stage colorful obby with checkpoints, a stage counter, kill bricks, moving platforms and a skip-stage button."),
        ("Tycoon", "A dropper tycoon: claimable plots, droppers, conveyor, collector, buy buttons that unlock upgrades, cash leaderstats and data saving."),
        ("Simulator", "A clicking simulator: click to earn strength, sell area, pets that boost earnings, rebirths, shop UI and data saving."),
        ("Tower Defense", "A tower defense map with an enemy path, waves, 3 tower types with upgrades, cash per kill, base health and wave UI."),
        ("Horror", "A short horror escape: dark house map, flashlight, collectible keys, a chasing monster NPC with pathfinding and jump-scare UI."),
        ("Battle Arena", "A round-based sword fighting arena: lobby, intermission timer, teleport to arena, last player standing wins, kills leaderboard."),
    ],
    "ui": [
        ("Shop", "A cartoon-style shop UI with tabs (Items, Pets, Gamepasses), a grid of item cards with price buttons, coin display and close button."),
        ("Main menu", "A main menu with game title, Play, Settings and Credits buttons, animated background gradient and smooth transitions."),
        ("HUD", "A HUD with health bar, coins and gems counters, level/XP bar, and mobile-friendly sprint and inventory buttons."),
        ("Inventory", "An inventory UI with a scrolling grid of slots, item details panel, equip/unequip buttons and rarity colors."),
        ("Settings", "A settings panel with toggles for music, SFX, shadows, and a slider for camera sensitivity."),
        ("Daily reward", "A daily reward popup with 7 day cards, claimed/locked states, and a big Claim button with a bounce animation."),
    ],
}


# ----------------------------------------------------------------------------- worker
class Worker(QObject):
    event = Signal(str, str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    @Slot()
    def run(self):
        try:
            self.done.emit(self.fn(lambda k, t: self.event.emit(k, t)) or "")
        except Exception as e:
            traceback.print_exc()
            self.failed.emit(str(e))


# ----------------------------------------------------------------------------- settings
class SettingsDialog(QDialog):
    def __init__(self, parent, cfg: dict):
        super().__init__(parent)
        self.setWindowTitle("AI settings")
        self.setMinimumWidth(520)
        self.cfg = cfg
        lay = QFormLayout(self)

        self.provider = QComboBox()
        for p in PROVIDERS:
            self.provider.addItem(p.name, p.id)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.base_url = QLineEdit()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        self.get_key = QPushButton("Get a key")
        self.get_key.clicked.connect(self._open_key_page)
        self.custom = QPlainTextEdit(cfg.get("custom_prompt", ""))
        self.custom.setPlaceholderText("Optional: your own rules, e.g. 'Use a neon sci-fi style. Comment all scripts.'")
        self.custom.setFixedHeight(90)
        self.steps = QSpinBox()
        self.steps.setRange(5, 200)
        self.steps.setValue(int(cfg.get("max_steps", 40)))

        lay.addRow("AI provider", self.provider)
        lay.addRow("", self.note)
        lay.addRow("Model", self.model)
        lay.addRow("Base URL", self.base_url)
        krow = QHBoxLayout()
        krow.addWidget(self.key)
        krow.addWidget(self.get_key)
        lay.addRow("API key", krow)
        lay.addRow("Max steps per request", self.steps)
        lay.addRow("Custom instructions", self.custom)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

        self.provider.currentIndexChanged.connect(self._load_provider)
        idx = max(0, self.provider.findData(cfg.get("provider", "free")))
        self.provider.setCurrentIndex(idx)
        self._load_provider()

    def _pid(self) -> str:
        return self.provider.currentData()

    def _load_provider(self):
        p = get_provider(self._pid())
        self.model.clear()
        self.model.addItems(p.models or ([p.default_model] if p.default_model else []))
        self.model.setCurrentText(self.cfg.get("models", {}).get(p.id, p.default_model))
        self.base_url.setText(self.cfg.get("base_urls", {}).get(p.id, p.base_url))
        self.base_url.setEnabled(p.id in ("custom", "ollama"))
        self.key.setText(config.get_key(p.id))
        self.key.setEnabled(p.needs_key)
        self.key.setPlaceholderText("Not needed" if not p.needs_key else "Paste your API key")
        self.get_key.setVisible(bool(p.key_url))
        self.get_key.setText("Download Ollama" if p.local else "Get a key")
        self.note.setText(p.note)

    def _open_key_page(self):
        p = get_provider(self._pid())
        if p.key_url:
            QDesktopServices.openUrl(QUrl(p.key_url))

    def apply(self):
        pid = self._pid()
        self.cfg["provider"] = pid
        self.cfg.setdefault("models", {})[pid] = self.model.currentText().strip()
        self.cfg.setdefault("base_urls", {})[pid] = self.base_url.text().strip()
        self.cfg["custom_prompt"] = self.custom.toPlainText()
        self.cfg["max_steps"] = self.steps.value()
        if get_provider(pid).needs_key:
            config.set_key(pid, self.key.text().strip())
        config.save(self.cfg)


# ----------------------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — AI for Roblox Studio")
        self.resize(1180, 760)
        self.cfg = config.load()
        self.studio = StudioMCP()
        self.agent: Agent | None = None
        self.thread: QThread | None = None
        self.worker: Worker | None = None
        self._last_plan = ""
        self.pending_idea = ""
        self.game_built = False
        self.mode = "chat"
        self._build_ui()
        self._refresh_provider_label()
        self._say("system", "Open a place in Roblox Studio, turn on <b>Assistant › … › Manage MCP Servers › Enable Studio as MCP server</b>, then press <b>Connect</b>.")
        QTimer.singleShot(400, self.connect_studio)

    # --------------------------------------------------------------- layout
    def _build_ui(self):
        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(250)
        sv = QVBoxLayout(side)
        t = QLabel(APP_NAME)
        t.setObjectName("title")
        sv.addWidget(t)
        sub = QLabel(f"v{VERSION} · AI agent for Roblox Studio")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        sv.addWidget(sub)
        sv.addSpacing(12)

        self.mode_group = QButtonGroup(self)
        for mid, label in (("chat", "💬  Chat / Script"), ("game", "🎮  Game Builder"), ("ui", "🎨  UI Builder")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setProperty("mode", mid)
            b.setStyleSheet("text-align:left;")
            self.mode_group.addButton(b)
            sv.addWidget(b)
            if mid == "chat":
                b.setChecked(True)
        self.mode_group.buttonClicked.connect(lambda b: self.set_mode(b.property("mode")))

        sv.addSpacing(10)
        self.tpl_label = QLabel("Quick start")
        self.tpl_label.setObjectName("muted")
        sv.addWidget(self.tpl_label)
        self.tpl_box = QVBoxLayout()
        sv.addLayout(self.tpl_box)
        sv.addStretch(1)

        self.status = QLabel("● Studio: not connected")
        self.status.setObjectName("muted")
        sv.addWidget(self.status)
        cb = QPushButton("Connect to Studio")
        cb.clicked.connect(self.connect_studio)
        sv.addWidget(cb)
        self.provider_label = QLabel()
        self.provider_label.setObjectName("muted")
        self.provider_label.setWordWrap(True)
        sv.addWidget(self.provider_label)
        sb = QPushButton("⚙  AI settings")
        sb.clicked.connect(self.open_settings)
        sv.addWidget(sb)
        h.addWidget(side)

        main = QWidget()
        mv = QVBoxLayout(main)
        mv.setContentsMargins(16, 12, 16, 12)
        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(True)
        mv.addWidget(self.chat, 1)

        self.plan_bar = QWidget()
        pb = QHBoxLayout(self.plan_bar)
        pb.setContentsMargins(0, 0, 0, 0)
        pb.addWidget(QLabel("Happy with the plan?"))
        pb.addStretch(1)
        self.build_btn = QPushButton("🚀  Build this game")
        self.build_btn.setObjectName("primary")
        self.build_btn.clicked.connect(self.build_plan)
        pb.addWidget(self.build_btn)
        self.plan_bar.hide()
        mv.addWidget(self.plan_bar)

        qa = QHBoxLayout()
        for key, label in (("fix", "🩹 Fix errors"), ("test", "▶ Playtest check"), ("explain", "📖 Explain place"),
                           ("optimize", "⚡ Optimize"), ("review", "🔍 Code review"), ("comment", "📝 Add comments")):
            b = QPushButton(label)
            b.setStyleSheet("padding:5px 9px;font-size:9.5pt;")
            b.clicked.connect(lambda _=False, k=key, l=label: self.quick(k, l))
            qa.addWidget(b)
        ub = QPushButton("↶ Undo")
        ub.setToolTip("Undo the last change in Studio")
        ub.setStyleSheet("padding:5px 9px;font-size:9.5pt;")
        ub.clicked.connect(self.undo)
        qa.addWidget(ub)
        qa.addStretch(1)
        mv.addLayout(qa)

        self.attach_label = QLabel("")
        self.attach_label.setObjectName("muted")
        self.attach_label.hide()
        mv.addWidget(self.attach_label)
        self.attachments: list[str] = []

        self.input = QPlainTextEdit()
        self.input.setFixedHeight(90)
        self.input.installEventFilter(self)
        mv.addWidget(self.input)
        row = QHBoxLayout()
        self.new_btn = QPushButton("New chat")
        self.new_btn.clicked.connect(self.new_chat)
        row.addWidget(self.new_btn)
        hb = QPushButton("🗂 History")
        hb.clicked.connect(self.open_history)
        row.addWidget(hb)
        ab = QPushButton("📎 Image")
        ab.setToolTip("Attach a reference picture (UI mockup, map sketch). Needs a vision model like Gemini or OpenAI.")
        ab.clicked.connect(self.attach)
        row.addWidget(ab)
        eb = QPushButton("✨ Enhance")
        eb.setToolTip("Turn a short idea into a detailed build request")
        eb.clicked.connect(self.enhance)
        row.addWidget(eb)
        row.addStretch(1)
        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        row.addWidget(self.stop_btn)
        self.send_btn = QPushButton("Send  ➤")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self.send)
        row.addWidget(self.send_btn)
        mv.addLayout(row)
        h.addWidget(main, 1)
        self.setCentralWidget(root)
        self.set_mode("chat")

    def eventFilter(self, obj, ev):
        if obj is self.input and ev.type() == ev.Type.KeyPress:
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and not (ev.modifiers() & Qt.ShiftModifier):
                self.send()
                return True
        return super().eventFilter(obj, ev)

    # --------------------------------------------------------------- chat rendering
    def _say(self, who: str, body_html: str):
        colors = {"you": "#3b5bfd", "ai": "#1c2030", "system": "#151824", "tool": "#111521", "error": "#3a1f26", "plan": "#16241c"}
        names = {"you": "You", "ai": "Agent", "system": "Studio Agent", "tool": "", "error": "Error", "plan": "Game plan"}
        if who == "tool":
            block = f"<div style='margin:2px 0 2px 12px;color:#8a90a6;font-family:Consolas;font-size:9pt'>{body_html}</div>"
        else:
            block = (
                f"<table width='100%' cellpadding='10' style='margin:6px 0'><tr><td style='background:{colors[who]};border-radius:10px'>"
                f"<b>{names[who]}</b><br>{body_html}</td></tr></table>"
            )
        self.chat.append(block)
        self.chat.moveCursor(QTextCursor.End)

    @staticmethod
    def _md(text: str) -> str:
        # light markdown: code fences, bold, line breaks
        out, in_code = [], False
        for line in text.split("\n"):
            if line.strip().startswith("```"):
                out.append("<pre style='background:#0b0d13;padding:8px'>" if not in_code else "</pre>")
                in_code = not in_code
                continue
            esc = html.escape(line)
            if not in_code:
                parts = esc.split("**")
                esc = "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(parts))
                if esc.startswith("#"):
                    esc = f"<b>{esc.lstrip('#').strip()}</b>"
            out.append(esc + ("" if in_code else "<br>"))
        if in_code:
            out.append("</pre>")
        return "\n".join(out)

    # --------------------------------------------------------------- modes
    def set_mode(self, mode: str):
        self.mode = mode
        for b in self.mode_group.buttons():
            b.setChecked(b.property("mode") == mode)
        hints = {
            "chat": "Ask anything: 'Add a double jump', 'Fix the errors in my shop script', 'Make a day/night cycle'…",
            "game": "Describe the game you want. I'll write a plan first, then build the whole thing in Studio.",
            "ui": "Describe the interface: style, colors, screens. Every button will actually work.",
        }
        self.input.setPlaceholderText(hints[mode] + "   (Enter to send, Shift+Enter for a new line)")
        while self.tpl_box.count():
            w = self.tpl_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        tpls = TEMPLATES.get(mode, [])
        self.tpl_label.setVisible(bool(tpls))
        for name, prompt in tpls:
            b = QPushButton(name)
            b.setStyleSheet("text-align:left;padding:6px 10px;")
            b.clicked.connect(lambda _=False, p=prompt: self.input.setPlainText(p))
            self.tpl_box.addWidget(b)
        if self.agent:
            self.agent.set_mode(mode)
        self.plan_bar.hide()
        self._last_plan = ""
        self.game_built = False

    # --------------------------------------------------------------- studio
    def connect_studio(self):
        if self.thread:
            return
        self.status.setText("● Studio: connecting…")

        def job(emit):
            self.studio.stop()
            self.studio.start()
            self.studio.bind()
            tools = self.studio.list_tools(refresh=True)
            return f"{self.studio.studio_name}|{len(tools)}"

        self._run(job, self._connected, busy_send=False)

    def _connected(self, res: str):
        name, n = res.split("|", 1)
        self.status.setText(f"<span style='color:#3ddc84'>●</span> Studio: {html.escape(name)} ({n} tools)")
        self._say("system", f"Connected to <b>{html.escape(name)}</b>. Ready to build.")
        self.agent = None  # rebuilt with the fresh tool list

    # --------------------------------------------------------------- AI
    def _refresh_provider_label(self):
        p = get_provider(self.cfg.get("provider", "free"))
        model = self.cfg.get("models", {}).get(p.id, p.default_model)
        self.provider_label.setText(f"AI: {p.name}<br>Model: {html.escape(model or '-')}")

    def open_settings(self):
        d = SettingsDialog(self, self.cfg)
        if d.exec():
            d.apply()
            self.cfg = config.load()
            self.agent = None
            self._refresh_provider_label()
            self._say("system", "AI settings saved. A new conversation starts with the next message.")

    def _make_agent(self) -> Agent:
        p = get_provider(self.cfg.get("provider", "free"))
        base = self.cfg.get("base_urls", {}).get(p.id) or p.base_url
        model = self.cfg.get("models", {}).get(p.id) or p.default_model
        key = config.get_key(p.id) if p.needs_key else ""
        if p.needs_key and not key:
            raise RuntimeError(f"{p.name} needs an API key. Open AI settings to add one, or switch to Free Cloud AI.")
        llm = FreePoolClient() if p.id == "free" else ChatClient(base, key, model)
        a = Agent(llm, self.studio, self.cfg.get("custom_prompt", ""), int(self.cfg.get("max_steps", 40)), vision=p.vision)
        a.set_mode(self.mode)
        return a

    def _ensure_ready(self) -> bool:
        if not self.studio.studio_id:
            QMessageBox.information(self, APP_NAME, "Connect to Roblox Studio first (open a place and enable its MCP server).")
            return False
        if self.agent is None:
            try:
                self.agent = self._make_agent()
            except Exception as e:
                self._say("error", html.escape(str(e)))
                return False
        return True

    def send(self):
        text = self.input.toPlainText().strip()
        if not text or self.thread:
            return
        if not self._ensure_ready():
            return
        self.input.clear()
        self._say("you", html.escape(text).replace("\n", "<br>"))
        agent = self.agent
        if self.mode == "game" and not self.game_built:
            if self.plan_bar.isVisible() and self._last_plan:
                idea = f"{self.pending_idea}\n\nPrevious plan:\n{self._last_plan}\n\nChanges the user wants: {text}"
            else:
                idea = text
            self.pending_idea = idea
            self.plan_bar.hide()
            self._say("system", "Planning your game…")
            self._run(lambda emit: agent.plan_game(idea), self._show_plan)
            return
        imgs, self.attachments = self.attachments, []
        self.attach_label.hide()
        self._run(lambda emit: agent.run(text, emit, images=imgs), self._finished)

    def _show_plan(self, plan: str):
        self._last_plan = plan
        self._say("plan", self._md(plan))
        self._say("system", "Press <b>Build this game</b>, or type changes and I'll revise the plan.")
        self.plan_bar.show()

    def build_plan(self):
        if self.thread or not self._last_plan or not self._ensure_ready():
            return
        self.plan_bar.hide()
        self.game_built = True  # follow-up messages now edit the built game
        msg = (
            "Build this game now, following the plan step by step until it is fully playable.\n\n"
            f"Game idea: {self.pending_idea}\n\nPlan:\n{self._last_plan}"
        )
        self._say("system", "Building your game in Studio. This can take several minutes…")
        agent = self.agent
        self._run(lambda emit: agent.run(msg, emit), self._finished)

    def _finished(self, text: str):
        self._say("ai", self._md(text))
        self._save_history()

    # --------------------------------------------------------------- extra features
    def quick(self, key: str, label: str):
        if self.thread or not self._ensure_ready():
            return
        self._say("you", html.escape(label))
        agent = self.agent
        self._run(lambda emit: agent.run(QUICK_ACTIONS[key], emit), self._finished)

    def undo(self):
        if self.thread or not self.studio.studio_id:
            return
        code = 'game:GetService("ChangeHistoryService"):Undo() return "undone"'
        self._run(lambda emit: self.studio.text_of(self.studio.call("execute_luau", {"code": code, "datamodel_type": "Edit"})),
                  lambda r: self._say("system", "Undo: " + html.escape(r[:200]) + "<br>If nothing changed, press Ctrl+Z in Studio."),
                  busy_send=False)

    def attach(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Attach reference images", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if paths:
            self.attachments.extend(paths)
            names = ", ".join(os.path.basename(p) for p in self.attachments)
            self.attach_label.setText(f"📎 {names}  (sent with your next message)")
            self.attach_label.show()

    def enhance(self):
        text = self.input.toPlainText().strip()
        if not text or self.thread:
            return
        if self.agent is None:
            try:
                self.agent = self._make_agent()
            except Exception as e:
                self._say("error", html.escape(str(e)))
                return
        agent = self.agent
        self._run(lambda emit: agent.enhance_prompt(text), lambda r: self.input.setPlainText(r), busy_send=False)

    def _history_dir(self):
        d = config.config_dir() / "chats"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save_history(self):
        if not hasattr(self, "_chat_file"):
            stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self._chat_file = self._history_dir() / f"chat_{stamp}.html"
        try:
            self._chat_file.write_text(self.chat.toHtml(), "utf-8")
        except Exception:
            pass

    def open_history(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._history_dir())))

    def stop(self):
        if self.agent:
            self.agent.stop_requested = True
        self._say("system", "Stopping after the current step…")

    def new_chat(self):
        if self.agent:
            self.agent.reset()
        self.chat.clear()
        if hasattr(self, "_chat_file"):
            del self._chat_file
        self.plan_bar.hide()
        self._last_plan = ""
        self.game_built = False
        self._say("system", "New conversation.")

    # --------------------------------------------------------------- threading
    def _run(self, fn, on_done, busy_send: bool = True):
        self.thread = QThread()
        self.worker = Worker(fn)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.event.connect(self._on_event)
        self.worker.done.connect(on_done)
        self.worker.failed.connect(self._on_fail)
        self.worker.done.connect(self._cleanup)
        self.worker.failed.connect(self._cleanup)
        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(busy_send)
        self.thread.start()

    def _on_event(self, kind: str, text: str):
        if kind == "tool":
            self._say("tool", "🔧 " + html.escape(text))
        elif kind == "result":
            first = text.strip().split("\n")[0][:160]
            self._say("tool", "&nbsp;&nbsp;↳ " + html.escape(first))
        elif kind == "thought":
            self._say("ai", self._md(text))

    def _on_fail(self, err: str):
        if "Studio" in err or "MCP" in err:
            self.status.setText("● Studio: not connected")
        self._say("error", html.escape(err))

    def _cleanup(self, *_):
        if self.thread:
            self.thread.quit()
            self.thread.wait(3000)
        self.thread = None
        self.worker = None
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def closeEvent(self, e):
        if self.agent:
            self.agent.stop_requested = True
        self.studio.stop()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Segoe UI", 10))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

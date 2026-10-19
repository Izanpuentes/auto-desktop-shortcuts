#!/usr/bin/env python3
"""auto-desktop-shortcuts: accesos directos en el escritorio de Ubuntu, como en Windows.

Usa Gio para obtener las mismas apps que muestra el menú de aplicaciones
(apt, Snap y Flatpak, sin duplicados ni lanzadores ocultos) y para enterarse
de cuándo se instala una app nueva.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

APP_NAME = "auto-desktop-shortcuts"
SCRIPT_PATH = Path(__file__).resolve()
STATE_FILE = Path(GLib.get_user_state_dir()) / APP_NAME / "state.json"
AUTOSTART_FILE = Path(GLib.get_user_config_dir()) / "autostart" / f"{APP_NAME}.desktop"
# Segundos de espera tras un cambio: una instalación genera varios eventos seguidos
CHANGE_DEBOUNCE = 3


# --- Apps y accesos directos ---------------------------------------------------

def desktop_dir():
    path = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP)
    return Path(path or Path.home() / "Desktop")


def visible_apps():
    """Apps que aparecen en el menú de aplicaciones, indexadas por su id."""
    return {
        app.get_id(): app
        for app in Gio.AppInfo.get_all()
        if isinstance(app, Gio.DesktopAppInfo) and app.should_show() and app.get_filename()
    }


def shortcut_path(app):
    return desktop_dir() / app.get_id()


def has_shortcut(app):
    return shortcut_path(app).exists()


def create_shortcut(app):
    """Copia el lanzador al escritorio, lo hace ejecutable y lo marca como de confianza."""
    dst = shortcut_path(app)
    dst.parent.mkdir(parents=True, exist_ok=True)
    # copyfile sigue los enlaces simbólicos (Flatpak los usa), así que copia el archivo real
    shutil.copyfile(app.get_filename(), dst)
    os.chmod(dst, 0o755)
    # Sin esto Desktop Icons NG muestra el icono pero no deja abrirlo
    Gio.File.new_for_path(str(dst)).set_attribute_string(
        "metadata::trusted", "true", Gio.FileQueryInfoFlags.NONE, None
    )
    return dst


def remove_shortcut(app):
    shortcut_path(app).unlink(missing_ok=True)


def find_app(query, apps):
    """Busca una app por id (con o sin .desktop) o por nombre, exacto o parcial."""
    q = query.lower().removesuffix(".desktop")
    for app_id, app in apps.items():
        if q in (app_id.lower().removesuffix(".desktop"), app.get_name().lower()):
            return app
    matches = [
        app for app_id, app in apps.items()
        if q in app_id.lower() or q in app.get_name().lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        names = ", ".join(sorted(a.get_name() for a in matches))
        raise LookupError(f"'{query}' es ambiguo: {names}")
    raise LookupError(f"No se ha encontrado ninguna app para '{query}'")


# --- Estado del vigilante --------------------------------------------------------

def load_state():
    try:
        data = json.loads(STATE_FILE.read_text())
        return set(data.get("known", [])), set(data.get("ignored", []))
    except (OSError, ValueError):
        return None, set()


def save_state(known, ignored):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(
        {"known": sorted(known), "ignored": sorted(ignored)}, indent=2, ensure_ascii=False
    ))


class Watcher:
    """Pregunta si crear el acceso directo cada vez que aparece una app nueva."""

    def __init__(self):
        known, self.ignored = load_state()
        # visible_apps() también es necesario para que el monitor emita eventos
        current = set(visible_apps())
        # La primera vez solo se apunta lo que ya hay instalado, sin preguntar nada
        self.known = current if known is None else known
        self.pending = None
        self.monitor = Gio.AppInfoMonitor.get()
        self.monitor.connect("changed", self.on_changed)
        save_state(self.known, self.ignored)
        # Comprueba también lo instalado mientras el vigilante no estaba en marcha
        self.check()

    def on_changed(self, _monitor):
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add_seconds(CHANGE_DEBOUNCE, self.check)

    def check(self):
        self.pending = None
        apps = visible_apps()
        for app_id in sorted(set(apps) - self.known):
            app = apps[app_id]
            if app_id not in self.ignored and not has_shortcut(app):
                self.ask(app)
        # Las apps desinstaladas salen de la lista: si se reinstalan se vuelve a preguntar
        self.known = set(apps)
        save_state(self.known, self.ignored)
        return GLib.SOURCE_REMOVE

    def ask(self, app):
        print(f"Nueva app: {app.get_name()} ({app.get_id()})", flush=True)
        icon = app.get_icon()
        cmd = [
            "notify-send",
            "--app-name=Accesos directos",
            f"--icon={icon.to_string() if icon else 'application-x-executable'}",
            "--action=add=Crear acceso directo",
            "--action=ignore=No volver a preguntar",
            f"Se ha instalado {app.get_name()}",
            "¿Quieres crear un acceso directo en el escritorio?",
        ]
        app_id = app.get_id()

        # notify-send espera a que el usuario responda, así que va en otro hilo
        def worker():
            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
            except OSError as e:
                print(f"No se pudo mostrar la notificación: {e}", file=sys.stderr)
                return
            GLib.idle_add(self.on_answer, app_id, result.stdout.strip())

        threading.Thread(target=worker, daemon=True).start()

    def on_answer(self, app_id, answer):
        if answer == "add":
            app = visible_apps().get(app_id)
            if app:
                print(f"Acceso directo creado: {create_shortcut(app)}", flush=True)
        elif answer == "ignore":
            self.ignored.add(app_id)
            save_state(self.known, self.ignored)
        return GLib.SOURCE_REMOVE


# --- Comandos --------------------------------------------------------------------

def cmd_list(_args):
    apps = visible_apps()
    for app in sorted(apps.values(), key=lambda a: a.get_name().lower()):
        mark = "x" if has_shortcut(app) else " "
        print(f"[{mark}] {app.get_name():<35} {app.get_id()}")
    print(f"\n{len(apps)} apps; [x] = ya está en el escritorio ({desktop_dir()})")


def cmd_add(args):
    apps = visible_apps()
    ok = True
    for query in args.apps:
        try:
            app = find_app(query, apps)
        except LookupError as e:
            print(e, file=sys.stderr)
            ok = False
            continue
        print(f"{app.get_name()}: {create_shortcut(app)}")
    return 0 if ok else 1


def cmd_remove(args):
    apps = visible_apps()
    ok = True
    for query in args.apps:
        try:
            app = find_app(query, apps)
        except LookupError as e:
            print(e, file=sys.stderr)
            ok = False
            continue
        if has_shortcut(app):
            remove_shortcut(app)
            print(f"{app.get_name()}: acceso directo eliminado")
        else:
            print(f"{app.get_name()}: no tenía acceso directo")
    return 0 if ok else 1


def cmd_watch(_args):
    Watcher()
    print("Vigilando instalaciones nuevas (Ctrl+C para salir)...", flush=True)
    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        pass


def cmd_autostart(args):
    if args.state == "on":
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART_FILE.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Accesos directos automáticos\n"
            "Comment=Ofrece crear accesos directos al instalar aplicaciones\n"
            f'Exec=/usr/bin/python3 "{SCRIPT_PATH}" watch\n'
            "NoDisplay=true\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        print(f"Se iniciará al entrar en la sesión ({AUTOSTART_FILE})")
    else:
        AUTOSTART_FILE.unlink(missing_ok=True)
        print("Inicio automático desactivado")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog=APP_NAME, description="Accesos directos en el escritorio para tus aplicaciones."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="lista las apps instaladas").set_defaults(func=cmd_list)
    p = sub.add_parser("add", help="crea accesos directos")
    p.add_argument("apps", nargs="+", help="nombre o id de la app")
    p.set_defaults(func=cmd_add)
    p = sub.add_parser("remove", help="quita accesos directos")
    p.add_argument("apps", nargs="+", help="nombre o id de la app")
    p.set_defaults(func=cmd_remove)
    sub.add_parser("watch", help="pregunta al instalar apps nuevas").set_defaults(func=cmd_watch)
    p = sub.add_parser("autostart", help="arranca 'watch' al iniciar sesión")
    p.add_argument("state", choices=["on", "off"])
    p.set_defaults(func=cmd_autostart)
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())

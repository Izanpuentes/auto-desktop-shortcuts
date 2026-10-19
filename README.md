# auto-desktop-shortcuts

Herramienta para Ubuntu (GNOME + Desktop Icons NG) que crea accesos directos en el
escritorio para las aplicaciones instaladas y, como en Windows, ofrece crearlos
automáticamente al instalar una app nueva.

Funciona con apps instaladas por apt, Snap y Flatpak: usa la misma lista que el
menú de aplicaciones, sin duplicados ni lanzadores ocultos.

## Requisitos

Ubuntu 24.04 o similar con GNOME. No necesita instalar nada: usa Python 3,
PyGObject y `notify-send`, que vienen de serie.

## Uso

```bash
./auto_desktop_shortcuts.py list               # apps instaladas; [x] = ya en el escritorio
./auto_desktop_shortcuts.py add firefox steam  # crea accesos directos (nombre o id)
./auto_desktop_shortcuts.py remove firefox     # los quita
./auto_desktop_shortcuts.py watch              # pregunta al instalar apps nuevas
./auto_desktop_shortcuts.py autostart on       # arranca 'watch' al iniciar sesión
```

Al instalar una app con `watch` en marcha aparece una notificación con los botones
**Crear acceso directo** y **No volver a preguntar**.

## Cómo funciona

Un acceso directo es una copia del archivo `.desktop` de la app en el escritorio,
marcada como ejecutable y como de confianza (`metadata::trusted`); sin esto último
Desktop Icons NG muestra el icono pero no deja abrirlo.

El estado del vigilante (apps conocidas e ignoradas) se guarda en
`~/.local/state/auto-desktop-shortcuts/state.json`.

## Pendiente

- Juegos de Steam: detectar los juegos nuevos aunque Steam no cree su lanzador.
- Interfaz gráfica para elegir apps sin usar la terminal.
- Empaquetado e integración con Desktop Icons NG.

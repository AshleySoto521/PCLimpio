<p align="center"><img src="assets/logo.png" alt="Logo de PCLimpio" width="160"></p>

# PCLimpio

**Mantenimiento de Windows gratis, en español y 100 % local.** Limpia archivos que sobran, te dice qué ocupa tu
disco (y si lo puedes borrar), acelera el encendido, actualiza programas y controladores y recupera archivos
borrados. Todo explicado para que cualquier persona lo entienda, sin tecnicismos.

- 🔒 **No puede romper Windows**: nunca borra archivos del sistema ni de tus programas, nunca apaga tu antivirus,
  aunque se ejecute como administrador. Si algo está protegido te dice por qué.
- 🏠 **Nada sale de tu equipo**: sin cuentas, sin nube, sin publicidad, sin enviar datos a nadie.
- 📝 **Transparente**: anota en un historial todo lo que borra o cambia.

> PCLimpio es un proyecto independiente. No está afiliado a CCleaner, Piriform ni Gen Digital.

## Descargar y usar (no necesitas Python)

1. Ve a la página **[Releases](../../releases/latest)** y descarga `PCLimpio.exe`.
2. Haz doble clic en `PCLimpio.exe`. No hay que instalar nada.
3. Como el programa es nuevo y no está firmado, Windows puede mostrar **«Windows protegió su PC»**.
   Pulsa **«Más información» → «Ejecutar de todas formas»**. Es normal en programas gratuitos que empiezan.

Requisitos: Windows 10 u 11 y Microsoft Edge (viene con Windows).

### ¿Cómo sé que el archivo es el original?

Junto al `.exe` se publica `PCLimpio.exe.sha256`, su «huella digital». Para comprobarla, abre PowerShell en la
carpeta donde lo descargaste y escribe:

```powershell
Get-FileHash .\PCLimpio.exe -Algorithm SHA256
```

El número que aparece debe ser igual al del archivo `.sha256`. Si no coincide, no lo uses.

## Qué hace

| Sección | Para qué sirve |
|---|---|
| Limpieza básica | Quita archivos temporales, copias guardadas por los navegadores y restos que Windows vuelve a crear solo. |
| Limpieza avanzada | Restos de actualizaciones de Windows, de instaladores y de tus programas; anotaciones rotas de Windows (con copia para deshacer). |
| Limpiador automático del historial | Borra el rastro de navegación cuando tú quieras o de forma programada. No toca favoritos ni contraseñas. |
| Analizador de disco | Qué llena tu disco, qué es cada cosa y si la puedes quitar. Encuentra archivos repetidos. |
| Optimizador de rendimiento | «Pone a dormir» programas que trabajan a escondidas y controla qué se abre al encender. |
| Actualizador de controladores | Revisa que la pantalla, el sonido o el Wi-Fi tengan controladores correctos (vía Windows Update). |
| Actualizador de software | Muestra qué programas tienen versión nueva y los actualiza (vía winget, de Windows). |
| Recuperación de archivos | Recupera de la Papelera o rescata archivos borrados hace tiempo en discos NTFS. |
| Información del sistema | Qué piezas tiene tu equipo y si están bien, en pocas palabras. |
| Historial de actividad | Todo lo que PCLimpio ha borrado o cambiado, con fecha y hora. |

Algunas funciones (carpetas de Windows, controladores, recuperación profunda) piden tu permiso de administrador
desde la propia app; Windows te preguntará y basta con responder «Sí».

## Privacidad

PCLimpio funciona como una pequeña página web **solo dentro de tu equipo** (`127.0.0.1`), protegida con una
clave aleatoria que cambia en cada inicio. Sus datos (historial, copias de seguridad, registros) se guardan en
`%LOCALAPPDATA%\PCLimpio`. Las únicas conexiones a Internet son las que hacen las herramientas oficiales de
Windows cuando tú buscas actualizaciones (Windows Update y winget).

---

## Para desarrolladores

Escrito en Python usando solo la librería estándar; la interfaz es HTML/CSS/JavaScript sin dependencias.

```bash
py -3 main.py                              # abre la app desde el código
py -3 -m unittest discover -s tests -v     # pruebas
py -3 -m pip install pyinstaller           # una sola vez
py -3 build.py                             # genera dist/PCLimpio.exe
```

### Publicar una versión nueva

1. Cambia `VERSION` en `core/version.py` (por ejemplo `1.1.0`).
2. Sube los cambios y crea la etiqueta: `git tag v1.1.0` y `git push origin v1.1.0`.
3. GitHub Actions ejecuta las pruebas, compila `PCLimpio.exe` y lo publica en Releases automáticamente.

### Estructura

| Archivo | Qué hace |
|---|---|
| `main.py` | Arranca el servidor local y abre la ventana. |
| `core/safety.py` | Protección del sistema: decide qué se puede borrar, desinstalar, desactivar o cerrar, y por qué no. |
| `core/explain.py` | Traduce rutas técnicas a lenguaje cotidiano (qué es, si se puede borrar, qué hacer). |
| `core/cleaning.py` | Limpieza básica y avanzada basada en reglas. |
| `core/registry_clean.py` | Anotaciones rotas del registro, con respaldo `.reg` y restauración. |
| `core/history.py` | Limpieza de navegadores y su programación. |
| `core/analyzer.py` | Analizador de disco y duplicados (tamaño → hash parcial → BLAKE2 completo). |
| `core/optimizer.py` | Inicio, tareas, servicios, «modo dormir», procesos y energía. |
| `core/drivers.py` | Controladores vía WMI y el agente de Windows Update. |
| `core/software.py` | Actualizaciones con winget y desinstalador. |
| `core/recovery.py` | Papelera y lectura de la `$MFT` NTFS para archivos borrados. |
| `core/sysinfo.py` | Información del equipo por WMI/CIM. |
| `core/activity.py` | Historial de todo lo que hace la app. |
| `ui/` | Interfaz. |
| `assets/` | Logo original (`logo-original.webp`) y sus versiones; `tools/make_icon.py` genera el ícono (necesita Pillow). |

Las contribuciones son bienvenidas. Toda función que borre o cambie algo debe pasar por `core/safety.py` y
anotarse en `core/activity.py`.

## Licencia y autoría

Copyright (C) 2026 ashleysoto521.

PCLimpio es software libre: puedes usarlo, estudiarlo, modificarlo y compartirlo bajo los términos de la
**Licencia Pública General de GNU, versión 3 o posterior** (ver [`LICENSE`](LICENSE)). Si distribuyes una
versión modificada, debe seguir siendo libre con la misma licencia, conservar este aviso de autoría e indicar qué
cambiaste. Se ofrece **sin ninguna garantía**.

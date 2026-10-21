# OCR PDF a Excel

Web app local (pod de Podman) para extraer datos de PDFs escaneados mediante OCR,
revisarlos con filtros, compararlos entre motores y exportarlos a Excel/CSV/PDF.

## Stack

- **Backend:** FastAPI + SQLite + Tesseract OCR + OpenCV + pdfplumber + openpyxl/xlwt
- **Frontend:** Nginx + HTML/CSS/JS vanilla (módulos ES, gráficos SVG propios)
- **Contenedores:** Podman Pod (`podman play kube pod.yaml`)

## Acceso y credenciales

URL local: **http://localhost:8081** — el login es obligatorio; sin sesión no se
muestra ninguna sección ni endpoint de datos (solo `/api/health` queda abierto).

### Primer uso (instalación nueva, sin usuarios)
Si no existe ningún usuario, la pantalla muestra **“Crear administrador”**:
1. Usuario de 3–32 caracteres.
2. Contraseña de **mínimo 4 caracteres** (se pide dos veces).
3. Pulsa **Crear administrador**. Esa cuenta queda con rol `admin`.

No hay usuario/contraseña por defecto; no se puede entrar sin crear esta cuenta.

### Instalación local actual
| Usuario | Contraseña | Rol |
|---|---|---|
| `admin` | `admin123` | `admin` |
| `usuario` | `usuario123` | `usuario` |

> Credenciales solo para el entorno local. La instalación nueva sigue usando la
> pantalla “Crear administrador”; estas cuentas existen en esta instancia local.
> En producción cámbialas antes de exponer la web.

### Roles
- **`admin`**: acceso total (Inicio, Cargar OCR, Datos, Comparar, Historial,
  Configuración: IA, OCR y usuarios).
- **`usuario`**: solo lo relacionado con su OCR (Inicio, Cargar OCR, Datos,
  Comparar e Historial **de sus propios trabajos**). No ve Configuración ni los
  trabajos de otros usuarios.

El sistema impide degradar, desactivar o eliminar al último administrador activo.
La longitud mínima se puede ajustar con `PASSWORD_MIN_LENGTH` (por defecto 4).

### Acceso a modelos de pago
El admin habilita por usuario el uso de proveedores de pago (OpenCode o externo)
desde **Configuración → Usuarios**. También puede activarlo o desactivarlo para
todos con los botones correspondientes. El admin siempre tiene acceso; los
usuarios nuevos empiezan sin acceso. Si el proveedor activo es llama.cpp local,
este permiso no es necesario.

### Iniciar sesión
- Abre http://localhost:8081, escribe usuario y contraseña, pulsa **Entrar**.
- **Recordar sesión**: 30 días. Sin marcar: 8 horas.
- Tras 5 intentos fallidos en 60 s, el login se bloquea 30 s.
- “Cerrar sesión” revoca la sesión. Desactivar o eliminar un usuario revoca sus
  sesiones al instante.

### Crear usuarios (solo admin)
**Configuración → Usuarios → Nuevo usuario**: usuario, contraseña corta y rol
(`admin` o `usuario`). Ahí mismo se cambia el rol, se activa/desactiva, se
resetea la contraseña y se elimina.

### Cambiar contraseña
- La propia: botón **Cambiar contraseña** en la barra lateral.
- La de otro usuario: **Configuración → Usuarios → Reset clave** (admin).

### Recuperar el admin si se pierde la contraseña
No hay recuperación por correo. Con el pod levantado, desde el host:

```bash
podman exec -it ocr-app-backend python3 -c "
from src import auth, db
auth.db.init_db()
u = db.query_one('SELECT id FROM users WHERE username=?', ('admin',))
auth.update_user(u['id'], role='admin', active=True, password='NuevaClave123')
"
```

Para empezar de cero hay que borrar `data/ocr.db` **y** `data/auth.json`
(si queda `auth.json`, el admin se vuelve a migrar con la contraseña antigua).
Se pierde el historial de trabajos y usuarios; la configuración IA cifrada
(`data/ai_settings.enc`) se conserva mientras no borres `data/.secret_key`.

## Interfaz

- **Inicio:** KPIs y gráficos (completitud, cobertura y precisión por campo,
  evolución). El usuario ve solo sus trabajos; el admin, la vista global.
- **Cargar OCR:** asistente en 3 pasos (archivo → motor → opciones) con progreso
  en vivo. El modelo de IA se **detecta automáticamente** y se elige con un
  selector compacto, con scroll fijo, búsqueda y navegación por teclado
  (`Ctrl+K`, `/`, flechas y Enter). Antes de procesar puedes cambiar el
  **nombre base del documento** y elegir la extensión con botones `.pdf`,
  `.xlsx` o `.xls`; la extensión no se escribe a mano. Incluye
  una lista de **documentos cargados** que conserva el PDF/Excel original para
  reprocesarlo sin volver a subirlo; el admin ve también el propietario. La lista
  se actualiza al iniciar y terminar un trabajo, y permite renombrar el documento
  (el nuevo nombre se sincroniza en Historial, Datos e Inicio).
- **Datos:** tabla espaciosa, filtros por campo/origen/estado, chips de filtros,
  selector de columnas, edición en panel lateral (drawer), selección y exportación.
  Al editar una página se muestra la **imagen del PDF** junto a los campos para
  verificar el OCR, con zoom y apertura en tamaño completo. En móvil la imagen
  queda arriba y el formulario debajo.
- **Comparar:** A vs B (otro motor o el ground truth), coincidencia por campo y
  acción “Usar B”. Las diferencias se muestran como tabla en escritorio y tarjetas
  en móvil. La selección A/B se guarda en la URL y se conserva al recargar.
- **Historial:** filtros por fecha, archivo, motor, estado y usuario (admin);
  abrir, cancelar, reintentar, descargar y borrar. Los trabajos de IA que
  terminaron usando OCR local se marcan como **Fallback local**. El admin puede
  borrar todos los trabajos, documentos y PDFs con contraseña y segunda
  confirmación; existe una opción para conservar los documentos. También existe
  borrado por rango. Borrar un trabajo elimina solo
  sus resultados: el documento original permanece en **Cargar OCR**. Para borrar
  también el archivo hay que usar **Documentos → Borrar documento**. El admin
  dispone de **Borrar por rango** para eliminar trabajos entre dos fechas,
  conservando los PDFs salvo que marque la opción de borrar documentos huérfanos.
- **Configuración (admin):** proveedor de IA, OCR por defecto y usuarios.

Diseño responsive verificado en 1920/1440/1024/768/390, sin emojis ni ilustraciones tipo sticker;
solo iconos lineales. Los gráficos son SVG propios, sin dependencias ni CDN.

## Motores de OCR

1. **Local (sin IA):** Tesseract + OpenCV. Perfil `OCR_PROFILE=legacy|cand`
   (`cand` por defecto: corrección de sombras, CLAHE, deskew y fusión de pasadas).
   Incluye código de barras (`pyzbar`) y MRZ con dígito de control.
2. **IA local (VLM):** envía la imagen de cada página + prompt OCR
   (`backend/src/prompts.py`) a un servidor llama.cpp/OpenAI-compatible.
   Si falla una página, cae automáticamente al motor local.
3. **Agente (offline):** ground truth de referencia (`data/ground_truth.*`),
   usado por Inicio y Comparar.

## IA local (llama.cpp)

La app **detecta sola** el servidor y los modelos; no hay que escribir modelo ni
ruta. El campo API key solo aparece para proveedores de pago (**OpenCode** o
externo); para llama.cpp no se usa.

Requisitos del servidor llama.cpp:

- Modelo **multimodal** con `--mmproj` (visión).
- `--host 0.0.0.0` y puerto `9931` (o el que publiques).
- **`ubatch-size ≥ 2048`** y `batch-size ≥ ubatch-size` en el preset del modelo.
  Con 512 el servidor aborta al procesar una página completa
  (`non-causal attention requires n_ubatch >= n_tokens`).
- La app desactiva el “thinking” (`enable_thinking=false`) y reintenta con una
  imagen más pequeña si el servidor falla.

Desde el contenedor OCR la URL correcta es:

```
http://host.containers.internal:9931/v1
```

`localhost` dentro del contenedor apunta al propio contenedor, no al host. Desde
el host usa `http://127.0.0.1:9931` (no `localhost`, que resuelve a IPv6).

En **Configuración → Proveedor de IA → Local** puedes cambiar la **URL del
servidor local** (por ejemplo `https://lama.cpp.mapstest.tech`), escanear modelos,
elegir uno con visión y **Probar conexión** (texto + visión). Si escribes la URL
sin ruta, se añade `/v1` automáticamente. El botón `?` muestra la ayuda al pasar
el mouse, se fija al hacer clic y se cierra al hacer clic fuera.
Alternativa por entorno: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT`.

## OpenCode Go (modelos de pago)

En **Configuración → Proveedor de IA → OpenCode Go** se configura la suscripción
Go de OpenCode:

```text
URL de chat / API:   https://opencode.ai/inference/go/openai/v1
URL de modelos:      https://opencode.ai/inference/go/v1/models
API key:             clave de OpenCode Console/Go
```

La app consulta los modelos, permite elegir uno y prueba conexión de texto y
visión. Los endpoints `/go/...` son los de la suscripción OpenCode Go; no deben usarse
los endpoints de Console/pago por uso, que devuelven `402 Insufficient funds`.
Go incluye modelos gratuitos y de pago. Para OCR elige un modelo con visión.
`claude-haiku-5-5` funciona con visión usando el adaptador Anthropic de Go;
DeepSeek V4.1 Flash responde texto pero no procesa imágenes. La migración desde
el endpoint antiguo de Console configura automáticamente Go y Claude Haiku 5.5. No todos los modelos aceptan imágenes; la prueba de visión
debe pasar antes de usar el modelo para OCR. La API key se guarda cifrada y solo
la usa el backend. El acceso de cada usuario se controla en
**Configuración → Usuarios**.

## Requisitos

- Podman 4.x+

## Uso

```bash
# 1. Construir imágenes
./scripts/build.sh

# 2. Iniciar pod (frontend en http://localhost:8081)
./scripts/start.sh

# 3. Detener
podman pod stop ocr-app

# 4. Eliminar pod
podman pod rm ocr-app
```

> El puerto es 8081 para no chocar con otros proyectos que usan 8080.

## API principal

| Ruta | Rol | Descripción |
|---|---|---|
| `GET /api/health` | — | Health check (abierto) |
| `POST /api/auth/login` / `logout` / `setup` | — | Sesión / primer admin |
| `GET /api/auth/me`, `POST /api/auth/change-password` | autenticado | Cuenta propia |
| `POST /api/auth/verify-password` | autenticado | Verifica la contraseña para acciones destructivas |
| `GET/POST/PATCH/DELETE /api/users` | admin | Usuarios, roles y acceso a API de pago |
| `POST /api/users/paid-access` | admin | Activa/desactiva API de pago para todos |
| `POST /api/jobs` | admin/usuario | Sube archivo, nombre visible y crea job asíncrono (incluye `model`) |
| `GET /api/documents` | admin/usuario | Documentos originales conservados (filtrado por dueño) |
| `POST /api/documents/{id}/jobs` | admin/usuario | Reprocesa un documento sin volver a subirlo |
| `PATCH /api/documents/{id}` | dueño/admin | Renombra el documento y sincroniza sus trabajos |
| `DELETE /api/documents/{id}` | dueño/admin | Borra el documento, su archivo y sus trabajos |
| `GET /api/jobs`, `GET /api/jobs/{id}`, `/events` | autenticado | Historial y progreso (filtrado por dueño) |
| `GET /api/jobs/bulk-delete/preview` | admin | Previsualiza borrado por rango |
| `POST /api/jobs/bulk-delete` | admin | Borra trabajos por rango; PDFs opcionales |
| `POST /api/jobs/delete-all` | admin | Borra todos los trabajos y, por defecto, documentos/PDFs |
| `POST /api/jobs/{id}/cancel`, `/retry`, `DELETE` | dueño/admin | Control |
| `GET/PATCH /api/jobs/{id}/results` | dueño/admin | Resultados con filtros y edición |
| `POST /api/jobs/{id}/export/{xlsx,xls,csv,pdf}` | dueño/admin | Exporta el filtrado |
| `GET /api/jobs/{id}/compare?other_id=…` | autenticado | Diferencias entre trabajos |
| `GET /api/stats` | autenticado | Métricas (propias o globales si admin) |
| `GET /api/ai/providers` | autenticado | Descubre llama.cpp y modelos |
| `GET/PUT/DELETE /api/settings/ai` | admin | Proveedor IA (clave cifrada para OpenCode/externo) |
| `POST /api/settings/ai/test` | admin | Prueba real de texto + visión |
| `GET/PUT /api/settings/ocr` | admin | Perfil/DPI/workers por defecto |

## Base de datos y archivos

- `data/ocr.db` (SQLite): usuarios, sesiones, documentos, jobs, resultados, eventos y auditoría.
  Incluye `users.paid_ai` y los nombres originales de documentos.
- `data/pages/<document_id>/<page>.jpg`: caché de imágenes para revisar el OCR.
- `data/uploads/`, `data/downloads/`: documentos originales y archivos exportados.
- `data/.secret_key`, `data/auth.json`, `data/ai_settings.enc`: sensibles.
  Si borras `.secret_key`, la configuración IA queda ilegible (vuelve a guardarla).
- `data/ground_truth.*`: referencia del agente (42 páginas de `data/documento.pdf`).

## Verificación

```bash
# Procesa un PDF con la API v1 y genera data/verify_output.xlsx y .xls
OCR_PASS='tu-contraseña' ./scripts/verify.sh ruta/al/documento.pdf

# Laboratorio OCR dentro del contenedor (perfiles legacy/cand, mide contra ground truth)
./scripts/ocr_lab.sh data/documento.pdf --pages all --profile cand

# Comparativo de modos contra data/ground_truth.json
podman run --rm -v "$PWD":/work:Z -w /work localhost/ocr-backend:latest \
  python3 scripts/compare_modes.py --gt data/ground_truth.json \
  --mode "local_cand=data/lab/cand_dpi200/rows.json" --out data/ocr_compare_report.md
```

Resultados de referencia: `data/ocr_quality_report.md` y `data/ocr_compare_report.md`.

## Notas

- Tesseract corre en CPU (sin GPU); el VLM local puede usar GPU si está disponible.
- El procesamiento es asíncrono: puedes cerrar la pestaña y ver el progreso en Historial.
- `OCR_WORKERS` (ajustable en Configuración; requiere reiniciar el pod) controla
  cuántos jobs se procesan a la vez.
- `data/auth.json` es solo legado de migración: tras confirmar el login puedes borrarlo.
- La app asume red local; si la expones, termina el TLS en nginx.

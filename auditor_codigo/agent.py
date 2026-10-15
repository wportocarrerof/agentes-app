import os
from datetime import datetime
from dotenv import load_dotenv
from google.adk.agents.llm_agent import Agent

# 1. Carga primero el .env local del agente y como fallback el .env de la raíz del proyecto
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
load_dotenv()

# Configuraciones de filtrado, seguridad y límites de contexto
EXTENSIONES_VALIDAS = {
    '.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs',
    '.html', '.css', '.sql', '.json', '.yaml', '.yml',
    '.sh', '.rules', '.vue', '.svelte', '.prisma'
}
ARCHIVOS_IGNORADOS = {
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    'composer.lock', 'tsconfig.tsbuildinfo'
}
PATRONES_SENSIBLES = (
    '.env', 'serviceaccount', 'credentials', 'firebase-adminsdk',
    'secret', 'private_key', 'id_rsa', '.pem', '.key'
)
DIRECTORIOS_IGNORADOS = {
    '.git', 'node_modules', '__pycache__', '.next', 'dist', 'build',
    '.adk', 'venv', '.venv', 'env', '.firebase', 'coverage',
    '.turbo', '.nuxt', '.svelte-kit', '.idea', '.vscode', '.pytest_cache'
}

MAX_ARCHIVOS_LISTADOS = 200    # Evita desbordar tokens en monorepositorios
MAX_ARCHIVOS_POR_LOTE = 25     # Máximo de archivos a leer por llamada
MAX_CHARS_POR_ARCHIVO = 40000  # ~10k tokens máx por archivo


def _es_archivo_sensible(nombre_archivo: str) -> bool:
    """Verifica si el nombre del archivo coincide con patrones de credenciales o secretos."""
    nombre_lower = nombre_archivo.lower()
    return any(patron in nombre_lower for patron in PATRONES_SENSIBLES)


def listar_archivos_proyecto(ruta_directorio: str) -> str:
    """Lista únicamente los archivos de código fuente relevantes del proyecto (máx. 200 archivos)."""
    try:
        ruta_abs = os.path.abspath(os.path.expanduser(ruta_directorio))
        if not os.path.exists(ruta_abs):
            return f"Error: El directorio '{ruta_directorio}' no existe."
        if not os.path.isdir(ruta_abs):
            return f"Error: La ruta '{ruta_directorio}' no es un directorio."

        archivos_encontrados = []
        truncado = False

        for raiz, dirs, archivos in os.walk(ruta_abs):
            dirs[:] = [d for d in dirs if d not in DIRECTORIOS_IGNORADOS and not d.startswith('.')]
            for archivo in sorted(archivos):
                _, ext = os.path.splitext(archivo)
                if (not archivo.startswith('.')
                    and not archivo.startswith('aud_')
                    and archivo not in ARCHIVOS_IGNORADOS
                    and not _es_archivo_sensible(archivo)
                    and ext.lower() in EXTENSIONES_VALIDAS):
                    archivos_encontrados.append(os.path.join(raiz, archivo))
                    if len(archivos_encontrados) >= MAX_ARCHIVOS_LISTADOS:
                        truncado = True
                        break
            if truncado:
                break

        if not archivos_encontrados:
            return "No se encontraron archivos de código auditables."

        salida = "\n".join(archivos_encontrados)
        if truncado:
            salida += f"\n... [LISTA TRUNCADA A {MAX_ARCHIVOS_LISTADOS} ARCHIVOS]"
        return salida
    except Exception as e:
        return f"Error al explorar el directorio {ruta_directorio}: {str(e)}"


def leer_archivos_en_lote(ruta_directorio_proyecto: str, rutas_archivos: list[str]) -> str:
    """Lee un lote de archivos (máx. 25) validando que pertenezcan al directorio del proyecto."""
    try:
        raiz_abs = os.path.abspath(os.path.expanduser(ruta_directorio_proyecto))
    except Exception as e:
        return f"Error al resolver la ruta raíz del proyecto: {str(e)}"

    resultado = []
    for ruta in rutas_archivos[:MAX_ARCHIVOS_POR_LOTE]:
        try:
            ruta_abs = os.path.abspath(os.path.expanduser(ruta))
            nombre_base = os.path.basename(ruta_abs)

            # 1. Prevenir Path Traversal fuera de la carpeta del proyecto
            if os.path.commonpath([raiz_abs, ruta_abs]) != raiz_abs:
                resultado.append(f"=== ACCESO DENEGADO (Fuera del proyecto): {ruta} ===\n")
                continue

            # 2. Bloquear archivos con credenciales o secretos (.env, serviceAccountKey.json, etc.)
            if _es_archivo_sensible(nombre_base):
                resultado.append(f"=== ARCHIVO SENSIBLE BLOQUEADO POR SEGURIDAD: {nombre_base} ===\n")
                continue

            with open(ruta_abs, 'r', encoding='utf-8', errors='replace') as f:
                contenido = f.read(MAX_CHARS_POR_ARCHIVO + 1)
                if len(contenido) > MAX_CHARS_POR_ARCHIVO:
                    contenido = contenido[:MAX_CHARS_POR_ARCHIVO] + "\n... [ARCHIVO TRUNCADO POR TAMAÑO]"
                resultado.append(f"=== ARCHIVO: {ruta} ===\n{contenido}\n")
        except Exception as e:
            resultado.append(f"=== ERROR EN {ruta}: {str(e)} ===\n")

    if len(rutas_archivos) > MAX_ARCHIVOS_POR_LOTE:
        restantes = len(rutas_archivos) - MAX_ARCHIVOS_POR_LOTE
        resultado.append(f"... [Se omitieron {restantes} archivos por límite de lote (máx {MAX_ARCHIVOS_POR_LOTE})]")

    return "\n".join(resultado)


def guardar_reporte_md(ruta_directorio_proyecto: str, contenido: str) -> str:
    """Guarda el informe de auditoría completo en un archivo Markdown (.md)."""
    try:
        ruta_limpia = os.path.abspath(os.path.expanduser(ruta_directorio_proyecto))
        if os.path.isfile(ruta_limpia):
            ruta_limpia = os.path.dirname(ruta_limpia)

        nombre_proyecto = os.path.basename(ruta_limpia) or "proyecto"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre_archivo = f"aud_{nombre_proyecto}_{timestamp}.md"
        ruta_completa = os.path.join(ruta_limpia, nombre_archivo)

        # Fallback a subcarpeta local ./reportes si el directorio analizado es de solo lectura
        try:
            with open(ruta_completa, 'w', encoding='utf-8') as f:
                f.write(contenido)
        except PermissionError:
            dir_alternativo = os.path.join(os.path.dirname(__file__), 'reportes')
            os.makedirs(dir_alternativo, exist_ok=True)
            ruta_completa = os.path.join(dir_alternativo, nombre_archivo)
            with open(ruta_completa, 'w', encoding='utf-8') as f:
                f.write(contenido)

        return f"OK: Reporte guardado en {ruta_completa}"
    except Exception as e:
        return f"Error al guardar el reporte: {str(e)}"


root_agent = Agent(
    model=os.getenv('ADK_MODEL', 'gemini-3.8-flash'),
    name='code_auditor_agent',
    description='Auditor técnico de código enfocado en seguridad, rendimiento y buenas prácticas.',
    instruction='''Eres un Ingeniero de Software Senior y Auditor de Código estricto pero constructivo.

FLUJO DE TRABAJO OBLIGATORIO:
Paso 1: Usa `listar_archivos_proyecto` para ver los archivos de la carpeta indicada.
Paso 2: Usa `leer_archivos_en_lote` pasando `ruta_directorio_proyecto` y una lista con los archivos principales que necesites auditar en UNA SOLA llamada (máximo 25 archivos por lote; solo realiza una segunda llamada si el proyecto tiene más de 25 archivos críticos).
Paso 3 (OBLIGATORIO): Invoca `guardar_reporte_md` pasándole la `ruta_directorio_proyecto` y el informe completo en `contenido` (estructurado en Resumen Ejecutivo, Hallazgos bajo los 4 pilares [CRÍTICO/MEDIO/MEJORA] con líneas exactas, y Código Refactorizado).
Paso 4: En el chat, NO vuelvas a escribir el informe completo ni el código refactorizado. Solo confirma la ruta del archivo .md creado y muestra un resumen de máximo 5 líneas con el conteo de hallazgos encontrados.''',
    tools=[listar_archivos_proyecto, leer_archivos_en_lote, guardar_reporte_md]
)
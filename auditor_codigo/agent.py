import os
from datetime import datetime
from dotenv import load_dotenv
from google.adk.agents.llm_agent import Agent
from google.genai import types

# 1. Carga primero el .env local del agente y como fallback el .env de la raíz del proyecto
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
load_dotenv()

# Configuraciones de filtrado, seguridad y límites de contexto
EXTENSIONES_CODIGO_PURO = {
    '.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs',
    '.html', '.css', '.sql', '.sh', '.rules', '.vue', '.svelte', '.prisma'
}
EXTENSIONES_CONFIG_AUDITABLES = {'.json', '.yaml', '.yml'}
EXTENSIONES_VALIDAS = EXTENSIONES_CODIGO_PURO | EXTENSIONES_CONFIG_AUDITABLES

ARCHIVOS_IGNORADOS = {
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    'composer.lock', 'tsconfig.tsbuildinfo'
}
EXTENSIONES_SENSIBLES = {
    '.pem', '.key', '.p12', '.pfx', '.keystore', '.jks', '.crt', '.cer', '.der'
}
ARCHIVOS_SENSIBLES_EXACTOS = {
    'id_rsa', 'id_ed25519', '.htpasswd', '.netrc', '.npmrc', '.pypirc'
}
PATRONES_SENSIBLES_CONFIG = (
    'serviceaccount', 'credentials', 'firebase-adminsdk',
    'secret', 'private_key', 'client_secret', 'master.key'
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
    """Verifica si el archivo corresponde a credenciales, llaves privadas o secretos."""
    nombre_lower = nombre_archivo.lower()
    _, ext = os.path.splitext(nombre_lower)

    if nombre_lower == '.env' or nombre_lower.startswith('.env.'):
        return True
    if ext in EXTENSIONES_SENSIBLES or nombre_lower in ARCHIVOS_SENSIBLES_EXACTOS:
        return True
    # En archivos que no son código fuente puro (ej. .json, .yaml), bloquear nombres con patrones de secretos
    if ext not in EXTENSIONES_CODIGO_PURO:
        return any(patron in nombre_lower for patron in PATRONES_SENSIBLES_CONFIG)
    return False


def _es_ruta_relativa_permitida(ruta_relativa: str, nombre_archivo: str) -> bool:
    """Valida que el archivo y sus directorios contenedores cumplan las políticas de auditoría."""
    partes = ruta_relativa.split(os.sep)
    for directorio in partes[:-1]:
        if directorio in DIRECTORIOS_IGNORADOS or directorio.startswith('.'):
            return False

    _, ext = os.path.splitext(nombre_archivo)
    return (
        not nombre_archivo.startswith('.')
        and not nombre_archivo.startswith('aud_')
        and nombre_archivo not in ARCHIVOS_IGNORADOS
        and not _es_archivo_sensible(nombre_archivo)
        and ext.lower() in EXTENSIONES_VALIDAS
    )


def listar_archivos_proyecto(ruta_directorio: str) -> str:
    """Lista únicamente los archivos de código fuente relevantes del proyecto (máx. 200 archivos)."""
    try:
        ruta_abs = os.path.realpath(os.path.expanduser(ruta_directorio))
        if not os.path.exists(ruta_abs):
            return f"Error: El directorio '{ruta_directorio}' no existe."
        if not os.path.isdir(ruta_abs):
            return f"Error: La ruta '{ruta_directorio}' no es un directorio."

        archivos_encontrados = []
        truncado = False

        for raiz, dirs, archivos in os.walk(ruta_abs, followlinks=False):
            dirs[:] = sorted(
                d for d in dirs
                if d not in DIRECTORIOS_IGNORADOS
                and not d.startswith('.')
                and not os.path.islink(os.path.join(raiz, d))
            )
            for archivo in sorted(archivos):
                ruta_completa = os.path.join(raiz, archivo)
                if os.path.islink(ruta_completa):
                    continue

                ruta_real = os.path.realpath(ruta_completa)
                if os.path.commonpath([ruta_abs, ruta_real]) != ruta_abs:
                    continue

                ruta_rel = os.path.relpath(ruta_real, ruta_abs)
                if _es_ruta_relativa_permitida(ruta_rel, archivo):
                    archivos_encontrados.append(ruta_real)
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
    """Lee un lote de archivos (máx. 25) con numeración de líneas, validando pertenencia y seguridad."""
    try:
        raiz_abs = os.path.realpath(os.path.expanduser(ruta_directorio_proyecto))
        if not os.path.isdir(raiz_abs):
            return f"Error: El directorio raíz '{ruta_directorio_proyecto}' no es válido."
    except Exception as e:
        return f"Error al resolver la ruta raíz del proyecto: {str(e)}"

    resultado = []
    for ruta in rutas_archivos[:MAX_ARCHIVOS_POR_LOTE]:
        try:
            ruta_expandida = os.path.abspath(os.path.expanduser(ruta))
            if os.path.islink(ruta_expandida):
                resultado.append(f"=== ACCESO DENEGADO (Enlace simbólico no permitido): {ruta} ===\n")
                continue

            ruta_abs = os.path.realpath(ruta_expandida)
            nombre_base = os.path.basename(ruta_abs)

            # 1. Prevenir Path Traversal fuera de la carpeta real del proyecto
            if os.path.commonpath([raiz_abs, ruta_abs]) != raiz_abs:
                resultado.append(f"=== ACCESO DENEGADO (Fuera del proyecto): {ruta} ===\n")
                continue

            # 2. Bloquear archivos con credenciales o secretos (.env, serviceAccountKey.json, etc.)
            if _es_archivo_sensible(nombre_base):
                resultado.append(f"=== ARCHIVO SENSIBLE BLOQUEADO POR SEGURIDAD: {nombre_base} ===\n")
                continue

            # 3. Validar extensión permitida, directorios ignorados y que sea un archivo regular
            ruta_rel = os.path.relpath(ruta_abs, raiz_abs)
            if not _es_ruta_relativa_permitida(ruta_rel, nombre_base):
                resultado.append(f"=== ARCHIVO OMITIDO POR POLÍTICA DE FILTRADO: {ruta} ===\n")
                continue

            if not os.path.isfile(ruta_abs):
                resultado.append(f"=== ERROR: '{ruta}' no es un archivo válido ===\n")
                continue

            with open(ruta_abs, 'r', encoding='utf-8', errors='replace') as f:
                contenido = f.read(MAX_CHARS_POR_ARCHIVO + 1)
                fue_truncado = len(contenido) > MAX_CHARS_POR_ARCHIVO
                if fue_truncado:
                    contenido = contenido[:MAX_CHARS_POR_ARCHIVO]

                lineas_numeradas = [
                    f"{i}: {linea}"
                    for i, linea in enumerate(contenido.splitlines(), start=1)
                ]
                contenido_con_lineas = "\n".join(lineas_numeradas)
                if fue_truncado:
                    contenido_con_lineas += "\n... [ARCHIVO TRUNCADO POR TAMAÑO]"

                resultado.append(f"=== ARCHIVO: {ruta} ===\n{contenido_con_lineas}\n")
        except Exception as e:
            resultado.append(f"=== ERROR EN {ruta}: {str(e)} ===\n")

    if len(rutas_archivos) > MAX_ARCHIVOS_POR_LOTE:
        restantes = len(rutas_archivos) - MAX_ARCHIVOS_POR_LOTE
        resultado.append(f"... [Se omitieron {restantes} archivos por límite de lote (máx {MAX_ARCHIVOS_POR_LOTE})]")

    return "\n".join(resultado)


def guardar_reporte_md(ruta_directorio_proyecto: str, contenido: str) -> str:
    """Guarda el informe de auditoría completo en un archivo Markdown (.md)."""
    try:
        ruta_limpia = os.path.realpath(os.path.expanduser(ruta_directorio_proyecto))
        if os.path.isfile(ruta_limpia):
            ruta_limpia = os.path.dirname(ruta_limpia)

        nombre_proyecto = os.path.basename(ruta_limpia) or "proyecto"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre_archivo = f"aud_{nombre_proyecto}_{timestamp}.md"
        ruta_completa = os.path.join(ruta_limpia, nombre_archivo)

        # Fallback a subcarpeta local ./reportes si el directorio analizado es de solo lectura o inaccesible
        try:
            with open(ruta_completa, 'w', encoding='utf-8') as f:
                f.write(contenido)
        except OSError:
            dir_alternativo = os.path.join(os.path.dirname(__file__), 'reportes')
            os.makedirs(dir_alternativo, exist_ok=True)
            ruta_completa = os.path.join(dir_alternativo, nombre_archivo)
            with open(ruta_completa, 'w', encoding='utf-8') as f:
                f.write(contenido)

        return f"OK: Reporte guardado en {ruta_completa}"
    except Exception as e:
        return f"Error al guardar el reporte: {str(e)}"

thinking_level = os.getenv('ADK_THINKING_LEVEL', 'LOW')  # Valores válidos: 'LOW', 'MEDIUM', 'HIGH'
root_agent = Agent(
    model=os.getenv('ADK_MODEL', 'gemini-4-argon'),
    # model=os.getenv('ADK_MODEL', 'gemini-3.8-flash'),

    generate_content_config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(
            thinking_level=thinking_level
        )
    ),

    name='code_auditor_agent',
    description='Auditor técnico de código enfocado en seguridad, confiabilidad, rendimiento y buenas prácticas.',
    instruction='''Eres un Ingeniero de Software Senior y Auditor de Código estricto pero constructivo.

PILARES DE AUDITORÍA (Evalúa siempre bajo estos 4 pilares):
1. Seguridad: Vulnerabilidades, inyecciones, Path Traversal, exposición de secretos y control de accesos.
2. Confiabilidad y Manejo de Errores: Bugs lógicos, condiciones de carrera, casos borde y manejo de excepciones.
3. Rendimiento y Escalabilidad: Complejidad algorítmica, uso de memoria, operaciones de E/S bloqueantes y consumo de recursos.
4. Mantenibilidad y Buenas Prácticas: Arquitectura, legibilidad, tipado, modularidad y estándares del lenguaje.

FLUJO DE TRABAJO OBLIGATORIO:
Paso 1: Usa `listar_archivos_proyecto` para ver los archivos de la carpeta indicada.
Paso 2: Usa `leer_archivos_en_lote` pasando `ruta_directorio_proyecto` y una lista con los archivos principales que necesites auditar en UNA SOLA llamada (máximo 25 archivos por lote; solo realiza una segunda llamada si el proyecto tiene más de 25 archivos críticos).
Paso 3 (OBLIGATORIO): Invoca `guardar_reporte_md` pasándole la `ruta_directorio_proyecto` y el informe completo en `contenido` (estructurado en Resumen Ejecutivo, Hallazgos bajo los 4 pilares clasificados por severidad [CRÍTICO/MEDIO/MEJORA] indicando líneas exactas, y Código Refactorizado).
Paso 4: En el chat, NO vuelvas a escribir el informe completo ni el código refactorizado. Solo confirma la ruta del archivo .md creado y muestra un resumen de máximo 5 líneas con el conteo de hallazgos encontrados.''',
    tools=[listar_archivos_proyecto, leer_archivos_en_lote, guardar_reporte_md]
)
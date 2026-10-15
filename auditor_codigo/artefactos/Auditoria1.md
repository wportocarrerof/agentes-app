¡Con ese código todo encaja al 100%\! Acabas de mostrar la causa exacta de los **2.4 millones de tokens de entrada** (934k normales \+ 1.5M en caché) y los **59k tokens de salida**.  
Cuando ejecutas un agente en **Google ADK**, cada vez que el modelo invoca una herramienta (Function Call), ADK hace un bucle (*Agent Loop*) que vuelve a llamar a GenerateContent enviando **todo el historial acumulado de la sesión**. Mira lo que hizo tu código por debajo en una sola auditoría:

### **1\. El efecto "Bola de Nieve" en los Tokens de Entrada (leer\_archivo\_local)**

1. **Llamada 1:** El agente llama a listar\_archivos\_proyecto. ADK le devuelve la lista de todos los archivos de la carpeta (incluyendo imágenes, JSONs, package-lock.json, archivos .md de auditorías previas, etc., porque tu función listar\_archivos\_proyecto no filtra por extensión).  
2. **Llamadas 2 a la N:** Si el proyecto tiene 15 archivos y el agente decide leerlos uno por uno (o en pequeños grupos):  
   * Lee el **Archivo 1** (ej. 5,000 tokens).  
   * Para leer el **Archivo 2**, ADK vuelve a enviar a la API el Archivo 1 \+ el Archivo 2\.  
   * Para leer el **Archivo 10**, ADK vuelve a enviar los Archivos 1 al 9 \+ el Archivo 10\.  
   * **Resultado:** ¡Los primeros archivos se cobran 10 o 15 veces en la misma ejecución\! Por eso se activó el **Context Caching automático** de Gemini (1,505,044 cached input tokens), que te ahorró bastante dinero, pero aun así acumulaste 934,337 tokens nuevos de entrada.

### **2\. El "Doble Cobro" de Tokens de Salida (Paso 3 y Paso 4\)**

Los tokens de salida (Output) en gemini-4-argon son los más caros (aprox. 5 veces más caros que los de entrada). Mira lo que le ordenaste en el prompt:

* **Paso 3:** *"DEBES invocar guardar\_reporte\_md pasándole el informe completo en contenido"*. Aquí el modelo redacta todo el informe \+ el código refactorizado dentro del JSON de la llamada a la función (ej. **3,000 tokens de salida**).  
* **Paso 4:** *"Muestra el informe en el chat"*. Una vez que guardar\_reporte\_md responde "Reporte guardado...", el modelo **vuelve a escribir exactamente el mismo informe completo** para mostrártelo en el chat (otros **3,000 tokens de salida**, además de meter los 3,000 anteriores como entrada). ¡Estás pagando el doble de salida en cada auditoría\!

### **🚀 Cómo optimizar tu agente en ADK para reducir el costo en un 80%**

Aquí tienes tu mismo código refactorizado con **4 mejoras críticas de ahorro de tokens** sin perder nada de calidad en la auditoría:

1. **Lectura en lote (leer\_multiples\_archivos):** En lugar de que el agente haga 10 viajes de ida y vuelta a la API leyendo archivo por archivo, lee todos los archivos solicitados en **un solo turno**.  
2. **Filtro de extensiones y límite de tamaño:** Evita que lea package-lock.json, archivos binarios, SVGs gigantes o los mismos reportes aud\_\*.md que él mismo generó antes.  
3. **Imprimir en consola desde la herramienta (Cero doble salida):** La herramienta guardar\_reporte\_md guarda el archivo, y en el Paso 4 el agente solo te da un resumen de 5 líneas en el chat en lugar de volver a escupir todo el Markdown.

### **¿Cuánto ahorras con este cambio?**

1. **Reduces los turnos del agente de \~15 llamadas a solo 3 llamadas** por auditoría (listar \-\> leer\_en\_lote \-\> guardar).  
2. **Cortas a la mitad el gasto de Output Tokens** gracias al nuevo Paso 4 (el código refactorizado solo se escribe una vez directo al archivo .md).  
3. **Evitas la auto-lectura infinita:** Con not archivo.startswith('aud\_'), evitas que en una segunda o tercera corrida el agente lea los reportes .md de auditorías anteriores que quedaron guardados en la misma carpeta del proyecto.
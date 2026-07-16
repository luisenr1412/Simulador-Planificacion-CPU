"""
Interfaz gráfica del Simulador de Algoritmos de Planificación de CPU.

Fase 3 - Desarrollo de Interfaz y Visualización.
Responsable: Diseñador de Experiencias (Luis Chavero).

Este módulo construye la ventana principal en CustomTkinter e integra:
  - Formulario de entrada manual de procesos (ráfagas y prioridades).
  - Carga de lotes de procesos desde archivos externos (JSON / CSV).
  - Diagrama de Gantt DINÁMICO dibujado sobre un Canvas a partir del historial
    de CPU que emite el motor lógico (src/planificador.py).
  - Tabla de resultados por proceso y promedios de las métricas.
  - Gráfico comparativo de algoritmos con Matplotlib (se actualiza solo,
    cada vez que se corre una simulación, sin necesidad de un botón aparte).

La animación del Gantt se realiza con Canvas.after(), la forma segura de
refrescar la interfaz en Tkinter sin congelarla (evita el "freezing" del Hito 2).
"""

import os
import sys
import csv
from tkinter import Canvas, filedialog

# Permite ejecutar el archivo directamente (python ui/gui_main.py) resolviendo
# la raíz del proyecto para poder importar el paquete src.
RAIZ_PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ_PROYECTO not in sys.path:
    sys.path.insert(0, RAIZ_PROYECTO)

import customtkinter as ctk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from src.modelo import Proceso
from src.planificador import Planificador


# --- Paleta de colores para los procesos (rol de Diseñador de Experiencias) ---
# Colores diferenciados y legibles para identificar cada proceso en el Gantt.
PALETA_PROCESOS = [
    "#4F9DDE", "#E67E5A", "#5FB878", "#B77BD9", "#E6B84F",
    "#4FD9C4", "#DE6F9E", "#8FB84F", "#7A8FE6", "#D95F5F",
]
COLOR_INACTIVO = "#5A5A5A"   # CPU ociosa
COLOR_TEXTO = "#FFFFFF"
COLOR_FONDO_CANVAS = "#242424"
COLOR_EJE = "#9A9A9A"

# Velocidad fija de la animación del Gantt (ms de espera por unidad de tiempo).
VELOCIDAD_ANIMACION_MS = 120

# Algoritmos disponibles: etiqueta visible -> (nombre del método, usa_quantum).
ALGORITMOS = {
    "FCFS (No apropiativo)": ("simular_fcfs", False),
    "SJF / SRTF (Apropiativo)": ("simular_sjf", False),
    "Round Robin": ("simular_rr", True),
    "Prioridades (Apropiativo)": ("simular_prioridades", False),
}


class SimuladorGUI(ctk.CTk):
    """Ventana principal del simulador."""

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Simulador de Planificación de CPU - UCAB")
        self.geometry("1180x760")
        self.minsize(980, 620)

        # --- Estado interno ---
        # Lista editable de procesos: cada uno es un dict con sus atributos.
        self.procesos_editables = []
        self.colores_por_proceso = {}     # id_proceso -> color
        self._animacion_id = None         # id del after() en curso (para cancelar)
        self._historial = []              # línea de tiempo del último cálculo

        # Configuración del grid principal: panel de control + área de pestañas.
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._construir_panel_control()
        self._construir_area_visualizacion()
        self._refrescar_lista_ui()  # muestra "(sin procesos)" al arrancar

        # No se carga ningún lote automáticamente: el usuario debe agregar
        # procesos a mano o cargar un archivo (JSON/CSV) para empezar.
        self._mostrar_mensaje("Agrega procesos manualmente o carga un archivo (JSON/CSV) para comenzar.")

        self._actualizar_estado_quantum()

    # ------------------------------------------------------------------ #
    #  Construcción de la interfaz
    # ------------------------------------------------------------------ #
    def _construir_panel_control(self):
        """Panel izquierdo (scrollable): algoritmo, quantum, editor de procesos."""
        panel = ctk.CTkScrollableFrame(self, width=300, corner_radius=0)
        panel.grid(row=0, column=0, sticky="nsew")

        ctk.CTkLabel(
            panel, text="Simulador de CPU",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(pady=(8, 2), padx=16)
        ctk.CTkLabel(
            panel, text="Planificación de procesos",
            font=ctk.CTkFont(size=12), text_color="#9A9A9A",
        ).pack(pady=(0, 16), padx=16)

        # -- Selección de algoritmo --
        ctk.CTkLabel(panel, text="Algoritmo", anchor="w").pack(fill="x", padx=16, pady=(4, 2))
        self.selector_algoritmo = ctk.CTkOptionMenu(
            panel, values=list(ALGORITMOS.keys()),
            command=lambda _: self._actualizar_estado_quantum(),
        )
        self.selector_algoritmo.pack(fill="x", padx=16, pady=(0, 12))

        # -- Quantum (solo Round Robin) --
        ctk.CTkLabel(panel, text="Quantum (Round Robin)", anchor="w").pack(fill="x", padx=16, pady=(4, 2))
        self.entry_quantum = ctk.CTkEntry(panel, placeholder_text="Ej: 3")
        self.entry_quantum.insert(0, "3")
        self.entry_quantum.pack(fill="x", padx=16, pady=(0, 16))

        # -- Formulario de entrada manual de procesos --
        ctk.CTkLabel(
            panel, text="Agregar proceso",
            font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        ).pack(fill="x", padx=16, pady=(4, 6))

        form = ctk.CTkFrame(panel, fg_color="transparent")
        form.pack(fill="x", padx=16)
        form.grid_columnconfigure((0, 1), weight=1)

        self.entry_id = self._campo_form(form, "ID", 0, 0, "P4")
        self.entry_arribo = self._campo_form(form, "Arribo", 0, 1, "0")
        self.entry_rafaga = self._campo_form(form, "Ráfaga", 1, 0, "5")
        self.entry_prioridad = self._campo_form(form, "Prioridad", 1, 1, "1")

        ctk.CTkButton(
            panel, text="+  Agregar a la lista", command=self._agregar_proceso,
        ).pack(fill="x", padx=16, pady=(10, 6))
        ctk.CTkButton(
            panel, text="Cargar archivo (JSON/CSV)",
            fg_color="transparent", border_width=1, command=self._cargar_archivo,
        ).pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkButton(
            panel, text="Limpiar lista",
            fg_color="transparent", border_width=1, text_color="#E06C6C",
            command=self._limpiar_lista,
        ).pack(fill="x", padx=16, pady=(0, 12))

        # -- Lista de procesos cargados (con botón de eliminar por fila) --
        ctk.CTkLabel(panel, text="Procesos en el lote", anchor="w").pack(fill="x", padx=16, pady=(4, 2))
        self.marco_lista = ctk.CTkFrame(panel)
        self.marco_lista.pack(fill="x", padx=16, pady=(0, 14))

        # -- Botón de acción --
        self.boton_simular = ctk.CTkButton(
            panel, text="▶  Simular", height=42,
            font=ctk.CTkFont(size=15, weight="bold"), command=self._ejecutar_simulacion,
        )
        self.boton_simular.pack(fill="x", padx=16, pady=(6, 6))

        # -- Estado / mensajes --
        self.label_estado = ctk.CTkLabel(
            panel, text="", font=ctk.CTkFont(size=12),
            text_color="#9A9A9A", wraplength=260, justify="left",
        )
        self.label_estado.pack(fill="x", padx=16, pady=(4, 12))

    def _campo_form(self, padre, etiqueta, fila, col, placeholder):
        """Crea un mini-campo etiquetado dentro del formulario de procesos."""
        celda = ctk.CTkFrame(padre, fg_color="transparent")
        celda.grid(row=fila, column=col, sticky="ew", padx=(0, 6), pady=4)
        ctk.CTkLabel(celda, text=etiqueta, font=ctk.CTkFont(size=11),
                     text_color="#9A9A9A", anchor="w").pack(fill="x")
        entry = ctk.CTkEntry(celda, placeholder_text=placeholder, height=30)
        entry.pack(fill="x")
        return entry

    def _construir_area_visualizacion(self):
        """Panel derecho: pestañas de Gantt, Resultados y Comparación."""
        self.tabs = ctk.CTkTabview(self, corner_radius=8)
        self.tabs.grid(row=0, column=1, sticky="nsew", padx=16, pady=16)

        self.tab_gantt = self.tabs.add("Diagrama de Gantt")
        self.tab_resultados = self.tabs.add("Tabla de Resultados")
        self.tab_comparacion = self.tabs.add("Comparación")

        self._construir_tab_gantt()
        self._construir_tab_resultados()
        self._construir_tab_comparacion()

    def _construir_tab_gantt(self):
        tab = self.tab_gantt
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        self.titulo_gantt = ctk.CTkLabel(
            tab, text="Diagrama de Gantt", anchor="w",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self.titulo_gantt.grid(row=0, column=0, sticky="w", pady=(0, 10))

        marco_canvas = ctk.CTkFrame(tab)
        marco_canvas.grid(row=1, column=0, sticky="nsew")
        marco_canvas.grid_columnconfigure(0, weight=1)
        marco_canvas.grid_rowconfigure(0, weight=1)

        self.canvas = Canvas(marco_canvas, bg=COLOR_FONDO_CANVAS,
                             highlightthickness=0, height=200)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        self.scroll_x = ctk.CTkScrollbar(marco_canvas, orientation="horizontal",
                                         command=self.canvas.xview)
        self.scroll_x.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=self.scroll_x.set)

        self.marco_leyenda = ctk.CTkFrame(tab, fg_color="transparent")
        self.marco_leyenda.grid(row=2, column=0, sticky="w", pady=(10, 6))

        self.label_metricas = ctk.CTkLabel(
            tab, text="", font=ctk.CTkFont(size=13), anchor="w", justify="left")
        self.label_metricas.grid(row=3, column=0, sticky="w", pady=(4, 0))

    def _construir_tab_resultados(self):
        tab = self.tab_resultados
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            tab, text="Resultados por proceso", anchor="w",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.tabla_resultados = ctk.CTkScrollableFrame(tab)
        self.tabla_resultados.grid(row=1, column=0, sticky="nsew")

    def _construir_tab_comparacion(self):
        tab = self.tab_comparacion
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            tab, text="Comparación de algoritmos (promedios)", anchor="w",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.marco_grafico = ctk.CTkFrame(tab)
        self.marco_grafico.grid(row=1, column=0, sticky="nsew")
        self.marco_grafico.grid_columnconfigure(0, weight=1)
        self.marco_grafico.grid_rowconfigure(0, weight=1)

        self.info_comparacion = ctk.CTkLabel(
            tab, text="Se actualiza automáticamente al simular.",
            text_color="#9A9A9A")
        self.info_comparacion.grid(row=0, column=0, sticky="e")
        self._canvas_grafico = None  # FigureCanvasTkAgg actual

    # ------------------------------------------------------------------ #
    #  Gestión del lote de procesos
    # ------------------------------------------------------------------ #
    def _actualizar_estado_quantum(self):
        """Habilita el campo de quantum solo cuando el algoritmo es Round Robin."""
        _, usa_quantum = ALGORITMOS[self.selector_algoritmo.get()]
        self.entry_quantum.configure(state="normal" if usa_quantum else "disabled")

    def _agregar_proceso(self):
        """Valida el formulario y agrega un proceso a la lista editable."""
        id_proc = self.entry_id.get().strip()
        if not id_proc:
            self._mostrar_mensaje("El ID del proceso no puede estar vacío.", es_error=True)
            return
        if any(p["id"] == id_proc for p in self.procesos_editables):
            self._mostrar_mensaje(f"Ya existe un proceso con ID '{id_proc}'.", es_error=True)
            return
        try:
            arribo = int(self.entry_arribo.get())
            rafaga = int(self.entry_rafaga.get())
            prioridad = int(self.entry_prioridad.get() or 0)
        except ValueError:
            self._mostrar_mensaje("Arribo, ráfaga y prioridad deben ser números enteros.", es_error=True)
            return
        if rafaga <= 0 or arribo < 0:
            self._mostrar_mensaje("Ráfaga debe ser > 0 y arribo >= 0.", es_error=True)
            return

        self.procesos_editables.append(
            {"id": id_proc, "tiempo_arribo": arribo, "rafaga_cpu": rafaga, "prioridad": prioridad})
        self.entry_id.delete(0, "end")
        self._refrescar_lista_ui()
        self._mostrar_mensaje(f"Proceso '{id_proc}' agregado.")

    def _eliminar_proceso(self, id_proc):
        self.procesos_editables = [p for p in self.procesos_editables if p["id"] != id_proc]
        self._refrescar_lista_ui()

    def _limpiar_lista(self):
        self.procesos_editables = []
        self._refrescar_lista_ui()
        self._mostrar_mensaje("Lista de procesos vaciada.")

    def _refrescar_lista_ui(self):
        """Redibuja la lista de procesos cargados con su botón de eliminar."""
        for hijo in self.marco_lista.winfo_children():
            hijo.destroy()

        if not self.procesos_editables:
            ctk.CTkLabel(self.marco_lista, text="(sin procesos)",
                         text_color="#7A7A7A", font=ctk.CTkFont(size=12)).pack(pady=8)
            return

        for p in self.procesos_editables:
            fila = ctk.CTkFrame(self.marco_lista, fg_color="transparent")
            fila.pack(fill="x", padx=6, pady=2)
            texto = f"{p['id']}  ·  arr {p['tiempo_arribo']}  ·  ráf {p['rafaga_cpu']}  ·  pri {p['prioridad']}"
            ctk.CTkLabel(fila, text=texto, font=ctk.CTkFont(size=12), anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkButton(fila, text="✕", width=26, height=24, fg_color="transparent",
                          text_color="#E06C6C", hover_color="#3A2A2A",
                          command=lambda i=p["id"]: self._eliminar_proceso(i)).pack(side="right")

    def _cargar_archivo(self):
        """Abre un selector de archivos para elegir el lote de procesos (JSON/CSV)."""
        ruta = filedialog.askopenfilename(
            title="Seleccionar lote de procesos",
            initialdir=os.path.join(RAIZ_PROYECTO, "data"),
            filetypes=[("JSON", "*.json"), ("CSV", "*.csv"), ("Todos", "*.*")],
        )
        if ruta:
            self._cargar_desde_archivo(ruta)

    def _cargar_desde_archivo(self, ruta):
        """Carga procesos de un JSON o CSV hacia la lista editable."""
        try:
            planificador = Planificador()
            if ruta.lower().endswith(".csv"):
                with open(ruta, newline="", encoding="utf-8") as archivo:
                    for fila in csv.DictReader(archivo):
                        planificador.lista_procesos.append(Proceso(
                            id_proceso=fila["id"],
                            tiempo_arribo=int(fila["tiempo_arribo"]),
                            rafaga_cpu=int(fila["rafaga_cpu"]),
                            prioridad=int(fila.get("prioridad", 0) or 0)))
            else:
                planificador.cargar_procesos(ruta)
        except (OSError, ValueError, KeyError) as error:
            self._mostrar_mensaje(f"Error al cargar el archivo: {error}", es_error=True)
            return

        self.procesos_editables = [
            {"id": p.id, "tiempo_arribo": p.tiempo_arribo,
             "rafaga_cpu": p.rafaga_cpu, "prioridad": p.prioridad}
            for p in planificador.lista_procesos]
        self._refrescar_lista_ui()
        self._mostrar_mensaje(f"Cargados {len(self.procesos_editables)} procesos de "
                              f"{os.path.basename(ruta)}.")

    def _construir_planificador(self):
        """Crea un Planificador nuevo con los procesos de la lista editable."""
        planificador = Planificador()
        for p in self.procesos_editables:
            planificador.lista_procesos.append(Proceso(
                id_proceso=p["id"], tiempo_arribo=p["tiempo_arribo"],
                rafaga_cpu=p["rafaga_cpu"], prioridad=p["prioridad"]))
        return planificador

    def _leer_quantum(self):
        """Devuelve el quantum validado, o None si es inválido."""
        try:
            quantum = int(self.entry_quantum.get())
            if quantum <= 0:
                raise ValueError
            return quantum
        except ValueError:
            self._mostrar_mensaje("El quantum debe ser un entero mayor que 0.", es_error=True)
            return None

    def _correr_algoritmo(self, planificador, etiqueta):
        """Ejecuta el método de Planificador correspondiente a la etiqueta."""
        nombre_metodo, usa_quantum = ALGORITMOS[etiqueta]
        metodo = getattr(planificador, nombre_metodo)
        if usa_quantum:
            quantum = self._leer_quantum()
            if quantum is None:
                return False
            metodo(quantum=quantum)
        else:
            metodo()
        return True

    # ------------------------------------------------------------------ #
    #  Simulación individual + Gantt
    # ------------------------------------------------------------------ #
    def _ejecutar_simulacion(self):
        """Ejecuta el algoritmo elegido, lanza la animación del Gantt y
        actualiza de una vez la comparación entre los 4 algoritmos."""
        if self._animacion_id is not None:
            self.canvas.after_cancel(self._animacion_id)
            self._animacion_id = None

        if not self.procesos_editables:
            self._mostrar_mensaje("Agrega o carga al menos un proceso.", es_error=True)
            return

        planificador = self._construir_planificador()
        etiqueta = self.selector_algoritmo.get()
        if not self._correr_algoritmo(planificador, etiqueta):
            return

        self._historial = list(planificador.historial_cpu)
        self._asignar_colores(planificador.lista_procesos)
        self.titulo_gantt.configure(text=f"Diagrama de Gantt  —  {etiqueta}")
        self._dibujar_leyenda(planificador.lista_procesos)
        self._mostrar_metricas(planificador.procesos_terminados)
        self._llenar_tabla_resultados(planificador.procesos_terminados)
        self.tabs.set("Diagrama de Gantt")
        self._animar_gantt()

        self._actualizar_comparacion()

    def _asignar_colores(self, procesos):
        """Asigna un color estable de la paleta a cada proceso."""
        self.colores_por_proceso = {
            proceso.id: PALETA_PROCESOS[i % len(PALETA_PROCESOS)]
            for i, proceso in enumerate(procesos)}

    def _animar_gantt(self):
        """Dibuja la línea de tiempo unidad por unidad para dar el efecto dinámico."""
        self.canvas.delete("all")

        ancho_celda, alto_barra = 42, 70
        margen_x, margen_y = 20, 40
        total = len(self._historial)
        ancho_total = margen_x * 2 + total * ancho_celda
        self.canvas.configure(scrollregion=(0, 0, max(ancho_total, 600), margen_y + alto_barra + 60))

        self.canvas.create_text(margen_x, margen_y + alto_barra / 2, text="CPU",
                                fill=COLOR_EJE, anchor="e", font=("Helvetica", 12, "bold"))

        def dibujar_celda(indice):
            if indice >= total:
                self._animacion_id = None
                return
            etiqueta = self._historial[indice]
            x0 = margen_x + indice * ancho_celda
            x1 = x0 + ancho_celda
            y0, y1 = margen_y, margen_y + alto_barra

            if etiqueta == "Inactivo":
                color, texto = COLOR_INACTIVO, "—"
            else:
                color, texto = self.colores_por_proceso.get(etiqueta, "#888888"), str(etiqueta)

            self.canvas.create_rectangle(x0, y0, x1, y1, fill=color,
                                         outline=COLOR_FONDO_CANVAS, width=2)
            self.canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=texto,
                                    fill=COLOR_TEXTO, font=("Helvetica", 13, "bold"))
            self.canvas.create_text(x0, y1 + 12, text=str(indice), fill=COLOR_EJE,
                                    font=("Helvetica", 10))
            if indice == total - 1:
                self.canvas.create_text(x1, y1 + 12, text=str(total), fill=COLOR_EJE,
                                        font=("Helvetica", 10))

            if x1 > self.canvas.winfo_width():
                self.canvas.xview_moveto(max(0.0, (x1 - self.canvas.winfo_width()) / ancho_total))

            self._animacion_id = self.canvas.after(VELOCIDAD_ANIMACION_MS,
                                                   dibujar_celda, indice + 1)

        dibujar_celda(0)

    def _dibujar_leyenda(self, procesos):
        """Muestra un chip de color por proceso debajo del Gantt."""
        for hijo in self.marco_leyenda.winfo_children():
            hijo.destroy()
        for proceso in procesos:
            color = self.colores_por_proceso.get(proceso.id, "#888888")
            chip = ctk.CTkFrame(self.marco_leyenda, fg_color="transparent")
            chip.pack(side="left", padx=(0, 14))
            ctk.CTkLabel(chip, text="  ", fg_color=color, corner_radius=4, width=18).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(chip, text=f"{proceso.id} (ráfaga {proceso.rafaga_cpu})",
                         font=ctk.CTkFont(size=12)).pack(side="left")

    def _mostrar_metricas(self, terminados):
        """Muestra los promedios de espera, retorno y respuesta bajo el Gantt."""
        prom = self._promedios(terminados)
        if prom is None:
            self.label_metricas.configure(text="")
            return
        self.label_metricas.configure(
            text=(f"Promedios  →  Espera: {prom['espera']:.2f}    "
                  f"Retorno: {prom['retorno']:.2f}    Respuesta: {prom['respuesta']:.2f}"))

    @staticmethod
    def _promedios(terminados):
        """Calcula el promedio de espera, retorno y respuesta (o None si vacío)."""
        if not terminados:
            return None
        n = len(terminados)
        return {
            "espera": sum(p.tiempo_espera for p in terminados) / n,
            "retorno": sum(p.tiempo_retorno for p in terminados) / n,
            "respuesta": sum(p.tiempo_respuesta for p in terminados) / n,
        }

    # ------------------------------------------------------------------ #
    #  Tabla de resultados por proceso
    # ------------------------------------------------------------------ #
    def _llenar_tabla_resultados(self, terminados):
        """Rellena la tabla de la pestaña Resultados con las métricas por proceso."""
        for hijo in self.tabla_resultados.winfo_children():
            hijo.destroy()

        columnas = ["Proceso", "Arribo", "Ráfaga", "Prioridad",
                    "Fin", "Retorno", "Espera", "Respuesta"]
        for col, texto in enumerate(columnas):
            self.tabla_resultados.grid_columnconfigure(col, weight=1)
            ctk.CTkLabel(self.tabla_resultados, text=texto,
                         font=ctk.CTkFont(size=13, weight="bold")).grid(
                row=0, column=col, padx=6, pady=(4, 8), sticky="w")

        for fila, p in enumerate(sorted(terminados, key=lambda x: str(x.id)), start=1):
            valores = [p.id, p.tiempo_arribo, p.rafaga_cpu, p.prioridad,
                       p.tiempo_finalizacion, p.tiempo_retorno, p.tiempo_espera, p.tiempo_respuesta]
            for col, valor in enumerate(valores):
                ctk.CTkLabel(self.tabla_resultados, text=str(valor),
                             font=ctk.CTkFont(size=12)).grid(
                    row=fila, column=col, padx=6, pady=3, sticky="w")

    # ------------------------------------------------------------------ #
    #  Comparación de algoritmos (Matplotlib) — automática, sin botón
    # ------------------------------------------------------------------ #
    def _actualizar_comparacion(self):
        """Corre los 4 algoritmos sobre el lote actual y refresca el gráfico
        de la pestaña Comparación. Se llama sola: al arrancar (con el lote
        inicial) y cada vez que se pulsa Simular."""
        if not self.procesos_editables:
            return

        quantum = None
        etiquetas, esperas, retornos, respuestas = [], [], [], []
        for etiqueta, (nombre_metodo, usa_quantum) in ALGORITMOS.items():
            planificador = self._construir_planificador()
            metodo = getattr(planificador, nombre_metodo)
            if usa_quantum:
                quantum = self._leer_quantum()
                if quantum is None:
                    return
                metodo(quantum=quantum)
            else:
                metodo()
            prom = self._promedios(planificador.procesos_terminados)
            etiquetas.append(etiqueta.split(" (")[0].split(" / ")[0])
            esperas.append(prom["espera"])
            retornos.append(prom["retorno"])
            respuestas.append(prom["respuesta"])

        self._dibujar_grafico_comparativo(etiquetas, esperas, retornos, respuestas)

    def _dibujar_grafico_comparativo(self, etiquetas, esperas, retornos, respuestas):
        """Dibuja un gráfico de barras agrupadas con los promedios por algoritmo."""
        if self._canvas_grafico is not None:
            self._canvas_grafico.get_tk_widget().destroy()

        fig = Figure(figsize=(7, 4.2), dpi=100)
        fig.patch.set_facecolor("#2B2B2B")
        ax = fig.add_subplot(111)
        ax.set_facecolor("#2B2B2B")

        posiciones = range(len(etiquetas))
        ancho = 0.26
        ax.bar([x - ancho for x in posiciones], esperas, ancho, label="Espera", color="#4F9DDE")
        ax.bar(list(posiciones), retornos, ancho, label="Retorno", color="#E67E5A")
        ax.bar([x + ancho for x in posiciones], respuestas, ancho, label="Respuesta", color="#5FB878")

        ax.set_ylabel("Tiempo promedio (ms)", color="#DDDDDD")
        ax.set_title("Promedios de métricas por algoritmo", color="#FFFFFF")
        ax.set_xticks(list(posiciones))
        ax.set_xticklabels(etiquetas, color="#DDDDDD", fontsize=9)
        ax.tick_params(colors="#DDDDDD")
        for lado in ax.spines.values():
            lado.set_color("#555555")
        ax.legend(facecolor="#3A3A3A", edgecolor="#555555", labelcolor="#DDDDDD")
        ax.grid(axis="y", color="#3F3F3F", linestyle="--", linewidth=0.6)
        fig.tight_layout()

        self._canvas_grafico = FigureCanvasTkAgg(fig, master=self.marco_grafico)
        self._canvas_grafico.draw()
        self._canvas_grafico.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.info_comparacion.configure(text="")

    # ------------------------------------------------------------------ #
    #  Utilidades
    # ------------------------------------------------------------------ #
    def _mostrar_mensaje(self, texto, es_error=False):
        self.label_estado.configure(text=texto, text_color="#E06C6C" if es_error else "#9A9A9A")


def main():
    app = SimuladorGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
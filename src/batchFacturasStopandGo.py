import os
import pandas as pd
import logging
import traceback
from datetime import datetime, date

from mail.envioMail import enviarMailLog


class FacturasStopAndGo:

    def __init__(self, ruta_base: str):
        self.ruta = ruta_base
        self._configurar_logging()

    # ============================================================
    # LOGGING
    # ============================================================
    def _configurar_logging(self):
        try:
            log_dir = os.path.join(self.ruta, "Log")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "batchFacturasStopAndGo.log")

            root = logging.getLogger()
            if not root.handlers:
                logging.basicConfig(
                    level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s",
                    handlers=[
                        logging.FileHandler(log_file, encoding="utf-8"),
                        logging.StreamHandler()
                    ]
                )

            logging.info("✅ Logging configurado en: %s", log_file)
            print(f"✅ Logging configurado en: {log_file}")

        except Exception:
            print("⚠️ No se pudo configurar el logging. Se seguirá sin log a fichero.")

    # ============================================================
    # UTILIDADES
    # ============================================================
    def _to_str(self, x):
        try:
            if pd.isna(x):
                return ""
        except Exception:
            pass
        return "" if x is None else str(x)

    def _clean_codigo(self, raw):
        s = self._to_str(raw).strip()
        if s.endswith(".0"):
            s = s[:-2]
        return s

    def _norm_float(self, raw):
        if raw is None:
            return 0.0
        try:
            if isinstance(raw, (int, float)):
                return float(raw)
        except Exception:
            pass

        s = self._to_str(raw).strip()
        if s == "":
            return 0.0

        s = s.replace("€", "").replace(" ", "")

        if ("," in s) and ("." in s):
            s_norm = s.replace(".", "").replace(",", ".")
        elif ("," in s) and ("." not in s):
            s_norm = s.replace(",", ".")
        else:
            s_norm = s

        try:
            return float(s_norm)
        except Exception:
            return 0.0

    def _norm(self, raw, forzar_negativo=False):
        val = raw if isinstance(raw, (int, float)) else self._norm_float(raw)
        if forzar_negativo and val > 0:
            val = -val
        return f"{val:.2f}".replace(".", ",")

    def _norm_fecha(self, raw):
        if raw is None:
            return ""

        try:
            if isinstance(raw, (pd.Timestamp, datetime, date)):
                if pd.isna(raw):
                    return ""
                return raw.strftime("%d/%m/%Y")
        except Exception:
            pass

        s = self._to_str(raw).strip()
        if s == "":
            return ""

        s = s.split(" ")[0]

        if "." in s and s.count(".") >= 2:
            dd, mm, yy = s.split(".")[0].zfill(2), s.split(".")[1].zfill(2), s.split(".")[2][:4]
            return f"{dd}/{mm}/{yy}"

        if "/" in s and s.count("/") >= 2:
            dd, mm, yy = s.split("/")[0].zfill(2), s.split("/")[1].zfill(2), s.split("/")[2][:4]
            return f"{dd}/{mm}/{yy}"

        if "-" in s and s.count("-") >= 2:
            yy, mm, dd = s.split("-")[0][:4], s.split("-")[1].zfill(2), s.split("-")[2].zfill(2)
            return f"{dd}/{mm}/{yy}"

        return s

    def _resolver_salida_dir(self):
        cand1 = os.path.join(self.ruta, "Contabilidad")
        cand2 = os.path.join(self.ruta, "Contabilidad Mes Actual")
        if os.path.isdir(cand1):
            return cand1
        if os.path.isdir(cand2):
            return cand2
        return self.ruta

    # ============================================================
    # CUENTAS ESTACIONES
    # ============================================================
    def leer_cuentas_estaciones(self):
        try:
            archivo = os.path.join(self.ruta, "Excel Auxiliares", "CuentasEstaciones.xlsx")
            print(f"📌 Leyendo cuentas estaciones: {archivo}")
            logging.info("[Stop&Go] Leyendo cuentas estaciones: %s", archivo)

            if not os.path.isfile(archivo):
                msg = f"❌ No existe CuentasEstaciones.xlsx: {archivo}"
                print(msg)
                logging.error(msg)
                return {}

            df = pd.read_excel(archivo, dtype=str, engine="openpyxl").fillna("")
            df.columns = df.columns.str.strip()

            if not {"Estacion", "Cuenta"}.issubset(set(df.columns)):
                msg = f"❌ Columnas inválidas en CuentasEstaciones.xlsx. Detectadas: {df.columns.tolist()}"
                print(msg)
                logging.error(msg)
                return {}

            dic = {}
            for _, fila in df.iterrows():
                estacion = self._clean_codigo(fila.get("Estacion", ""))
                cuenta = self._clean_codigo(fila.get("Cuenta", ""))
                if estacion:
                    dic[estacion] = cuenta

            print(f"✅ Cuentas estaciones cargadas: {len(dic)}")
            logging.info("[Stop&Go] Cuentas estaciones cargadas: %d", len(dic))
            if dic:
                print("   Ejemplo (5 primeras):", list(dic.items())[:5])

            return dic

        except Exception:
            err = traceback.format_exc()
            print("❌ Error leyendo CuentasEstaciones.xlsx. Revisa el log.")
            logging.error("[Stop&Go] Error leer_cuentas_estaciones:\n%s", err)
            enviarMailLog("david.casalsuarez@galuresa.com", "[Stop&Go] Error leer cuentas estaciones:\n" + err)
            return {}

    # ============================================================
    # BUSCAR EXCEL FACTURAS STOP&GO
    # ============================================================
    def _buscar_excel_facturas(self):
        carpeta = os.path.join(self.ruta, "Excel Facturas Stop & Go")
        if not os.path.isdir(carpeta):
            return None

        excels = []
        for f in os.listdir(carpeta):
            if f.lower().endswith((".xlsx", ".xls")) and not f.startswith("~$"):
                excels.append(os.path.join(carpeta, f))

        if not excels:
            return None

        excels.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return excels[0]

    # ============================================================
    # MAPEADO DE COLUMNAS (CLAVE PARA TU EXCEL)
    # ============================================================
    def _normalizar_columnas_stopgo(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Tu Excel trae:
          Fecha, Nfactura, Vencimiento, Concepto, Estacion, Base, Iva, TotalFactura
        Lo convertimos internamente a:
          FechaFactura, Nfactura, Vencimiento, Estacion, BaseImponible, Iva, TotalFactura, Concepto
        """
        rename_map = {
            "Fecha": "FechaFactura",
            "Base": "BaseImponible",
            # el resto coinciden ya:
            # "Nfactura": "Nfactura",
            # "Vencimiento": "Vencimiento",
            # "Estacion": "Estacion",
            # "Iva": "Iva",
            # "TotalFactura": "TotalFactura",
            # "Concepto": "Concepto"
        }

        df = df.copy()
        df.columns = df.columns.str.strip()
        df.rename(columns=rename_map, inplace=True)
        return df

    # ============================================================
    # PROCESO PRINCIPAL
    # ============================================================
    def generarExtraFacturasStopAndGo(self):
        try:
            print("\n==================== INICIO STOP&GO ====================")
            logging.info("[Stop&Go] INICIO generarExtraFacturasStopAndGo")

            print(f"📌 Ruta base: {self.ruta}")
            print("📌 Auxiliares en: Excel Auxiliares/")
            print("📌 Salida en: Contabilidad/ (si existe)")

            dic_cuentas = self.leer_cuentas_estaciones()
            if not dic_cuentas:
                print("⚠️ Aviso: No se cargaron cuentas de estaciones. Bases irán como 'Cuenta no encontrada'.")

            excel_facturas = self._buscar_excel_facturas()
            if not excel_facturas:
                msg = "❌ No se encontró ningún Excel dentro de 'Excel Facturas Stop & Go'."
                print(msg)
                logging.error(msg)
                return

            print(f"📄 Excel detectado: {excel_facturas}")
            logging.info("[Stop&Go] Excel detectado: %s", excel_facturas)

            pf = pd.read_excel(excel_facturas, dtype=str, engine="openpyxl").fillna("")
            pf.columns = pf.columns.str.strip()

            # ✅ Normalizamos columnas según tu Excel
            pf = self._normalizar_columnas_stopgo(pf)

            print(f"✅ Filas leídas del Excel: {len(pf)}")
            logging.info("[Stop&Go] Filas leídas: %d", len(pf))

            columnas = set(pf.columns.tolist())
            minimas = {"FechaFactura", "Nfactura", "BaseImponible", "Iva", "TotalFactura", "Estacion"}
            if not minimas.issubset(columnas):
                msg = f"❌ Tras normalizar, siguen faltando columnas mínimas. Detectadas: {pf.columns.tolist()}"
                print(msg)
                logging.error(msg)
                return

            # ================== CONSTANTES según tus CSV ==================
            proveedor_nombre = "REPSOL CIAL. P.P., S.A"
            proveedor_cuenta = "41000001"
            proveedor_cif = "A80298839"
            cuenta_iva_21 = "47200021"
            cuenta_banco = "57200052"
            # =============================================================

            lista_extra = []
            facturas_unicas_iva = {}

            # Contadores
            omitidas_vacias = 0
            sin_vencimiento = 0
            con_pago = 0
            sin_cuenta_estacion = 0
            duplicadas_iva = 0
            facturas_validas = 0

            contador_asiento = 0

            for _, factura in pf.iterrows():
                estacion = self._clean_codigo(factura.get("Estacion", ""))
                numFactura = self._clean_codigo(factura.get("Nfactura", ""))

                fecha_emision = self._norm_fecha(factura.get("FechaFactura", ""))
                fecha_vencimiento = self._norm_fecha(factura.get("Vencimiento", ""))

                base = self._norm_float(factura.get("BaseImponible", ""))
                iva = self._norm_float(factura.get("Iva", ""))
                total = self._norm_float(factura.get("TotalFactura", ""))

                if base == 0 and iva == 0 and total == 0:
                    omitidas_vacias += 1
                    continue

                if total == 0 and (base != 0 or iva != 0):
                    total = base + iva
                    logging.info("[Stop&Go] TotalFactura vacío en %s -> calculado %.2f", numFactura, total)

                cuenta_estacion = dic_cuentas.get(estacion, "")
                if cuenta_estacion == "":
                    sin_cuenta_estacion += 1
                    cuenta_estacion = "Cuenta no encontrada"
                    logging.warning("[Stop&Go] Estación sin cuenta: estacion=%s | factura=%s", estacion, numFactura)

                base_str = self._norm(base)
                iva_str = self._norm(iva)
                total_str_pos = self._norm(total)
                total_str_neg = self._norm(total, forzar_negativo=True)

                # ✅ FACTURA (orden igual a tu EXTRA)
                contador_asiento += 1
                desc_factura = f"Fra. {numFactura}, {proveedor_nombre}".strip()

                # Proveedor (Haber 2)
                lista_extra.append([
                    fecha_emision, proveedor_cuenta, str(numFactura), "", "0", contador_asiento,
                    desc_factura, "2", total_str_neg,
                    "", "", "", "", "", "0", "10"
                ])

                # Base (Debe 1)
                if base != 0:
                    lista_extra.append([
                        fecha_emision, cuenta_estacion, str(numFactura), "", "0", contador_asiento,
                        desc_factura, "1", base_str,
                        "", "", "", "", "", "0", "10"
                    ])

                # IVA (Debe 1)
                if iva != 0:
                    lista_extra.append([
                        fecha_emision, cuenta_iva_21, str(numFactura), "", "0", contador_asiento,
                        desc_factura, "1", iva_str,
                        "", "", "", "", "", "0", "10"
                    ])

                if numFactura in facturas_unicas_iva:
                    duplicadas_iva += 1
                    logging.warning("[Stop&Go] Nfactura duplicada para IVA (se sobrescribe): %s", numFactura)

                facturas_unicas_iva[numFactura] = factura
                facturas_validas += 1

                # ✅ PAGO (orden igual a tu EXTRA)
                if fecha_vencimiento != "":
                    contador_asiento += 1
                    desc_pago = f"PAGO FRA. REPSOL {numFactura}".strip()

                    # Proveedor (Debe 1)
                    lista_extra.append([
                        fecha_vencimiento, proveedor_cuenta, "", "", "0", contador_asiento,
                        desc_pago, "1", total_str_pos,
                        "", "", "", "", "", "0", "0"
                    ])

                    # Banco (Haber 2)
                    lista_extra.append([
                        fecha_vencimiento, cuenta_banco, "", "", "0", contador_asiento,
                        desc_pago, "2", total_str_neg,
                        "", "", "", "", "", "0", "0"
                    ])

                    con_pago += 1
                else:
                    sin_vencimiento += 1
                    logging.info("[Stop&Go] Factura sin vencimiento: %s", numFactura)

            if not lista_extra:
                print("⚠️ No se generó ninguna línea para EXTRA01.csv.")
                logging.warning("[Stop&Go] lista_extra vacía, no se exporta.")
                return

            out_dir = self._resolver_salida_dir()
            out_extra = os.path.join(out_dir, "EXTRA01.csv")

            print(f"\n📤 Exportando EXTRA01.csv a: {out_extra}")
            logging.info("[Stop&Go] Exportando EXTRA01.csv a: %s", out_extra)

            pd.DataFrame(lista_extra).to_csv(out_extra, index=False, header=False, sep=";")
            print(f"✅ EXTRA01.csv generado. Líneas: {len(lista_extra)}")

            # IVA
            self._generar_iva(facturas_unicas_iva, proveedor_nombre, proveedor_cif, proveedor_cuenta)

            # Resumen
            print("\n------------------ RESUMEN STOP&GO ------------------")
            print(f"✅ Facturas válidas procesadas: {facturas_validas}")
            print(f"💳 Facturas con pago: {con_pago}")
            print(f"⏳ Facturas sin vencimiento: {sin_vencimiento}")
            print(f"⚠️ Facturas sin cuenta estación: {sin_cuenta_estacion}")
            print(f"🧹 Omitidas por importes vacíos: {omitidas_vacias}")
            print(f"⚠️ Duplicadas Nfactura IVA (sobrescribe): {duplicadas_iva}")
            print(f"📦 Líneas EXTRA01.csv: {len(lista_extra)}")
            print("-----------------------------------------------------")
            print("✅ STOP&GO finalizado.\n")

            logging.info("[Stop&Go] FIN generarExtraFacturasStopAndGo OK")

        except Exception:
            err = traceback.format_exc()
            logging.error("[Stop&Go] Error en proceso principal:\n%s", err)
            enviarMailLog("david.casalsuarez@galuresa.com", "[Stop&Go] Error batch:\n" + err)
            print("❌ Error STOP&GO. Revisa el log.")

    # ============================================================
    # IVA
    # ============================================================
    def _generar_iva(self, facturas_unicas, proveedor_nombre, proveedor_cif, proveedor_cuenta):
        try:
            print("\n📌 Generando IVA0101.csv...")
            logging.info("[Stop&Go] Iniciando IVA0101")

            lista_iva = []
            omitidas_vacias = 0

            for factura in facturas_unicas.values():
                numFactura = self._clean_codigo(factura.get("Nfactura", ""))
                fecha = self._norm_fecha(factura.get("FechaFactura", factura.get("Fecha", "")))

                base = self._norm_float(factura.get("BaseImponible", factura.get("Base", "")))
                iva = self._norm_float(factura.get("Iva", ""))
                total = self._norm_float(factura.get("TotalFactura", ""))

                if base == 0 and iva == 0 and total == 0:
                    omitidas_vacias += 1
                    continue

                if total == 0 and (base != 0 or iva != 0):
                    total = base + iva

                base_str = self._norm(base)
                iva_str = self._norm(iva)
                total_str = self._norm(total)

                lista_iva.append([
                    proveedor_cuenta, proveedor_nombre, proveedor_cif,
                    str(numFactura), base_str, "", "", "-2",
                    "47200021", "S", fecha, "",
                    "21", "0",
                    total_str, iva_str, "0", "283",
                    fecha, "0", "1", "0", "", fecha, "0"
                ])

            if not lista_iva:
                print("⚠️ No se generó IVA0101.csv (lista vacía).")
                logging.warning("[Stop&Go] lista_iva vacía, no se exporta.")
                return

            out_dir = self._resolver_salida_dir()
            out_iva = os.path.join(out_dir, "IVA0101.csv")

            print(f"📤 Exportando IVA0101.csv a: {out_iva}")
            logging.info("[Stop&Go] Exportando IVA0101.csv a: %s", out_iva)

            pd.DataFrame(lista_iva).to_csv(out_iva, sep=";", index=False, header=False)
            print(f"✅ IVA0101.csv generado. Líneas: {len(lista_iva)}")
            print(f"ℹ️ IVA omitidas por importes vacíos: {omitidas_vacias}")

            logging.info("[Stop&Go] FIN IVA0101 OK - lineas=%d omitidas=%d", len(lista_iva), omitidas_vacias)

        except Exception:
            err = traceback.format_exc()
            logging.error("[Stop&Go] Error generando IVA:\n%s", err)
            enviarMailLog("david.casalsuarez@galuresa.com", "[Stop&Go] Error IVA:\n" + err)
            print("❌ Error generando IVA0101.csv. Revisa el log.")

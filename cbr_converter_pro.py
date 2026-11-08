import tkinter as tk
from tkinter import ttk, messagebox
import requests
import xml.etree.ElementTree as ET
import sqlite3
import os
from datetime import datetime, date

# URL официального XML-фида ЦБ РФ
CBR_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
CACHE_DB = "cbr_cache.db"


# ============================================================
# 1. Функции для работы с кэшем (SQLite)
# ============================================================
def init_cache_db():
    """Создаёт таблицу кэша, если её нет."""
    conn = sqlite3.connect(CACHE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rate_cache (
            date_key TEXT PRIMARY KEY,
            xml_content BLOB NOT NULL,
            fetched_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def get_cached_xml(date_key):
    """Возвращает сохранённый XML для указанной даты (или None)."""
    if not os.path.exists(CACHE_DB):
        return None
    conn = sqlite3.connect(CACHE_DB)
    cursor = conn.execute(
        "SELECT xml_content FROM rate_cache WHERE date_key = ?",
        (date_key,)
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def save_xml_to_cache(date_key, xml_bytes):
    """Сохраняет XML в кэш для указанной даты."""
    conn = sqlite3.connect(CACHE_DB)
    conn.execute(
        "INSERT OR REPLACE INTO rate_cache (date_key, xml_content, fetched_at) VALUES (?, ?, ?)",
        (date_key, xml_bytes, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


# ============================================================
# 2. Парсинг XML ЦБ РФ (вынесен отдельно для тестов)
# ============================================================
def parse_cbr_xml(xml_bytes):
    """
    Принимает bytes XML от ЦБ РФ, возвращает словарь:
    { 'USD': {'name': 'Доллар США', 'rate': 92.5}, ... }
    Курс приведён к 1 единице валюты (номинал учтён).
    """
    root = ET.fromstring(xml_bytes)
    rates = {}
    for valute in root.findall("Valute"):
        char_code = valute.find("CharCode").text
        name = valute.find("Name").text
        nominal = int(valute.find("Nominal").text)
        value = float(valute.find("Value").text.replace(",", "."))
        rates[char_code] = {
            "name": name,
            "rate": value / nominal,
        }
    return rates


def fetch_cbr_xml(date_req=None):
    """
    Запрашивает XML с сайта ЦБ РФ.
    date_req: строка 'DD/MM/YYYY' или None (тогда — последняя дата).
    Возвращает (xml_bytes, дата_из_атрибута_или_None).
    """
    params = {}
    if date_req:
        params["date_req"] = date_req

    try:
        response = requests.get(CBR_URL, params=params, timeout=15)
        response.raise_for_status()
        xml_bytes = response.content
    except requests.RequestException as e:
        raise RuntimeError(f"Ошибка запроса к ЦБ РФ: {e}")

    # Пытаемся вытащить дату из атрибута Date
    try:
        root = ET.fromstring(xml_bytes)
        xml_date = root.attrib.get("Date")
    except ET.ParseError:
        xml_date = None

    return xml_bytes, xml_date


def get_rates(date_req=None):
    """
    Основная функция получения курсов.
    Если date_req указан — проверяет кэш, при отсутствии качает и сохраняет.
    Если date_req не указан (сегодня) — всегда пытается скачать свежие,
    но при ошибке сети падает обратно на кэш за сегодня.
    """
    init_cache_db()

    # Определяем ключ кэша
    if date_req:
        # Пользователь указал конкретную дату — используем её как ключ
        cache_key = date_req
    else:
        # Сегодня — ключ по текущей дате в формате ЦБ
        cache_key = date.today().strftime("%d/%m/%Y")

    # Сначала пробуем кэш (для указанной даты — всегда, для сегодня — только если сеть упадёт)
    cached_xml = get_cached_xml(cache_key)
    if cached_xml and date_req:
        # Для конкретной даты кэш — основной источник
        try:
            return parse_cbr_xml(cached_xml), cache_key
        except ET.ParseError:
            pass  # битый кэш — перекачаем

    # Пытаемся скачать
    try:
        xml_bytes, xml_date = fetch_cbr_xml(date_req)
        # Сохраняем в кэш (ключ — либо запрошенная дата, либо сегодня)
        save_xml_to_cache(cache_key, xml_bytes)
        return parse_cbr_xml(xml_bytes), xml_date or cache_key
    except RuntimeError as e:
        # Сеть не работает — если есть кэш, используем его
        if cached_xml:
            return parse_cbr_xml(cached_xml), cache_key
        raise e


# ============================================================
# GUI
# ============================================================
class CBRConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Конвертер валют ЦБ РФ")
        self.root.geometry("540x480")
        self.root.resizable(False, False)

        self.rates = {}
        self.currency_codes = []
        self.current_date_key = None

        self.build_ui()
        self.load_rates()

    def build_ui(self):
        # --- Выбор даты ---
        frame_date = tk.Frame(self.root)
        frame_date.pack(pady=10, padx=20, fill="x")

        tk.Label(frame_date, text="Дата курса (ДД/ММ/ГГГГ):", font=("Arial", 11)).pack(side="left")
        self.date_entry = tk.Entry(frame_date, font=("Arial", 11), width=12, justify="center")
        self.date_entry.pack(side="left", padx=5)
        # По умолчанию — сегодня
        self.date_entry.insert(0, date.today().strftime("%d/%m/%Y"))

        tk.Button(
            frame_date, text="Загрузить", font=("Arial", 10),
            command=self.load_rates
        ).pack(side="left", padx=5)

        # --- Сумма ---
        frame_amount = tk.Frame(self.root)
        frame_amount.pack(pady=10, padx=20, fill="x")
        tk.Label(frame_amount, text="Сумма:", font=("Arial", 12)).pack(side="left")
        self.amount_entry = tk.Entry(frame_amount, font=("Arial", 14), width=20, justify="right")
        self.amount_entry.pack(side="right")
        self.amount_entry.insert(0, "1000")

        # --- Выбор валют ---
        frame_cur = tk.Frame(self.root)
        frame_cur.pack(pady=10, padx=20, fill="x")

        left = tk.Frame(frame_cur); left.pack(side="left", expand=True, fill="x")
        tk.Label(left, text="Из валюты:", font=("Arial", 11)).pack(anchor="w")
        self.from_combo = ttk.Combobox(left, state="readonly", font=("Arial", 11))
        self.from_combo.pack(fill="x", pady=5)
        self.from_combo.set("RUB")

        right = tk.Frame(frame_cur); right.pack(side="right", expand=True, fill="x", padx=(10, 0))
        tk.Label(right, text="В валюту:", font=("Arial", 11)).pack(anchor="w")
        self.to_combo = ttk.Combobox(right, state="readonly", font=("Arial", 11))
        self.to_combo.pack(fill="x", pady=5)
        self.to_combo.set("USD")

        # --- Кнопка ---
        self.convert_btn = tk.Button(
            self.root, text="Конвертировать", font=("Arial", 13),
            command=self.convert, bg="#4CAF50", fg="white", height=2
        )
        self.convert_btn.pack(pady=15, padx=20, fill="x")

        # --- Результат ---
        self.result_label = tk.Label(self.root, text="", font=("Arial", 16, "bold"), fg="#333")
        self.result_label.pack(pady=5)
        self.rate_label = tk.Label(self.root, text="", font=("Arial", 10), fg="#666")
        self.rate_label.pack(pady=2)

        # --- Статус ---
        self.status_label = tk.Label(self.root, text="", font=("Arial", 9), fg="#999")
        self.status_label.pack(side="bottom", pady=10)

    def load_rates(self):
        """Загружает курсы на выбранную дату (с кэшем)."""
        date_req = self.date_entry.get().strip() or None
        # Валидация формата (простая)
        if date_req:
            try:
                datetime.strptime(date_req, "%d/%m/%Y")
            except ValueError:
                messagebox.showwarning("Ошибка", "Введите дату в формате ДД/ММ/ГГГГ")
                return

        self.status_label.config(text="Загрузка…")
        self.root.update()

        try:
            rates, actual_date = get_rates(date_req)
        except RuntimeError as e:
            self.status_label.config(text="Ошибка загрузки")
            messagebox.showerror("Ошибка", str(e))
            return

        self.rates = rates
        self.current_date_key = actual_date
        self.currency_codes = sorted(rates.keys())
        self.currency_codes.insert(0, "RUB")

        self.from_combo["values"] = self.currency_codes
        self.to_combo["values"] = self.currency_codes
        if "USD" in self.currency_codes:
            self.to_combo.set("USD")
        self.from_combo.set("RUB")

        self.status_label.config(
            text=f"Загружено. Дата: {actual_date or 'сегодня'}. Валют: {len(self.currency_codes)}"
        )

    def convert(self):
        if not self.rates:
            messagebox.showwarning("Нет данных", "Сначала загрузите курсы.")
            return

        from_cur = self.from_combo.get()
        to_cur = self.to_combo.get()

        try:
            amount = float(self.amount_entry.get().replace(",", ".").strip())
            if amount < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Ошибка", "Введите корректную положительную сумму.")
            return

        def rate_to_rub(code):
            if code == "RUB":
                return 1.0
            return self.rates[code]["rate"]

        try:
            rate_from = rate_to_rub(from_cur)
            rate_to = rate_to_rub(to_cur)
            result = amount * rate_from / rate_to
        except KeyError as e:
            messagebox.showerror("Ошибка", f"Валюта не найдена: {e}")
            return

        def fmt(n):
            if n == int(n):
                return f"{int(n):,}".replace(",", " ")
            return f"{n:,.4f}".replace(",", " ").rstrip("0").rstrip(".")

        self.result_label.config(text=f"{fmt(amount)} {from_cur} = {fmt(result)} {to_cur}")

        if from_cur == "RUB":
            rate_text = f"1 {to_cur} = {rate_to:.4f} RUB"
        elif to_cur == "RUB":
            rate_text = f"1 {from_cur} = {rate_from:.4f} RUB"
        else:
            rate_text = f"1 {from_cur} = {rate_from:.4f} RUB  |  1 {to_cur} = {rate_to:.4f} RUB"

        self.rate_label.config(text=rate_text)


if __name__ == "__main__":
    root = tk.Tk()
    app = CBRConverterApp(root)
    root.mainloop()
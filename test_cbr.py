import unittest
import os
import sqlite3
import tempfile
import xml.etree.ElementTree as ET

# Импортируем функции из основного модуля
from cbr_converter_pro import (
    parse_cbr_xml,
    init_cache_db,
    get_cached_xml,
    save_xml_to_cache,
    CACHE_DB,
)

# Образец XML, имитирующий ответ ЦБ РФ (минимальный набор)
SAMPLE_XML = """<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="27.10.2026" name="Foreign Currency Market">
    <Valute ID="R01235">
        <NumCode>840</NumCode>
        <CharCode>USD</CharCode>
        <Nominal>1</Nominal>
        <Name>Доллар США</Name>
        <Value>92,5000</Value>
    </Valute>
    <Valute ID="R01239">
        <NumCode>978</NumCode>
        <CharCode>EUR</CharCode>
        <Nominal>1</Nominal>
        <Name>Евро</Name>
        <Value>100,2500</Value>
    </Valute>
    <Valute ID="R01375">
        <NumCode>392</NumCode>
        <CharCode>JPY</CharCode>
        <Nominal>100</Nominal>
        <Name>Японских иен</Name>
        <Value>61,5000</Value>
    </Valute>
</ValCurs>""".encode("windows-1251")


class TestParseCBRXML(unittest.TestCase):
    """Тесты парсинга XML ЦБ РФ (без сети)."""

    def test_parse_returns_dict(self):
        rates = parse_cbr_xml(SAMPLE_XML)
        self.assertIsInstance(rates, dict)

    def test_usd_rate(self):
        rates = parse_cbr_xml(SAMPLE_XML)
        self.assertIn("USD", rates)
        self.assertAlmostEqual(rates["USD"]["rate"], 92.5, places=4)
        self.assertEqual(rates["USD"]["name"], "Доллар США")

    def test_eur_rate(self):
        rates = parse_cbr_xml(SAMPLE_XML)
        self.assertAlmostEqual(rates["EUR"]["rate"], 100.25, places=4)

    def test_jpy_nominal_division(self):
        """JPY имеет номинал 100, курс должен быть приведён к 1 иене."""
        rates = parse_cbr_xml(SAMPLE_XML)
        # 61.5 / 100 = 0.615
        self.assertAlmostEqual(rates["JPY"]["rate"], 0.615, places=4)

    def test_all_currencies_present(self):
        rates = parse_cbr_xml(SAMPLE_XML)
        self.assertEqual(set(rates.keys()), {"USD", "EUR", "JPY"})

    def test_comma_replaced_with_dot(self):
        """В XML ЦБ запятая как десятичный разделитель — парсер должен её заменить."""
        rates = parse_cbr_xml(SAMPLE_XML)
        # Если бы запятая не заменилась, float() упал бы с ValueError
        self.assertIsInstance(rates["USD"]["rate"], float)

    def test_broken_xml_raises(self):
        with self.assertRaises(ET.ParseError):
            parse_cbr_xml(b"<broken>")


class TestCacheFunctions(unittest.TestCase):
    """Тесты кэша SQLite (с временной базой, чтобы не трогать рабочую)."""

    def setUp(self):
        # Подменяем путь к БД на временный файл
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.original_db = CACHE_DB
        # Переопределяем константу в модуле (для теста)
        import cbr_converter_pro
        cbr_converter_pro.CACHE_DB = self.temp_db.name
        # Переимпортируем, чтобы функции видели новую константу
        global init_cache_db, get_cached_xml, save_xml_to_cache
        from cbr_converter_pro import init_cache_db as ic, get_cached_xml as gc, save_xml_to_cache as sc
        init_cache_db = ic
        get_cached_xml = gc
        save_xml_to_cache = sc
        init_cache_db()

    def tearDown(self):
        os.unlink(self.temp_db.name)
        # Возвращаем исходную константу
        import cbr_converter_pro
        cbr_converter_pro.CACHE_DB = self.original_db

    def test_save_and_get(self):
        save_xml_to_cache("27/10/2026", SAMPLE_XML)
        cached = get_cached_xml("27/10/2026")
        self.assertEqual(cached, SAMPLE_XML)

    def test_get_missing_returns_none(self):
        cached = get_cached_xml("01/01/1990")
        self.assertIsNone(cached)

    def test_overwrite_cache(self):
        save_xml_to_cache("27/10/2026", b"<old>")
        save_xml_to_cache("27/10/2026", b"<new>")
        cached = get_cached_xml("27/10/2026")
        self.assertEqual(cached, b"<new>")


if __name__ == "__main__":
    unittest.main(verbosity=2)
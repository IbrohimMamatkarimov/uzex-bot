"""Builds the analytical views (deals_full etc.) over the slim parquet files."""
COMMODITIES = {  # HS code -> (Russian, Uzbek)
 '100199': ('Пшеница', 'Bug‘doy'), '100630': ('Рис', 'Guruch'), '110100': ('Мука пшеничная', 'Bug‘doy uni'),
 '151219': ('Подсолнечное масло', 'Kungaboqar yog‘i'), '151229': ('Хлопковое масло', 'Paxta yog‘i'),
 '170199': ('Сахар', 'Shakar'), '220190': ('Питьевая вода', 'Ichimlik suvi'),
 '230610': ('Шрот хлопковый', 'Paxta shroti'), '230990': ('Комбикорм / кормосмесь', 'Omixta yem / em-xashak aralashmasi'),
 '250100': ('Соль пищевая', 'Osh tuzi'), '252020': ('Гипс строительный', 'Qurilish gipsi'),
 '252210': ('Известь', 'Ohak'), '252329': ('Портландцемент', 'Portlandsement'),
 '271012': ('Бензин автомобильный', 'Avtomobil benzini'), '271112': ('Сжиженный газ', 'Suyultirilgan gaz'),
 '271320': ('Битум нефтяной', 'Neft bitumi'), '280421': ('Аргон', 'Argon'), '280430': ('Азот', 'Azot'),
 '280700': ('Серная кислота', 'Sulfat kislota'), '281511': ('Каустическая сода', 'Kaustik soda'),
 '310210': ('Карбамид (мочевина)', 'Karbamid (mochevina)'), '310230': ('Аммиачная селитра', 'Ammiakli selitra'),
 '320810': ('Эмаль', 'Emal'), '390120': ('Полиэтилен', 'Polietilen'), '390210': ('Полипропилен', 'Polipropilen'),
 '390410': ('Поливинилхлорид (ПВХ)', 'Polivinilxlorid (PVX)'), '391721': ('Трубы полиэтиленовые', 'Polietilen quvurlar'),
 '440711': ('Пиломатериалы', 'Yog‘och taxta (pilomaterial)'), '520100': ('Хлопок-сырец', 'Paxta xomashyosi (paxta-xom)'),
 '520512': ('Пряжа хлопчатобумажная', 'Paxta ipi'), '690410': ('Кирпич керамический', 'Sopol g‘isht'),
 '700529': ('Стекло листовое (флоат)', 'Tekis oyna (flout)'), '720853': ('Лист стальной горячекатаный', 'Issiq prokat po‘lat list'),
 '721420': ('Арматура стальная', 'Armatura'), '721710': ('Проволока арматурная', 'Armatura simi'),
 '740311': ('Катод медный', 'Mis katod'), '760421': ('Профиль алюминиевый', 'Alyuminiy profil'),
 '848210': ('Подшипники', 'Podshipnik'), '854449': ('Кабель силовой', 'Kuch kabeli'),
}
REGIONS = {  # Uzbek (as in deals) -> Russian
 'Toshkent shahri': 'г. Ташкент', 'Toshkent viloyati': 'Ташкентская область', 'Namangan viloyati': 'Наманганская область',
 'Buxoro viloyati': 'Бухарская область', 'Samarqand viloyati': 'Самаркандская область', 'Sirdaryo viloyati': 'Сырдарьинская область',
 'Qashqadaryo viloyati': 'Кашкадарьинская область', 'Xorazm viloyati': 'Хорезмская область', 'Andijon viloyati': 'Андижанская область',
 'Farg‘ona viloyati': 'Ферганская область', 'Surxondaryo viloyati': 'Сурхандарьинская область', 'Navoiy viloyati': 'Навоийская область',
 'Qoraqalpog‘iston Respublikasi': 'Республика Каракалпакстан', 'Jizzax viloyati': 'Джизакская область',
}

def setup(con, data_dir):
    for t in ("deals", "contracts", "participants", "brokers", "usd_rates"):
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{data_dir}/{t}.parquet')")
    con.execute("CREATE TABLE _comm(hs_code VARCHAR, commodity VARCHAR, commodity_uz VARCHAR)")
    con.executemany("INSERT INTO _comm VALUES (?,?,?)", [(k, v[0], v[1]) for k, v in COMMODITIES.items()])
    con.execute("CREATE TABLE _reg(region VARCHAR, region_ru VARCHAR)")
    con.executemany("INSERT INTO _reg VALUES (?,?)", list(REGIONS.items()))
    con.execute("""CREATE VIEW deals_full AS
SELECT
  d.deal_id, d.deal_date,
  year(d.deal_date) AS year, month(d.deal_date) AS month, quarter(d.deal_date) AS quarter,
  d.deal_time, d.auction_type, d.contract_type, d.contract_form, d.status,
  (d.status = 'Аннулирован(Не оплачен)') AS is_cancelled,
  d.contract_id, d.product_name,
  c.hs_code,
  CASE WHEN c.hs_code='271019' AND lower(c.product) LIKE '%мазут%' THEN 'Мазут топочный'
       WHEN c.hs_code='271019' THEN 'Дизельное топливо' ELSE m.commodity END AS commodity,
  CASE WHEN c.hs_code='271019' AND lower(c.product) LIKE '%мазут%' THEN 'Mazut'
       WHEN c.hs_code='271019' THEN 'Dizel yoqilg‘isi' ELSE m.commodity_uz END AS commodity_uz,
  c.category, c.product_group, c.industry,
  d.unit, d.lot_size, d.quantity_lots,
  d.quantity_lots * d.lot_size AS volume_units,
  CASE d.unit WHEN 'тонна' THEN d.quantity_lots*d.lot_size
              WHEN 'килограмм' THEN d.quantity_lots*d.lot_size/1000.0 END AS volume_tonnes,
  c.currency, d.amount AS amount_contract_ccy, d.start_price AS start_price_contract_ccy,
  CASE WHEN c.currency='Доллар США' THEN d.amount * r.uzs_per_usd ELSE d.amount END AS amount_uzs,
  CASE WHEN c.currency='Доллар США' THEN d.amount ELSE d.amount / r.uzs_per_usd END AS amount_usd,
  r.uzs_per_usd AS usd_rate_on_deal_date,
  d.amount / NULLIF(d.quantity_lots*d.lot_size,0) AS unit_price_contract_ccy,
  CASE WHEN c.currency='Доллар США' THEN d.amount * r.uzs_per_usd ELSE d.amount END
       / NULLIF(d.quantity_lots*d.lot_size,0) AS unit_price_uzs,
  d.region, rg.region_ru,
  c.delivery_basis, c.packaging, c.deposit_pct, c.payment_term_days, c.delivery_term_days, c.base_price,
  d.seller_inn, sp.name AS seller_name, sp.region AS seller_region, sp.activity AS seller_activity,
  d.buyer_inn,  bp.name AS buyer_name,  bp.region AS buyer_region,  bp.activity AS buyer_activity,
  d.seller_broker, sb.name AS seller_broker_name, d.buyer_broker, bb.name AS buyer_broker_name,
  d.payment_date, d.delivery_date, d.delivered_lots,
  date_diff('day', d.deal_date, d.payment_date) AS days_to_pay,
  date_diff('day', d.payment_date, d.delivery_date) AS days_to_deliver,
  d.delivered_lots / NULLIF(d.quantity_lots,0) AS delivered_share
FROM deals d
JOIN contracts c USING (contract_id)
LEFT JOIN _comm m ON m.hs_code = c.hs_code
LEFT JOIN _reg rg ON rg.region = d.region
LEFT JOIN usd_rates r ON r.rate_date = d.deal_date
LEFT JOIN participants sp ON sp.inn = d.seller_inn
LEFT JOIN participants bp ON bp.inn = d.buyer_inn
LEFT JOIN brokers sb ON sb.broker_code = d.seller_broker
LEFT JOIN brokers bb ON bb.broker_code = d.buyer_broker
""")

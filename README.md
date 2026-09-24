# niim-agent — Tasarım ve Uygulama Belgesi

> Buluttaki bir veya daha fazla projeden etiket işi çekip Bluetooth ile Niimbot
> yazıcıya basan, Windows ve macOS'ta arka planda çalışan ara yazılım.

| | |
|---|---|
| Durum | Taslak — uygulamaya hazır |
| Tarih | 2026-09-24 |
| Kaynak | `atlantis-envanter/printagent/` (commit `5568bf4`) — orada çalışan agent'ın bağımsız, çok platformlu hâli |
| Donanımda doğrulanan | Niimbot D110_M, firmware 301 (protokol v4), macOS, bleak 3.0.2 |

---

## 0. Bu belge nasıl kullanılır

- Belge kendi başına yeter; `atlantis-envanter` reposuna erişim gerekmez. Gereken
  protokol ayrıntıları, bayt dizileri ve donanımda doğrulanmış değerler burada.
- **§5 (Yazıcı protokolü) donanımda doğrulandı.** Oradaki sabitleri, bayt
  düzenlerini ve komut sırasını "iyileştirmek" için değiştirmeyin; değişiklik
  gerekiyorsa önce donanımda deneyin. Bu yazıcılar yanlış diziye de "başarılı"
  cevabı verip boş etiket basıyor (§5.11).
- İş sırası §13'teki kilometre taşlarıdır; her birinin kabul ölçütü var.
- Verilmiş kararlar metinde **Karar:** diye geçer; açık olanlar §15'te.

---

## 1. Amaç ve kapsam

**Amaç:** Yazıcının yanındaki bir Windows ya da Mac bilgisayarda sürekli çalışan,
bir veya daha fazla bulut projesinin yazdırma kuyruğunu yoklayan ve gelen
etiketleri BLE ile Niimbot yazıcıya basan tek bir program.

**Kapsam içi**
- Birden fazla bulut kaynağı (her biri §4'teki sözleşmeyi uygulayan bir sunucu)
- Terminalde ön planda çalışma ve oturum açılınca arka planda başlama (macOS, Windows)
- Yardımcı komutlar: tarama, yazıcı bilgisi, deneme baskısı, dosyadan baskı, durum
- Kurulabilir paketler (Windows `.exe`, macOS `.app`)

**Kapsam dışı**
- Etiket tasarımı. Görseli sunucu üretir, agent yalnızca PNG basar (§2, ilke 2).
- Bir agent'ın birden fazla yazıcıyı yönetmesi. Her yazıcı için ayrı agent (ayrı makine).
- Grafik arayüz. Sistem tepsisi simgesi isteğe bağlı (M6).
- Linux: bleak desteklediği için büyük olasılıkla çalışır ama hedef değil; servis kurulumu yok.

**Yazıcılar:** NiimPrintX'in bildiği modeller (§6.1). Donanımda doğrulanan yalnızca D110_M.

---

## 2. Mimari

```
 Bulut kaynakları (§4 sözleşmesi)             niim-agent (Win / Mac)                          Yazıcı
┌──────────────────────┐                     ┌─────────────────────────────────────────┐
│ Atlantis Envanter    │◄── claim/result ────┤ worker: yazıcı boşken sıradaki           │
│ Başka proje A        │◄── claim/result ────┤         kaynaktan 1 iş ister, basar      ├── BLE ──► Niimbot
│ Başka proje B        │◄── heartbeat ───────┤ heartbeat: 60 sn'de bir durum            │
└──────────────────────┘      (HTTPS)        │ PrinterSession: tek bağlantı, tek kilit  │
                                             │ yerel API 127.0.0.1 (M6, isteğe bağlı)   │
                                             └─────────────────────────────────────────┘
```

**İlkeler**

1. **Bağlantıyı hep agent başlatır (pull).** Agent NAT ya da güvenlik duvarı
   arkasında olabilir; sunucunun agent'a ulaşması gerekmez. Port yönlendirme,
   tünel, sabit IP yok. Makine uykudan kalkınca agent kaldığı yerden devam eder.
2. **Etiket tasarımı sunucuda.** Agent tasarımı bilmez: PNG ve birkaç baskı
   parametresi alır. Tasarım değişince agent güncellenmez; tüm istasyonlar aynı
   çıktıyı verir.
3. **Yazıcı boşken iş iste, her seferinde 1 iş.** Bir etiketin BLE ile
   gönderilip basılması ~8 sn sürüyor (§5.12). Sunucu, alınıp 180 sn içinde
   sonucu bildirilmeyen işi kuyruğa geri koyuyor. 5 iş birden alınırsa sonuncusu
   bu sınıra yaklaşır. O sırada aynı kaynağa başka bir claim gelirse (başka bir
   agent, ya da çok kaynaklı agent'ın kendisi) sunucu işi başkasına verir ve
   etiket iki kez basılır. Yalnızca basılabilecek anda iş istemek bu sorunu
   ortadan kaldırır. Claim isteğinin maliyeti (~0.2 sn) baskı süresinin yanında önemsiz.
4. **Yazıcıya tek kapı.** Niimbot aynı anda tek BLE bağlantısı kabul eder ve
   komut–cevap eşlemesi sıralıdır. Yazıcıya her erişim (baskı, heartbeat, bilgi)
   tek bir `asyncio.Lock` üzerinden geçer.
5. **Kaynaklar birbirinden yalıtık.** Bir kaynağın çökmesi, yanlış jetonu ya da
   yavaşlığı diğerlerini etkilemez; her kaynağın kendi geri çekilme (backoff) durumu var.

Tek süreç, tek asyncio olay döngüsü. Eşzamanlı görevler: `worker`, `heartbeat`,
(M6'da) `local_api`. Boşta bağlantı kapatma worker döngüsünün içinde yapılır.

---

## 3. Proje yapısı

```
niim-agent/
├── pyproject.toml
├── LICENSE                    # GPL-3.0 (§11.2)
├── README.md                  # kurulum ve kullanım (M5)
├── SPEC.md                    # bu belge
├── src/niim_agent/
│   ├── __init__.py            # __version__ (tek kaynak)
│   ├── __main__.py            # python -m niim_agent
│   ├── cli.py                 # alt komutlar (§9)
│   ├── config.py              # TOML okuma, doğrulama, varsayılanlar (§8)
│   ├── paths.py               # platformdirs: config / log / state dizinleri
│   ├── logs.py                # logging kurulumu (dosya + konsol)
│   ├── state.py               # state.json, tek örnek kilidi (§7.4, §9)
│   ├── agent.py               # worker, heartbeat, iç gözetmen, kapanış (§7)
│   ├── sources.py             # CloudSource: claim / result / heartbeat, backoff (§4)
│   ├── imaging.py             # prepare_image, deneme etiketi (§6)
│   ├── printer/
│   │   ├── __init__.py
│   │   ├── models.py          # model tablosu (§6.1)
│   │   ├── packet.py          # paket çerçevesi (§5.1)
│   │   ├── transport.py       # bleak sarmalayıcı (§5.2)
│   │   ├── discovery.py       # find_printer (§5.3)
│   │   ├── client.py          # komutlar, sürüm tespiti, v1 / v4 baskı (§5.4–5.10)
│   │   └── session.py         # PrinterSession: bağlantı ömrü, kilit, pil kontrolü (§7.2)
│   ├── localapi.py            # M6
│   └── service/
│       ├── __init__.py        # platforma göre install / uninstall / status
│       ├── macos.py           # launchd LaunchAgent (§10.1)
│       └── windows.py         # HKCU Run (§10.2)
├── packaging/
│   ├── niim-agent.spec        # PyInstaller (§11.3)
│   └── macos-info-plist.json  # ek Info.plist anahtarları
└── tests/
    ├── fakes.py               # FakeTransport, sahte bulut sunucusu
    ├── test_packet.py
    ├── test_imaging.py
    ├── test_client.py         # sürüm tespiti, v1 / v4 dizileri
    ├── test_sources.py
    └── test_config.py
```

**Kurallar:** Python 3.12+, `src/` düzeni, tanımlayıcılar İngilizce, kullanıcıya
görünen mesajlar ve loglar Türkçe. Biçim ve lint: `ruff`.

---

## 4. Bulut sözleşmesi — Print Agent Protokolü v1

Bu sözleşmeyi uygulayan her sunucu agent'a iş gönderebilir. Referans uygulama:
Atlantis Envanter'in `labels` uygulaması (§14).

### 4.0 Genel

- Her kaynağın bir **kök adresi** var, örn. `https://envanter.ornek.com/etiket/api`.
  Uçlar bunun altında ve **sonda `/` ile** çağrılır: Django'nun `APPEND_SLASH`
  özelliği POST isteklerini yönlendiremez.
- Tüm istekler `POST`, gövde JSON, taşıma HTTPS.
- Başlıklar:
  ```
  X-Agent-Token: <kaynağa özel jeton>
  Content-Type: application/json
  User-Agent: niim-agent/<sürüm>
  X-Agent-Protocol: 1
  ```
- İstek zaman aşımı 30 sn (long-poll açıksa `wait + 10` sn).

### 4.1 `POST {kök}/claim/` — iş al

İstek:
```json
{"agent": "ofis-mac", "max": 1, "wait": 0}
```

| Alan | Tip | Açıklama |
|---|---|---|
| `agent` | string ≤ 60 | Agent adı; sunucu işin kimde olduğunu kaydeder |
| `max` | int | En fazla kaç iş. Agent her zaman `1` gönderir (§2, ilke 3). Sunucu 1–20 aralığına sıkıştırır |
| `wait` | int, isteğe bağlı | Long-poll: iş yoksa sunucu en fazla bu kadar sn bekler, iş gelirse hemen döner. Desteklemeyen sunucu alanı yok sayıp hemen döner (M6) |

Cevap `200`:
```json
{"jobs": [{
  "id": 42,
  "claim_token": "3f2a9c…",
  "png_b64": "iVBORw0KGgo…",
  "copies": 1,
  "density": 3,
  "rotate": 270,
  "title": "PC #12",
  "width": 320,
  "height": 96,
  "printer_model": "d110",
  "preset": "40x12"
}]}
```

| Alan | Zorunlu | Açıklama |
|---|---|---|
| `id` | ✔ | Kaynak içinde tekil iş kimliği (int ya da string) |
| `claim_token` | ✔ | Sunucunun bu alım için ürettiği jeton; sonuç bildirilirken geri gönderilir |
| `png_b64` | ✔ | Etiket görseli, base64 PNG. Yatay çizilmiş; siyah = basılacak nokta (§4.6) |
| `copies` | – (1) | Kopya sayısı. Görsel bir kez gönderilir, çoğaltmayı yazıcı yapar |
| `density` | – (3) | 1–5; agent model sınırına kırpar (§6.1) |
| `rotate` | – (270) | Saat yönünde derece (0 / 90 / 180 / 270). D110 için doğru değer 270 |
| `title` | – | Yalnızca log için |
| `width`, `height`, `printer_model`, `preset` | – | Bilgi amaçlı; agent kullanmaz. Agent her zaman kendi yapılandırmasındaki modele basar |

İş yoksa `{"jobs": []}`.

**Sunucunun yükümlülükleri**
- Dağıtım **atomik** olmalı; iki agent aynı işi alamaz. Atlantis'te seçilen
  kimlikler tek bir `UPDATE … SET status='claimed', claim_token=<yeni> WHERE id IN (…) AND status='pending'`
  ile devredilir, ardından o jetonla seçilip döndürülür.
- Alınıp `claim_timeout` (Atlantis: 180 sn) içinde sonucu gelmeyen iş kuyruğa
  döner; deneme hakkı bittiyse `failed` olur. Atlantis bu kontrolü her claim
  isteğinin başında yapar.
- Her alım işin deneme sayacını 1 artırır.

### 4.2 `POST {kök}/jobs/{id}/result/` — sonuç bildir

```json
{"claim_token": "3f2a9c…", "status": "done", "error": ""}
```

`status`: `done` | `failed`. `failed` ise `error` insanın okuyacağı Türkçe bir
mesajdır (≤ 2000 karakter).

Cevap `200`: `{"id": 42, "status": "done"}`. Bu, sunucunun işe verdiği yeni
durumdur. `failed` bildirilse bile deneme hakkı kaldıysa `pending` dönebilir.

Sunucu `claim_token` değerini sabit zamanlı karşılaştırır; tutmazsa `409` döner
(iş başka bir agent'a geçmiş ya da iptal edilmiş).

### 4.3 `POST {kök}/heartbeat/` — durum bildir

```json
{"agent": "ofis-mac", "printer_connected": true, "printer_name": "D110_M",
 "battery": "3", "version": "0.1.0", "note": ""}
```

`battery`: 0–4 ölçeğinde, string; bilinmiyorsa `""`. `note`: son hata gibi kısa
bir durum notu (≤ 300 karakter).

Cevap `200`: `{"ok": true, "pending": 3, "server_time": "2026-09-24T10:00:00+00:00"}`.
`pending` ve `server_time` isteğe bağlıdır; agent yalnızca loglar. Atlantis, son
heartbeat'ten sonraki 90 sn boyunca agent'ı çevrimiçi sayar.

### 4.4 Hata kodları ve agent'ın tepkisi

| Durum | Anlamı | Agent ne yapar |
|---|---|---|
| `403` | Jeton yanlış | ERROR logu, kaynağı 5 dk beklet, heartbeat notuna yaz. Diğer kaynaklar devam eder |
| `404` (result) | İş silinmiş | WARNING logu, sonucu bırak |
| `409` (result) | İş artık bu agent'ta değil | WARNING logu, sonucu bırak (tekrar deneme yok) |
| `503` | Sunucuda agent erişimi kapalı (jeton tanımsız) | Kaynağı 5 dk beklet |
| Diğer `4xx` | İstemci hatası | ERROR logu, kaynağı 1 dk beklet |
| `5xx`, ağ hatası, zaman aşımı | Geçici | Üstel geri çekilme: 3 → 6 → 12 → … en fazla 60 sn. İlk başarılı istekte sıfırla |

Sonuç bildirimi ağ hatasıyla başarısız olursa 3 kez daha denenir (2, 5, 10 sn
arayla); yine olmazsa bırakılır. Sunucu işi zaman aşımıyla kuyruğa geri koyar,
yani etiket bir kez daha basılabilir. Bu bilinçli bir tercih: kaybolan etiket
yerine fazladan etiket.

### 4.5 Güvenlik

- Jeton kaynak başına ayrıdır. Sunucu sabit zamanlı karşılaştırma yapar (`hmac.compare_digest`).
- Sunucuda jeton tanımlı değilse uçlar `503` döner; yanlışlıkla kimliksiz açık kalmaz.
- Agent `http://` kök adresini yalnızca `localhost` / `127.0.0.1` için kabul eder;
  diğerlerinde başlangıçta yapılandırma hatası verir. Böylece jeton düz metin gitmez.

### 4.6 Başka projeler için: etiket görseli üretme kuralları

D110'da doğrulandı; yeni bir sunucu entegrasyonu yazarken bunlara uyun:

- Çözünürlük 203 dpi (8 px/mm): `px = round(mm * 203 / 25.4)`.
- Görsel **yatay** çizilir: etiketin uzun kenarı genişliktir. Agent `rotate` kadar döndürür.
- Mod `L` ya da `1`, beyaz zemin, siyah = basılır. Gri pikseller agent'ta
  Floyd–Steinberg ile noktalara çevrilir (Pillow'da `convert("1")` varsayılanı).
- Kenarlarda en az **1.2 mm** pay bırakın. D110 en uçtaki pikselleri basmıyor.
- Döndürmeden sonra genişlik, yani etiketin dar kenarı, model sınırını geçemez:
  D110 için 240 px = 30 mm.
- **QR:** 40×12 mm etikette QR'a ~10.5 mm kalıyor. Kısa ve TAMAMEN BÜYÜK HARFLİ
  içerik (örn. `HTTPS://ALAN.ADI/E/12-34`) QR'ı alfanümerik kipe sokar: sürüm 2,
  modül ~0.375 mm, telefonla rahat okunur. 57 karakterlik karışık harfli bir URL
  sürüm 4'e çıkıp modülü 0.25 mm'ye düşürüyor ve güvenilir okunmuyor. QR'ı tam
  katlarla ve `NEAREST` ile büyütün.

D110 etiket boyutları (Atlantis ön ayarları):

| Etiket | Yatay çizim | Yazıcıya giden (270° döndürülmüş) |
|---|---|---|
| 40×12 mm | 320×96 px | 96×320 px |
| 30×15 mm | 240×120 px | 120×240 px |
| 50×14 mm | 400×112 px | 112×400 px |
| 75×12 mm | 600×96 px | 96×600 px |
| 109×12.5 mm | 871×100 px | 100×871 px |

---

## 5. Yazıcı protokolü (Niimbot BLE)

Kaynak: [labbots/NiimPrintX](https://github.com/labbots/NiimPrintX) `NiimPrintX/nimmy/`
(GPL-3.0) ve atlantis-envanter'de donanım üzerinde bulunan düzeltmeler. §11.2'ye
göre bu kod projeye alınır ve düzeltmeler doğrudan içine işlenir (monkeypatch yok).

### 5.1 Paket çerçevesi

```
55 55 | type (1) | len (1) | data (len bayt) | checksum (1) | AA AA
checksum = type XOR len XOR data[0] XOR … XOR data[len-1]
```

**Tek istisna:** `CONNECT` (0xC1) paketinin başına fazladan bir `0x03` baytı
eklenir: `03 55 55 C1 01 01 C1 AA AA`. Cevap paketleri normal çerçevededir.
Çözerken başlangıç/bitiş işaretleri ve checksum doğrulanır.

### 5.2 BLE katmanı

- **Kütüphane:** `bleak` (Windows: WinRT, macOS: CoreBluetooth, Linux: BlueZ).
  Doğrulanan sürüm 3.0.2; kodu `bleak>=1.0` davranışına göre yazın.
- **Bağlantı kontrolü:** bleak ≥ 1.0'da `BleakClient.connect()` `None` döner.
  "Bağlandı mı" kararı yalnızca `client.is_connected` ile verilir. NiimPrintX
  dönüş değerine baktığı için bağlantıyı başarısız sayıyor ve karakteristik
  aramasını atlıyordu.
- **Karakteristik bulma:** Tam olarak **bir** karakteristiği olan ve o
  karakteristiğin özellikleri `read`, `write-without-response` ve `notify`
  içeren servisi seç. Bu karakteristik hem yazma hem bildirim için kullanılır.
  Bulunamazsa `PrinterError("Bluetooth karakteristiği bulunamadı")`.
- **Komut–cevap:** `start_notify` → paketi yaz → ilk bildirimi bekle (10 sn) →
  `stop_notify` → cevabı çöz. NiimPrintX böyle yapıyor ve donanımda çalışıyor;
  M1'de aynen koruyun. Bildirimi bağlantı başına bir kez açmak sonraya bırakılabilecek bir iyileştirme.
- **Cevapsız yazma** (`write_no_notify`): Paketi yaz, bildirim bekleme. Yem
  paketler (§5.8) böyle, **yanıtlı** ATT yazmasıyla gönderilir.
- **Görsel satırları** ATT onayı beklenmeden (write-without-response) ve aralarında
  10 ms beklemeyle yazılır. Yanıtlı yazmada her satır bir bağlantı aralığı bekliyor
  (320 satır ~19 sn); yanıtsız ~3.6 sn. D110_M'de donanımda doğrulandı
  (2026-09-25). Beklemesiz gönderim doğrulanmadı: macOS kuyruğu dolunca paket
  atabilir.
- **Zaman aşımı:** NiimPrintX zaman aşımında `None` döndürüyor ve çağıranı
  `NoneType` hatasıyla çökertiyor. Yeni kodda `send_command` zaman aşımında
  `PrinterTimeout` fırlatır. `None`'a dayanıklı olması gereken yerler (sürüm
  tespiti §5.6, baskı durumu §5.10) bu istisnayı yakalar.
- **Log:** Komut kodunu enum adıyla loglamayın. NiimPrintX `RequestCodeEnum(code).name`
  kullanıyor ve enum'da olmayan kodda `ValueError` fırlatıyor. f-string erken
  değerlendiği için bu, log kapalıyken bile oluyor. Tüm kodlar §5.4'teki enum'da
  bulunsun; logda `0x{code:02X}` kullanın.
- Yazıcı aynı anda tek cihaza bağlanır. Niimbot telefon uygulaması açıksa agent bağlanamaz.

### 5.3 Yazıcıyı bulma

- **Filtre:** Cihaz adı (`device.name`, yoksa `adv.local_name`) model önekiyle
  başlamalı (büyük/küçük harf duyarsız; örn. `d110` → `D110_M…`) **ve**
  reklamdaki `service_uuids` listesi boş olmalı. Niimbot birden fazla reklam
  yayınlıyor; baskı servisini taşıyan, UUID listesi boş olanıdır.
- `BleakScanner.find_device_by_filter(filtre, timeout=8)` kullan. İlk eşleşmede
  döner; yakındaki yazıcıda bu 1 sn'nin altında. `discover()` ise eşleşme bulsa
  da süreyi sonuna kadar bekler.
- **Yavaş yol:** Bulunamazsa `discover(timeout=8, return_adv=True)` ile tam tara.
  Adı tutan bir cihaz varsa (UUID listesi dolu olsa bile) onu döndür. Yoksa
  görülen cihaz adlarını içeren bir `PrinterNotFound` fırlat.
- Yapılandırmada `printer.address` doluysa tarama atlanır ve doğrudan o adrese
  bağlanılır. **Adres platforma özel:** Windows ve Linux'ta MAC adresi, macOS'ta
  CoreBluetooth'un verdiği UUID.
- ⚠ **Windows'ta denenmedi.** WinRT reklam ile tarama cevabını birleştirebilir.
  O durumda UUID filtresi hiç tutmaz ve her ilk bağlantı yavaş yoldan (~16 sn)
  geçer. M1'de Windows'ta `scan` çıktısıyla kontrol edin; gerekirse Windows'ta
  yalnızca ada göre filtreleyin.

### 5.4 Komut kodları

| Ad | Kod | Gönderilen veri |
|---|---|---|
| `START_PRINT` | 0x01 | v1: `01`; v4: 9 bayt (§5.8) |
| `START_PAGE_PRINT` | 0x03 | `01` (yalnız v1) |
| `SET_DIMENSION` | 0x13 | v1: 4 bayt; v4: 13 bayt |
| `SET_QUANTITY` | 0x15 | `>H` adet (yalnız v1) |
| `GET_RFID` | 0x1A | `01` |
| `ALLOW_PRINT_CLEAR` | 0x20 | `01` |
| `SET_LABEL_DENSITY` | 0x21 | 1 bayt, 1–5 |
| `SET_LABEL_TYPE` | 0x23 | 1 bayt, 1–3 (hep 1 gönderilir) |
| `GET_INFO` | 0x40 | 1 bayt, bilgi anahtarı |
| `IMAGE_ROW` | 0x85 | Satır verisi (§5.9) |
| `GET_PRINT_STATUS` | 0xA3 | `01` |
| `PRINTER_STATUS_DATA` | 0xA5 | `01` — NiimPrintX'te yok |
| `CONNECT` | 0xC1 | `01`, `03` önekiyle — NiimPrintX'te yok |
| `HEARTBEAT` | 0xDC | `01` |
| `END_PAGE_PRINT` | 0xE3 | `01` |
| `END_PRINT` | 0xF3 | `01` |

`GET_INFO` anahtarları:

| Anahtar | Değer | Çözüm |
|---|---|---|
| `DENSITY` | 1 | big-endian int |
| `PRINTSPEED` | 2 | int |
| `LABELTYPE` | 3 | int |
| `LANGUAGETYPE` | 6 | int |
| `AUTOSHUTDOWNTIME` | 7 | int |
| `DEVICETYPE` | 8 | int |
| `SOFTVERSION` | 9 | int / 100 |
| `BATTERY` | 10 | int |
| `DEVICESERIAL` | 11 | `data.hex()`. D110 bunu ASCII'nin hex'i olarak veriyor (`47423239323530303135` → `GB29250015`); yazdırılabilir ASCII'ye çözülebiliyorsa çöz |
| `HARDVERSION` | 12 | int / 100 |

### 5.5 HEARTBEAT cevabı

Alanlar, cevap verisinin **uzunluğuna** göre farklı yerlerde:

| `len(data)` | closing_state | power_level | paper_state | rfid_read_state |
|---|---|---|---|---|
| 20 | – | – | [18] | [19] |
| 19 | [15] | [16] | [17] | [18] |
| 13 | [9] | [10] | [11] | [12] |
| 10 | [8] | [9] | – | [8] |
| 9 | [8] | – | – | – |

`power_level` 0–4 ölçeğinde pil seviyesi. `len = 10` satırındaki
`rfid_read_state = [8]` NiimPrintX'teki hâliyle alındı; değiştirmeyin.

### 5.6 Protokol sürümü tespiti

Yeni firmware'ler (D110_M, D11_H, B21_PRO…) farklı bir baskı dizisi bekliyor ve
**eski diziyi sessizce kabul edip hiçbir şey basmıyor** (§5.11). Bu yüzden her
bağlantıda, baskıdan önce sürüm belirlenir ve bağlantı boyunca önbellekte tutulur:

```
r = send(CONNECT, 01)                   # 03 önekli paket
if r yok ya da boş: r = send(CONNECT, 01)   # ilk pakete cevap vermeyen firmware var
if r yok ya da boş: return 1

if r.data[0] == 3:                      # yeni firmware, sürümünü kendisi bildiriyor
    s = send(PRINTER_STATUS_DATA, 01)
    if s ve len(s.data) >= 13:
        fw = s.data[11] * 100 + s.data[12]
        204 <= fw < 300  → 3
        300 <= fw < 302  → 4            # D110_M, fw 301 → 4 (doğrulandı)
        fw >= 302        → 5
elif r.data[0] == 2:                    # yeni firmware, eski protokol
    return 1

belirlenemediyse → 1
```

Sürüm ≥ 4 ise §5.8 dizisi, değilse §5.7 dizisi kullanılır. Upstream karşılığı:
NiimPrintX PR #55 ve issue #32.

### 5.7 Baskı dizisi — v1 (eski firmware)

```
SET_LABEL_DENSITY(density)
SET_LABEL_TYPE(1)
START_PRINT(01)
START_PAGE_PRINT(01)
SET_DIMENSION(>HH: height, width)        # önce yükseklik (satır sayısı), sonra genişlik
SET_QUANTITY(>H: copies)
her satır: IMAGE_ROW (cevapsız) + 10 ms bekle
END_PAGE_PRINT(01)                       # data[0] true dönene kadar 50 ms arayla tekrarla
GET_PRINT_STATUS                         # page == copies olana kadar 100 ms arayla
END_PRINT(01)
```

v1 yolu NiimPrintX'ten olduğu gibi taşınıyor; eski firmware'li bir yazıcıyla doğrulanmadı.

### 5.8 Baskı dizisi — v4 (D110_M ve yeni firmware) — doğrulandı

```
SET_LABEL_TYPE(1)
SET_LABEL_DENSITY(density)
START_PRINT(>H7B: copies, 0, 0, 0, 0, 0, 1, 0)
    # 9 bayt: toplam sayfa, 4 ayrılmış bayt, sayfa rengi, hız, ayrılmış bayrak
write_no_notify(GET_PRINT_STATUS, 01)
    # YEM: yazıcı START_PRINT sonrasındaki ilk paketi yutuyor
SET_DIMENSION(>HHHHBBBH: height, width, copies, 0, 0, 0, 0, 0)
    # 13 bayt: satır, sütun, kopya, kesim yüksekliği, kesim tipi, ayrılmış,
    #          hepsini gönder, parça yüksekliği
her satır: IMAGE_ROW (cevapsız) + 10 ms bekle
END_PAGE_PRINT(01)
bekle: GET_PRINT_STATUS → page >= copies     # 100 ms arayla, 60 sn zaman aşımı;
                                             # cevapsız tur hata sayılmaz
END_PRINT(01)
write_no_notify(HEARTBEAT, 01)
    # YEM: END_PRINT sonrasındaki ilk paket de yutuluyor
```

v1'den farklar: `START_PAGE_PRINT` ve `SET_QUANTITY` **gönderilmez**; kopya
sayısı `START_PRINT` ve `SET_DIMENSION` içinde gider; iki yem paketi eklenir;
tür ve yoğunluk komutlarının sırası terstir. Alan adları upstream PR #55'ten
alındı. Değerleri değiştirmeyin.

### 5.9 Görsel kodlama (`IMAGE_ROW`)

```python
img = ImageOps.invert(image.convert("L")).convert("1")   # siyah piksel → bit 1 (basılır)
for y in range(img.height):
    bits   = "".join("0" if img.getpixel((x, y)) == 0 else "1" for x in range(img.width))
    row    = int(bits, 2).to_bytes(math.ceil(img.width / 8), "big")
    header = struct.pack(">H3BB", y, 0, 0, 0, 1)          # satır no, 3 sayaç (hep 0), 1
    yield Packet(0x85, header + row)
```

NiimPrintX'teki `vertical_offset` / `horizontal_offset` parametreleri
kullanılmıyor (hep 0); taşımayın.

### 5.10 Baskı durumu

`GET_PRINT_STATUS` cevabı `>HBB` biçiminde: `page`, `progress1`, `progress2`.
Cevap yoksa ya da 4 bayttan kısaysa o tur `None` sayılır ve beklemeye devam edilir.

### 5.11 Tuzaklar (hepsi donanımda yaşandı)

1. **"Yazıcı 01 dedi" hiçbir şey kanıtlamaz.** V4 yazıcıya v1 dizisi
   gönderildiğinde her komut `01` döner, ilerleme sayacı artar, sayfa sayılır,
   kağıt ilerler; ama etiket **bembeyaz** çıkar. Boş etiket görürseniz önce
   protokol sürümüne bakın.
2. **Döndürme 270:** saat yönünde 270°, yani saat yönünün tersine 90°.
   NiimPrintX README'sindeki `-r 90` bu yazıcıda etiketi 180° ters basıyor.
3. **Kenar payı 1.2 mm.** Bu, sunucu tarafındaki bir kural (§4.6).
4. **Yoğunluk sınırı:** d110 / d11 / d11_h / b18 en fazla 3; fazlası kırpılır.
5. **Pil:** Bu yazıcı pil 1/4 iken de temiz basıyor. Bu yüzden varsayılan olarak
   baskı engellenmez, yalnızca uyarı verilir (§7.2).
6. **Boş etiket teşhis sırası:**
   - (a) Yazıcının kendi test düğmesiyle çıktı alın. Çıktı gelmiyorsa sorun
     donanımda ya da ruloda. Termal yüzü bulmak için: tırnakla kazıyınca kararan
     yüz kafaya bakmalı.
   - (b) Protokol sürümünü kontrol edin.
   - (c) `--dry-run` ile giden PNG'nin dolu olduğunu doğrulayın.
   - (d) Yoğunluğa ve pile bakın.

### 5.12 Performans (D110, 40×12 mm, macOS ölçümü)

| Aşama | Süre |
|---|---|
| Yazıcıyı bulma | < 1 sn (ilk sefer); aynı oturumda yeniden bağlanırken tarama yok |
| Bağlanma | ~1 sn |
| Hazırlık (sürüm tespiti, baskı öncesi komutlar) | ~1.3 sn |
| Görsel gönderme (320 satır, yanıtsız + 10 ms) | ~3.6–3.8 sn |
| Baskı (END_PAGE_PRINT → sayfa bitti) | ~2.5 sn |

Bağlandıktan sonra etiket başına ~8 sn (niim-agent ve Chrome Web Bluetooth'ta
aynı). Satırlar yanıtlı yazıldığında gönderme ~19 sn sürüyordu (§5.2). Kopyalar
(`copies`) görseli yeniden göndermez; 5 kopya, 1 kopyadan belirgin şekilde uzun sürmez.

---

## 6. Görsel hazırlama (agent tarafı)

### 6.1 Model tablosu

| Model öneki | Kafa genişliği | Azami yoğunluk |
|---|---|---|
| `d110`, `d11`, `d11_h` | 240 px | 3 |
| `b18` | 384 px | 3 |
| `b1`, `b21` | 384 px | 5 |

Kaynak: NiimPrintX `cli/command.py`. Eski agent tüm modeller için 240 px
kullanıyordu; bu hatayı taşımayın.

### 6.2 `prepare_image(png_bytes, rotate, model) -> Image`

1. PNG'yi aç, `load()` çağır.
2. `rotate` 0 değilse `image.rotate(-rotate, expand=True)`. PIL saat yönünün
   tersine döndürür; eksi işaretiyle saat yönüne döner.
3. `image.width > kafa genişliği` ise `ValueError`, örn. "Görsel genişliği 320px; D110 için sınır 240px".
4. `convert("L")`.

Ayrıca `copies = max(1, copies)` ve `density = min(density or 3, modelin azami yoğunluğu)`.

### 6.3 Deneme etiketi

`test` komutu buluta gitmeden 320×96 px'lik (40×12 mm) bir etiket çizer: 2 px
çerçeve, "NIIM-AGENT" yazısı ve saat. Kenarlarda 1.2 mm (10 px) pay bırakır,
270° döndürüp basar.

---

## 7. Agent davranışı

### 7.1 Worker döngüsü

```python
async def worker():
    while not stopping:
        job = None
        if not printer_backoff_active():
            for src in sources.round_robin():         # her turda bir sonraki kaynaktan başla
                if src.in_backoff():
                    continue
                job = await src.claim(max=1)          # hata → kaynak backoff'a girer, None döner
                if job:
                    break
        if job is None:
            await session.close_if_idle()
            await asyncio.sleep(poll_interval)        # long-poll açıksa uyumaz (M6)
            continue
        await process(src, job)
```

`process(src, job)` adımları:

1. `prepare_image`. Hata verirse yazıcıya dokunmadan `failed` bildir.
2. `dry_run` açıksa PNG'yi `output_dir/<kaynak>-<id>.png` olarak kaydet ve `done` bildir.
3. Değilse `session.print_image(image, density, copies)`.
4. Başarılıysa `done`. İstisna olursa `failed` ve mesajı bildir, sonra
   `session.close()` çağır (bağlantı bozulmuş olabilir).
5. Hata `PrinterNotFound` ya da bir bağlantı hatasıysa **yazıcı backoff'u**
   başlar: 30 → 60 → 120 → en fazla 300 sn. Bu sürede **iş alınmaz**; yoksa
   yazıcı kapalıyken işlerin deneme hakları saniyeler içinde tükenir. İlk
   başarılı baskıda backoff sıfırlanır.
6. `state.json` içindeki `last_job` güncellenir.

Round-robin, dolu kuyruklu bir kaynağın diğerlerini aç bırakmasını önler.

### 7.2 PrinterSession

- Bağlantıyı işler arasında açık tutar. `idle_disconnect` süresi (90 sn) boyunca
  iş gelmezse kapatır. Yazıcı kendi kendine uykuya geçiyor; bağlantıyı asılı bırakmayın.
- Bu süreçte bulduğu cihazı hatırlar. Sonraki bağlantıda önce doğrudan o cihaza
  bağlanmayı dener; olmazsa yeniden tarar.
- Yazıcıya her erişim `self.lock` (`asyncio.Lock`) altında yapılır.
- `print_image`: `ensure()` → pil kontrolü → sürüm tespiti → baskı.
- **Pil kontrolü:** `HEARTBEAT` cevabından `power_level` okunur.
  - `min_battery > 0` ve `level <= min_battery` ise baskı başlamadan `LowBattery` hatası verilir.
  - `level <= 1` ise yalnızca uyarı loglanır.
  - Seviye okunamazsa baskıya devam edilir.
- `status()`: Yalnızca bağlıysa ve kilit boştaysa `HEARTBEAT` sorar. Bağlı
  değilse, sırf durum için yazıcıyı uyandırmaz. Kilit meşgulse son bilinen durumu döner.

### 7.3 Heartbeat görevi

Başlangıçta hemen, sonra her `heartbeat_interval` (60 sn) aralığında tüm etkin
kaynaklara §4.3 gönderilir. `note` alanında varsa son yazıcı ya da kaynak hatası
yer alır. Heartbeat hataları yalnızca loglanır; worker'ın kaynak backoff'unu
etkilemez. Her turda `state.json` da güncellenir.

### 7.4 Tek örnek kilidi

Aynı makinede iki agent aynı yazıcı için yarışmamalı. Bunun için
`<state>/agent.lock` dosyasına işletim sistemi kilidi konur: POSIX'te
`fcntl.flock`, Windows'ta `msvcrt.locking`.

- Kilit alınamazsa `run` "Agent zaten çalışıyor (pid X)" der ve 3 koduyla çıkar.
- Agent çalışırken `scan`, `info`, `test` ve `print` komutları reddedilir
  ("Önce agent'ı durdurun"), çünkü yazıcı aynı anda tek bağlantı kabul ediyor.
  M6'da bu komutlar yerel API üzerinden çalışan agent'a yönlendirilebilir.

### 7.5 Kapanış

- SIGINT / SIGTERM (Windows'ta Ctrl+C / Ctrl+Break) gelince:
  1. Yeni iş alınmaz.
  2. Baskı sürüyorsa bitmesi en fazla 60 sn beklenir ve sonucu bildirilir.
  3. BLE bağlantısı kapatılır, kilit bırakılır, 0 koduyla çıkılır.
- Windows'ta `loop.add_signal_handler` desteklenmez. `asyncio.run` çevresinde
  `KeyboardInterrupt` yakalayın ya da `signal.signal` kullanın.
- Oturum kapanır ya da süreç öldürülürse yarım kalan iş, sunucunun claim zaman
  aşımıyla kuyruğa döner.

### 7.6 İç gözetmen

`run`, ana görevleri bir döngü içinde çalıştırır. Beklenmeyen bir istisna
loglanır, 10 sn beklenir ve görevler yeniden kurulur; süreç ölmez. Windows'ta
çöken süreci yeniden başlatacak bir servis yöneticisi olmadığı için bu gerekli (§10.2).

---

## 8. Yapılandırma

Dosya konumları `platformdirs` ile belirlenir (`appname="niim-agent"`,
`appauthor=False`). Aşağıdaki yollar beklenen değerlerdir; esas olan
`platformdirs`'in döndürdüğüdür.

| | macOS | Windows |
|---|---|---|
| config | `~/Library/Application Support/niim-agent/config.toml` | `%LOCALAPPDATA%\niim-agent\config.toml` |
| log | `~/Library/Logs/niim-agent/agent.log` | `%LOCALAPPDATA%\niim-agent\Logs\agent.log` |
| state | `~/Library/Application Support/niim-agent/` | `%LOCALAPPDATA%\niim-agent\` |

Hangi config dosyasının kullanılacağı şu sırayla belirlenir: `--config` bayrağı,
sonra `NIIM_AGENT_CONFIG` ortam değişkeni, sonra varsayılan konum.

```toml
# niim-agent yapılandırması
agent_name = ""                   # boş = makine adı

[printer]
model = "d110"                    # d110 | d11 | d11_h | b1 | b18 | b21
address = ""                      # boş = ada göre tara (§5.3); dolu = doğrudan bağlan (platforma özel)
idle_disconnect = 90              # sn; iş gelmezse BLE bağlantısını kapat
min_battery = 0                   # 0 = engelleme yok; 1–4 = bu seviye ve altında basma

[agent]
poll_interval = 3                 # sn; iş yokken kaynak yoklama aralığı
heartbeat_interval = 60           # sn
dry_run = false                   # true = basma, PNG'yi output_dir'e yaz
output_dir = ""                   # boş = <state>/out

[[source]]
name = "atlantis"
url = "https://envanter.ornek.com/etiket/api"
token_env = "ATLANTIS_AGENT_TOKEN"    # jetonu ortam değişkeninden oku
enabled = true

[[source]]
name = "depo"
url = "https://depo.ornek.com/print-api"
token = "…"                           # ya da doğrudan
```

**Doğrulama** (`config check` ve `run` başlangıcında):
- En az bir etkin kaynak olmalı.
- Her kaynakta `url` ve bir jeton olmalı: `token`, ya da değeri dolu bir `token_env`.
- Kaynak adları (`name`) tekil olmalı.
- https kuralına uyulmalı (§4.5).
- Model bilinen bir model olmalı (§6.1).

Tüm hatalar kaynak adlarıyla birlikte tek listede gösterilir ve 2 koduyla çıkılır.

**Jeton güvenliği:** `config init`, dosyayı macOS'ta `0600` izniyle oluşturur.
Windows'ta `%LOCALAPPDATA%` zaten yalnızca o kullanıcıya açık. macOS Keychain ya
da Windows Credential Manager desteği kapsam dışı.

---

## 9. Komut satırı

| Komut | İş |
|---|---|
| `niim-agent run` | Servis döngüsü, ön planda; loglar hem konsola hem dosyaya |
| `niim-agent run --once` | Her kaynağı bir kez yokla, gelen işleri bas, çık |
| `niim-agent run --dry-run` | Basma, PNG'leri kaydet |
| `niim-agent scan` | Yakındaki BLE cihazlarını listele: ad, adres, RSSI, servis UUID sayısı |
| `niim-agent info` | Yazıcıya bağlan: seri no, yazılım/donanım sürümü, pil, protokol sürümü, heartbeat |
| `niim-agent test` | Deneme etiketi bas (§6.3) |
| `niim-agent print <png> [--rotate 270] [--density 3] [--copies 1]` | Dosyadan bas |
| `niim-agent install` / `uninstall` | Oturum açılışında arka planda başlatmayı kur / kaldır (§10) |
| `niim-agent status` | Kurulu mu, çalışıyor mu (kilit + `state.json` tazeliği), yazıcı, pil, kaynaklar, son iş |
| `niim-agent config init` / `path` / `check` | Şablon oluştur / dosya yolunu yaz / doğrula |
| `niim-agent logs [-f]` | Log dosyasının sonu; `-f` ile canlı takip |
| `niim-agent --version` | Sürüm |

Tüm komutlarda geçerli bayraklar:
- `-v` / `--verbose`: BLE paket loglarını (hex) DEBUG seviyesinde açar.
- `--config PATH`: config dosyasının yolunu verir.

Çıkış kodları: 0 başarı, 1 yazıcı ya da çalışma hatası, 2 yapılandırma hatası, 3 agent zaten çalışıyor.

`status` IPC gerektirmez. Çalışan agent her heartbeat'te ve her işten sonra
`state.json` dosyasını atomik olarak yazar (önce geçici dosyaya, sonra `os.replace`):

```json
{
  "version": "0.1.0", "pid": 1234,
  "started_at": "2026-09-24T09:00:00+03:00", "updated_at": "2026-09-24T09:41:00+03:00",
  "printer": {"connected": true, "name": "D110_M", "battery": 3, "protocol": 4, "last_error": ""},
  "sources": {"atlantis": {"ok": true, "last_error": "", "backoff_until": null}},
  "last_job": {"source": "atlantis", "id": 42, "status": "done", "at": "2026-09-24T09:40:12+03:00", "error": ""}
}
```

`updated_at`, heartbeat aralığının iki katından eskiyse `status` "yanıt vermiyor" der.

---

## 10. Arka planda çalışma

**Karar:** Agent her iki platformda da **kullanıcı oturumunda** çalışır, sistem
servisi olarak çalışmaz. Nedenleri:
- macOS'ta Bluetooth izni kullanıcıya bağlı.
- Windows'ta sistem servislerinin çalıştığı ortamdan (session 0) BLE erişimi
  güvenilir değil. Bu doğrulanmadı, ama oturum içinde çalışmak riski tamamen ortadan kaldırıyor.

Sonuç olarak kullanıcı oturum açmadan agent çalışmaz. Gerekirse o makinede
otomatik oturum açma etkinleştirilir.

### 10.1 macOS — LaunchAgent

`install`, `~/Library/LaunchAgents/com.niim-agent.plist` dosyasını yazar ve yükler:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
    <key>Label</key><string>com.niim-agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe}</string>          <!-- paketliyse .app içindeki ikili; değilse sys.executable -->
        <!-- paketli değilse ayrıca: <string>-m</string><string>niim_agent</string> -->
        <string>run</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
    <key>ThrottleInterval</key><integer>30</integer>
    <key>StandardOutPath</key><string>{log_dir}/launchd.out.log</string>
    <key>StandardErrorPath</key><string>{log_dir}/launchd.err.log</string>
</dict>
</plist>
```

- Yükleme: `launchctl bootstrap gui/$(id -u) <plist>`
- Kaldırma: `launchctl bootout gui/$(id -u)/com.niim-agent`
- Durum: `launchctl print gui/$(id -u)/com.niim-agent`
- Eski `load -w` / `unload -w` komutları da çalışır.

**Bluetooth izni (TCC):** macOS izni, programı başlatan uygulamaya bağlar.
Terminal'den çalıştırınca izin Terminal'e verilir; launchd altında izin istemi
hiç çıkmayabilir.
- **Paketsiz (geliştirme):** Önce `niim-agent scan` komutunu Terminal'den bir
  kez çalıştırıp izni verin, sonra `install` yapın.
- **Paketli (M5):** `Info.plist` içinde `NSBluetoothAlwaysUsageDescription`
  bulunan bir `.app` izni kendi adına ister. Kalıcı çözüm bu.

### 10.2 Windows — oturum açılışında başlatma

**Karar:** Yönetici yetkisi gerektirmeyen bir **HKCU Run** kaydı.

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
    "niim-agent" = "C:\…\niim-agent-bg.exe" run
```

- **Pencere yok:** Konsol penceresi açılmaması için kayıt, pencere açmayan
  ikiliyi çalıştırır. Paketliyse `niim-agent-bg.exe`, paketsizse `pythonw.exe -m niim_agent run`.
- **Çıktı yalnızca dosyaya:** Bu modda `sys.stdout` / `sys.stderr` `None`
  olabilir. Tüm çıktı dosya loguna gider; hiçbir kod doğrudan `print` ya da
  `sys.stderr.write` kullanmaz.
- **Yeniden başlatma yok:** Run kaydı çöken süreci yeniden başlatmaz. Bunu §7.6'daki iç gözetmen üstlenir.
- `install` agent'ı hemen de başlatır:
  `subprocess.Popen(..., creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW)`.
- `uninstall` kaydı siler ve kilidi tutan süreci sonlandırır (pid `state.json` içinde).
- **Alternatif:** Görev Zamanlayıcı'da "oturum açıldığında" tetikleyicisi ve
  "hata olursa yeniden başlat" ayarı. `schtasks /SC ONLOGON` genelde yönetici
  yetkisi istediği için yalnızca M4'te gerekirse eklenir.

**Gereksinimler:** Windows 10 1709 (build 16299) ya da üstü, veya Windows 11;
BLE destekli Bluetooth adaptörü; Bluetooth açık. Yazıcıyı Windows ayarlarından
eşleştirmek gerekmez; BLE GATT bağlantısı eşleştirme istemiyor.

### 10.3 Uyku ve ağ

Uyku, BLE ve ağ bağlantılarını düşürür. Uyanınca ilk yazıcı erişiminde
`ensure()` yeniden bağlanır; ağ hataları kaynak backoff'uyla toparlanır. Özel
bir kod gerekmez ama M4 donanım testinde denenir.

---

## 11. Bağımlılıklar, lisans, paketleme

### 11.1 Bağımlılıklar

| Paket | Neden |
|---|---|
| `bleak>=1.0,<4` | BLE (3.0.2 ile doğrulandı) |
| `Pillow` | Görsel işleme |
| `aiohttp` | Bulut istemcisi (async, long-poll) ve M6 yerel API sunucusu |
| `platformdirs` | Config / log / state yolları |

- **Standart kütüphane:** `tomllib`, `logging` (`RotatingFileHandler`, 5 MB × 3), `argparse`, `asyncio`.
- **Geliştirme:** `pytest`, `pytest-asyncio`, `ruff`, `pyinstaller`.
- NiimPrintX'in `loguru`, `rich`, `devtools`, `click`, `wand` ve `pycairo`
  bağımlılıkları **alınmaz**. Yazdırma yolunda hiçbiri gerekmiyor; `wand` ve
  `pycairo` ayrıca ImageMagick ve cairo sistem kütüphanelerini istiyor.

### 11.2 NiimPrintX kodunun alınması ve lisans

Alınacak dosyalar: `nimmy/packet.py`, `nimmy/bluetooth.py`, `nimmy/printer.py`
(toplam ~420 satır). Her dosyanın başına kaynak repo ve commit hash'i yazılır.
Taşırken yapılacaklar:

- `loguru` / `devtools` yerine standart `logging`
- `connect()`: `is_connected` kontrolü (§5.2)
- `find_device()` yerine §5.3
- `CONNECT` öneki paket sınıfının içinde; `CONNECT` ve `PRINTER_STATUS_DATA` enum'da
- `send_command` zaman aşımında istisna fırlatır (§5.2)
- Sürüm tespiti ve v4 dizisi (§5.6, §5.8)
- `__del__` kaldırılır: hiç bağlanmamış bir nesnede `AttributeError` fırlatıyor
- Offset parametreleri kaldırılır (§5.9)
- Model tablosu eklenir (§6.1)

**Karar: niim-agent GPL-3.0 lisanslı olur.** NiimPrintX GPL-3.0; türetilmiş kod
aynı lisansla dağıtılmalı. Şirket içinde kullanım serbest. Exe'yi şirket dışına
verirseniz kaynak kodunu da vermeniz gerekir. Bu kabul edilemezse protokol
katmanı temiz odada (clean-room) yeniden yazılmalı (§15).

### 11.3 Paketleme (PyInstaller, M5)

**Windows**
- Aynı giriş noktasından iki ikili üretilir:
  - `niim-agent.exe`: konsollu, terminal komutları için.
  - `niim-agent-bg.exe`: `console=False`, arka plan için.
- Başlangıç süresi için tek klasör (`onedir`) derlemesi tercih edilir; zip olarak dağıtılır.
- bleak'in WinRT paketleri için `--collect-all bleak` ile başlayın; gerekirse `winrt` paketlerini de ekleyin.
- İmzasız exe'de SmartScreen uyarısı çıkar.

**macOS**
- `niim-agent.app` (`windowed`) üretilir. `Info.plist` içine şunlar eklenir:
  - `NSBluetoothAlwaysUsageDescription` = "Etiket yazıcısına bağlanmak için Bluetooth gerekiyor."
  - `LSUIElement` = `true` (Dock simgesi yok)
  - `CFBundleIdentifier` = `com.niim-agent`
- Terminalden kullanım: `…/niim-agent.app/Contents/MacOS/niim-agent scan`. `install`, isteğe bağlı olarak `/usr/local/bin/niim-agent` sembolik bağlantısını önerir.
- En azından ad-hoc imza atılır: `codesign --force --deep -s - niim-agent.app`.
- TCC izni imzaya bağlıdır. Ad-hoc imza her derlemede değiştiği için güncellemeden sonra Bluetooth izni yeniden istenebilir. Kalıcı çözüm bir Developer ID imzası.

**Ortak**
- Sürüm tek yerde tutulur (`niim_agent/__init__.py` içindeki `__version__`); `pyproject.toml` onu dinamik okur.
- Geliştirme kurulumu: `pipx install -e .` ya da `uv tool install -e .`.

---

## 12. Test stratejisi

### 12.1 Birim testleri (donanımsız)

- **Paket:** kodlama, çözme, checksum, `CONNECT` öneki → Ek B vektörleri.
- **Görsel kodlama:** Ek B'deki satır vektörleri.
- **Sürüm tespiti** (sahte transport ile):
  - `CONNECT` → `3`, STATUS `data[11..12] = 3, 1` → 4
  - `CONNECT` → `2` → 1
  - İki kez cevapsız → 1
  - fw 250 → 3
  - fw 302 → 5
- **v1 / v4 dizileri:** `FakeTransport` yazılan tüm paketleri kaydeder. Test,
  beklenen sırayı ve baytları karşılaştırır: yem paketler var mı, v4'te
  `START_PAGE_PRINT` ve `SET_QUANTITY` yok mu.
- **Heartbeat çözümü:** §5.5'teki her uzunluk için.
- **`prepare_image`:** döndürme yönü (320×96 → 96×320), genişlik sınırı, model tablosu.
- **Yapılandırma:** varsayılanlar, doğrulama hataları, `token_env`.

### 12.2 Entegrasyon (sahte bulut sunucusu)

Bir `aiohttp` test sunucusu §4'ü bellekte bir kuyrukla uygular. Senaryolar:
- İş yok.
- Tek iş → `done`.
- Yazıcı hatası → `failed` ve mesajı.
- `403` / `503` → kaynak backoff'a girer, diğer kaynak çalışmaya devam eder.
- `409` → sonuç bırakılır.
- Ağ kesintisi → üstel backoff ve toparlanma.
- İki kaynak → round-robin.
- Yazıcı yokken iş alınmaması (§7.1, adım 5).
- `--once` ve `--dry-run`.

### 12.3 Donanım kontrol listesi (her platformda)

1. `scan` → `D110…` görünüyor; UUID sayısını not edin.
2. `info` → seri no, pil ve **protokol 4**.
3. `test` → dolu, doğru yönde, kenarları kesilmemiş bir etiket.
4. `print` → 40×12 ve 50×14 PNG.
5. Atlantis'e karşı `run --once` → admin'de iş "Yazdırıldı".
6. `copies=3` → üç etiket, tek aktarım.
7. Yazıcı kapalıyken iş → "bulunamadı" mesajıyla `failed`, yazıcı backoff'u
   başlıyor; yazıcı açılınca devam ediyor.
8. 90 sn boşta kalınca "bağlantı kapatıldı" logu; sonraki iş hızlıca yeniden bağlanıyor.
9. Uyku → uyanma → iş basılıyor.
10. `install` → oturumu kapatıp aç → `status` "çalışıyor".

---

## 13. Kilometre taşları

### M1 — Yazıcı çekirdeği ve yardımcı komutlar
- **İçerik:** `printer/` paketi (§5), `imaging.py`, CLI'da `scan` / `info` /
  `test` / `print`, logging, config'in `[printer]` bölümü.
- **Kabul:**
  - §12.1'deki paket, görsel, sürüm ve dizi testleri geçiyor.
  - macOS'ta §12.3 madde 1–4 tamam.
  - **Bir Windows PC varsa aynı 1–4 maddeleri Windows'ta da denenir.** En büyük
    bilinmeyen bu; erken görmek istiyoruz.

### M2 — Tek kaynakla servis döngüsü
- **İçerik:** `sources.py` (§4), worker ve heartbeat görevleri, `run`,
  `run --once`, `--dry-run`, `state.json`, tek örnek kilidi, kapanış.
- **Kabul:** §12.2'nin temel senaryoları geçiyor. Atlantis'e karşı §12.3 madde
  5–8 tamam (önce §14'ün 1. adımı yapılmalı).

### M3 — Çoklu kaynak ve dayanıklılık
- **İçerik:** round-robin, kaynak backoff tablosu (§4.4), yazıcı backoff'u,
  sonuç bildirme tekrarları, iç gözetmen, `status`, `config init` / `check`.
- **Kabul:** §12.2'nin tamamı geçiyor.

### M4 — Arka planda çalışma
- **İçerik:** macOS ve Windows için `install` / `uninstall` (§10).
- **Kabul:** İki platformda §12.3 madde 9–10 tamam. Windows'ta konsol penceresi açılmıyor, loglar dosyada.

### M5 — Paketler
- **İçerik:** PyInstaller yapılandırması, Windows'ta iki exe, macOS'ta `.app` ve
  `Info.plist`, README'de kurulum kılavuzu.
- **Kabul:**
  - Python kurulu olmayan temiz bir makinede: paketten kurulum → `install` →
    admin'den gönderilen etiket basılıyor.
  - macOS'ta Bluetooth izni launchd altında da isteniyor.

### M6 — İsteğe bağlı
- **Yerel API:** `127.0.0.1:8765` adresinde `POST /print` (gövde PNG; `rotate`,
  `density`, `copies` sorgu parametreleri) ve `GET /status`. Yalnızca localhost'u
  dinler. `local_api.token` doluysa `X-Agent-Token` ister. Yerel işler kuyruğa
  girer ve bulut işleriyle aynı worker'dan geçer.
- **Long-poll:** `wait` alanı; Atlantis tarafına da eklenir.
- **Sistem tepsisi simgesi** (`pystray`): durum, "deneme etiketi", "logları aç",
  "çık". Windows'ta tepsi kütüphanesi COM'u STA modunda başlatırsa bleak
  çalışmaz. Bunun için bleak'in `bleak.backends.winrt.util.allow_sta()` /
  `uninitialize_sta()` yardımcılarına bakın.

---

## 14. Atlantis Envanter tarafında yapılacaklar

1. **Sonuç ucu için takma ad.** Mevcut uç `api/is/<pk>/sonuc/`; protokol
   `jobs/{id}/result/` bekliyor. `labels/urls.py` dosyasına şu satır eklenir:
   ```python
   path('api/jobs/<int:pk>/result/', api.job_result, name='job_result_v1'),
   ```
   Eski uç, eski agent için bir süre kalır. Atlantis'in kaynak kökü `https://<alan>/etiket/api`.
2. **(M6) Long-poll:** `claim` ucuna `wait` desteği.
3. **(İsteğe bağlı) Hedef agent:** Birden fazla yazıcı ya da ofis olacaksa
   `PrintJob.target_agent` alanı eklenir. `claim` yalnızca
   `target_agent in ("", agent)` koşulunu sağlayan işleri verir.
4. **Geçiş:** Yeni agent M2 kabulünü geçince eski agent durdurulur
   (`launchctl unload -w ~/Library/LaunchAgents/com.atlantis.niimagent.plist`)
   ve `printagent/` klasörü repodan kaldırılır. **İki agent'ı aynı Mac'te aynı
   anda çalıştırmayın**; aynı yazıcı için BLE'de çakışırlar.

---

## 15. Açık kararlar ve riskler

| Konu | Durum / öneri |
|---|---|
| Windows'ta BLE | Hiç denenmedi. Keşif filtresi (§5.3) ve adaptör uyumluluğu belirsiz. M1'de ölçülecek |
| Lisans | Öneri GPL-3.0 (§11.2). Şirket dışına kapalı kaynak dağıtım gerekiyorsa protokol katmanı temiz odada yazılmalı. Bu büyük bir iş; karar M1'den önce verilmeli |
| macOS izinleri | Paketsizken launchd altında Bluetooth izni sorunlu. Ad-hoc imzada güncellemeden sonra izin yeniden isteniyor. Developer ID imzası ücretli |
| Windows'ta otomatik başlatma | HKCU Run seçildi (yetki gerektirmiyor); çökmeden sonra yeniden başlatma iç gözetmende. Yetersiz kalırsa Görev Zamanlayıcı |
| v1 protokol yolu | Eski firmware'li bir yazıcıyla hiç doğrulanmadı |
| Baskı hızı | Etiket başına ~8 sn (satırlar yanıtsız yazılınca; §5.12). Toplu işlerde beklenti buna göre kurulmalı |
| Oturum şartı | Agent, oturum açılmadan çalışmıyor. Gerekirse otomatik oturum açma, ya da Linux çalışan bir Raspberry Pi (systemd). İkisi de kapsam dışı |

---

## Ek A — Eski koddan yeni modüllere eşleme

| atlantis-envanter | niim-agent |
|---|---|
| `printagent/agent.py` → `load_config` | `config.py` (`.env` yerine TOML) |
| `printagent/agent.py` → `PrinterSession` | `printer/session.py` (+ kilit) |
| `printagent/agent.py` → `CloudClient` | `sources.py` (aiohttp, çoklu kaynak) |
| `printagent/agent.py` → `prepare_image`, `build_test_label` | `imaging.py` |
| `printagent/agent.py` → `handle_job`, `run_loop` | `agent.py` (worker) |
| `printagent/agent.py` → `cmd_*`, `main` | `cli.py` |
| `printagent/niim_compat.py` → `find_printer` | `printer/discovery.py` |
| `printagent/niim_compat.py` → `make_printer_class`, `negotiate_protocol`, `_print_image_v4` | `printer/client.py` |
| `printagent/niim_compat.py` → `_patch_connect_packet`, `_patch_request_codes` | Doğrudan `printer/packet.py` ve enum içinde |
| `printagent/com.atlantis.niimagent.plist` | `service/macos.py` (şablondan üretilir) |
| NiimPrintX `nimmy/*` | `printer/packet.py`, `printer/transport.py`, `printer/client.py` |

## Ek B — Test vektörleri

Bu baytlar, NiimPrintX'in `NiimbotPacket.to_bytes()` ve `_encode_image()` kodu
çalıştırılarak üretildi.

```
HEARTBEAT                        55 55 DC 01 01 DC AA AA
CONNECT (03 önekli)              03 55 55 C1 01 01 C1 AA AA
PRINTER_STATUS_DATA              55 55 A5 01 01 A5 AA AA
SET_LABEL_TYPE(1)                55 55 23 01 01 23 AA AA
SET_LABEL_DENSITY(3)             55 55 21 01 03 23 AA AA
GET_PRINT_STATUS                 55 55 A3 01 01 A3 AA AA
END_PAGE_PRINT                   55 55 E3 01 01 E3 AA AA
END_PRINT                        55 55 F3 01 01 F3 AA AA

v1 START_PRINT                   55 55 01 01 01 01 AA AA
v1 SET_DIMENSION(h=320, w=96)    55 55 13 04 01 40 00 60 36 AA AA

v4 START_PRINT copies=1          55 55 01 09 00 01 00 00 00 00 00 01 00 08 AA AA
v4 START_PRINT copies=3          55 55 01 09 00 03 00 00 00 00 00 01 00 0A AA AA
v4 SET_DIMENSION(h=320, w=96, copies=1)
                                 55 55 13 0D 01 40 00 60 00 01 00 00 00 00 00 00 00 3E AA AA

IMAGE_ROW — 16×2 px görsel; 0. satırın soldaki 8 pikseli siyah, 1. satır tamamen beyaz:
  satır 0                        55 55 85 08 00 00 00 00 00 01 FF 00 73 AA AA
  satır 1                        55 55 85 08 00 01 00 00 00 01 00 00 8D AA AA
```

40×12 mm bir etiket 270° döndürüldükten sonra yazıcıya 96 px genişlik × 320 px
yükseklik olarak gider. v4 `SET_DIMENSION` vektörü bu boyutlarla üretildi.
